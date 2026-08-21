#!/usr/bin/env python3
"""Fail-closed, one-time recovery for the interrupted v3.8.2 publication.

The immutable tag workflow built and validated the release artifacts, but its
pre-OIDC verifier rejected the normal setuptools ``.egg-info/PKG-INFO`` copy.
The publishing action was skipped.  This recovery keeps the tag and artifacts
immutable, binds every original identity explicitly, and only permits the same
bytes to be published from the repository's trusted ``release.yml`` workflow.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
    urlopen,
)

from v382_release_provenance import (
    GitHubAPI,
    ReleaseProvenanceError,
    load_attestation,
    require_fields,
    require_one_successful_job,
    require_pypi_absent,
    require_repository,
    require_sha,
    validate_distribution_set,
)


VERSION = "3.8.2"
TAG = "v3.8.2"
MODE = "v382_publish_recovery"
POSTPUBLISH_MODE = "v382_postpublish_resume"
QUALIFIED_SHA = "f94547a7c2faee1e3ea1b2a3e2c12aa5498b920c"
QUALIFIED_RUN_ID = 32485115821
CONTROLLER_RUN_ID = 32485555450
CONTROLLER_RUN_ATTEMPT = 1
ORIGINAL_RELEASE_RUN_ID = 32485582558
TAG_OBJECT_SHA = "8043b37572edf6aa3c40419f2e1ad385d6e3ae70"
REPOSITORY_ID = 1_275_110_431
RELEASE_WORKFLOW_ID = 314_388_312
CONTROLLER_WORKFLOW_ID = 339_384_559
ATTESTATION_ARTIFACT_ID = 9_447_710_482
ATTESTATION_ARTIFACT_NAME = (
    "v382-release-controller-attestation-32485555450-1"
)
ATTESTATION_ARTIFACT_DIGEST = (
    "sha256:c49a78c10990dd00f5dc156dde20d87d842cddbef0cbb659b571a720ac59b053"
)
ATTESTATION_ARTIFACT_SIZE = 411
ATTESTATION_FILE_SHA256 = (
    "a6fe26d4c7e0069c0a700646e42c7e382d17f77857ce916529d859159d786bbd"
)
ATTESTATION_FILE_SIZE = 354
ARTIFACT_ID = 9447848146
ARTIFACT_NAME = "staqtapp-tds-distributions"
ARTIFACT_DIGEST = (
    "sha256:3e48125ce996021251731ff51510c7b842a3cd5336ea1af5063812099db04579"
)
ARTIFACT_SIZE = 9_126_879
EXPECTED_DISTRIBUTION_IDENTITIES = {
    "staqtapp_tds-3.8.2-py3-none-any.whl": {
        "sha256": "a720e2cf8edf5676c9fdb5d49c5fe8325ecea470ace6f4d03d04d30bf04f8162",
        "size": 744_603,
    },
    "staqtapp_tds-3.8.2.tar.gz": {
        "sha256": "3101b5c2dde70aa4f01188194f7fdc4df0efdfa19537c9de94724ba0a2ac1ffd",
        "size": 8_401_104,
    },
}
RECOVERY_PATHS = frozenset(
    {
        ".github/workflows/release.yml",
        ".github/workflows/v382-release-controller.yml",
        "scripts/v382_release_provenance.py",
        "scripts/v382_release_recovery.py",
        "tests/test_v382_release_bridge.py",
    }
)
ORIGINAL_TAG_POLICY_ID = 54_814_185
ORIGINAL_JOB_IDS = {
    "Build and inspect distributions": 96_782_315_820,
    "Release gates complete": 96_782_448_570,
    "Verify exact v3.8.2 controller provenance before OIDC": 96_782_476_979,
    "Publish validated distributions to PyPI": 96_782_524_329,
    "Verify exact production PyPI publication": 96_784_615_419,
    "Require production smoke before publishing GitHub Release": 96_784_615_489,
}
QUALIFIED_GATE_JOB_ID = 96_781_116_299
CONTROLLER_JOB_IDS = {
    "Validate exact qualified source without a persisted token": 96_781_149_461,
    "Create exact annotated tag and dispatch exact tag run": 96_781_189_992,
}


class RecoveryGitHubAPI(GitHubAPI):
    """Small write-capable extension used only by the final recovery step."""

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, dict[str, Any] | None]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers={**self.headers, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                status = response.status
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
        if status not in expected:
            raise ReleaseProvenanceError(
                f"{method} {path} returned {status}: {raw[:500]!r}"
            )
        if not raw:
            return status, None
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReleaseProvenanceError(
                f"{method} {path} returned malformed JSON"
            ) from exc
        if not isinstance(result, dict):
            raise ReleaseProvenanceError(
                f"{method} {path} returned a non-object"
            )
        return status, result

    def get(self, path: str) -> dict[str, Any]:
        _, payload = self.request("GET", path)
        if payload is None:  # pragma: no cover - successful GitHub GETs have JSON
            raise ReleaseProvenanceError(f"GET {path} returned no object")
        return payload


def _require_exact_inputs(
    event: dict[str, Any],
    *,
    mode: str,
    release_run_id: str,
) -> None:
    expected = {
        "qualified_sha": QUALIFIED_SHA,
        "qualified_run_id": str(QUALIFIED_RUN_ID),
        "controller_run_id": str(CONTROLLER_RUN_ID),
        "controller_run_attempt": str(CONTROLLER_RUN_ATTEMPT),
        "mode": mode,
        "release_run_id": release_run_id,
    }
    if event.get("inputs") != expected:
        raise ReleaseProvenanceError("recovery workflow_dispatch inputs are not exact")


def _require_one_running_job(
    jobs: list[dict[str, Any]], name: str
) -> None:
    matches = [job for job in jobs if job.get("name") == name]
    if (
        len(matches) != 1
        or matches[0].get("status") != "in_progress"
        or matches[0].get("conclusion") is not None
    ):
        raise ReleaseProvenanceError(f"run lacks one running {name!r} job")


def _require_repo_identity(
    payload: dict[str, Any], repo: str, label: str
) -> None:
    require_repository(payload, repo, label)
    for key in ("repository", "head_repository"):
        if payload.get(key, {}).get("id") != REPOSITORY_ID:
            raise ReleaseProvenanceError(
                f"{label} has the wrong {key} numeric identity"
            )


def _require_exact_job(
    jobs: list[dict[str, Any]],
    name: str,
    *,
    job_id: int,
    conclusion: str,
) -> dict[str, Any]:
    matches = [job for job in jobs if job.get("name") == name]
    if (
        len(matches) != 1
        or matches[0].get("id") != job_id
        or matches[0].get("status") != "completed"
        or matches[0].get("conclusion") != conclusion
    ):
        raise ReleaseProvenanceError(
            f"run lacks exact {conclusion} job {name!r}"
        )
    return matches[0]


def _require_original_publish_failure(jobs: list[dict[str, Any]]) -> None:
    job = _require_exact_job(
        jobs,
        "Publish validated distributions to PyPI",
        job_id=ORIGINAL_JOB_IDS["Publish validated distributions to PyPI"],
        conclusion="failure",
    )
    required = {
        "Revalidate all publication proof immediately before OIDC": "failure",
        "Publish with PyPI trusted publishing": "skipped",
    }
    for name, conclusion in required.items():
        matches = [
            step
            for step in job.get("steps", [])
            if isinstance(step, dict) and step.get("name") == name
        ]
        step = matches[0] if len(matches) == 1 else None
        if (
            step is None
            or step.get("status") != "completed"
            or step.get("conclusion") != conclusion
        ):
            raise ReleaseProvenanceError(
                f"original publication step {name!r} is not exact"
            )


def _require_original_artifact(api: RecoveryGitHubAPI) -> None:
    artifact = api.get(f"/actions/artifacts/{ARTIFACT_ID}")
    require_fields(
        artifact,
        {
            "id": ARTIFACT_ID,
            "name": ARTIFACT_NAME,
            "size_in_bytes": ARTIFACT_SIZE,
            "digest": ARTIFACT_DIGEST,
            "expired": False,
        },
        "original distribution artifact",
    )
    if artifact.get("workflow_run", {}).get("id") != ORIGINAL_RELEASE_RUN_ID:
        raise ReleaseProvenanceError(
            "original distribution artifact belongs to the wrong run"
        )
    artifact_origin = artifact.get("workflow_run", {})
    if (
        artifact_origin.get("repository_id") != REPOSITORY_ID
        or artifact_origin.get("head_repository_id") != REPOSITORY_ID
        or artifact_origin.get("head_branch") != TAG
        or artifact_origin.get("head_sha") != QUALIFIED_SHA
    ):
        raise ReleaseProvenanceError(
            "original distribution artifact origin is not exact"
        )
    listing = api.get(
        f"/actions/runs/{ORIGINAL_RELEASE_RUN_ID}/artifacts?"
        f"name={quote(ARTIFACT_NAME, safe='')}&per_page=100"
    )
    matches = [
        item
        for item in listing.get("artifacts", [])
        if item.get("name") == ARTIFACT_NAME
    ]
    if (
        listing.get("total_count") != 1
        or len(matches) != 1
        or matches[0].get("id") != ARTIFACT_ID
        or matches[0].get("digest") != ARTIFACT_DIGEST
        or matches[0].get("expired") is not False
    ):
        raise ReleaseProvenanceError(
            "original distribution artifact listing is not exact"
        )


def _require_attestation_artifact(api: RecoveryGitHubAPI, root: Path) -> None:
    artifact = api.get(f"/actions/artifacts/{ATTESTATION_ARTIFACT_ID}")
    require_fields(
        artifact,
        {
            "id": ATTESTATION_ARTIFACT_ID,
            "name": ATTESTATION_ARTIFACT_NAME,
            "size_in_bytes": ATTESTATION_ARTIFACT_SIZE,
            "digest": ATTESTATION_ARTIFACT_DIGEST,
            "expired": False,
        },
        "controller attestation artifact",
    )
    origin = artifact.get("workflow_run", {})
    if (
        origin.get("id") != CONTROLLER_RUN_ID
        or origin.get("repository_id") != REPOSITORY_ID
        or origin.get("head_repository_id") != REPOSITORY_ID
        or origin.get("head_branch") != "main"
        or origin.get("head_sha") != QUALIFIED_SHA
    ):
        raise ReleaseProvenanceError(
            "controller attestation artifact origin is not exact"
        )
    listing = api.get(
        f"/actions/runs/{CONTROLLER_RUN_ID}/artifacts?"
        f"name={quote(ATTESTATION_ARTIFACT_NAME, safe='')}&per_page=100"
    )
    matches = [
        item
        for item in listing.get("artifacts", [])
        if item.get("name") == ATTESTATION_ARTIFACT_NAME
    ]
    if (
        listing.get("total_count") != 1
        or len(matches) != 1
        or matches[0].get("id") != ATTESTATION_ARTIFACT_ID
        or matches[0].get("digest") != ATTESTATION_ARTIFACT_DIGEST
        or matches[0].get("expired") is not False
    ):
        raise ReleaseProvenanceError(
            "controller attestation artifact listing is not exact"
        )
    path = root / "v382-release-controller-attestation.json"
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != ATTESTATION_FILE_SIZE
        or hashlib.sha256(path.read_bytes()).hexdigest()
        != ATTESTATION_FILE_SHA256
    ):
        raise ReleaseProvenanceError(
            "controller attestation file bytes are not exact"
        )


def _require_recovery_diff(
    api: RecoveryGitHubAPI, recovery_sha: str
) -> None:
    comparison = api.get(f"/compare/{QUALIFIED_SHA}...{recovery_sha}")
    if (
        comparison.get("status") != "ahead"
        or comparison.get("base_commit", {}).get("sha") != QUALIFIED_SHA
        or comparison.get("merge_base_commit", {}).get("sha") != QUALIFIED_SHA
        or comparison.get("ahead_by") != 1
        or comparison.get("behind_by") != 0
        or comparison.get("total_commits") != 1
    ):
        raise ReleaseProvenanceError(
            "recovery main is not an exact descendant of the release commit"
        )
    files = comparison.get("files")
    if not isinstance(files, list):
        raise ReleaseProvenanceError("recovery comparison lacks an exact file list")
    changed = {
        item.get("filename")
        for item in files
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    }
    if (
        len(files) != len(RECOVERY_PATHS)
        or changed != RECOVERY_PATHS
    ):
        raise ReleaseProvenanceError(
            f"recovery changed files outside the exact repair: {sorted(changed)!r}"
        )


def _require_distribution_identities(root: Path) -> None:
    actual = validate_distribution_set(root)
    if actual != EXPECTED_DISTRIBUTION_IDENTITIES:
        raise ReleaseProvenanceError(
            f"original distribution bytes changed: {actual!r}"
        )


def _require_pypi_absent_on_both_apis() -> None:
    require_pypi_absent()
    request = Request(
        "https://pypi.org/simple/staqtapp-tds/?v382-recovery-absence=1",
        headers={
            "Accept": "application/vnd.pypi.simple.v1+json",
            "Cache-Control": "no-cache",
            "User-Agent": "staqtapp-tds-v382-recovery-verifier",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            status = response.status
    except HTTPError as exc:
        raise ReleaseProvenanceError(
            f"PyPI Simple API absence check failed closed with HTTP {exc.code}"
        ) from exc
    if status != 200 or len(raw) > 8 * 1024 * 1024:
        raise ReleaseProvenanceError(
            "PyPI Simple API absence response is not bounded and exact"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseProvenanceError(
            "PyPI Simple API absence response is malformed"
        ) from exc
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        raise ReleaseProvenanceError("PyPI Simple API files field is malformed")
    visible = {
        item.get("filename")
        for item in files
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    }
    if set(EXPECTED_DISTRIBUTION_IDENTITIES) & visible:
        raise ReleaseProvenanceError(
            f"PyPI {VERSION} already exists in the Simple API; upload is prohibited"
        )


def _require_release_absent(api: RecoveryGitHubAPI) -> None:
    status, _ = api.request(
        "GET",
        f"/releases/tags/{quote(TAG, safe='')}",
        expected=(200, 404),
    )
    if status != 404:
        raise ReleaseProvenanceError(
            "v3.8.2 GitHub Release already exists; recovery re-entry is prohibited"
        )


def _require_temporary_main_environment_policy(
    api: RecoveryGitHubAPI,
) -> None:
    policies = api.get(
        "/environments/pypi/deployment-branch-policies?per_page=100"
    )
    entries = policies.get("branch_policies")
    if not isinstance(entries, list) or policies.get("total_count") != 2:
        raise ReleaseProvenanceError(
            "pypi environment must have exactly the permanent tag rule and "
            "temporary main rule"
        )
    normalized = {
        (item.get("name"), item.get("type")): item.get("id")
        for item in entries
        if isinstance(item, dict)
    }
    main_policy_id = normalized.get(("main", "branch"))
    if (
        len(normalized) != 2
        or normalized.get(("v*", "tag")) != ORIGINAL_TAG_POLICY_ID
        or isinstance(main_policy_id, bool)
        or not isinstance(main_policy_id, int)
        or main_policy_id <= 0
        or main_policy_id == ORIGINAL_TAG_POLICY_ID
    ):
        raise ReleaseProvenanceError(
            "pypi environment deployment policies are not the exact "
            "temporary recovery set"
        )


def _require_permanent_environment_policy(api: RecoveryGitHubAPI) -> None:
    policies = api.get(
        "/environments/pypi/deployment-branch-policies?per_page=100"
    )
    entries = policies.get("branch_policies")
    if (
        policies.get("total_count") != 1
        or not isinstance(entries, list)
        or len(entries) != 1
        or not isinstance(entries[0], dict)
        or entries[0].get("id") != ORIGINAL_TAG_POLICY_ID
        or entries[0].get("name") != "v*"
        or entries[0].get("type") != "tag"
    ):
        raise ReleaseProvenanceError(
            "no-upload finalization requires the restored sole v* policy"
        )


def _require_successful_publishing_recovery(
    api: RecoveryGitHubAPI,
    *,
    run_id: int,
    recovery_sha: str,
) -> None:
    run = api.get(f"/actions/runs/{run_id}")
    require_fields(
        run,
        {
            "id": run_id,
            "run_attempt": 1,
            "workflow_id": RELEASE_WORKFLOW_ID,
            "path": ".github/workflows/release.yml",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": recovery_sha,
            "status": "completed",
        },
        "publishing recovery run",
    )
    _require_repo_identity(run, api.repo, "publishing recovery run")
    if run.get("conclusion") not in {"failure", "cancelled", "timed_out"}:
        raise ReleaseProvenanceError(
            "publishing recovery run did not stop after publication"
        )
    jobs = api.jobs(run_id)
    for name in (
        "Release gates complete",
        "Verify one-time v3.8.2 recovery provenance before approval",
    ):
        require_one_successful_job(jobs, name)
    matches = [
        job
        for job in jobs
        if job.get("name") == "Publish validated distributions to PyPI"
    ]
    if (
        len(matches) != 1
        or matches[0].get("status") != "completed"
        or matches[0].get("conclusion") != "success"
    ):
        raise ReleaseProvenanceError(
            "publishing recovery lacks one successful publisher job"
        )
    steps = matches[0].get("steps")
    if not isinstance(steps, list):
        raise ReleaseProvenanceError("publishing recovery steps are missing")
    proof_name = "Revalidate all publication proof immediately before OIDC"
    publish_name = "Publish with PyPI trusted publishing"
    proof_indexes = [
        index
        for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("name") == proof_name
    ]
    publish_indexes = [
        index
        for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("name") == publish_name
    ]
    if (
        len(proof_indexes) != 1
        or len(publish_indexes) != 1
        or proof_indexes[0] + 1 != publish_indexes[0]
        or steps[proof_indexes[0]].get("status") != "completed"
        or steps[proof_indexes[0]].get("conclusion") != "success"
        or steps[publish_indexes[0]].get("status") != "completed"
        or steps[publish_indexes[0]].get("conclusion") != "success"
    ):
        raise ReleaseProvenanceError(
            "publishing recovery proof and Trusted Publisher steps are not exact"
        )


def verify_recovery_provenance(phase: str) -> RecoveryGitHubAPI:
    if phase not in {
        "preflight",
        "publish",
        "finalize",
        "postpublish-preflight",
        "postpublish-finalize",
    }:
        raise ReleaseProvenanceError(f"unsupported recovery phase: {phase!r}")
    postpublish = phase.startswith("postpublish-")
    expected_mode = POSTPUBLISH_MODE if postpublish else MODE
    env = os.environ
    if (
        env["GITHUB_EVENT_NAME"] != "workflow_dispatch"
        or env["RECOVERY_MODE"] != expected_mode
        or env["RECOVERY_REF"] != "refs/heads/main"
        or env["RECOVERY_REF_TYPE"] != "branch"
        or env["RECOVERY_REF_NAME"] != "main"
        or env["RECOVERY_RUN_ATTEMPT"] != "1"
        or env["QUALIFIED_SHA"] != QUALIFIED_SHA
        or env["QUALIFIED_RUN_ID"] != str(QUALIFIED_RUN_ID)
        or env["CONTROLLER_RUN_ID"] != str(CONTROLLER_RUN_ID)
        or env["CONTROLLER_RUN_ATTEMPT"] != str(CONTROLLER_RUN_ATTEMPT)
        or env["ORIGINAL_RELEASE_RUN_ID"] != str(ORIGINAL_RELEASE_RUN_ID)
    ):
        raise ReleaseProvenanceError("recovery environment identity is not exact")
    recovery_sha = require_sha(env["RECOVERY_SHA"], "recovery SHA")
    recovery_run_id = int(env["RECOVERY_RUN_ID"])
    if recovery_run_id <= 0:
        raise ReleaseProvenanceError("recovery run ID is not positive")
    event = json.loads(
        Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    published_recovery_run_text = env.get("PUBLISHED_RECOVERY_RUN_ID", "")
    if postpublish:
        published_recovery_run_id = int(published_recovery_run_text)
        if published_recovery_run_id <= 0:
            raise ReleaseProvenanceError(
                "published recovery run ID is not positive"
            )
    else:
        if published_recovery_run_text:
            raise ReleaseProvenanceError(
                "publishing recovery cannot name a prior publishing run"
            )
        published_recovery_run_id = 0
    _require_exact_inputs(
        event,
        mode=expected_mode,
        release_run_id=(
            published_recovery_run_text
            if postpublish
            else str(ORIGINAL_RELEASE_RUN_ID)
        ),
    )

    repo = env["GH_REPOSITORY"]
    api = RecoveryGitHubAPI(repo, env["GH_TOKEN"])
    current = api.get(f"/actions/runs/{recovery_run_id}")
    require_fields(
        current,
        {
            "id": recovery_run_id,
            "run_attempt": 1,
            "path": ".github/workflows/release.yml",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": recovery_sha,
            "status": "in_progress",
        },
        "current recovery run",
    )
    _require_repo_identity(current, repo, "current recovery run")
    workflow_id = current.get("workflow_id")
    if workflow_id != RELEASE_WORKFLOW_ID:
        raise ReleaseProvenanceError(
            "current recovery run has the wrong workflow ID"
        )

    main_ref = api.get("/git/ref/heads/main")
    if (
        main_ref.get("object", {}).get("type") != "commit"
        or main_ref.get("object", {}).get("sha") != recovery_sha
    ):
        raise ReleaseProvenanceError("main changed after recovery dispatch")
    _require_recovery_diff(api, recovery_sha)

    qualified = api.get(f"/actions/runs/{QUALIFIED_RUN_ID}")
    require_fields(
        qualified,
        {
            "id": QUALIFIED_RUN_ID,
            "workflow_id": workflow_id,
            "path": ".github/workflows/release.yml",
            "event": "push",
            "head_branch": "main",
            "head_sha": QUALIFIED_SHA,
            "status": "completed",
            "conclusion": "success",
        },
        "qualified main run",
    )
    _require_repo_identity(qualified, repo, "qualified main run")
    _require_exact_job(
        api.jobs(QUALIFIED_RUN_ID),
        "Release gates complete",
        job_id=QUALIFIED_GATE_JOB_ID,
        conclusion="success",
    )

    controller = api.get(f"/actions/runs/{CONTROLLER_RUN_ID}")
    require_fields(
        controller,
        {
            "id": CONTROLLER_RUN_ID,
            "run_attempt": CONTROLLER_RUN_ATTEMPT,
            "workflow_id": CONTROLLER_WORKFLOW_ID,
            "path": ".github/workflows/v382-release-controller.yml",
            "event": "workflow_run",
            "head_branch": "main",
            "head_sha": QUALIFIED_SHA,
            "status": "completed",
            "conclusion": "success",
        },
        "controller run",
    )
    _require_repo_identity(controller, repo, "controller run")
    controller_jobs = api.jobs(CONTROLLER_RUN_ID)
    _require_exact_job(
        controller_jobs,
        "Validate exact qualified source without a persisted token",
        job_id=CONTROLLER_JOB_IDS[
            "Validate exact qualified source without a persisted token"
        ],
        conclusion="success",
    )
    _require_exact_job(
        controller_jobs,
        "Create exact annotated tag and dispatch exact tag run",
        job_id=CONTROLLER_JOB_IDS[
            "Create exact annotated tag and dispatch exact tag run"
        ],
        conclusion="success",
    )

    original = api.get(f"/actions/runs/{ORIGINAL_RELEASE_RUN_ID}")
    require_fields(
        original,
        {
            "id": ORIGINAL_RELEASE_RUN_ID,
            "run_attempt": 1,
            "workflow_id": workflow_id,
            "path": ".github/workflows/release.yml",
            "event": "workflow_dispatch",
            "head_branch": TAG,
            "head_sha": QUALIFIED_SHA,
            "status": "completed",
            "conclusion": "failure",
        },
        "original tag release run",
    )
    _require_repo_identity(original, repo, "original tag release run")
    original_jobs = api.jobs(ORIGINAL_RELEASE_RUN_ID)
    for name in (
        "Build and inspect distributions",
        "Release gates complete",
        "Verify exact v3.8.2 controller provenance before OIDC",
    ):
        _require_exact_job(
            original_jobs,
            name,
            job_id=ORIGINAL_JOB_IDS[name],
            conclusion="success",
        )
    _require_original_publish_failure(original_jobs)
    for name in (
        "Verify exact production PyPI publication",
        "Require production smoke before publishing GitHub Release",
    ):
        _require_exact_job(
            original_jobs,
            name,
            job_id=ORIGINAL_JOB_IDS[name],
            conclusion="skipped",
        )

    attestation_root = Path(env["CONTROLLER_ATTESTATION_DIR"])
    _require_attestation_artifact(api, attestation_root)
    attestation = load_attestation(
        attestation_root,
        repo=repo,
        controller_run_id=CONTROLLER_RUN_ID,
        controller_run_attempt=CONTROLLER_RUN_ATTEMPT,
        release_run_id=ORIGINAL_RELEASE_RUN_ID,
        qualified_run_id=QUALIFIED_RUN_ID,
        qualified_sha=QUALIFIED_SHA,
        tag=TAG,
    )
    if attestation.get("tag_object_sha") != TAG_OBJECT_SHA:
        raise ReleaseProvenanceError("controller tag object identity changed")
    _require_original_artifact(api)

    tag_ref = api.get(f"/git/ref/tags/{quote(TAG, safe='')}")
    if (
        tag_ref.get("object", {}).get("type") != "tag"
        or tag_ref.get("object", {}).get("sha") != TAG_OBJECT_SHA
    ):
        raise ReleaseProvenanceError("annotated v3.8.2 tag reference changed")
    tag_object = api.get(f"/git/tags/{TAG_OBJECT_SHA}")
    if (
        tag_object.get("sha") != TAG_OBJECT_SHA
        or tag_object.get("tag") != TAG
        or tag_object.get("object", {}).get("type") != "commit"
        or tag_object.get("object", {}).get("sha") != QUALIFIED_SHA
    ):
        raise ReleaseProvenanceError("annotated v3.8.2 tag target changed")

    _require_distribution_identities(Path(env["DISTRIBUTION_DIR"]))
    recovery_jobs = api.jobs(recovery_run_id)
    if postpublish:
        _require_permanent_environment_policy(api)
        if published_recovery_run_id == recovery_run_id:
            raise ReleaseProvenanceError(
                "postpublication run cannot attest itself as the publisher"
            )
        _require_successful_publishing_recovery(
            api,
            run_id=published_recovery_run_id,
            recovery_sha=recovery_sha,
        )
    else:
        _require_temporary_main_environment_policy(api)
        require_one_successful_job(recovery_jobs, "Release gates complete")
        if phase == "preflight":
            _require_one_running_job(
                recovery_jobs,
                "Verify one-time v3.8.2 recovery provenance before approval",
            )
        else:
            require_one_successful_job(
                recovery_jobs,
                "Verify one-time v3.8.2 recovery provenance before approval",
            )
        if phase == "publish":
            _require_one_running_job(
                recovery_jobs,
                "Publish validated distributions to PyPI",
            )
        if phase == "finalize":
            for name in (
                "Publish validated distributions to PyPI",
                "Verify exact v3.8.2 recovery publication",
                "v3.8.2 recovery PyPI smoke complete",
            ):
                require_one_successful_job(recovery_jobs, name)
            _require_one_running_job(
                recovery_jobs,
                "Publish the recovered v3.8.2 GitHub Release",
            )
    if phase == "postpublish-preflight":
        _require_one_running_job(
            recovery_jobs,
            "Verify already-published v3.8.2 recovery provenance",
        )
    if phase == "postpublish-finalize":
        for name in (
            "Verify already-published v3.8.2 recovery provenance",
            "Verify exact already-published v3.8.2 distributions",
            "v3.8.2 no-upload finalization smoke complete",
        ):
            require_one_successful_job(recovery_jobs, name)
        _require_one_running_job(
            recovery_jobs,
            "Publish the resumed v3.8.2 GitHub Release",
        )
    _require_release_absent(api)
    if postpublish:
        verify_public_distribution_set(attempts=6)
    elif phase != "finalize":
        _require_pypi_absent_on_both_apis()
    return api


def _require_public_file_url(value: str, name: str):
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "files.pythonhosted.org"
        or parsed.query
        or parsed.fragment
        or unquote(parsed.path.rsplit("/", 1)[-1]) != name
    ):
        raise ReleaseProvenanceError(
            f"unsafe PyPI distribution URL for {name}: {value!r}"
        )
    return parsed


class _ConstrainedRedirect(HTTPRedirectHandler):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_public_file_url(newurl, self.name)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verify_public_distribution_set(*, attempts: int = 30) -> None:
    if attempts <= 0:
        raise ValueError("attempts must be positive")
    url = f"https://pypi.org/pypi/staqtapp-tds/{VERSION}/json"
    last = "not visible"
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "User-Agent": "staqtapp-tds-v382-recovery-verifier",
                },
            )
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code not in {404, 429} and exc.code < 500:
                raise
            payload = None
            last = f"HTTP {exc.code}"
        except URLError as exc:
            payload = None
            last = repr(exc)
        if payload is not None:
            if payload.get("info", {}).get("version") != VERSION:
                raise ReleaseProvenanceError(
                    "PyPI returned an unexpected release identity"
                )
            urls = payload.get("urls")
            if not isinstance(urls, list):
                raise ReleaseProvenanceError("PyPI urls field is not a list")
            remote: dict[str, dict[str, Any]] = {}
            for item in urls:
                if not isinstance(item, dict):
                    raise ReleaseProvenanceError(
                        "PyPI distribution entry is not an object"
                    )
                filename = item.get("filename")
                if not isinstance(filename, str) or filename in remote:
                    raise ReleaseProvenanceError(
                        "PyPI distribution filename set is ambiguous"
                    )
                remote[filename] = item
            if set(remote) - set(EXPECTED_DISTRIBUTION_IDENTITIES):
                raise ReleaseProvenanceError(
                    f"PyPI exposed unexpected artifacts: {sorted(remote)!r}"
                )
            for name, item in remote.items():
                expected = EXPECTED_DISTRIBUTION_IDENTITIES[name]
                identity = {
                    "sha256": item.get("digests", {}).get("sha256"),
                    "size": item.get("size"),
                }
                if identity != expected:
                    raise ReleaseProvenanceError(
                        f"PyPI JSON identity mismatch for {name}: {identity!r}"
                    )
            if set(remote) == set(EXPECTED_DISTRIBUTION_IDENTITIES):
                for name, item in remote.items():
                    expected = EXPECTED_DISTRIBUTION_IDENTITIES[name]
                    expected_type = (
                        "bdist_wheel" if name.endswith(".whl") else "sdist"
                    )
                    if item.get("packagetype") != expected_type or item.get("yanked"):
                        raise ReleaseProvenanceError(
                            f"PyPI type or yank state is wrong for {name}"
                        )
                    raw_url = item.get("url")
                    if not isinstance(raw_url, str):
                        raise ReleaseProvenanceError(
                            f"PyPI distribution URL is missing for {name}"
                        )
                    _require_public_file_url(raw_url, name)
                    opener = build_opener(_ConstrainedRedirect(name))
                    request = Request(
                        raw_url,
                        headers={
                            "Accept": "application/octet-stream",
                            "Cache-Control": "no-cache",
                            "User-Agent": (
                                "staqtapp-tds-v382-recovery-verifier"
                            ),
                        },
                    )
                    digest = hashlib.sha256()
                    size = 0
                    with opener.open(request, timeout=60) as response:
                        _require_public_file_url(response.geturl(), name)
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > expected["size"]:
                                raise ReleaseProvenanceError(
                                    f"public {name} exceeds expected size"
                                )
                            digest.update(chunk)
                    public_identity = {
                        "sha256": digest.hexdigest(),
                        "size": size,
                    }
                    if public_identity != expected:
                        raise ReleaseProvenanceError(
                            f"downloaded public bytes mismatch for {name}: "
                            f"{public_identity!r}"
                        )
                print(
                    json.dumps(
                        {
                            "version": VERSION,
                            "artifacts": EXPECTED_DISTRIBUTION_IDENTITIES,
                        },
                        sort_keys=True,
                    )
                )
                return
            last = f"only visible: {sorted(remote)!r}"
        if attempt + 1 < attempts:
            time.sleep(10)
    raise ReleaseProvenanceError(
        f"PyPI did not expose the exact artifact set: {last}"
    )


def finalize_github_release(api: RecoveryGitHubAPI) -> None:
    verify_public_distribution_set(attempts=6)
    recovery_sha = require_sha(os.environ["RECOVERY_SHA"], "recovery SHA")
    main_ref = api.get("/git/ref/heads/main")
    if (
        main_ref.get("object", {}).get("type") != "commit"
        or main_ref.get("object", {}).get("sha") != recovery_sha
    ):
        raise ReleaseProvenanceError("main changed during public verification")
    tag_ref = api.get(f"/git/ref/tags/{quote(TAG, safe='')}")
    if (
        tag_ref.get("object", {}).get("type") != "tag"
        or tag_ref.get("object", {}).get("sha") != TAG_OBJECT_SHA
    ):
        raise ReleaseProvenanceError("v3.8.2 tag changed during recovery")
    tag_object = api.get(f"/git/tags/{TAG_OBJECT_SHA}")
    if (
        tag_object.get("tag") != TAG
        or tag_object.get("object", {}).get("type") != "commit"
        or tag_object.get("object", {}).get("sha") != QUALIFIED_SHA
    ):
        raise ReleaseProvenanceError("v3.8.2 tag target changed during recovery")
    if os.environ["RECOVERY_MODE"] == POSTPUBLISH_MODE:
        _require_permanent_environment_policy(api)
    else:
        _require_temporary_main_environment_policy(api)
    _require_release_absent(api)
    body = (
        "Production wheel and source distribution for `v3.8.2` were "
        "hash-verified against the immutable tag-workflow artifact. The "
        "original trusted-publishing action was skipped after a pre-OIDC "
        "metadata-path false positive; the corrected, fully qualified "
        "one-time recovery then passed public PyPI verification and "
        "cross-platform installation smoke tests before this Release was "
        "published.\n\n"
        "- PyPI: https://pypi.org/project/staqtapp-tds/3.8.2/\n"
        "- Performance evidence: "
        "https://github.com/lastforkbender/staqtapp-tds/blob/v3.8.2/docs/"
        "135_v382_System_Performance_Corrections.md"
    )
    _, release = api.request(
        "POST",
        "/releases",
        {
            "tag_name": TAG,
            "target_commitish": QUALIFIED_SHA,
            "name": f"Staqtapp-TDS {TAG}",
            "body": body,
            "draft": False,
            "prerelease": False,
            "generate_release_notes": True,
            "make_latest": "true",
        },
        expected=(201,),
    )
    if (
        release is None
        or release.get("tag_name") != TAG
        or release.get("draft") is not False
        or release.get("prerelease") is not False
    ):
        raise ReleaseProvenanceError(
            "GitHub returned an unexpected recovered Release identity"
        )
    print(f"GitHub Release published: {release.get('html_url')}")


def main() -> int:
    if len(os.sys.argv) != 2 or os.sys.argv[1] not in {
        "preflight",
        "publish",
        "verify-public",
        "finalize",
        "postpublish-preflight",
        "postpublish-finalize",
    }:
        print(
            "usage: v382_release_recovery.py "
            "{preflight|publish|verify-public|finalize|"
            "postpublish-preflight|postpublish-finalize}",
            file=os.sys.stderr,
        )
        return 2
    command = os.sys.argv[1]
    try:
        if command == "verify-public":
            _require_distribution_identities(Path(os.environ["DISTRIBUTION_DIR"]))
            verify_public_distribution_set()
        else:
            api = verify_recovery_provenance(command)
            if command in {"finalize", "postpublish-finalize"}:
                finalize_github_release(api)
    except (
        HTTPError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        ReleaseProvenanceError,
    ) as exc:
        print(f"v3.8.2 recovery failed closed: {exc}", file=os.sys.stderr)
        return 1
    print(f"v3.8.2 recovery {command} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

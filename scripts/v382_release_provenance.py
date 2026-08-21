#!/usr/bin/env python3
"""Fail-closed v3.8.2 proof immediately before Trusted Publishing.

This verifier is intentionally release-specific.  It binds the running tag
workflow to the immutable one-time-controller artifact, the successful main
qualification, the annotated tag object, the current main head, the exact
distribution artifact, and production-PyPI absence.  Any ambiguity is fatal.
"""
from __future__ import annotations

import email.parser
import email.policy
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile

from release_version import read_source_version, validate_tag


VERSION = "3.8.2"
TAG = "v3.8.2"
ATTESTATION_SCHEMA = "staqtapp-tds/v382-release-controller-attestation-1"
ATTESTATION_FILENAME = "v382-release-controller-attestation.json"
EXPECTED_DISTRIBUTIONS = frozenset(
    {
        "staqtapp_tds-3.8.2-py3-none-any.whl",
        "staqtapp_tds-3.8.2.tar.gz",
    }
)
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")


class ReleaseProvenanceError(RuntimeError):
    """Raised when publication proof is missing, stale, or ambiguous."""


def require_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise ReleaseProvenanceError(f"{label} is not an exact commit SHA")
    return value


def positive_integer(value: str, label: str) -> int:
    if not isinstance(value, str) or not POSITIVE_INTEGER_PATTERN.fullmatch(value):
        raise ReleaseProvenanceError(f"{label} is not an exact positive integer")
    return int(value)


def require_repository(run: dict[str, Any], repo: str, label: str) -> None:
    for key in ("repository", "head_repository"):
        if run.get(key, {}).get("full_name") != repo:
            raise ReleaseProvenanceError(
                f"{label} has the wrong {key} provenance"
            )


def require_fields(
    payload: dict[str, Any], expected: dict[str, Any], label: str
) -> None:
    for key, value in expected.items():
        actual = payload.get(key)
        if (
            type(value) is int and type(actual) is not int
        ) or actual != value:
            raise ReleaseProvenanceError(
                f"{label} mismatch for {key}: {actual!r}"
            )


def load_attestation(
    root: Path,
    *,
    repo: str,
    controller_run_id: int,
    controller_run_attempt: int,
    release_run_id: int,
    qualified_run_id: int,
    qualified_sha: str,
    tag: str,
) -> dict[str, Any]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    )
    expected_path = root / ATTESTATION_FILENAME
    if (
        files != [expected_path]
        or expected_path.is_symlink()
        or expected_path.stat().st_size > 16_384
    ):
        raise ReleaseProvenanceError(
            "controller attestation artifact must contain exactly one regular file"
        )
    try:
        payload = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseProvenanceError("controller attestation is unreadable") from exc
    required_keys = {
        "schema",
        "repo",
        "controller_run_id",
        "controller_run_attempt",
        "release_run_id",
        "qualified_run_id",
        "qualified_sha",
        "tag",
        "tag_object_sha",
    }
    if not isinstance(payload, dict) or set(payload) != required_keys:
        raise ReleaseProvenanceError("controller attestation keys are not exact")
    integer_keys = {
        "controller_run_id",
        "controller_run_attempt",
        "release_run_id",
        "qualified_run_id",
    }
    if any(
        type(payload.get(key)) is not int or payload[key] <= 0
        for key in integer_keys
    ):
        raise ReleaseProvenanceError(
            "controller attestation run identities are not exact integers"
        )
    tag_object_sha = require_sha(payload.get("tag_object_sha"), "tag object SHA")
    expected = {
        "schema": ATTESTATION_SCHEMA,
        "repo": repo,
        "controller_run_id": controller_run_id,
        "controller_run_attempt": controller_run_attempt,
        "release_run_id": release_run_id,
        "qualified_run_id": qualified_run_id,
        "qualified_sha": qualified_sha,
        "tag": tag,
        "tag_object_sha": tag_object_sha,
    }
    if payload != expected:
        raise ReleaseProvenanceError(
            "controller attestation does not authorize this release run"
        )
    return payload


def _metadata_identity(data: bytes, label: str) -> None:
    try:
        metadata = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            data
        )
    except Exception as exc:  # pragma: no cover - parser failures are uncommon
        raise ReleaseProvenanceError(f"cannot parse {label} metadata") from exc
    if metadata.get("Name") != "staqtapp-tds" or metadata.get("Version") != VERSION:
        raise ReleaseProvenanceError(f"{label} package identity is not exact")


def validate_distribution_set(root: Path) -> dict[str, dict[str, int | str]]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    )
    if (
        {path.name for path in files} != EXPECTED_DISTRIBUTIONS
        or len(files) != 2
        or any(path.parent != root or path.is_symlink() for path in files)
    ):
        raise ReleaseProvenanceError(
            "distribution artifact must contain exactly the v3.8.2 wheel and sdist"
        )
    by_name = {path.name: path for path in files}
    wheel = by_name["staqtapp_tds-3.8.2-py3-none-any.whl"]
    sdist = by_name["staqtapp_tds-3.8.2.tar.gz"]
    if not zipfile.is_zipfile(wheel):
        raise ReleaseProvenanceError("wheel is not a valid ZIP distribution")
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if metadata_names != ["staqtapp_tds-3.8.2.dist-info/METADATA"]:
            raise ReleaseProvenanceError("wheel metadata path is not exact")
        _metadata_identity(archive.read(metadata_names[0]), "wheel")
    try:
        with tarfile.open(sdist, mode="r:gz") as archive:
            expected_metadata_names = {
                "staqtapp_tds-3.8.2/PKG-INFO",
                (
                    "staqtapp_tds-3.8.2/src/"
                    "staqtapp_tds.egg-info/PKG-INFO"
                ),
            }
            metadata_members = [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.endswith("/PKG-INFO")
            ]
            if (
                len(metadata_members) != len(expected_metadata_names)
                or {member.name for member in metadata_members}
                != expected_metadata_names
            ):
                raise ReleaseProvenanceError("sdist metadata path is not exact")
            metadata_payloads = []
            for member in metadata_members:
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ReleaseProvenanceError("sdist metadata is unreadable")
                payload = extracted.read()
                _metadata_identity(payload, f"sdist {member.name}")
                metadata_payloads.append(payload)
            if metadata_payloads[0] != metadata_payloads[1]:
                raise ReleaseProvenanceError("sdist metadata copies differ")
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseProvenanceError("sdist is not a valid gzip tarball") from exc
    return {
        path.name: {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for path in files
    }


class GitHubAPI:
    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.base = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "staqtapp-tds-v382-pre-oidc-verifier",
        }

    def get(self, path: str) -> dict[str, Any]:
        request = Request(self.base + path, method="GET", headers=self.headers)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                status = response.status
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
        if status != 200:
            raise ReleaseProvenanceError(
                f"GET {path} returned {status}: {raw[:500]!r}"
            )
        payload = json.loads(raw) if raw else None
        if not isinstance(payload, dict):
            raise ReleaseProvenanceError(f"GET {path} returned a non-object")
        return payload

    def jobs(self, run_id: int) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.get(
                f"/actions/runs/{run_id}/jobs?"
                f"filter=latest&per_page=100&page={page}"
            )
            jobs = payload.get("jobs")
            if not isinstance(jobs, list):
                raise ReleaseProvenanceError("GitHub job list is malformed")
            seen.extend(jobs)
            if len(seen) >= int(payload.get("total_count", 0)):
                return seen
            page += 1
            if page > 10:
                raise ReleaseProvenanceError("GitHub job list exceeded safety bound")

    def require_artifact(self, run_id: int, name: str) -> None:
        payload = self.get(
            f"/actions/runs/{run_id}/artifacts?"
            f"name={quote(name, safe='')}&per_page=100"
        )
        artifacts = [
            artifact
            for artifact in payload.get("artifacts", [])
            if artifact.get("name") == name
        ]
        if (
            payload.get("total_count") != 1
            or len(artifacts) != 1
            or artifacts[0].get("expired") is not False
            or artifacts[0].get("workflow_run", {}).get("id") != run_id
        ):
            raise ReleaseProvenanceError(
                f"exact immutable artifact {name!r} is unavailable"
            )


def require_one_successful_job(
    jobs: list[dict[str, Any]], name: str
) -> None:
    matches = [job for job in jobs if job.get("name") == name]
    if (
        len(matches) != 1
        or matches[0].get("status") != "completed"
        or matches[0].get("conclusion") != "success"
    ):
        raise ReleaseProvenanceError(
            f"run lacks one successful {name!r} job"
        )


def require_pypi_absent() -> None:
    request = Request(
        f"https://pypi.org/pypi/staqtapp-tds/{VERSION}/json",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "staqtapp-tds-v382-pre-oidc-verifier",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            response.read(1)
            status = response.status
    except HTTPError as exc:
        if exc.code == 404:
            return
        raise ReleaseProvenanceError(
            f"PyPI absence check failed closed with HTTP {exc.code}"
        ) from exc
    raise ReleaseProvenanceError(
        f"PyPI {VERSION} already exists (HTTP {status}); upload is prohibited"
    )


def verify_from_environment() -> dict[str, dict[str, int | str]]:
    env = os.environ
    repo = env["GH_REPOSITORY"]
    token = env["GH_TOKEN"]
    tag = env["RELEASE_TAG"]
    release_ref = env["RELEASE_REF"]
    qualified_sha = require_sha(env["QUALIFIED_SHA"], "qualified SHA")
    release_sha = require_sha(env["RELEASE_SHA"], "release SHA")
    release_run_id = positive_integer(env["RELEASE_RUN_ID"], "release run ID")
    release_run_attempt = positive_integer(
        env["RELEASE_RUN_ATTEMPT"], "release run attempt"
    )
    qualified_run_id = positive_integer(
        env["QUALIFIED_RUN_ID"], "qualified run ID"
    )
    controller_run_id = positive_integer(
        env["CONTROLLER_RUN_ID"], "controller run ID"
    )
    controller_run_attempt = positive_integer(
        env["CONTROLLER_RUN_ATTEMPT"], "controller run attempt"
    )
    if (
        tag != TAG
        or release_ref != f"refs/tags/{TAG}"
        or release_sha != qualified_sha
        or release_run_attempt != 1
        or validate_tag(tag, source_version=read_source_version()) != VERSION
    ):
        raise ReleaseProvenanceError("current release identity is not exact v3.8.2")

    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    expected_inputs = {
        "qualified_sha": qualified_sha,
        "qualified_run_id": str(qualified_run_id),
        "controller_run_id": str(controller_run_id),
        "controller_run_attempt": str(controller_run_attempt),
    }
    inputs = event.get("inputs")
    if (
        not isinstance(inputs, dict)
        or set(inputs) - {*expected_inputs, "mode", "release_run_id"}
        or any(inputs.get(key) != value for key, value in expected_inputs.items())
        or inputs.get("mode", "standard") != "standard"
        or inputs.get("release_run_id", "") != ""
    ):
        raise ReleaseProvenanceError("workflow_dispatch inputs are not exact")

    attestation = load_attestation(
        Path(env["CONTROLLER_ATTESTATION_DIR"]),
        repo=repo,
        controller_run_id=controller_run_id,
        controller_run_attempt=controller_run_attempt,
        release_run_id=release_run_id,
        qualified_run_id=qualified_run_id,
        qualified_sha=qualified_sha,
        tag=tag,
    )
    tag_object_sha = attestation["tag_object_sha"]
    api = GitHubAPI(repo, token)

    current = api.get(f"/actions/runs/{release_run_id}")
    require_fields(
        current,
        {
            "id": release_run_id,
            "run_attempt": 1,
            "path": ".github/workflows/release.yml",
            "event": "workflow_dispatch",
            "head_sha": qualified_sha,
            "status": "in_progress",
        },
        "current release run",
    )
    require_repository(current, repo, "current release run")
    workflow_id = current.get("workflow_id")
    if isinstance(workflow_id, bool) or not isinstance(workflow_id, int):
        raise ReleaseProvenanceError("current release run lacks a workflow ID")

    controller = api.get(f"/actions/runs/{controller_run_id}")
    require_fields(
        controller,
        {
            "id": controller_run_id,
            "run_attempt": controller_run_attempt,
            "path": ".github/workflows/v382-release-controller.yml",
            "event": "workflow_run",
            "head_branch": "main",
            "head_sha": qualified_sha,
            "status": "completed",
            "conclusion": "success",
        },
        "controller run",
    )
    require_repository(controller, repo, "controller run")

    qualified = api.get(f"/actions/runs/{qualified_run_id}")
    require_fields(
        qualified,
        {
            "id": qualified_run_id,
            "workflow_id": workflow_id,
            "path": ".github/workflows/release.yml",
            "event": "push",
            "head_branch": "main",
            "head_sha": qualified_sha,
            "status": "completed",
            "conclusion": "success",
        },
        "qualified main run",
    )
    require_repository(qualified, repo, "qualified main run")

    require_one_successful_job(api.jobs(qualified_run_id), "Release gates complete")
    current_jobs = api.jobs(release_run_id)
    require_one_successful_job(current_jobs, "Build and inspect distributions")
    require_one_successful_job(current_jobs, "Release gates complete")
    controller_jobs = api.jobs(controller_run_id)
    require_one_successful_job(
        controller_jobs,
        "Validate exact qualified source without a persisted token",
    )
    require_one_successful_job(
        controller_jobs,
        "Create exact annotated tag and dispatch exact tag run",
    )

    attestation_name = (
        f"v382-release-controller-attestation-{controller_run_id}-"
        f"{controller_run_attempt}"
    )
    api.require_artifact(controller_run_id, attestation_name)
    api.require_artifact(release_run_id, "staqtapp-tds-distributions")

    main_ref = api.get("/git/ref/heads/main")
    if (
        main_ref.get("object", {}).get("type") != "commit"
        or main_ref.get("object", {}).get("sha") != qualified_sha
    ):
        raise ReleaseProvenanceError("main changed after release qualification")
    tag_ref = api.get(f"/git/ref/tags/{quote(tag, safe='')}")
    if (
        tag_ref.get("object", {}).get("type") != "tag"
        or tag_ref.get("object", {}).get("sha") != tag_object_sha
    ):
        raise ReleaseProvenanceError("annotated tag object changed before upload")
    tag_object = api.get(f"/git/tags/{tag_object_sha}")
    if (
        tag_object.get("sha") != tag_object_sha
        or tag_object.get("tag") != tag
        or tag_object.get("object", {}).get("type") != "commit"
        or tag_object.get("object", {}).get("sha") != qualified_sha
    ):
        raise ReleaseProvenanceError("annotated tag does not target qualified main")

    distributions = validate_distribution_set(Path(env["DISTRIBUTION_DIR"]))
    require_pypi_absent()
    return distributions


def main() -> int:
    try:
        distributions = verify_from_environment()
    except (KeyError, OSError, ValueError, ReleaseProvenanceError) as exc:
        print(f"pre-OIDC release provenance failed: {exc}", file=os.sys.stderr)
        return 1
    print(
        json.dumps(
            {"version": VERSION, "distributions": distributions},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Bind a production-PyPI smoke run to its exact parent release proof."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from release_version import read_source_version, validate_tag
from v382_release_provenance import (
    GitHubAPI,
    ReleaseProvenanceError,
    positive_integer,
    require_fields,
    require_one_successful_job,
    require_repository,
    require_sha,
)


VERSION = "3.8.2"
TAG = "v3.8.2"


def require_one_running_job(jobs: list[dict[str, Any]], name: str) -> None:
    matches = [job for job in jobs if job.get("name") == name]
    if (
        len(matches) != 1
        or matches[0].get("status") != "in_progress"
        or matches[0].get("conclusion") is not None
    ):
        raise ReleaseProvenanceError(f"run lacks one running {name!r} job")


def verify_from_environment() -> None:
    env = os.environ
    repo = env["GH_REPOSITORY"]
    token = env["GH_TOKEN"]
    tag = env["RELEASE_VERSION"]
    qualified_sha = require_sha(env["QUALIFIED_SHA"], "qualified SHA")
    smoke_sha = require_sha(env["SMOKE_SHA"], "smoke SHA")
    tag_object_sha = require_sha(
        env["ATTESTED_TAG_OBJECT_SHA"], "controller-attested tag object SHA"
    )
    qualified_run_id = positive_integer(
        env["QUALIFIED_RUN_ID"], "qualified run ID"
    )
    release_run_id = positive_integer(env["RELEASE_RUN_ID"], "release run ID")
    smoke_run_id = positive_integer(env["SMOKE_RUN_ID"], "smoke run ID")
    smoke_run_attempt = positive_integer(
        env["SMOKE_RUN_ATTEMPT"], "smoke run attempt"
    )
    if (
        env["GITHUB_EVENT_NAME"] != "workflow_dispatch"
        or tag != TAG
        or env["SMOKE_REF"] != f"refs/tags/{TAG}"
        or smoke_sha != qualified_sha
        or smoke_run_attempt != 1
        or validate_tag(tag, source_version=read_source_version()) != VERSION
    ):
        raise ReleaseProvenanceError("smoke release identity is not exact v3.8.2")

    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    expected_inputs = {
        "version": tag,
        "qualified_sha": qualified_sha,
        "qualified_run_id": str(qualified_run_id),
        "release_run_id": str(release_run_id),
        "tag_object_sha": tag_object_sha,
    }
    if event.get("inputs") != expected_inputs:
        raise ReleaseProvenanceError("smoke workflow_dispatch inputs are not exact")

    api = GitHubAPI(repo, token)
    current = api.get(f"/actions/runs/{smoke_run_id}")
    require_fields(
        current,
        {
            "id": smoke_run_id,
            "run_attempt": 1,
            "path": ".github/workflows/pypi-smoke.yml",
            "event": "workflow_dispatch",
            "head_sha": qualified_sha,
            "status": "in_progress",
        },
        "current smoke run",
    )
    require_repository(current, repo, "current smoke run")
    smoke_workflow_id = current.get("workflow_id")
    if isinstance(smoke_workflow_id, bool) or not isinstance(smoke_workflow_id, int):
        raise ReleaseProvenanceError("current smoke run lacks a workflow ID")

    parent = api.get(f"/actions/runs/{release_run_id}")
    require_fields(
        parent,
        {
            "id": release_run_id,
            "run_attempt": 1,
            "path": ".github/workflows/release.yml",
            "event": "workflow_dispatch",
            "head_sha": qualified_sha,
            "status": "in_progress",
        },
        "parent release run",
    )
    require_repository(parent, repo, "parent release run")
    release_workflow_id = parent.get("workflow_id")
    if (
        isinstance(release_workflow_id, bool)
        or not isinstance(release_workflow_id, int)
        or release_workflow_id == smoke_workflow_id
    ):
        raise ReleaseProvenanceError("parent release workflow ID is invalid")

    qualified = api.get(f"/actions/runs/{qualified_run_id}")
    require_fields(
        qualified,
        {
            "id": qualified_run_id,
            "workflow_id": release_workflow_id,
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

    parent_jobs = api.jobs(release_run_id)
    require_one_successful_job(
        parent_jobs, "Verify exact production PyPI publication"
    )
    require_one_running_job(
        parent_jobs, "Require production smoke before publishing GitHub Release"
    )

    tag_ref = api.get(f"/git/ref/tags/{quote(tag, safe='')}")
    tag_reference = tag_ref.get("object", {})
    if (
        tag_reference.get("type") != "tag"
        or tag_reference.get("sha") != tag_object_sha
    ):
        raise ReleaseProvenanceError(
            "smoke requires the controller-attested annotated tag object"
        )
    tag_object = api.get(f"/git/tags/{tag_object_sha}")
    if (
        tag_object.get("sha") != tag_object_sha
        or tag_object.get("tag") != tag
        or tag_object.get("object", {}).get("type") != "commit"
        or tag_object.get("object", {}).get("sha") != qualified_sha
    ):
        raise ReleaseProvenanceError("smoke tag does not target qualified main")


def main() -> int:
    try:
        verify_from_environment()
    except (KeyError, OSError, ValueError, ReleaseProvenanceError) as exc:
        print(f"production smoke provenance failed: {exc}", file=os.sys.stderr)
        return 1
    print("exact production smoke provenance passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

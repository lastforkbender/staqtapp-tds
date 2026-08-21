from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from urllib.parse import unquote, urlparse
import zipfile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ROOT / ".github" / "workflows" / "release.yml"
CONTROLLER_PATH = (
    ROOT / ".github" / "workflows" / "v382-release-controller.yml"
)
SMOKE_PATH = ROOT / ".github" / "workflows" / "pypi-smoke.yml"
SCRIPTS = ROOT / "scripts"
VERIFIED_ACTION_PINS = {
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b",
}
sys.path.insert(0, str(SCRIPTS))
import v382_release_provenance as provenance  # noqa: E402
import v382_smoke_provenance as smoke_provenance  # noqa: E402


class _ActionsLoader(yaml.SafeLoader):
    """YAML 1.2 booleans without YAML 1.1's surprising ``on`` coercion."""

    def construct_mapping(self, node, deep: bool = False):
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise AssertionError(f"duplicate YAML mapping key: {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


_ActionsLoader.yaml_implicit_resolvers = deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for _initial, _resolvers in tuple(
    _ActionsLoader.yaml_implicit_resolvers.items()
):
    _ActionsLoader.yaml_implicit_resolvers[_initial] = [
        resolver
        for resolver in _resolvers
        if resolver[0] != "tag:yaml.org,2002:bool"
    ]
_ActionsLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def _workflow(path: Path) -> dict:
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_ActionsLoader)
    assert isinstance(loaded, dict)
    assert "on" in loaded
    assert True not in loaded
    return loaded


def _job(workflow: dict, name: str) -> dict:
    job = workflow["jobs"][name]
    assert isinstance(job, dict)
    return job


def _step(job: dict, name: str) -> dict:
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def _python_blocks(workflow: dict) -> list[str]:
    blocks = []
    pattern = re.compile(
        r"(?:^|\n)python - <<'PY'\n(.*?)\nPY(?:\n|$)",
        re.DOTALL,
    )
    for job in workflow.get("jobs", {}).values():
        for step in job.get("steps", []):
            run = step.get("run")
            if isinstance(run, str):
                blocks.extend(match.group(1) for match in pattern.finditer(run))
    return blocks


def _job_python(workflow: dict, job_name: str) -> str:
    blocks = _python_blocks({"jobs": {job_name: _job(workflow, job_name)}})
    assert len(blocks) == 1
    return blocks[0]


def _load_function(source: str, name: str, globals_: dict | None = None):
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    module = ast.Module(body=[matches[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {} if globals_ is None else dict(globals_)
    exec(compile(module, f"<{name}>", "exec"), namespace)
    return namespace[name]


def _dispatch_call(source: str, path: str) -> ast.Call:
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "api" or len(node.args) < 3:
            continue
        if isinstance(node.args[1], ast.Constant) and node.args[1].value == path:
            calls.append(node)
    assert len(calls) == 1
    return calls[0]


def _dict_value(mapping: ast.Dict, key: str) -> ast.expr:
    for candidate, value in zip(mapping.keys, mapping.values, strict=True):
        if isinstance(candidate, ast.Constant) and candidate.value == key:
            return value
    raise AssertionError(f"missing key {key!r}")


def _needs(job: dict) -> set[str]:
    value = job.get("needs", [])
    if isinstance(value, str):
        return {value}
    return set(value)


def _write_exact_distributions(root: Path) -> None:
    root.mkdir(parents=True)
    metadata = (
        b"Metadata-Version: 2.4\n"
        b"Name: staqtapp-tds\n"
        b"Version: 3.8.2\n\n"
    )
    wheel = root / "staqtapp_tds-3.8.2-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("staqtapp_tds-3.8.2.dist-info/METADATA", metadata)
        archive.writestr("staqtapp_tds/__init__.py", b"")
    sdist = root / "staqtapp_tds-3.8.2.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        info = tarfile.TarInfo("staqtapp_tds-3.8.2/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))


def _attestation(
    *, release_run_id: int = 200, tag_object_sha: str = "d" * 40
) -> dict:
    return {
        "schema": provenance.ATTESTATION_SCHEMA,
        "repo": "owner/repo",
        "controller_run_id": 300,
        "controller_run_attempt": 1,
        "release_run_id": release_run_id,
        "qualified_run_id": 100,
        "qualified_sha": "a" * 40,
        "tag": "v3.8.2",
        "tag_object_sha": tag_object_sha,
    }


def _write_attestation(root: Path, payload: dict | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / provenance.ATTESTATION_FILENAME).write_text(
        json.dumps(_attestation() if payload is None else payload) + "\n",
        encoding="utf-8",
    )


def _run_payload(**values) -> dict:
    payload = {
        "repository": {"full_name": "owner/repo"},
        "head_repository": {"full_name": "owner/repo"},
    }
    payload.update(values)
    return payload


def _successful_job(name: str) -> dict:
    return {"name": name, "status": "completed", "conclusion": "success"}


def test_actions_yaml_and_embedded_python_are_real_parseable_programs() -> None:
    workflows = [_workflow(path) for path in (RELEASE_PATH, CONTROLLER_PATH, SMOKE_PATH)]
    for workflow in workflows:
        for source in _python_blocks(workflow):
            compile(source, "<workflow-python>", "exec")

    actionlint = shutil.which("actionlint")
    if actionlint is not None:
        subprocess.run(
            [actionlint, str(RELEASE_PATH), str(CONTROLLER_PATH), str(SMOKE_PATH)],
            cwd=ROOT,
            check=True,
        )


def test_release_dependency_graph_is_fail_closed_and_tag_serialized() -> None:
    workflow = _workflow(RELEASE_PATH)
    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(dispatch_inputs) == {
        "qualified_sha",
        "qualified_run_id",
        "controller_run_id",
        "controller_run_attempt",
    }
    assert all(spec["required"] is True for spec in dispatch_inputs.values())
    assert all("default" not in spec for spec in dispatch_inputs.values())

    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] is False
    assert "github.ref_type == 'tag'" in concurrency["group"]
    assert "github.ref_name" in concurrency["group"]
    assert "github.run_id" in concurrency["group"]

    prepublish = _job(workflow, "prepublish-provenance")
    publish = _job(workflow, "publish-pypi")
    verify = _job(workflow, "verify-production-pypi")
    finalize = _job(workflow, "finalize-github-release")
    assert _needs(prepublish) == {"release-gates-complete"}
    assert _needs(publish) == {
        "release-gates-complete",
        "prepublish-provenance",
    }
    assert _needs(verify) == {"publish-pypi"}
    assert _needs(finalize) == {
        "verify-production-pypi",
        "prepublish-provenance",
    }
    assert prepublish["outputs"]["tag_object_sha"] == (
        "${{ steps.provenance.outputs.tag_object_sha }}"
    )
    assert finalize["env"]["ATTESTED_TAG_OBJECT_SHA"] == (
        "${{ needs.prepublish-provenance.outputs.tag_object_sha }}"
    )
    for job in (prepublish, publish, verify, finalize):
        condition = job["if"]
        assert "workflow_dispatch" in condition
        assert "github.ref_type == 'tag'" in condition
        assert "github.ref_name == 'v3.8.2'" in condition

    assert prepublish["permissions"] == {"contents": "read", "actions": "read"}
    assert publish["permissions"] == {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
    }
    assert publish["environment"]["name"] == "pypi"
    assert "skip-existing" not in str(publish)
    assert "PYPI_TOKEN" not in RELEASE_PATH.read_text(encoding="utf-8")


def test_allocator_proof_remains_a_required_long_running_gate() -> None:
    workflow = _workflow(RELEASE_PATH)
    allocator = _job(workflow, "native-handle-allocator-release-qualification")
    aggregate = _job(workflow, "release-gates-complete")
    assert allocator["timeout-minutes"] == 330
    assert "native-handle-allocator-release-qualification" in _needs(aggregate)
    run = _step(
        allocator, "Run retained randomized paired AB/BA allocator proof"
    )["run"]
    for exact in (
        "--baseline-ref v3.8.1",
        '--candidate-ref "$GITHUB_SHA"',
        "--pairs 7",
        "--warmup-pairs 2",
        "--seed 3820817",
    ):
        assert exact in run
    archive = _step(
        allocator, "Archive allocator proof even when a release threshold fails"
    )
    assert archive["if"] == "always()"
    assert archive["with"]["retention-days"] == 90


def test_controller_separates_untrusted_validation_from_mutation_token() -> None:
    workflow = _workflow(CONTROLLER_PATH)
    assert workflow["permissions"] == {"contents": "read"}
    assert "workflow_dispatch" not in workflow["on"]
    assert workflow["concurrency"]["cancel-in-progress"] is False

    validate = _job(workflow, "validate-qualified-source")
    mutate = _job(workflow, "mutate-release")
    assert validate["permissions"] == {"contents": "read"}
    assert "GH_TOKEN" not in validate.get("env", {})
    checkout = validate["steps"][0]
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout["uses"])
    assert checkout["with"]["persist-credentials"] is False

    assert mutate["permissions"] == {"contents": "write", "actions": "write"}
    assert _needs(mutate) == {"validate-qualified-source"}
    assert "uses" not in mutate["steps"][0]
    assert re.fullmatch(
        r"actions/upload-artifact@[0-9a-f]{40}",
        mutate["steps"][1]["uses"],
    )
    assert "GH_TOKEN" not in mutate.get("env", {})
    assert len(mutate["steps"]) == 2
    assert mutate["steps"][0]["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "actions/checkout" not in str(mutate)


def test_controller_emits_one_exact_run_bound_attestation(tmp_path: Path) -> None:
    workflow = _workflow(CONTROLLER_PATH)
    mutate = _job(workflow, "mutate-release")
    source = _job_python(workflow, "mutate-release")
    upload = mutate["steps"][1]
    assert upload["with"]["name"] == (
        "v382-release-controller-attestation-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert upload["with"]["path"] == provenance.ATTESTATION_FILENAME
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == 90
    for key in (
        "schema",
        "repo",
        "controller_run_id",
        "controller_run_attempt",
        "release_run_id",
        "qualified_run_id",
        "qualified_sha",
        "tag",
        "tag_object_sha",
    ):
        assert f'"{key}"' in source

    root = tmp_path / "attestation"
    _write_attestation(root)
    loaded = provenance.load_attestation(
        root,
        repo="owner/repo",
        controller_run_id=300,
        controller_run_attempt=1,
        release_run_id=200,
        qualified_run_id=100,
        qualified_sha="a" * 40,
        tag="v3.8.2",
    )
    assert loaded == _attestation()

    # Copying valid controller/qualified inputs into another manual release
    # run cannot satisfy the immutable attested release_run_id.
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.load_attestation(
            root,
            repo="owner/repo",
            controller_run_id=300,
            controller_run_attempt=1,
            release_run_id=201,
            qualified_run_id=100,
            qualified_sha="a" * 40,
            tag="v3.8.2",
        )

    extra = _attestation()
    extra["unexpected"] = True
    _write_attestation(root, extra)
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.load_attestation(
            root,
            repo="owner/repo",
            controller_run_id=300,
            controller_run_attempt=1,
            release_run_id=200,
            qualified_run_id=100,
            qualified_sha="a" * 40,
            tag="v3.8.2",
        )

    wrong_type = _attestation()
    wrong_type["controller_run_attempt"] = True
    _write_attestation(root, wrong_type)
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.load_attestation(
            root,
            repo="owner/repo",
            controller_run_id=300,
            controller_run_attempt=1,
            release_run_id=200,
            qualified_run_id=100,
            qualified_sha="a" * 40,
            tag="v3.8.2",
        )


def test_critical_oidc_actions_are_full_sha_pinned() -> None:
    workflow = _workflow(RELEASE_PATH)
    all_uses = [
        step["uses"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    ]
    assert all_uses
    assert all(
        re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in all_uses
    )
    assert set(all_uses) <= VERIFIED_ACTION_PINS
    producer = _job(workflow, "build-distributions")
    producer_uses = [
        step["uses"] for step in producer["steps"] if "uses" in step
    ]
    assert len(producer_uses) == 3
    assert all(
        re.fullmatch(r"[^@]+@[0-9a-f]{40}", value)
        for value in producer_uses
    )
    assert producer["steps"][0]["with"]["persist-credentials"] is False

    publish = _job(workflow, "publish-pypi")
    uses = [step["uses"] for step in publish["steps"] if "uses" in step]
    assert len(uses) == 5
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in uses)
    assert uses[-1].startswith("pypa/gh-action-pypi-publish@")

    finalize = _job(workflow, "finalize-github-release")
    assert all("uses" not in step for step in finalize["steps"])
    assert "GH_TOKEN" not in finalize.get("env", {})
    assert finalize["steps"][0]["env"]["GH_TOKEN"] == "${{ github.token }}"

    smoke = _workflow(SMOKE_PATH)
    for name in (
        "validate-release-identity",
        "install-from-pypi",
        "verify-pypi-presentation",
    ):
        action_steps = [
            step for step in _job(smoke, name)["steps"] if "uses" in step
        ]
        assert action_steps
        assert all(
            re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
            for step in action_steps
        )
        checkout = next(
            step for step in action_steps
            if step["uses"].startswith("actions/checkout@")
        )
        assert checkout["with"]["persist-credentials"] is False

    controller_uses = {
        step["uses"]
        for job in _workflow(CONTROLLER_PATH)["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    }
    smoke_uses = {
        step["uses"]
        for job in smoke["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    }
    assert controller_uses <= VERIFIED_ACTION_PINS
    assert smoke_uses <= VERIFIED_ACTION_PINS


def test_publish_revalidates_after_environment_gate_immediately_before_oidc() -> None:
    workflow = _workflow(RELEASE_PATH)
    publish = _job(workflow, "publish-pypi")
    assert publish["permissions"] == {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
    }
    names = [step.get("name") for step in publish["steps"]]
    proof_index = names.index(
        "Revalidate all publication proof immediately before OIDC"
    )
    publisher_index = names.index("Publish with PyPI trusted publishing")
    assert proof_index + 1 == publisher_index
    assert publish["steps"][proof_index]["run"] == (
        "set -euo pipefail\npython scripts/v382_release_provenance.py\n"
    )
    downloads = [
        step for step in publish["steps"][:proof_index]
        if step.get("uses", "").startswith("actions/download-artifact@")
    ]
    assert len(downloads) == 2
    assert {step["with"]["name"] for step in downloads} == {
        "staqtapp-tds-distributions",
        "v382-release-controller-attestation-"
        "${{ inputs.controller_run_id }}-${{ inputs.controller_run_attempt }}",
    }
    assert all("run-id" in step["with"] for step in downloads)


@pytest.mark.parametrize("workflow_path, job_name", [
    (CONTROLLER_PATH, "mutate-release"),
    (RELEASE_PATH, "finalize-github-release"),
])
def test_dispatch_requires_http_200_and_non_null_returned_run_id(
    workflow_path: Path, job_name: str
) -> None:
    source = _job_python(_workflow(workflow_path), job_name)
    require = _load_function(source, "require_dispatch_response")
    assert require(200, {"workflow_run_id": 431}) == 431
    for status, payload in (
        (204, None),
        (200, None),
        (200, {}),
        (200, {"workflow_run_id": None}),
        (200, {"workflow_run_id": False}),
        (200, {"workflow_run_id": 0}),
        (200, {"workflow_run_id": "431"}),
    ):
        with pytest.raises(SystemExit):
            require(status, payload)


def test_both_dispatches_request_details_and_poll_only_returned_ids() -> None:
    controller_source = _job_python(_workflow(CONTROLLER_PATH), "mutate-release")
    finalizer_source = _job_python(
        _workflow(RELEASE_PATH), "finalize-github-release"
    )
    cases = (
        (
                controller_source,
                "/actions/workflows/release.yml/dispatches",
                {
                    "qualified_sha",
                    "qualified_run_id",
                    "controller_run_id",
                    "controller_run_attempt",
                },
        ),
        (
            finalizer_source,
            "/actions/workflows/pypi-smoke.yml/dispatches",
            {
                "version",
                "qualified_sha",
                "qualified_run_id",
                "release_run_id",
                "tag_object_sha",
            },
        ),
    )
    for source, path, expected_inputs in cases:
        call = _dispatch_call(source, path)
        payload = call.args[2]
        assert isinstance(payload, ast.Dict)
        details = _dict_value(payload, "return_run_details")
        assert isinstance(details, ast.Constant) and details.value is True
        inputs = _dict_value(payload, "inputs")
        assert isinstance(inputs, ast.Dict)
        assert {
            key.value for key in inputs.keys if isinstance(key, ast.Constant)
        } == expected_inputs
        expected = next(keyword.value for keyword in call.keywords if keyword.arg == "expected")
        assert isinstance(expected, ast.Tuple)
        assert [item.value for item in expected.elts] == [200]
        assert "/runs?" not in source
        assert "head_sha=" not in source


def test_exact_returned_release_run_rejects_unrelated_runs() -> None:
    source = _job_python(_workflow(CONTROLLER_PATH), "mutate-release")
    require = _load_function(
        source,
        "require_dispatched_run",
        {"sha": "a" * 40, "repo": "owner/repo", "SystemExit": SystemExit},
    )
    valid = {
        "id": 90,
        "run_attempt": 1,
        "workflow_id": 12,
        "path": ".github/workflows/release.yml",
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "repository": {"full_name": "owner/repo"},
        "head_repository": {"full_name": "owner/repo"},
    }
    require(valid, 90, 12)
    for field, wrong in (
        ("id", 91),
        ("run_attempt", True),
        ("workflow_id", 13),
        ("path", ".github/workflows/other.yml"),
        ("event", "push"),
        ("head_sha", "b" * 40),
        ("repository", {"full_name": "attacker/repo"}),
    ):
        candidate = deepcopy(valid)
        candidate[field] = wrong
        with pytest.raises(SystemExit):
            require(candidate, 90, 12)


def test_exact_returned_smoke_run_rejects_unrelated_runs() -> None:
    source = _job_python(_workflow(RELEASE_PATH), "finalize-github-release")
    require = _load_function(source, "require_smoke_run")
    valid = {
        "id": 91,
        "run_attempt": 1,
        "workflow_id": 14,
        "path": ".github/workflows/pypi-smoke.yml",
        "event": "workflow_dispatch",
        "head_sha": "c" * 40,
        "repository": {"full_name": "owner/repo"},
        "head_repository": {"full_name": "owner/repo"},
    }
    require(valid, 91, 14, "owner/repo", "c" * 40)
    for field, wrong in (
        ("id", 92),
        ("run_attempt", True),
        ("workflow_id", 15),
        ("path", ".github/workflows/release.yml"),
        ("event", "release"),
        ("head_sha", "d" * 40),
        ("head_repository", {"full_name": "attacker/repo"}),
    ):
        candidate = deepcopy(valid)
        candidate[field] = wrong
        with pytest.raises(SystemExit):
            require(candidate, 91, 14, "owner/repo", "c" * 40)


def test_prepublish_proves_exact_tag_main_run_gate_and_pypi_absence() -> None:
    workflow = _workflow(RELEASE_PATH)
    prepublish = _job(workflow, "prepublish-provenance")
    source = _job_python(workflow, "prepublish-provenance")
    action_steps = [step for step in prepublish["steps"] if "uses" in step]
    assert len(action_steps) == 1
    assert re.fullmatch(
        r"actions/download-artifact@[0-9a-f]{40}",
        action_steps[0]["uses"],
    )
    assert action_steps[0]["with"] == {
        "name": (
            "v382-release-controller-attestation-"
            "${{ inputs.controller_run_id }}-"
            "${{ inputs.controller_run_attempt }}"
        ),
        "path": "controller-attestation",
        "github-token": "${{ github.token }}",
        "repository": "${{ github.repository }}",
        "run-id": "${{ inputs.controller_run_id }}",
    }
    for required in (
        '"event": "workflow_dispatch"',
        '"path": ".github/workflows/release.yml"',
        '"path": ".github/workflows/v382-release-controller.yml"',
        '"event": "push"',
        '"head_branch": "main"',
        '"status": "completed"',
        '"conclusion": "success"',
        'job.get("name") == "Release gates complete"',
        '"release_run_id": release_run_id',
        '"controller_run_id": controller_run_id',
        '"controller_run_attempt": controller_run_attempt',
        '"tag_object_sha": tag_object_sha',
        'f"/actions/runs/{controller_run_id}/artifacts?"',
        'f"/git/ref/tags/{quote(tag, safe=\'\')}"',
        'tag_ref.get("object", {}).get("type") != "tag"',
        '"/git/ref/heads/main"',
        "pypi.org/pypi/staqtapp-tds",
        "automatic publication re-entry is prohibited",
    ):
        assert required in source
    assert "expected=(200, 404)" not in source.split("pypi_request", 1)[1]


def test_pre_oidc_distribution_set_is_exact_and_typed(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_exact_distributions(dist)
    identities = provenance.validate_distribution_set(dist)
    assert set(identities) == provenance.EXPECTED_DISTRIBUTIONS
    assert all(identity["size"] > 0 for identity in identities.values())
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])
        for identity in identities.values()
    )

    (dist / "unexpected.txt").write_text("no", encoding="utf-8")
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.validate_distribution_set(dist)
    (dist / "unexpected.txt").unlink()
    (dist / "staqtapp_tds-3.8.2-py3-none-any.whl").write_bytes(b"not a wheel")
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.validate_distribution_set(dist)


def test_pre_oidc_proof_rejects_stale_main_tag_pypi_and_manual_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    attestation_dir = tmp_path / "attestation"
    _write_exact_distributions(dist)
    _write_attestation(attestation_dir)
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "qualified_sha": "a" * 40,
                    "qualified_run_id": "100",
                    "controller_run_id": "300",
                    "controller_run_attempt": "1",
                }
            }
        ),
        encoding="utf-8",
    )
    env = {
        "GH_REPOSITORY": "owner/repo",
        "GH_TOKEN": "read-token",
        "RELEASE_TAG": "v3.8.2",
        "RELEASE_REF": "refs/tags/v3.8.2",
        "RELEASE_SHA": "a" * 40,
        "RELEASE_RUN_ID": "200",
        "RELEASE_RUN_ATTEMPT": "1",
        "QUALIFIED_SHA": "a" * 40,
        "QUALIFIED_RUN_ID": "100",
        "CONTROLLER_RUN_ID": "300",
        "CONTROLLER_RUN_ATTEMPT": "1",
        "CONTROLLER_ATTESTATION_DIR": str(attestation_dir),
        "DISTRIBUTION_DIR": str(dist),
        "GITHUB_EVENT_PATH": str(event_path),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    class FakeAPI:
        artifact_calls: list[tuple[int, str]] = []
        responses = {
            "/actions/runs/200": _run_payload(
                id=200,
                run_attempt=1,
                workflow_id=10,
                path=".github/workflows/release.yml",
                event="workflow_dispatch",
                head_sha="a" * 40,
                status="in_progress",
            ),
            "/actions/runs/300": _run_payload(
                id=300,
                run_attempt=1,
                workflow_id=30,
                path=".github/workflows/v382-release-controller.yml",
                event="workflow_run",
                head_branch="main",
                head_sha="a" * 40,
                status="completed",
                conclusion="success",
            ),
            "/actions/runs/100": _run_payload(
                id=100,
                run_attempt=1,
                workflow_id=10,
                path=".github/workflows/release.yml",
                event="push",
                head_branch="main",
                head_sha="a" * 40,
                status="completed",
                conclusion="success",
            ),
            "/git/ref/heads/main": {
                "object": {"type": "commit", "sha": "a" * 40}
            },
            "/git/ref/tags/v3.8.2": {
                "object": {"type": "tag", "sha": "d" * 40}
            },
            f"/git/tags/{'d' * 40}": {
                "sha": "d" * 40,
                "tag": "v3.8.2",
                "object": {"type": "commit", "sha": "a" * 40},
            },
        }
        job_sets = {
            100: [_successful_job("Release gates complete")],
            200: [
                _successful_job("Build and inspect distributions"),
                _successful_job("Release gates complete"),
            ],
            300: [
                _successful_job(
                    "Validate exact qualified source without a persisted token"
                ),
                _successful_job(
                    "Create exact annotated tag and dispatch exact tag run"
                ),
            ],
        }

        def __init__(self, repo: str, token: str) -> None:
            assert (repo, token) == ("owner/repo", "read-token")

        def get(self, path: str) -> dict:
            return deepcopy(self.responses[path])

        def jobs(self, run_id: int) -> list[dict]:
            return deepcopy(self.job_sets[run_id])

        def require_artifact(self, run_id: int, name: str) -> None:
            self.artifact_calls.append((run_id, name))

    monkeypatch.setattr(provenance, "GitHubAPI", FakeAPI)
    monkeypatch.setattr(provenance, "require_pypi_absent", lambda: None)
    result = provenance.verify_from_environment()
    assert set(result) == provenance.EXPECTED_DISTRIBUTIONS
    assert FakeAPI.artifact_calls == [
        (300, "v382-release-controller-attestation-300-1"),
        (200, "staqtapp-tds-distributions"),
    ]

    FakeAPI.responses["/git/ref/heads/main"]["object"]["sha"] = "b" * 40
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.verify_from_environment()
    FakeAPI.responses["/git/ref/heads/main"]["object"]["sha"] = "a" * 40

    FakeAPI.responses["/git/ref/tags/v3.8.2"]["object"]["sha"] = "e" * 40
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.verify_from_environment()
    FakeAPI.responses["/git/ref/tags/v3.8.2"]["object"]["sha"] = "d" * 40

    def pypi_exists() -> None:
        raise provenance.ReleaseProvenanceError("PyPI 3.8.2 already exists")

    monkeypatch.setattr(provenance, "require_pypi_absent", pypi_exists)
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.verify_from_environment()
    monkeypatch.setattr(provenance, "require_pypi_absent", lambda: None)

    monkeypatch.setenv("RELEASE_RUN_ID", "201")
    with pytest.raises(provenance.ReleaseProvenanceError):
        provenance.verify_from_environment()


def test_smoke_binds_version_tag_ref_sha_and_parent_inputs() -> None:
    workflow = _workflow(SMOKE_PATH)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "version",
        "qualified_sha",
        "qualified_run_id",
        "release_run_id",
        "tag_object_sha",
    }
    assert all(spec["required"] is True for spec in inputs.values())
    assert all("default" not in spec for spec in inputs.values())

    identity = _job(workflow, "validate-release-identity")
    run = _step(
        identity, "Bind version input, tag ref, source, SHA, and parent run IDs"
    )["run"]
    assert 'release_version.py --check-tag "$RELEASE_VERSION"' in run
    assert 'test "$GITHUB_REF_TYPE" = tag' in run
    assert 'test "$GITHUB_REF_NAME" = "$RELEASE_VERSION"' in run
    assert 'test "$GITHUB_SHA" = "$QUALIFIED_SHA"' in run
    assert 'git cat-file -t "$GITHUB_REF"' in run
    assert 'git rev-parse "${GITHUB_REF}^{}"' in run
    assert "QUALIFIED_RUN_ID" in run and "RELEASE_RUN_ID" in run
    assert "python scripts/v382_smoke_provenance.py" in run
    assert _needs(_job(workflow, "install-from-pypi")) == {
        "validate-release-identity"
    }
    assert _needs(_job(workflow, "verify-pypi-presentation")) == {
        "validate-release-identity"
    }
    assert _needs(_job(workflow, "smoke-complete")) == {
        "validate-release-identity",
        "install-from-pypi",
        "verify-pypi-presentation",
    }

    command = [sys.executable, "scripts/release_version.py", "--check-tag"]
    assert subprocess.run(command + ["v3.8.2"], cwd=ROOT).returncode == 0
    assert subprocess.run(command + ["v3.8.1"], cwd=ROOT).returncode != 0
    assert subprocess.run(command + ["3.8.2"], cwd=ROOT).returncode != 0


def test_smoke_semantically_binds_current_parent_qualified_and_tag_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_path = tmp_path / "event.json"
    event_payload = {
        "inputs": {
            "version": "v3.8.2",
            "qualified_sha": "a" * 40,
            "qualified_run_id": "100",
            "release_run_id": "200",
            "tag_object_sha": "d" * 40,
        }
    }
    event_path.write_text(json.dumps(event_payload), encoding="utf-8")
    env = {
        "GH_REPOSITORY": "owner/repo",
        "GH_TOKEN": "read-token",
        "RELEASE_VERSION": "v3.8.2",
        "QUALIFIED_SHA": "a" * 40,
        "QUALIFIED_RUN_ID": "100",
        "RELEASE_RUN_ID": "200",
        "ATTESTED_TAG_OBJECT_SHA": "d" * 40,
        "SMOKE_REF": "refs/tags/v3.8.2",
        "SMOKE_SHA": "a" * 40,
        "SMOKE_RUN_ID": "400",
        "SMOKE_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_EVENT_PATH": str(event_path),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    class FakeAPI:
        responses = {
            "/actions/runs/400": _run_payload(
                id=400,
                run_attempt=1,
                workflow_id=20,
                path=".github/workflows/pypi-smoke.yml",
                event="workflow_dispatch",
                head_sha="a" * 40,
                status="in_progress",
            ),
            "/actions/runs/200": _run_payload(
                id=200,
                run_attempt=1,
                workflow_id=10,
                path=".github/workflows/release.yml",
                event="workflow_dispatch",
                head_sha="a" * 40,
                status="in_progress",
            ),
            "/actions/runs/100": _run_payload(
                id=100,
                run_attempt=1,
                workflow_id=10,
                path=".github/workflows/release.yml",
                event="push",
                head_branch="main",
                head_sha="a" * 40,
                status="completed",
                conclusion="success",
            ),
            "/git/ref/tags/v3.8.2": {
                "object": {"type": "tag", "sha": "d" * 40}
            },
            f"/git/tags/{'d' * 40}": {
                "sha": "d" * 40,
                "tag": "v3.8.2",
                "object": {"type": "commit", "sha": "a" * 40},
            },
        }
        job_sets = {
            100: [_successful_job("Release gates complete")],
            200: [
                _successful_job("Verify exact production PyPI publication"),
                {
                    "name": (
                        "Require production smoke before publishing GitHub "
                        "Release"
                    ),
                    "status": "in_progress",
                    "conclusion": None,
                },
            ],
        }

        def __init__(self, repo: str, token: str) -> None:
            assert (repo, token) == ("owner/repo", "read-token")

        def get(self, path: str) -> dict:
            return deepcopy(self.responses[path])

        def jobs(self, run_id: int) -> list[dict]:
            return deepcopy(self.job_sets[run_id])

    monkeypatch.setattr(smoke_provenance, "GitHubAPI", FakeAPI)
    smoke_provenance.verify_from_environment()

    mutations = (
        ("/actions/runs/200", "event", "push"),
        ("/actions/runs/200", "status", "completed"),
        ("/actions/runs/200", "head_sha", "b" * 40),
        ("/actions/runs/100", "conclusion", "failure"),
        (
            "/git/ref/tags/v3.8.2",
            "object",
            {"type": "commit", "sha": "d" * 40},
        ),
        (
            "/git/ref/tags/v3.8.2",
            "object",
            {"type": "tag", "sha": "e" * 40},
        ),
    )
    for path, field, wrong in mutations:
        original = deepcopy(FakeAPI.responses[path][field])
        FakeAPI.responses[path][field] = wrong
        with pytest.raises(provenance.ReleaseProvenanceError):
            smoke_provenance.verify_from_environment()
        FakeAPI.responses[path][field] = original

    event_payload["inputs"]["version"] = "v3.8.1"
    event_path.write_text(json.dumps(event_payload), encoding="utf-8")
    with pytest.raises(provenance.ReleaseProvenanceError):
        smoke_provenance.verify_from_environment()


def test_public_distribution_urls_are_https_host_and_filename_constrained() -> None:
    source = _job_python(_workflow(RELEASE_PATH), "verify-production-pypi")
    require_url = _load_function(
        source,
        "require_public_file_url",
        {
            "name": "staqtapp_tds-3.8.2-py3-none-any.whl",
            "urlparse": urlparse,
            "unquote": unquote,
        },
    )
    safe = (
        "https://files.pythonhosted.org/packages/aa/bb/"
        "staqtapp_tds-3.8.2-py3-none-any.whl"
    )
    require_url(safe)
    for unsafe in (
        safe.replace("https://", "http://"),
        safe.replace("files.pythonhosted.org", "evil.example"),
        safe.replace("staqtapp_tds-3.8.2-py3-none-any.whl", "other.whl"),
        safe + "?mirror=evil",
    ):
        with pytest.raises(SystemExit):
            require_url(unsafe)

    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "urlopen"
    ]
    assert any(
        call.args and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "request"
        for call in calls
    )
    assert "class ConstrainedRedirect(HTTPRedirectHandler)" in source
    assert "require_public_file_url(newurl)" in source
    assert "opener = build_opener(ConstrainedRedirect)" in source
    assert "with opener.open(request, timeout=60)" in source
    assert "digest.update(chunk)" in source
    assert '"sha256": digest.hexdigest()' in source
    assert '"size": size' in source
    assert "public_identity != expected[name]" in source
    assert "public_identity != json_identity" in source
    assert 'item.get("packagetype") != expected_type' in source
    assert 'item.get("yanked")' in source


def test_public_verifier_hashes_downloaded_wheel_and_sdist_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    _write_exact_distributions(tmp_path / "dist")
    local = {
        path.name: path.read_bytes()
        for path in (tmp_path / "dist").iterdir()
        if path.is_file()
    }
    urls = {
        name: f"https://files.pythonhosted.org/packages/aa/bb/{name}"
        for name in local
    }
    payload = {
        "info": {"version": "3.8.2"},
        "urls": [
            {
                "filename": name,
                "digests": {"sha256": hashlib.sha256(data).hexdigest()},
                "size": len(data),
                "packagetype": (
                    "bdist_wheel" if name.endswith(".whl") else "sdist"
                ),
                "yanked": False,
                "url": urls[name],
            }
            for name, data in sorted(local.items())
        ],
    }
    public_bytes = {urls[name]: data for name, data in local.items()}

    class Response:
        def __init__(self, data: bytes, url: str) -> None:
            self.data = data
            self.url = url
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if size < 0:
                result = self.data[self.offset :]
                self.offset = len(self.data)
                return result
            result = self.data[self.offset : self.offset + size]
            self.offset += len(result)
            return result

        def geturl(self) -> str:
            return self.url

    def fake_urlopen(request, timeout: int):
        assert timeout == 30
        assert request.full_url == (
            "https://pypi.org/pypi/staqtapp-tds/3.8.2/json"
        )
        return Response(json.dumps(payload).encode(), request.full_url)

    class Opener:
        def open(self, request, timeout: int):
            assert timeout == 60
            return Response(public_bytes[request.full_url], request.full_url)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: Opener())
    monkeypatch.setenv("RELEASE_TAG", "v3.8.2")
    monkeypatch.chdir(tmp_path)
    source = _job_python(_workflow(RELEASE_PATH), "verify-production-pypi")
    exec(compile(source, "<public-verifier>", "exec"), {})

    wheel_name = "staqtapp_tds-3.8.2-py3-none-any.whl"
    wheel_url = urls[wheel_name]
    original_wheel = public_bytes[wheel_url]
    public_bytes[wheel_url] = bytes([original_wheel[0] ^ 1]) + original_wheel[1:]
    with pytest.raises(SystemExit, match="downloaded public bytes mismatch"):
        exec(compile(source, "<public-verifier>", "exec"), {})
    public_bytes[wheel_url] = original_wheel

    payload["urls"][0]["digests"]["sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="PyPI JSON identity mismatch"):
        exec(compile(source, "<public-verifier>", "exec"), {})


def test_smoke_completes_before_any_public_github_release_and_reentry_fails() -> None:
    source = _job_python(_workflow(RELEASE_PATH), "finalize-github-release")
    tree = ast.parse(source)
    assert any(
        isinstance(node, ast.Import)
        and any(alias.name == "re" for alias in node.names)
        for node in tree.body
    )
    dispatch_at = source.index(
        '"/actions/workflows/pypi-smoke.yml/dispatches"'
    )
    success_at = source.index('current.get("conclusion") != "success"')
    identity_job_at = source.index(
        '"Validate production release identity"'
    )
    release_post_at = source.index('"/releases"', identity_job_at)
    assert dispatch_at < success_at < identity_job_at < release_post_at
    assert source.count('api("GET", release_path, expected=(200, 404))') == 2
    assert "automatic finalizer " in source
    assert "re-entry is prohibited" in source
    assert "GitHub Release appeared during smoke" in source
    assert "completed_smoke is None" in source
    assert "30 minutes" in source
    assert 'current.get("status") == "completed"' in source

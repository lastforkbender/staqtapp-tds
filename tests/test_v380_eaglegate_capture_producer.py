from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import re

import pytest

from staqtapp_tds.eaglegate.capture_attestation import (
    CaptureReadOnlyStatusSnapshot,
    compare_capture_status,
)
from staqtapp_tds.eaglegate.capture_producer import (
    EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY,
    EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
    EAGLEGATE_CAPTURE_PRODUCER_DISTRIBUTION,
    EAGLEGATE_CAPTURE_PRODUCER_PROFILE_ID,
    CaptureProducerAuthorityBoundary,
    CaptureProducerLimits,
    CaptureProducerProfile,
    inspect_distribution_object,
    main as producer_main,
    normalize_distribution_name,
    produce_offline_capture,
    validate_distribution_member_path,
)
from staqtapp_tds.eaglegate.capture_producer_suite import (
    _SyntheticDistribution,
    _write_synthetic_distribution,
    run_reference_capture_producer_suite,
)
from staqtapp_tds.eaglegate.exactness_common import (
    EaglegateExactnessError,
    canonical_root,
)
from staqtapp_tds.eaglegate.vllm_shadow_suite import (
    reference_vllm_eagle_snapshot,
    snapshot_to_mapping,
)


def root(label: str) -> str:
    return canonical_root("capture-producer-test", {"label": label})


def test_producer_authority_is_fixed_and_non_executing():
    value = EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY.canonical_dict()
    assert value["may_inspect_distribution_metadata"] is True
    assert value["may_hash_distribution_files"] is True
    assert value["may_import_provider_runtime"] is False
    assert value["may_load_model"] is False
    assert value["may_read_model_artifact"] is False
    assert value["may_probe_accelerator"] is False
    assert value["may_use_network"] is False
    assert value["may_spawn_subprocess"] is False
    assert value["may_execute_dynamic_code"] is False
    assert value["may_execute_inference"] is False
    assert value["may_accept_tokens"] is False
    assert value["may_commit_kv"] is False
    assert value["may_verify_source_commit"] is False
    assert value["may_activate"] is False
    with pytest.raises(EaglegateExactnessError, match="cannot be widened"):
        CaptureProducerAuthorityBoundary(may_import_provider_runtime=True)


def test_profile_is_immutable_closed_and_source_commit_unverified():
    profile = CaptureProducerProfile(source_commit_root=root("source"))
    assert profile.provider_id == "vllm-eagle-v1"
    assert profile.distribution_name == "vllm"
    assert profile.profile_id == EAGLEGATE_CAPTURE_PRODUCER_PROFILE_ID
    with pytest.raises(FrozenInstanceError):
        profile.capture_sequence = 2  # type: ignore[misc]
    with pytest.raises(EaglegateExactnessError, match="unsupported capture provider"):
        replace(profile, provider_id="other")
    with pytest.raises(EaglegateExactnessError, match="only the vllm distribution"):
        replace(profile, distribution_name="torch")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("vllm", "vllm"),
        ("VLLM", "vllm"),
        ("vllm_runtime", "vllm-runtime"),
        ("vllm.runtime", "vllm-runtime"),
    ],
)
def test_distribution_name_normalization(value: str, expected: str):
    assert normalize_distribution_name(value) == expected


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/absolute.py",
        "weights/model.safetensors",
        "weights/model.gguf",
        "weights/model.pt",
        "weights/model.onnx",
    ],
)
def test_unsafe_distribution_paths_are_rejected(path: str):
    with pytest.raises(EaglegateExactnessError):
        validate_distribution_member_path(path)


def test_distribution_inspection_is_byte_deterministic(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = inspect_distribution_object(
        _write_synthetic_distribution(first_root), expected_name="vllm"
    )
    second = inspect_distribution_object(
        _write_synthetic_distribution(second_root), expected_name="VLLM"
    )
    assert first == second
    assert first.distribution_root == second.distribution_root
    assert first.file_count == 5
    assert first.total_bytes > 0


def test_package_byte_change_changes_distribution_identity(tmp_path: Path):
    distribution = _write_synthetic_distribution(tmp_path)
    before = inspect_distribution_object(distribution, expected_name="vllm")
    (tmp_path / "vllm" / "engine.py").write_text(
        "CAPABILITY_ONLY = False\n", encoding="utf-8", newline="\n"
    )
    after = inspect_distribution_object(distribution, expected_name="vllm")
    assert before.file_manifest_root != after.file_manifest_root
    assert before.distribution_root != after.distribution_root


def test_name_missing_metadata_and_duplicate_files_fail_closed(tmp_path: Path):
    distribution = _write_synthetic_distribution(tmp_path / "name")
    with pytest.raises(EaglegateExactnessError, match="name mismatch"):
        inspect_distribution_object(
            _SyntheticDistribution(tmp_path / "name", name="other"),
            expected_name="vllm",
        )

    missing_root = tmp_path / "missing"
    missing = _write_synthetic_distribution(missing_root)
    (missing_root / "vllm-0.0.0.dist-info" / "WHEEL").unlink()
    with pytest.raises(EaglegateExactnessError, match="required WHEEL"):
        inspect_distribution_object(missing, expected_name="vllm")

    duplicate_root = tmp_path / "duplicate"
    duplicate = _write_synthetic_distribution(duplicate_root)
    duplicated = _SyntheticDistribution(
        duplicate_root, files=duplicate.files + (duplicate.files[0],)
    )
    with pytest.raises(EaglegateExactnessError, match="duplicate file paths"):
        inspect_distribution_object(duplicated, expected_name="vllm")


def test_file_count_and_byte_budgets_fail_closed(tmp_path: Path):
    distribution = _write_synthetic_distribution(tmp_path)
    with pytest.raises(EaglegateExactnessError, match="file-count"):
        inspect_distribution_object(
            distribution,
            expected_name="vllm",
            limits=CaptureProducerLimits(max_files=1),
        )
    with pytest.raises(EaglegateExactnessError, match="byte limit"):
        inspect_distribution_object(
            distribution,
            expected_name="vllm",
            limits=CaptureProducerLimits(
                max_file_bytes=64,
                max_total_bytes=64,
                max_metadata_bytes=4096,
            ),
        )


def test_symlinked_distribution_member_is_rejected_when_supported(tmp_path: Path):
    distribution = _write_synthetic_distribution(tmp_path)
    target = tmp_path / "vllm" / "engine.py"
    link = tmp_path / "vllm" / "linked.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")
    files = distribution.files + (type(distribution.files[0])("vllm/linked.py"),)
    linked = _SyntheticDistribution(tmp_path, files=files)
    with pytest.raises(EaglegateExactnessError, match="symlinked"):
        inspect_distribution_object(linked, expected_name="vllm")


def test_produced_bundle_passes_importer_and_exact_witness(tmp_path: Path):
    inspection = inspect_distribution_object(
        _write_synthetic_distribution(tmp_path), expected_name="vllm"
    )
    result = produce_offline_capture(
        snapshot_to_mapping(reference_vllm_eagle_snapshot()),
        inspection,
        CaptureProducerProfile(source_commit_root=root("source")),
    )
    assert result.decision.compatible is True
    assert result.canonical_dict()["source_commit_verified"] is False
    assert result.canonical_dict()["provider_runtime_imported"] is False
    assert result.canonical_dict()["model_artifact_read"] is False
    status = CaptureReadOnlyStatusSnapshot(
        provider_id=result.envelope.provider_id,
        capture_root=result.envelope.capture_root,
        provider_snapshot_payload_root=result.decision.provider_snapshot_payload_root,
        adapter_identity_root=result.decision.adapter_identity_root,
        runtime_distribution_root=result.envelope.runtime_distribution_root,
        package_metadata_root=result.envelope.package_metadata_root,
        source_commit_root=result.envelope.source_commit_root,
        environment_root=result.envelope.environment_root,
        service_instance_root=root("service"),
        status_exporter_root=root("exporter"),
        snapshot_generation=1,
    )
    observation = compare_capture_status(
        result.envelope,
        result.decision,
        status,
        witness_id="producer-test",
        witness_tool_root=root("witness-tool"),
    )
    assert observation.matched is True


def test_provider_version_mismatch_is_rejected(tmp_path: Path):
    inspection = inspect_distribution_object(
        _write_synthetic_distribution(tmp_path), expected_name="vllm"
    )
    snapshot = replace(reference_vllm_eagle_snapshot(), runtime_version="0.0.1")
    with pytest.raises(EaglegateExactnessError, match="version does not match"):
        produce_offline_capture(
            snapshot_to_mapping(snapshot),
            inspection,
            CaptureProducerProfile(source_commit_root=root("source")),
        )


def test_reference_suite_is_deterministic_content_free_and_non_qualifying():
    first = run_reference_capture_producer_suite()
    second = run_reference_capture_producer_suite()
    assert first.passed
    assert len(first.checks) == 10
    assert first.report_root == second.report_root
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    expected_false = (
        "source_commit_verified",
        "provider_runtime_imported",
        "model_artifact_read",
        "model_loaded",
        "accelerator_probed",
        "network_used",
        "subprocess_used",
        "dynamic_code_executed",
        "inference_performed",
        "token_acceptance_authority",
        "kv_commit_authority",
        "activation_authority",
        "real_runtime_qualified",
    )
    assert all(payload[name] is False for name in expected_false)


def test_source_has_no_provider_runtime_network_subprocess_or_dynamic_imports():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "staqtapp_tds"
        / "eaglegate"
        / "capture_producer.py"
    ).read_text(encoding="utf-8")
    forbidden_import = re.compile(
        r"^\s*(?:from|import)\s+(?:vllm|torch|requests|urllib|socket|subprocess|http\.client|pynvml|cuda)\b",
        re.MULTILINE,
    )
    assert forbidden_import.search(source) is None
    for forbidden in (
        "importlib.import_module(",
        "__import__(",
        "eval(",
        "exec(",
        "os.system(",
        "Popen(",
    ):
        assert forbidden not in source


def test_cli_missing_distribution_is_structured_target_only(
    tmp_path: Path, capsys, monkeypatch
):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            snapshot_to_mapping(reference_vllm_eagle_snapshot()), sort_keys=True
        ),
        encoding="utf-8",
    )

    def missing(_name):
        from importlib.metadata import PackageNotFoundError

        raise PackageNotFoundError("vllm")

    monkeypatch.setattr("importlib.metadata.distribution", missing)
    assert producer_main(
        [
            "--provider-snapshot",
            str(snapshot_path),
            "--source-commit-root",
            root("source"),
            "--json",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["fault"] == "capture_producer_rejected"
    assert payload["serving_effect"] == "target_only"
    assert payload["provider_runtime_imported"] is False
    assert payload["model_loaded"] is False
    assert payload["activation_authority"] is False


def test_contract_ids_are_explicit():
    assert (
        EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID
        == "tds-eaglegate-isolated-capture-producer-v1"
    )
    assert EAGLEGATE_CAPTURE_PRODUCER_DISTRIBUTION == "vllm"

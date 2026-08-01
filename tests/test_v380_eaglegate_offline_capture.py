from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import re

import pytest

from staqtapp_tds.eaglegate.exactness_common import EaglegateExactnessError
from staqtapp_tds.eaglegate.offline_capture import (
    EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY,
    EAGLEGATE_OFFLINE_CAPTURE_BUNDLE_ID,
    EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID,
    EAGLEGATE_VLLM_EAGLE_PROVIDER_ID,
    OfflineCapabilityCaptureEnvelope,
    OfflineCaptureAuthorityBoundary,
    OfflineCaptureFault,
    capture_envelope_to_mapping,
    main as capture_main,
    provider_snapshot_payload_root,
    validate_offline_capability_capture,
)
from staqtapp_tds.eaglegate.offline_capture_suite import (
    capture_bundle_to_mapping,
    reference_offline_capture_bundle,
    run_reference_offline_capture_suite,
)


def test_authority_is_fixed_and_import_only():
    value = EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY.canonical_dict()
    assert value["metadata_import_only"] is True
    assert value["tds_runtime_import_allowed"] is False
    assert value["model_loading_allowed"] is False
    assert value["inference_allowed"] is False
    assert value["network_io_allowed"] is False
    assert value["subprocess_allowed"] is False
    assert value["token_acceptance_authority"] is False
    assert value["target_rng_authority"] is False
    assert value["kv_commit_authority"] is False
    assert value["activation_authority"] is False
    assert value["raw_content_persistence_allowed"] is False
    assert value["target_only_execution_required"] is True
    with pytest.raises(EaglegateExactnessError, match="cannot be widened"):
        OfflineCaptureAuthorityBoundary(activation_authority=True)


def test_envelope_is_canonical_immutable_and_roundtrips():
    envelope, _ = reference_offline_capture_bundle()
    restored = OfflineCapabilityCaptureEnvelope.from_mapping(
        capture_envelope_to_mapping(envelope)
    )
    assert restored == envelope
    assert restored.capture_root == envelope.capture_root
    with pytest.raises(FrozenInstanceError):
        envelope.capture_sequence = 2  # type: ignore[misc]


def test_valid_capture_translates_without_runtime_authority():
    envelope, snapshot = reference_offline_capture_bundle()
    decision = validate_offline_capability_capture(envelope, snapshot)
    payload = decision.to_dict()
    assert decision.compatible is True
    assert decision.fault is OfflineCaptureFault.NONE
    assert payload["serving_effect"] == "shadow_metadata_only"
    assert payload["runtime_imported_by_tds"] is False
    assert payload["model_invoked"] is False
    assert payload["inference_performed"] is False
    assert payload["token_acceptance_authority"] is False
    assert payload["kv_commit_authority"] is False
    assert payload["activation_authority"] is False
    assert payload["real_runtime_qualified"] is False


def test_payload_tamper_is_target_only():
    envelope, snapshot = reference_offline_capture_bundle()
    tampered = dict(snapshot)
    tampered["runtime_version"] = "0.0.1"
    decision = validate_offline_capability_capture(envelope, tampered)
    assert decision.fault is OfflineCaptureFault.PAYLOAD_MISMATCH
    assert decision.to_dict()["serving_effect"] == "target_only"


def test_unknown_provider_is_target_only():
    envelope, snapshot = reference_offline_capture_bundle()
    decision = validate_offline_capability_capture(
        replace(envelope, provider_id="unknown-provider-v1"), snapshot
    )
    assert decision.fault is OfflineCaptureFault.UNSUPPORTED_PROVIDER
    assert decision.to_dict()["serving_effect"] == "target_only"


def test_adapter_conformance_cannot_be_rebound():
    envelope, snapshot = reference_offline_capture_bundle()
    wrong = replace(
        envelope,
        adapter_conformance_root=provider_snapshot_payload_root(
            {"label": "wrong-adapter"}
        ),
    )
    decision = validate_offline_capability_capture(wrong, snapshot)
    assert decision.fault is OfflineCaptureFault.ADAPTER_MISMATCH
    assert decision.to_dict()["serving_effect"] == "target_only"


def test_invalid_provider_snapshot_is_structured_target_only():
    envelope, snapshot = reference_offline_capture_bundle()
    invalid = dict(snapshot)
    del invalid["runtime_version"]
    envelope = replace(
        envelope,
        provider_snapshot_payload_root=provider_snapshot_payload_root(invalid),
    )
    decision = validate_offline_capability_capture(envelope, invalid)
    assert decision.fault is OfflineCaptureFault.INVALID_BUNDLE
    assert decision.to_dict()["serving_effect"] == "target_only"


@pytest.mark.parametrize(
    "key",
    [
        "prompt",
        "prompt_text",
        "tokens",
        "token_sequence",
        "logits",
        "logits_payload",
        "hidden_states",
        "kv_tensor",
        "kv_tensors",
    ],
)
def test_content_bearing_provider_fields_are_rejected(key: str):
    envelope, snapshot = reference_offline_capture_bundle()
    content = {**snapshot, key: "forbidden"}
    envelope = replace(
        envelope,
        provider_snapshot_payload_root=provider_snapshot_payload_root(content),
    )
    decision = validate_offline_capability_capture(envelope, content)
    assert decision.fault is OfflineCaptureFault.CONTENT_REJECTED
    assert decision.to_dict()["serving_effect"] == "target_only"


@pytest.mark.parametrize(
    "field",
    ["model_loaded", "inference_performed", "network_used", "subprocess_used"],
)
def test_capture_cannot_attest_forbidden_activity(field: str):
    envelope, _ = reference_offline_capture_bundle()
    with pytest.raises(EaglegateExactnessError, match="forbidden runtime activity"):
        replace(envelope, **{field: True})


def test_unknown_and_missing_envelope_fields_fail_closed():
    envelope, _ = reference_offline_capture_bundle()
    mapping = capture_envelope_to_mapping(envelope)
    with pytest.raises(EaglegateExactnessError, match="unknown offline capture fields"):
        OfflineCapabilityCaptureEnvelope.from_mapping(
            {**mapping, "execute": True}
        )
    del mapping["provider_id"]
    with pytest.raises(EaglegateExactnessError, match="invalid offline capture fields"):
        OfflineCapabilityCaptureEnvelope.from_mapping(mapping)


def test_reference_suite_is_deterministic_content_free_and_non_qualifying():
    first = run_reference_offline_capture_suite()
    second = run_reference_offline_capture_suite()
    assert first.passed
    assert len(first.checks) == 10
    assert first.report_root == second.report_root
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    assert payload["runtime_imported_by_tds"] is False
    assert payload["model_invoked"] is False
    assert payload["inference_performed"] is False
    assert payload["activation_authority"] is False
    assert payload["real_runtime_qualified"] is False


def test_importer_source_has_no_runtime_network_or_subprocess_imports():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "staqtapp_tds"
        / "eaglegate"
        / "offline_capture.py"
    ).read_text(encoding="utf-8")
    forbidden_import = re.compile(
        r"^\s*(?:from|import)\s+(?:vllm|torch|requests|urllib|socket|subprocess|http\.client)\b",
        re.MULTILINE,
    )
    assert forbidden_import.search(source) is None
    assert "os.system(" not in source
    assert "Popen(" not in source


def test_capture_cli_accepts_complete_bundle_without_execution(
    tmp_path: Path, capsys
):
    envelope, snapshot = reference_offline_capture_bundle()
    path = tmp_path / "capture.json"
    path.write_text(
        json.dumps(capture_bundle_to_mapping(envelope, snapshot), sort_keys=True),
        encoding="utf-8",
    )
    assert capture_main(["--bundle", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["compatible"] is True
    assert payload["runtime_imported_by_tds"] is False
    assert payload["model_invoked"] is False
    assert payload["activation_authority"] is False


def test_capture_cli_malformed_bundle_is_structured_target_only(
    tmp_path: Path, capsys
):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps({"execute": True}), encoding="utf-8")
    assert capture_main(["--bundle", str(path), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["fault"] == "invalid_bundle"
    assert payload["serving_effect"] == "target_only"
    assert payload["runtime_imported_by_tds"] is False
    assert payload["activation_authority"] is False


def test_contract_ids_and_provider_are_explicit():
    assert (
        EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID
        == "tds-eaglegate-offline-capture-v1"
    )
    assert (
        EAGLEGATE_OFFLINE_CAPTURE_BUNDLE_ID
        == "tds-eaglegate-offline-capture-bundle-v1"
    )
    assert EAGLEGATE_VLLM_EAGLE_PROVIDER_ID == "vllm-eagle-v1"

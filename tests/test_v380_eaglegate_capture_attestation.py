from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import re

import pytest

from staqtapp_tds.eaglegate.capture_attestation import (
    EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY,
    EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID,
    EAGLEGATE_CAPTURE_ATTESTATION_MIN_WITNESSES,
    CaptureAttestationAuthorityBoundary,
    CaptureAttestationBundle,
    CaptureAttestationDecision,
    CaptureObservationState,
    CaptureReadOnlyStatusSnapshot,
    canonicalize_observations,
    compare_capture_status,
    main as witness_main,
    next_observation_receipt,
    record_attestation_bundle,
    validate_observation_chain,
)
from staqtapp_tds.eaglegate.capture_attestation_suite import (
    reference_capture_attestation_bundle,
    reference_capture_observations,
    reference_capture_status,
    run_reference_capture_attestation_suite,
)
from staqtapp_tds.eaglegate.exactness_common import EaglegateExactnessError
from staqtapp_tds.eaglegate.offline_capture import (
    validate_offline_capability_capture,
)
from staqtapp_tds.eaglegate.offline_capture_suite import (
    capture_bundle_to_mapping,
    reference_offline_capture_bundle,
)


def test_authority_is_fixed_mechanical_only():
    value = EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY.canonical_dict()
    assert value["may_import_runtime"] is False
    assert value["may_connect_network"] is False
    assert value["may_submit_request"] is False
    assert value["may_load_model"] is False
    assert value["may_allocate_kv"] is False
    assert value["may_generate_tokens"] is False
    assert value["may_verify_tokens"] is False
    assert value["may_commit_tokens"] is False
    assert value["may_verify_cryptographic_signature"] is False
    assert value["may_claim_witness_independence"] is False
    assert value["may_claim_metadata_truth"] is False
    assert value["may_record_mechanical_corroboration"] is True
    assert value["may_activate"] is False
    with pytest.raises(EaglegateExactnessError, match="cannot be widened"):
        CaptureAttestationAuthorityBoundary(may_activate=True)


def test_status_snapshot_is_strict_immutable_and_deterministic():
    first = reference_capture_status()
    second = reference_capture_status()
    assert first.snapshot_root == second.snapshot_root
    with pytest.raises(FrozenInstanceError):
        first.snapshot_generation = 2  # type: ignore[misc]
    with pytest.raises(EaglegateExactnessError, match="unknown status snapshot fields"):
        CaptureReadOnlyStatusSnapshot.from_mapping(
            {**first.comparable_dict(), "execute": True}
        )
    with pytest.raises(EaglegateExactnessError, match="read-only metadata"):
        replace(first, model_loaded=True)


def test_exact_comparison_matches_reference_capture():
    envelope, snapshot = reference_offline_capture_bundle()
    decision = validate_offline_capability_capture(envelope, snapshot)
    observation = compare_capture_status(
        envelope,
        decision,
        reference_capture_status(),
        witness_id="witness-test",
        witness_tool_root=reference_capture_observations()[0].witness_tool_root,
    )
    assert observation.matched is True
    assert observation.mismatch_fields == ()


def test_mismatch_fields_are_sorted_and_target_only():
    envelope, snapshot = reference_offline_capture_bundle()
    decision = validate_offline_capability_capture(envelope, snapshot)
    status = replace(
        reference_capture_status(),
        environment_root=reference_capture_observations()[0].witness_tool_root,
        source_commit_root=reference_capture_observations()[1].witness_tool_root,
    )
    observation = compare_capture_status(
        envelope,
        decision,
        status,
        witness_id="witness-mismatch",
        witness_tool_root=reference_capture_observations()[0].witness_tool_root,
    )
    assert observation.matched is False
    assert observation.mismatch_fields == (
        "environment_root",
        "source_commit_root",
    )


def test_two_distinct_witnesses_are_required_and_canonical():
    bundle = reference_capture_attestation_bundle()
    assert bundle.required_witnesses == EAGLEGATE_CAPTURE_ATTESTATION_MIN_WITNESSES
    assert bundle.decision is CaptureAttestationDecision.CORROBORATED
    roots = [item.observation_root for item in bundle.observations]
    assert roots == sorted(roots)
    with pytest.raises(EaglegateExactnessError, match="witness quorum"):
        CaptureAttestationBundle(
            bundle.capture_root,
            bundle.provider_snapshot_payload_root,
            bundle.adapter_identity_root,
            (bundle.observations[0],),
        )


def test_duplicate_witness_and_tool_cannot_inflate_quorum():
    bundle = reference_capture_attestation_bundle()
    first, second = bundle.observations
    with pytest.raises(EaglegateExactnessError, match="duplicate witness identity"):
        duplicate = replace(second, witness_id=first.witness_id)
        CaptureAttestationBundle(
            bundle.capture_root,
            bundle.provider_snapshot_payload_root,
            bundle.adapter_identity_root,
            canonicalize_observations((first, duplicate)),
        )
    with pytest.raises(EaglegateExactnessError, match="duplicate witness tool"):
        duplicate = replace(second, witness_tool_root=first.witness_tool_root)
        CaptureAttestationBundle(
            bundle.capture_root,
            bundle.provider_snapshot_payload_root,
            bundle.adapter_identity_root,
            canonicalize_observations((first, duplicate)),
        )


def test_corroborated_history_is_append_only_and_retirable():
    bundle = reference_capture_attestation_bundle()
    chain = record_attestation_bundle(bundle)
    assert tuple(item.state for item in chain) == (
        CaptureObservationState.RECEIVED,
        CaptureObservationState.CORROBORATED,
        CaptureObservationState.RECORDED,
    )
    retired = next_observation_receipt(
        chain[-1], CaptureObservationState.RETIRED
    )
    validated = validate_observation_chain((*chain, retired))
    assert validated[-1].state is CaptureObservationState.RETIRED
    with pytest.raises(EaglegateExactnessError, match="illegal"):
        next_observation_receipt(retired, CaptureObservationState.RECORDED)


def test_mismatch_history_is_quarantined_and_terminal():
    bundle = reference_capture_attestation_bundle()
    first, second = bundle.observations
    mismatch = replace(
        second,
        matched=False,
        mismatch_fields=("environment_root",),
    )
    mismatch_bundle = CaptureAttestationBundle(
        bundle.capture_root,
        bundle.provider_snapshot_payload_root,
        bundle.adapter_identity_root,
        canonicalize_observations((first, mismatch)),
    )
    chain = record_attestation_bundle(mismatch_bundle)
    assert chain[-1].state is CaptureObservationState.QUARANTINED
    with pytest.raises(EaglegateExactnessError, match="illegal"):
        next_observation_receipt(
            chain[-1], CaptureObservationState.CORROBORATED
        )


def test_forged_predecessor_and_identity_drift_are_rejected():
    chain = record_attestation_bundle(reference_capture_attestation_bundle())
    with pytest.raises(EaglegateExactnessError, match="predecessor"):
        validate_observation_chain(
            (
                chain[0],
                replace(
                    chain[1],
                    previous_receipt_root=reference_capture_status().snapshot_root,
                ),
                chain[2],
            )
        )
    with pytest.raises(EaglegateExactnessError, match="identity changed"):
        validate_observation_chain(
            (
                chain[0],
                replace(
                    chain[1],
                    adapter_identity_root=reference_capture_status().snapshot_root,
                ),
            )
        )


def test_reference_suite_is_deterministic_content_free_and_non_qualifying():
    first = run_reference_capture_attestation_suite()
    second = run_reference_capture_attestation_suite()
    assert first.passed
    assert len(first.checks) == 10
    assert first.report_root == second.report_root
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    expected_false = (
        "runtime_imported_by_tds",
        "network_connection_created_by_tds",
        "request_submitted_by_tds",
        "model_invoked",
        "inference_performed",
        "token_acceptance_authority",
        "kv_commit_authority",
        "cryptographic_signature_verified",
        "witness_independence_proven",
        "metadata_truth_claimed",
        "activation_authority",
        "real_runtime_qualified",
    )
    assert all(payload[name] is False for name in expected_false)


def test_source_has_no_runtime_network_crypto_or_subprocess_imports():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "staqtapp_tds"
        / "eaglegate"
        / "capture_attestation.py"
    ).read_text(encoding="utf-8")
    forbidden_import = re.compile(
        r"^\s*(?:from|import)\s+(?:vllm|torch|requests|urllib|socket|subprocess|cryptography|nacl|http\.client)\b",
        re.MULTILINE,
    )
    assert forbidden_import.search(source) is None
    assert "os.system(" not in source
    assert "Popen(" not in source


def test_single_witness_cli_is_explicitly_non_quorum(tmp_path: Path, capsys):
    envelope, snapshot = reference_offline_capture_bundle()
    bundle_path = tmp_path / "capture.json"
    status_path = tmp_path / "status.json"
    bundle_path.write_text(
        json.dumps(capture_bundle_to_mapping(envelope, snapshot), sort_keys=True),
        encoding="utf-8",
    )
    status = reference_capture_status()
    status_path.write_text(
        json.dumps(
            status.comparable_dict()
            | {
                "service_instance_root": status.service_instance_root,
                "status_exporter_root": status.status_exporter_root,
                "snapshot_generation": 1,
                "read_only_export": True,
                "metadata_only": True,
                "model_loaded": False,
                "inference_performed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    tool_root = reference_capture_observations()[0].witness_tool_root
    assert witness_main(
        [
            "--bundle",
            str(bundle_path),
            "--status",
            str(status_path),
            "--witness-id",
            "witness-cli",
            "--witness-tool-root",
            tool_root,
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matched"] is True
    assert payload["single_witness_only"] is True
    assert payload["quorum_satisfied"] is False
    assert payload["serving_effect"] == "target_only"
    assert payload["activation_authority"] is False


def test_contract_id_is_explicit():
    assert (
        EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID
        == "tds-eaglegate-capture-attestation-v1"
    )

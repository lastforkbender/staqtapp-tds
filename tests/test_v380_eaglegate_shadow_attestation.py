from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from staqtapp_tds.eaglegate.attestation import main
from staqtapp_tds.eaglegate.attestation_contract import (
    AttestationDecision,
    EAGLEGATE_ATTESTATION_AUTHORITY,
    EaglegateAttestationAuthorityBoundary,
    ObservationState,
    ShadowObservationReceipt,
    next_observation_receipt,
    validate_observation_chain,
)
from staqtapp_tds.eaglegate.attestation_suite import (
    run_reference_attestation_suite,
)
from staqtapp_tds.eaglegate.attestation_vllm import (
    build_capability_attestation_bundle,
    build_shadow_observation_chain,
    compare_vllm_shadow_status,
    parse_vllm_read_only_status,
)
from staqtapp_tds.eaglegate.exactness_common import EaglegateExactnessError
from staqtapp_tds.eaglegate.shadow_vllm import parse_vllm_eagle_metadata


ROOT = Path(__file__).resolve().parents[1]


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("ascii")).hexdigest()


def _metadata_dict(**overrides):
    value = {
        "runtime_version": "0.22.0",
        "method": "eagle",
        "foundation_identity_root": _root("foundation"),
        "target_model_root": _root("target-model"),
        "tokenizer_root": _root("tokenizer"),
        "draft_model_root": _root("draft-model"),
        "adapter_build_root": _root("adapter-build"),
        "target_verifier_root": _root("target-verifier"),
        "rng_contract_root": _root("rng"),
        "sampler_order_root": _root("sampler"),
        "logits_processor_order_root": _root("logits"),
        "termination_contract_root": _root("termination"),
        "kv_allocator_root": _root("kv"),
        "numerical_kernel_root": _root("kernel"),
        "deadline_contract_root": _root("deadline"),
        "capability_source_root": _root("source"),
        "metadata_attestation_root": _root("attestation"),
        "num_speculative_tokens": 3,
        "draft_tensor_parallel_size": 1,
        "target_tensor_parallel_size": 4,
        "max_model_len": 32768,
        "parallel_drafting": False,
        "rejection_sample_method": "strict",
    }
    value.update(overrides)
    return value


def _metadata(**overrides):
    return parse_vllm_eagle_metadata(_metadata_dict(**overrides))


def _status_dict(metadata=None, label="a", **overrides):
    metadata = metadata or _metadata()
    value = {
        "runtime_version": metadata.runtime_version,
        "method": metadata.method,
        "foundation_identity_root": metadata.foundation_identity_root,
        "target_model_root": metadata.target_model_root,
        "tokenizer_root": metadata.tokenizer_root,
        "draft_model_root": metadata.draft_model_root,
        "adapter_build_root": metadata.adapter_build_root,
        "target_verifier_root": metadata.target_verifier_root,
        "rng_contract_root": metadata.rng_contract_root,
        "sampler_order_root": metadata.sampler_order_root,
        "logits_processor_order_root": metadata.logits_processor_order_root,
        "termination_contract_root": metadata.termination_contract_root,
        "kv_allocator_root": metadata.kv_allocator_root,
        "numerical_kernel_root": metadata.numerical_kernel_root,
        "deadline_contract_root": metadata.deadline_contract_root,
        "num_speculative_tokens": metadata.num_speculative_tokens,
        "draft_tensor_parallel_size": metadata.draft_tensor_parallel_size,
        "target_tensor_parallel_size": metadata.target_tensor_parallel_size,
        "max_model_len": metadata.max_model_len,
        "parallel_drafting": metadata.parallel_drafting,
        "rejection_sample_method": metadata.rejection_sample_method,
        "service_instance_root": _root(f"service-{label}"),
        "status_exporter_root": _root(f"exporter-{label}"),
        "snapshot_generation": 1,
    }
    value.update(overrides)
    return value


def _status(metadata=None, label="a", **overrides):
    return parse_vllm_read_only_status(
        _status_dict(metadata, label, **overrides)
    )


def _witness(metadata, status, witness_id, tool_label=None, shadow=None):
    return compare_vllm_shadow_status(
        metadata,
        status,
        shadow_report_root=shadow or _root("shadow-report"),
        witness_id=witness_id,
        witness_tool_root=_root(tool_label or f"tool-{witness_id}"),
    )


def test_attestation_authority_is_non_widenable():
    authority = EAGLEGATE_ATTESTATION_AUTHORITY
    assert authority.may_import_runtime is False
    assert authority.may_connect_network is False
    assert authority.may_submit_request is False
    assert authority.may_verify_cryptographic_signature is False
    assert authority.may_claim_witness_independence is False
    assert authority.may_claim_metadata_truth is False
    assert authority.may_activate is False
    with pytest.raises(EaglegateExactnessError, match="cannot be widened"):
        EaglegateAttestationAuthorityBoundary(may_connect_network=True)


def test_read_only_status_is_strict_and_deterministic():
    first = _status()
    second = _status()
    assert first.snapshot_root == second.snapshot_root
    assert first.read_only_export is True
    with pytest.raises(EaglegateExactnessError, match="unknown"):
        parse_vllm_read_only_status(_status_dict(unexpected="value"))
    missing = _status_dict()
    missing.pop("rng_contract_root")
    with pytest.raises(EaglegateExactnessError, match="missing"):
        parse_vllm_read_only_status(missing)


def test_matching_status_produces_content_free_witness_observation():
    metadata = _metadata()
    observation = _witness(metadata, _status(metadata), "witness-a")
    assert observation.matched
    assert observation.mismatch_fields == ()
    payload = observation.canonical_dict()
    assert payload["runtime_imported_by_tds"] is False
    assert payload["network_connection_created_by_tds"] is False
    assert payload["cryptographic_signature_verified"] is False
    assert payload["witness_independence_proven"] is False


def test_any_exact_field_mismatch_is_recorded_and_target_only():
    metadata = _metadata()
    observation = _witness(
        metadata,
        _status(metadata, rng_contract_root=_root("different-rng")),
        "witness-a",
    )
    assert observation.matched is False
    assert observation.mismatch_fields == ("rng_contract_root",)
    matching = _witness(metadata, _status(metadata, "b"), "witness-b")
    bundle = build_capability_attestation_bundle((observation, matching))
    assert bundle.decision is AttestationDecision.TARGET_ONLY
    assert build_shadow_observation_chain(bundle)[-1].state is ObservationState.QUARANTINED


def test_two_distinct_matching_witnesses_mechanically_corroborate():
    metadata = _metadata()
    first = _witness(metadata, _status(metadata, "a"), "witness-a")
    second = _witness(metadata, _status(metadata, "b"), "witness-b")
    bundle = build_capability_attestation_bundle((first, second))
    assert bundle.decision is AttestationDecision.CORROBORATED
    assert bundle.canonical_dict()["witness_independence_proven"] is False
    assert bundle.canonical_dict()["metadata_truth_claimed"] is False
    assert bundle.canonical_dict()["real_runtime_qualified"] is False


def test_single_witness_cannot_satisfy_quorum():
    metadata = _metadata()
    witness = _witness(metadata, _status(metadata), "witness-a")
    with pytest.raises(EaglegateExactnessError, match="quorum"):
        build_capability_attestation_bundle((witness,))


def test_duplicate_witness_or_tool_cannot_inflate_quorum():
    metadata = _metadata()
    first = _witness(metadata, _status(metadata, "a"), "witness-a")
    second = _witness(metadata, _status(metadata, "b"), "witness-b")
    with pytest.raises(EaglegateExactnessError, match="duplicate witness"):
        build_capability_attestation_bundle(
            (first, replace(second, witness_id=first.witness_id))
        )
    with pytest.raises(EaglegateExactnessError, match="duplicate witness tool"):
        build_capability_attestation_bundle(
            (first, replace(second, witness_tool_root=first.witness_tool_root))
        )


def test_witnesses_must_bind_identical_metadata_and_shadow_roots():
    metadata = _metadata()
    first = _witness(metadata, _status(metadata, "a"), "witness-a")
    second = _witness(metadata, _status(metadata, "b"), "witness-b")
    with pytest.raises(EaglegateExactnessError, match="metadata root mismatch"):
        build_capability_attestation_bundle(
            (first, replace(second, metadata_root=_root("other-metadata")))
        )
    with pytest.raises(EaglegateExactnessError, match="shadow root mismatch"):
        build_capability_attestation_bundle(
            (first, replace(second, shadow_report_root=_root("other-shadow")))
        )


def test_matching_bundle_builds_append_only_recorded_chain():
    metadata = _metadata()
    bundle = build_capability_attestation_bundle(
        (
            _witness(metadata, _status(metadata, "a"), "witness-a"),
            _witness(metadata, _status(metadata, "b"), "witness-b"),
        )
    )
    chain = build_shadow_observation_chain(bundle)
    assert tuple(receipt.state for receipt in chain) == (
        ObservationState.RECEIVED,
        ObservationState.CORROBORATED,
        ObservationState.RECORDED,
    )
    assert validate_observation_chain(chain) == chain


def test_forged_predecessor_or_identity_change_is_rejected():
    metadata = _metadata()
    bundle = build_capability_attestation_bundle(
        (
            _witness(metadata, _status(metadata, "a"), "witness-a"),
            _witness(metadata, _status(metadata, "b"), "witness-b"),
        )
    )
    chain = build_shadow_observation_chain(bundle)
    with pytest.raises(EaglegateExactnessError, match="predecessor"):
        validate_observation_chain(
            (chain[0], replace(chain[1], previous_receipt_root=_root("forged")))
        )
    with pytest.raises(EaglegateExactnessError, match="identity changed"):
        validate_observation_chain(
            (chain[0], replace(chain[1], metadata_root=_root("changed")))
        )


def test_quarantine_and_retirement_are_terminal():
    metadata = _metadata()
    mismatch = _witness(
        metadata,
        _status(metadata, rng_contract_root=_root("different")),
        "witness-a",
    )
    matching = _witness(metadata, _status(metadata, "b"), "witness-b")
    quarantine = build_shadow_observation_chain(
        build_capability_attestation_bundle((mismatch, matching))
    )[-1]
    with pytest.raises(EaglegateExactnessError, match="illegal"):
        next_observation_receipt(quarantine, ObservationState.RECORDED)

    bundle = build_capability_attestation_bundle(
        (
            _witness(metadata, _status(metadata, "c"), "witness-c"),
            _witness(metadata, _status(metadata, "d"), "witness-d"),
        )
    )
    recorded = build_shadow_observation_chain(bundle)[-1]
    retired = next_observation_receipt(recorded, ObservationState.RETIRED)
    with pytest.raises(EaglegateExactnessError, match="illegal"):
        next_observation_receipt(retired, ObservationState.CORROBORATED)


def test_receipt_initial_and_non_initial_invariants_are_strict():
    with pytest.raises(EaglegateExactnessError, match="initial receipt"):
        ShadowObservationReceipt(
            sequence=0,
            state=ObservationState.CORROBORATED,
            metadata_root=_root("metadata"),
            shadow_report_root=_root("shadow"),
            attestation_root=_root("attestation"),
        )
    with pytest.raises(EaglegateExactnessError, match="requires predecessor"):
        ShadowObservationReceipt(
            sequence=1,
            state=ObservationState.CORROBORATED,
            metadata_root=_root("metadata"),
            shadow_report_root=_root("shadow"),
            attestation_root=_root("attestation"),
        )


def test_reference_suite_is_deterministic_and_non_activating():
    first = run_reference_attestation_suite()
    second = run_reference_attestation_suite()
    assert first.passed
    assert len(first.checks) == 10
    assert first.report_root == second.report_root
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    assert payload["cryptographic_signature_verified"] is False
    assert payload["witness_independence_proven"] is False
    assert payload["metadata_truth_claimed"] is False
    assert payload["real_runtime_qualified"] is False
    assert payload["activation_authority"] is False


def test_reference_cli_emits_deterministic_json(capsys):
    assert main(["reference", "--json"]) == 0
    first = capsys.readouterr().out
    assert main(["reference", "--json"]) == 0
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert payload["passed"] is True
    assert payload["check_count"] == 10
    assert payload["network_connection_created"] is False
    assert payload["metadata_truth_claimed"] is False


def test_compare_cli_uses_supplied_files_only(tmp_path, capsys):
    metadata = _metadata_dict()
    status = _status_dict(_metadata(), "cli")
    metadata_path = tmp_path / "metadata.json"
    status_path = tmp_path / "status.json"
    metadata_path.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
    status_path.write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    args = [
        "compare",
        "--metadata",
        str(metadata_path),
        "--status",
        str(status_path),
        "--shadow-root",
        _root("shadow-report"),
        "--witness-id",
        "witness-cli",
        "--witness-tool-root",
        _root("witness-tool"),
        "--json",
    ]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matched"] is True
    assert payload["network_connection_created_by_tds"] is False
    assert payload["cryptographic_signature_verified"] is False
    assert payload["metadata_truth_claimed"] is False
    assert payload["activation_authority"] is False


def test_fixture_source_has_no_network_runtime_or_crypto_claim_path():
    package = ROOT / "src" / "staqtapp_tds" / "eaglegate"
    sources = "\n".join(
        (package / name).read_text(encoding="utf-8")
        for name in (
            "attestation_contract.py",
            "attestation_vllm.py",
            "attestation_suite.py",
            "attestation.py",
        )
    )
    forbidden = (
        "import vllm",
        "from vllm",
        "requests.",
        "urllib.request",
        "socket.",
        "subprocess",
        "os.system",
        "Popen",
        "cryptography",
        "nacl",
    )
    assert all(term not in sources for term in forbidden)


def test_report_is_content_free_and_contains_no_signature_material():
    payload = run_reference_attestation_suite().to_dict()
    forbidden = {
        "prompt",
        "prompt_text",
        "tokens",
        "token_sequence",
        "logits",
        "logits_payload",
        "hidden_states",
        "kv_tensor",
        "kv_tensors",
        "signature",
        "public_key",
        "private_key",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert forbidden.isdisjoint(set(keys(payload)))

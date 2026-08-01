"""Reference witness-corroboration and observation-receipt qualification suite."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .attestation_contract import (
    AttestationDecision,
    EAGLEGATE_ATTESTATION_AUTHORITY,
    EAGLEGATE_ATTESTATION_CONTRACT_ID,
    ObservationState,
    VLLMReadOnlyStatusSnapshot,
    next_observation_receipt,
    validate_observation_chain,
)
from .attestation_vllm import (
    build_capability_attestation_bundle,
    build_shadow_observation_chain,
    compare_vllm_shadow_status,
)
from .exactness_common import (
    EaglegateExactnessError,
    canonical_root,
    require_ascii,
    require_root,
)
from .shadow_vllm import parse_vllm_eagle_metadata

EAGLEGATE_ATTESTATION_SUITE_ID = "eaglegate-reference-shadow-attestation-v1"


def _root(label: str) -> str:
    return canonical_root("attestation-fixture", {"label": label})


def _metadata():
    return parse_vllm_eagle_metadata(
        {
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
            "capability_source_root": _root("capability-source"),
            "metadata_attestation_root": _root("metadata-attestation"),
            "num_speculative_tokens": 3,
            "draft_tensor_parallel_size": 1,
            "target_tensor_parallel_size": 4,
            "max_model_len": 32768,
            "parallel_drafting": False,
            "rejection_sample_method": "strict",
        }
    )


def _status(metadata, label: str = "status", **overrides):
    values = {
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
    values.update(overrides)
    return VLLMReadOnlyStatusSnapshot(**values)


def _witness(metadata, status, witness: str, shadow_root: str):
    return compare_vllm_shadow_status(
        metadata,
        status,
        shadow_report_root=shadow_root,
        witness_id=witness,
        witness_tool_root=_root(f"tool-{witness}"),
    )


@dataclass(frozen=True, slots=True)
class AttestationQualificationCheck:
    name: str
    passed: bool
    evidence_root: str
    detail: str

    def __post_init__(self) -> None:
        require_ascii("name", self.name)
        if not isinstance(self.passed, bool):
            raise EaglegateExactnessError("passed must be boolean")
        require_root("evidence_root", self.evidence_root)
        require_ascii("detail", self.detail, allow_spaces=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence_root": self.evidence_root,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EaglegateAttestationQualificationReport:
    checks: tuple[AttestationQualificationCheck, ...]
    suite_id: str = EAGLEGATE_ATTESTATION_SUITE_ID

    def __post_init__(self) -> None:
        require_ascii("suite_id", self.suite_id)
        if not self.checks or any(
            not isinstance(check, AttestationQualificationCheck)
            for check in self.checks
        ):
            raise EaglegateExactnessError("invalid attestation check catalog")

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_ATTESTATION_CONTRACT_ID,
            "suite_id": self.suite_id,
            "passed": self.passed,
            "check_count": len(self.checks),
            "checks": [check.canonical_dict() for check in self.checks],
            "authority_root": EAGLEGATE_ATTESTATION_AUTHORITY.authority_root,
            "runtime_imported": False,
            "network_connection_created": False,
            "request_submitted": False,
            "model_loaded": False,
            "tokens_generated": False,
            "cryptographic_signature_verified": False,
            "witness_independence_proven": False,
            "metadata_truth_claimed": False,
            "real_runtime_qualified": False,
            "activation_authority": False,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
        }

    @property
    def report_root(self) -> str:
        return canonical_root("attestation-qualification-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def _content_free(value: Any) -> bool:
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
    }
    if isinstance(value, Mapping):
        return all(
            key not in forbidden and _content_free(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(_content_free(item) for item in value)
    return True


def run_reference_attestation_suite() -> EaglegateAttestationQualificationReport:
    metadata = _metadata()
    shadow_root = _root("shadow-report")
    witness_a = _witness(metadata, _status(metadata, "a"), "witness-a", shadow_root)
    witness_b = _witness(metadata, _status(metadata, "b"), "witness-b", shadow_root)
    matching_bundle = build_capability_attestation_bundle((witness_a, witness_b))
    matching_chain = build_shadow_observation_chain(matching_bundle)
    checks: list[AttestationQualificationCheck] = []

    checks.append(
        AttestationQualificationCheck(
            "two_witness_corroboration",
            matching_bundle.decision is AttestationDecision.CORROBORATED
            and tuple(receipt.state for receipt in matching_chain)
            == (
                ObservationState.RECEIVED,
                ObservationState.CORROBORATED,
                ObservationState.RECORDED,
            ),
            matching_bundle.attestation_root,
            "two distinct matching witnesses are mechanically corroborated",
        )
    )

    mismatch_status = _status(metadata, "mismatch", rng_contract_root=_root("rng-other"))
    mismatch_witness = _witness(
        metadata, mismatch_status, "witness-c", shadow_root
    )
    mismatch_bundle = build_capability_attestation_bundle(
        (witness_a, mismatch_witness)
    )
    mismatch_chain = build_shadow_observation_chain(mismatch_bundle)
    checks.append(
        AttestationQualificationCheck(
            "mismatch_target_only",
            mismatch_bundle.decision is AttestationDecision.TARGET_ONLY
            and mismatch_witness.mismatch_fields == ("rng_contract_root",)
            and mismatch_chain[-1].state is ObservationState.QUARANTINED,
            mismatch_bundle.attestation_root,
            "any exact status mismatch remains target-only and quarantined",
        )
    )

    single_denied = False
    try:
        build_capability_attestation_bundle((witness_a,))
    except EaglegateExactnessError:
        single_denied = True
    checks.append(
        AttestationQualificationCheck(
            "single_witness_denied",
            single_denied,
            witness_a.observation_root,
            "one witness cannot satisfy the mechanical quorum",
        )
    )

    duplicate_identity_denied = False
    duplicate_id = replace(
        witness_b,
        witness_id=witness_a.witness_id,
    )
    try:
        build_capability_attestation_bundle((witness_a, duplicate_id))
    except EaglegateExactnessError:
        duplicate_identity_denied = True
    checks.append(
        AttestationQualificationCheck(
            "duplicate_witness_denied",
            duplicate_identity_denied,
            witness_b.observation_root,
            "duplicate witness identity cannot inflate quorum",
        )
    )

    duplicate_tool_denied = False
    duplicate_tool = replace(
        witness_b,
        witness_tool_root=witness_a.witness_tool_root,
    )
    try:
        build_capability_attestation_bundle((witness_a, duplicate_tool))
    except EaglegateExactnessError:
        duplicate_tool_denied = True
    checks.append(
        AttestationQualificationCheck(
            "duplicate_tool_denied",
            duplicate_tool_denied,
            witness_b.observation_root,
            "duplicate tool identity cannot inflate quorum",
        )
    )

    metadata_mix_denied = False
    mixed_metadata = replace(witness_b, metadata_root=_root("other-metadata"))
    try:
        build_capability_attestation_bundle((witness_a, mixed_metadata))
    except EaglegateExactnessError:
        metadata_mix_denied = True
    checks.append(
        AttestationQualificationCheck(
            "mixed_metadata_denied",
            metadata_mix_denied,
            mixed_metadata.observation_root,
            "witnesses cannot attest different metadata roots",
        )
    )

    shadow_mix_denied = False
    mixed_shadow = replace(witness_b, shadow_report_root=_root("other-shadow"))
    try:
        build_capability_attestation_bundle((witness_a, mixed_shadow))
    except EaglegateExactnessError:
        shadow_mix_denied = True
    checks.append(
        AttestationQualificationCheck(
            "mixed_shadow_denied",
            shadow_mix_denied,
            mixed_shadow.observation_root,
            "witnesses cannot bind different shadow reports",
        )
    )

    forged_chain_denied = False
    forged = replace(
        matching_chain[1],
        previous_receipt_root=_root("forged-predecessor"),
    )
    try:
        validate_observation_chain((matching_chain[0], forged))
    except EaglegateExactnessError:
        forged_chain_denied = True
    checks.append(
        AttestationQualificationCheck(
            "forged_receipt_denied",
            forged_chain_denied,
            forged.receipt_root,
            "append-only predecessor roots are mandatory",
        )
    )

    terminal_denied = False
    try:
        next_observation_receipt(
            mismatch_chain[-1], ObservationState.RECORDED
        )
    except EaglegateExactnessError:
        terminal_denied = True
    checks.append(
        AttestationQualificationCheck(
            "quarantine_terminal",
            terminal_denied,
            mismatch_chain[-1].receipt_root,
            "quarantined observation history cannot be reopened",
        )
    )

    partial = EaglegateAttestationQualificationReport(tuple(checks))
    checks.append(
        AttestationQualificationCheck(
            "authority_and_content_boundary",
            _content_free(partial.canonical_dict())
            and partial.canonical_dict()["cryptographic_signature_verified"] is False
            and partial.canonical_dict()["witness_independence_proven"] is False
            and partial.canonical_dict()["metadata_truth_claimed"] is False,
            EAGLEGATE_ATTESTATION_AUTHORITY.authority_root,
            "corroboration makes no signature independence truth or activation claim",
        )
    )

    return EaglegateAttestationQualificationReport(tuple(checks))


__all__ = [
    "AttestationQualificationCheck",
    "EAGLEGATE_ATTESTATION_SUITE_ID",
    "EaglegateAttestationQualificationReport",
    "run_reference_attestation_suite",
]

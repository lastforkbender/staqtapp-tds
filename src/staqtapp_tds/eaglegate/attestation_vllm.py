"""Strict off-path comparison of vLLM metadata and read-only status exports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .attestation_contract import (
    AttestationDecision,
    CapabilityAttestationBundle,
    CapabilityWitnessObservation,
    ObservationState,
    ShadowObservationReceipt,
    VLLMReadOnlyStatusSnapshot,
    next_observation_receipt,
    validate_observation_chain,
)
from .exactness_common import EaglegateExactnessError, require_ascii, require_root
from .shadow_contract import VLLMEagleCapabilityMetadata
from .shadow_vllm import load_vllm_eagle_metadata

_MAX_STATUS_BYTES = 64 * 1024
_STATUS_FIELDS = frozenset(
    {
        "runtime_version",
        "method",
        "foundation_identity_root",
        "target_model_root",
        "tokenizer_root",
        "draft_model_root",
        "adapter_build_root",
        "target_verifier_root",
        "rng_contract_root",
        "sampler_order_root",
        "logits_processor_order_root",
        "termination_contract_root",
        "kv_allocator_root",
        "numerical_kernel_root",
        "deadline_contract_root",
        "num_speculative_tokens",
        "draft_tensor_parallel_size",
        "target_tensor_parallel_size",
        "max_model_len",
        "parallel_drafting",
        "rejection_sample_method",
        "service_instance_root",
        "status_exporter_root",
        "snapshot_generation",
        "runtime_name",
        "read_only_export",
    }
)
_REQUIRED_STATUS_FIELDS = _STATUS_FIELDS - {"runtime_name", "read_only_export"}


def parse_vllm_read_only_status(
    value: Mapping[str, Any],
) -> VLLMReadOnlyStatusSnapshot:
    if not isinstance(value, Mapping):
        raise EaglegateExactnessError("status must be a JSON object")
    keys = set(value)
    unknown = sorted(keys - _STATUS_FIELDS)
    missing = sorted(_REQUIRED_STATUS_FIELDS - keys)
    if unknown:
        raise EaglegateExactnessError(
            "unknown vllm status fields: " + ",".join(unknown)
        )
    if missing:
        raise EaglegateExactnessError(
            "missing vllm status fields: " + ",".join(missing)
        )
    return VLLMReadOnlyStatusSnapshot(**dict(value))


def load_vllm_read_only_status(path: str | Path) -> VLLMReadOnlyStatusSnapshot:
    status_path = Path(path)
    raw = status_path.read_bytes()
    if len(raw) > _MAX_STATUS_BYTES:
        raise EaglegateExactnessError("status file exceeds 64 KiB")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EaglegateExactnessError("status file must be strict UTF-8 JSON") from exc
    return parse_vllm_read_only_status(value)


def _metadata_comparable(
    metadata: VLLMEagleCapabilityMetadata,
) -> dict[str, Any]:
    return {
        "runtime_name": metadata.runtime_name,
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
    }


def compare_vllm_shadow_status(
    metadata: VLLMEagleCapabilityMetadata,
    status: VLLMReadOnlyStatusSnapshot,
    *,
    shadow_report_root: str,
    witness_id: str,
    witness_tool_root: str,
) -> CapabilityWitnessObservation:
    if not isinstance(metadata, VLLMEagleCapabilityMetadata):
        raise EaglegateExactnessError("metadata must be VLLMEagleCapabilityMetadata")
    if not isinstance(status, VLLMReadOnlyStatusSnapshot):
        raise EaglegateExactnessError("status must be VLLMReadOnlyStatusSnapshot")
    require_root("shadow_report_root", shadow_report_root)
    require_ascii("witness_id", witness_id)
    require_root("witness_tool_root", witness_tool_root)
    expected = _metadata_comparable(metadata)
    observed = status.comparable_dict()
    mismatch_fields = tuple(
        sorted(field for field in expected if expected[field] != observed[field])
    )
    return CapabilityWitnessObservation(
        witness_id=witness_id,
        witness_tool_root=witness_tool_root,
        metadata_root=metadata.metadata_root,
        shadow_report_root=shadow_report_root,
        status_snapshot_root=status.snapshot_root,
        matched=not mismatch_fields,
        mismatch_fields=mismatch_fields,
    )


def build_capability_attestation_bundle(
    observations: Iterable[CapabilityWitnessObservation],
) -> CapabilityAttestationBundle:
    ordered = tuple(sorted(observations, key=lambda item: item.observation_root))
    if not ordered:
        raise EaglegateExactnessError("attestation observations cannot be empty")
    return CapabilityAttestationBundle(
        metadata_root=ordered[0].metadata_root,
        shadow_report_root=ordered[0].shadow_report_root,
        observations=ordered,
    )


def build_shadow_observation_chain(
    bundle: CapabilityAttestationBundle,
) -> tuple[ShadowObservationReceipt, ...]:
    if not isinstance(bundle, CapabilityAttestationBundle):
        raise EaglegateExactnessError("bundle must be CapabilityAttestationBundle")
    initial = ShadowObservationReceipt(
        sequence=0,
        state=ObservationState.RECEIVED,
        metadata_root=bundle.metadata_root,
        shadow_report_root=bundle.shadow_report_root,
        attestation_root=bundle.attestation_root,
    )
    if bundle.decision is AttestationDecision.CORROBORATED:
        corroborated = next_observation_receipt(
            initial, ObservationState.CORROBORATED
        )
        recorded = next_observation_receipt(corroborated, ObservationState.RECORDED)
        return validate_observation_chain((initial, corroborated, recorded))
    quarantined = next_observation_receipt(initial, ObservationState.QUARANTINED)
    return validate_observation_chain((initial, quarantined))


__all__ = [
    "build_capability_attestation_bundle",
    "build_shadow_observation_chain",
    "compare_vllm_shadow_status",
    "load_vllm_eagle_metadata",
    "load_vllm_read_only_status",
    "parse_vllm_read_only_status",
]

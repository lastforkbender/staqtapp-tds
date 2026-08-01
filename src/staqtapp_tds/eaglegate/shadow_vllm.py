"""Strict non-executing vLLM EAGLE metadata fixture for Eaglegate shadowing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .exactness_common import EaglegateExactnessError, require_root
from .shadow_contract import (
    EaglegateShadowCompilationReport,
    ShadowDecisionKind,
    ShadowReason,
    VLLMEagleCapabilityMetadata,
    VLLMEagleShadowPreview,
)

_MAX_METADATA_BYTES = 64 * 1024
_METADATA_FIELDS = frozenset(
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
        "capability_source_root",
        "metadata_attestation_root",
        "num_speculative_tokens",
        "draft_tensor_parallel_size",
        "target_tensor_parallel_size",
        "max_model_len",
        "parallel_drafting",
        "rejection_sample_method",
        "fixture_id",
        "runtime_name",
    }
)
_REQUIRED_FIELDS = _METADATA_FIELDS - {"fixture_id", "runtime_name"}


def parse_vllm_eagle_metadata(
    value: Mapping[str, Any],
) -> VLLMEagleCapabilityMetadata:
    if not isinstance(value, Mapping):
        raise EaglegateExactnessError("metadata must be a JSON object")
    keys = set(value)
    unknown = sorted(keys - _METADATA_FIELDS)
    missing = sorted(_REQUIRED_FIELDS - keys)
    if unknown:
        raise EaglegateExactnessError(
            "unknown vllm metadata fields: " + ",".join(unknown)
        )
    if missing:
        raise EaglegateExactnessError(
            "missing vllm metadata fields: " + ",".join(missing)
        )
    return VLLMEagleCapabilityMetadata(**dict(value))


def load_vllm_eagle_metadata(path: str | Path) -> VLLMEagleCapabilityMetadata:
    metadata_path = Path(path)
    raw = metadata_path.read_bytes()
    if len(raw) > _MAX_METADATA_BYTES:
        raise EaglegateExactnessError("metadata file exceeds 64 KiB")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EaglegateExactnessError("metadata file must be strict UTF-8 JSON") from exc
    return parse_vllm_eagle_metadata(value)


def compile_vllm_eagle_shadow(
    metadata: VLLMEagleCapabilityMetadata,
    *,
    exactness_qualification_root: str,
    adapter_conformance_report_root: str,
) -> tuple[VLLMEagleShadowPreview, EaglegateShadowCompilationReport]:
    if not isinstance(metadata, VLLMEagleCapabilityMetadata):
        raise EaglegateExactnessError(
            "metadata must be VLLMEagleCapabilityMetadata"
        )
    require_root("exactness_qualification_root", exactness_qualification_root)
    require_root(
        "adapter_conformance_report_root",
        adapter_conformance_report_root,
    )
    adapter_identity = metadata.adapter_identity(
        exactness_qualification_root=exactness_qualification_root
    )
    preview = VLLMEagleShadowPreview(
        metadata_root=metadata.metadata_root,
        runtime_name=metadata.runtime_name,
        runtime_version=metadata.runtime_version,
        method=metadata.method,
        target_model_root=metadata.target_model_root,
        tokenizer_root=metadata.tokenizer_root,
        draft_model_root=metadata.draft_model_root,
        num_speculative_tokens=metadata.num_speculative_tokens,
        draft_tensor_parallel_size=metadata.draft_tensor_parallel_size,
        target_tensor_parallel_size=metadata.target_tensor_parallel_size,
        max_model_len=metadata.max_model_len,
        parallel_drafting=metadata.parallel_drafting,
        rejection_sample_method=metadata.rejection_sample_method,
    )
    if metadata.rejection_sample_method == "synthetic":
        decision = ShadowDecisionKind.TARGET_ONLY
        reason = ShadowReason.SYNTHETIC_ACCEPTANCE_FORBIDDEN
    elif metadata.parallel_drafting:
        decision = ShadowDecisionKind.TARGET_ONLY
        reason = ShadowReason.PARALLEL_DRAFTING_UNQUALIFIED
    else:
        decision = ShadowDecisionKind.OBSERVE
        reason = ShadowReason.METADATA_ONLY_SHADOW
    report = EaglegateShadowCompilationReport(
        decision=decision,
        reason=reason,
        metadata_root=metadata.metadata_root,
        preview_root=preview.preview_root,
        adapter_identity_root=adapter_identity.adapter_identity_root,
        exactness_qualification_root=exactness_qualification_root,
        adapter_conformance_report_root=adapter_conformance_report_root,
    )
    return preview, report


def vllm_eagle_metadata_schema() -> dict[str, Any]:
    return {
        "fixture_id": "vllm-eagle-metadata-v1",
        "runtime_name": "vllm",
        "required_fields": sorted(_REQUIRED_FIELDS),
        "allowed_methods": ["eagle", "eagle3"],
        "known_rejection_sample_methods": [
            "strict",
            "probabilistic",
            "synthetic",
        ],
        "model_identifiers": "sha256 roots only",
        "runtime_imported": False,
        "executable_command_emitted": False,
        "activation_authority": False,
        "real_runtime_qualified": False,
    }


__all__ = [
    "compile_vllm_eagle_shadow",
    "load_vllm_eagle_metadata",
    "parse_vllm_eagle_metadata",
    "vllm_eagle_metadata_schema",
]

"""Non-executing vLLM EAGLE capability translator for Eaglegate shadow use.

This module never imports vLLM, loads a model, starts a runtime, samples a token,
or mutates KV state. It validates caller-supplied metadata and translates one
fully pinned capability snapshot into the immutable Eaglegate adapter identity.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .adapter_contract import EaglegateAdapterIdentity
from .contract import EaglegateSamplerClass
from .exactness_common import (
    EaglegateExactnessError,
    MAX_TOKENS,
    UINT32_MAX,
    UINT63_MAX,
    canonical_root,
    require_ascii,
    require_int,
    require_root,
)

EAGLEGATE_VLLM_SHADOW_CONTRACT_ID = "tds-eaglegate-vllm-shadow-v1"
EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID = "vllm-eagle-capability-snapshot-v1"
EAGLEGATE_VLLM_RUNTIME_NAME = "vllm"
EAGLEGATE_VLLM_METHOD = "eagle"
EAGLEGATE_VLLM_DRAFT_TENSOR_PARALLEL_SIZE = 1
EAGLEGATE_VLLM_SHADOW_SUITE_ID = "eaglegate-vllm-shadow-reference-v1"

_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class VllmShadowFault(str, Enum):
    NONE = "none"
    SNAPSHOT_MISMATCH = "snapshot_mismatch"
    SAMPLER_UNSUPPORTED = "sampler_unsupported"
    CANDIDATE_LIMIT = "candidate_limit"
    TARGET_PARALLELISM_MISMATCH = "target_parallelism_mismatch"
    AUTHORITY_REJECTED = "authority_rejected"


@dataclass(frozen=True, slots=True)
class VllmShadowAuthorityBoundary:
    metadata_translation_only: bool = True
    runtime_import_allowed: bool = False
    model_loading_allowed: bool = False
    inference_allowed: bool = False
    network_io_allowed: bool = False
    subprocess_allowed: bool = False
    token_acceptance_authority: bool = False
    target_rng_authority: bool = False
    kv_commit_authority: bool = False
    activation_authority: bool = False
    configuration_mutation_allowed: bool = False
    target_only_execution_required: bool = True

    def __post_init__(self) -> None:
        expected = {
            "metadata_translation_only": True,
            "runtime_import_allowed": False,
            "model_loading_allowed": False,
            "inference_allowed": False,
            "network_io_allowed": False,
            "subprocess_allowed": False,
            "token_acceptance_authority": False,
            "target_rng_authority": False,
            "kv_commit_authority": False,
            "activation_authority": False,
            "configuration_mutation_allowed": False,
            "target_only_execution_required": True,
        }
        if asdict(self) != expected:
            raise EaglegateExactnessError(
                "vLLM shadow authority cannot be widened"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return canonical_root("vllm-shadow-authority", self.canonical_dict())


EAGLEGATE_VLLM_SHADOW_AUTHORITY = VllmShadowAuthorityBoundary()


def _require_semver(value: str) -> str:
    message = (
        "runtime_version must be one exact Semantic Version; "
        "ranges and latest are forbidden"
    )
    try:
        require_ascii("runtime_version", value)
    except EaglegateExactnessError as exc:
        raise EaglegateExactnessError(message) from exc
    if not _SEMVER_RE.fullmatch(value):
        raise EaglegateExactnessError(message)
    return value


def _require_bool(name: str, value: bool) -> bool:
    if not isinstance(value, bool):
        raise EaglegateExactnessError(f"{name} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class VllmEagleCapabilitySnapshot:
    runtime_version: str
    runtime_build_root: str
    engine_api_root: str
    foundation_identity_root: str
    exactness_qualification_root: str
    adapter_conformance_root: str
    shadow_adapter_build_root: str
    target_model_root: str
    tokenizer_root: str
    draft_model_root: str
    target_verifier_root: str
    rng_contract_root: str
    sampler_order_root: str
    logits_processor_order_root: str
    termination_contract_root: str
    kv_allocator_root: str
    numerical_kernel_root: str
    deadline_contract_root: str
    scheduler_contract_root: str
    num_speculative_tokens: int
    target_tensor_parallel_size: int
    max_batch: int
    max_concurrency: int
    max_context_tokens: int
    max_kv_pressure_ppm: int
    max_workspace_budget_bytes: int
    sampler_classes: tuple[EaglegateSamplerClass, ...]
    runtime_name: str = EAGLEGATE_VLLM_RUNTIME_NAME
    method: str = EAGLEGATE_VLLM_METHOD
    draft_tensor_parallel_size: int = EAGLEGATE_VLLM_DRAFT_TENSOR_PARALLEL_SIZE
    snapshot_contract_id: str = EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID
    fixture_only: bool = True

    def __post_init__(self) -> None:
        if self.snapshot_contract_id != EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID:
            raise EaglegateExactnessError("unsupported vLLM snapshot contract")
        if self.runtime_name != EAGLEGATE_VLLM_RUNTIME_NAME:
            raise EaglegateExactnessError("runtime_name must be exactly vllm")
        if self.method != EAGLEGATE_VLLM_METHOD:
            raise EaglegateExactnessError(
                "shadow profile v1 supports only method=eagle"
            )
        if self.draft_tensor_parallel_size != 1:
            raise EaglegateExactnessError(
                "shadow profile v1 requires draft_tensor_parallel_size=1"
            )
        _require_bool("fixture_only", self.fixture_only)
        if self.fixture_only is not True:
            raise EaglegateExactnessError(
                "a non-executing snapshot must declare fixture_only=true"
            )
        _require_semver(self.runtime_version)
        root_fields = (
            "runtime_build_root",
            "engine_api_root",
            "foundation_identity_root",
            "exactness_qualification_root",
            "adapter_conformance_root",
            "shadow_adapter_build_root",
            "target_model_root",
            "tokenizer_root",
            "draft_model_root",
            "target_verifier_root",
            "rng_contract_root",
            "sampler_order_root",
            "logits_processor_order_root",
            "termination_contract_root",
            "kv_allocator_root",
            "numerical_kernel_root",
            "deadline_contract_root",
            "scheduler_contract_root",
        )
        for name in root_fields:
            require_root(name, getattr(self, name))
        require_int("num_speculative_tokens", self.num_speculative_tokens, 1, 64)
        require_int(
            "target_tensor_parallel_size",
            self.target_tensor_parallel_size,
            1,
            UINT32_MAX,
        )
        require_int("max_batch", self.max_batch, 1, UINT32_MAX)
        require_int("max_concurrency", self.max_concurrency, 1, UINT32_MAX)
        require_int("max_context_tokens", self.max_context_tokens, 1, UINT32_MAX)
        require_int("max_kv_pressure_ppm", self.max_kv_pressure_ppm, 0, 1_000_000)
        require_int(
            "max_workspace_budget_bytes",
            self.max_workspace_budget_bytes,
            1,
            UINT63_MAX,
        )
        if not isinstance(self.sampler_classes, tuple) or not self.sampler_classes:
            raise EaglegateExactnessError(
                "sampler_classes must be a non-empty tuple"
            )
        if any(
            not isinstance(value, EaglegateSamplerClass)
            for value in self.sampler_classes
        ):
            raise EaglegateExactnessError("unsupported sampler class value")
        if len(set(self.sampler_classes)) != len(self.sampler_classes):
            raise EaglegateExactnessError("sampler_classes must be unique")

    def speculative_config_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "draft_model_root": self.draft_model_root,
            "draft_tensor_parallel_size": self.draft_tensor_parallel_size,
            "num_speculative_tokens": self.num_speculative_tokens,
        }

    @property
    def speculative_config_root(self) -> str:
        return canonical_root(
            "vllm-speculative-config", self.speculative_config_dict()
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
            "snapshot_contract_id": self.snapshot_contract_id,
            "authority_root": EAGLEGATE_VLLM_SHADOW_AUTHORITY.authority_root,
            "runtime_name": self.runtime_name,
            "runtime_version": self.runtime_version,
            "runtime_build_root": self.runtime_build_root,
            "engine_api_root": self.engine_api_root,
            "foundation_identity_root": self.foundation_identity_root,
            "exactness_qualification_root": self.exactness_qualification_root,
            "adapter_conformance_root": self.adapter_conformance_root,
            "shadow_adapter_build_root": self.shadow_adapter_build_root,
            "target_model_root": self.target_model_root,
            "tokenizer_root": self.tokenizer_root,
            "draft_model_root": self.draft_model_root,
            "target_verifier_root": self.target_verifier_root,
            "rng_contract_root": self.rng_contract_root,
            "sampler_order_root": self.sampler_order_root,
            "logits_processor_order_root": self.logits_processor_order_root,
            "termination_contract_root": self.termination_contract_root,
            "kv_allocator_root": self.kv_allocator_root,
            "numerical_kernel_root": self.numerical_kernel_root,
            "deadline_contract_root": self.deadline_contract_root,
            "scheduler_contract_root": self.scheduler_contract_root,
            "speculative_config": self.speculative_config_dict(),
            "speculative_config_root": self.speculative_config_root,
            "target_tensor_parallel_size": self.target_tensor_parallel_size,
            "max_batch": self.max_batch,
            "max_concurrency": self.max_concurrency,
            "max_context_tokens": self.max_context_tokens,
            "max_kv_pressure_ppm": self.max_kv_pressure_ppm,
            "max_workspace_budget_bytes": self.max_workspace_budget_bytes,
            "sampler_classes": [value.value for value in self.sampler_classes],
            "fixture_only": True,
        }

    @property
    def snapshot_root(self) -> str:
        return canonical_root("vllm-capability-snapshot", self.canonical_dict())

    def adapter_identity(self) -> EaglegateAdapterIdentity:
        return EaglegateAdapterIdentity(
            foundation_identity_root=self.foundation_identity_root,
            exactness_qualification_root=self.exactness_qualification_root,
            adapter_build_root=canonical_root(
                "vllm-shadow-adapter-build",
                {
                    "shadow_adapter_build_root": self.shadow_adapter_build_root,
                    "adapter_conformance_root": self.adapter_conformance_root,
                    "runtime_build_root": self.runtime_build_root,
                    "engine_api_root": self.engine_api_root,
                    "scheduler_contract_root": self.scheduler_contract_root,
                    "speculative_config_root": self.speculative_config_root,
                },
            ),
            target_verifier_root=self.target_verifier_root,
            rng_contract_root=self.rng_contract_root,
            sampler_order_root=self.sampler_order_root,
            logits_processor_order_root=self.logits_processor_order_root,
            termination_contract_root=self.termination_contract_root,
            kv_allocator_root=self.kv_allocator_root,
            numerical_kernel_root=self.numerical_kernel_root,
            deadline_contract_root=self.deadline_contract_root,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VllmEagleCapabilitySnapshot":
        if not isinstance(value, Mapping):
            raise EaglegateExactnessError("snapshot must be an object")
        fields = dict(value)
        sampler_values = fields.pop("sampler_classes", ())
        if isinstance(sampler_values, str) or not isinstance(
            sampler_values, Sequence
        ):
            raise EaglegateExactnessError("sampler_classes must be an array")
        try:
            samplers = tuple(
                EaglegateSamplerClass(str(item)) for item in sampler_values
            )
        except ValueError as exc:
            raise EaglegateExactnessError("unsupported sampler class") from exc
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise EaglegateExactnessError(
                f"unknown vLLM capability fields: {unknown}"
            )
        try:
            return cls(sampler_classes=samplers, **fields)
        except TypeError as exc:
            raise EaglegateExactnessError(
                f"invalid vLLM capability snapshot fields: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class VllmShadowRequirement:
    expected_snapshot_root: str
    sampler_class: EaglegateSamplerClass
    candidate_tokens: int
    target_tensor_parallel_size: int

    def __post_init__(self) -> None:
        require_root("expected_snapshot_root", self.expected_snapshot_root)
        if not isinstance(self.sampler_class, EaglegateSamplerClass):
            raise EaglegateExactnessError(
                "sampler_class must be EaglegateSamplerClass"
            )
        require_int("candidate_tokens", self.candidate_tokens, 1, MAX_TOKENS)
        require_int(
            "target_tensor_parallel_size",
            self.target_tensor_parallel_size,
            1,
            UINT32_MAX,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
            "expected_snapshot_root": self.expected_snapshot_root,
            "sampler_class": self.sampler_class.value,
            "candidate_tokens": self.candidate_tokens,
            "target_tensor_parallel_size": self.target_tensor_parallel_size,
        }

    @property
    def requirement_root(self) -> str:
        return canonical_root("vllm-shadow-requirement", self.canonical_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VllmShadowRequirement":
        if not isinstance(value, Mapping):
            raise EaglegateExactnessError("requirement must be an object")
        fields = dict(value)
        try:
            fields["sampler_class"] = EaglegateSamplerClass(
                str(fields.get("sampler_class", ""))
            )
        except ValueError as exc:
            raise EaglegateExactnessError("unsupported sampler class") from exc
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise EaglegateExactnessError(
                f"unknown vLLM requirement fields: {unknown}"
            )
        try:
            return cls(**fields)
        except TypeError as exc:
            raise EaglegateExactnessError(
                f"invalid vLLM shadow requirement fields: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class VllmShadowDecision:
    snapshot_root: str
    requirement_root: str
    adapter_identity_root: str
    compatible: bool
    fault: VllmShadowFault
    reason: str

    def __post_init__(self) -> None:
        require_root("snapshot_root", self.snapshot_root)
        require_root("requirement_root", self.requirement_root)
        require_root("adapter_identity_root", self.adapter_identity_root)
        _require_bool("compatible", self.compatible)
        if not isinstance(self.fault, VllmShadowFault):
            raise EaglegateExactnessError("fault must be VllmShadowFault")
        require_ascii("reason", self.reason, allow_empty=True)
        if self.compatible and self.fault is not VllmShadowFault.NONE:
            raise EaglegateExactnessError("compatible decision cannot carry a fault")
        if not self.compatible and self.fault is VllmShadowFault.NONE:
            raise EaglegateExactnessError("incompatible decision requires a fault")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
            "authority_root": EAGLEGATE_VLLM_SHADOW_AUTHORITY.authority_root,
            "snapshot_root": self.snapshot_root,
            "requirement_root": self.requirement_root,
            "adapter_identity_root": self.adapter_identity_root,
            "compatible": self.compatible,
            "fault": self.fault.value,
            "reason": self.reason,
            "serving_effect": "shadow_metadata_only" if self.compatible else "target_only",
            "runtime_invoked": False,
            "model_invoked": False,
            "inference_performed": False,
            "token_acceptance_authority": False,
            "kv_commit_authority": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
        }

    @property
    def decision_root(self) -> str:
        return canonical_root("vllm-shadow-decision", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "decision_root": self.decision_root}


def evaluate_vllm_shadow(
    snapshot: VllmEagleCapabilitySnapshot,
    requirement: VllmShadowRequirement,
) -> VllmShadowDecision:
    if not isinstance(snapshot, VllmEagleCapabilitySnapshot):
        raise EaglegateExactnessError("snapshot has wrong type")
    if not isinstance(requirement, VllmShadowRequirement):
        raise EaglegateExactnessError("requirement has wrong type")
    identity_root = snapshot.adapter_identity().adapter_identity_root
    checks = (
        (
            requirement.expected_snapshot_root != snapshot.snapshot_root,
            VllmShadowFault.SNAPSHOT_MISMATCH,
            "snapshot_mismatch",
        ),
        (
            requirement.sampler_class not in snapshot.sampler_classes,
            VllmShadowFault.SAMPLER_UNSUPPORTED,
            "sampler_unsupported",
        ),
        (
            requirement.candidate_tokens > snapshot.num_speculative_tokens,
            VllmShadowFault.CANDIDATE_LIMIT,
            "candidate_limit",
        ),
        (
            requirement.target_tensor_parallel_size
            != snapshot.target_tensor_parallel_size,
            VllmShadowFault.TARGET_PARALLELISM_MISMATCH,
            "target_parallelism_mismatch",
        ),
    )
    for rejected, fault, reason in checks:
        if rejected:
            return VllmShadowDecision(
                snapshot.snapshot_root,
                requirement.requirement_root,
                identity_root,
                False,
                fault,
                reason,
            )
    return VllmShadowDecision(
        snapshot.snapshot_root,
        requirement.requirement_root,
        identity_root,
        True,
        VllmShadowFault.NONE,
        "metadata_translation_ready",
    )


def _read_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EaglegateExactnessError(f"could not read {source}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise EaglegateExactnessError(f"{source} must contain one JSON object")
    return dict(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-vllm-shadow")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        snapshot = VllmEagleCapabilitySnapshot.from_mapping(
            _read_json_object(args.snapshot)
        )
        requirement = VllmShadowRequirement.from_mapping(
            _read_json_object(args.requirement)
        )
        decision = evaluate_vllm_shadow(snapshot, requirement)
        payload = decision.to_dict()
        code = 0 if decision.compatible else 2
    except EaglegateExactnessError as exc:
        payload = {
            "shadow_contract_id": EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
            "ok": False,
            "fault": "invalid_metadata",
            "message": str(exc),
            "serving_effect": "target_only",
            "runtime_invoked": False,
            "model_invoked": False,
            "inference_performed": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
        }
        code = 2
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        state = "READY" if payload.get("compatible") else "TARGET-ONLY"
        print(f"Eaglegate vLLM shadow metadata: {state}")
        print(json.dumps(payload, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_VLLM_DRAFT_TENSOR_PARALLEL_SIZE",
    "EAGLEGATE_VLLM_METHOD",
    "EAGLEGATE_VLLM_RUNTIME_NAME",
    "EAGLEGATE_VLLM_SHADOW_AUTHORITY",
    "EAGLEGATE_VLLM_SHADOW_CONTRACT_ID",
    "EAGLEGATE_VLLM_SHADOW_SUITE_ID",
    "EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID",
    "VllmEagleCapabilitySnapshot",
    "VllmShadowAuthorityBoundary",
    "VllmShadowDecision",
    "VllmShadowFault",
    "VllmShadowRequirement",
    "evaluate_vllm_shadow",
    "main",
]

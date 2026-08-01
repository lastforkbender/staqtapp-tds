"""Immutable shadow-only metadata contracts for named Eaglegate fixtures."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Any

from .adapter_contract import EaglegateAdapterIdentity
from .exactness_common import (
    EaglegateExactnessError,
    UINT32_MAX,
    canonical_root,
    require_ascii,
    require_int,
    require_root,
)

EAGLEGATE_SHADOW_CONTRACT_ID = "tds-eaglegate-shadow-sdk-v1"
EAGLEGATE_SHADOW_FORMAT_VERSION = 1
EAGLEGATE_VLLM_FIXTURE_ID = "vllm-eagle-metadata-v1"
EAGLEGATE_VLLM_RUNTIME_NAME = "vllm"
EAGLEGATE_VLLM_METHODS = ("eagle", "eagle3")
EAGLEGATE_VLLM_REJECTION_METHODS = ("strict", "probabilistic", "synthetic")

_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[a-z0-9][a-z0-9.-]*)?$")


class ShadowDecisionKind(str, Enum):
    OBSERVE = "observe"
    TARGET_ONLY = "target_only"


class ShadowReason(str, Enum):
    METADATA_ONLY_SHADOW = "metadata_only_shadow"
    SYNTHETIC_ACCEPTANCE_FORBIDDEN = "synthetic_acceptance_forbidden"
    PARALLEL_DRAFTING_UNQUALIFIED = "parallel_drafting_unqualified"


@dataclass(frozen=True, slots=True)
class EaglegateShadowAuthorityBoundary:
    may_import_runtime: bool = False
    may_start_server: bool = False
    may_load_model: bool = False
    may_allocate_kv: bool = False
    may_generate_tokens: bool = False
    may_verify_tokens: bool = False
    may_commit_tokens: bool = False
    may_emit_executable_command: bool = False
    may_activate: bool = False
    target_only_default: bool = True
    may_render_content_free_preview: bool = True

    def __post_init__(self) -> None:
        expected = {
            "may_import_runtime": False,
            "may_start_server": False,
            "may_load_model": False,
            "may_allocate_kv": False,
            "may_generate_tokens": False,
            "may_verify_tokens": False,
            "may_commit_tokens": False,
            "may_emit_executable_command": False,
            "may_activate": False,
            "target_only_default": True,
            "may_render_content_free_preview": True,
        }
        if asdict(self) != expected:
            raise EaglegateExactnessError("shadow authority cannot be widened")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_SHADOW_CONTRACT_ID,
            "shadow_format_version": EAGLEGATE_SHADOW_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return canonical_root("shadow-authority", self.canonical_dict())


EAGLEGATE_SHADOW_AUTHORITY = EaglegateShadowAuthorityBoundary()


@dataclass(frozen=True, slots=True)
class VLLMEagleCapabilityMetadata:
    runtime_version: str
    method: str
    foundation_identity_root: str
    target_model_root: str
    tokenizer_root: str
    draft_model_root: str
    adapter_build_root: str
    target_verifier_root: str
    rng_contract_root: str
    sampler_order_root: str
    logits_processor_order_root: str
    termination_contract_root: str
    kv_allocator_root: str
    numerical_kernel_root: str
    deadline_contract_root: str
    capability_source_root: str
    metadata_attestation_root: str
    num_speculative_tokens: int
    draft_tensor_parallel_size: int
    target_tensor_parallel_size: int
    max_model_len: int
    parallel_drafting: bool
    rejection_sample_method: str
    fixture_id: str = EAGLEGATE_VLLM_FIXTURE_ID
    runtime_name: str = EAGLEGATE_VLLM_RUNTIME_NAME

    def __post_init__(self) -> None:
        if self.fixture_id != EAGLEGATE_VLLM_FIXTURE_ID:
            raise EaglegateExactnessError("unsupported shadow fixture identity")
        if self.runtime_name != EAGLEGATE_VLLM_RUNTIME_NAME:
            raise EaglegateExactnessError("fixture accepts only vllm metadata")
        require_ascii("runtime_version", self.runtime_version)
        if not _VERSION_RE.fullmatch(self.runtime_version):
            raise EaglegateExactnessError(
                "runtime_version must be an exact normalized package version"
            )
        if self.method not in EAGLEGATE_VLLM_METHODS:
            raise EaglegateExactnessError("fixture accepts only eagle or eagle3")
        if self.rejection_sample_method not in EAGLEGATE_VLLM_REJECTION_METHODS:
            raise EaglegateExactnessError(
                "unsupported rejection_sample_method metadata"
            )
        for name in (
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
        ):
            require_root(name, getattr(self, name))
        require_int("num_speculative_tokens", self.num_speculative_tokens, 1, 64)
        require_int(
            "draft_tensor_parallel_size",
            self.draft_tensor_parallel_size,
            1,
            1024,
        )
        require_int(
            "target_tensor_parallel_size",
            self.target_tensor_parallel_size,
            1,
            1024,
        )
        require_int("max_model_len", self.max_model_len, 1, UINT32_MAX)
        if not isinstance(self.parallel_drafting, bool):
            raise EaglegateExactnessError("parallel_drafting must be boolean")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_SHADOW_CONTRACT_ID,
            "shadow_format_version": EAGLEGATE_SHADOW_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def metadata_root(self) -> str:
        return canonical_root("vllm-eagle-metadata", self.canonical_dict())

    def adapter_identity(
        self,
        *,
        exactness_qualification_root: str,
    ) -> EaglegateAdapterIdentity:
        require_root("exactness_qualification_root", exactness_qualification_root)
        return EaglegateAdapterIdentity(
            foundation_identity_root=self.foundation_identity_root,
            exactness_qualification_root=exactness_qualification_root,
            adapter_build_root=self.adapter_build_root,
            target_verifier_root=self.target_verifier_root,
            rng_contract_root=self.rng_contract_root,
            sampler_order_root=self.sampler_order_root,
            logits_processor_order_root=self.logits_processor_order_root,
            termination_contract_root=self.termination_contract_root,
            kv_allocator_root=self.kv_allocator_root,
            numerical_kernel_root=self.numerical_kernel_root,
            deadline_contract_root=self.deadline_contract_root,
        )


@dataclass(frozen=True, slots=True)
class VLLMEagleShadowPreview:
    metadata_root: str
    runtime_name: str
    runtime_version: str
    method: str
    target_model_root: str
    tokenizer_root: str
    draft_model_root: str
    num_speculative_tokens: int
    draft_tensor_parallel_size: int
    target_tensor_parallel_size: int
    max_model_len: int
    parallel_drafting: bool
    rejection_sample_method: str
    preview_only: bool = True
    executable_command_emitted: bool = False

    def __post_init__(self) -> None:
        require_root("metadata_root", self.metadata_root)
        require_ascii("runtime_name", self.runtime_name)
        require_ascii("runtime_version", self.runtime_version)
        if self.method not in EAGLEGATE_VLLM_METHODS:
            raise EaglegateExactnessError("invalid shadow preview method")
        for name in ("target_model_root", "tokenizer_root", "draft_model_root"):
            require_root(name, getattr(self, name))
        require_int("num_speculative_tokens", self.num_speculative_tokens, 1, 64)
        require_int("draft_tensor_parallel_size", self.draft_tensor_parallel_size, 1, 1024)
        require_int("target_tensor_parallel_size", self.target_tensor_parallel_size, 1, 1024)
        require_int("max_model_len", self.max_model_len, 1, UINT32_MAX)
        if not isinstance(self.parallel_drafting, bool):
            raise EaglegateExactnessError("parallel_drafting must be boolean")
        if self.rejection_sample_method not in EAGLEGATE_VLLM_REJECTION_METHODS:
            raise EaglegateExactnessError("invalid rejection method preview")
        if self.preview_only is not True or self.executable_command_emitted is not False:
            raise EaglegateExactnessError("shadow preview cannot become executable")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_SHADOW_CONTRACT_ID,
            "shadow_format_version": EAGLEGATE_SHADOW_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def preview_root(self) -> str:
        return canonical_root("vllm-eagle-shadow-preview", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateShadowCompilationReport:
    decision: ShadowDecisionKind
    reason: ShadowReason
    metadata_root: str
    preview_root: str
    adapter_identity_root: str
    exactness_qualification_root: str
    adapter_conformance_report_root: str
    authority_root: str = EAGLEGATE_SHADOW_AUTHORITY.authority_root
    fixture_id: str = EAGLEGATE_VLLM_FIXTURE_ID

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ShadowDecisionKind):
            raise EaglegateExactnessError("decision must be ShadowDecisionKind")
        if not isinstance(self.reason, ShadowReason):
            raise EaglegateExactnessError("reason must be ShadowReason")
        if self.fixture_id != EAGLEGATE_VLLM_FIXTURE_ID:
            raise EaglegateExactnessError("report fixture identity mismatch")
        for name in (
            "metadata_root",
            "preview_root",
            "adapter_identity_root",
            "exactness_qualification_root",
            "adapter_conformance_report_root",
            "authority_root",
        ):
            require_root(name, getattr(self, name))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_SHADOW_CONTRACT_ID,
            "shadow_format_version": EAGLEGATE_SHADOW_FORMAT_VERSION,
            "fixture_id": self.fixture_id,
            "decision": self.decision.value,
            "reason": self.reason.value,
            "metadata_root": self.metadata_root,
            "preview_root": self.preview_root,
            "adapter_identity_root": self.adapter_identity_root,
            "exactness_qualification_root": self.exactness_qualification_root,
            "adapter_conformance_report_root": self.adapter_conformance_report_root,
            "authority_root": self.authority_root,
            "runtime_imported": False,
            "server_started": False,
            "model_loaded": False,
            "kv_allocated": False,
            "tokens_generated": False,
            "tokens_verified": False,
            "tokens_committed": False,
            "executable_command_emitted": False,
            "activation_authority": False,
            "production_execution_authority": False,
            "real_runtime_qualified": False,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
        }

    @property
    def report_root(self) -> str:
        return canonical_root("shadow-compilation-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


__all__ = [
    "EAGLEGATE_SHADOW_AUTHORITY",
    "EAGLEGATE_SHADOW_CONTRACT_ID",
    "EAGLEGATE_SHADOW_FORMAT_VERSION",
    "EAGLEGATE_VLLM_FIXTURE_ID",
    "EAGLEGATE_VLLM_METHODS",
    "EAGLEGATE_VLLM_REJECTION_METHODS",
    "EAGLEGATE_VLLM_RUNTIME_NAME",
    "EaglegateShadowAuthorityBoundary",
    "EaglegateShadowCompilationReport",
    "ShadowDecisionKind",
    "ShadowReason",
    "VLLMEagleCapabilityMetadata",
    "VLLMEagleShadowPreview",
]

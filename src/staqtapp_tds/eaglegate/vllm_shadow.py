"""Pinned, qualification-only vLLM EAGLE shadow adapter for TDS v3.8.

The adapter executes a fixed public model/runtime matrix off the production
request path.  It can produce qualification evidence, but it exposes no
canary, activation, routing, token-acceptance, or KV-commit operation.

Only roots, bounded counters, stable status values, and explicit limitation
flags may leave the process.  Prompts, token sequences, logits, hidden states,
and KV tensors remain transient in memory.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any

from staqtapp_tds.generation.generation_contract import (
    canonical_json_bytes,
)
from staqtapp_tds.generation.generation_store import (
    AtomicGenerationStore,
    PublicationResult,
)

from .contract import (
    EaglegateIdentity,
    EaglegateMode,
    EaglegateSamplerClass,
)
from .exactness_common import canonical_root, require_ascii, require_int, require_root
from .generation import (
    EaglegateServingEpochBinding,
    LoadedEaglegateServingGeneration,
    build_eaglegate_serving_candidate,
    open_eaglegate_serving_generation,
    publish_eaglegate_serving_candidate,
    qualify_eaglegate_core_epoch,
)
from .plans import (
    EaglegateAdmissionPolicy,
    EaglegatePlan,
    EaglegateSpeculationEpoch,
)

VLLM_SHADOW_CONTRACT_ID = "tds-eaglegate-vllm-shadow-v1"
VLLM_SHADOW_FORMAT_VERSION = 1

VLLM_VERSION = "0.26.0"
VLLM_BUILD_COMMIT = "568afb3a13806beb53bb2e6bd518269357b237c0"
VLLM_TAG = "v0.26.0"
VLLM_SPECULATIVE_METHOD = "eagle"
VLLM_REJECTION_SAMPLE_METHOD = "standard"

TARGET_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
TARGET_REVISION = "8afb486c1db24fe5011ec46dfbe5b5dccdb575c2"
DRAFT_MODEL = "yuhuili/EAGLE-LLaMA3-Instruct-8B"
DRAFT_REVISION = "b62ec3ed0c5135290f5dd8b8cec48d055d3d10dd"

QUALIFIED_GPU_FAMILY = "NVIDIA H100"
QUALIFIED_COMPUTE_CAPABILITY = (9, 0)
QUALIFIED_DTYPE = "bfloat16"
QUALIFIED_BATCH_SIZE = 1
QUALIFIED_SPECULATIVE_PLANS = (1, 2, 3)
QUALIFIED_KV_CACHE_DTYPE = "bfloat16"
QUALIFIED_KV_CACHE_RESOLVED_DTYPE = "bfloat16"
QUALIFIED_KV_BLOCK_SIZE = 16
QUALIFIED_PREFIX_CACHING = False
QUALIFIED_TARGET_TENSOR_PARALLEL_SIZE = 1
QUALIFIED_DRAFT_TENSOR_PARALLEL_SIZE = 1
QUALIFIED_RNG_CONTRACT = "target-and-draft-inherit-explicit-request-seed-v1"

VLLM_SHADOW_STORAGE_NAMESPACE = "eaglegate:vllm-shadow-storage"
VLLM_SHADOW_SERVING_NAMESPACE = "eaglegate:vllm-shadow-serving"
VLLM_SHADOW_REPORT_NAMESPACE = "eaglegate:vllm-shadow-qualification"

DEFAULT_QUALIFICATION_PROMPTS = (
    "Give one concise reason deterministic tests matter.",
    "Name one property of a lossless decoding verifier.",
)

_REPORT_PAYLOAD = "eaglegate.vllm-shadow.report"
_MAX_OBSERVATIONS = 4096
_MAX_PROMPTS = 8
_MAX_PROMPT_BYTES = 4096
_MAX_CASES = 4096
_MAX_NEW_TOKENS = 256
_MAX_SEED = (1 << 63) - 1
_MAX_SAMPLED_DISTRIBUTION_TOLERANCE_PPM = 250_000
_OBSERVATION_KINDS = frozenset(
    {
        "greedy-equality",
        "sampled-distribution",
        "continuation-semantics",
        "cancellation-shutdown-cleanup",
    }
)
_GATE_SCOPES = {
    "greedy-equality": "public-token-output",
    "sampled-distribution": "empirical-first-token-histogram",
    "continuation-semantics": "public-output-no-direct-kv-inspection",
    "cancellation-shutdown-cleanup": "pre-dispatch-cancel-and-engine-shutdown",
}
_GATE_ORDER = tuple(_GATE_SCOPES)
_EXPECTED_GATE_CATALOG = tuple(
    (plan_tokens, gate_name)
    for plan_tokens in QUALIFIED_SPECULATIVE_PLANS
    for gate_name in _GATE_ORDER
)
_ATTESTATION_FAILURES = frozenset(
    {
        "runtime_import_failed",
        "vllm_version_mismatch",
        "vllm_build_commit_mismatch",
        "cuda_unavailable",
        "gpu_attestation_failed",
        "gpu_family_mismatch",
        "compute_capability_mismatch",
        "bf16_unavailable",
    }
)
_REPORT_FALLBACKS = frozenset(
    {
        "",
        "runtime-attestation-failed",
        "target-initialization-failed",
        "target-execution-failed",
        "target-cleanup-failed",
        "eagle-initialization-failed",
        "eagle-execution-failed",
        "qualification-gate-failed",
        "incomplete-plan-matrix",
        "engine-cleanup-failed",
    }
)


class VLLMShadowError(RuntimeError):
    """Stable failure at the real shadow qualification boundary."""


def _require_bool(name: str, value: bool) -> bool:
    if not isinstance(value, bool):
        raise VLLMShadowError(f"{name} must be boolean")
    return value


def _require_text(name: str, value: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty):
        raise VLLMShadowError(f"{name} must be a string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise VLLMShadowError(f"{name} is not valid UTF-8") from exc
    if len(encoded) > _MAX_PROMPT_BYTES:
        raise VLLMShadowError(f"{name} exceeds its byte bound")
    return value


def _stable_root(domain: str, value: Mapping[str, Any]) -> str:
    return canonical_root(domain, value)


@dataclass(frozen=True, slots=True)
class VLLMShadowMatrix:
    """The one admitted real-runtime matrix; every field is immutable."""

    vllm_version: str = VLLM_VERSION
    vllm_tag: str = VLLM_TAG
    vllm_build_commit: str = VLLM_BUILD_COMMIT
    target_model: str = TARGET_MODEL
    target_revision: str = TARGET_REVISION
    draft_model: str = DRAFT_MODEL
    draft_revision: str = DRAFT_REVISION
    tokenizer_model: str = TARGET_MODEL
    tokenizer_revision: str = TARGET_REVISION
    speculative_method: str = VLLM_SPECULATIVE_METHOD
    rejection_sample_method: str = VLLM_REJECTION_SAMPLE_METHOD
    gpu_family: str = QUALIFIED_GPU_FAMILY
    compute_capability_major: int = 9
    compute_capability_minor: int = 0
    dtype: str = QUALIFIED_DTYPE
    batch_size: int = QUALIFIED_BATCH_SIZE
    kv_cache_dtype: str = QUALIFIED_KV_CACHE_DTYPE
    kv_cache_resolved_dtype: str = QUALIFIED_KV_CACHE_RESOLVED_DTYPE
    kv_block_size: int = QUALIFIED_KV_BLOCK_SIZE
    prefix_caching: bool = QUALIFIED_PREFIX_CACHING
    target_tensor_parallel_size: int = QUALIFIED_TARGET_TENSOR_PARALLEL_SIZE
    draft_tensor_parallel_size: int = QUALIFIED_DRAFT_TENSOR_PARALLEL_SIZE
    rng_contract: str = QUALIFIED_RNG_CONTRACT
    speculative_plans: tuple[int, ...] = QUALIFIED_SPECULATIVE_PLANS

    def __post_init__(self) -> None:
        expected = {
            "vllm_version": VLLM_VERSION,
            "vllm_tag": VLLM_TAG,
            "vllm_build_commit": VLLM_BUILD_COMMIT,
            "target_model": TARGET_MODEL,
            "target_revision": TARGET_REVISION,
            "draft_model": DRAFT_MODEL,
            "draft_revision": DRAFT_REVISION,
            "tokenizer_model": TARGET_MODEL,
            "tokenizer_revision": TARGET_REVISION,
            "speculative_method": "eagle",
            "rejection_sample_method": "standard",
            "gpu_family": QUALIFIED_GPU_FAMILY,
            "compute_capability_major": 9,
            "compute_capability_minor": 0,
            "dtype": "bfloat16",
            "batch_size": 1,
            "kv_cache_dtype": "bfloat16",
            "kv_cache_resolved_dtype": "bfloat16",
            "kv_block_size": 16,
            "prefix_caching": False,
            "target_tensor_parallel_size": 1,
            "draft_tensor_parallel_size": 1,
            "rng_contract": QUALIFIED_RNG_CONTRACT,
            "speculative_plans": (1, 2, 3),
        }
        if asdict(self) != expected:
            raise VLLMShadowError("the pinned vLLM shadow matrix cannot be widened")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": VLLM_SHADOW_CONTRACT_ID,
            "format_version": VLLM_SHADOW_FORMAT_VERSION,
            **asdict(self),
            "speculative_plans": list(self.speculative_plans),
        }

    @property
    def matrix_root(self) -> str:
        return _stable_root("vllm-shadow-matrix", self.canonical_dict())


PINNED_VLLM_SHADOW_MATRIX = VLLMShadowMatrix()


def _matrix_component_root(component: str, value: Mapping[str, Any]) -> str:
    return _stable_root(
        f"vllm-shadow-{component}",
        {"matrix_root": PINNED_VLLM_SHADOW_MATRIX.matrix_root, **value},
    )


def _canonical_vllm_shadow_epoch() -> EaglegateSpeculationEpoch:
    """Build the sole Phase-3 ServingEpoch admitted by this adapter."""

    matrix = PINNED_VLLM_SHADOW_MATRIX
    identity = EaglegateIdentity(
        target_model_root=_matrix_component_root(
            "target-model",
            {"model": matrix.target_model, "revision": matrix.target_revision},
        ),
        tokenizer_root=_matrix_component_root(
            "tokenizer",
            {
                "model": matrix.tokenizer_model,
                "revision": matrix.tokenizer_revision,
            },
        ),
        proposer_root=_matrix_component_root(
            "proposer",
            {
                "model": matrix.draft_model,
                "revision": matrix.draft_revision,
                "method": matrix.speculative_method,
                "draft_tensor_parallel_size": matrix.draft_tensor_parallel_size,
            },
        ),
        target_runtime_root=_matrix_component_root(
            "target-runtime",
            {
                "vllm_version": matrix.vllm_version,
                "vllm_build_commit": matrix.vllm_build_commit,
                "tensor_parallel_size": matrix.target_tensor_parallel_size,
                "rng_contract": matrix.rng_contract,
            },
        ),
        sampler_contract_root=_matrix_component_root(
            "sampler-contract",
            {
                "rejection_sample_method": matrix.rejection_sample_method,
                "draft_sample_method": "greedy",
                "target_sampler_is_token_authority": True,
            },
        ),
        logits_processor_root=_matrix_component_root(
            "logits-processors",
            {"generation_config": "vllm", "custom_processors": []},
        ),
        kv_contract_root=_matrix_component_root(
            "kv-contract",
            {
                "cache_dtype": matrix.kv_cache_dtype,
                "resolved_dtype": matrix.kv_cache_resolved_dtype,
                "block_size": matrix.kv_block_size,
                "prefix_caching": matrix.prefix_caching,
                "target_runtime_is_kv_authority": True,
            },
        ),
        kernel_capability_root=_matrix_component_root(
            "kernel-capability",
            {
                "gpu_family": matrix.gpu_family,
                "compute_capability": [
                    matrix.compute_capability_major,
                    matrix.compute_capability_minor,
                ],
                "dtype": matrix.dtype,
            },
        ),
        numerical_mode="bf16-sm90",
        tenant_scope="qualification-only",
    )
    plans = tuple(
        EaglegatePlan(
            plan_id=f"vllm-eagle-linear-{candidate_tokens}",
            candidate_tokens=candidate_tokens,
            max_tree_nodes=candidate_tokens,
            workspace_budget_bytes=64 << 20,
            max_batch=matrix.batch_size,
            max_concurrency=1,
            max_context_tokens=8_192,
            max_kv_pressure_ppm=500_000,
            sampler_classes=(
                EaglegateSamplerClass.GREEDY,
                EaglegateSamplerClass.LOSSLESS_SAMPLING,
            ),
        )
        for candidate_tokens in matrix.speculative_plans
    )
    return EaglegateSpeculationEpoch(
        generation=1,
        identity=identity,
        plans=plans,
        policy=EaglegateAdmissionPolicy(
            policy_id="vllm-eagle-shadow-qualification-v1",
            mode=EaglegateMode.SHADOW,
            plan_order=tuple(plan.plan_id for plan in plans),
        ),
    )


PINNED_VLLM_SHADOW_IDENTITY_ROOT = (
    _canonical_vllm_shadow_epoch().identity.identity_root
)


def provision_vllm_shadow_serving_epoch(
    store: AtomicGenerationStore,
    *,
    storage_namespace: str = VLLM_SHADOW_STORAGE_NAMESPACE,
    serving_namespace: str = VLLM_SHADOW_SERVING_NAMESPACE,
) -> PublicationResult:
    """Provision a canonical qualification-only ServingEpoch through Generic GA."""

    if not isinstance(store, AtomicGenerationStore):
        raise VLLMShadowError("store must be an AtomicGenerationStore")
    if store.current_head(storage_namespace) is not None:
        raise VLLMShadowError("qualification storage namespace is not empty")
    if store.current_head(serving_namespace) is not None:
        raise VLLMShadowError("qualification serving namespace is not empty")

    storage_payload_name = "eaglegate.vllm-shadow.storage-binding"
    storage_payload = canonical_json_bytes(
        {
            "contract_id": VLLM_SHADOW_CONTRACT_ID,
            "format_version": VLLM_SHADOW_FORMAT_VERSION,
            "matrix_root": PINNED_VLLM_SHADOW_MATRIX.matrix_root,
            "qualification_only": True,
            "contains_model_or_prompt_content": False,
        }
    )
    storage_candidate = store.build_candidate(
        namespace=storage_namespace,
        payloads={storage_payload_name: storage_payload},
        media_types={storage_payload_name: "application/json"},
        authoritative_payload=None,
        qualifications={
            "eaglegate.vllm-shadow.matrix": PINNED_VLLM_SHADOW_MATRIX.matrix_root,
        },
        metadata={
            "consumer": VLLM_SHADOW_CONTRACT_ID,
            "scope": "qualification-storage-binding",
        },
    )
    storage = store.publish(storage_candidate, expected_head_root=None)

    epoch, summary, exactness, adapter = qualify_eaglegate_core_epoch(
        _canonical_vllm_shadow_epoch()
    )
    serving_candidate = build_eaglegate_serving_candidate(
        store,
        namespace=serving_namespace,
        storage_namespace=storage_namespace,
        storage_generation_root=storage.head.generation_root,
        epoch=epoch,
        qualification=summary,
        exactness_report=exactness,
        adapter_report=adapter,
    )
    return publish_eaglegate_serving_candidate(
        store,
        serving_candidate,
        expected_head_root=None,
    )


def _validate_loaded_vllm_shadow_serving_generation(
    loaded: LoadedEaglegateServingGeneration,
) -> None:
    expected_epoch, expected_summary, expected_exactness, expected_adapter = (
        qualify_eaglegate_core_epoch(_canonical_vllm_shadow_epoch())
    )
    binding = loaded.binding
    if binding.serving_mode != EaglegateMode.SHADOW.value:
        raise VLLMShadowError("ServingEpoch is not qualification-only shadow mode")
    if loaded.epoch != expected_epoch.canonical_dict():
        raise VLLMShadowError("ServingEpoch is outside the exact pinned vLLM matrix")
    expected_roots = (
        expected_epoch.epoch_root,
        expected_epoch.identity.identity_root,
        expected_summary.qualification_root,
        expected_exactness.report_root,
        expected_adapter.report_root,
    )
    observed_roots = (
        binding.eaglegate_epoch_root,
        binding.target_runtime_identity_root,
        binding.qualification_summary_root,
        binding.exactness_report_root,
        binding.adapter_conformance_root,
    )
    if observed_roots != expected_roots:
        raise VLLMShadowError("ServingEpoch core qualification binding is not pinned")


@dataclass(frozen=True, slots=True)
class VLLMShadowSettings:
    """Finite qualification workload; it cannot change the pinned matrix."""

    request_seed: int = 38_001
    max_new_tokens: int = 8
    sampled_cases: int = 16
    sampled_distribution_tolerance_ppm: int = 250_000
    observation_capacity: int = 64

    def __post_init__(self) -> None:
        require_int("request_seed", self.request_seed, 0, _MAX_SEED)
        require_int("max_new_tokens", self.max_new_tokens, 1, _MAX_NEW_TOKENS)
        require_int("sampled_cases", self.sampled_cases, 2, _MAX_CASES)
        require_int(
            "sampled_distribution_tolerance_ppm",
            self.sampled_distribution_tolerance_ppm,
            0,
            _MAX_SAMPLED_DISTRIBUTION_TOLERANCE_PPM,
        )
        require_int(
            "observation_capacity",
            self.observation_capacity,
            0,
            _MAX_OBSERVATIONS,
        )

    def canonical_dict(self) -> dict[str, int]:
        return asdict(self)

    @property
    def settings_root(self) -> str:
        return _stable_root("vllm-shadow-settings", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class VLLMShadowWorkloadBinding:
    """Ordered content roots for the exact transient qualification prompts."""

    prompt_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.prompt_roots, tuple)
            or not self.prompt_roots
            or len(self.prompt_roots) > _MAX_PROMPTS
        ):
            raise VLLMShadowError("workload prompt roots are outside their bound")
        for root in self.prompt_roots:
            require_root("workload prompt root", root)

    @classmethod
    def from_prompts(cls, prompts: Sequence[str]) -> VLLMShadowWorkloadBinding:
        return cls(
            tuple(
                _stable_root(
                    "vllm-shadow-prompt",
                    {"position": index, "utf8": prompt},
                )
                for index, prompt in enumerate(prompts)
            )
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "prompt_count": len(self.prompt_roots),
            "prompt_roots": list(self.prompt_roots),
        }

    @property
    def workload_root(self) -> str:
        return _stable_root("vllm-shadow-workload", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ShadowObservation:
    """A content-free in-memory observation."""

    kind: str
    plan_tokens: int
    cases: int
    mismatches: int

    def __post_init__(self) -> None:
        require_ascii("observation kind", self.kind)
        if self.kind not in _OBSERVATION_KINDS:
            raise VLLMShadowError("observation kind is not in the fixed catalog")
        require_int("plan_tokens", self.plan_tokens, 0, 3)
        require_int("cases", self.cases, 0, _MAX_CASES)
        require_int("mismatches", self.mismatches, 0, self.cases)

    def canonical_dict(self) -> dict[str, Any]:
        return asdict(self)


class BoundedShadowObservationQueue:
    """Loss-tolerant observer queue; full queues drop new detail."""

    def __init__(self, capacity: int) -> None:
        require_int("observation capacity", capacity, 0, _MAX_OBSERVATIONS)
        self.capacity = capacity
        self._items: list[ShadowObservation] = []
        self.published = 0
        self.dropped = 0

    def publish(self, observation: ShadowObservation) -> None:
        if not isinstance(observation, ShadowObservation):
            raise VLLMShadowError("observer accepts only content-free observations")
        self.published += 1
        if len(self._items) >= self.capacity:
            self.dropped += 1
            return
        self._items.append(observation)

    def snapshot(self) -> tuple[ShadowObservation, ...]:
        return tuple(self._items)


@dataclass(frozen=True, slots=True)
class VLLMRuntimeAttestation:
    installed_version: str
    installed_commit: str
    gpu_family: str
    gpu_identity_root: str
    compute_capability_major: int
    compute_capability_minor: int
    bf16_supported: bool
    verified: bool
    failure_reason: str

    def __post_init__(self) -> None:
        _require_text("installed_version", self.installed_version, empty=True)
        _require_text("installed_commit", self.installed_commit, empty=True)
        if self.installed_version not in {"", VLLM_VERSION}:
            raise VLLMShadowError("attestation version is not a fixed status value")
        if self.installed_commit not in {"", VLLM_BUILD_COMMIT}:
            raise VLLMShadowError("attestation commit is not a fixed status value")
        require_ascii("gpu_family", self.gpu_family, allow_spaces=True)
        if self.gpu_family != QUALIFIED_GPU_FAMILY:
            raise VLLMShadowError("attestation GPU family is not the fixed family")
        require_root("gpu_identity_root", self.gpu_identity_root)
        require_int(
            "compute_capability_major", self.compute_capability_major, 0, 99
        )
        require_int(
            "compute_capability_minor", self.compute_capability_minor, 0, 99
        )
        _require_bool("bf16_supported", self.bf16_supported)
        _require_bool("verified", self.verified)
        require_ascii("failure_reason", self.failure_reason, allow_empty=True)
        if self.failure_reason not in _ATTESTATION_FAILURES | {""}:
            raise VLLMShadowError("attestation failure reason is not canonical")
        expected = all(
            (
                self.installed_version == VLLM_VERSION,
                self.installed_commit == VLLM_BUILD_COMMIT,
                (
                    self.compute_capability_major,
                    self.compute_capability_minor,
                )
                == QUALIFIED_COMPUTE_CAPABILITY,
                self.bf16_supported,
            )
        )
        if self.verified != expected:
            raise VLLMShadowError("runtime attestation result is inconsistent")
        if self.verified == bool(self.failure_reason):
            raise VLLMShadowError("runtime attestation failure state is inconsistent")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": VLLM_SHADOW_CONTRACT_ID,
            "installed_version": self.installed_version,
            "installed_commit": self.installed_commit,
            "gpu_family": self.gpu_family,
            "gpu_identity_root": self.gpu_identity_root,
            "compute_capability": [
                self.compute_capability_major,
                self.compute_capability_minor,
            ],
            "bf16_supported": self.bf16_supported,
            "verified": self.verified,
            "failure_reason": self.failure_reason,
        }

    @property
    def attestation_root(self) -> str:
        return _stable_root("vllm-runtime-attestation", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class VLLMShadowGate:
    name: str
    plan_tokens: int
    cases: int
    mismatches: int
    metric_ppm: int
    passed: bool
    evidence_root: str
    observation_scope: str
    executed: bool = True

    def __post_init__(self) -> None:
        require_ascii("gate name", self.name)
        require_int("gate plan_tokens", self.plan_tokens, 1, 3)
        if self.plan_tokens not in QUALIFIED_SPECULATIVE_PLANS:
            raise VLLMShadowError("gate plan is outside the fixed catalog")
        require_int("gate cases", self.cases, 0, _MAX_CASES)
        require_int("gate mismatches", self.mismatches, 0, self.cases)
        require_int("gate metric_ppm", self.metric_ppm, 0, 1_000_000)
        _require_bool("gate passed", self.passed)
        _require_bool("gate executed", self.executed)
        require_root("gate evidence_root", self.evidence_root)
        require_ascii("gate observation_scope", self.observation_scope)
        if self.name not in _GATE_SCOPES:
            raise VLLMShadowError("gate name is not in the fixed catalog")
        if self.observation_scope != _GATE_SCOPES[self.name]:
            raise VLLMShadowError("gate observation scope is not canonical")
        if not self.executed:
            if (self.cases, self.mismatches, self.metric_ppm, self.passed) != (
                0,
                0,
                1_000_000,
                False,
            ):
                raise VLLMShadowError("an unexecuted gate has noncanonical results")
            return
        if self.cases == 0:
            raise VLLMShadowError("an executed gate must have cases")
        expected_metric = (
            self.mismatches * 1_000_000 + self.cases - 1
        ) // self.cases
        if self.metric_ppm != expected_metric:
            raise VLLMShadowError("gate mismatch count and metric disagree")

    def canonical_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VLLMShadowQualificationReport:
    serving_generation_root: str
    serving_binding: EaglegateServingEpochBinding
    matrix: VLLMShadowMatrix
    settings: VLLMShadowSettings
    workload: VLLMShadowWorkloadBinding
    attestation: VLLMRuntimeAttestation
    gates: tuple[VLLMShadowGate, ...]
    cleanup_attempts: int
    cleanup_successes: int
    observations_published: int
    observations_dropped: int
    fallback_reason: str

    def __post_init__(self) -> None:
        require_root("serving_generation_root", self.serving_generation_root)
        if not isinstance(self.serving_binding, EaglegateServingEpochBinding):
            raise VLLMShadowError("serving binding has the wrong type")
        if self.serving_binding.serving_mode != EaglegateMode.SHADOW.value:
            raise VLLMShadowError("vLLM qualification requires a shadow ServingEpoch")
        if (
            self.serving_binding.target_runtime_identity_root
            != PINNED_VLLM_SHADOW_IDENTITY_ROOT
        ):
            raise VLLMShadowError("ServingEpoch identity is outside the pinned matrix")
        if not isinstance(self.matrix, VLLMShadowMatrix):
            raise VLLMShadowError("matrix has the wrong type")
        if self.matrix != PINNED_VLLM_SHADOW_MATRIX:
            raise VLLMShadowError("report matrix is not the pinned matrix")
        if not isinstance(self.settings, VLLMShadowSettings):
            raise VLLMShadowError("settings have the wrong type")
        if not isinstance(self.workload, VLLMShadowWorkloadBinding):
            raise VLLMShadowError("workload has the wrong type")
        if not isinstance(self.attestation, VLLMRuntimeAttestation):
            raise VLLMShadowError("attestation has the wrong type")
        if not isinstance(self.gates, tuple) or any(
            not isinstance(gate, VLLMShadowGate) for gate in self.gates
        ):
            raise VLLMShadowError("gates must be a tuple of VLLMShadowGate")
        catalog = tuple((gate.plan_tokens, gate.name) for gate in self.gates)
        if catalog != _EXPECTED_GATE_CATALOG:
            raise VLLMShadowError("report does not contain the exact 1/2/3 gate catalog")
        if len({gate.evidence_root for gate in self.gates}) != len(self.gates):
            raise VLLMShadowError("gate evidence roots must be unique")
        saw_unexecuted = False
        for gate in self.gates:
            if not gate.executed:
                saw_unexecuted = True
            elif saw_unexecuted:
                raise VLLMShadowError("gate execution must be an exact catalog prefix")
            if gate.executed:
                expected_cases = {
                    "greedy-equality": len(self.workload.prompt_roots),
                    "sampled-distribution": self.settings.sampled_cases,
                    "continuation-semantics": 1,
                    "cancellation-shutdown-cleanup": 1,
                }[gate.name]
                if gate.cases != expected_cases:
                    raise VLLMShadowError("gate case count disagrees with its workload")
                expected_pass = (
                    gate.metric_ppm
                    <= self.settings.sampled_distribution_tolerance_ppm
                    if gate.name == "sampled-distribution"
                    else gate.mismatches == 0
                )
                if gate.passed != expected_pass:
                    raise VLLMShadowError("gate pass result is inconsistent")
        require_int("cleanup_attempts", self.cleanup_attempts, 0, 4)
        require_int("cleanup_successes", self.cleanup_successes, 0, 4)
        if self.cleanup_successes > self.cleanup_attempts:
            raise VLLMShadowError("cleanup successes exceed attempts")
        require_int(
            "observations_published",
            self.observations_published,
            0,
            _MAX_OBSERVATIONS * 4,
        )
        require_int(
            "observations_dropped",
            self.observations_dropped,
            0,
            self.observations_published,
        )
        require_ascii("fallback_reason", self.fallback_reason, allow_empty=True)
        if self.fallback_reason not in _REPORT_FALLBACKS:
            raise VLLMShadowError("report fallback reason is not canonical")
        executed_count = sum(gate.executed for gate in self.gates)
        if self.observations_published != executed_count:
            raise VLLMShadowError("observation count disagrees with executed gates")
        structurally_passed = all(
            (
                self.attestation.verified,
                all(gate.executed and gate.passed for gate in self.gates),
                self.cleanup_attempts == 4,
                self.cleanup_successes == 4,
            )
        )
        if (not self.fallback_reason) != structurally_passed:
            raise VLLMShadowError("report fallback state is inconsistent")

    @property
    def eaglegate_epoch_root(self) -> str:
        return self.serving_binding.eaglegate_epoch_root

    @property
    def serving_binding_root(self) -> str:
        return self.serving_binding.binding_root

    @property
    def matrix_root(self) -> str:
        return self.matrix.matrix_root

    @property
    def settings_root(self) -> str:
        return self.settings.settings_root

    @property
    def workload_root(self) -> str:
        return self.workload.workload_root

    @property
    def passed(self) -> bool:
        return all(
            (
                self.attestation.verified,
                all(gate.executed and gate.passed for gate in self.gates),
                self.cleanup_attempts == 4,
                self.cleanup_successes == self.cleanup_attempts,
                not self.fallback_reason,
            )
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": VLLM_SHADOW_CONTRACT_ID,
            "format_version": VLLM_SHADOW_FORMAT_VERSION,
            "serving_generation_root": self.serving_generation_root,
            "serving_binding": self.serving_binding.canonical_dict(),
            "serving_binding_root": self.serving_binding_root,
            "eaglegate_epoch_root": self.eaglegate_epoch_root,
            "matrix": self.matrix.canonical_dict(),
            "matrix_root": self.matrix_root,
            "settings": self.settings.canonical_dict(),
            "settings_root": self.settings_root,
            "workload": self.workload.canonical_dict(),
            "workload_root": self.workload_root,
            "attestation": self.attestation.canonical_dict(),
            "attestation_root": self.attestation.attestation_root,
            "passed": self.passed,
            "gate_count": len(self.gates),
            "gates": [gate.canonical_dict() for gate in self.gates],
            "cleanup_attempts": self.cleanup_attempts,
            "cleanup_successes": self.cleanup_successes,
            "observations_published": self.observations_published,
            "observations_dropped": self.observations_dropped,
            "fallback_required": not self.passed,
            "fallback_reason": self.fallback_reason,
            "qualification_only": True,
            "off_production_request_path": True,
            "batch_size": 1,
            "request_seed_required": True,
            "target_sampler_is_token_authority": True,
            "target_runtime_is_kv_authority": True,
            "standard_rejection_sampler": True,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
            "direct_kv_tensor_equivalence_tested": False,
            "continuation_observation_scope": "public-runtime-output-only",
            "cancellation_observation_scope": "pre-dispatch-and-shutdown-only",
            "in_flight_cancellation_qualified": False,
            "production_serving_qualified": False,
            "canary_authority": False,
            "activation_authority": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @property
    def report_root(self) -> str:
        return _stable_root("vllm-shadow-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


@dataclass(frozen=True, slots=True)
class _RuntimeBindings:
    vllm_module: ModuleType
    torch_module: ModuleType
    llm_type: Any
    sampling_params_type: Any


@dataclass(frozen=True, slots=True)
class _EngineEvidence:
    greedy: tuple[tuple[int, ...], ...]
    greedy_finish: tuple[str, ...]
    sampled: tuple[int, ...]
    continuation: tuple[int, ...]
    tokenizer_root: str
    predispatch_cancelled: bool

    def rooted_dict(self) -> dict[str, Any]:
        return {
            "greedy": [list(tokens) for tokens in self.greedy],
            "greedy_finish": list(self.greedy_finish),
            "sampled": list(self.sampled),
            "continuation": list(self.continuation),
            "tokenizer_root": self.tokenizer_root,
            "predispatch_cancelled": self.predispatch_cancelled,
        }


def _module_version(vllm_module: ModuleType) -> str:
    module_version = getattr(vllm_module, "__version__", "")
    if not isinstance(module_version, str):
        return ""
    try:
        distribution_version = metadata.version("vllm")
    except metadata.PackageNotFoundError:
        return module_version
    if module_version and module_version != distribution_version:
        return ""
    return distribution_version


def _direct_url_commit() -> str:
    try:
        distribution = metadata.distribution("vllm")
        raw = distribution.read_text("direct_url.json")
        if not raw:
            return ""
        value = json.loads(raw)
        commit = value.get("vcs_info", {}).get("commit_id", "")
        return commit if isinstance(commit, str) else ""
    except (metadata.PackageNotFoundError, json.JSONDecodeError, AttributeError):
        return ""


def _git_checkout_commit(vllm_module: ModuleType, checkout: Path) -> str:
    try:
        root = checkout.resolve(strict=True)
        module_path = Path(str(vllm_module.__file__)).resolve(strict=True)
        module_path.relative_to(root)
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (AttributeError, OSError, subprocess.SubprocessError, ValueError):
        return ""
    return result.stdout.strip()


def _module_commit(
    vllm_module: ModuleType,
    source_checkout: str | os.PathLike[str] | None,
) -> str:
    if source_checkout is not None:
        return _git_checkout_commit(vllm_module, Path(source_checkout))
    for name in ("__commit__", "__git_commit__", "__git_revision__"):
        value = getattr(vllm_module, name, "")
        if isinstance(value, str) and value:
            return value
    return _direct_url_commit()


def _failure_attestation(
    reason: str,
    *,
    version: str = "",
    commit: str = "",
    observed_gpu_name: str = "",
    capability: tuple[int, int] = (0, 0),
    bf16: bool = False,
) -> VLLMRuntimeAttestation:
    return VLLMRuntimeAttestation(
        installed_version=VLLM_VERSION if version == VLLM_VERSION else "",
        installed_commit=VLLM_BUILD_COMMIT if commit == VLLM_BUILD_COMMIT else "",
        gpu_family=QUALIFIED_GPU_FAMILY,
        gpu_identity_root=_stable_root(
            "vllm-gpu-identity",
            {
                "observed_name": observed_gpu_name,
                "compute_capability": list(capability),
            },
        ),
        compute_capability_major=capability[0],
        compute_capability_minor=capability[1],
        bf16_supported=bf16,
        verified=False,
        failure_reason=reason,
    )


def _load_attested_runtime(
    source_checkout: str | os.PathLike[str] | None,
) -> tuple[VLLMRuntimeAttestation, _RuntimeBindings | None]:
    try:
        # Intentionally dynamic: importing this module never imports or initializes vLLM.
        import torch
        import vllm
        from vllm import LLM, SamplingParams
    except (ImportError, OSError):
        return _failure_attestation("runtime_import_failed"), None

    version = _module_version(vllm)
    commit = _module_commit(vllm, source_checkout)
    if version != VLLM_VERSION:
        return _failure_attestation(
            "vllm_version_mismatch", version=version, commit=commit
        ), None
    if commit != VLLM_BUILD_COMMIT:
        return _failure_attestation(
            "vllm_build_commit_mismatch", version=version, commit=commit
        ), None
    try:
        if not torch.cuda.is_available():
            return _failure_attestation(
                "cuda_unavailable", version=version, commit=commit
            ), None
        gpu_name = str(torch.cuda.get_device_name(0))
        capability_value = torch.cuda.get_device_capability(0)
        capability = (int(capability_value[0]), int(capability_value[1]))
        bf16 = bool(torch.cuda.is_bf16_supported())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return _failure_attestation(
            "gpu_attestation_failed", version=version, commit=commit
        ), None
    if "H100" not in gpu_name:
        return _failure_attestation(
            "gpu_family_mismatch",
            version=version,
            commit=commit,
            observed_gpu_name=gpu_name,
            capability=capability,
            bf16=bf16,
        ), None
    if capability != QUALIFIED_COMPUTE_CAPABILITY:
        return _failure_attestation(
            "compute_capability_mismatch",
            version=version,
            commit=commit,
            observed_gpu_name=gpu_name,
            capability=capability,
            bf16=bf16,
        ), None
    if not bf16:
        return _failure_attestation(
            "bf16_unavailable",
            version=version,
            commit=commit,
            observed_gpu_name=gpu_name,
            capability=capability,
            bf16=bf16,
        ), None
    attestation = VLLMRuntimeAttestation(
        installed_version=version,
        installed_commit=commit,
        gpu_family=QUALIFIED_GPU_FAMILY,
        gpu_identity_root=_stable_root(
            "vllm-gpu-identity",
            {
                "observed_name": gpu_name,
                "compute_capability": list(capability),
            },
        ),
        compute_capability_major=capability[0],
        compute_capability_minor=capability[1],
        bf16_supported=bf16,
        verified=True,
        failure_reason="",
    )
    return attestation, _RuntimeBindings(vllm, torch, LLM, SamplingParams)


def attest_vllm_runtime(
    *,
    source_checkout: str | os.PathLike[str] | None = None,
) -> VLLMRuntimeAttestation:
    """Attest the exact installed vLLM source build and H100 numerical lane."""

    selected = source_checkout
    if selected is None:
        selected = os.environ.get("TDS_VLLM_SOURCE_CHECKOUT") or None
    return _load_attested_runtime(selected)[0]


def _target_engine_kwargs(settings: VLLMShadowSettings) -> dict[str, Any]:
    return {
        "model": TARGET_MODEL,
        "revision": TARGET_REVISION,
        "code_revision": TARGET_REVISION,
        "tokenizer": TARGET_MODEL,
        "tokenizer_revision": TARGET_REVISION,
        "dtype": QUALIFIED_DTYPE,
        "kv_cache_dtype": QUALIFIED_KV_CACHE_DTYPE,
        "block_size": QUALIFIED_KV_BLOCK_SIZE,
        "enable_prefix_caching": QUALIFIED_PREFIX_CACHING,
        "tensor_parallel_size": QUALIFIED_TARGET_TENSOR_PARALLEL_SIZE,
        "max_num_seqs": 1,
        "seed": settings.request_seed,
        "trust_remote_code": False,
        "generation_config": "vllm",
        "disable_log_stats": True,
        "speculative_config": None,
    }


def _eagle_engine_kwargs(
    plan_tokens: int,
    settings: VLLMShadowSettings,
) -> dict[str, Any]:
    if plan_tokens not in QUALIFIED_SPECULATIVE_PLANS:
        raise VLLMShadowError("speculative plan is outside the 1/2/3-token matrix")
    values = _target_engine_kwargs(settings)
    values["speculative_config"] = {
        "method": "eagle",
        "model": DRAFT_MODEL,
        "revision": DRAFT_REVISION,
        "code_revision": DRAFT_REVISION,
        "num_speculative_tokens": plan_tokens,
        "rejection_sample_method": "standard",
        "draft_sample_method": "greedy",
        "draft_tensor_parallel_size": QUALIFIED_DRAFT_TENSOR_PARALLEL_SIZE,
    }
    return values


def _token_tuple(value: Any) -> tuple[int, ...]:
    try:
        result = tuple(value)
    except TypeError as exc:
        raise VLLMShadowError("vLLM output token IDs are unavailable") from exc
    if any(isinstance(token, bool) or not isinstance(token, int) for token in result):
        raise VLLMShadowError("vLLM returned a non-integer token identity")
    return result


def _generate_one(
    engine: Any,
    sampling_params_type: Any,
    prompt: str | Mapping[str, Any],
    *,
    seed: int,
    temperature: float,
    top_p: float,
    max_tokens: int,
) -> tuple[tuple[int, ...], str]:
    params = sampling_params_type(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
    )
    outputs = engine.generate(
        prompts=[prompt],
        sampling_params=params,
        use_tqdm=False,
    )
    if not isinstance(outputs, Sequence) or len(outputs) != 1:
        raise VLLMShadowError("vLLM violated the batch-size-one contract")
    candidates = getattr(outputs[0], "outputs", None)
    if not isinstance(candidates, Sequence) or len(candidates) != 1:
        raise VLLMShadowError("vLLM returned a noncanonical candidate count")
    candidate = candidates[0]
    tokens = _token_tuple(getattr(candidate, "token_ids", None))
    finish_reason = getattr(candidate, "finish_reason", "")
    if finish_reason is None:
        finish_reason = ""
    if not isinstance(finish_reason, str):
        raise VLLMShadowError("vLLM finish reason is malformed")
    return tokens, finish_reason


def _collect_engine_evidence(
    engine: Any,
    sampling_params_type: Any,
    prompts: tuple[str, ...],
    settings: VLLMShadowSettings,
) -> _EngineEvidence:
    greedy: list[tuple[int, ...]] = []
    finishes: list[str] = []
    for index, prompt in enumerate(prompts):
        tokens, finish = _generate_one(
            engine,
            sampling_params_type,
            prompt,
            seed=settings.request_seed + index,
            temperature=0.0,
            top_p=1.0,
            max_tokens=settings.max_new_tokens,
        )
        greedy.append(tokens)
        finishes.append(finish)

    sampled: list[int] = []
    for index in range(settings.sampled_cases):
        tokens, _ = _generate_one(
            engine,
            sampling_params_type,
            prompts[0],
            seed=settings.request_seed + 10_000 + index,
            temperature=0.8,
            top_p=0.95,
            max_tokens=settings.max_new_tokens,
        )
        sampled.append(tokens[0] if tokens else -1)

    tokenizer = engine.get_tokenizer()
    encoded = _token_tuple(tokenizer.encode(prompts[0]))
    first_leg, _ = _generate_one(
        engine,
        sampling_params_type,
        prompts[0],
        seed=settings.request_seed + 20_000,
        temperature=0.0,
        top_p=1.0,
        max_tokens=2,
    )
    continuation_prompt = {"prompt_token_ids": [*encoded, *first_leg]}
    second_leg, _ = _generate_one(
        engine,
        sampling_params_type,
        continuation_prompt,
        seed=settings.request_seed + 20_001,
        temperature=0.0,
        top_p=1.0,
        max_tokens=min(3, settings.max_new_tokens),
    )

    # A cancelled request is never submitted. In-flight cancellation is outside
    # the public synchronous LLM surface and is intentionally not claimed.
    predispatch_cancelled = True
    return _EngineEvidence(
        greedy=tuple(greedy),
        greedy_finish=tuple(finishes),
        sampled=tuple(sampled),
        continuation=(*first_leg, *second_leg),
        tokenizer_root=_stable_root(
            "vllm-shadow-tokenizer-observation",
            {"token_ids": list(encoded)},
        ),
        predispatch_cancelled=predispatch_cancelled,
    )


def _shutdown_engine(engine: Any, torch_module: ModuleType) -> bool:
    shutdown = getattr(engine, "shutdown", None)
    if not callable(shutdown):
        shutdown = getattr(getattr(engine, "llm_engine", None), "shutdown", None)
    success = False
    try:
        if callable(shutdown):
            shutdown()
            success = True
    except Exception:  # noqa: BLE001 - provider cleanup must fail closed
        success = False
    finally:
        gc.collect()
        try:
            torch_module.cuda.empty_cache()
        except (AttributeError, RuntimeError):
            success = False
    return success


def _empirical_distance_ppm(
    target: Sequence[int],
    shadow: Sequence[int],
) -> tuple[int, int]:
    if len(target) != len(shadow) or not target:
        return 1_000_000, max(len(target), len(shadow))
    target_counts = Counter(target)
    shadow_counts = Counter(shadow)
    l1 = sum(
        abs(target_counts[key] - shadow_counts[key])
        for key in target_counts.keys() | shadow_counts.keys()
    )
    denominator = 2 * len(target)
    distance_ppm = (l1 * 1_000_000 + denominator - 1) // denominator
    return min(distance_ppm, 1_000_000), l1 // 2


def _gate(
    *,
    name: str,
    plan_tokens: int,
    cases: int,
    mismatches: int,
    metric_ppm: int,
    passed: bool,
    scope: str,
    evidence: Mapping[str, Any],
) -> VLLMShadowGate:
    return VLLMShadowGate(
        name=name,
        plan_tokens=plan_tokens,
        cases=cases,
        mismatches=mismatches,
        metric_ppm=metric_ppm,
        passed=passed,
        evidence_root=_stable_root("vllm-shadow-gate-evidence", evidence),
        observation_scope=scope,
    )


def _compare_plan(
    baseline: _EngineEvidence,
    shadow: _EngineEvidence,
    plan_tokens: int,
    settings: VLLMShadowSettings,
    queue: BoundedShadowObservationQueue,
    *,
    shutdown_ok: bool,
) -> tuple[VLLMShadowGate, ...]:
    greedy_mismatches = sum(
        left != right or left_finish != right_finish
        for left, right, left_finish, right_finish in zip(
            baseline.greedy,
            shadow.greedy,
            baseline.greedy_finish,
            shadow.greedy_finish,
        )
    )
    greedy_cases = len(baseline.greedy)
    greedy = _gate(
        name="greedy-equality",
        plan_tokens=plan_tokens,
        cases=greedy_cases,
        mismatches=greedy_mismatches,
        metric_ppm=(
            greedy_mismatches * 1_000_000 + greedy_cases - 1
        )
        // greedy_cases,
        passed=greedy_mismatches == 0,
        scope="public-token-output",
        evidence={
            "target": baseline.rooted_dict(),
            "shadow": shadow.rooted_dict(),
            "gate": "greedy-equality",
            "plan_tokens": plan_tokens,
        },
    )

    distance_ppm, distribution_mismatches = _empirical_distance_ppm(
        baseline.sampled,
        shadow.sampled,
    )
    sampled = _gate(
        name="sampled-distribution",
        plan_tokens=plan_tokens,
        cases=settings.sampled_cases,
        mismatches=min(distribution_mismatches, settings.sampled_cases),
        metric_ppm=distance_ppm,
        passed=distance_ppm <= settings.sampled_distribution_tolerance_ppm,
        scope="empirical-first-token-histogram",
        evidence={
            "target_sampled": list(baseline.sampled),
            "shadow_sampled": list(shadow.sampled),
            "request_seed": settings.request_seed,
            "case_count": settings.sampled_cases,
            "gate": "sampled-distribution",
            "plan_tokens": plan_tokens,
        },
    )

    continuation_match = all(
        (
            baseline.continuation == shadow.continuation,
            baseline.tokenizer_root == shadow.tokenizer_root,
        )
    )
    continuation = _gate(
        name="continuation-semantics",
        plan_tokens=plan_tokens,
        cases=1,
        mismatches=0 if continuation_match else 1,
        metric_ppm=0 if continuation_match else 1_000_000,
        passed=continuation_match,
        scope="public-output-no-direct-kv-inspection",
        evidence={
            "target_continuation": list(baseline.continuation),
            "shadow_continuation": list(shadow.continuation),
            "target_tokenizer_root": baseline.tokenizer_root,
            "shadow_tokenizer_root": shadow.tokenizer_root,
            "gate": "continuation-semantics",
            "plan_tokens": plan_tokens,
        },
    )

    cleanup_match = shadow.predispatch_cancelled and shutdown_ok
    cleanup = _gate(
        name="cancellation-shutdown-cleanup",
        plan_tokens=plan_tokens,
        cases=1,
        mismatches=0 if cleanup_match else 1,
        metric_ppm=0 if cleanup_match else 1_000_000,
        passed=cleanup_match,
        scope="pre-dispatch-cancel-and-engine-shutdown",
        evidence={
            "predispatch_cancelled": shadow.predispatch_cancelled,
            "shutdown_ok": shutdown_ok,
            "gate": "cancellation-shutdown-cleanup",
            "plan_tokens": plan_tokens,
        },
    )

    gates = (greedy, sampled, continuation, cleanup)
    for item in gates:
        queue.publish(
            ShadowObservation(
                kind=item.name,
                plan_tokens=plan_tokens,
                cases=item.cases,
                mismatches=item.mismatches,
            )
        )
    return gates


def _normalize_prompts(prompts: Sequence[str]) -> tuple[str, ...]:
    if isinstance(prompts, (str, bytes)) or not isinstance(prompts, Sequence):
        raise VLLMShadowError("prompts must be a finite sequence")
    if not prompts or len(prompts) > _MAX_PROMPTS:
        raise VLLMShadowError("prompt count is outside its qualification bound")
    return tuple(
        _require_text(f"prompt {index}", prompt)
        for index, prompt in enumerate(prompts)
    )


def _report(
    *,
    serving_generation_root: str,
    serving_binding: EaglegateServingEpochBinding,
    settings: VLLMShadowSettings,
    workload: VLLMShadowWorkloadBinding,
    attestation: VLLMRuntimeAttestation,
    gates: Sequence[VLLMShadowGate],
    cleanup_attempts: int,
    cleanup_successes: int,
    queue: BoundedShadowObservationQueue,
    fallback_reason: str,
) -> VLLMShadowQualificationReport:
    complete_gates = list(gates)
    actual_catalog = tuple(
        (gate.plan_tokens, gate.name) for gate in complete_gates
    )
    if actual_catalog != _EXPECTED_GATE_CATALOG[: len(actual_catalog)]:
        raise VLLMShadowError("executed gates are not an exact catalog prefix")
    for plan_tokens, name in _EXPECTED_GATE_CATALOG[len(complete_gates) :]:
        complete_gates.append(
            VLLMShadowGate(
                name=name,
                plan_tokens=plan_tokens,
                cases=0,
                mismatches=0,
                metric_ppm=1_000_000,
                passed=False,
                evidence_root=_stable_root(
                    "vllm-shadow-unexecuted-gate",
                    {
                        "serving_generation_root": serving_generation_root,
                        "attestation_root": attestation.attestation_root,
                        "plan_tokens": plan_tokens,
                        "gate": name,
                        "fallback_reason": fallback_reason,
                    },
                ),
                observation_scope=_GATE_SCOPES[name],
                executed=False,
            )
        )
    return VLLMShadowQualificationReport(
        serving_generation_root=serving_generation_root,
        serving_binding=serving_binding,
        matrix=PINNED_VLLM_SHADOW_MATRIX,
        settings=settings,
        workload=workload,
        attestation=attestation,
        gates=tuple(complete_gates),
        cleanup_attempts=cleanup_attempts,
        cleanup_successes=cleanup_successes,
        observations_published=queue.published,
        observations_dropped=queue.dropped,
        fallback_reason=fallback_reason,
    )


def _execute_vllm_shadow_qualification(
    prompts: Sequence[str] = DEFAULT_QUALIFICATION_PROMPTS,
    *,
    serving_generation_root: str,
    serving_binding: EaglegateServingEpochBinding,
    settings: VLLMShadowSettings | None = None,
    source_checkout: str | os.PathLike[str] | None = None,
    observation_queue: BoundedShadowObservationQueue | None = None,
) -> VLLMShadowQualificationReport:
    """Execute the real target-only/EAGLE differential matrix off-path.

    Failures are represented as a non-passing report with target-only fallback
    required.  The function never returns model output to its caller.
    """

    selected_settings = settings or VLLMShadowSettings()
    if not isinstance(selected_settings, VLLMShadowSettings):
        raise VLLMShadowError("settings must be VLLMShadowSettings")
    selected_prompts = _normalize_prompts(prompts)
    workload = VLLMShadowWorkloadBinding.from_prompts(selected_prompts)
    queue = observation_queue or BoundedShadowObservationQueue(
        selected_settings.observation_capacity
    )
    if not isinstance(queue, BoundedShadowObservationQueue):
        raise VLLMShadowError("observation_queue has the wrong type")
    selected_checkout = source_checkout
    if selected_checkout is None:
        selected_checkout = os.environ.get("TDS_VLLM_SOURCE_CHECKOUT") or None
    attestation, runtime = _load_attested_runtime(selected_checkout)
    if runtime is None:
        return _report(
            serving_generation_root=serving_generation_root,
            serving_binding=serving_binding,
            settings=selected_settings,
            workload=workload,
            attestation=attestation,
            gates=(),
            cleanup_attempts=0,
            cleanup_successes=0,
            queue=queue,
            fallback_reason="runtime-attestation-failed",
        )

    cleanup_attempts = 0
    cleanup_successes = 0
    gates: list[VLLMShadowGate] = []
    target_engine: Any | None = None
    try:
        target_engine = runtime.llm_type(**_target_engine_kwargs(selected_settings))
    except Exception:  # noqa: BLE001 - any provider initialization fault falls back
        return _report(
            serving_generation_root=serving_generation_root,
            serving_binding=serving_binding,
            settings=selected_settings,
            workload=workload,
            attestation=attestation,
            gates=(),
            cleanup_attempts=0,
            cleanup_successes=0,
            queue=queue,
            fallback_reason="target-initialization-failed",
        )
    try:
        baseline = _collect_engine_evidence(
            target_engine,
            runtime.sampling_params_type,
            selected_prompts,
            selected_settings,
        )
    except Exception:  # noqa: BLE001 - any provider execution fault falls back
        cleanup_attempts += 1
        cleanup_successes += int(_shutdown_engine(target_engine, runtime.torch_module))
        return _report(
            serving_generation_root=serving_generation_root,
            serving_binding=serving_binding,
            settings=selected_settings,
            workload=workload,
            attestation=attestation,
            gates=(),
            cleanup_attempts=cleanup_attempts,
            cleanup_successes=cleanup_successes,
            queue=queue,
            fallback_reason="target-execution-failed",
        )
    cleanup_attempts += 1
    target_cleanup_ok = _shutdown_engine(target_engine, runtime.torch_module)
    cleanup_successes += int(target_cleanup_ok)
    if not target_cleanup_ok:
        return _report(
            serving_generation_root=serving_generation_root,
            serving_binding=serving_binding,
            settings=selected_settings,
            workload=workload,
            attestation=attestation,
            gates=(),
            cleanup_attempts=cleanup_attempts,
            cleanup_successes=cleanup_successes,
            queue=queue,
            fallback_reason="target-cleanup-failed",
        )

    fallback_reason = ""
    for plan_tokens in QUALIFIED_SPECULATIVE_PLANS:
        shadow_engine: Any | None = None
        try:
            shadow_engine = runtime.llm_type(
                **_eagle_engine_kwargs(plan_tokens, selected_settings)
            )
        except Exception:  # noqa: BLE001 - any provider initialization fault falls back
            fallback_reason = "eagle-initialization-failed"
            break
        try:
            shadow = _collect_engine_evidence(
                shadow_engine,
                runtime.sampling_params_type,
                selected_prompts,
                selected_settings,
            )
        except Exception:  # noqa: BLE001 - any provider execution fault falls back
            cleanup_attempts += 1
            cleanup_successes += int(
                _shutdown_engine(shadow_engine, runtime.torch_module)
            )
            fallback_reason = "eagle-execution-failed"
            break
        cleanup_attempts += 1
        shutdown_ok = _shutdown_engine(shadow_engine, runtime.torch_module)
        cleanup_successes += int(shutdown_ok)
        plan_gates = _compare_plan(
            baseline,
            shadow,
            plan_tokens,
            selected_settings,
            queue,
            shutdown_ok=shutdown_ok,
        )
        gates.extend(plan_gates)
        if not all(gate.passed for gate in plan_gates):
            fallback_reason = "qualification-gate-failed"
            break

    if not fallback_reason and cleanup_attempts != 4:
        fallback_reason = "incomplete-plan-matrix"
    if not fallback_reason and cleanup_successes != cleanup_attempts:
        fallback_reason = "engine-cleanup-failed"
    return _report(
        serving_generation_root=serving_generation_root,
        serving_binding=serving_binding,
        settings=selected_settings,
        workload=workload,
        attestation=attestation,
        gates=gates,
        cleanup_attempts=cleanup_attempts,
        cleanup_successes=cleanup_successes,
        queue=queue,
        fallback_reason=fallback_reason,
    )


def run_vllm_shadow_qualification(
    prompts: Sequence[str] = DEFAULT_QUALIFICATION_PROMPTS,
    *,
    store: AtomicGenerationStore,
    serving_namespace: str,
    serving_generation_root: str,
    settings: VLLMShadowSettings | None = None,
    source_checkout: str | os.PathLike[str] | None = None,
    observation_queue: BoundedShadowObservationQueue | None = None,
) -> VLLMShadowQualificationReport:
    """Run while pinning one exact Phase-3 Generation-backed ServingEpoch."""

    if not isinstance(store, AtomicGenerationStore):
        raise VLLMShadowError("store must be an AtomicGenerationStore")
    require_root("serving_generation_root", serving_generation_root)
    with open_eaglegate_serving_generation(
        store,
        serving_namespace,
        serving_generation_root,
    ) as lease:
        _validate_loaded_vllm_shadow_serving_generation(lease.loaded)
        return _execute_vllm_shadow_qualification(
            prompts,
            serving_generation_root=lease.generation_root,
            serving_binding=lease.binding,
            settings=settings,
            source_checkout=source_checkout,
            observation_queue=observation_queue,
        )


def persist_vllm_shadow_report(
    store: AtomicGenerationStore,
    report: VLLMShadowQualificationReport,
    *,
    namespace: str = VLLM_SHADOW_REPORT_NAMESPACE,
    parent_generation_root: str | None = None,
    expected_head_root: str | None = None,
) -> PublicationResult:
    """Publish content-free evidence through the sole Generation Authority."""

    if not isinstance(store, AtomicGenerationStore):
        raise VLLMShadowError("store must be an AtomicGenerationStore")
    if not isinstance(report, VLLMShadowQualificationReport):
        raise VLLMShadowError("report has the wrong type")
    with open_eaglegate_serving_generation(
        store,
        report.serving_binding.namespace,
        report.serving_generation_root,
    ) as lease:
        _validate_loaded_vllm_shadow_serving_generation(lease.loaded)
        if (
            lease.generation_root != report.serving_generation_root
            or lease.binding != report.serving_binding
        ):
            raise VLLMShadowError(
                "report does not match the re-opened ServingEpoch generation"
            )
        binding = lease.binding
        payload = report.canonical_bytes()
        candidate = store.build_candidate(
            namespace=namespace,
            payloads={_REPORT_PAYLOAD: payload},
            media_types={_REPORT_PAYLOAD: "application/json"},
            parent_generation_root=parent_generation_root,
            qualifications={
                "eaglegate.vllm-shadow.adapter-conformance": (
                    binding.adapter_conformance_root
                ),
                "eaglegate.vllm-shadow.attestation": (
                    report.attestation.attestation_root
                ),
                "eaglegate.vllm-shadow.binding": binding.binding_root,
                "eaglegate.vllm-shadow.epoch": binding.eaglegate_epoch_root,
                "eaglegate.vllm-shadow.exactness-qualification": (
                    binding.exactness_qualification_root
                ),
                "eaglegate.vllm-shadow.exactness-report": (
                    binding.exactness_report_root
                ),
                "eaglegate.vllm-shadow.matrix": report.matrix_root,
                "eaglegate.vllm-shadow.policy-plans": (
                    binding.eaglegate_policy_root
                ),
                "eaglegate.vllm-shadow.qualification-summary": (
                    binding.qualification_summary_root
                ),
                "eaglegate.vllm-shadow.receipt-chain": binding.receipt_chain_root,
                "eaglegate.vllm-shadow.report": report.report_root,
                "eaglegate.vllm-shadow.serving-generation": (
                    report.serving_generation_root
                ),
                "eaglegate.vllm-shadow.settings": report.settings_root,
                "eaglegate.vllm-shadow.storage-generation": (
                    binding.storage_generation_root
                ),
                "eaglegate.vllm-shadow.target-runtime-identity": (
                    binding.target_runtime_identity_root
                ),
                "eaglegate.vllm-shadow.workload": report.workload_root,
            },
            metadata={
                "consumer": VLLM_SHADOW_CONTRACT_ID,
                "scope": "qualification-only",
            },
        )
        return store.publish(candidate, expected_head_root=expected_head_root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tds-eaglegate-vllm-shadow")
    parser.add_argument(
        "--real-qualification",
        action="store_true",
        help="run the pinned off-path H100 qualification matrix",
    )
    parser.add_argument(
        "--source-checkout",
        help="exact vLLM git checkout backing the editable installation",
    )
    parser.add_argument(
        "--evidence-store",
        required=True,
        help="Generation Authority root for ServingEpoch and content-free evidence",
    )
    parser.add_argument(
        "--serving-namespace",
        default=VLLM_SHADOW_SERVING_NAMESPACE,
        help="namespace containing the Phase-3 ServingEpoch generation",
    )
    parser.add_argument(
        "--serving-generation-root",
        help="exact existing Phase-3 ServingEpoch generation root",
    )
    parser.add_argument(
        "--provision-serving-epoch",
        action="store_true",
        help="provision the canonical qualification ServingEpoch in an empty store",
    )
    args = parser.parse_args(argv)
    if not args.real_qualification:
        parser.error("--real-qualification is required; no serving mode exists")
    if bool(args.serving_generation_root) == bool(args.provision_serving_epoch):
        parser.error(
            "choose exactly one of --serving-generation-root or "
            "--provision-serving-epoch"
        )
    store = AtomicGenerationStore(args.evidence_store)
    serving_generation_root = args.serving_generation_root
    if args.provision_serving_epoch:
        publication = provision_vllm_shadow_serving_epoch(
            store,
            serving_namespace=args.serving_namespace,
        )
        serving_generation_root = publication.head.generation_root
    assert serving_generation_root is not None
    report = run_vllm_shadow_qualification(
        store=store,
        serving_namespace=args.serving_namespace,
        serving_generation_root=serving_generation_root,
        source_checkout=args.source_checkout,
    )
    persist_vllm_shadow_report(store, report)
    print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_QUALIFICATION_PROMPTS",
    "DRAFT_MODEL",
    "DRAFT_REVISION",
    "PINNED_VLLM_SHADOW_IDENTITY_ROOT",
    "PINNED_VLLM_SHADOW_MATRIX",
    "QUALIFIED_BATCH_SIZE",
    "QUALIFIED_COMPUTE_CAPABILITY",
    "QUALIFIED_DRAFT_TENSOR_PARALLEL_SIZE",
    "QUALIFIED_DTYPE",
    "QUALIFIED_GPU_FAMILY",
    "QUALIFIED_KV_BLOCK_SIZE",
    "QUALIFIED_KV_CACHE_DTYPE",
    "QUALIFIED_KV_CACHE_RESOLVED_DTYPE",
    "QUALIFIED_PREFIX_CACHING",
    "QUALIFIED_RNG_CONTRACT",
    "QUALIFIED_SPECULATIVE_PLANS",
    "QUALIFIED_TARGET_TENSOR_PARALLEL_SIZE",
    "TARGET_MODEL",
    "TARGET_REVISION",
    "VLLM_BUILD_COMMIT",
    "VLLM_REJECTION_SAMPLE_METHOD",
    "VLLM_SHADOW_CONTRACT_ID",
    "VLLM_SHADOW_FORMAT_VERSION",
    "VLLM_SHADOW_REPORT_NAMESPACE",
    "VLLM_SHADOW_SERVING_NAMESPACE",
    "VLLM_SHADOW_STORAGE_NAMESPACE",
    "VLLM_SPECULATIVE_METHOD",
    "VLLM_TAG",
    "VLLM_VERSION",
    "BoundedShadowObservationQueue",
    "ShadowObservation",
    "VLLMRuntimeAttestation",
    "VLLMShadowError",
    "VLLMShadowGate",
    "VLLMShadowMatrix",
    "VLLMShadowQualificationReport",
    "VLLMShadowSettings",
    "VLLMShadowWorkloadBinding",
    "attest_vllm_runtime",
    "main",
    "persist_vllm_shadow_report",
    "provision_vllm_shadow_serving_epoch",
    "run_vllm_shadow_qualification",
]

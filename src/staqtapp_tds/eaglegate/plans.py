"""Immutable Eaglegate plan, policy, qualification, and epoch records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import (
    EAGLEGATE_AUTHORITY,
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
    EAGLEGATE_SELECTION_CONTRACT_ID,
    EaglegateContractError,
    EaglegateFault,
    EaglegateIdentity,
    EaglegateMode,
    EaglegateSamplerClass,
    _U16,
    _U32,
    _ascii,
    _bool,
    _canonical_root,
    _enum,
    _int,
    _root,
)


@dataclass(frozen=True, slots=True)
class EaglegatePlan:
    plan_id: str
    candidate_tokens: int
    max_tree_nodes: int
    workspace_budget_bytes: int
    max_batch: int
    max_concurrency: int
    max_context_tokens: int
    max_kv_pressure_ppm: int
    sampler_classes: tuple[EaglegateSamplerClass, ...]

    def __post_init__(self) -> None:
        _ascii("plan_id", self.plan_id)
        _int("candidate_tokens", self.candidate_tokens, 1, _U16)
        _int("max_tree_nodes", self.max_tree_nodes, 1, _U32)
        if self.max_tree_nodes < self.candidate_tokens:
            raise EaglegateContractError("tree must cover a complete candidate path")
        _int("workspace_budget_bytes", self.workspace_budget_bytes, 1)
        _int("max_batch", self.max_batch, 1, _U16)
        _int("max_concurrency", self.max_concurrency, 1, _U16)
        _int("max_context_tokens", self.max_context_tokens, 1, _U32)
        _int("max_kv_pressure_ppm", self.max_kv_pressure_ppm, 0, 1_000_000)
        if not isinstance(self.sampler_classes, tuple) or not self.sampler_classes:
            raise EaglegateContractError("sampler_classes must be a non-empty tuple")
        for value in self.sampler_classes:
            _enum("sampler_class", value, EaglegateSamplerClass)
        if len(set(self.sampler_classes)) != len(self.sampler_classes):
            raise EaglegateContractError(
                "sampler classes must be unique", fault=EaglegateFault.NONCANONICAL
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "plan_id": self.plan_id,
            "candidate_tokens": self.candidate_tokens,
            "max_tree_nodes": self.max_tree_nodes,
            "workspace_budget_bytes": self.workspace_budget_bytes,
            "max_batch": self.max_batch,
            "max_concurrency": self.max_concurrency,
            "max_context_tokens": self.max_context_tokens,
            "max_kv_pressure_ppm": self.max_kv_pressure_ppm,
            "sampler_classes": [item.value for item in self.sampler_classes],
        }

    @property
    def plan_root(self) -> str:
        return _canonical_root("plan", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateAdmissionPolicy:
    policy_id: str
    mode: EaglegateMode
    plan_order: tuple[str, ...]
    canary_basis_points: int = 0
    selection_contract_id: str = EAGLEGATE_SELECTION_CONTRACT_ID

    def __post_init__(self) -> None:
        _ascii("policy_id", self.policy_id)
        _enum("mode", self.mode, EaglegateMode)
        if not isinstance(self.plan_order, tuple):
            raise EaglegateContractError("plan_order must be a tuple")
        for value in self.plan_order:
            _ascii("plan_id", value)
        if len(set(self.plan_order)) != len(self.plan_order):
            raise EaglegateContractError(
                "plan order must be unique", fault=EaglegateFault.NONCANONICAL
            )
        if self.mode is not EaglegateMode.TARGET_ONLY and not self.plan_order:
            raise EaglegateContractError("non-target-only mode requires plans")
        _int("canary_basis_points", self.canary_basis_points, 0, 10_000)
        if self.mode in {EaglegateMode.TARGET_ONLY, EaglegateMode.SHADOW}:
            if self.canary_basis_points:
                raise EaglegateContractError("target-only/shadow traffic must be zero")
        elif self.mode is EaglegateMode.CANARY:
            if not 1 <= self.canary_basis_points <= 9_999:
                raise EaglegateContractError("canary traffic must be 1..9999")
        elif self.canary_basis_points != 10_000:
            raise EaglegateContractError("active mode requires 10000 basis points")
        if self.selection_contract_id != EAGLEGATE_SELECTION_CONTRACT_ID:
            raise EaglegateContractError(
                "unknown selection contract", fault=EaglegateFault.INCOMPATIBLE
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "policy_id": self.policy_id,
            "mode": self.mode.value,
            "plan_order": list(self.plan_order),
            "canary_basis_points": self.canary_basis_points,
            "selection_contract_id": self.selection_contract_id,
        }

    @property
    def policy_root(self) -> str:
        return _canonical_root("policy", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateQualificationSummary:
    suite_id: str
    identity_root: str
    plan_roots: tuple[str, ...]
    sampling_required: bool
    greedy_exact_cases: int
    sampled_distribution_cases: int
    kv_lifecycle_cases: int
    failure_containment_cases: int
    greedy_exact: bool
    sampled_distribution_preserved: bool
    kv_state_equivalent: bool
    failure_fallback_preserved: bool

    def __post_init__(self) -> None:
        _ascii("suite_id", self.suite_id)
        _root("identity_root", self.identity_root)
        if not isinstance(self.plan_roots, tuple) or not self.plan_roots:
            raise EaglegateContractError("plan_roots must be a non-empty tuple")
        for value in self.plan_roots:
            _root("plan_root", value)
        if len(set(self.plan_roots)) != len(self.plan_roots):
            raise EaglegateContractError(
                "plan roots must be unique", fault=EaglegateFault.NONCANONICAL
            )
        _bool("sampling_required", self.sampling_required)
        for name in (
            "greedy_exact_cases",
            "sampled_distribution_cases",
            "kv_lifecycle_cases",
            "failure_containment_cases",
        ):
            _int(name, getattr(self, name), 0, _U32)
        for name in (
            "greedy_exact",
            "sampled_distribution_preserved",
            "kv_state_equivalent",
            "failure_fallback_preserved",
        ):
            _bool(name, getattr(self, name))

    @property
    def qualified(self) -> bool:
        sampling_ok = not self.sampling_required or (
            self.sampled_distribution_preserved
            and self.sampled_distribution_cases > 0
        )
        return bool(
            self.greedy_exact
            and self.greedy_exact_cases > 0
            and sampling_ok
            and self.kv_state_equivalent
            and self.kv_lifecycle_cases > 0
            and self.failure_fallback_preserved
            and self.failure_containment_cases > 0
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "suite_id": self.suite_id,
            "identity_root": self.identity_root,
            "plan_roots": list(self.plan_roots),
            "sampling_required": self.sampling_required,
            "greedy_exact_cases": self.greedy_exact_cases,
            "sampled_distribution_cases": self.sampled_distribution_cases,
            "kv_lifecycle_cases": self.kv_lifecycle_cases,
            "failure_containment_cases": self.failure_containment_cases,
            "greedy_exact": self.greedy_exact,
            "sampled_distribution_preserved": self.sampled_distribution_preserved,
            "kv_state_equivalent": self.kv_state_equivalent,
            "failure_fallback_preserved": self.failure_fallback_preserved,
            "qualified": self.qualified,
        }

    @property
    def qualification_root(self) -> str:
        return _canonical_root("qualification", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateSpeculationEpoch:
    generation: int
    identity: EaglegateIdentity
    plans: tuple[EaglegatePlan, ...]
    policy: EaglegateAdmissionPolicy
    qualification_root: str = ""
    previous_epoch_root: str = ""

    def __post_init__(self) -> None:
        _int("generation", self.generation, 1)
        if not isinstance(self.identity, EaglegateIdentity):
            raise EaglegateContractError("identity has wrong type")
        if not isinstance(self.plans, tuple) or not self.plans:
            raise EaglegateContractError("plans must be a non-empty tuple")
        if any(not isinstance(plan, EaglegatePlan) for plan in self.plans):
            raise EaglegateContractError("plans contain invalid values")
        if not isinstance(self.policy, EaglegateAdmissionPolicy):
            raise EaglegateContractError("policy has wrong type")
        ids = tuple(plan.plan_id for plan in self.plans)
        roots = tuple(plan.plan_root for plan in self.plans)
        if len(set(ids)) != len(ids) or len(set(roots)) != len(roots):
            raise EaglegateContractError(
                "plans must have unique ids and roots",
                fault=EaglegateFault.NONCANONICAL,
            )
        if any(value not in ids for value in self.policy.plan_order):
            raise EaglegateContractError(
                "policy references an unknown plan",
                fault=EaglegateFault.IDENTITY_MISMATCH,
            )
        _root("qualification_root", self.qualification_root, empty=True)
        _root("previous_epoch_root", self.previous_epoch_root, empty=True)
        if self.policy.mode in {EaglegateMode.CANARY, EaglegateMode.ACTIVE}:
            if not self.qualification_root:
                raise EaglegateContractError(
                    "canary/active epochs require qualification",
                    fault=EaglegateFault.QUALIFICATION_REQUIRED,
                )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "authority_root": EAGLEGATE_AUTHORITY.authority_root,
            "generation": self.generation,
            "identity": self.identity.canonical_dict(),
            "identity_root": self.identity.identity_root,
            "plans": [plan.canonical_dict() for plan in self.plans],
            "plan_roots": [plan.plan_root for plan in self.plans],
            "policy": self.policy.canonical_dict(),
            "policy_root": self.policy.policy_root,
            "qualification_root": self.qualification_root,
            "previous_epoch_root": self.previous_epoch_root,
        }

    @property
    def epoch_root(self) -> str:
        return _canonical_root("epoch", self.canonical_dict())

    def plan_by_id(self, plan_id: str) -> EaglegatePlan:
        for plan in self.plans:
            if plan.plan_id == plan_id:
                return plan
        raise EaglegateContractError(
            "unknown plan", fault=EaglegateFault.IDENTITY_MISMATCH
        )


def validate_qualification_for_epoch(
    epoch: EaglegateSpeculationEpoch,
    qualification: EaglegateQualificationSummary,
) -> EaglegateQualificationSummary:
    if qualification.identity_root != epoch.identity.identity_root:
        raise EaglegateContractError(
            "qualification identity mismatch",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    if qualification.plan_roots != tuple(plan.plan_root for plan in epoch.plans):
        raise EaglegateContractError(
            "qualification plan mismatch", fault=EaglegateFault.IDENTITY_MISMATCH
        )
    required = any(
        EaglegateSamplerClass.LOSSLESS_SAMPLING in plan.sampler_classes
        for plan in epoch.plans
    )
    if qualification.sampling_required != required:
        raise EaglegateContractError(
            "qualification sampler mismatch",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    if not qualification.qualified:
        raise EaglegateContractError(
            "lossless qualification incomplete",
            fault=EaglegateFault.QUALIFICATION_REQUIRED,
        )
    if epoch.qualification_root and (
        epoch.qualification_root != qualification.qualification_root
    ):
        raise EaglegateContractError(
            "qualification root mismatch",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    return qualification


__all__ = [
    "EaglegateAdmissionPolicy",
    "EaglegatePlan",
    "EaglegateQualificationSummary",
    "EaglegateSpeculationEpoch",
    "validate_qualification_for_epoch",
]

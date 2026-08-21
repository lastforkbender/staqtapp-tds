"""Deterministic, non-committing Eaglegate admission decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import (
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
    EaglegateContractError,
    EaglegateDecisionKind,
    EaglegateFault,
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
from .plans import EaglegatePlan, EaglegateSpeculationEpoch


class _RequestRootCacheSlot:
    """Keep the derived root out of dataclass fields and canonical payloads."""

    __slots__ = ("_request_class_root_cache",)


@dataclass(frozen=True, slots=True)
class EaglegateRequestClass(_RequestRootCacheSlot):
    identity_root: str
    sampler_class: EaglegateSamplerClass
    batch_size: int
    concurrency: int
    context_tokens: int
    kv_pressure_ppm: int
    request_bucket: int
    deadline_class: str = "default"

    def __post_init__(self) -> None:
        _root("identity_root", self.identity_root)
        _enum("sampler_class", self.sampler_class, EaglegateSamplerClass)
        _int("batch_size", self.batch_size, 1, _U16)
        _int("concurrency", self.concurrency, 1, _U16)
        _int("context_tokens", self.context_tokens, 0, _U32)
        _int("kv_pressure_ppm", self.kv_pressure_ppm, 0, 1_000_000)
        _int("request_bucket", self.request_bucket, 0, 9_999)
        _ascii("deadline_class", self.deadline_class)
        object.__setattr__(
            self,
            "_request_class_root_cache",
            _canonical_root("request-class", self.canonical_dict()),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "identity_root": self.identity_root,
            "sampler_class": self.sampler_class.value,
            "batch_size": self.batch_size,
            "concurrency": self.concurrency,
            "context_tokens": self.context_tokens,
            "kv_pressure_ppm": self.kv_pressure_ppm,
            "request_bucket": self.request_bucket,
            "deadline_class": self.deadline_class,
        }

    @property
    def request_class_root(self) -> str:
        try:
            return self._request_class_root_cache
        except AttributeError:
            value = _canonical_root("request-class", self.canonical_dict())
            object.__setattr__(self, "_request_class_root_cache", value)
            return value


@dataclass(frozen=True, slots=True)
class EaglegateRuntimeHealth:
    epoch_root: str
    identity_root: str
    target_available: bool
    proposer_available: bool
    workspace_available_bytes: int
    faulted: bool = False

    def __post_init__(self) -> None:
        _root("epoch_root", self.epoch_root)
        _root("identity_root", self.identity_root)
        _bool("target_available", self.target_available)
        _bool("proposer_available", self.proposer_available)
        _int("workspace_available_bytes", self.workspace_available_bytes)
        _bool("faulted", self.faulted)


@dataclass(frozen=True, slots=True)
class EaglegateDecision:
    kind: EaglegateDecisionKind
    epoch_root: str
    request_class_root: str
    plan_id: str = ""
    reason: str = ""
    fault: EaglegateFault = EaglegateFault.NONE

    def __post_init__(self) -> None:
        _enum("kind", self.kind, EaglegateDecisionKind)
        _root("epoch_root", self.epoch_root)
        _root("request_class_root", self.request_class_root)
        _ascii("plan_id", self.plan_id, empty=True)
        _ascii("reason", self.reason, empty=True)
        _enum("fault", self.fault, EaglegateFault)
        if self.kind is EaglegateDecisionKind.ADMIT and not self.plan_id:
            raise EaglegateContractError("admit requires a plan")
        if self.kind is EaglegateDecisionKind.FAULT:
            if self.fault is EaglegateFault.NONE:
                raise EaglegateContractError("fault decision requires a fault")
        elif self.fault is not EaglegateFault.NONE:
            raise EaglegateContractError("non-fault decision cannot carry a fault")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "kind": self.kind.value,
            "epoch_root": self.epoch_root,
            "request_class_root": self.request_class_root,
            "plan_id": self.plan_id,
            "reason": self.reason,
            "fault": self.fault.value,
        }

    @property
    def decision_root(self) -> str:
        return _canonical_root("decision", self.canonical_dict())


def _rejection(
    plan: EaglegatePlan,
    request: EaglegateRequestClass,
    health: EaglegateRuntimeHealth,
) -> str | None:
    checks = (
        (request.sampler_class not in plan.sampler_classes, "unsupported_sampler"),
        (request.batch_size > plan.max_batch, "batch_limit"),
        (request.concurrency > plan.max_concurrency, "concurrency_limit"),
        (request.context_tokens > plan.max_context_tokens, "context_limit"),
        (request.kv_pressure_ppm > plan.max_kv_pressure_ppm, "kv_pressure_limit"),
        (
            health.workspace_available_bytes < plan.workspace_budget_bytes,
            "workspace_limit",
        ),
    )
    return next((reason for rejected, reason in checks if rejected), None)


def evaluate_admission(
    epoch: EaglegateSpeculationEpoch,
    request: EaglegateRequestClass,
    health: EaglegateRuntimeHealth,
) -> EaglegateDecision:
    """Select a prequalified plan without accepting tokens or committing state."""

    if not all(
        (
            isinstance(epoch, EaglegateSpeculationEpoch),
            isinstance(request, EaglegateRequestClass),
            isinstance(health, EaglegateRuntimeHealth),
        )
    ):
        raise EaglegateContractError("invalid admission value type")
    epoch_root = epoch.epoch_root
    request_root = request.request_class_root
    identity_root = epoch.identity_root
    if (
        request.identity_root != identity_root
        or health.identity_root != identity_root
        or health.epoch_root != epoch_root
    ):
        return EaglegateDecision(
            EaglegateDecisionKind.FAULT,
            epoch_root,
            request_root,
            reason="identity_mismatch",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    if not health.target_available:
        return EaglegateDecision(
            EaglegateDecisionKind.FAULT,
            epoch_root,
            request_root,
            reason="target_unavailable",
            fault=EaglegateFault.TARGET_UNAVAILABLE,
        )
    if epoch.policy.mode in {EaglegateMode.CANARY, EaglegateMode.ACTIVE}:
        return EaglegateDecision(
            EaglegateDecisionKind.FAULT,
            epoch_root,
            request_root,
            reason="policy_mode_not_authorized",
            fault=EaglegateFault.AUTHORITY_REJECTED,
        )
    if epoch.policy.mode is EaglegateMode.TARGET_ONLY:
        return EaglegateDecision(
            EaglegateDecisionKind.FALLBACK,
            epoch_root,
            request_root,
            reason="policy_target_only",
        )
    if health.faulted or not health.proposer_available:
        return EaglegateDecision(
            EaglegateDecisionKind.FALLBACK,
            epoch_root,
            request_root,
            reason="runtime_health_fault" if health.faulted else "proposer_unavailable",
        )

    selected: EaglegatePlan | None = None
    reason = "no_eligible_plan"
    for plan_id in epoch.policy.plan_order:
        candidate = epoch.plan_by_id(plan_id)
        rejected = _rejection(candidate, request, health)
        if rejected is None:
            selected = candidate
            break
        reason = rejected
    if selected is None:
        return EaglegateDecision(
            EaglegateDecisionKind.FALLBACK,
            epoch_root,
            request_root,
            reason=reason,
        )
    if epoch.policy.mode is EaglegateMode.SHADOW:
        return EaglegateDecision(
            EaglegateDecisionKind.ABSTAIN,
            epoch_root,
            request_root,
            plan_id=selected.plan_id,
            reason="shadow_only",
        )
    return EaglegateDecision(
        EaglegateDecisionKind.FAULT,
        epoch_root,
        request_root,
        reason="policy_mode_not_authorized",
        fault=EaglegateFault.AUTHORITY_REJECTED,
    )


__all__ = [
    "EaglegateDecision",
    "EaglegateRequestClass",
    "EaglegateRuntimeHealth",
    "evaluate_admission",
]

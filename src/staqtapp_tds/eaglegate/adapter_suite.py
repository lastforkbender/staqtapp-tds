"""Adversarial fake-runtime qualification suite for the Eaglegate adapter ABI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .adapter_contract import (
    AdapterFault,
    AdapterOperation,
    EAGLEGATE_ADAPTER_ABI_VERSION,
    EAGLEGATE_ADAPTER_CONTRACT_ID,
    EAGLEGATE_ADAPTER_SEQUENCE_ID,
    EAGLEGATE_TARGET_COMMIT_AUTHORITY,
    EaglegateAdapterIdentity,
    EaglegateAdapterLimits,
    EaglegateAdapterRequest,
)
from .adapter_runtime import (
    AdapterExecution,
    AdapterTraceBuilder,
    FakeEagleAdapter,
    FakeTargetRuntimeAdapter,
    run_adapter_conformance_reference,
)
from .contract import EAGLEGATE_CONTRACT_ID
from .exactness_common import (
    EAGLEGATE_EXACTNESS_CONTRACT_ID,
    EaglegateExactnessError,
    canonical_root,
    reference_epoch_root,
    require_ascii,
    require_root,
)
from .exactness_runtime import run_target_only
from .exactness_suite import run_reference_exactness_suite

EAGLEGATE_ADAPTER_SUITE_ID = "eaglegate-reference-adapter-conformance-v1"


@dataclass(frozen=True, slots=True)
class EaglegateAdapterConformanceCheck:
    name: str
    passed: bool
    target_outcome_root: str
    adapter_outcome_root: str
    trace_root: str
    detail: str

    def __post_init__(self) -> None:
        require_ascii("name", self.name)
        if not isinstance(self.passed, bool):
            raise EaglegateExactnessError("passed must be a boolean")
        require_root("target_outcome_root", self.target_outcome_root)
        require_root("adapter_outcome_root", self.adapter_outcome_root)
        require_root("trace_root", self.trace_root)
        require_ascii("detail", self.detail, allow_spaces=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "target_outcome_root": self.target_outcome_root,
            "adapter_outcome_root": self.adapter_outcome_root,
            "trace_root": self.trace_root,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EaglegateAdapterConformanceReport:
    suite_id: str
    adapter_identity_root: str
    checks: tuple[EaglegateAdapterConformanceCheck, ...]

    def __post_init__(self) -> None:
        require_ascii("suite_id", self.suite_id)
        require_root("adapter_identity_root", self.adapter_identity_root)
        if not self.checks or any(
            not isinstance(check, EaglegateAdapterConformanceCheck)
            for check in self.checks
        ):
            raise EaglegateExactnessError(
                "checks must contain adapter conformance checks"
            )

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "adapter_contract_id": EAGLEGATE_ADAPTER_CONTRACT_ID,
            "adapter_abi_version": EAGLEGATE_ADAPTER_ABI_VERSION,
            "sequence_id": EAGLEGATE_ADAPTER_SEQUENCE_ID,
            "target_commit_authority": EAGLEGATE_TARGET_COMMIT_AUTHORITY,
            "foundation_contract_id": EAGLEGATE_CONTRACT_ID,
            "exactness_contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            "suite_id": self.suite_id,
            "adapter_identity_root": self.adapter_identity_root,
            "passed": self.passed,
            "check_count": len(self.checks),
            "checks": [check.canonical_dict() for check in self.checks],
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
            "activation_authority": False,
            "adapter_execution_authority": False,
            "real_runtime_qualified": False,
        }

    @property
    def report_root(self) -> str:
        return canonical_root("adapter-conformance-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def _root(label: str) -> str:
    return canonical_root("adapter-fixture", {"label": label})


def reference_adapter_identity(label: str = "reference") -> EaglegateAdapterIdentity:
    exactness_root = (
        run_reference_exactness_suite().report_root
        if label == "reference"
        else _root(f"exactness-qualification-{label}")
    )
    return EaglegateAdapterIdentity(
        foundation_identity_root=_root(f"foundation-{label}"),
        exactness_qualification_root=exactness_root,
        adapter_build_root=_root(f"adapter-build-{label}"),
        target_verifier_root=_root(f"target-verifier-{label}"),
        rng_contract_root=_root(f"rng-{label}"),
        sampler_order_root=_root(f"sampler-order-{label}"),
        logits_processor_order_root=_root(f"logits-order-{label}"),
        termination_contract_root=_root(f"termination-{label}"),
        kv_allocator_root=_root(f"kv-allocator-{label}"),
        numerical_kernel_root=_root(f"kernel-{label}"),
        deadline_contract_root=_root(f"deadline-{label}"),
    )


def reference_adapter_limits(
    *,
    candidate_tokens: int = 4,
    deadline_ticks: int = 128,
) -> EaglegateAdapterLimits:
    return EaglegateAdapterLimits(
        max_candidate_tokens=candidate_tokens,
        max_outstanding_reservations=1,
        max_trace_events=128,
        deadline_budget_ticks=deadline_ticks,
    )


def reference_adapter_request(
    identity: EaglegateAdapterIdentity,
    limits: EaglegateAdapterLimits,
    *,
    epoch_root: str | None = None,
) -> EaglegateAdapterRequest:
    return EaglegateAdapterRequest(
        epoch_root=epoch_root or reference_epoch_root("adapter"),
        adapter_identity_root=identity.adapter_identity_root,
        plan_root=_root("plan"),
        request_class_root=_root("request-class"),
        limits_root=limits.limits_root,
    )


def _execute(
    target: tuple[int, ...],
    proposals,
    *,
    identity: EaglegateAdapterIdentity,
    runtime_identity: EaglegateAdapterIdentity | None = None,
    limits: EaglegateAdapterLimits | None = None,
    request_epoch: str | None = None,
    runtime_epoch: str | None = None,
    proposer_fail: int | None = None,
    reserve_fail: int | None = None,
    verify_fail: int | None = None,
    cancel_at: int | None = None,
) -> AdapterExecution:
    limits = limits or reference_adapter_limits()
    request = reference_adapter_request(identity, limits, epoch_root=request_epoch)
    actual_identity = runtime_identity or identity
    runtime = FakeTargetRuntimeAdapter(
        target,
        epoch_root=runtime_epoch or request.epoch_root,
        adapter_identity_root=actual_identity.adapter_identity_root,
        reserve_fail_at_position=reserve_fail,
        verify_fail_at_position=verify_fail,
    )
    proposer = FakeEagleAdapter(proposals, fail_at_position=proposer_fail)
    return run_adapter_conformance_reference(
        target,
        proposer,
        runtime,
        request,
        limits,
        cancel_at_position=cancel_at,
    )


def _paired_check(
    name: str,
    target_tokens: tuple[int, ...],
    execution: AdapterExecution,
    *,
    cancel_after: int | None = None,
    extra: bool = True,
    detail: str,
) -> EaglegateAdapterConformanceCheck:
    baseline = run_target_only(target_tokens, cancel_after=cancel_after)
    outcome = execution.outcome
    passed = all(
        (
            baseline.token_sequence_root == outcome.token_sequence_root,
            baseline.committed_state_root == outcome.committed_state_root,
            baseline.token_count == outcome.token_count,
            outcome.outstanding_reservations == 0,
            outcome.all_commits_by_target,
            extra,
        )
    )
    return EaglegateAdapterConformanceCheck(
        name,
        passed,
        baseline.outcome_root,
        outcome.outcome_root,
        execution.trace.trace_root,
        detail,
    )


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
    }
    if isinstance(value, Mapping):
        return all(
            key not in forbidden and _content_free(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(_content_free(item) for item in value)
    return True


def run_reference_adapter_conformance_suite() -> EaglegateAdapterConformanceReport:
    identity = reference_adapter_identity()
    target = (11, 22, 33, 44, 55, 66)
    checks: list[EaglegateAdapterConformanceCheck] = []

    full = _execute(target, {0: target[:4], 4: target[4:]}, identity=identity)
    checks.append(
        _paired_check(
            "full_accept_sequence",
            target,
            full,
            extra=[event.operation for event in full.trace.events]
            == [
                AdapterOperation.PIN,
                AdapterOperation.RESERVE,
                AdapterOperation.PROPOSE,
                AdapterOperation.VERIFY,
                AdapterOperation.COMMIT,
                AdapterOperation.RELEASE,
                AdapterOperation.RESERVE,
                AdapterOperation.PROPOSE,
                AdapterOperation.VERIFY,
                AdapterOperation.COMMIT,
                AdapterOperation.RELEASE,
                AdapterOperation.CLOSE,
            ],
            detail="target verifies and commits every accepted prefix",
        )
    )

    rejected = _execute(
        target,
        {0: (11, 999, 999, 999), 2: (33, 44, 55, 66)},
        identity=identity,
    )
    operations = [event.operation for event in rejected.trace.events]
    checks.append(
        _paired_check(
            "rewind_before_correction_commit",
            target,
            rejected,
            extra=(
                AdapterOperation.REWIND in operations
                and operations.index(AdapterOperation.REWIND)
                < operations.index(AdapterOperation.COMMIT)
            ),
            detail="rejected speculative state rewinds before target correction",
        )
    )

    proposer_failure = _execute(target, {}, identity=identity, proposer_fail=0)
    checks.append(
        _paired_check(
            "proposer_failure_cleanup",
            target,
            proposer_failure,
            extra=proposer_failure.outcome.fault is AdapterFault.PROPOSER_FAILURE,
            detail="proposer failure cancels releases and falls back target-only",
        )
    )

    epoch_mismatch = _execute(
        target,
        {0: target},
        identity=identity,
        request_epoch=reference_epoch_root("request"),
        runtime_epoch=reference_epoch_root("runtime"),
    )
    checks.append(
        _paired_check(
            "epoch_mismatch_preflight",
            target,
            epoch_mismatch,
            extra=(
                epoch_mismatch.outcome.fault is AdapterFault.EPOCH_MISMATCH
                and epoch_mismatch.outcome.proposer_calls == 0
            ),
            detail="mixed epoch denied before pin reserve or propose",
        )
    )

    runtime_identity = reference_adapter_identity("rng-mismatch")
    identity_mismatch = _execute(
        target,
        {0: target},
        identity=identity,
        runtime_identity=runtime_identity,
    )
    checks.append(
        _paired_check(
            "execution_identity_preflight",
            target,
            identity_mismatch,
            extra=(
                identity.rng_contract_root != runtime_identity.rng_contract_root
                and identity_mismatch.outcome.fault is AdapterFault.IDENTITY_MISMATCH
                and identity_mismatch.outcome.proposer_calls == 0
            ),
            detail="RNG sampler logits termination KV and kernel identity are pinned",
        )
    )

    deadline = _execute(
        target,
        {0: target},
        identity=identity,
        limits=reference_adapter_limits(deadline_ticks=2),
    )
    checks.append(
        _paired_check(
            "deadline_cleanup",
            target,
            deadline,
            extra=(
                deadline.outcome.fault is AdapterFault.DEADLINE_EXCEEDED
                and deadline.outcome.fallback_reason == "deadline_before_propose"
            ),
            detail="deadline exhaustion cannot leak an active reservation",
        )
    )

    exhausted = _execute(target, {0: target}, identity=identity, reserve_fail=0)
    checks.append(
        _paired_check(
            "reservation_exhaustion",
            target,
            exhausted,
            extra=(
                exhausted.outcome.fault is AdapterFault.RESOURCE_EXHAUSTED
                and exhausted.outcome.proposer_calls == 0
            ),
            detail="workspace exhaustion falls back before proposer execution",
        )
    )

    verifier_failure = _execute(
        target,
        {0: target},
        identity=identity,
        verify_fail=0,
    )
    checks.append(
        _paired_check(
            "verifier_failure_cleanup",
            target,
            verifier_failure,
            extra=verifier_failure.outcome.fault is AdapterFault.VERIFIER_FAILURE,
            detail="verifier failure cancels releases and preserves target-only output",
        )
    )

    cancelled = _execute(
        target,
        {0: (11, 22), 2: (33, 44, 55, 66)},
        identity=identity,
        cancel_at=2,
    )
    checks.append(
        _paired_check(
            "active_reservation_cancellation",
            target,
            cancelled,
            cancel_after=2,
            extra=(
                cancelled.outcome.fault is AdapterFault.REQUEST_CANCELLED
                and cancelled.outcome.cancelled
                and AdapterOperation.CANCEL
                in [event.operation for event in cancelled.trace.events]
            ),
            detail="request cancellation preserves the exact committed prefix",
        )
    )

    denied = False
    builder = AdapterTraceBuilder(_root("invalid-sequence-request"), 8)
    try:
        builder.record(
            AdapterOperation.COMMIT,
            position=0,
            authority="proposer",
        )
    except EaglegateExactnessError:
        denied = True
    partial = EaglegateAdapterConformanceReport(
        EAGLEGATE_ADAPTER_SUITE_ID,
        identity.adapter_identity_root,
        tuple(checks),
    )
    empty = run_target_only(())
    checks.append(
        EaglegateAdapterConformanceCheck(
            "authority_and_evidence_boundary",
            denied and _content_free(partial.canonical_dict()),
            empty.outcome_root,
            empty.outcome_root,
            full.trace.trace_root,
            "proposer commit and content-bearing evidence are rejected",
        )
    )

    return EaglegateAdapterConformanceReport(
        EAGLEGATE_ADAPTER_SUITE_ID,
        identity.adapter_identity_root,
        tuple(checks),
    )


__all__ = [
    "EAGLEGATE_ADAPTER_SUITE_ID",
    "EaglegateAdapterConformanceCheck",
    "EaglegateAdapterConformanceReport",
    "reference_adapter_identity",
    "reference_adapter_limits",
    "reference_adapter_request",
    "run_reference_adapter_conformance_suite",
]

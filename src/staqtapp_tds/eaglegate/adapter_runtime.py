"""Adversarial fake-runtime implementation of the Eaglegate adapter ABI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .adapter_contract import (
    ADAPTER_ALLOWED_TRANSITIONS,
    AdapterFault,
    AdapterOperation,
    AdapterState,
    AdapterTraceEvent,
    EAGLEGATE_ADAPTER_CONTRACT_ID,
    EAGLEGATE_TARGET_COMMIT_AUTHORITY,
    EaglegateAdapterLimits,
    EaglegateAdapterRequest,
    EaglegateAdapterTrace,
)
from .exactness_common import (
    EaglegateExactnessError,
    MAX_TOKENS,
    canonical_root,
    normalize_tokens,
    require_ascii,
    require_int,
    require_root,
    token_sequence_root,
)
from .exactness_runtime import ReferenceKVLedger


class EaglegateAdapterBoundaryError(RuntimeError):
    """Stable fake-runtime boundary failure eligible for target-only fallback."""


class EaglegateProposerFailure(EaglegateAdapterBoundaryError):
    pass


class EaglegateVerifierFailure(EaglegateAdapterBoundaryError):
    pass


class EaglegateResourceExhausted(EaglegateAdapterBoundaryError):
    pass


@dataclass
class AdapterTraceBuilder:
    request_root: str
    max_events: int

    def __post_init__(self) -> None:
        require_root("request_root", self.request_root)
        require_int("max_events", self.max_events, 1)
        self.state = AdapterState.NEW
        self.events: list[AdapterTraceEvent] = []

    def record(
        self,
        operation: AdapterOperation,
        *,
        position: int,
        token_count: int = 0,
        reservation_id: int = 0,
        authority: str = "",
        reason: str = "",
        fault: AdapterFault = AdapterFault.NONE,
    ) -> AdapterTraceEvent:
        if len(self.events) >= self.max_events:
            raise EaglegateExactnessError("adapter trace event bound exceeded")
        state_after = ADAPTER_ALLOWED_TRANSITIONS.get((self.state, operation))
        if state_after is None:
            raise EaglegateExactnessError(
                f"invalid adapter transition {self.state.value}->{operation.value}"
            )
        previous_root = self.events[-1].event_root if self.events else ""
        event = AdapterTraceEvent(
            sequence=len(self.events),
            operation=operation,
            state_before=self.state,
            state_after=state_after,
            position=position,
            token_count=token_count,
            reservation_id=reservation_id,
            authority=authority,
            reason=reason,
            fault=fault,
            previous_event_root=previous_root,
        )
        self.events.append(event)
        self.state = state_after
        return event

    def finish(self) -> EaglegateAdapterTrace:
        if self.state is not AdapterState.CLOSED:
            raise EaglegateExactnessError("adapter trace is not closed")
        return EaglegateAdapterTrace(self.request_root, tuple(self.events))


@dataclass
class DeterministicOperationClock:
    deadline_ticks: int

    def __post_init__(self) -> None:
        require_int("deadline_ticks", self.deadline_ticks, 1)
        self.ticks = 0

    def consume(self) -> bool:
        if self.ticks + 1 > self.deadline_ticks:
            return False
        self.ticks += 1
        return True


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    accepted_prefix: int
    rejected_tokens: int
    target_commit_tokens: tuple[int, ...]

    def __post_init__(self) -> None:
        require_int("accepted_prefix", self.accepted_prefix, 0, MAX_TOKENS)
        require_int("rejected_tokens", self.rejected_tokens, 0, MAX_TOKENS)
        normalize_tokens(self.target_commit_tokens)
        if not self.target_commit_tokens:
            raise EaglegateExactnessError("verification must produce target commit tokens")


class FakeTargetRuntimeAdapter:
    """Target-owned verifier, commit ledger, and reservation authority."""

    def __init__(
        self,
        target_tokens: Iterable[int],
        *,
        epoch_root: str,
        adapter_identity_root: str,
        reserve_fail_at_position: int | None = None,
        verify_fail_at_position: int | None = None,
    ) -> None:
        self.target_tokens = normalize_tokens(target_tokens)
        self.epoch_root = require_root("epoch_root", epoch_root)
        self.adapter_identity_root = require_root(
            "adapter_identity_root", adapter_identity_root
        )
        for name, value in (
            ("reserve_fail_at_position", reserve_fail_at_position),
            ("verify_fail_at_position", verify_fail_at_position),
        ):
            if value is not None:
                require_int(name, value, 0, len(self.target_tokens))
        self.reserve_fail_at_position = reserve_fail_at_position
        self.verify_fail_at_position = verify_fail_at_position
        self.ledger = ReferenceKVLedger()
        self.rewind_count = 0
        self.cancel_count = 0

    @property
    def position(self) -> int:
        return len(self.ledger.committed)

    def reserve(self, position: int, token_slots: int) -> int:
        if self.reserve_fail_at_position == position:
            raise EaglegateResourceExhausted("injected reservation exhaustion")
        return self.ledger.reserve(token_slots)

    def verify(
        self,
        position: int,
        proposal: Sequence[int],
    ) -> VerificationDecision:
        if self.verify_fail_at_position == position:
            raise EaglegateVerifierFailure("injected verifier failure")
        candidate = normalize_tokens(proposal)
        if not candidate:
            raise EaglegateExactnessError("verification proposal cannot be empty")
        if position != self.position:
            raise EaglegateExactnessError("verification position is not committed position")
        if position + len(candidate) > len(self.target_tokens):
            raise EaglegateExactnessError("proposal exceeds target extent")
        accepted = 0
        for offset, proposed_token in enumerate(candidate):
            if proposed_token != self.target_tokens[position + offset]:
                break
            accepted += 1
        rejected = len(candidate) - accepted
        commit_length = accepted + (1 if rejected else 0)
        return VerificationDecision(
            accepted,
            rejected,
            self.target_tokens[position : position + commit_length],
        )

    def rewind(self, reservation_id: int, rejected_tokens: int) -> None:
        if reservation_id <= 0:
            raise EaglegateExactnessError("rewind requires an active reservation")
        require_int("rejected_tokens", rejected_tokens, 1, MAX_TOKENS)
        self.rewind_count += rejected_tokens

    def commit(self, tokens: Iterable[int]) -> None:
        self.ledger.commit(tokens, authority=EAGLEGATE_TARGET_COMMIT_AUTHORITY)

    def cancel(self, reservation_id: int) -> None:
        if reservation_id <= 0:
            raise EaglegateExactnessError("cancel requires an active reservation")
        self.cancel_count += 1

    def release(self, reservation_id: int) -> None:
        self.ledger.release(reservation_id)

    def finish_target_only(self, boundary: int) -> None:
        require_int("boundary", boundary, self.position, len(self.target_tokens))
        self.commit(self.target_tokens[self.position : boundary])


class FakeEagleAdapter:
    """Proposal-only fake adapter; no target verification or commit surface."""

    def __init__(
        self,
        proposals: Mapping[int, Sequence[int]],
        *,
        fail_at_position: int | None = None,
    ) -> None:
        if not isinstance(proposals, Mapping):
            raise EaglegateExactnessError("proposals must be a mapping")
        self._proposals = {
            require_int("proposal position", position, 0, MAX_TOKENS):
            normalize_tokens(tokens)
            for position, tokens in proposals.items()
        }
        if fail_at_position is not None:
            require_int("fail_at_position", fail_at_position, 0, MAX_TOKENS)
        self.fail_at_position = fail_at_position
        self.call_count = 0

    def propose(
        self,
        position: int,
        reservation_id: int,
        max_candidate_tokens: int,
    ) -> tuple[int, ...]:
        require_int("position", position, 0, MAX_TOKENS)
        require_int("reservation_id", reservation_id, 1)
        require_int("max_candidate_tokens", max_candidate_tokens, 1, MAX_TOKENS)
        self.call_count += 1
        if self.fail_at_position == position:
            raise EaglegateProposerFailure("injected proposer failure")
        return self._proposals.get(position, ())[:max_candidate_tokens]


@dataclass(frozen=True, slots=True)
class AdapterConformanceOutcome:
    request_root: str
    path: str
    fallback_reason: str
    fault: AdapterFault
    token_count: int
    token_sequence_root: str
    committed_state_root: str
    trace_root: str
    trace_event_count: int
    outstanding_reservations: int
    proposer_calls: int
    operation_ticks: int
    all_commits_by_target: bool
    cancelled: bool
    activation_authority: bool = False

    def __post_init__(self) -> None:
        require_root("request_root", self.request_root)
        require_ascii("path", self.path)
        require_ascii("fallback_reason", self.fallback_reason, allow_empty=True)
        if not isinstance(self.fault, AdapterFault):
            raise EaglegateExactnessError("fault must be AdapterFault")
        require_int("token_count", self.token_count, 0, MAX_TOKENS)
        require_root("token_sequence_root", self.token_sequence_root)
        require_root("committed_state_root", self.committed_state_root)
        require_root("trace_root", self.trace_root)
        require_int("trace_event_count", self.trace_event_count, 1)
        require_int("outstanding_reservations", self.outstanding_reservations)
        require_int("proposer_calls", self.proposer_calls)
        require_int("operation_ticks", self.operation_ticks)
        if not isinstance(self.all_commits_by_target, bool):
            raise EaglegateExactnessError("all_commits_by_target must be boolean")
        if not isinstance(self.cancelled, bool):
            raise EaglegateExactnessError("cancelled must be boolean")
        if self.activation_authority is not False:
            raise EaglegateExactnessError("adapter conformance has no activation authority")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "adapter_contract_id": EAGLEGATE_ADAPTER_CONTRACT_ID,
            "request_root": self.request_root,
            "path": self.path,
            "fallback_reason": self.fallback_reason,
            "fault": self.fault.value,
            "token_count": self.token_count,
            "token_sequence_root": self.token_sequence_root,
            "committed_state_root": self.committed_state_root,
            "trace_root": self.trace_root,
            "trace_event_count": self.trace_event_count,
            "outstanding_reservations": self.outstanding_reservations,
            "proposer_calls": self.proposer_calls,
            "operation_ticks": self.operation_ticks,
            "all_commits_by_target": self.all_commits_by_target,
            "cancelled": self.cancelled,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
            "activation_authority": False,
        }

    @property
    def outcome_root(self) -> str:
        return canonical_root("adapter-outcome", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class AdapterExecution:
    outcome: AdapterConformanceOutcome
    trace: EaglegateAdapterTrace


@dataclass
class DeterministicOperationClock:
    deadline_ticks: int

    def __post_init__(self) -> None:
        require_int("deadline_ticks", self.deadline_ticks, 1)
        self.ticks = 0

    def consume(self) -> bool:
        if self.ticks + 1 > self.deadline_ticks:
            return False
        self.ticks += 1
        return True


def _consume_or_fallback(clock: DeterministicOperationClock) -> bool:
    return clock.consume()


def run_adapter_conformance_reference(
    target_tokens: Iterable[int],
    proposer: FakeEagleAdapter,
    runtime: FakeTargetRuntimeAdapter,
    request: EaglegateAdapterRequest,
    limits: EaglegateAdapterLimits,
    *,
    cancel_at_position: int | None = None,
) -> AdapterExecution:
    """Execute the fake ABI while preserving target-only equivalence."""

    target = normalize_tokens(target_tokens)
    if target != runtime.target_tokens:
        raise EaglegateExactnessError("target input differs from runtime target")
    if not isinstance(proposer, FakeEagleAdapter):
        raise EaglegateExactnessError("proposer must be FakeEagleAdapter")
    if not isinstance(runtime, FakeTargetRuntimeAdapter):
        raise EaglegateExactnessError("runtime must be FakeTargetRuntimeAdapter")
    if not isinstance(request, EaglegateAdapterRequest):
        raise EaglegateExactnessError("request must be EaglegateAdapterRequest")
    if not isinstance(limits, EaglegateAdapterLimits):
        raise EaglegateExactnessError("limits must be EaglegateAdapterLimits")
    if request.limits_root != limits.limits_root:
        raise EaglegateExactnessError("request limits root mismatch")
    if cancel_at_position is not None:
        require_int("cancel_at_position", cancel_at_position, 0, len(target))
    target_boundary = len(target) if cancel_at_position is None else cancel_at_position
    trace = AdapterTraceBuilder(request.request_root, limits.max_trace_events)
    clock = DeterministicOperationClock(limits.deadline_budget_ticks)
    fallback_reason = ""
    fault = AdapterFault.NONE
    cancelled = False

    def finish_fallback(
        reason: str,
        fallback_fault: AdapterFault,
        *,
        reservation_id: int = 0,
        continue_target_only: bool = True,
    ) -> None:
        nonlocal fallback_reason, fault, cancelled
        fallback_reason = reason
        fault = fallback_fault
        if reservation_id:
            runtime.cancel(reservation_id)
            trace.record(
                AdapterOperation.CANCEL,
                position=runtime.position,
                reservation_id=reservation_id,
                reason=reason,
            )
            runtime.release(reservation_id)
            trace.record(
                AdapterOperation.RELEASE,
                position=runtime.position,
                reservation_id=reservation_id,
                reason="safety_release",
            )
        trace.record(
            AdapterOperation.FALLBACK,
            position=runtime.position,
            reason=reason,
            fault=fallback_fault,
        )
        if continue_target_only:
            runtime.finish_target_only(target_boundary)
        else:
            cancelled = True
        trace.record(
            AdapterOperation.CLOSE,
            position=runtime.position,
            reason="target_only_complete" if continue_target_only else "cancelled",
        )

    if request.epoch_root != runtime.epoch_root:
        finish_fallback("epoch_mismatch", AdapterFault.EPOCH_MISMATCH)
    elif request.adapter_identity_root != runtime.adapter_identity_root:
        finish_fallback("identity_mismatch", AdapterFault.IDENTITY_MISMATCH)
    elif not _consume_or_fallback(clock):
        finish_fallback("deadline_before_pin", AdapterFault.DEADLINE_EXCEEDED)
    else:
        trace.record(AdapterOperation.PIN, position=0, reason="identity_pinned")

    while trace.state not in (AdapterState.CLOSED, AdapterState.FALLBACK):
        position = runtime.position
        if position >= len(target):
            trace.record(AdapterOperation.CLOSE, position=position, reason="complete")
            break
        if not _consume_or_fallback(clock):
            finish_fallback("deadline_before_reserve", AdapterFault.DEADLINE_EXCEEDED)
            break
        candidate_extent = len(target) - position
        if cancel_at_position is not None and position < cancel_at_position:
            candidate_extent = min(candidate_extent, cancel_at_position - position)
        candidate_slots = min(limits.max_candidate_tokens, candidate_extent)
        try:
            reservation_id = runtime.reserve(position, candidate_slots)
        except EaglegateResourceExhausted:
            finish_fallback("resource_exhausted", AdapterFault.RESOURCE_EXHAUSTED)
            break
        trace.record(
            AdapterOperation.RESERVE,
            position=position,
            token_count=candidate_slots,
            reservation_id=reservation_id,
        )
        if not _consume_or_fallback(clock):
            finish_fallback(
                "deadline_before_propose",
                AdapterFault.DEADLINE_EXCEEDED,
                reservation_id=reservation_id,
            )
            break
        try:
            proposal = proposer.propose(position, reservation_id, candidate_slots)
        except EaglegateProposerFailure:
            finish_fallback(
                "proposer_failure",
                AdapterFault.PROPOSER_FAILURE,
                reservation_id=reservation_id,
            )
            break
        if not proposal:
            finish_fallback(
                "empty_proposal",
                AdapterFault.PROPOSER_FAILURE,
                reservation_id=reservation_id,
            )
            break
        trace.record(
            AdapterOperation.PROPOSE,
            position=position,
            token_count=len(proposal),
            reservation_id=reservation_id,
        )
        if cancel_at_position is not None and position >= cancel_at_position:
            finish_fallback(
                "request_cancelled",
                AdapterFault.REQUEST_CANCELLED,
                reservation_id=reservation_id,
                continue_target_only=False,
            )
            break
        if not _consume_or_fallback(clock):
            finish_fallback(
                "deadline_before_verify",
                AdapterFault.DEADLINE_EXCEEDED,
                reservation_id=reservation_id,
            )
            break
        try:
            decision = runtime.verify(position, proposal)
        except EaglegateVerifierFailure:
            finish_fallback(
                "verifier_failure",
                AdapterFault.VERIFIER_FAILURE,
                reservation_id=reservation_id,
            )
            break
        trace.record(
            AdapterOperation.VERIFY,
            position=position,
            token_count=decision.accepted_prefix,
            reservation_id=reservation_id,
        )
        if decision.rejected_tokens:
            if not _consume_or_fallback(clock):
                finish_fallback(
                    "deadline_before_rewind",
                    AdapterFault.DEADLINE_EXCEEDED,
                    reservation_id=reservation_id,
                )
                break
            runtime.rewind(reservation_id, decision.rejected_tokens)
            trace.record(
                AdapterOperation.REWIND,
                position=position,
                token_count=decision.rejected_tokens,
                reservation_id=reservation_id,
            )
        if not _consume_or_fallback(clock):
            finish_fallback(
                "deadline_before_commit",
                AdapterFault.DEADLINE_EXCEEDED,
                reservation_id=reservation_id,
            )
            break
        runtime.commit(decision.target_commit_tokens)
        trace.record(
            AdapterOperation.COMMIT,
            position=position,
            token_count=len(decision.target_commit_tokens),
            reservation_id=reservation_id,
            authority=EAGLEGATE_TARGET_COMMIT_AUTHORITY,
        )
        runtime.release(reservation_id)
        trace.record(
            AdapterOperation.RELEASE,
            position=runtime.position,
            reservation_id=reservation_id,
        )

    completed_trace = trace.finish()
    committed = runtime.ledger.committed
    outcome = AdapterConformanceOutcome(
        request_root=request.request_root,
        path=(
            "adapter_conformance"
            if fault is AdapterFault.NONE
            else "target_only_fallback"
        ),
        fallback_reason=fallback_reason,
        fault=fault,
        token_count=len(committed),
        token_sequence_root=token_sequence_root(committed),
        committed_state_root=runtime.ledger.state_root,
        trace_root=completed_trace.trace_root,
        trace_event_count=len(completed_trace.events),
        outstanding_reservations=runtime.ledger.outstanding_reservations,
        proposer_calls=proposer.call_count,
        operation_ticks=clock.ticks,
        all_commits_by_target=all(
            authority == EAGLEGATE_TARGET_COMMIT_AUTHORITY
            for authority in runtime.ledger.commit_authorities
        ),
        cancelled=cancelled,
    )
    return AdapterExecution(outcome, completed_trace)


__all__ = [
    "AdapterConformanceOutcome",
    "AdapterExecution",
    "AdapterTraceBuilder",
    "DeterministicOperationClock",
    "EaglegateAdapterBoundaryError",
    "EaglegateProposerFailure",
    "EaglegateResourceExhausted",
    "EaglegateVerifierFailure",
    "FakeEagleAdapter",
    "FakeTargetRuntimeAdapter",
    "VerificationDecision",
    "run_adapter_conformance_reference",
]

"""Scripted target/proposer and committed-state oracle for Eaglegate."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .exactness_common import (
    EAGLEGATE_EXACTNESS_CONTRACT_ID,
    EaglegateExactnessError,
    MAX_EVENTS,
    MAX_TOKENS,
    canonical_root,
    committed_state_root,
    normalize_tokens,
    require_ascii,
    require_int,
    require_root,
    token_sequence_root,
)


@dataclass
class BoundedEvidenceRing:
    """Loss-tolerant observer ring with a content-free event schema."""

    capacity: int

    def __post_init__(self) -> None:
        require_int("capacity", self.capacity, 0, MAX_EVENTS)
        self._events: list[dict[str, Any]] = []
        self.published = 0
        self.dropped = 0

    def publish(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping) or set(event) != {"kind", "count"}:
            raise EaglegateExactnessError(
                "observer events must contain only kind and count"
            )
        normalized = {
            "kind": require_ascii("event kind", event["kind"]),
            "count": require_int("event count", event["count"], 0, MAX_TOKENS),
        }
        self.published += 1
        if len(self._events) >= self.capacity:
            self.dropped += 1
            return
        self._events.append(normalized)

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(event) for event in self._events)


@dataclass
class ReferenceKVLedger:
    """Committed-state authority and speculative reservation ledger."""

    def __post_init__(self) -> None:
        self._committed: list[int] = []
        self._reservations: dict[int, int] = {}
        self._next_reservation = 1
        self.commit_authorities: list[str] = []

    @property
    def committed(self) -> tuple[int, ...]:
        return tuple(self._committed)

    @property
    def outstanding_reservations(self) -> int:
        return len(self._reservations)

    @property
    def state_root(self) -> str:
        return committed_state_root(self._committed)

    def reserve(self, token_slots: int) -> int:
        require_int("token_slots", token_slots, 1, MAX_TOKENS)
        reservation_id = self._next_reservation
        self._next_reservation += 1
        self._reservations[reservation_id] = token_slots
        return reservation_id

    def release(self, reservation_id: int) -> None:
        if reservation_id not in self._reservations:
            raise EaglegateExactnessError("unknown speculative reservation")
        del self._reservations[reservation_id]

    def commit(self, tokens: Iterable[int], *, authority: str) -> None:
        normalized = normalize_tokens(tokens)
        if authority != "target-runtime":
            raise EaglegateExactnessError("only target-runtime may commit state")
        if len(self._committed) + len(normalized) > MAX_TOKENS:
            raise EaglegateExactnessError("committed token count exceeds bound")
        self._committed.extend(normalized)
        self.commit_authorities.extend(authority for _ in normalized)


class ScriptedProposer:
    """Deterministic EAGLE stand-in with no verification or commit authority."""

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

    def propose(self, position: int) -> tuple[int, ...]:
        require_int("position", position, 0, MAX_TOKENS)
        self.call_count += 1
        if self.fail_at_position == position:
            raise RuntimeError("injected proposer failure")
        return self._proposals.get(position, ())


@dataclass(frozen=True, slots=True)
class DecodeOutcome:
    path: str
    fallback_reason: str
    token_count: int
    token_sequence_root: str
    committed_state_root: str
    outstanding_reservations: int
    proposer_calls: int
    observer_events_published: int
    observer_events_dropped: int
    target_only_continuation: bool
    cancelled: bool
    all_commits_by_target: bool

    def __post_init__(self) -> None:
        require_ascii("path", self.path)
        require_ascii("fallback_reason", self.fallback_reason, allow_empty=True)
        require_int("token_count", self.token_count, 0, MAX_TOKENS)
        require_root("token_sequence_root", self.token_sequence_root)
        require_root("committed_state_root", self.committed_state_root)
        require_int("outstanding_reservations", self.outstanding_reservations)
        require_int("proposer_calls", self.proposer_calls)
        require_int("observer_events_published", self.observer_events_published)
        require_int("observer_events_dropped", self.observer_events_dropped)
        for name in (
            "target_only_continuation",
            "cancelled",
            "all_commits_by_target",
        ):
            if not isinstance(getattr(self, name), bool):
                raise EaglegateExactnessError(f"{name} must be a boolean")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            "path": self.path,
            "fallback_reason": self.fallback_reason,
            "token_count": self.token_count,
            "token_sequence_root": self.token_sequence_root,
            "committed_state_root": self.committed_state_root,
            "outstanding_reservations": self.outstanding_reservations,
            "proposer_calls": self.proposer_calls,
            "observer_events_published": self.observer_events_published,
            "observer_events_dropped": self.observer_events_dropped,
            "target_only_continuation": self.target_only_continuation,
            "cancelled": self.cancelled,
            "all_commits_by_target": self.all_commits_by_target,
        }

    @property
    def outcome_root(self) -> str:
        return canonical_root("decode-outcome", self.canonical_dict())


def _finish(
    *,
    path: str,
    fallback_reason: str,
    ledger: ReferenceKVLedger,
    proposer_calls: int,
    ring: BoundedEvidenceRing,
    target_only_continuation: bool,
    cancelled: bool,
) -> DecodeOutcome:
    committed = ledger.committed
    return DecodeOutcome(
        path=path,
        fallback_reason=fallback_reason,
        token_count=len(committed),
        token_sequence_root=token_sequence_root(committed),
        committed_state_root=ledger.state_root,
        outstanding_reservations=ledger.outstanding_reservations,
        proposer_calls=proposer_calls,
        observer_events_published=ring.published,
        observer_events_dropped=ring.dropped,
        target_only_continuation=target_only_continuation,
        cancelled=cancelled,
        all_commits_by_target=all(
            authority == "target-runtime" for authority in ledger.commit_authorities
        ),
    )


def run_target_only(
    target_tokens: Iterable[int],
    *,
    cancel_after: int | None = None,
    ring_capacity: int = 64,
) -> DecodeOutcome:
    target = normalize_tokens(target_tokens)
    if cancel_after is not None:
        require_int("cancel_after", cancel_after, 0, len(target))
    boundary = len(target) if cancel_after is None else cancel_after
    ring = BoundedEvidenceRing(ring_capacity)
    ledger = ReferenceKVLedger()
    for token in target[:boundary]:
        ledger.commit((token,), authority="target-runtime")
        ring.publish({"kind": "target_commit", "count": 1})
    return _finish(
        path="target_only",
        fallback_reason="",
        ledger=ledger,
        proposer_calls=0,
        ring=ring,
        target_only_continuation=False,
        cancelled=cancel_after is not None and cancel_after < len(target),
    )


def run_speculative_reference(
    target_tokens: Iterable[int],
    proposer: ScriptedProposer,
    *,
    pinned_epoch_root: str,
    runtime_epoch_root: str,
    cancel_after: int | None = None,
    ring_capacity: int = 64,
) -> DecodeOutcome:
    """Verify scripted proposals while the target exclusively commits state."""

    target = normalize_tokens(target_tokens)
    if not isinstance(proposer, ScriptedProposer):
        raise EaglegateExactnessError("proposer must be ScriptedProposer")
    require_root("pinned_epoch_root", pinned_epoch_root)
    require_root("runtime_epoch_root", runtime_epoch_root)
    if cancel_after is not None:
        require_int("cancel_after", cancel_after, 0, len(target))
    boundary = len(target) if cancel_after is None else cancel_after
    ring = BoundedEvidenceRing(ring_capacity)
    ledger = ReferenceKVLedger()
    position = 0
    fallback_reason = ""
    target_only = pinned_epoch_root != runtime_epoch_root
    if target_only:
        fallback_reason = "epoch_mismatch"

    while position < boundary:
        if target_only:
            ledger.commit((target[position],), authority="target-runtime")
            ring.publish({"kind": "target_fallback_commit", "count": 1})
            position += 1
            continue

        try:
            candidate = proposer.propose(position)
        except Exception:
            fallback_reason = "proposer_failure"
            target_only = True
            ring.publish({"kind": "proposer_failure", "count": 1})
            continue
        if not candidate:
            fallback_reason = "empty_proposal"
            target_only = True
            continue

        candidate = candidate[: boundary - position]
        reservation = ledger.reserve(len(candidate))
        try:
            ring.publish({"kind": "proposal", "count": len(candidate)})
            matched = 0
            for offset, proposed_token in enumerate(candidate):
                if proposed_token != target[position + offset]:
                    break
                matched += 1
            if matched:
                ledger.commit(
                    target[position : position + matched],
                    authority="target-runtime",
                )
                ring.publish({"kind": "verified_prefix", "count": matched})
                position += matched
            if position < boundary and matched < len(candidate):
                ledger.commit((target[position],), authority="target-runtime")
                ring.publish({"kind": "target_correction", "count": 1})
                position += 1
        finally:
            ledger.release(reservation)
            ring.publish({"kind": "reservation_release", "count": 1})

    return _finish(
        path="speculative_reference",
        fallback_reason=fallback_reason,
        ledger=ledger,
        proposer_calls=proposer.call_count,
        ring=ring,
        target_only_continuation=target_only,
        cancelled=cancel_after is not None and cancel_after < len(target),
    )


__all__ = [
    "BoundedEvidenceRing",
    "DecodeOutcome",
    "ReferenceKVLedger",
    "ScriptedProposer",
    "run_speculative_reference",
    "run_target_only",
]

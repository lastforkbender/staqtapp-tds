"""Immutable runtime-adapter identity, trace, and authority contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .contract import EAGLEGATE_CONTRACT_ID, EAGLEGATE_FORMAT_VERSION
from .exactness_common import (
    EAGLEGATE_EXACTNESS_CONTRACT_ID,
    EaglegateExactnessError,
    MAX_EVENTS,
    MAX_TOKENS,
    UINT32_MAX,
    UINT63_MAX,
    canonical_root,
    require_ascii,
    require_int,
    require_root,
)

EAGLEGATE_ADAPTER_CONTRACT_ID = "tds-eaglegate-adapter-conformance-v1"
EAGLEGATE_ADAPTER_ABI_VERSION = 1
EAGLEGATE_ADAPTER_SEQUENCE_ID = (
    "pin-reserve-propose-verify-rewind-commit-cancel-release-v1"
)
EAGLEGATE_TARGET_COMMIT_AUTHORITY = "target-runtime"


class AdapterOperation(str, Enum):
    PIN = "pin"
    RESERVE = "reserve"
    PROPOSE = "propose"
    VERIFY = "verify"
    REWIND = "rewind"
    COMMIT = "commit"
    CANCEL = "cancel"
    RELEASE = "release"
    FALLBACK = "fallback"
    CLOSE = "close"


class AdapterState(str, Enum):
    NEW = "new"
    PINNED = "pinned"
    RESERVED = "reserved"
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REWOUND = "rewound"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    RELEASED = "released"
    FALLBACK = "fallback"
    CLOSED = "closed"


class AdapterFault(str, Enum):
    NONE = "none"
    IDENTITY_MISMATCH = "identity_mismatch"
    EPOCH_MISMATCH = "epoch_mismatch"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    PROPOSER_FAILURE = "proposer_failure"
    VERIFIER_FAILURE = "verifier_failure"
    INVALID_SEQUENCE = "invalid_sequence"
    REQUEST_CANCELLED = "request_cancelled"
    AUTHORITY_REJECTED = "authority_rejected"


ADAPTER_ALLOWED_TRANSITIONS: dict[
    tuple[AdapterState, AdapterOperation], AdapterState
] = {
    (AdapterState.NEW, AdapterOperation.PIN): AdapterState.PINNED,
    (AdapterState.NEW, AdapterOperation.FALLBACK): AdapterState.FALLBACK,
    (AdapterState.PINNED, AdapterOperation.RESERVE): AdapterState.RESERVED,
    (AdapterState.PINNED, AdapterOperation.FALLBACK): AdapterState.FALLBACK,
    (AdapterState.PINNED, AdapterOperation.CLOSE): AdapterState.CLOSED,
    (AdapterState.RESERVED, AdapterOperation.PROPOSE): AdapterState.PROPOSED,
    (AdapterState.RESERVED, AdapterOperation.CANCEL): AdapterState.CANCELLED,
    (AdapterState.PROPOSED, AdapterOperation.VERIFY): AdapterState.VERIFIED,
    (AdapterState.PROPOSED, AdapterOperation.CANCEL): AdapterState.CANCELLED,
    (AdapterState.VERIFIED, AdapterOperation.REWIND): AdapterState.REWOUND,
    (AdapterState.VERIFIED, AdapterOperation.COMMIT): AdapterState.COMMITTED,
    (AdapterState.VERIFIED, AdapterOperation.CANCEL): AdapterState.CANCELLED,
    (AdapterState.REWOUND, AdapterOperation.COMMIT): AdapterState.COMMITTED,
    (AdapterState.REWOUND, AdapterOperation.CANCEL): AdapterState.CANCELLED,
    (AdapterState.COMMITTED, AdapterOperation.RELEASE): AdapterState.RELEASED,
    (AdapterState.CANCELLED, AdapterOperation.RELEASE): AdapterState.RELEASED,
    (AdapterState.RELEASED, AdapterOperation.RESERVE): AdapterState.RESERVED,
    (AdapterState.RELEASED, AdapterOperation.FALLBACK): AdapterState.FALLBACK,
    (AdapterState.RELEASED, AdapterOperation.CLOSE): AdapterState.CLOSED,
    (AdapterState.FALLBACK, AdapterOperation.CLOSE): AdapterState.CLOSED,
}


@dataclass(frozen=True, slots=True)
class EaglegateAdapterIdentity:
    foundation_identity_root: str
    exactness_qualification_root: str
    adapter_build_root: str
    target_verifier_root: str
    rng_contract_root: str
    sampler_order_root: str
    logits_processor_order_root: str
    termination_contract_root: str
    kv_allocator_root: str
    numerical_kernel_root: str
    deadline_contract_root: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            require_root(name, value)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "adapter_contract_id": EAGLEGATE_ADAPTER_CONTRACT_ID,
            "adapter_abi_version": EAGLEGATE_ADAPTER_ABI_VERSION,
            "foundation_contract_id": EAGLEGATE_CONTRACT_ID,
            "foundation_format_version": EAGLEGATE_FORMAT_VERSION,
            "exactness_contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def adapter_identity_root(self) -> str:
        return canonical_root("adapter-identity", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateAdapterLimits:
    max_candidate_tokens: int
    max_outstanding_reservations: int
    max_trace_events: int
    deadline_budget_ticks: int

    def __post_init__(self) -> None:
        require_int("max_candidate_tokens", self.max_candidate_tokens, 1, MAX_TOKENS)
        require_int(
            "max_outstanding_reservations",
            self.max_outstanding_reservations,
            1,
            UINT32_MAX,
        )
        if self.max_outstanding_reservations != 1:
            raise EaglegateExactnessError(
                "adapter ABI v1 permits exactly one outstanding reservation"
            )
        require_int("max_trace_events", self.max_trace_events, 1, MAX_EVENTS)
        require_int(
            "deadline_budget_ticks", self.deadline_budget_ticks, 1, UINT63_MAX
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "adapter_contract_id": EAGLEGATE_ADAPTER_CONTRACT_ID,
            "adapter_abi_version": EAGLEGATE_ADAPTER_ABI_VERSION,
            **asdict(self),
        }

    @property
    def limits_root(self) -> str:
        return canonical_root("adapter-limits", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateAdapterRequest:
    epoch_root: str
    adapter_identity_root: str
    plan_root: str
    request_class_root: str
    limits_root: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            require_root(name, value)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "adapter_contract_id": EAGLEGATE_ADAPTER_CONTRACT_ID,
            "adapter_abi_version": EAGLEGATE_ADAPTER_ABI_VERSION,
            "sequence_id": EAGLEGATE_ADAPTER_SEQUENCE_ID,
            **asdict(self),
        }

    @property
    def request_root(self) -> str:
        return canonical_root("adapter-request", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class AdapterTraceEvent:
    sequence: int
    operation: AdapterOperation
    state_before: AdapterState
    state_after: AdapterState
    position: int
    token_count: int
    reservation_id: int
    authority: str = ""
    reason: str = ""
    fault: AdapterFault = AdapterFault.NONE
    previous_event_root: str = ""

    def __post_init__(self) -> None:
        require_int("sequence", self.sequence, 0, UINT32_MAX)
        if not isinstance(self.operation, AdapterOperation):
            raise EaglegateExactnessError("operation must be AdapterOperation")
        if not isinstance(self.state_before, AdapterState):
            raise EaglegateExactnessError("state_before must be AdapterState")
        if not isinstance(self.state_after, AdapterState):
            raise EaglegateExactnessError("state_after must be AdapterState")
        require_int("position", self.position, 0, MAX_TOKENS)
        require_int("token_count", self.token_count, 0, MAX_TOKENS)
        require_int("reservation_id", self.reservation_id, 0, UINT32_MAX)
        require_ascii("authority", self.authority, allow_empty=True)
        require_ascii("reason", self.reason, allow_empty=True)
        if not isinstance(self.fault, AdapterFault):
            raise EaglegateExactnessError("fault must be AdapterFault")
        if self.previous_event_root:
            require_root("previous_event_root", self.previous_event_root)
        if self.operation is AdapterOperation.COMMIT:
            if self.authority != EAGLEGATE_TARGET_COMMIT_AUTHORITY:
                raise EaglegateExactnessError(
                    "adapter commit must be owned by target-runtime"
                )
        elif self.authority:
            raise EaglegateExactnessError(
                "only commit events may carry an authority"
            )
        if self.operation is AdapterOperation.FALLBACK:
            if self.fault is AdapterFault.NONE:
                raise EaglegateExactnessError("fallback requires a stable fault")
        elif self.fault is not AdapterFault.NONE:
            raise EaglegateExactnessError(
                "only fallback events may carry a fault"
            )
        reservation_operations = {
            AdapterOperation.RESERVE,
            AdapterOperation.PROPOSE,
            AdapterOperation.VERIFY,
            AdapterOperation.REWIND,
            AdapterOperation.COMMIT,
            AdapterOperation.CANCEL,
            AdapterOperation.RELEASE,
        }
        if self.operation in reservation_operations:
            if self.reservation_id == 0:
                raise EaglegateExactnessError(
                    "reservation operation requires a reservation id"
                )
        elif self.reservation_id != 0:
            raise EaglegateExactnessError(
                "non-reservation operation cannot carry a reservation id"
            )
        positive_count_operations = {
            AdapterOperation.RESERVE,
            AdapterOperation.PROPOSE,
            AdapterOperation.REWIND,
            AdapterOperation.COMMIT,
        }
        if self.operation in positive_count_operations and self.token_count == 0:
            raise EaglegateExactnessError(
                "operation requires a positive token count"
            )
        if self.operation in {
            AdapterOperation.PIN,
            AdapterOperation.CANCEL,
            AdapterOperation.RELEASE,
            AdapterOperation.FALLBACK,
            AdapterOperation.CLOSE,
        } and self.token_count != 0:
            raise EaglegateExactnessError(
                "operation cannot carry a token count"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "adapter_contract_id": EAGLEGATE_ADAPTER_CONTRACT_ID,
            "adapter_abi_version": EAGLEGATE_ADAPTER_ABI_VERSION,
            "sequence_id": EAGLEGATE_ADAPTER_SEQUENCE_ID,
            "sequence": self.sequence,
            "operation": self.operation.value,
            "state_before": self.state_before.value,
            "state_after": self.state_after.value,
            "position": self.position,
            "token_count": self.token_count,
            "reservation_id": self.reservation_id,
            "authority": self.authority,
            "reason": self.reason,
            "fault": self.fault.value,
            "previous_event_root": self.previous_event_root,
        }

    @property
    def event_root(self) -> str:
        return canonical_root("adapter-trace-event", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateAdapterTrace:
    request_root: str
    events: tuple[AdapterTraceEvent, ...]

    def __post_init__(self) -> None:
        require_root("request_root", self.request_root)
        if not self.events:
            raise EaglegateExactnessError("adapter trace requires events")
        previous_root = ""
        state = AdapterState.NEW
        active_reservation = 0
        for sequence, event in enumerate(self.events):
            if not isinstance(event, AdapterTraceEvent):
                raise EaglegateExactnessError(
                    "adapter trace contains a non-event value"
                )
            if event.sequence != sequence:
                raise EaglegateExactnessError(
                    "adapter trace sequence is not contiguous"
                )
            if event.previous_event_root != previous_root:
                raise EaglegateExactnessError(
                    "adapter trace predecessor root mismatch"
                )
            if event.state_before is not state:
                raise EaglegateExactnessError(
                    "adapter trace state chain is not contiguous"
                )
            expected = ADAPTER_ALLOWED_TRANSITIONS.get((state, event.operation))
            if expected is None or event.state_after is not expected:
                raise EaglegateExactnessError(
                    "adapter trace contains an illegal transition"
                )
            if event.operation is AdapterOperation.RESERVE:
                if active_reservation:
                    raise EaglegateExactnessError(
                        "adapter trace overlaps reservations"
                    )
                active_reservation = event.reservation_id
            elif event.operation in {
                AdapterOperation.PROPOSE,
                AdapterOperation.VERIFY,
                AdapterOperation.REWIND,
                AdapterOperation.COMMIT,
                AdapterOperation.CANCEL,
                AdapterOperation.RELEASE,
            }:
                if not active_reservation or event.reservation_id != active_reservation:
                    raise EaglegateExactnessError(
                        "adapter trace reservation identity mismatch"
                    )
                if event.operation is AdapterOperation.RELEASE:
                    active_reservation = 0
            elif active_reservation:
                raise EaglegateExactnessError(
                    "adapter trace leaves a reservation active"
                )
            state = expected
            previous_root = event.event_root
        if state is not AdapterState.CLOSED:
            raise EaglegateExactnessError("adapter trace must end closed")
        if active_reservation:
            raise EaglegateExactnessError(
                "adapter trace ends with an active reservation"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "adapter_contract_id": EAGLEGATE_ADAPTER_CONTRACT_ID,
            "adapter_abi_version": EAGLEGATE_ADAPTER_ABI_VERSION,
            "sequence_id": EAGLEGATE_ADAPTER_SEQUENCE_ID,
            "request_root": self.request_root,
            "event_count": len(self.events),
            "events": [event.canonical_dict() for event in self.events],
        }

    @property
    def trace_root(self) -> str:
        return canonical_root("adapter-trace", self.canonical_dict())


__all__ = [
    "ADAPTER_ALLOWED_TRANSITIONS",
    "AdapterFault",
    "AdapterOperation",
    "AdapterState",
    "AdapterTraceEvent",
    "EAGLEGATE_ADAPTER_ABI_VERSION",
    "EAGLEGATE_ADAPTER_CONTRACT_ID",
    "EAGLEGATE_ADAPTER_SEQUENCE_ID",
    "EAGLEGATE_TARGET_COMMIT_AUTHORITY",
    "EaglegateAdapterIdentity",
    "EaglegateAdapterLimits",
    "EaglegateAdapterRequest",
    "EaglegateAdapterTrace",
]

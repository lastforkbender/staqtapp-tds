"""Content-free Eaglegate evidence and append-only epoch receipts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .contract import (
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
    EaglegateContractError,
    EaglegateEpochState,
    EaglegateFault,
    _ascii,
    _bool,
    _canonical_root,
    _enum,
    _int,
    _root,
)


@dataclass(frozen=True, slots=True)
class EaglegateEpisodeReceipt:
    epoch_root: str
    decision_root: str
    request_class_root: str
    proposed_tokens: int
    verified_candidate_tokens: int
    accepted_draft_tokens: int
    target_tokens_committed: int
    target_verification_passes: int
    draft_ns: int
    verify_ns: int
    commit_or_rewind_ns: int
    kv_pages_reserved: int
    kv_pages_released: int
    fallback_reason: str = ""
    fault: EaglegateFault = EaglegateFault.NONE
    prompt_content_persisted: bool = False
    logits_persisted: bool = False
    kv_tensor_persisted: bool = False

    def __post_init__(self) -> None:
        for name in ("epoch_root", "decision_root", "request_class_root"):
            _root(name, getattr(self, name))
        for name in (
            "proposed_tokens",
            "verified_candidate_tokens",
            "accepted_draft_tokens",
            "target_tokens_committed",
            "target_verification_passes",
            "draft_ns",
            "verify_ns",
            "commit_or_rewind_ns",
            "kv_pages_reserved",
            "kv_pages_released",
        ):
            _int(name, getattr(self, name))
        if self.accepted_draft_tokens > min(
            self.proposed_tokens,
            self.verified_candidate_tokens,
            self.target_tokens_committed,
        ):
            raise EaglegateContractError("accepted token counts are inconsistent")
        _ascii("fallback_reason", self.fallback_reason, empty=True)
        _enum("fault", self.fault, EaglegateFault)
        for name in (
            "prompt_content_persisted",
            "logits_persisted",
            "kv_tensor_persisted",
        ):
            _bool(name, getattr(self, name))
            if getattr(self, name):
                raise EaglegateContractError(
                    f"{name} violates content-free evidence",
                    fault=EaglegateFault.AUTHORITY_REJECTED,
                )

    def canonical_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fault"] = self.fault.value
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            **value,
        }

    @property
    def receipt_root(self) -> str:
        return _canonical_root("episode-receipt", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EaglegateEpochReceipt:
    epoch_root: str
    state: EaglegateEpochState
    qualification_root: str = ""
    previous_receipt_root: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        _root("epoch_root", self.epoch_root)
        _enum("state", self.state, EaglegateEpochState)
        _root("qualification_root", self.qualification_root, empty=True)
        _root("previous_receipt_root", self.previous_receipt_root, empty=True)
        _ascii("reason_code", self.reason_code, empty=True)
        if self.state in {
            EaglegateEpochState.QUALIFIED,
            EaglegateEpochState.STAGED,
            EaglegateEpochState.SHADOW,
            EaglegateEpochState.CANARY,
            EaglegateEpochState.ACTIVE,
        } and not self.qualification_root:
            raise EaglegateContractError(
                "state requires qualification",
                fault=EaglegateFault.QUALIFICATION_REQUIRED,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "epoch_root": self.epoch_root,
            "state": self.state.value,
            "qualification_root": self.qualification_root,
            "previous_receipt_root": self.previous_receipt_root,
            "reason_code": self.reason_code,
        }

    @property
    def receipt_root(self) -> str:
        return _canonical_root("epoch-receipt", self.canonical_dict())


_TRANSITIONS: Mapping[EaglegateEpochState, frozenset[EaglegateEpochState]] = {
    EaglegateEpochState.DRAFT: frozenset(
        {EaglegateEpochState.QUALIFIED, EaglegateEpochState.QUARANTINED}
    ),
    EaglegateEpochState.QUALIFIED: frozenset(
        {
            EaglegateEpochState.STAGED,
            EaglegateEpochState.RETIRED,
            EaglegateEpochState.QUARANTINED,
        }
    ),
    EaglegateEpochState.STAGED: frozenset(
        {
            EaglegateEpochState.SHADOW,
            EaglegateEpochState.RETIRED,
            EaglegateEpochState.QUARANTINED,
        }
    ),
    EaglegateEpochState.SHADOW: frozenset(
        {
            EaglegateEpochState.CANARY,
            EaglegateEpochState.RETIRED,
            EaglegateEpochState.QUARANTINED,
        }
    ),
    EaglegateEpochState.CANARY: frozenset(
        {
            EaglegateEpochState.ACTIVE,
            EaglegateEpochState.SHADOW,
            EaglegateEpochState.RETIRED,
            EaglegateEpochState.QUARANTINED,
        }
    ),
    EaglegateEpochState.ACTIVE: frozenset(
        {EaglegateEpochState.RETIRED, EaglegateEpochState.QUARANTINED}
    ),
    EaglegateEpochState.RETIRED: frozenset(),
    EaglegateEpochState.QUARANTINED: frozenset(),
}


def validate_epoch_transition(
    previous: EaglegateEpochReceipt,
    current: EaglegateEpochReceipt,
) -> EaglegateEpochReceipt:
    if previous.epoch_root != current.epoch_root:
        raise EaglegateContractError(
            "receipt chain crossed epoch identity",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    if current.previous_receipt_root != previous.receipt_root:
        raise EaglegateContractError(
            "receipt does not bind its predecessor",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    if current.state not in _TRANSITIONS[previous.state]:
        raise EaglegateContractError(
            "invalid epoch transition", fault=EaglegateFault.NONCANONICAL
        )
    if previous.qualification_root and (
        current.qualification_root != previous.qualification_root
    ):
        raise EaglegateContractError(
            "qualification changed within an epoch",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    return current


__all__ = [
    "EaglegateEpisodeReceipt",
    "EaglegateEpochReceipt",
    "validate_epoch_transition",
]

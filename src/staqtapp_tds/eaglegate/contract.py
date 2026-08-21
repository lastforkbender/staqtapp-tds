"""Lossless control-plane contracts for Eaglegate speculative decoding.

Eaglegate never predicts, accepts, samples, or commits tokens. It binds an exact
model/runtime identity, selects only prequalified EAGLE plans, and emits bounded
content-free evidence. The target sampler remains token authority and the target
runtime remains committed-token/KV authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

EAGLEGATE_FORMAT_VERSION = 1
EAGLEGATE_CONTRACT_ID = "tds-eaglegate-lossless-v1"
EAGLEGATE_CAPABILITY_SNAPSHOT_ID = "tds-eaglegate-capability-snapshot-v1"
EAGLEGATE_ACCEPTANCE_CONTRACT_ID = "target-exact-verification-v1"
EAGLEGATE_SELECTION_CONTRACT_ID = "first-eligible-plan-v1"
EAGLEGATE_PROPOSER_FAMILY = "eagle"

_U16 = (1 << 16) - 1
_U32 = (1 << 32) - 1
_U63 = (1 << 63) - 1
_ROOT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROOT_PREFIX = b"STAQTAPP-TDS\x00EAGLEGATE\x00V1\x00"


class EaglegateFault(str, Enum):
    NONE = "none"
    INVALID_INPUT = "invalid_input"
    BOUND_EXCEEDED = "bound_exceeded"
    IDENTITY_MISMATCH = "identity_mismatch"
    INCOMPATIBLE = "incompatible"
    NONCANONICAL = "noncanonical"
    AUTHORITY_REJECTED = "authority_rejected"
    QUALIFICATION_REQUIRED = "qualification_required"
    PUBLICATION_CONFLICT = "publication_conflict"
    TARGET_UNAVAILABLE = "target_unavailable"


class EaglegateMode(str, Enum):
    TARGET_ONLY = "target_only"
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"


class EaglegateSamplerClass(str, Enum):
    GREEDY = "greedy"
    LOSSLESS_SAMPLING = "lossless_sampling"


class EaglegateDecisionKind(str, Enum):
    ADMIT = "admit"
    FALLBACK = "fallback"
    ABSTAIN = "abstain"
    FAULT = "fault"


class EaglegateEpochState(str, Enum):
    DRAFT = "draft"
    QUALIFIED = "qualified"
    STAGED = "staged"
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"
    RETIRED = "retired"
    QUARANTINED = "quarantined"


class EaglegateContractError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        fault: EaglegateFault = EaglegateFault.INVALID_INPUT,
    ) -> None:
        super().__init__(message)
        self.fault = fault


def _int(name: str, value: int, lo: int = 0, hi: int = _U63) -> int:
    if type(value) is not int:
        raise EaglegateContractError(f"{name} must be an integer")
    if value < lo:
        raise EaglegateContractError(f"{name} must be at least {lo}")
    if value > hi:
        raise EaglegateContractError(
            f"{name} exceeds {hi}", fault=EaglegateFault.BOUND_EXCEEDED
        )
    return value


def _bool(name: str, value: bool) -> bool:
    if type(value) is not bool:
        raise EaglegateContractError(f"{name} must be a boolean")
    return value


def _ascii(name: str, value: str, *, empty: bool = False, limit: int = 192) -> str:
    if type(value) is not str or (not value and not empty):
        raise EaglegateContractError(f"{name} must be a valid string")
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise EaglegateContractError(f"{name} must be printable ASCII") from exc
    if len(raw) > limit:
        raise EaglegateContractError(
            f"{name} exceeds {limit} bytes", fault=EaglegateFault.BOUND_EXCEEDED
        )
    if raw and any(byte < 0x21 or byte > 0x7E for byte in raw):
        raise EaglegateContractError(f"{name} contains whitespace/control bytes")
    return value


def _root(name: str, value: str, *, empty: bool = False) -> str:
    if empty and value == "":
        return value
    if type(value) is not str or not _ROOT_RE.fullmatch(value):
        raise EaglegateContractError(
            f"{name} must be lowercase sha256:<64-hex>",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    return value


def _enum(name: str, value: Enum, expected: type[Enum]) -> str:
    if not isinstance(value, expected):
        raise EaglegateContractError(f"{name} must be {expected.__name__}")
    return str(value.value)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise EaglegateContractError("value is not canonical JSON") from exc


def _canonical_root(domain: str, value: Mapping[str, Any]) -> str:
    _ascii("domain", domain)
    payload = _ROOT_PREFIX + domain.encode("ascii") + b"\x00" + _canonical_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class EaglegateAuthorityBoundary:
    target_verifier_required: bool = True
    target_sampler_is_acceptance_authority: bool = True
    target_runtime_is_commit_authority: bool = True
    proposer_may_accept_tokens: bool = False
    proposer_may_commit_tokens: bool = False
    proposer_may_commit_kv: bool = False
    approximate_acceptance_allowed: bool = False
    semantic_similarity_acceptance_allowed: bool = False
    unverified_cache_acceptance_allowed: bool = False
    mixed_epoch_execution_allowed: bool = False
    online_policy_mutation_allowed: bool = False
    target_only_fallback_required: bool = True
    console_may_activate: bool = False
    browser_may_activate: bool = False
    prompt_content_persistence_allowed: bool = False
    logits_persistence_allowed: bool = False
    kv_tensor_persistence_allowed: bool = False

    def __post_init__(self) -> None:
        expected = {
            "target_verifier_required": True,
            "target_sampler_is_acceptance_authority": True,
            "target_runtime_is_commit_authority": True,
            "proposer_may_accept_tokens": False,
            "proposer_may_commit_tokens": False,
            "proposer_may_commit_kv": False,
            "approximate_acceptance_allowed": False,
            "semantic_similarity_acceptance_allowed": False,
            "unverified_cache_acceptance_allowed": False,
            "mixed_epoch_execution_allowed": False,
            "online_policy_mutation_allowed": False,
            "target_only_fallback_required": True,
            "console_may_activate": False,
            "browser_may_activate": False,
            "prompt_content_persistence_allowed": False,
            "logits_persistence_allowed": False,
            "kv_tensor_persistence_allowed": False,
        }
        if asdict(self) != expected:
            raise EaglegateContractError(
                "lossless authority cannot be widened",
                fault=EaglegateFault.AUTHORITY_REJECTED,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "acceptance_contract_id": EAGLEGATE_ACCEPTANCE_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return _canonical_root("authority", self.canonical_dict())


EAGLEGATE_AUTHORITY = EaglegateAuthorityBoundary()


@dataclass(frozen=True, slots=True)
class EaglegateIdentity:
    target_model_root: str
    tokenizer_root: str
    proposer_root: str
    target_runtime_root: str
    sampler_contract_root: str
    logits_processor_root: str
    kv_contract_root: str
    kernel_capability_root: str
    numerical_mode: str
    tenant_scope: str
    proposer_family: str = EAGLEGATE_PROPOSER_FAMILY

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            _root(item.name, value) if item.name.endswith("_root") else _ascii(
                item.name, value
            )
        if self.proposer_family != EAGLEGATE_PROPOSER_FAMILY:
            raise EaglegateContractError(
                "Eaglegate v1 accepts only EAGLE-family proposers",
                fault=EaglegateFault.INCOMPATIBLE,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "acceptance_contract_id": EAGLEGATE_ACCEPTANCE_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def identity_root(self) -> str:
        return _canonical_root("identity", self.canonical_dict())


def authority_snapshot() -> dict[str, Any]:
    return {
        **EAGLEGATE_AUTHORITY.canonical_dict(),
        "authority_root": EAGLEGATE_AUTHORITY.authority_root,
    }


__all__ = [
    "EAGLEGATE_ACCEPTANCE_CONTRACT_ID",
    "EAGLEGATE_AUTHORITY",
    "EAGLEGATE_CAPABILITY_SNAPSHOT_ID",
    "EAGLEGATE_CONTRACT_ID",
    "EAGLEGATE_FORMAT_VERSION",
    "EAGLEGATE_PROPOSER_FAMILY",
    "EAGLEGATE_SELECTION_CONTRACT_ID",
    "EaglegateAuthorityBoundary",
    "EaglegateContractError",
    "EaglegateDecisionKind",
    "EaglegateEpochState",
    "EaglegateFault",
    "EaglegateIdentity",
    "EaglegateMode",
    "EaglegateSamplerClass",
    "authority_snapshot",
]

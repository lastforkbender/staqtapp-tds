"""Deterministic Trace Rank ABI v2 contract types.

This module defines bounded, immutable identities and limits for the planned
Native Trace Ranking redesign. It intentionally contains no graph search,
forest inference, storage mutation, training, activation, network access, or
request-path telemetry. The contract is the Phase-1 boundary that later native
implementations must match.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import Enum
import hashlib
import json
from typing import Any, Mapping

TRACE_RANK_ABI_VERSION = 2
TRACE_RANK_CONTRACT_ID = "tds-trace-rank-abi-v2"

# Full proposed first-release envelope. Smaller qualified profiles may lower
# these values, but no runtime bundle may raise them without a new ABI contract.
_HARD_MAX_FEATURES = 64
_HARD_MAX_HOT_PATH_SENTINELS = 4
_HARD_MAX_TREES_PER_SENTINEL = 32
_HARD_MAX_TREE_DEPTH = 6
_HARD_MAX_MODEL_BYTES_PER_SENTINEL = 256 * 1024
_HARD_MAX_LEARNED_BUNDLE_BYTES = 2 * 1024 * 1024
_HARD_MAX_CANDIDATES = 32
_HARD_MAX_EXPANDED_NODES = 512
_HARD_MAX_EDGES = 2_048
_HARD_MAX_STEPS = 16
_HARD_MAX_ALTERNATIVES = 4
_HARD_MAX_REQUEST_SCRATCH_BYTES = 64 * 1024
_HARD_MESSAGE_BYTES = 128
_HARD_MAX_MESSAGES = 16
_HARD_MAX_MESSAGE_DEPTH = 8
_IDENTITY_MAX_BYTES = 192
_ROOT_DOMAIN_PREFIX = b"STAQTAPP-TDS\x00TRACE-RANK\x00ABI-V2\x00"


class TraceRankDecision(str, Enum):
    """Only externally meaningful outcomes of the advisory ranker."""

    RANKED = "ranked"
    FALLBACK = "fallback"
    ABSTAIN = "abstain"


class TraceRankFault(str, Enum):
    """Stable failure classes for Phase-1 fixtures and later C parity."""

    NONE = "none"
    INVALID_INPUT = "invalid_input"
    BOUND_EXCEEDED = "bound_exceeded"
    EPOCH_MISMATCH = "epoch_mismatch"
    POLICY_REJECTED = "policy_rejected"
    INTEGRITY_FAILURE = "integrity_failure"
    RANKER_UNAVAILABLE = "ranker_unavailable"
    TIMEOUT = "timeout"


class TraceRankSentinelRole(str, Enum):
    """The maximum learned hot-path role set allowed by ABI v2."""

    ROUTE = "route"
    CACHE = "cache"
    COST = "cost"
    INTEGRITY = "integrity"


TRACE_RANK_V2_SENTINEL_ROLES = (
    TraceRankSentinelRole.ROUTE,
    TraceRankSentinelRole.CACHE,
    TraceRankSentinelRole.COST,
    TraceRankSentinelRole.INTEGRITY,
)
TRACE_RANK_V2_VERTICAL_SLICE_ROLES = (
    TraceRankSentinelRole.ROUTE,
    TraceRankSentinelRole.COST,
    TraceRankSentinelRole.INTEGRITY,
)


class TraceRankContractError(ValueError):
    """A deterministic ABI contract failure with a stable fault class."""

    def __init__(
        self,
        message: str,
        *,
        fault: TraceRankFault = TraceRankFault.INVALID_INPUT,
    ) -> None:
        super().__init__(message)
        self.fault = fault


def _validate_identity(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise TraceRankContractError(f"{name} must be a string")
    if not value:
        raise TraceRankContractError(f"{name} must not be empty")
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise TraceRankContractError(f"{name} must be printable ASCII") from exc
    if len(raw) > _IDENTITY_MAX_BYTES:
        raise TraceRankContractError(
            f"{name} exceeds {_IDENTITY_MAX_BYTES} encoded bytes",
            fault=TraceRankFault.BOUND_EXCEEDED,
        )
    if any(byte < 0x21 or byte > 0x7E for byte in raw):
        raise TraceRankContractError(
            f"{name} must not contain whitespace or control characters"
        )
    return value


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _canonical_root(domain: str, value: Mapping[str, Any]) -> str:
    domain_bytes = domain.encode("ascii")
    material = _ROOT_DOMAIN_PREFIX + domain_bytes + b"\x00" + _canonical_json_bytes(value)
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class ServingEpochIdentity:
    """One request-pinned compatible identity tuple.

    The fields follow the Frontier Evidence Fabric composite ServingEpoch. The
    identities are deliberately opaque at ABI v2: a deployment may use content
    roots, signed catalog identifiers, or another bounded canonical identity,
    while the request must pin all fields together.
    """

    dataset_generation_set: str
    graph_map_epoch: str
    feature_schema: str
    rank_model_epoch: str
    sentinel_policy_epoch: str
    retrieval_policy_epoch: str
    context_policy_epoch: str
    shard_directory_epoch: str
    frontier_model_config_id: str

    def __post_init__(self) -> None:
        for item in fields(self):
            _validate_identity(item.name, getattr(self, item.name))

    def canonical_dict(self) -> dict[str, str | int]:
        return {
            "abi_version": TRACE_RANK_ABI_VERSION,
            "contract_id": TRACE_RANK_CONTRACT_ID,
            **asdict(self),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_dict())

    @property
    def epoch_root(self) -> str:
        return _canonical_root("serving-epoch", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class TraceRankLimits:
    """Qualified limits that can only narrow the ABI v2 hard envelope."""

    max_features: int = _HARD_MAX_FEATURES
    max_hot_path_sentinels: int = _HARD_MAX_HOT_PATH_SENTINELS
    max_trees_per_sentinel: int = _HARD_MAX_TREES_PER_SENTINEL
    max_tree_depth: int = _HARD_MAX_TREE_DEPTH
    max_model_bytes_per_sentinel: int = _HARD_MAX_MODEL_BYTES_PER_SENTINEL
    max_learned_bundle_bytes: int = _HARD_MAX_LEARNED_BUNDLE_BYTES
    max_candidates: int = _HARD_MAX_CANDIDATES
    max_expanded_nodes: int = _HARD_MAX_EXPANDED_NODES
    max_edges: int = _HARD_MAX_EDGES
    max_steps: int = _HARD_MAX_STEPS
    max_alternatives: int = _HARD_MAX_ALTERNATIVES
    max_request_scratch_bytes: int = _HARD_MAX_REQUEST_SCRATCH_BYTES
    message_bytes: int = _HARD_MESSAGE_BYTES
    max_messages: int = _HARD_MAX_MESSAGES
    max_message_depth: int = _HARD_MAX_MESSAGE_DEPTH

    def __post_init__(self) -> None:
        hard_limits = {
            "max_features": _HARD_MAX_FEATURES,
            "max_hot_path_sentinels": _HARD_MAX_HOT_PATH_SENTINELS,
            "max_trees_per_sentinel": _HARD_MAX_TREES_PER_SENTINEL,
            "max_tree_depth": _HARD_MAX_TREE_DEPTH,
            "max_model_bytes_per_sentinel": _HARD_MAX_MODEL_BYTES_PER_SENTINEL,
            "max_learned_bundle_bytes": _HARD_MAX_LEARNED_BUNDLE_BYTES,
            "max_candidates": _HARD_MAX_CANDIDATES,
            "max_expanded_nodes": _HARD_MAX_EXPANDED_NODES,
            "max_edges": _HARD_MAX_EDGES,
            "max_steps": _HARD_MAX_STEPS,
            "max_alternatives": _HARD_MAX_ALTERNATIVES,
            "max_request_scratch_bytes": _HARD_MAX_REQUEST_SCRATCH_BYTES,
            "message_bytes": _HARD_MESSAGE_BYTES,
            "max_messages": _HARD_MAX_MESSAGES,
            "max_message_depth": _HARD_MAX_MESSAGE_DEPTH,
        }
        for name, hard_max in hard_limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TraceRankContractError(f"{name} must be an integer")
            if value <= 0:
                raise TraceRankContractError(f"{name} must be positive")
            if value > hard_max:
                raise TraceRankContractError(
                    f"{name}={value} exceeds ABI v2 hard maximum {hard_max}",
                    fault=TraceRankFault.BOUND_EXCEEDED,
                )
        if self.message_bytes != _HARD_MESSAGE_BYTES:
            raise TraceRankContractError(
                f"message_bytes must remain exactly {_HARD_MESSAGE_BYTES} in ABI v2"
            )
        if self.max_steps > self.max_expanded_nodes:
            raise TraceRankContractError("max_steps cannot exceed max_expanded_nodes")
        if self.max_alternatives > self.max_candidates:
            raise TraceRankContractError(
                "max_alternatives cannot exceed max_candidates"
            )
        if self.max_hot_path_sentinels > len(TRACE_RANK_V2_SENTINEL_ROLES):
            raise TraceRankContractError(
                "max_hot_path_sentinels exceeds the closed ABI v2 role set",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )

    def canonical_dict(self) -> dict[str, int | str]:
        return {
            "abi_version": TRACE_RANK_ABI_VERSION,
            "contract_id": TRACE_RANK_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def limits_root(self) -> str:
        return _canonical_root("limits", self.canonical_dict())

    @classmethod
    def first_vertical_slice(cls) -> "TraceRankLimits":
        """Return the future shadow-only profile fixed during Foundation Repair."""

        return cls(
            max_hot_path_sentinels=len(TRACE_RANK_V2_VERTICAL_SLICE_ROLES),
            max_trees_per_sentinel=16,
            max_tree_depth=5,
            max_candidates=16,
            max_steps=8,
        )


@dataclass(frozen=True, slots=True)
class TraceRankBaselineManifest:
    """Immutable identities needed to replay a Phase-1 baseline."""

    implementation_root: str
    corpus_root: str
    objective_contract_root: str
    feature_schema_root: str
    baseline_configuration_root: str
    deterministic_fallback_id: str
    baseline_engine_id: str = "native-spiral-compat"

    def __post_init__(self) -> None:
        for item in fields(self):
            _validate_identity(item.name, getattr(self, item.name))

    def canonical_dict(self) -> dict[str, str | int]:
        return {
            "abi_version": TRACE_RANK_ABI_VERSION,
            "contract_id": TRACE_RANK_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def manifest_root(self) -> str:
        return _canonical_root("baseline-manifest", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class TraceRankAuthorityBoundary:
    """Machine-checkable declaration of the ranker's non-authority."""

    read_only_ranking: bool = True
    may_write_storage: bool = False
    may_commit_semantics: bool = False
    may_change_privacy_or_license_policy: bool = False
    may_activate_bundles: bool = False
    may_train_on_request_path: bool = False
    may_enter_storage_locks: bool = False
    may_use_frontier_logits: bool = False

    def __post_init__(self) -> None:
        expected = {
            "read_only_ranking": True,
            "may_write_storage": False,
            "may_commit_semantics": False,
            "may_change_privacy_or_license_policy": False,
            "may_activate_bundles": False,
            "may_train_on_request_path": False,
            "may_enter_storage_locks": False,
            "may_use_frontier_logits": False,
        }
        if asdict(self) != expected:
            raise TraceRankContractError(
                "ABI v2 authority boundary cannot be weakened by configuration",
                fault=TraceRankFault.POLICY_REJECTED,
            )

    def canonical_dict(self) -> dict[str, bool | int | str]:
        return {
            "abi_version": TRACE_RANK_ABI_VERSION,
            "contract_id": TRACE_RANK_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return _canonical_root("authority", self.canonical_dict())


TRACE_RANK_V2_AUTHORITY = TraceRankAuthorityBoundary()
TRACE_RANK_V2_LIMITS = TraceRankLimits()
TRACE_RANK_V2_VERTICAL_SLICE_LIMITS = TraceRankLimits.first_vertical_slice()


def validate_pinned_epoch(
    pinned_epoch: ServingEpochIdentity,
    expected_epoch: ServingEpochIdentity,
) -> None:
    """Reject a mixed or stale epoch before candidate generation or ranking."""

    if not isinstance(pinned_epoch, ServingEpochIdentity):
        raise TraceRankContractError("pinned_epoch has an invalid type")
    if not isinstance(expected_epoch, ServingEpochIdentity):
        raise TraceRankContractError("expected_epoch has an invalid type")
    if pinned_epoch.epoch_root != expected_epoch.epoch_root:
        raise TraceRankContractError(
            "pinned ServingEpoch does not match the admitted request epoch",
            fault=TraceRankFault.EPOCH_MISMATCH,
        )


def validate_request_shape(
    *,
    candidate_count: int,
    top_k: int,
    feature_count: int,
    limits: TraceRankLimits = TRACE_RANK_V2_LIMITS,
) -> None:
    """Validate bounded request dimensions before any learned work occurs."""

    if not isinstance(limits, TraceRankLimits):
        raise TraceRankContractError("limits must be a TraceRankLimits instance")
    values = {
        "candidate_count": candidate_count,
        "top_k": top_k,
        "feature_count": feature_count,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise TraceRankContractError(f"{name} must be an integer")
        if value < 0:
            raise TraceRankContractError(f"{name} must not be negative")
    if candidate_count > limits.max_candidates:
        raise TraceRankContractError(
            "candidate_count exceeds qualified limit",
            fault=TraceRankFault.BOUND_EXCEEDED,
        )
    if feature_count > limits.max_features:
        raise TraceRankContractError(
            "feature_count exceeds qualified limit",
            fault=TraceRankFault.BOUND_EXCEEDED,
        )
    if top_k > candidate_count:
        raise TraceRankContractError(
            "top_k cannot exceed candidate_count",
            fault=TraceRankFault.BOUND_EXCEEDED,
        )

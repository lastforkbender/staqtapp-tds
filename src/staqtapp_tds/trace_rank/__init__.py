"""Versioned Native Trace Ranking contracts.

No learned or graph implementation is active in the v3.6 Foundation Repair
phase. This package exposes only the deterministic ABI v2 contract surface.
"""
from staqtapp_tds.trace_rank.contract import (
    TRACE_RANK_ABI_VERSION,
    TRACE_RANK_CONTRACT_ID,
    TRACE_RANK_V2_AUTHORITY,
    TRACE_RANK_V2_LIMITS,
    TRACE_RANK_V2_SENTINEL_ROLES,
    TRACE_RANK_V2_VERTICAL_SLICE_LIMITS,
    TRACE_RANK_V2_VERTICAL_SLICE_ROLES,
    ServingEpochIdentity,
    TraceRankAuthorityBoundary,
    TraceRankBaselineManifest,
    TraceRankContractError,
    TraceRankDecision,
    TraceRankFault,
    TraceRankLimits,
    TraceRankSentinelRole,
    validate_pinned_epoch,
    validate_request_shape,
)

__all__ = [
    "TRACE_RANK_ABI_VERSION",
    "TRACE_RANK_CONTRACT_ID",
    "TRACE_RANK_V2_AUTHORITY",
    "TRACE_RANK_V2_LIMITS",
    "TRACE_RANK_V2_SENTINEL_ROLES",
    "TRACE_RANK_V2_VERTICAL_SLICE_LIMITS",
    "TRACE_RANK_V2_VERTICAL_SLICE_ROLES",
    "ServingEpochIdentity",
    "TraceRankAuthorityBoundary",
    "TraceRankBaselineManifest",
    "TraceRankContractError",
    "TraceRankDecision",
    "TraceRankFault",
    "TraceRankLimits",
    "TraceRankSentinelRole",
    "validate_pinned_epoch",
    "validate_request_shape",
]

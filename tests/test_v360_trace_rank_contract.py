from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from staqtapp_tds.trace_rank import (
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
    TraceRankFault,
    TraceRankLimits,
    TraceRankSentinelRole,
    validate_pinned_epoch,
    validate_request_shape,
)

def _epoch(**overrides: str) -> ServingEpochIdentity:
    values = {
        "dataset_generation_set": "sha256:dataset",
        "graph_map_epoch": "sha256:graph",
        "feature_schema": "sha256:features",
        "rank_model_epoch": "sha256:forest",
        "sentinel_policy_epoch": "sha256:sentinels",
        "retrieval_policy_epoch": "sha256:retrieval",
        "context_policy_epoch": "sha256:context",
        "shard_directory_epoch": "sha256:shards",
        "frontier_model_config_id": "model:frontier-config",
    }
    values.update(overrides)
    return ServingEpochIdentity(**values)


def _baseline(**overrides: str) -> TraceRankBaselineManifest:
    values = {
        "implementation_root": "git:281cfedf3531beb3c9e2a85330cd2b8210374faa",
        "corpus_root": "sha256:corpus",
        "objective_contract_root": "sha256:objective",
        "feature_schema_root": "sha256:features",
        "baseline_configuration_root": "sha256:baseline-config",
        "deterministic_fallback_id": "tds:complete-deterministic-route",
    }
    values.update(overrides)
    return TraceRankBaselineManifest(**values)


def test_trace_rank_v2_contract_identity_is_stable_and_immutable() -> None:
    assert TRACE_RANK_ABI_VERSION == 2
    assert TRACE_RANK_CONTRACT_ID == "tds-trace-rank-abi-v2"
    first = _epoch()
    second = _epoch()
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.epoch_root == second.epoch_root
    assert len(first.epoch_root) == 64
    with pytest.raises(FrozenInstanceError):
        first.graph_map_epoch = "other"  # type: ignore[misc]


def test_serving_epoch_rejects_empty_unbounded_or_noncanonical_identity() -> None:
    with pytest.raises(TraceRankContractError) as empty:
        _epoch(graph_map_epoch="")
    assert empty.value.fault is TraceRankFault.INVALID_INPUT

    with pytest.raises(TraceRankContractError):
        _epoch(graph_map_epoch="contains whitespace")

    with pytest.raises(TraceRankContractError) as oversized:
        _epoch(graph_map_epoch="x" * 193)
    assert oversized.value.fault is TraceRankFault.BOUND_EXCEEDED


def test_mixed_epoch_is_rejected_before_ranking() -> None:
    admitted = _epoch()
    validate_pinned_epoch(admitted, _epoch())

    with pytest.raises(TraceRankContractError) as mismatch:
        validate_pinned_epoch(admitted, _epoch(graph_map_epoch="sha256:graph-v2"))
    assert mismatch.value.fault is TraceRankFault.EPOCH_MISMATCH


def test_full_envelope_and_first_vertical_slice_are_exactly_bounded() -> None:
    full = TRACE_RANK_V2_LIMITS
    assert full.max_features == 64
    assert full.max_hot_path_sentinels == 4
    assert full.max_trees_per_sentinel == 32
    assert full.max_tree_depth == 6
    assert full.max_candidates == 32
    assert full.max_steps == 16
    assert full.message_bytes == 128
    assert len(full.limits_root) == 64

    assert TRACE_RANK_V2_SENTINEL_ROLES == (
        TraceRankSentinelRole.ROUTE,
        TraceRankSentinelRole.CACHE,
        TraceRankSentinelRole.COST,
        TraceRankSentinelRole.INTEGRITY,
    )

    first = TRACE_RANK_V2_VERTICAL_SLICE_LIMITS
    assert TRACE_RANK_V2_VERTICAL_SLICE_ROLES == (
        TraceRankSentinelRole.ROUTE,
        TraceRankSentinelRole.COST,
        TraceRankSentinelRole.INTEGRITY,
    )
    assert first.max_hot_path_sentinels == 3
    assert first.max_trees_per_sentinel == 16
    assert first.max_tree_depth == 5
    assert first.max_candidates == 16
    assert first.max_steps == 8
    assert first.limits_root != full.limits_root

    with pytest.raises(TraceRankContractError) as candidates:
        TraceRankLimits(max_candidates=33)
    assert candidates.value.fault is TraceRankFault.BOUND_EXCEEDED
    with pytest.raises(TraceRankContractError):
        TraceRankLimits(message_bytes=64)


def test_ranker_authority_cannot_be_widened() -> None:
    assert TRACE_RANK_V2_AUTHORITY.read_only_ranking is True
    assert TRACE_RANK_V2_AUTHORITY.may_write_storage is False
    assert TRACE_RANK_V2_AUTHORITY.may_activate_bundles is False
    assert TRACE_RANK_V2_AUTHORITY.may_train_on_request_path is False
    assert TRACE_RANK_V2_AUTHORITY.may_enter_storage_locks is False
    assert TRACE_RANK_V2_AUTHORITY.may_use_frontier_logits is False
    assert len(TRACE_RANK_V2_AUTHORITY.authority_root) == 64

    with pytest.raises(TraceRankContractError) as widened:
        TraceRankAuthorityBoundary(may_write_storage=True)
    assert widened.value.fault is TraceRankFault.POLICY_REJECTED


def test_request_shape_fails_before_learned_work() -> None:
    limits = TRACE_RANK_V2_VERTICAL_SLICE_LIMITS
    validate_request_shape(
        candidate_count=16,
        top_k=8,
        feature_count=64,
        limits=limits,
    )
    with pytest.raises(TraceRankContractError) as candidates:
        validate_request_shape(
            candidate_count=17,
            top_k=8,
            feature_count=64,
            limits=limits,
        )
    assert candidates.value.fault is TraceRankFault.BOUND_EXCEEDED
    with pytest.raises(TraceRankContractError) as top_k:
        validate_request_shape(
            candidate_count=8,
            top_k=9,
            feature_count=64,
            limits=limits,
        )
    assert top_k.value.fault is TraceRankFault.BOUND_EXCEEDED


def test_baseline_manifest_root_binds_every_replay_identity() -> None:
    baseline = _baseline()
    assert len(baseline.manifest_root) == 64
    assert _baseline().manifest_root == baseline.manifest_root
    assert (
        _baseline(corpus_root="sha256:corpus-v2").manifest_root
        != baseline.manifest_root
    )
    assert (
        _baseline(implementation_root="git:other").manifest_root
        != baseline.manifest_root
    )
    assert (
        _baseline(baseline_configuration_root="sha256:config-v2").manifest_root
        != baseline.manifest_root
    )

from __future__ import annotations

import ast
import hashlib
import json
import random
from dataclasses import fields, replace
from pathlib import Path

import pytest

from staqtapp_tds.generation.csv import (
    build_csv_generation_candidate,
    open_csv_generation,
    publish_csv_generation,
)
from staqtapp_tds.generation.generation_contract import bytes_root
from staqtapp_tds.generation.generation_store import AtomicGenerationStore
from staqtapp_tds.trace_rank import (
    PATH_MAX_RECEIPT_BYTES,
    TRACE_RANK_V2_LIMITS,
    TRACE_RANK_V2_VERTICAL_SLICE_LIMITS,
    AdmittedPathContext,
    Edge,
    FeatureBlock,
    ImmutableSourceBinding,
    PackedWaypointGraph,
    ProvenanceRecord,
    QualifiedPathPolicy,
    ServingEpochIdentity,
    TraceRankDecision,
    TraceRankFault,
    TraceRankPathBudget,
    TraceRankPathReceipt,
    TraceRankPathRequest,
    TraceRankPlannerError,
    VerifiedCSVGraphBridge,
    VerifiedPackedGraph,
    Waypoint,
    baseline_rank_model_epoch,
    admit_csv_packed_graph,
    bind_csv_generation_source,
    bind_csv_generation_sources,
    build_reference_baseline_manifest,
    plan_shortest_path,
    replay_path_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("ascii")).hexdigest()


def _row_source(row_count: int) -> tuple[bytes, tuple[int, ...]]:
    rows = tuple(f"row-{index}\n".encode("ascii") for index in range(row_count))
    offsets = [0]
    for row in rows:
        offsets.append(offsets[-1] + len(row))
    return b"".join(rows), tuple(offsets)


def _build_graph(
    edge_rows: tuple[tuple[Edge, ...], ...],
    *,
    source_binding: ImmutableSourceBinding | None = None,
    provenance_policy: int = 0b0001,
) -> tuple[PackedWaypointGraph, tuple[ImmutableSourceBinding, ...]]:
    row_count = len(edge_rows)
    if source_binding is None:
        raw, offsets = _row_source(row_count)
        source_binding = ImmutableSourceBinding(
            _root(f"generation-{row_count}"), raw, offsets
        )
    if source_binding.row_count != row_count:
        raise AssertionError("fixture source and edge row counts differ")

    sources = (source_binding,)
    provenance = (
        ProvenanceRecord(
            _root("planner-provenance"),
            generation_index=0,
            privacy_class=2,
            license_class=1,
            policy_mask=provenance_policy,
        ),
    )
    features = (FeatureBlock((7, 0), missing_mask=0b10, privacy_class=2),)
    waypoints = tuple(
        Waypoint(
            generation_index=0,
            causal_sequence=(index + 1) * 10,
            predecessor_index=index - 1,
            byte_start=source_binding.row_offsets[index],
            byte_end=source_binding.row_offsets[index + 1],
            row_start=index,
            row_end=index + 1,
            feature_index=0,
            provenance_index=0,
        )
        for index in range(row_count)
    )
    offsets = [0]
    flat_edges: list[Edge] = []
    for row in edge_rows:
        flat_edges.extend(row)
        offsets.append(len(flat_edges))
    graph = PackedWaypointGraph.build(
        server_namespace_root=_root("planner-server-namespace"),
        feature_schema_root=_root("planner-feature-schema"),
        hard_mask_universe=0b0011,
        source_bindings=sources,
        provenance=provenance,
        feature_blocks=features,
        waypoints=waypoints,
        edge_offsets=tuple(offsets),
        edges=tuple(flat_edges),
    )
    return graph, sources


def _admit(
    edge_rows: tuple[tuple[Edge, ...], ...],
) -> tuple[AdmittedPathContext, tuple[ImmutableSourceBinding, ...]]:
    graph, sources = _build_graph(edge_rows)
    verified = _verify(graph, sources)
    return _context(verified), sources


def _verify(
    graph: PackedWaypointGraph,
    sources: tuple[ImmutableSourceBinding, ...],
    *,
    source_evidence_roots: tuple[str, ...] | None = None,
) -> VerifiedPackedGraph:
    evidence = source_evidence_roots or tuple(
        _root(f"source-evidence-{index}") for index in range(len(sources))
    )
    return VerifiedPackedGraph.from_graph(
        graph,
        sources,
        source_evidence_roots=evidence,
        edge_catalog_root=_root("qualified-edge-catalog"),
    )


def _epoch(
    verified: VerifiedPackedGraph,
    baseline_root: str,
    **overrides: str,
) -> ServingEpochIdentity:
    values = {
        "dataset_generation_set": verified.dataset_generation_set_root,
        "graph_map_epoch": verified.graph_root,
        "feature_schema": verified.feature_schema_root,
        "rank_model_epoch": baseline_root,
        "sentinel_policy_epoch": "sentinel-disabled-phase5",
        "retrieval_policy_epoch": "retrieval-policy-v1",
        "context_policy_epoch": "context-policy-v1",
        "shard_directory_epoch": "shard-directory-v1",
        "frontier_model_config_id": "frontier-reference-oracle-v1",
    }
    values.update(overrides)
    return ServingEpochIdentity(
        **values,
    )


def _context(
    verified: VerifiedPackedGraph,
    *,
    hard_mask: int = 0b0001,
    operations: tuple[int, ...] = (1,),
    privacy_classes: tuple[int, ...] = (2,),
    license_classes: tuple[int, ...] = (1,),
) -> AdmittedPathContext:
    baseline = build_reference_baseline_manifest(
        verified,
        implementation_root="git:test-reference-planner",
    )
    epoch = _epoch(verified, baseline_rank_model_epoch(baseline))
    policy = QualifiedPathPolicy.admit(
        verified,
        epoch,
        satisfied_hard_mask=hard_mask,
        allowed_operations=operations,
        allowed_privacy_classes=privacy_classes,
        allowed_license_classes=license_classes,
        qualification_root=_root("controller-qualification"),
    )
    return AdmittedPathContext.admit(verified, epoch, policy, baseline)


def _request(
    context: AdmittedPathContext,
    *,
    candidates: tuple[int, ...],
    budget: TraceRankPathBudget | None = None,
) -> TraceRankPathRequest:
    return TraceRankPathRequest(
        pinned_epoch=context.expected_epoch,
        path_context_root=context.context_root,
        policy_root=context.policy.policy_root,
        start_waypoint=0,
        candidate_waypoints=candidates,
        budget=budget or TraceRankPathBudget(),
    )


def _reference_best_path(
    context: AdmittedPathContext,
    request: TraceRankPathRequest,
) -> tuple[tuple[int, ...], tuple[int, ...], int] | None:
    """Small exhaustive oracle independent of the Dijkstra implementation."""

    graph = context.verified_graph.graph
    policy = context.policy
    goals = set(request.candidate_waypoints)
    allowed = set(policy.allowed_operations)
    ranked: list[
        tuple[int, int, tuple[int, ...], tuple[int, ...], tuple[int, ...]]
    ] = []
    stack = [(0, (request.start_waypoint,), (), ())]
    while stack:
        total, waypoints, operations, edge_indices = stack.pop()
        source = waypoints[-1]
        if source in goals:
            ranked.append(
                (total, len(edge_indices), waypoints, operations, edge_indices)
            )
            continue
        if len(edge_indices) >= request.budget.max_steps:
            continue
        for edge_index in range(
            graph.edge_offsets[source], graph.edge_offsets[source + 1]
        ):
            edge = graph.edges[edge_index]
            destination = edge.destination_index
            if edge.operation not in allowed:
                continue
            if (
                edge.hard_eligibility_mask & policy.satisfied_hard_mask
                != edge.hard_eligibility_mask
            ):
                continue
            provenance = graph.provenance[
                graph.waypoints[destination].provenance_index
            ]
            if provenance.privacy_class not in policy.allowed_privacy_classes:
                continue
            if provenance.license_class not in policy.allowed_license_classes:
                continue
            if (
                graph.waypoints[destination].causal_sequence
                <= graph.waypoints[source].causal_sequence
            ):
                continue
            if destination in waypoints:
                continue
            subtotal = edge.base_cost + edge.learned_delta
            cost = subtotal - min(subtotal, edge.evidence_gain)
            next_total = total + cost
            if next_total > request.budget.max_total_cost:
                continue
            stack.append(
                (
                    next_total,
                    waypoints + (destination,),
                    operations + (edge.operation,),
                    edge_indices + (edge_index,),
                )
            )
    if not ranked:
        return None
    winner = min(ranked)
    return winner[2], winner[4], winner[0]


def test_phase5_dijkstra_returns_exact_epoch_bound_replayable_receipt() -> None:
    admitted, _sources = _admit(
        (
            (Edge(1, 1, 5, 0, 0, 1), Edge(2, 1, 2, 0, 0, 1)),
            (Edge(4, 1, 5, 0, 0, 1),),
            (Edge(3, 1, 2, 0, 0, 1),),
            (Edge(4, 1, 2, 0, 0, 1),),
            (),
        )
    )
    request = _request(admitted, candidates=(4,))

    receipt = plan_shortest_path(admitted, request)
    repeated = plan_shortest_path(admitted, request)

    assert receipt.decision is TraceRankDecision.RANKED
    assert receipt.fault is TraceRankFault.NONE
    assert tuple(item.waypoint_index for item in receipt.waypoint_path) == (0, 2, 3, 4)
    assert tuple(item.edge_index for item in receipt.edge_path) == (1, 3, 4)
    assert receipt.total_cost == receipt.total_base_cost == 6
    assert receipt.total_learned_delta == 0
    assert receipt.serving_epoch_root == request.pinned_epoch.epoch_root
    verified = admitted.verified_graph
    assert receipt.graph_root == verified.graph_root
    assert receipt.dataset_generation_set_root == verified.dataset_generation_set_root
    assert receipt.feature_schema_root == verified.feature_schema_root
    assert receipt.server_namespace_root == verified.graph.server_namespace_root
    assert receipt.graph_admission_root == verified.graph_admission_root
    assert receipt.path_context_root == admitted.context_root
    assert receipt.policy_root == admitted.policy.policy_root
    assert receipt.limits_root == TRACE_RANK_V2_VERTICAL_SLICE_LIMITS.limits_root
    assert receipt.baseline_manifest_root == admitted.baseline.manifest_root
    assert receipt.sentinel_outputs == ()
    assert receipt.canonical_bytes() == repeated.canonical_bytes()
    assert receipt.receipt_root == repeated.receipt_root
    assert receipt.request_root == (
        "sha256:311ca6dca94f4f210af579dc63a9f9a4623317c512af0a5751a33de41fe28d6c"
    )
    assert receipt.receipt_root == (
        "sha256:45be190f7fb79e59bc7d45cf73fd2f7b8da5ce7e5ee113535c4a90c998c6c2f9"
    )
    assert TraceRankPathReceipt.from_bytes(receipt.canonical_bytes()) == receipt
    assert replay_path_receipt(admitted, request, receipt) == receipt


def test_fixed_point_evidence_credit_is_saturating_and_auditable() -> None:
    admitted, _sources = _admit(
        (
            (Edge(1, 1, 2, 0, 7, 1),),
            (Edge(2, 1, 3, 0, 1, 1),),
            (),
        )
    )
    receipt = plan_shortest_path(admitted, _request(admitted, candidates=(2,)))

    assert receipt.total_base_cost == 5
    assert receipt.total_evidence_gain == 8
    assert receipt.total_credited_evidence_gain == 3
    assert receipt.total_cost == 2
    assert tuple(item.effective_cost for item in receipt.edge_path) == (0, 2)
    assert tuple(item.credited_evidence_gain for item in receipt.edge_path) == (2, 1)


def test_equal_paths_use_public_waypoint_then_operation_tie_breaks() -> None:
    admitted, _sources = _admit(
        (
            (Edge(1, 1, 3, 0, 0, 1), Edge(2, 1, 3, 0, 0, 1)),
            (Edge(3, 1, 3, 0, 0, 1),),
            (Edge(3, 1, 3, 0, 0, 1),),
            (),
        )
    )
    receipt = plan_shortest_path(admitted, _request(admitted, candidates=(3,)))
    assert tuple(item.waypoint_index for item in receipt.waypoint_path) == (0, 1, 3)

    operation_graph, sources = _build_graph(
        (
            (Edge(1, 1, 4, 0, 0, 1), Edge(1, 2, 4, 0, 0, 1)),
            (),
        )
    )
    operation_verified = _verify(operation_graph, sources)
    operation_admitted = _context(operation_verified, operations=(1, 2))
    operation_receipt = plan_shortest_path(
        operation_admitted,
        _request(operation_admitted, candidates=(1,)),
    )
    assert tuple(item.operation for item in operation_receipt.edge_path) == (1,)


def test_hard_policy_operation_and_causal_edges_are_filtered_before_rank() -> None:
    admitted, _sources = _admit(
        (
            (
                Edge(0, 1, 0, 0, 0, 1),
                Edge(1, 2, 0, 0, 0, 1),
                Edge(2, 1, 0, 0, 0, 3),
                Edge(3, 1, 7, 0, 0, 1),
            ),
            (),
            (),
            (),
        )
    )
    receipt = plan_shortest_path(admitted, _request(admitted, candidates=(3,)))

    assert receipt.decision is TraceRankDecision.RANKED
    assert tuple(item.waypoint_index for item in receipt.waypoint_path) == (0, 3)
    assert receipt.exclusions.causal == 1
    assert receipt.exclusions.operation == 1
    assert receipt.exclusions.policy == 1

    rejected_context = _context(admitted.verified_graph, hard_mask=0)
    start_rejected = plan_shortest_path(
        rejected_context, _request(rejected_context, candidates=(3,))
    )
    assert start_rejected.decision is TraceRankDecision.FALLBACK
    assert start_rejected.fault is TraceRankFault.POLICY_REJECTED
    assert start_rejected.examined_edges == 0


@pytest.mark.parametrize(
    "budget",
    (
        TraceRankPathBudget(max_steps=1),
        TraceRankPathBudget(max_expanded_nodes=1),
        TraceRankPathBudget(max_examined_edges=1),
    ),
)
def test_work_exhaustion_abstains_without_a_partial_path(
    budget: TraceRankPathBudget,
) -> None:
    admitted, _sources = _admit(
        (
            (Edge(1, 1, 1, 0, 0, 1), Edge(2, 1, 1, 0, 0, 1)),
            (Edge(3, 1, 1, 0, 0, 1),),
            (Edge(3, 1, 1, 0, 0, 1),),
            (),
        )
    )
    receipt = plan_shortest_path(
        admitted,
        _request(admitted, candidates=(3,), budget=budget),
    )
    assert receipt.decision is TraceRankDecision.ABSTAIN
    assert receipt.fault is TraceRankFault.BOUND_EXCEEDED
    assert receipt.waypoint_path == receipt.edge_path == ()


def test_uint64_path_overflow_fails_closed() -> None:
    admitted, _sources = _admit(
        (
            (Edge(1, 1, (1 << 64) - 1, 0, 0, 1),),
            (Edge(2, 1, 1, 0, 0, 1),),
            (),
        )
    )
    with pytest.raises(TraceRankPlannerError) as error:
        plan_shortest_path(admitted, _request(admitted, candidates=(2,)))
    assert error.value.fault is TraceRankFault.INTEGRITY_FAILURE


@pytest.mark.parametrize(
    "field_name",
    (
        "dataset_generation_set",
        "graph_map_epoch",
        "feature_schema",
        "rank_model_epoch",
        "sentinel_policy_epoch",
        "retrieval_policy_epoch",
        "context_policy_epoch",
        "shard_directory_epoch",
        "frontier_model_config_id",
    ),
)
def test_every_serving_epoch_component_is_matched_exactly(field_name: str) -> None:
    admitted, sources = _admit(((Edge(1, 1, 1, 0, 0, 1),), ()))
    request = _request(admitted, candidates=(1,))
    mismatched_epoch = replace(
        request.pinned_epoch, **{field_name: f"mismatch-{field_name}"}
    )
    with pytest.raises(TraceRankPlannerError) as mismatch:
        plan_shortest_path(admitted, replace(request, pinned_epoch=mismatched_epoch))
    assert mismatch.value.fault is TraceRankFault.EPOCH_MISMATCH


def test_verified_graph_and_controller_context_are_factory_only() -> None:
    graph, sources = _build_graph(((Edge(1, 1, 1, 0, 0, 1),), ()))
    with pytest.raises(TypeError):
        VerifiedPackedGraph()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        QualifiedPathPolicy()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        AdmittedPathContext()  # type: ignore[call-arg]

    verified = _verify(graph, sources)
    context = _context(verified)
    request_fields = {item.name for item in fields(TraceRankPathRequest)}
    assert "allowed_operations" not in request_fields
    assert "satisfied_hard_mask" not in request_fields

    with pytest.raises(TraceRankPlannerError) as policy:
        plan_shortest_path(
            context,
            replace(
                _request(context, candidates=(1,)),
                policy_root=_root("self-granted-policy"),
            ),
        )
    assert policy.value.fault is TraceRankFault.POLICY_REJECTED

    baseline = build_reference_baseline_manifest(
        verified, implementation_root="git:test-reference-planner"
    )
    epoch = _epoch(verified, baseline_rank_model_epoch(baseline))
    qualified = QualifiedPathPolicy.admit(
        verified,
        epoch,
        satisfied_hard_mask=1,
        allowed_operations=(1,),
        allowed_privacy_classes=(2,),
        allowed_license_classes=(1,),
        qualification_root=_root("controller-qualification"),
    )
    with pytest.raises(TraceRankPlannerError) as objective:
        AdmittedPathContext.admit(
            verified,
            epoch,
            qualified,
            replace(baseline, objective_contract_root=_root("foreign-objective")),
        )
    assert objective.value.fault is TraceRankFault.INTEGRITY_FAILURE

    wide_policy = QualifiedPathPolicy.admit(
        verified,
        epoch,
        satisfied_hard_mask=1,
        allowed_operations=(1,),
        allowed_privacy_classes=(2,),
        allowed_license_classes=(1,),
        qualification_root=_root("controller-qualification"),
        limits=TRACE_RANK_V2_LIMITS,
    )
    with pytest.raises(TraceRankPlannerError) as policy_limits:
        AdmittedPathContext.admit(verified, epoch, wide_policy, baseline)
    assert policy_limits.value.fault is TraceRankFault.EPOCH_MISMATCH


def test_unqualified_learned_delta_fails_graph_admission() -> None:
    admitted, sources = _admit(((Edge(1, 1, 1, 0, 0, 1),), ()))

    learned_graph = replace(
        admitted.verified_graph.graph,
        edges=(replace(admitted.verified_graph.graph.edges[0], learned_delta=1),),
    )
    with pytest.raises(TraceRankPlannerError) as learned:
        _verify(learned_graph, sources)
    assert learned.value.fault is TraceRankFault.POLICY_REJECTED


@pytest.mark.parametrize(
    ("privacy_classes", "license_classes", "exclusion"),
    (
        ((), (1,), "privacy"),
        ((2,), (), "license"),
    ),
)
def test_privacy_and_license_are_controller_qualified_hard_constraints(
    privacy_classes: tuple[int, ...],
    license_classes: tuple[int, ...],
    exclusion: str,
) -> None:
    admitted, _sources = _admit(((Edge(1, 1, 1, 0, 0, 1),), ()))
    restricted = _context(
        admitted.verified_graph,
        privacy_classes=privacy_classes,
        license_classes=license_classes,
    )
    receipt = plan_shortest_path(restricted, _request(restricted, candidates=(1,)))
    assert receipt.decision is TraceRankDecision.FALLBACK
    assert receipt.fault is TraceRankFault.POLICY_REJECTED
    assert getattr(receipt.exclusions, exclusion) == 1


def test_receipt_tampering_is_detected_by_exact_replay() -> None:
    admitted, _sources = _admit(((Edge(1, 1, 1, 0, 0, 1),), ()))
    request = _request(admitted, candidates=(1,))
    receipt = plan_shortest_path(admitted, request)
    tampered = replace(receipt, request_root=_root("another-request"))

    with pytest.raises(TraceRankPlannerError) as error:
        replay_path_receipt(admitted, request, tampered)
    assert error.value.fault is TraceRankFault.INTEGRITY_FAILURE

    loaded_tamper = TraceRankPathReceipt.from_bytes(tampered.canonical_bytes())
    with pytest.raises(TraceRankPlannerError):
        replay_path_receipt(admitted, request, loaded_tamper)

    with pytest.raises(TraceRankPlannerError) as whitespace:
        TraceRankPathReceipt.from_bytes(receipt.canonical_bytes() + b"\n")
    assert whitespace.value.fault is TraceRankFault.INTEGRITY_FAILURE

    missing = json.loads(receipt.canonical_bytes())
    del missing["graph_admission_root"]
    with pytest.raises(TraceRankPlannerError) as incomplete:
        TraceRankPathReceipt.from_bytes(
            json.dumps(missing, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
    assert incomplete.value.fault is TraceRankFault.INTEGRITY_FAILURE

    with pytest.raises(TraceRankPlannerError) as oversized:
        TraceRankPathReceipt.from_bytes(b" " * (PATH_MAX_RECEIPT_BYTES + 1))
    assert oversized.value.fault is TraceRankFault.BOUND_EXCEEDED


def test_request_and_policy_raw_collections_are_bounded_before_search() -> None:
    admitted, _sources = _admit(((Edge(1, 1, 1, 0, 0, 1),), ()))
    with pytest.raises(TraceRankPlannerError) as candidates:
        TraceRankPathRequest(
            pinned_epoch=admitted.expected_epoch,
            path_context_root=admitted.context_root,
            policy_root=admitted.policy.policy_root,
            start_waypoint=0,
            candidate_waypoints=tuple(range(33)),
        )
    assert candidates.value.fault is TraceRankFault.BOUND_EXCEEDED

    with pytest.raises(TraceRankPlannerError) as operations:
        QualifiedPathPolicy.admit(
            admitted.verified_graph,
            admitted.expected_epoch,
            satisfied_hard_mask=1,
            allowed_operations=tuple(range(1, 2_050)),
            allowed_privacy_classes=(2,),
            allowed_license_classes=(1,),
            qualification_root=_root("oversized-controller-policy"),
        )
    assert operations.value.fault is TraceRankFault.BOUND_EXCEEDED


def test_dijkstra_matches_independent_exhaustive_oracle() -> None:
    randomizer = random.Random(381)
    for case in range(40):
        rows: list[tuple[Edge, ...]] = []
        for source in range(6):
            edges: list[Edge] = []
            for destination in range(source + 1, 6):
                if randomizer.randrange(3) == 0:
                    continue
                edges.append(
                    Edge(
                        destination,
                        randomizer.choice((1, 2)),
                        randomizer.randrange(8),
                        0,
                        randomizer.randrange(5),
                        randomizer.choice((1, 3)),
                    )
                )
            rows.append(tuple(edges))
        admitted, _sources = _admit(tuple(rows))
        request = _request(
            admitted,
            candidates=tuple(sorted(randomizer.sample((3, 4, 5), 2))),
        )
        expected = _reference_best_path(admitted, request)
        actual = plan_shortest_path(admitted, request)
        if expected is None:
            assert actual.decision is TraceRankDecision.FALLBACK, case
        else:
            assert actual.decision is TraceRankDecision.RANKED, case
            assert tuple(item.waypoint_index for item in actual.waypoint_path) == expected[0]
            assert tuple(item.edge_index for item in actual.edge_path) == expected[1]
            assert actual.total_cost == expected[2]


def test_published_csv_lease_is_the_only_graph_source_adapter(tmp_path: Path) -> None:
    source, _offsets = _row_source(4)
    store = AtomicGenerationStore(tmp_path / "authority")
    candidate = build_csv_generation_candidate(
        store,
        namespace="dataset:planner-source",
        source=source,
        closure_root=bytes_root(b"planner-closure"),
        evidence_root=bytes_root(b"planner-evidence"),
        chunk_bytes=5,
        oracle_block_bytes=2,
    )
    publish_csv_generation(store, candidate, expected_head_root=None)

    lease = open_csv_generation(store, "dataset:planner-source")
    evidence = bind_csv_generation_source(
        lease, expected_namespace="dataset:planner-source"
    )
    assert evidence.source_binding.generation_root == lease.generation_root
    assert evidence.source_binding.source_bytes == source
    assert evidence.source_binding.row_offsets == lease.row_offsets + (len(source),)
    assert evidence.csv_row_offsets_root == lease.binding.row_offsets_root
    assert evidence.source_binding.row_offsets_root != evidence.csv_row_offsets_root
    assert evidence.graph_row_offsets_root == evidence.source_binding.row_offsets_root
    assert evidence.canonical_dict()["bridge_root"] == evidence.bridge_root

    second_pin = open_csv_generation(store, "dataset:planner-source")
    repeated = bind_csv_generation_source(
        second_pin, expected_namespace="dataset:planner-source"
    )
    assert repeated.bridge_root == evidence.bridge_root
    second_pin.close()

    with pytest.raises(Exception):
        bind_csv_generation_source(lease, expected_namespace="dataset:other")
    with pytest.raises(Exception):
        bind_csv_generation_sources(
            (lease,),
            expected_namespace="dataset:planner-source",
            max_generations=0,
        )
    with pytest.raises(TypeError):
        VerifiedCSVGraphBridge()  # type: ignore[call-arg]

    graph, _sources = _build_graph(
        (
            (Edge(1, 1, 2, 0, 0, 1),),
            (Edge(2, 1, 2, 0, 0, 1),),
            (Edge(3, 1, 2, 0, 0, 1),),
            (),
        ),
        source_binding=evidence.source_binding,
    )
    verified = admit_csv_packed_graph(
        graph,
        (evidence,),
        expected_namespace="dataset:planner-source",
        edge_catalog_root=_root("qualified-edge-catalog"),
    )
    admitted = _context(verified)
    request = _request(admitted, candidates=(3,))
    receipt = plan_shortest_path(admitted, request)
    assert receipt.decision is TraceRankDecision.RANKED
    assert receipt.waypoint_path[0].generation_root == candidate.generation_root
    assert replay_path_receipt(admitted, request, receipt) == receipt

    with pytest.raises(Exception):
        bind_csv_generation_sources(
            (lease, lease), expected_namespace="dataset:planner-source"
        )
    lease.close()
    with pytest.raises(Exception):
        admit_csv_packed_graph(
            graph,
            (evidence,),
            expected_namespace="dataset:planner-source",
            edge_catalog_root=_root("qualified-edge-catalog"),
        )
    with pytest.raises(Exception):
        bind_csv_generation_source(
            lease, expected_namespace="dataset:planner-source"
        )


def test_empty_csv_bridge_has_one_terminal_boundary_and_requires_its_pin(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "empty-authority")
    candidate = build_csv_generation_candidate(
        store,
        namespace="dataset:empty-planner-source",
        source=b"",
        closure_root=bytes_root(b"empty-planner-closure"),
        evidence_root=bytes_root(b"empty-planner-evidence"),
        chunk_bytes=4,
    )
    publish_csv_generation(store, candidate, expected_head_root=None)
    lease = open_csv_generation(store, "dataset:empty-planner-source")
    bridge = bind_csv_generation_source(
        lease, expected_namespace="dataset:empty-planner-source"
    )
    assert bridge.source_binding.source_bytes == b""
    assert bridge.source_binding.row_offsets == (0,)
    assert bridge.source_binding.row_count == 0
    bridge.require_open_lease()

    lease.close()
    with pytest.raises(Exception):
        bridge.require_open_lease()


def test_reference_planner_has_no_storage_execution_or_sentinel_authority() -> None:
    source = (ROOT / "src" / "staqtapp_tds" / "trace_rank" / "planner.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert not any(
        forbidden in module
        for forbidden in (
            "pathlib",
            "subprocess",
            "socket",
            "requests",
            "generation_store",
        )
        for module in imported_modules
    )
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert function_names.isdisjoint(
        {"execute", "commit", "activate", "promote", "train"}
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "open"
        for node in ast.walk(tree)
    )

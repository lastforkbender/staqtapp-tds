"""Bounded deterministic shortest-path reference for Trace Rank ABI v2.

The search consumes only a factory-admitted packed graph, a controller-qualified
policy, and an exactly matched composite :class:`ServingEpochIdentity`.  It
performs no source materialization, storage write, telemetry publication,
training, model inference, network I/O, promotion, or activation.  This Python
implementation is an off-path oracle; it does not claim the native hot-path
scratch, allocation, lock, or syscall envelope.

Costs are unsigned fixed-point integers.  Each edge is evaluated as::

    max(0, base_cost + learned_delta - evidence_gain)

Every addition is checked against uint64.  Hard policy, privacy, license, and
operation checks remove illegal edges before the deterministic Dijkstra
search.  Equal paths are ordered by cost, step count, waypoint sequence,
operation sequence, and packed edge indices.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from staqtapp_tds.trace_rank.contract import (
    TRACE_RANK_V2_AUTHORITY,
    TRACE_RANK_V2_LIMITS,
    TRACE_RANK_V2_VERTICAL_SLICE_LIMITS,
    ServingEpochIdentity,
    TraceRankBaselineManifest,
    TraceRankDecision,
    TraceRankFault,
    TraceRankLimits,
)
from staqtapp_tds.trace_rank.graph import (
    DEFAULT_PACKED_GRAPH_LIMITS,
    PACKED_GRAPH_FORMAT_ID,
    PACKED_GRAPH_FORMAT_VERSION,
    Edge,
    ImmutableSourceBinding,
    PackedGraphLimits,
    PackedWaypointGraph,
)

PATH_PLANNER_CONTRACT_ID = "tds-fixed-point-dijkstra-v1"
PATH_COST_CONTRACT_ID = "u64-base-plus-u32-delta-minus-bounded-gain-v1"
PATH_TIE_BREAK_ID = "cost-steps-waypoints-operations-packed-edges-v1"
PATH_RECEIPT_FORMAT_ID = "tds-trace-path-receipt-v1"
PATH_DETERMINISTIC_FALLBACK_ID = "tds-phase5-deterministic-graph-fallback-v1"
PATH_MAX_RECEIPT_BYTES = 256 * 1024

_UINT16_MAX = (1 << 16) - 1
_UINT64_MAX = (1 << 64) - 1
_ROOT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX_ROOT_RE = re.compile(r"^[0-9a-f]{64}$")
_ROOT_DOMAIN_PREFIX = b"STAQTAPP-TDS\x00TRACE-RANK\x00PATH-V1\x00"


class TraceRankPlannerError(ValueError):
    """A fail-closed planner admission or arithmetic error."""

    def __init__(
        self,
        message: str,
        *,
        fault: TraceRankFault = TraceRankFault.INVALID_INPUT,
    ) -> None:
        super().__init__(message)
        self.fault = fault


def _require_int(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TraceRankPlannerError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise TraceRankPlannerError(
            f"{name} must be between {minimum} and {maximum}",
            fault=TraceRankFault.BOUND_EXCEEDED,
        )
    return value


def _require_root(name: str, value: str) -> str:
    if not isinstance(value, str) or not _ROOT_RE.fullmatch(value):
        raise TraceRankPlannerError(
            f"{name} must be a canonical sha256 root",
            fault=TraceRankFault.INTEGRITY_FAILURE,
        )
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _canonical_root(domain: str, value: Mapping[str, Any]) -> str:
    material = (
        _ROOT_DOMAIN_PREFIX
        + domain.encode("ascii")
        + b"\x00"
        + _canonical_bytes(value)
    )
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _require_mapping_fields(
    value: object,
    expected: frozenset[str],
    description: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise TraceRankPlannerError(
            f"{description} fields are not canonical",
            fault=TraceRankFault.INTEGRITY_FAILURE,
        )
    return value


PATH_OBJECTIVE_CONTRACT_ROOT = _canonical_root(
    "path-objective-contract",
    {
        "arithmetic": "checked-u64",
        "cost_contract_id": PATH_COST_CONTRACT_ID,
        "evidence_credit": "min-base-plus-delta-evidence-gain",
        "edge_cost": "max-zero-base-plus-delta-minus-evidence-gain",
        "learned_delta": "must-be-zero-in-phase5-reference",
    },
)
PATH_BASELINE_CONFIGURATION_ROOT = _canonical_root(
    "path-baseline-configuration",
    {
        "causal_rule": "destination-sequence-strictly-increases",
        "decision_contract": "ranked-fallback-abstain-v1",
        "graph_format_id": PACKED_GRAPH_FORMAT_ID,
        "graph_format_version": PACKED_GRAPH_FORMAT_VERSION,
        "path_planner_contract_id": PATH_PLANNER_CONTRACT_ID,
        "policy_rule": "controller-qualified-closed-sets-v1",
        "receipt_format_id": PATH_RECEIPT_FORMAT_ID,
        "tie_break_id": PATH_TIE_BREAK_ID,
    },
)


def baseline_rank_model_epoch(manifest: TraceRankBaselineManifest) -> str:
    """Return the ServingEpoch identity for one admitted baseline manifest."""

    if not isinstance(manifest, TraceRankBaselineManifest):
        raise TraceRankPlannerError("manifest must be TraceRankBaselineManifest")
    return "sha256:" + manifest.manifest_root


def build_reference_baseline_manifest(
    verified_graph: "VerifiedPackedGraph",
    *,
    implementation_root: str,
) -> TraceRankBaselineManifest:
    """Build the replay manifest; callers supply the source/binary identity."""

    if not isinstance(verified_graph, VerifiedPackedGraph):
        raise TraceRankPlannerError("verified_graph must be VerifiedPackedGraph")
    return TraceRankBaselineManifest(
        implementation_root=implementation_root,
        corpus_root=verified_graph.dataset_generation_set_root,
        objective_contract_root=PATH_OBJECTIVE_CONTRACT_ROOT,
        feature_schema_root=verified_graph.feature_schema_root,
        baseline_configuration_root=PATH_BASELINE_CONFIGURATION_ROOT,
        deterministic_fallback_id=PATH_DETERMINISTIC_FALLBACK_ID,
        baseline_engine_id=PATH_PLANNER_CONTRACT_ID,
    )


def _checked_add(name: str, left: int, right: int) -> int:
    if right > _UINT64_MAX - left:
        raise TraceRankPlannerError(
            f"{name} overflows uint64",
            fault=TraceRankFault.INTEGRITY_FAILURE,
        )
    return left + right


def _edge_cost(edge: Edge) -> tuple[int, int]:
    subtotal = _checked_add("edge base plus learned cost", edge.base_cost, edge.learned_delta)
    credited_gain = min(subtotal, edge.evidence_gain)
    return subtotal - credited_gain, credited_gain


@dataclass(frozen=True, slots=True, init=False)
class VerifiedPackedGraph:
    """Factory-only proof of canonical bytes and exact-source admission."""

    graph: PackedWaypointGraph
    packed_bytes: bytes
    source_bindings: tuple[ImmutableSourceBinding, ...]
    source_evidence_roots: tuple[str, ...]
    edge_catalog_root: str
    graph_root: str
    dataset_generation_set_root: str
    feature_schema_root: str
    graph_admission_root: str

    def __init__(self) -> None:
        raise TypeError("use VerifiedPackedGraph.from_bytes or .from_graph")

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        source_bindings: tuple[ImmutableSourceBinding, ...],
        *,
        source_evidence_roots: tuple[str, ...],
        edge_catalog_root: str,
        limits: PackedGraphLimits = DEFAULT_PACKED_GRAPH_LIMITS,
    ) -> "VerifiedPackedGraph":
        """Decode canonical bytes and derive every graph identity internally."""

        if type(payload) is not bytes:
            raise TraceRankPlannerError("packed graph payload must be exact bytes")
        if not isinstance(limits, PackedGraphLimits):
            raise TraceRankPlannerError("limits must be PackedGraphLimits")
        if not isinstance(source_bindings, tuple):
            raise TraceRankPlannerError("source_bindings must be an immutable tuple")
        if not isinstance(source_evidence_roots, tuple):
            raise TraceRankPlannerError(
                "source_evidence_roots must be an immutable tuple"
            )
        if len(source_bindings) > limits.max_generations:
            raise TraceRankPlannerError(
                "source binding count exceeds the packed graph limit",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        if len(source_evidence_roots) != len(source_bindings):
            raise TraceRankPlannerError(
                "every graph source requires one admission evidence root",
                fault=TraceRankFault.INTEGRITY_FAILURE,
            )
        for index, root in enumerate(source_evidence_roots):
            _require_root(f"source_evidence_roots[{index}]", root)
        _require_root("edge_catalog_root", edge_catalog_root)
        graph = PackedWaypointGraph.from_bytes(
            payload, source_bindings, limits=limits
        )
        if graph.to_bytes(source_bindings, limits=limits) != payload:
            raise TraceRankPlannerError(
                "packed graph failed exact decode/re-encode admission",
                fault=TraceRankFault.INTEGRITY_FAILURE,
            )
        if any(edge.learned_delta != 0 for edge in graph.edges):
            raise TraceRankPlannerError(
                "the Phase-5 reference rejects learned edge deltas",
                fault=TraceRankFault.POLICY_REJECTED,
            )
        graph_root = "sha256:" + hashlib.sha256(payload).hexdigest()
        generation_roots = [item.generation_root for item in graph.generations]
        dataset_root = _canonical_root(
            "dataset-generation-set", {"generation_roots": generation_roots}
        )
        packed_limits = {
            "max_edges": limits.max_edges,
            "max_feature_blocks": limits.max_feature_blocks,
            "max_generations": limits.max_generations,
            "max_graph_bytes": limits.max_graph_bytes,
            "max_provenance_records": limits.max_provenance_records,
            "max_waypoints": limits.max_waypoints,
        }
        admission_root = _canonical_root(
            "packed-graph-admission",
            {
                "dataset_generation_set_root": dataset_root,
                "edge_catalog_root": edge_catalog_root,
                "feature_schema_root": graph.feature_schema_root,
                "graph_root": graph_root,
                "packed_limits": packed_limits,
                "server_namespace_root": graph.server_namespace_root,
                "source_evidence_roots": list(source_evidence_roots),
            },
        )
        result = object.__new__(cls)
        values = {
            "graph": graph,
            "packed_bytes": payload,
            "source_bindings": source_bindings,
            "source_evidence_roots": source_evidence_roots,
            "edge_catalog_root": edge_catalog_root,
            "graph_root": graph_root,
            "dataset_generation_set_root": dataset_root,
            "feature_schema_root": graph.feature_schema_root,
            "graph_admission_root": admission_root,
        }
        for name, value in values.items():
            object.__setattr__(result, name, value)
        return result

    @classmethod
    def from_graph(
        cls,
        graph: PackedWaypointGraph,
        source_bindings: tuple[ImmutableSourceBinding, ...],
        *,
        source_evidence_roots: tuple[str, ...],
        edge_catalog_root: str,
        limits: PackedGraphLimits = DEFAULT_PACKED_GRAPH_LIMITS,
    ) -> "VerifiedPackedGraph":
        """Serialize a builder graph and re-admit it through the byte decoder."""

        if not isinstance(graph, PackedWaypointGraph):
            raise TraceRankPlannerError("graph must be a PackedWaypointGraph")
        payload = graph.to_bytes(source_bindings, limits=limits)
        return cls.from_bytes(
            payload,
            source_bindings,
            source_evidence_roots=source_evidence_roots,
            edge_catalog_root=edge_catalog_root,
            limits=limits,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": PATH_PLANNER_CONTRACT_ID,
            "dataset_generation_set_root": self.dataset_generation_set_root,
            "feature_schema_root": self.feature_schema_root,
            "graph_admission_root": self.graph_admission_root,
            "graph_root": self.graph_root,
            "server_namespace_root": self.graph.server_namespace_root,
        }


@dataclass(frozen=True, slots=True)
class TraceRankPathBudget:
    """Per-request work limits that may only narrow the admitted ABI limits."""

    max_expanded_nodes: int = TRACE_RANK_V2_VERTICAL_SLICE_LIMITS.max_expanded_nodes
    max_examined_edges: int = TRACE_RANK_V2_VERTICAL_SLICE_LIMITS.max_edges
    max_steps: int = TRACE_RANK_V2_VERTICAL_SLICE_LIMITS.max_steps
    max_total_cost: int = _UINT64_MAX

    def __post_init__(self) -> None:
        _require_int("max_expanded_nodes", self.max_expanded_nodes, 1, _UINT64_MAX)
        _require_int("max_examined_edges", self.max_examined_edges, 1, _UINT64_MAX)
        _require_int("max_steps", self.max_steps, 1, _UINT64_MAX)
        _require_int("max_total_cost", self.max_total_cost, 0, _UINT64_MAX)

    def validate_against(self, limits: TraceRankLimits) -> None:
        if not isinstance(limits, TraceRankLimits):
            raise TraceRankPlannerError("limits must be TraceRankLimits")
        if self.max_expanded_nodes > limits.max_expanded_nodes:
            raise TraceRankPlannerError(
                "path expanded-node budget exceeds the qualified limit",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        if self.max_examined_edges > limits.max_edges:
            raise TraceRankPlannerError(
                "path edge budget exceeds the qualified limit",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        if self.max_steps > limits.max_steps:
            raise TraceRankPlannerError(
                "path step budget exceeds the qualified limit",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )

    def canonical_dict(self) -> dict[str, int]:
        return {
            "max_examined_edges": self.max_examined_edges,
            "max_expanded_nodes": self.max_expanded_nodes,
            "max_steps": self.max_steps,
            "max_total_cost": self.max_total_cost,
        }


DEFAULT_PATH_BUDGET = TraceRankPathBudget()


def _canonical_int_tuple(
    name: str,
    values: tuple[int, ...],
    *,
    minimum: int,
    maximum: int,
) -> tuple[int, ...]:
    if not isinstance(values, tuple):
        raise TraceRankPlannerError(f"{name} must be an immutable tuple")
    for index, value in enumerate(values):
        _require_int(f"{name}[{index}]", value, minimum, maximum)
    if values != tuple(sorted(set(values))):
        raise TraceRankPlannerError(f"{name} must be unique and in canonical order")
    return values


@dataclass(frozen=True, slots=True, init=False)
class QualifiedPathPolicy:
    """Controller-qualified closed policy sets; never request assertions."""

    graph_admission_root: str
    serving_epoch_root: str
    server_namespace_root: str
    retrieval_policy_epoch: str
    context_policy_epoch: str
    satisfied_hard_mask: int
    allowed_operations: tuple[int, ...]
    allowed_privacy_classes: tuple[int, ...]
    allowed_license_classes: tuple[int, ...]
    qualification_root: str
    limits_root: str
    policy_root: str

    def __init__(self) -> None:
        raise TypeError("use QualifiedPathPolicy.admit")

    @classmethod
    def admit(
        cls,
        verified_graph: VerifiedPackedGraph,
        expected_epoch: ServingEpochIdentity,
        *,
        satisfied_hard_mask: int,
        allowed_operations: tuple[int, ...],
        allowed_privacy_classes: tuple[int, ...],
        allowed_license_classes: tuple[int, ...],
        qualification_root: str,
        limits: TraceRankLimits = TRACE_RANK_V2_VERTICAL_SLICE_LIMITS,
    ) -> "QualifiedPathPolicy":
        """Bind controller output to one graph and full ServingEpoch."""

        if not isinstance(verified_graph, VerifiedPackedGraph):
            raise TraceRankPlannerError("verified_graph must be VerifiedPackedGraph")
        if not isinstance(expected_epoch, ServingEpochIdentity):
            raise TraceRankPlannerError("expected_epoch must be ServingEpochIdentity")
        if not isinstance(limits, TraceRankLimits):
            raise TraceRankPlannerError("limits must be TraceRankLimits")
        hard_mask = _require_int(
            "satisfied_hard_mask", satisfied_hard_mask, 0, _UINT64_MAX
        )
        if hard_mask & ~verified_graph.graph.hard_mask_universe:
            raise TraceRankPlannerError(
                "qualified hard mask exceeds the graph universe",
                fault=TraceRankFault.POLICY_REJECTED,
            )
        for name, value in (
            ("allowed_operations", allowed_operations),
            ("allowed_privacy_classes", allowed_privacy_classes),
            ("allowed_license_classes", allowed_license_classes),
        ):
            if not isinstance(value, tuple):
                raise TraceRankPlannerError(f"{name} must be an immutable tuple")
        if len(allowed_operations) > limits.max_edges:
            raise TraceRankPlannerError(
                "qualified operation set exceeds the edge limit",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        if len(allowed_privacy_classes) > _UINT16_MAX + 1:
            raise TraceRankPlannerError(
                "qualified privacy set exceeds its closed class space",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        if len(allowed_license_classes) > _UINT16_MAX + 1:
            raise TraceRankPlannerError(
                "qualified license set exceeds its closed class space",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        operations = _canonical_int_tuple(
            "allowed_operations",
            allowed_operations,
            minimum=1,
            maximum=_UINT16_MAX,
        )
        privacy = _canonical_int_tuple(
            "allowed_privacy_classes",
            allowed_privacy_classes,
            minimum=0,
            maximum=_UINT16_MAX,
        )
        licenses = _canonical_int_tuple(
            "allowed_license_classes",
            allowed_license_classes,
            minimum=0,
            maximum=_UINT16_MAX,
        )
        _require_root("qualification_root", qualification_root)
        values: dict[str, Any] = {
            "allowed_license_classes": list(licenses),
            "allowed_operations": list(operations),
            "allowed_privacy_classes": list(privacy),
            "context_policy_epoch": expected_epoch.context_policy_epoch,
            "graph_admission_root": verified_graph.graph_admission_root,
            "limits_root": limits.limits_root,
            "qualification_root": qualification_root,
            "retrieval_policy_epoch": expected_epoch.retrieval_policy_epoch,
            "satisfied_hard_mask": hard_mask,
            "server_namespace_root": verified_graph.graph.server_namespace_root,
            "serving_epoch_root": expected_epoch.epoch_root,
        }
        policy_root = _canonical_root("qualified-path-policy", values)
        result = object.__new__(cls)
        values["allowed_operations"] = operations
        values["allowed_privacy_classes"] = privacy
        values["allowed_license_classes"] = licenses
        values["policy_root"] = policy_root
        for name, value in values.items():
            object.__setattr__(result, name, value)
        return result

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "allowed_license_classes": list(self.allowed_license_classes),
            "allowed_operations": list(self.allowed_operations),
            "allowed_privacy_classes": list(self.allowed_privacy_classes),
            "context_policy_epoch": self.context_policy_epoch,
            "graph_admission_root": self.graph_admission_root,
            "limits_root": self.limits_root,
            "policy_root": self.policy_root,
            "qualification_root": self.qualification_root,
            "retrieval_policy_epoch": self.retrieval_policy_epoch,
            "satisfied_hard_mask": self.satisfied_hard_mask,
            "server_namespace_root": self.server_namespace_root,
            "serving_epoch_root": self.serving_epoch_root,
        }


@dataclass(frozen=True, slots=True, init=False)
class AdmittedPathContext:
    """Factory-only complete trust input for the reference path oracle."""

    verified_graph: VerifiedPackedGraph
    expected_epoch: ServingEpochIdentity
    policy: QualifiedPathPolicy
    limits: TraceRankLimits
    baseline: TraceRankBaselineManifest
    context_root: str

    def __init__(self) -> None:
        raise TypeError("use AdmittedPathContext.admit")

    @classmethod
    def admit(
        cls,
        verified_graph: VerifiedPackedGraph,
        expected_epoch: ServingEpochIdentity,
        policy: QualifiedPathPolicy,
        baseline: TraceRankBaselineManifest,
        *,
        limits: TraceRankLimits = TRACE_RANK_V2_VERTICAL_SLICE_LIMITS,
    ) -> "AdmittedPathContext":
        if not isinstance(verified_graph, VerifiedPackedGraph):
            raise TraceRankPlannerError("verified_graph must be VerifiedPackedGraph")
        if not isinstance(expected_epoch, ServingEpochIdentity):
            raise TraceRankPlannerError("expected_epoch must be ServingEpochIdentity")
        if not isinstance(policy, QualifiedPathPolicy):
            raise TraceRankPlannerError("policy must be QualifiedPathPolicy")
        if not isinstance(baseline, TraceRankBaselineManifest):
            raise TraceRankPlannerError("baseline must be TraceRankBaselineManifest")
        if not isinstance(limits, TraceRankLimits):
            raise TraceRankPlannerError("limits must be TraceRankLimits")

        expected_graph_epoch = (
            verified_graph.dataset_generation_set_root,
            verified_graph.graph_root,
            verified_graph.feature_schema_root,
        )
        actual_graph_epoch = (
            expected_epoch.dataset_generation_set,
            expected_epoch.graph_map_epoch,
            expected_epoch.feature_schema,
        )
        if actual_graph_epoch != expected_graph_epoch:
            raise TraceRankPlannerError(
                "admitted ServingEpoch does not bind the verified graph",
                fault=TraceRankFault.EPOCH_MISMATCH,
            )
        expected_baseline = (
            verified_graph.dataset_generation_set_root,
            PATH_OBJECTIVE_CONTRACT_ROOT,
            verified_graph.feature_schema_root,
            PATH_BASELINE_CONFIGURATION_ROOT,
            PATH_DETERMINISTIC_FALLBACK_ID,
            PATH_PLANNER_CONTRACT_ID,
        )
        actual_baseline = (
            baseline.corpus_root,
            baseline.objective_contract_root,
            baseline.feature_schema_root,
            baseline.baseline_configuration_root,
            baseline.deterministic_fallback_id,
            baseline.baseline_engine_id,
        )
        if actual_baseline != expected_baseline:
            raise TraceRankPlannerError(
                "baseline manifest does not bind the admitted path objective",
                fault=TraceRankFault.INTEGRITY_FAILURE,
            )
        if expected_epoch.rank_model_epoch != baseline_rank_model_epoch(baseline):
            raise TraceRankPlannerError(
                "ServingEpoch rank model does not bind the baseline manifest",
                fault=TraceRankFault.EPOCH_MISMATCH,
            )
        expected_policy = (
            verified_graph.graph_admission_root,
            expected_epoch.epoch_root,
            verified_graph.graph.server_namespace_root,
            expected_epoch.retrieval_policy_epoch,
            expected_epoch.context_policy_epoch,
            limits.limits_root,
        )
        actual_policy = (
            policy.graph_admission_root,
            policy.serving_epoch_root,
            policy.server_namespace_root,
            policy.retrieval_policy_epoch,
            policy.context_policy_epoch,
            policy.limits_root,
        )
        if actual_policy != expected_policy:
            raise TraceRankPlannerError(
                "qualified path policy is not bound to the admitted context",
                fault=TraceRankFault.EPOCH_MISMATCH,
            )
        context_root = _canonical_root(
            "admitted-path-context",
            {
                "authority_root": TRACE_RANK_V2_AUTHORITY.authority_root,
                "baseline_manifest_root": baseline.manifest_root,
                "graph_admission_root": verified_graph.graph_admission_root,
                "limits_root": limits.limits_root,
                "policy_root": policy.policy_root,
                "serving_epoch_root": expected_epoch.epoch_root,
            },
        )
        result = object.__new__(cls)
        for name, value in {
            "verified_graph": verified_graph,
            "expected_epoch": expected_epoch,
            "policy": policy,
            "limits": limits,
            "baseline": baseline,
            "context_root": context_root,
        }.items():
            object.__setattr__(result, name, value)
        return result


@dataclass(frozen=True, slots=True)
class TraceRankPathRequest:
    """One immutable, policy-bounded path request."""

    pinned_epoch: ServingEpochIdentity
    path_context_root: str
    policy_root: str
    start_waypoint: int
    candidate_waypoints: tuple[int, ...]
    budget: TraceRankPathBudget = DEFAULT_PATH_BUDGET

    def __post_init__(self) -> None:
        if not isinstance(self.pinned_epoch, ServingEpochIdentity):
            raise TraceRankPlannerError(
                "pinned_epoch must be a ServingEpochIdentity",
                fault=TraceRankFault.EPOCH_MISMATCH,
            )
        _require_root("path_context_root", self.path_context_root)
        _require_root("policy_root", self.policy_root)
        _require_int("start_waypoint", self.start_waypoint, 0, _UINT64_MAX)
        if not isinstance(self.candidate_waypoints, tuple):
            raise TraceRankPlannerError("candidate_waypoints must be an immutable tuple")
        if not self.candidate_waypoints:
            raise TraceRankPlannerError("candidate_waypoints must not be empty")
        if len(self.candidate_waypoints) > TRACE_RANK_V2_LIMITS.max_candidates:
            raise TraceRankPlannerError(
                "candidate_waypoints exceeds the ABI hard limit",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        for index, candidate in enumerate(self.candidate_waypoints):
            _require_int(f"candidate_waypoints[{index}]", candidate, 0, _UINT64_MAX)
        if self.candidate_waypoints != tuple(sorted(set(self.candidate_waypoints))):
            raise TraceRankPlannerError(
                "candidate_waypoints must be unique and in canonical order"
            )
        if not isinstance(self.budget, TraceRankPathBudget):
            raise TraceRankPlannerError("budget must be TraceRankPathBudget")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget.canonical_dict(),
            "candidate_waypoints": list(self.candidate_waypoints),
            "contract_id": PATH_PLANNER_CONTRACT_ID,
            "path_context_root": self.path_context_root,
            "pinned_epoch": self.pinned_epoch.canonical_dict(),
            "policy_root": self.policy_root,
            "start_waypoint": self.start_waypoint,
        }

    @property
    def request_root(self) -> str:
        return _canonical_root("path-request", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class PathExclusionCounts:
    """Content-free counts for every mechanical edge exclusion class."""

    policy: int = 0
    operation: int = 0
    privacy: int = 0
    license: int = 0
    causal: int = 0
    step_budget: int = 0
    cost_budget: int = 0

    def __post_init__(self) -> None:
        for name in (
            "policy",
            "operation",
            "privacy",
            "license",
            "causal",
            "step_budget",
            "cost_budget",
        ):
            _require_int(name, getattr(self, name), 0, _UINT64_MAX)

    def canonical_dict(self) -> dict[str, int]:
        return {
            "causal": self.causal,
            "cost_budget": self.cost_budget,
            "license": self.license,
            "operation": self.operation,
            "policy": self.policy,
            "privacy": self.privacy,
            "step_budget": self.step_budget,
        }


@dataclass(frozen=True, slots=True)
class PathWaypointReceipt:
    """Exact immutable locator for one selected waypoint."""

    waypoint_index: int
    generation_root: str
    provenance_root: str
    causal_sequence: int
    byte_start: int
    byte_end: int
    row_start: int
    row_end: int
    privacy_class: int
    license_class: int
    policy_mask: int

    def __post_init__(self) -> None:
        _require_int("waypoint_index", self.waypoint_index, 0, _UINT64_MAX)
        _require_root("generation_root", self.generation_root)
        _require_root("provenance_root", self.provenance_root)
        _require_int("causal_sequence", self.causal_sequence, 0, _UINT64_MAX)
        _require_int("byte_start", self.byte_start, 0, _UINT64_MAX)
        _require_int("byte_end", self.byte_end, 0, _UINT64_MAX)
        _require_int("row_start", self.row_start, 0, _UINT64_MAX)
        _require_int("row_end", self.row_end, 0, _UINT64_MAX)
        _require_int("privacy_class", self.privacy_class, 0, _UINT16_MAX)
        _require_int("license_class", self.license_class, 0, _UINT16_MAX)
        _require_int("policy_mask", self.policy_mask, 0, _UINT64_MAX)
        if self.byte_start >= self.byte_end or self.row_start >= self.row_end:
            raise TraceRankPlannerError("receipt waypoint spans must be non-empty")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "byte_end": self.byte_end,
            "byte_start": self.byte_start,
            "causal_sequence": self.causal_sequence,
            "generation_root": self.generation_root,
            "license_class": self.license_class,
            "policy_mask": self.policy_mask,
            "privacy_class": self.privacy_class,
            "provenance_root": self.provenance_root,
            "row_end": self.row_end,
            "row_start": self.row_start,
            "waypoint_index": self.waypoint_index,
        }


@dataclass(frozen=True, slots=True)
class PathEdgeReceipt:
    """Fixed-point cost and hard-policy evidence for one selected edge."""

    edge_index: int
    source_index: int
    destination_index: int
    operation: int
    base_cost: int
    learned_delta: int
    evidence_gain: int
    credited_evidence_gain: int
    effective_cost: int
    hard_eligibility_mask: int

    def __post_init__(self) -> None:
        _require_int("edge_index", self.edge_index, 0, _UINT64_MAX)
        _require_int("source_index", self.source_index, 0, _UINT64_MAX)
        _require_int("destination_index", self.destination_index, 0, _UINT64_MAX)
        _require_int("operation", self.operation, 1, _UINT16_MAX)
        _require_int("base_cost", self.base_cost, 0, _UINT64_MAX)
        _require_int("learned_delta", self.learned_delta, 0, (1 << 32) - 1)
        _require_int("evidence_gain", self.evidence_gain, 0, (1 << 32) - 1)
        _require_int(
            "credited_evidence_gain", self.credited_evidence_gain, 0, _UINT64_MAX
        )
        _require_int("effective_cost", self.effective_cost, 0, _UINT64_MAX)
        _require_int("hard_eligibility_mask", self.hard_eligibility_mask, 0, _UINT64_MAX)
        subtotal = _checked_add(
            "receipt edge base plus learned cost", self.base_cost, self.learned_delta
        )
        if self.credited_evidence_gain != min(subtotal, self.evidence_gain):
            raise TraceRankPlannerError(
                "receipt credited evidence gain is not canonical",
                fault=TraceRankFault.INTEGRITY_FAILURE,
            )
        if self.effective_cost != subtotal - self.credited_evidence_gain:
            raise TraceRankPlannerError(
                "receipt edge effective cost is inconsistent",
                fault=TraceRankFault.INTEGRITY_FAILURE,
            )

    def canonical_dict(self) -> dict[str, int]:
        return {
            "base_cost": self.base_cost,
            "credited_evidence_gain": self.credited_evidence_gain,
            "destination_index": self.destination_index,
            "edge_index": self.edge_index,
            "effective_cost": self.effective_cost,
            "evidence_gain": self.evidence_gain,
            "hard_eligibility_mask": self.hard_eligibility_mask,
            "learned_delta": self.learned_delta,
            "operation": self.operation,
            "source_index": self.source_index,
        }


@dataclass(frozen=True, slots=True)
class TraceRankPathReceipt:
    """Canonical, content-free and replayable result of one path request."""

    decision: TraceRankDecision
    fault: TraceRankFault
    request_root: str
    serving_epoch_root: str
    graph_root: str
    dataset_generation_set_root: str
    feature_schema_root: str
    server_namespace_root: str
    graph_admission_root: str
    path_context_root: str
    policy_root: str
    limits_root: str
    baseline_manifest_root: str
    authority_root: str
    waypoint_path: tuple[PathWaypointReceipt, ...]
    edge_path: tuple[PathEdgeReceipt, ...]
    total_base_cost: int
    total_learned_delta: int
    total_evidence_gain: int
    total_credited_evidence_gain: int
    total_cost: int
    expanded_nodes: int
    examined_edges: int
    exclusions: PathExclusionCounts
    budget: TraceRankPathBudget
    sentinel_outputs: tuple[int, ...] = ()
    tie_break_id: str = PATH_TIE_BREAK_ID
    cost_contract_id: str = PATH_COST_CONTRACT_ID

    def __post_init__(self) -> None:
        if not isinstance(self.decision, TraceRankDecision):
            raise TraceRankPlannerError("decision must be TraceRankDecision")
        if not isinstance(self.fault, TraceRankFault):
            raise TraceRankPlannerError("fault must be TraceRankFault")
        _require_root("request_root", self.request_root)
        if not isinstance(self.serving_epoch_root, str) or not _HEX_ROOT_RE.fullmatch(
            self.serving_epoch_root
        ):
            raise TraceRankPlannerError("serving_epoch_root is not canonical")
        _require_root("graph_root", self.graph_root)
        _require_root(
            "dataset_generation_set_root", self.dataset_generation_set_root
        )
        _require_root("feature_schema_root", self.feature_schema_root)
        _require_root("server_namespace_root", self.server_namespace_root)
        _require_root("graph_admission_root", self.graph_admission_root)
        _require_root("path_context_root", self.path_context_root)
        _require_root("policy_root", self.policy_root)
        for name in ("limits_root", "baseline_manifest_root", "authority_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX_ROOT_RE.fullmatch(value):
                raise TraceRankPlannerError(f"{name} is not canonical")
        if not isinstance(self.waypoint_path, tuple) or any(
            not isinstance(item, PathWaypointReceipt) for item in self.waypoint_path
        ):
            raise TraceRankPlannerError("waypoint_path must contain receipt records")
        if not isinstance(self.edge_path, tuple) or any(
            not isinstance(item, PathEdgeReceipt) for item in self.edge_path
        ):
            raise TraceRankPlannerError("edge_path must contain receipt records")
        for name in (
            "total_base_cost",
            "total_learned_delta",
            "total_evidence_gain",
            "total_credited_evidence_gain",
            "total_cost",
            "expanded_nodes",
            "examined_edges",
        ):
            _require_int(name, getattr(self, name), 0, _UINT64_MAX)
        if not isinstance(self.exclusions, PathExclusionCounts):
            raise TraceRankPlannerError("exclusions must be PathExclusionCounts")
        if not isinstance(self.budget, TraceRankPathBudget):
            raise TraceRankPlannerError("budget must be TraceRankPathBudget")
        if self.sentinel_outputs != ():
            raise TraceRankPlannerError(
                "Phase-5 receipt cannot contain sentinel output",
                fault=TraceRankFault.POLICY_REJECTED,
            )
        if self.tie_break_id != PATH_TIE_BREAK_ID:
            raise TraceRankPlannerError("unsupported path tie-break identity")
        if self.cost_contract_id != PATH_COST_CONTRACT_ID:
            raise TraceRankPlannerError("unsupported path cost identity")
        if self.expanded_nodes > self.budget.max_expanded_nodes:
            raise TraceRankPlannerError("receipt expanded-node count exceeds its budget")
        if self.examined_edges > self.budget.max_examined_edges:
            raise TraceRankPlannerError("receipt examined-edge count exceeds its budget")

        if self.decision is TraceRankDecision.RANKED:
            if self.fault is not TraceRankFault.NONE:
                raise TraceRankPlannerError("a ranked receipt cannot carry a fault")
            if not self.waypoint_path:
                raise TraceRankPlannerError("a ranked receipt requires waypoints")
            if len(self.edge_path) + 1 != len(self.waypoint_path):
                raise TraceRankPlannerError("ranked path lengths are inconsistent")
            if len(self.edge_path) > self.budget.max_steps:
                raise TraceRankPlannerError("ranked path exceeds its step budget")
            for left, edge, right in zip(
                self.waypoint_path, self.edge_path, self.waypoint_path[1:]
            ):
                if (
                    edge.source_index != left.waypoint_index
                    or edge.destination_index != right.waypoint_index
                ):
                    raise TraceRankPlannerError(
                        "receipt edge does not join adjacent waypoints",
                        fault=TraceRankFault.INTEGRITY_FAILURE,
                    )
            expected_totals = (
                sum(item.base_cost for item in self.edge_path),
                sum(item.learned_delta for item in self.edge_path),
                sum(item.evidence_gain for item in self.edge_path),
                sum(item.credited_evidence_gain for item in self.edge_path),
                sum(item.effective_cost for item in self.edge_path),
            )
            actual_totals = (
                self.total_base_cost,
                self.total_learned_delta,
                self.total_evidence_gain,
                self.total_credited_evidence_gain,
                self.total_cost,
            )
            if expected_totals != actual_totals or any(
                value > _UINT64_MAX for value in expected_totals
            ):
                raise TraceRankPlannerError(
                    "receipt path totals are inconsistent",
                    fault=TraceRankFault.INTEGRITY_FAILURE,
                )
            if self.total_cost > self.budget.max_total_cost:
                raise TraceRankPlannerError("ranked path exceeds its cost budget")
        else:
            if (
                self.decision is TraceRankDecision.ABSTAIN
                and self.fault is not TraceRankFault.BOUND_EXCEEDED
            ):
                raise TraceRankPlannerError(
                    "an abstention must identify bound exhaustion"
                )
            if self.decision is TraceRankDecision.FALLBACK and self.fault not in (
                TraceRankFault.NONE,
                TraceRankFault.POLICY_REJECTED,
            ):
                raise TraceRankPlannerError("fallback receipt carries an invalid fault")
            if self.waypoint_path or self.edge_path or any(
                (
                    self.total_base_cost,
                    self.total_learned_delta,
                    self.total_evidence_gain,
                    self.total_credited_evidence_gain,
                    self.total_cost,
                )
            ):
                raise TraceRankPlannerError(
                    "non-ranked receipts cannot contain a path"
                )

    @property
    def selected_goal_index(self) -> int | None:
        if not self.waypoint_path:
            return None
        return self.waypoint_path[-1].waypoint_index

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget.canonical_dict(),
            "authority_root": self.authority_root,
            "baseline_manifest_root": self.baseline_manifest_root,
            "cost_contract_id": self.cost_contract_id,
            "dataset_generation_set_root": self.dataset_generation_set_root,
            "decision": self.decision.value,
            "edge_path": [item.canonical_dict() for item in self.edge_path],
            "examined_edges": self.examined_edges,
            "exclusions": self.exclusions.canonical_dict(),
            "expanded_nodes": self.expanded_nodes,
            "fault": self.fault.value,
            "feature_schema_root": self.feature_schema_root,
            "format_id": PATH_RECEIPT_FORMAT_ID,
            "graph_admission_root": self.graph_admission_root,
            "graph_root": self.graph_root,
            "limits_root": self.limits_root,
            "path_context_root": self.path_context_root,
            "policy_root": self.policy_root,
            "request_root": self.request_root,
            "sentinel_outputs": list(self.sentinel_outputs),
            "server_namespace_root": self.server_namespace_root,
            "serving_epoch_root": self.serving_epoch_root,
            "tie_break_id": self.tie_break_id,
            "total_base_cost": self.total_base_cost,
            "total_cost": self.total_cost,
            "total_credited_evidence_gain": self.total_credited_evidence_gain,
            "total_evidence_gain": self.total_evidence_gain,
            "total_learned_delta": self.total_learned_delta,
            "waypoint_path": [item.canonical_dict() for item in self.waypoint_path],
        }

    def canonical_bytes(self) -> bytes:
        result = _canonical_bytes(self.canonical_dict())
        if len(result) > PATH_MAX_RECEIPT_BYTES:
            raise TraceRankPlannerError(
                "canonical path receipt exceeds its byte bound",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )
        return result

    @classmethod
    def from_bytes(cls, data: bytes) -> "TraceRankPathReceipt":
        """Load only the exact canonical receipt representation."""

        if type(data) is not bytes:
            raise TraceRankPlannerError("receipt payload must be exact bytes")
        if len(data) > PATH_MAX_RECEIPT_BYTES:
            raise TraceRankPlannerError(
                "path receipt payload exceeds its byte bound",
                fault=TraceRankFault.BOUND_EXCEEDED,
            )

        def reject_constant(value: str) -> None:
            raise ValueError(f"non-finite JSON constant: {value}")

        try:
            decoded = json.loads(
                data.decode("ascii"),
                parse_constant=reject_constant,
            )
            value = _require_mapping_fields(
                decoded,
                frozenset(
                    {
                        "authority_root",
                        "baseline_manifest_root",
                        "budget",
                        "cost_contract_id",
                        "dataset_generation_set_root",
                        "decision",
                        "edge_path",
                        "examined_edges",
                        "exclusions",
                        "expanded_nodes",
                        "fault",
                        "feature_schema_root",
                        "format_id",
                        "graph_admission_root",
                        "graph_root",
                        "limits_root",
                        "path_context_root",
                        "policy_root",
                        "request_root",
                        "sentinel_outputs",
                        "server_namespace_root",
                        "serving_epoch_root",
                        "tie_break_id",
                        "total_base_cost",
                        "total_cost",
                        "total_credited_evidence_gain",
                        "total_evidence_gain",
                        "total_learned_delta",
                        "waypoint_path",
                    }
                ),
                "path receipt",
            )
            if value["format_id"] != PATH_RECEIPT_FORMAT_ID:
                raise TraceRankPlannerError(
                    "unsupported path receipt format",
                    fault=TraceRankFault.INTEGRITY_FAILURE,
                )
            budget_value = _require_mapping_fields(
                value["budget"],
                frozenset(
                    {
                        "max_examined_edges",
                        "max_expanded_nodes",
                        "max_steps",
                        "max_total_cost",
                    }
                ),
                "path budget",
            )
            exclusion_value = _require_mapping_fields(
                value["exclusions"],
                frozenset(
                    {
                        "causal",
                        "cost_budget",
                        "license",
                        "operation",
                        "policy",
                        "privacy",
                        "step_budget",
                    }
                ),
                "path exclusions",
            )
            waypoint_fields = frozenset(
                {
                    "byte_end",
                    "byte_start",
                    "causal_sequence",
                    "generation_root",
                    "license_class",
                    "policy_mask",
                    "privacy_class",
                    "provenance_root",
                    "row_end",
                    "row_start",
                    "waypoint_index",
                }
            )
            edge_fields = frozenset(
                {
                    "base_cost",
                    "credited_evidence_gain",
                    "destination_index",
                    "edge_index",
                    "effective_cost",
                    "evidence_gain",
                    "hard_eligibility_mask",
                    "learned_delta",
                    "operation",
                    "source_index",
                }
            )
            waypoint_values = value["waypoint_path"]
            edge_values = value["edge_path"]
            sentinel_values = value["sentinel_outputs"]
            if not isinstance(waypoint_values, list):
                raise TypeError("waypoint_path is not a list")
            if not isinstance(edge_values, list):
                raise TypeError("edge_path is not a list")
            if not isinstance(sentinel_values, list):
                raise TypeError("sentinel_outputs is not a list")
            receipt = cls(
                decision=TraceRankDecision(value["decision"]),
                fault=TraceRankFault(value["fault"]),
                request_root=value["request_root"],
                serving_epoch_root=value["serving_epoch_root"],
                graph_root=value["graph_root"],
                dataset_generation_set_root=value[
                    "dataset_generation_set_root"
                ],
                feature_schema_root=value["feature_schema_root"],
                server_namespace_root=value["server_namespace_root"],
                graph_admission_root=value["graph_admission_root"],
                path_context_root=value["path_context_root"],
                policy_root=value["policy_root"],
                limits_root=value["limits_root"],
                baseline_manifest_root=value["baseline_manifest_root"],
                authority_root=value["authority_root"],
                waypoint_path=tuple(
                    PathWaypointReceipt(
                        **_require_mapping_fields(
                            item, waypoint_fields, "waypoint receipt"
                        )
                    )
                    for item in waypoint_values
                ),
                edge_path=tuple(
                    PathEdgeReceipt(
                        **_require_mapping_fields(item, edge_fields, "edge receipt")
                    )
                    for item in edge_values
                ),
                total_base_cost=value["total_base_cost"],
                total_learned_delta=value["total_learned_delta"],
                total_evidence_gain=value["total_evidence_gain"],
                total_credited_evidence_gain=value[
                    "total_credited_evidence_gain"
                ],
                total_cost=value["total_cost"],
                expanded_nodes=value["expanded_nodes"],
                examined_edges=value["examined_edges"],
                exclusions=PathExclusionCounts(**exclusion_value),
                budget=TraceRankPathBudget(**budget_value),
                sentinel_outputs=tuple(sentinel_values),
                tie_break_id=value["tie_break_id"],
                cost_contract_id=value["cost_contract_id"],
            )
        except TraceRankPlannerError:
            raise
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TraceRankPlannerError(
                "path receipt payload is malformed",
                fault=TraceRankFault.INTEGRITY_FAILURE,
            ) from exc
        if receipt.canonical_bytes() != data:
            raise TraceRankPlannerError(
                "path receipt bytes are not canonical",
                fault=TraceRankFault.INTEGRITY_FAILURE,
            )
        return receipt

    @property
    def receipt_root(self) -> str:
        return _canonical_root("path-receipt", self.canonical_dict())


def _validate_request(
    context: AdmittedPathContext,
    request: TraceRankPathRequest,
) -> None:
    if not isinstance(context, AdmittedPathContext):
        raise TraceRankPlannerError("context must be AdmittedPathContext")
    if not isinstance(request, TraceRankPathRequest):
        raise TraceRankPlannerError("request must be TraceRankPathRequest")
    request.budget.validate_against(context.limits)
    graph = context.verified_graph.graph
    if len(request.candidate_waypoints) > context.limits.max_candidates:
        raise TraceRankPlannerError(
            "candidate count exceeds the qualified limit",
            fault=TraceRankFault.BOUND_EXCEEDED,
        )
    if request.start_waypoint >= len(graph.waypoints) or any(
        item >= len(graph.waypoints) for item in request.candidate_waypoints
    ):
        raise TraceRankPlannerError("path request contains an unknown waypoint")
    if request.path_context_root != context.context_root:
        raise TraceRankPlannerError(
            "request does not bind the admitted path context",
            fault=TraceRankFault.EPOCH_MISMATCH,
        )
    if request.policy_root != context.policy.policy_root:
        raise TraceRankPlannerError(
            "request does not bind the controller-qualified path policy",
            fault=TraceRankFault.POLICY_REJECTED,
        )
    if request.pinned_epoch.epoch_root != context.expected_epoch.epoch_root:
        raise TraceRankPlannerError(
            "request ServingEpoch does not match the fully admitted epoch",
            fault=TraceRankFault.EPOCH_MISMATCH,
        )


def _waypoint_receipt(
    graph: PackedWaypointGraph, waypoint_index: int
) -> PathWaypointReceipt:
    waypoint = graph.waypoints[waypoint_index]
    generation = graph.generations[waypoint.generation_index]
    provenance = graph.provenance[waypoint.provenance_index]
    return PathWaypointReceipt(
        waypoint_index=waypoint_index,
        generation_root=generation.generation_root,
        provenance_root=provenance.provenance_root,
        causal_sequence=waypoint.causal_sequence,
        byte_start=waypoint.byte_start,
        byte_end=waypoint.byte_end,
        row_start=waypoint.row_start,
        row_end=waypoint.row_end,
        privacy_class=provenance.privacy_class,
        license_class=provenance.license_class,
        policy_mask=provenance.policy_mask,
    )


def _edge_receipt(
    graph: PackedWaypointGraph,
    source_index: int,
    edge_index: int,
) -> PathEdgeReceipt:
    edge = graph.edges[edge_index]
    effective_cost, credited_gain = _edge_cost(edge)
    return PathEdgeReceipt(
        edge_index=edge_index,
        source_index=source_index,
        destination_index=edge.destination_index,
        operation=edge.operation,
        base_cost=edge.base_cost,
        learned_delta=edge.learned_delta,
        evidence_gain=edge.evidence_gain,
        credited_evidence_gain=credited_gain,
        effective_cost=effective_cost,
        hard_eligibility_mask=edge.hard_eligibility_mask,
    )


def _empty_receipt(
    *,
    context: AdmittedPathContext,
    request: TraceRankPathRequest,
    decision: TraceRankDecision,
    fault: TraceRankFault,
    expanded_nodes: int,
    examined_edges: int,
    exclusions: PathExclusionCounts,
) -> TraceRankPathReceipt:
    admitted = context.verified_graph
    return TraceRankPathReceipt(
        decision=decision,
        fault=fault,
        request_root=request.request_root,
        serving_epoch_root=request.pinned_epoch.epoch_root,
        graph_root=admitted.graph_root,
        dataset_generation_set_root=admitted.dataset_generation_set_root,
        feature_schema_root=admitted.feature_schema_root,
        server_namespace_root=admitted.graph.server_namespace_root,
        graph_admission_root=admitted.graph_admission_root,
        path_context_root=context.context_root,
        policy_root=context.policy.policy_root,
        limits_root=context.limits.limits_root,
        baseline_manifest_root=context.baseline.manifest_root,
        authority_root=TRACE_RANK_V2_AUTHORITY.authority_root,
        waypoint_path=(),
        edge_path=(),
        total_base_cost=0,
        total_learned_delta=0,
        total_evidence_gain=0,
        total_credited_evidence_gain=0,
        total_cost=0,
        expanded_nodes=expanded_nodes,
        examined_edges=examined_edges,
        exclusions=exclusions,
        budget=request.budget,
    )


def _ranked_receipt(
    *,
    context: AdmittedPathContext,
    request: TraceRankPathRequest,
    waypoint_indices: tuple[int, ...],
    edge_indices: tuple[int, ...],
    expanded_nodes: int,
    examined_edges: int,
    exclusions: PathExclusionCounts,
) -> TraceRankPathReceipt:
    admitted = context.verified_graph
    graph = admitted.graph
    waypoint_path = tuple(_waypoint_receipt(graph, index) for index in waypoint_indices)
    edge_path = tuple(
        _edge_receipt(graph, source, edge)
        for source, edge in zip(waypoint_indices, edge_indices)
    )
    totals = (0, 0, 0, 0, 0)
    for edge in edge_path:
        totals = tuple(
            _checked_add("path receipt component", left, right)
            for left, right in zip(
                totals,
                (
                    edge.base_cost,
                    edge.learned_delta,
                    edge.evidence_gain,
                    edge.credited_evidence_gain,
                    edge.effective_cost,
                ),
            )
        )
    return TraceRankPathReceipt(
        decision=TraceRankDecision.RANKED,
        fault=TraceRankFault.NONE,
        request_root=request.request_root,
        serving_epoch_root=request.pinned_epoch.epoch_root,
        graph_root=admitted.graph_root,
        dataset_generation_set_root=admitted.dataset_generation_set_root,
        feature_schema_root=admitted.feature_schema_root,
        server_namespace_root=admitted.graph.server_namespace_root,
        graph_admission_root=admitted.graph_admission_root,
        path_context_root=context.context_root,
        policy_root=context.policy.policy_root,
        limits_root=context.limits.limits_root,
        baseline_manifest_root=context.baseline.manifest_root,
        authority_root=TRACE_RANK_V2_AUTHORITY.authority_root,
        waypoint_path=waypoint_path,
        edge_path=edge_path,
        total_base_cost=totals[0],
        total_learned_delta=totals[1],
        total_evidence_gain=totals[2],
        total_credited_evidence_gain=totals[3],
        total_cost=totals[4],
        expanded_nodes=expanded_nodes,
        examined_edges=examined_edges,
        exclusions=exclusions,
        budget=request.budget,
    )


def plan_shortest_path(
    context: AdmittedPathContext,
    request: TraceRankPathRequest,
) -> TraceRankPathReceipt:
    """Run the bounded off-path Dijkstra reference over qualified inputs."""

    _validate_request(context, request)
    graph = context.verified_graph.graph
    policy = context.policy
    goals = frozenset(request.candidate_waypoints)
    allowed_operations = frozenset(policy.allowed_operations)
    allowed_privacy_classes = frozenset(policy.allowed_privacy_classes)
    allowed_license_classes = frozenset(policy.allowed_license_classes)
    budget = request.budget

    # Heap order is the complete public tie-break contract.
    initial = (0, 0, (request.start_waypoint,), (), ())
    heap: list[tuple[Any, ...]] = [initial]
    best: dict[
        tuple[int, int],
        tuple[int, tuple[int, ...], tuple[int, ...], tuple[int, ...]],
    ] = {
        (request.start_waypoint, 0): (0, (request.start_waypoint,), (), ())
    }
    expanded_nodes = 0
    examined_edges = 0
    exclusions = {
        "policy": 0,
        "operation": 0,
        "privacy": 0,
        "license": 0,
        "causal": 0,
        "step_budget": 0,
        "cost_budget": 0,
    }

    start = graph.waypoints[request.start_waypoint]
    start_provenance = graph.provenance[start.provenance_index]
    if (
        start_provenance.policy_mask & policy.satisfied_hard_mask
        != start_provenance.policy_mask
    ):
        exclusions["policy"] = 1
    if start_provenance.privacy_class not in allowed_privacy_classes:
        exclusions["privacy"] = 1
    if start_provenance.license_class not in allowed_license_classes:
        exclusions["license"] = 1
    if exclusions["policy"] or exclusions["privacy"] or exclusions["license"]:
        return _empty_receipt(
            context=context,
            request=request,
            decision=TraceRankDecision.FALLBACK,
            fault=TraceRankFault.POLICY_REJECTED,
            expanded_nodes=0,
            examined_edges=0,
            exclusions=PathExclusionCounts(**exclusions),
        )

    while heap:
        (
            total_cost,
            steps,
            waypoint_path,
            operation_path,
            edge_path,
        ) = heapq.heappop(heap)
        node = waypoint_path[-1]
        key = (node, steps)
        rank_key = (total_cost, waypoint_path, operation_path, edge_path)
        if best.get(key) != rank_key:
            continue

        if node in goals:
            return _ranked_receipt(
                context=context,
                request=request,
                waypoint_indices=waypoint_path,
                edge_indices=edge_path,
                expanded_nodes=expanded_nodes,
                examined_edges=examined_edges,
                exclusions=PathExclusionCounts(**exclusions),
            )
        if expanded_nodes >= budget.max_expanded_nodes:
            return _empty_receipt(
                context=context,
                request=request,
                decision=TraceRankDecision.ABSTAIN,
                fault=TraceRankFault.BOUND_EXCEEDED,
                expanded_nodes=expanded_nodes,
                examined_edges=examined_edges,
                exclusions=PathExclusionCounts(**exclusions),
            )
        expanded_nodes += 1

        start = graph.edge_offsets[node]
        end = graph.edge_offsets[node + 1]
        for edge_index in range(start, end):
            if examined_edges >= budget.max_examined_edges:
                return _empty_receipt(
                    context=context,
                    request=request,
                    decision=TraceRankDecision.ABSTAIN,
                    fault=TraceRankFault.BOUND_EXCEEDED,
                    expanded_nodes=expanded_nodes,
                    examined_edges=examined_edges,
                    exclusions=PathExclusionCounts(**exclusions),
                )
            examined_edges += 1
            edge = graph.edges[edge_index]
            destination = edge.destination_index
            if edge.operation not in allowed_operations:
                exclusions["operation"] += 1
                continue
            if (
                edge.hard_eligibility_mask & policy.satisfied_hard_mask
                != edge.hard_eligibility_mask
            ):
                exclusions["policy"] += 1
                continue
            destination_provenance = graph.provenance[
                graph.waypoints[destination].provenance_index
            ]
            if destination_provenance.privacy_class not in allowed_privacy_classes:
                exclusions["privacy"] += 1
                continue
            if destination_provenance.license_class not in allowed_license_classes:
                exclusions["license"] += 1
                continue
            if (
                graph.waypoints[destination].causal_sequence
                <= graph.waypoints[node].causal_sequence
            ):
                exclusions["causal"] += 1
                continue
            next_steps = steps + 1
            if next_steps > budget.max_steps:
                exclusions["step_budget"] += 1
                continue
            effective_cost, _ = _edge_cost(edge)
            next_cost = _checked_add("path total cost", total_cost, effective_cost)
            if next_cost > budget.max_total_cost:
                exclusions["cost_budget"] += 1
                continue
            next_waypoints = waypoint_path + (destination,)
            next_operations = operation_path + (edge.operation,)
            next_edges = edge_path + (edge_index,)
            next_rank = (next_cost, next_waypoints, next_operations, next_edges)
            next_key = (destination, next_steps)
            previous = best.get(next_key)
            if previous is not None and previous <= next_rank:
                continue
            best[next_key] = next_rank
            heapq.heappush(
                heap,
                (
                    next_cost,
                    next_steps,
                    next_waypoints,
                    next_operations,
                    next_edges,
                ),
            )

    exclusion_counts = PathExclusionCounts(**exclusions)
    if exclusions["step_budget"] or exclusions["cost_budget"]:
        decision = TraceRankDecision.ABSTAIN
        fault = TraceRankFault.BOUND_EXCEEDED
    else:
        decision = TraceRankDecision.FALLBACK
        fault = (
            TraceRankFault.POLICY_REJECTED
            if any(
                exclusions[name]
                for name in ("policy", "operation", "privacy", "license")
            )
            else TraceRankFault.NONE
        )
    return _empty_receipt(
        context=context,
        request=request,
        decision=decision,
        fault=fault,
        expanded_nodes=expanded_nodes,
        examined_edges=examined_edges,
        exclusions=exclusion_counts,
    )


def replay_path_receipt(
    context: AdmittedPathContext,
    request: TraceRankPathRequest,
    receipt: TraceRankPathReceipt,
) -> TraceRankPathReceipt:
    """Recompute and byte-compare one immutable path receipt."""

    if not isinstance(receipt, TraceRankPathReceipt):
        raise TraceRankPlannerError("receipt must be TraceRankPathReceipt")
    replayed = plan_shortest_path(context, request)
    if replayed.canonical_bytes() != receipt.canonical_bytes():
        raise TraceRankPlannerError(
            "path receipt does not replay against the pinned graph and request",
            fault=TraceRankFault.INTEGRITY_FAILURE,
        )
    return replayed


__all__ = [
    "AdmittedPathContext",
    "DEFAULT_PATH_BUDGET",
    "PATH_BASELINE_CONFIGURATION_ROOT",
    "PATH_COST_CONTRACT_ID",
    "PATH_DETERMINISTIC_FALLBACK_ID",
    "PATH_MAX_RECEIPT_BYTES",
    "PATH_OBJECTIVE_CONTRACT_ROOT",
    "PATH_PLANNER_CONTRACT_ID",
    "PATH_RECEIPT_FORMAT_ID",
    "PATH_TIE_BREAK_ID",
    "PathEdgeReceipt",
    "PathExclusionCounts",
    "PathWaypointReceipt",
    "QualifiedPathPolicy",
    "TraceRankPathBudget",
    "TraceRankPathReceipt",
    "TraceRankPathRequest",
    "TraceRankPlannerError",
    "VerifiedPackedGraph",
    "baseline_rank_model_epoch",
    "build_reference_baseline_manifest",
    "plan_shortest_path",
    "replay_path_receipt",
]

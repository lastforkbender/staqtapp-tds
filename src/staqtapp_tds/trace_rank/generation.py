"""Build-time Generation Authority bridges for Trace Rank graph sources."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from staqtapp_tds.generation.csv import CSVGenerationLease
from staqtapp_tds.trace_rank.graph import (
    DEFAULT_PACKED_GRAPH_LIMITS,
    ImmutableSourceBinding,
    PackedGraphError,
    PackedGraphLimits,
    PackedWaypointGraph,
)

CSV_GRAPH_BRIDGE_CONTRACT_ID = "tds-csv-generation-graph-bridge-v1"
_ROOT_DOMAIN_PREFIX = b"STAQTAPP-TDS\x00TRACE-RANK\x00CSV-GRAPH-BRIDGE-V1\x00"


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _bridge_root(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        _ROOT_DOMAIN_PREFIX + _canonical_bytes(value)
    ).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedCSVGraphBridge:
    """Factory-only, build-time bridge from one verified pinned CSV lease.

    CSV Generation Authority persists canonical *row starts*.  The packed graph
    uses a half-open boundary vector with one terminal source-length element.
    This bridge records that mechanical conversion and its exact qualification
    identities.  Closure/evidence values remain qualification roots, not
    retained evidence payloads.  The caller must keep the lease open through
    graph serialization/admission; the serving epoch manager owns later pins.
    """

    namespace: str
    source_binding: ImmutableSourceBinding
    graph_row_offsets_root: str
    csv_binding_root: str
    csv_row_offsets_root: str
    csv_row_anchors_root: str
    csv_closure_root: str
    csv_evidence_root: str
    csv_parser_root: str
    csv_dialect_root: str
    bridge_root: str
    _lease: CSVGenerationLease

    def __init__(self) -> None:
        raise TypeError("use bind_csv_generation_source")

    @property
    def lease_open(self) -> bool:
        return not self._lease.closed

    def require_open_lease(self) -> None:
        if not self.lease_open:
            raise PackedGraphError(
                "CSV graph bridge lost its build-time generation pin"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "bridge_root": self.bridge_root,
            "contract_id": CSV_GRAPH_BRIDGE_CONTRACT_ID,
            "csv_binding_root": self.csv_binding_root,
            "csv_closure_qualification_root": self.csv_closure_root,
            "csv_dialect_root": self.csv_dialect_root,
            "csv_evidence_qualification_root": self.csv_evidence_root,
            "csv_parser_root": self.csv_parser_root,
            "csv_row_anchors_root": self.csv_row_anchors_root,
            "csv_row_offsets_root": self.csv_row_offsets_root,
            "generation_root": self.source_binding.generation_root,
            "graph_row_offsets_root": self.graph_row_offsets_root,
            "namespace": self.namespace,
            "source_root": self.source_binding.source_root,
            "source_size": len(self.source_binding.source_bytes),
        }


def bind_csv_generation_source(
    lease: CSVGenerationLease,
    *,
    expected_namespace: str,
) -> VerifiedCSVGraphBridge:
    """Build a graph source only from one open, fully verified CSV lease."""

    if not isinstance(lease, CSVGenerationLease):
        raise PackedGraphError("lease must be a CSVGenerationLease")
    if lease.closed:
        raise PackedGraphError("CSV generation lease is closed")
    if not isinstance(expected_namespace, str) or not expected_namespace:
        raise PackedGraphError("expected_namespace must not be empty")
    if lease.binding.namespace != expected_namespace:
        raise PackedGraphError("CSV generation lease belongs to another namespace")
    source = lease.read_source()
    starts = lease.row_offsets
    binding = lease.binding
    if len(starts) != binding.row_count or len(source) != binding.source_size:
        raise PackedGraphError("CSV lease row/source counts changed after verification")
    if source:
        boundaries = starts + (len(source),)
    else:
        if starts:
            raise PackedGraphError("empty CSV source has non-empty row starts")
        boundaries = (0,)
    graph_source = ImmutableSourceBinding(
        generation_root=lease.generation_root,
        source_bytes=source,
        row_offsets=boundaries,
    )
    if graph_source.row_count != binding.row_count:
        raise PackedGraphError("CSV-to-graph row boundary conversion is inconsistent")
    values = {
        "contract_id": CSV_GRAPH_BRIDGE_CONTRACT_ID,
        "csv_binding_root": binding.binding_root,
        "csv_closure_qualification_root": binding.closure_root,
        "csv_dialect_root": binding.dialect_root,
        "csv_evidence_qualification_root": binding.evidence_root,
        "csv_parser_root": binding.parser_root,
        "csv_row_anchors_root": binding.row_anchors_root,
        "csv_row_offsets_root": binding.row_offsets_root,
        "generation_root": graph_source.generation_root,
        "graph_row_offsets_root": graph_source.row_offsets_root,
        "namespace": binding.namespace,
        "source_root": graph_source.source_root,
        "source_size": len(source),
    }
    result = object.__new__(VerifiedCSVGraphBridge)
    fields = {
        "namespace": binding.namespace,
        "source_binding": graph_source,
        "graph_row_offsets_root": graph_source.row_offsets_root,
        "csv_binding_root": binding.binding_root,
        "csv_row_offsets_root": binding.row_offsets_root,
        "csv_row_anchors_root": binding.row_anchors_root,
        "csv_closure_root": binding.closure_root,
        "csv_evidence_root": binding.evidence_root,
        "csv_parser_root": binding.parser_root,
        "csv_dialect_root": binding.dialect_root,
        "bridge_root": _bridge_root(values),
        "_lease": lease,
    }
    for name, value in fields.items():
        object.__setattr__(result, name, value)
    return result


def bind_csv_generation_sources(
    leases: tuple[CSVGenerationLease, ...],
    *,
    expected_namespace: str,
    max_generations: int = DEFAULT_PACKED_GRAPH_LIMITS.max_generations,
) -> tuple[VerifiedCSVGraphBridge, ...]:
    """Convert a canonical ordered set of pinned CSV generations."""

    if not isinstance(leases, tuple):
        raise PackedGraphError("CSV generation leases must be an immutable tuple")
    if isinstance(max_generations, bool) or not isinstance(max_generations, int):
        raise PackedGraphError("max_generations must be an integer")
    if max_generations < 1 or max_generations > DEFAULT_PACKED_GRAPH_LIMITS.max_generations:
        raise PackedGraphError("max_generations exceeds the packed graph envelope")
    if not leases or len(leases) > max_generations:
        raise PackedGraphError("CSV generation lease count exceeds its bound")
    for lease in leases:
        if not isinstance(lease, CSVGenerationLease) or lease.closed:
            raise PackedGraphError("CSV generation leases must be open verified leases")
        if lease.binding.namespace != expected_namespace:
            raise PackedGraphError("CSV generation leases cross a namespace boundary")
    roots = tuple(lease.generation_root for lease in leases)
    if any(right <= left for left, right in zip(roots, roots[1:])):
        raise PackedGraphError(
            "CSV generation leases must be unique and in generation-root order"
        )
    return tuple(
        bind_csv_generation_source(lease, expected_namespace=expected_namespace)
        for lease in leases
    )


def admit_csv_packed_graph(
    graph: PackedWaypointGraph,
    bridges: tuple[VerifiedCSVGraphBridge, ...],
    *,
    expected_namespace: str,
    edge_catalog_root: str,
    limits: PackedGraphLimits = DEFAULT_PACKED_GRAPH_LIMITS,
) -> "VerifiedPackedGraph":
    """Admit graph bytes while every CSV bridge still owns its build pin."""

    if not isinstance(graph, PackedWaypointGraph):
        raise PackedGraphError("graph must be a PackedWaypointGraph")
    if not isinstance(bridges, tuple) or not bridges:
        raise PackedGraphError("bridges must be a non-empty immutable tuple")
    if not isinstance(limits, PackedGraphLimits):
        raise PackedGraphError("limits must be PackedGraphLimits")
    if not isinstance(expected_namespace, str) or not expected_namespace:
        raise PackedGraphError("expected_namespace must not be empty")
    if len(bridges) > limits.max_generations:
        raise PackedGraphError("CSV graph bridge count exceeds its bound")
    for bridge in bridges:
        if not isinstance(bridge, VerifiedCSVGraphBridge):
            raise PackedGraphError("bridges contains an invalid record")
        if bridge.namespace != expected_namespace:
            raise PackedGraphError("CSV graph bridges cross a namespace boundary")
        bridge.require_open_lease()
    sources = tuple(item.source_binding for item in bridges)
    evidence_roots = tuple(item.bridge_root for item in bridges)
    from staqtapp_tds.trace_rank.planner import VerifiedPackedGraph

    return VerifiedPackedGraph.from_graph(
        graph,
        sources,
        source_evidence_roots=evidence_roots,
        edge_catalog_root=edge_catalog_root,
        limits=limits,
    )


__all__ = [
    "CSV_GRAPH_BRIDGE_CONTRACT_ID",
    "VerifiedCSVGraphBridge",
    "admit_csv_packed_graph",
    "bind_csv_generation_source",
    "bind_csv_generation_sources",
]

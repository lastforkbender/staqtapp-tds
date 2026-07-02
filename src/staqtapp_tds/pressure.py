"""Pressure Calculations Engine for TDS v2.7.2.

This module converts already-copied counters and immutable diagnostic snapshots
into operator-facing pressure scores.  It is intentionally observational: it
owns no storage objects, takes no storage locks, and never calls into hot-path
operations.  The browser dashboard can consume the resulting structure directly
from status snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from staqtapp_tds.asi import PressureMode, pressure_mode_for_score


def _num(mapping: Mapping[str, Any] | None, key: str, default: float = 0.0) -> float:
    if not mapping:
        return default
    try:
        return float(mapping.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(round(value))))


@dataclass(frozen=True, slots=True)
class PressureComponent:
    """One independently explainable pressure dimension."""

    name: str
    score: int
    mode: PressureMode
    cause: str
    metrics: dict[str, float | int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "mode": self.mode.name.lower(),
            "mode_label": self.mode.label,
            "cause": self.cause,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class PressureCalculationSnapshot:
    """Dashboard-ready pressure interpretation assembled off the hot path."""

    schema_version: int
    score: int
    mode: PressureMode
    components: tuple[PressureComponent, ...]
    dominant_component: str
    causes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        component_map = {c.name: c.to_dict() for c in self.components}
        return {
            "schema_version": self.schema_version,
            "score": self.score,
            "mode": self.mode.name.lower(),
            "mode_label": self.mode.label,
            "dominant_component": self.dominant_component,
            "causes": list(self.causes),
            "components": component_map,
            "component_list": [c.to_dict() for c in self.components],
            # Flattened fields keep the existing browser simple and stable.
            "engine_pressure": component_map.get("engine", {}).get("score", 0),
            "storage_pressure": component_map.get("storage", {}).get("score", 0),
            "index_pressure": component_map.get("index", {}).get("score", 0),
            "lock_pressure": component_map.get("lock", {}).get("score", 0),
            "ring_buffer_pressure": component_map.get("diagnostic_ring", {}).get("score", 0),
            "memory_pressure": component_map.get("memory", {}).get("score", 0),
            "bridge_pressure": component_map.get("python_bridge", {}).get("score", 0),
            "dashboard_pressure": component_map.get("dashboard", {}).get("score", 0),
        }


def _component(name: str, score: float, cause: str, **metrics: float | int) -> PressureComponent:
    bounded = _clamp(score)
    return PressureComponent(
        name=name,
        score=bounded,
        mode=pressure_mode_for_score(bounded),
        cause=cause,
        metrics={k: v for k, v in metrics.items()},
    )


def calculate_pressure_snapshot(
    counters: Mapping[str, Any],
    *,
    native_counters: Mapping[str, Any] | None = None,
    performance: Mapping[str, Any] | None = None,
    storage: Mapping[str, Any] | None = None,
    indexes: Mapping[str, Any] | None = None,
    snapshot_lag: int = 0,
) -> PressureCalculationSnapshot:
    """Calculate multi-dimensional operational pressure from copied data only."""

    native_counters = native_counters or {}
    performance = performance or {}
    storage = storage or {}
    indexes = indexes or {}
    swiss = indexes.get("swiss", {}) if isinstance(indexes.get("swiss", {}), Mapping) else {}

    reads_s = _num(performance, "reads_per_sec")
    writes_s = _num(performance, "writes_per_sec")
    lookups_s = _num(performance, "lookups_per_sec")
    avg_lookup_ms = _num(performance, "avg_lookup_ms")
    avg_write_ms = _num(performance, "avg_write_ms")
    transition_rate = _num(performance, "python_native_transitions_per_sec")
    batch_rate = _num(performance, "native_batch_ops_per_sec")

    chunk_pending = _num(storage, "chunk_pending", _num(counters, "chunk_pending"))
    chunk_quarantined = _num(storage, "chunk_quarantined", _num(counters, "chunk_quarantined"))
    telemetry_dropped = _num(storage, "telemetry_dropped", _num(counters, "telemetry_dropped"))
    errors = _num(storage, "errors", _num(counters, "errors"))

    ring_capacity = max(1.0, _num(native_counters, "ring_capacity", 1.0))
    ring_occupancy = _num(native_counters, "ring_occupancy")
    ring_used_pct = 100.0 * ring_occupancy / ring_capacity
    events_dropped = _num(native_counters, "events_dropped")
    wraps = _num(native_counters, "event_ring_wraparounds")
    lock_transitions = _num(native_counters, "lock_transitions")
    memory_transitions = _num(native_counters, "memory_transitions")
    slot_transitions = _num(native_counters, "slot_transitions")
    index_transitions = _num(native_counters, "index_transitions")

    alloc_calls = _num(performance, "pool_allocator_calls", _num(counters, "pool_allocator_calls"))
    pool_reuse_percent = _num(performance, "pool_reuse_percent", 100.0)
    avg_probe = _num(swiss, "average_probe", _num(swiss, "avg_probe"))
    max_probe = _num(swiss, "max_probe")
    load_factor_pct = _num(swiss, "load_factor")
    if load_factor_pct <= 1.0:
        load_factor_pct *= 100.0

    components = (
        _component(
            "engine",
            min(35, reads_s / 2500) + min(35, writes_s / 1500) + min(20, avg_lookup_ms * 3) + min(10, errors * 2),
            "Hot-path latency, read/write rate, and error counters.",
            reads_per_sec=reads_s,
            writes_per_sec=writes_s,
            avg_lookup_ms=avg_lookup_ms,
            errors=errors,
        ),
        _component(
            "storage",
            min(40, chunk_pending * 4) + min(35, chunk_quarantined * 10) + min(15, avg_write_ms * 2) + min(10, slot_transitions / 2000),
            "Chunk backlog, quarantine count, write latency, and slot lifecycle churn.",
            chunk_pending=chunk_pending,
            chunk_quarantined=chunk_quarantined,
            avg_write_ms=avg_write_ms,
            slot_transitions=slot_transitions,
        ),
        _component(
            "index",
            min(35, avg_probe * 12) + min(25, max_probe * 4) + max(0, min(25, load_factor_pct - 70)) + min(15, index_transitions / 2500),
            "Swiss probe length, table load, and index transition churn.",
            average_probe=avg_probe,
            max_probe=max_probe,
            load_factor_percent=load_factor_pct,
            index_transitions=index_transitions,
        ),
        _component(
            "lock",
            min(100, lock_transitions / 4000),
            "Observed lock transition volume from native diagnostics.",
            lock_transitions=lock_transitions,
        ),
        _component(
            "diagnostic_ring",
            min(70, ring_used_pct) + min(20, events_dropped * 2) + min(10, wraps),
            "Diagnostic ring occupancy, dropped events, and wraparound activity.",
            ring_occupancy=ring_occupancy,
            ring_capacity=ring_capacity,
            ring_used_percent=round(ring_used_pct, 2),
            events_dropped=events_dropped,
            wraparounds=wraps,
        ),
        _component(
            "memory",
            min(40, alloc_calls / 1500) + max(0, min(40, 100 - pool_reuse_percent)) + min(20, memory_transitions / 3000),
            "Allocator calls, pool reuse, and native memory transition churn.",
            allocator_calls=alloc_calls,
            pool_reuse_percent=pool_reuse_percent,
            memory_transitions=memory_transitions,
        ),
        _component(
            "python_bridge",
            min(45, transition_rate / 1500) + min(30, batch_rate / 2500) + min(25, telemetry_dropped * 3),
            "Python↔native transition rate, native batch rate, and telemetry drops.",
            transitions_per_sec=transition_rate,
            native_batch_ops_per_sec=batch_rate,
            telemetry_dropped=telemetry_dropped,
        ),
        _component(
            "dashboard",
            min(50, max(0, int(snapshot_lag)) * 8) + min(35, telemetry_dropped * 4) + min(15, lookups_s / 4000),
            "Snapshot lag, telemetry drops, and dashboard-facing lookup volume.",
            snapshot_lag=int(snapshot_lag),
            telemetry_dropped=telemetry_dropped,
            lookups_per_sec=lookups_s,
        ),
    )
    dominant = max(components, key=lambda c: c.score)
    # Weighted overall score: emphasize highest pressure but keep broad pressure visible.
    average = sum(c.score for c in components) / max(1, len(components))
    score = _clamp((dominant.score * 0.55) + (average * 0.45))
    ordered_causes = [c.cause for c in sorted(components, key=lambda c: c.score, reverse=True) if c.score > 0][:5]
    if not ordered_causes:
        ordered_causes = ["No elevated pressure detected from current snapshots."]
    return PressureCalculationSnapshot(
        schema_version=1,
        score=score,
        mode=pressure_mode_for_score(score),
        components=components,
        dominant_component=dominant.name,
        causes=tuple(ordered_causes),
    )

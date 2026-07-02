"""Advisory Recovery Planner for TDS v2.7.4.

The planner consumes pressure snapshots, native diagnostic counters, and copied
telemetry dictionaries.  It is deliberately observational: no storage locks, no
mutation of VFS/chunk/index state, and no automatic recovery execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


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
class RecoveryAction:
    """One safe, advisory recovery action."""

    code: str
    title: str
    severity: str
    subsystem: str
    recommendation: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    expected_effect: str = "Reduce observed pressure without changing hot-path semantics."
    confidence: int = 75
    automatic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity,
            "subsystem": self.subsystem,
            "recommendation": self.recommendation,
            "evidence": list(self.evidence),
            "expected_effect": self.expected_effect,
            "confidence": self.confidence,
            "automatic": self.automatic,
        }


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """Snapshot-ready Recovery Planner output."""

    schema_version: int
    status: str
    primary_subsystem: str
    confidence: int
    summary: str
    actions: tuple[RecoveryAction, ...]
    guardrails: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "primary_subsystem": self.primary_subsystem,
            "confidence": self.confidence,
            "summary": self.summary,
            "actions": [a.to_dict() for a in self.actions],
            "guardrails": list(self.guardrails),
            "action_count": len(self.actions),
            "automatic_actions": 0,
        }


def build_recovery_plan(
    pressure: Mapping[str, Any] | None,
    *,
    native_diagnostics: Mapping[str, Any] | None = None,
    performance: Mapping[str, Any] | None = None,
    storage: Mapping[str, Any] | None = None,
) -> RecoveryPlan:
    """Create an advisory recovery plan from immutable snapshot data only."""

    pressure = pressure or {}
    native_diagnostics = native_diagnostics or {}
    performance = performance or {}
    storage = storage or {}
    counters = native_diagnostics.get("counters", native_diagnostics)
    counters = counters if isinstance(counters, Mapping) else {}

    overall = _num(pressure, "score")
    dominant = str(pressure.get("dominant_component") or "stable")
    actions: list[RecoveryAction] = []

    ring_pressure = _num(pressure, "ring_buffer_pressure")
    ring_used = _num(counters, "ring_occupancy")
    ring_capacity = max(1.0, _num(counters, "ring_capacity", 1.0))
    dropped = _num(counters, "events_dropped")
    if ring_pressure >= 55 or dropped > 0:
        actions.append(RecoveryAction(
            code="REC_DIAG_RING_RELIEF",
            title="Relieve diagnostic-ring pressure",
            severity="warning" if ring_pressure < 80 else "critical",
            subsystem="diagnostic_ring",
            recommendation="Increase diagnostic ring capacity or reduce dashboard polling during bursts.",
            evidence=(
                f"Ring pressure {ring_pressure:.0f}%.",
                f"Ring occupancy {ring_used:.0f}/{ring_capacity:.0f}.",
                f"Dropped diagnostic events {dropped:.0f}.",
            ),
            expected_effect="Preserve transition visibility while keeping diagnostics loss-tolerant.",
            confidence=_clamp(70 + ring_pressure / 4 + min(15, dropped * 2)),
        ))

    bridge_pressure = _num(pressure, "bridge_pressure")
    transitions = _num(performance, "python_native_transitions_per_sec", _num(performance, "python_native_transitions"))
    telemetry_dropped = _num(storage, "telemetry_dropped")
    if bridge_pressure >= 55 or telemetry_dropped > 0:
        actions.append(RecoveryAction(
            code="REC_BRIDGE_THROTTLE",
            title="Throttle bridge-facing telemetry detail",
            severity="warning" if bridge_pressure < 80 else "critical",
            subsystem="python_bridge",
            recommendation="Temporarily coarsen snapshot cadence and prefer aggregate counters over verbose event rendering.",
            evidence=(
                f"Bridge pressure {bridge_pressure:.0f}%.",
                f"Python/native transitions {transitions:.0f} per snapshot interval.",
                f"Telemetry dropped {telemetry_dropped:.0f}.",
            ),
            expected_effect="Lower browser/bridge pressure without changing native storage execution.",
            confidence=_clamp(68 + bridge_pressure / 4 + min(10, telemetry_dropped * 3)),
        ))

    lock_pressure = _num(pressure, "lock_pressure")
    lock_transitions = _num(counters, "lock_transitions")
    if lock_pressure >= 45:
        actions.append(RecoveryAction(
            code="REC_LOCK_TRACE_WINDOW",
            title="Preserve contention trace window",
            severity="warning" if lock_pressure < 75 else "critical",
            subsystem="lock",
            recommendation="Preserve recent lock-transition events and inspect the Lock Contention page before changing concurrency settings.",
            evidence=(f"Lock pressure {lock_pressure:.0f}%.", f"Lock transitions {lock_transitions:.0f}."),
            expected_effect="Keep the evidence window intact for root-cause analysis of contention spikes.",
            confidence=_clamp(65 + lock_pressure / 3),
        ))

    storage_pressure = _num(pressure, "storage_pressure")
    pending = _num(storage, "chunk_pending", _num(pressure, "chunk_pending_count"))
    quarantined = _num(storage, "chunk_quarantined", _num(pressure, "chunk_quarantined_count"))
    if storage_pressure >= 55 or quarantined > 0:
        actions.append(RecoveryAction(
            code="REC_STORAGE_LIFECYCLE_AUDIT",
            title="Audit chunk lifecycle pressure",
            severity="warning" if quarantined == 0 else "critical",
            subsystem="storage",
            recommendation="Inspect pending/quarantined chunk lifecycle state and defer nonessential compaction until evidence is captured.",
            evidence=(
                f"Storage pressure {storage_pressure:.0f}%.",
                f"Pending chunks {pending:.0f}.",
                f"Quarantined chunks {quarantined:.0f}.",
            ),
            expected_effect="Separate recoverable backlog from integrity-sensitive quarantine events.",
            confidence=_clamp(70 + storage_pressure / 5 + min(12, quarantined * 6)),
        ))

    memory_pressure = _num(pressure, "memory_pressure")
    reuse = _num(performance, "pool_reuse_percent", 100.0)
    if memory_pressure >= 60:
        actions.append(RecoveryAction(
            code="REC_MEMORY_RETENTION_TRIM",
            title="Trim observer retention pressure",
            severity="warning" if memory_pressure < 85 else "critical",
            subsystem="memory",
            recommendation="Reduce retained diagnostic rows and snapshot-history depth before adjusting allocator policy.",
            evidence=(f"Memory pressure {memory_pressure:.0f}%.", f"Pool reuse {reuse:.0f}%."),
            expected_effect="Reduce observability memory pressure while preserving storage allocator behavior.",
            confidence=_clamp(66 + memory_pressure / 4),
        ))

    if not actions:
        actions.append(RecoveryAction(
            code="REC_OBSERVE_ONLY",
            title="Continue observation",
            severity="info",
            subsystem="system",
            recommendation="No recovery action is recommended. Continue snapshot observation and preserve current RuntimeConfig.",
            evidence=(f"Overall pressure {overall:.0f}%.", f"Dominant component {dominant}."),
            expected_effect="Maintain stable baseline for later comparison.",
            confidence=92,
        ))
        status = "stable"
        summary = "No elevated pressure requires recovery. Planner remains advisory and observe-only."
        primary = "system"
    else:
        actions.sort(key=lambda a: ({"critical": 3, "warning": 2, "info": 1}.get(a.severity, 0), a.confidence), reverse=True)
        top = actions[0]
        status = "critical" if top.severity == "critical" else "advisory"
        primary = top.subsystem
        summary = f"{len(actions)} advisory recovery action(s) generated; primary focus is {primary}."

    confidence = _clamp(sum(a.confidence for a in actions) / max(1, len(actions)))
    return RecoveryPlan(
        schema_version=1,
        status=status,
        primary_subsystem=primary,
        confidence=confidence,
        summary=summary,
        actions=tuple(actions[:6]),
        guardrails=(
            "Recovery Planner never mutates storage, chunk, index, or lock state.",
            "All actions are advisory until an operator explicitly changes RuntimeConfig.",
            "Planner consumes copied counters, pressure snapshots, and native diagnostics snapshots only.",
        ),
    )

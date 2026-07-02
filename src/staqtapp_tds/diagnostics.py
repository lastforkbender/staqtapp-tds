"""Native Diagnostics Engine bridge for TDS v2.7.2.

The diagnostics layer is deliberately observational.  It owns no storage
objects, mutates no VFS/chunk/index state, and communicates with the native
extension only through copied counters/events and immutable snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List


class DiagnosticEvent(IntEnum):
    GIL_RELEASED = 1
    GIL_REACQUIRED = 2
    CHUNK_SEALED = 3
    CHUNK_VERIFIED = 4
    CHUNK_QUARANTINED = 5
    PRESSURE_MODE_CHANGED = 6
    SNAPSHOT_DROPPED = 7
    RECOVERY_STARTED = 8
    RECOVERY_COMPLETED = 9
    NATIVE_OPERATION = 10
    RING_OVERFLOW = 11
    SLOT_ALLOCATED = 20
    SLOT_WRITTEN = 21
    SLOT_UPDATED = 22
    SLOT_DELETED = 23
    SLOT_VISIBLE = 24
    INDEX_RESIZED = 30
    INDEX_LOOKUP_HIT = 31
    INDEX_LOOKUP_MISS = 32
    LOCK_WAIT = 40
    LOCK_ACQUIRED = 41
    LOCK_RELEASED = 42
    MEMORY_POOL_REUSED = 50
    MEMORY_POOL_ALLOCATED = 51
    MEMORY_POOL_FREED = 52
    SNAPSHOT_MARKER = 60


DIAGNOSTIC_EVENT_NAMES = {int(e): e.name.lower() for e in DiagnosticEvent}
DIAGNOSTIC_SUBSYSTEM_NAMES = {
    0: "native_diagnostics",
    1: "gil_boundary",
    2: "slot_lifecycle",
    3: "index_engine",
    4: "lock_observer",
    5: "memory_pool",
    6: "snapshotter",
}


def enrich_diagnostic_event(event: Dict[str, int]) -> Dict[str, int | str]:
    """Return a UI-friendly copy of a fixed-width native diagnostic event."""
    out: Dict[str, int | str] = dict(event)
    code = int(event.get("code", 0))
    subsystem = int(event.get("subsystem", 0))
    out["event_name"] = DIAGNOSTIC_EVENT_NAMES.get(code, f"event_{code}")
    out["subsystem_name"] = DIAGNOSTIC_SUBSYSTEM_NAMES.get(subsystem, f"subsystem_{subsystem}")
    return out


@dataclass(frozen=True, slots=True)
class NativeDiagnosticSnapshot:
    schema_version: int
    subsystem: str
    enabled: bool
    degraded: bool
    sequence: int
    snapshot_build_ns: int
    counters: Dict[str, int] = field(default_factory=dict)
    recent_events: List[Dict[str, int | str]] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "NativeDiagnosticSnapshot":
        counters = {str(k): int(v) for k, v in dict(data.get("counters", {})).items()}
        events = []
        for item in list(data.get("recent_events", [])):
            if isinstance(item, dict):
                numeric = {str(k): int(v) for k, v in item.items() if isinstance(v, (int, float))}
                events.append(enrich_diagnostic_event(numeric))
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            subsystem=str(data.get("subsystem", "native_diagnostics")),
            enabled=bool(data.get("enabled", False)),
            degraded=bool(data.get("degraded", False)),
            sequence=int(data.get("sequence", 0)),
            snapshot_build_ns=int(data.get("snapshot_build_ns", 0)),
            counters=counters,
            recent_events=events,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "subsystem": self.subsystem,
            "enabled": self.enabled,
            "degraded": self.degraded,
            "sequence": self.sequence,
            "snapshot_build_ns": self.snapshot_build_ns,
            "counters": dict(self.counters),
            "recent_events": [dict(ev) for ev in self.recent_events],
            "event_names": dict(DIAGNOSTIC_EVENT_NAMES),
            "subsystem_names": dict(DIAGNOSTIC_SUBSYSTEM_NAMES),
        }


def _native_module():
    try:
        from staqtapp_tds import _native_index  # type: ignore
    except Exception:
        return None
    return _native_index


def native_diagnostics_available() -> bool:
    mod = _native_module()
    return bool(mod is not None and hasattr(mod, "diag_snapshot"))


def native_diag_snapshot(*, event_limit: int = 32) -> NativeDiagnosticSnapshot:
    mod = _native_module()
    if mod is None or not hasattr(mod, "diag_snapshot"):
        return NativeDiagnosticSnapshot(
            schema_version=1,
            subsystem="native_diagnostics",
            enabled=False,
            degraded=False,
            sequence=0,
            snapshot_build_ns=0,
            counters={},
            recent_events=[],
        )
    try:
        return NativeDiagnosticSnapshot.from_mapping(mod.diag_snapshot(event_limit=int(event_limit)))
    except Exception:
        # Diagnostics has its own failure domain.  A failed diagnostic read must
        # not propagate into storage reads/writes or dashboard assembly.
        return NativeDiagnosticSnapshot(
            schema_version=1,
            subsystem="native_diagnostics",
            enabled=False,
            degraded=True,
            sequence=0,
            snapshot_build_ns=0,
            counters={"snapshot_errors": 1},
            recent_events=[],
        )


def native_diag_reset() -> bool:
    mod = _native_module()
    if mod is None or not hasattr(mod, "diag_reset"):
        return False
    mod.diag_reset()
    return True


def native_diag_set_enabled(enabled: bool) -> bool:
    mod = _native_module()
    if mod is None or not hasattr(mod, "diag_set_enabled"):
        return False
    mod.diag_set_enabled(bool(enabled))
    return True


def native_diag_mark_degraded(degraded: bool = True) -> bool:
    mod = _native_module()
    if mod is None or not hasattr(mod, "diag_mark_degraded"):
        return False
    mod.diag_mark_degraded(bool(degraded))
    return True


def native_diag_emit(event: DiagnosticEvent | int, value_a: int = 0, value_b: int = 0) -> bool:
    mod = _native_module()
    if mod is None or not hasattr(mod, "diag_emit"):
        return False
    mod.diag_emit(int(event), int(value_a), int(value_b))
    return True

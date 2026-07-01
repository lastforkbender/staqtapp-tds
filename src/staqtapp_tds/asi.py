"""ASI-storm pressure model and semantic VFS state helpers for TDS v2.6.

The term "ASI storm" is a TDS design concept: a transient burst condition in
which autonomous or multi-agent systems amplify a small external request into a
large number of native, chunk, index, telemetry, and scheduling operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping


class PressureMode(IntEnum):
    NORMAL = 0
    WARM_PRESSURE = 1
    HIGH_PRESSURE = 2
    CRITICAL_PRESSURE = 3
    PROTECTIVE_READ_ONLY = 4
    RECOVERY = 5

    @property
    def label(self) -> str:
        return self.name.replace("_", " ")


class VFSState(IntEnum):
    CREATED = 0
    ACTIVE = 1
    PRESSURIZED = 2
    THROTTLED = 3
    READ_ONLY = 4
    RECOVERING = 5
    RETIRED = 6


class ChunkState(IntEnum):
    ALLOCATED = 0
    WRITING = 1
    SEALED = 2
    VERIFIED = 3
    INDEXED = 4
    EXPOSED = 5
    RETIRED = 6
    QUARANTINED = 7


@dataclass(slots=True, frozen=True)
class PressureSnapshot:
    score: int
    mode: PressureMode
    vfs_state: VFSState
    queue_depth: int = 0
    chunk_pending_count: int = 0
    chunk_quarantined_count: int = 0
    snapshot_lag: int = 0
    telemetry_dropped_rate: int = 0
    gil_reacquire_rate: int = 0
    allocator_pressure: int = 0
    radix_hot_prefix_score: int = 0
    swiss_probe_pressure: int = 0
    error_skip_rate: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "mode": self.mode.name.lower(),
            "mode_label": self.mode.label,
            "vfs_state": self.vfs_state.name.lower(),
            "queue_depth": self.queue_depth,
            "chunk_pending_count": self.chunk_pending_count,
            "chunk_quarantined_count": self.chunk_quarantined_count,
            "snapshot_lag": self.snapshot_lag,
            "telemetry_dropped_rate": self.telemetry_dropped_rate,
            "gil_reacquire_rate": self.gil_reacquire_rate,
            "allocator_pressure": self.allocator_pressure,
            "radix_hot_prefix_score": self.radix_hot_prefix_score,
            "swiss_probe_pressure": self.swiss_probe_pressure,
            "error_skip_rate": self.error_skip_rate,
        }


def pressure_mode_for_score(score: int) -> PressureMode:
    s = max(0, min(100, int(score)))
    if s >= 95:
        return PressureMode.PROTECTIVE_READ_ONLY
    if s >= 80:
        return PressureMode.CRITICAL_PRESSURE
    if s >= 60:
        return PressureMode.HIGH_PRESSURE
    if s >= 30:
        return PressureMode.WARM_PRESSURE
    return PressureMode.NORMAL


def vfs_state_for_mode(mode: PressureMode) -> VFSState:
    if mode == PressureMode.NORMAL:
        return VFSState.ACTIVE
    if mode == PressureMode.WARM_PRESSURE:
        return VFSState.PRESSURIZED
    if mode in {PressureMode.HIGH_PRESSURE, PressureMode.CRITICAL_PRESSURE}:
        return VFSState.THROTTLED
    if mode == PressureMode.PROTECTIVE_READ_ONLY:
        return VFSState.READ_ONLY
    return VFSState.RECOVERING


def estimate_pressure(counters: Mapping[str, int], *, queue_depth: int = 0, snapshot_lag: int = 0,
                      swiss_probe_pressure: int = 0, radix_hot_prefix_score: int = 0) -> PressureSnapshot:
    """Compute a bounded ASI-storm pressure score from cheap counters only."""
    chunk_pending = max(0, int(counters.get("chunk_pending", 0)))
    chunk_quarantined = max(0, int(counters.get("chunk_quarantined", 0)))
    telemetry_dropped = max(0, int(counters.get("telemetry_dropped", 0)))
    gil_rate = max(0, int(counters.get("python_native_transitions", 0)))
    alloc_calls = max(0, int(counters.get("pool_allocator_calls", 0)))
    reuse = max(0, int(counters.get("pool_reuse_count", 0)))
    error_skips = max(0, int(counters.get("errors", 0))) + max(0, int(counters.get("telemetry_skipped", 0)))
    allocator_pressure = 0 if alloc_calls == 0 else min(20, int(20 * alloc_calls / max(1, alloc_calls + reuse)))
    score = (
        min(20, int(queue_depth) // 5) +
        min(20, chunk_pending * 2) +
        min(18, int(snapshot_lag) * 3) +
        min(15, telemetry_dropped) +
        min(12, gil_rate // 100) +
        allocator_pressure +
        min(10, int(radix_hot_prefix_score)) +
        min(12, int(swiss_probe_pressure)) +
        min(12, error_skips * 2) +
        min(15, chunk_quarantined * 5)
    )
    score = max(0, min(100, int(score)))
    mode = pressure_mode_for_score(score)
    return PressureSnapshot(
        score=score,
        mode=mode,
        vfs_state=vfs_state_for_mode(mode),
        queue_depth=int(queue_depth),
        chunk_pending_count=chunk_pending,
        chunk_quarantined_count=chunk_quarantined,
        snapshot_lag=int(snapshot_lag),
        telemetry_dropped_rate=telemetry_dropped,
        gil_reacquire_rate=gil_rate,
        allocator_pressure=allocator_pressure,
        radix_hot_prefix_score=int(radix_hot_prefix_score),
        swiss_probe_pressure=int(swiss_probe_pressure),
        error_skip_rate=error_skips,
    )

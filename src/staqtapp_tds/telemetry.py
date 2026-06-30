"""Directory telemetry and observation snapshots for Staqtapp-TDS."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Deque, Dict, List

import numpy as np

from staqtapp_tds.latency import LatencyBucket, LatencyPolicy


class TelemetryMode(IntEnum):
    OFF = 0
    LIGHT = 1
    TRACE = 2


TELEMETRY_DTYPE = np.dtype([
    ("hits", "u8"),
    ("misses", "u8"),
    ("cold_count", "u8"),
    ("slow_count", "u8"),
    ("last_ns", "u8"),
    ("avg_ns", "u8"),
    ("max_ns", "u8"),
    ("last_error_code", "u4"),
    ("bucket", "u1"),
])


@dataclass(slots=True, frozen=True)
class TraceRecord:
    timestamp_ns: int
    route_id: int
    elapsed_ns: int
    result_code: int
    bucket: int


@dataclass
class DirectoryTelemetry:
    mode: TelemetryMode = TelemetryMode.LIGHT
    latency_policy: LatencyPolicy = field(default_factory=LatencyPolicy)
    trace_window: int = 1024

    def __post_init__(self) -> None:
        self.record = np.zeros(1, dtype=TELEMETRY_DTYPE)
        self._trace: Deque[TraceRecord] = deque(maxlen=max(1, int(self.trace_window)))

    @property
    def enabled(self) -> bool:
        return self.mode != TelemetryMode.OFF

    def start(self) -> int:
        return time.perf_counter_ns() if self.enabled else 0

    def record_lookup(self, elapsed_ns: int, *, hit: bool, cold: bool = False, error_code: int = 0, route_id: int = 0) -> None:
        if self.mode == TelemetryMode.OFF:
            return
        elapsed = max(0, int(elapsed_ns))
        rec = self.record
        if hit:
            rec["hits"][0] += np.uint64(1)
        else:
            rec["misses"][0] += np.uint64(1)
        if cold:
            rec["cold_count"][0] += np.uint64(1)
        bucket = self.latency_policy.classify(elapsed)
        if bucket >= LatencyBucket.SLOW:
            rec["slow_count"][0] += np.uint64(1)
        rec["last_ns"][0] = np.uint64(elapsed)
        previous_total = int(rec["hits"][0] + rec["misses"][0])
        if previous_total <= 1:
            rec["avg_ns"][0] = np.uint64(elapsed)
        else:
            old_avg = int(rec["avg_ns"][0])
            rec["avg_ns"][0] = np.uint64(old_avg + ((elapsed - old_avg) // previous_total))
        if elapsed > int(rec["max_ns"][0]):
            rec["max_ns"][0] = np.uint64(elapsed)
        rec["last_error_code"][0] = np.uint32(error_code)
        rec["bucket"][0] = np.uint8(bucket)
        if self.mode == TelemetryMode.TRACE:
            self._trace.append(TraceRecord(time.time_ns(), int(route_id), elapsed, int(error_code), int(bucket)))

    def snapshot(self) -> Dict[str, int | str]:
        rec = self.record[0]
        return {
            "mode": self.mode.name.lower(),
            "hits": int(rec["hits"]),
            "misses": int(rec["misses"]),
            "cold_count": int(rec["cold_count"]),
            "slow_count": int(rec["slow_count"]),
            "last_ns": int(rec["last_ns"]),
            "avg_ns": int(rec["avg_ns"]),
            "max_ns": int(rec["max_ns"]),
            "last_error_code": int(rec["last_error_code"]),
            "bucket": LatencyBucket(int(rec["bucket"])).name.lower(),
        }

    def trace_snapshot(self) -> List[Dict[str, int]]:
        return [r.__dict__.copy() for r in list(self._trace)]

    def restore_snapshot(self, data: Dict[str, int | str]) -> None:
        if not data:
            return
        rec = self.record
        for key in ("hits", "misses", "cold_count", "slow_count", "last_ns", "avg_ns", "max_ns"):
            if key in data:
                rec[key][0] = np.uint64(int(data[key]))
        if "last_error_code" in data:
            rec["last_error_code"][0] = np.uint32(int(data["last_error_code"]))
        if "bucket" in data:
            b = data["bucket"]
            rec["bucket"][0] = np.uint8(LatencyBucket[str(b).upper()] if isinstance(b, str) and str(b).upper() in LatencyBucket.__members__ else int(b))


# =============================================================================
# v2.3 Observation Layer
# =============================================================================

@dataclass(slots=True, frozen=True)
class TelemetrySnapshot:
    """Immutable dashboard-facing snapshot.

    This is intentionally plain data. The browser/admin panel should consume this
    snapshot rather than touching directory, radix, index, or persistence objects.
    """

    schema_version: int
    created_at: float
    uptime_seconds: float
    performance: Dict[str, float | int | str]
    storage: Dict[str, float | int | str]
    indexes: Dict[str, object]
    behavior: Dict[str, object]
    recommendations: List[Dict[str, str]]
    components: Dict[str, Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "uptime_seconds": self.uptime_seconds,
            "performance": dict(self.performance),
            "storage": dict(self.storage),
            "indexes": dict(self.indexes),
            "behavior": dict(self.behavior),
            "recommendations": list(self.recommendations),
            "components": {k: dict(v) for k, v in self.components.items()},
        }


class TelemetryManager:
    """Low-interference observation manager for v2.3.

    The hot path performs only simple counter/timer updates. Snapshot assembly is
    cached and throttled so the dashboard can refresh without repeatedly walking
    TDS internals. Optional sampler callables may provide light subsystem stats;
    they are invoked only when the cache expires or when force=True.
    """

    schema_version = 1

    def __init__(self, *, snapshot_interval_seconds: float = 2.0, enabled: bool = True):
        import threading
        self.enabled = bool(enabled)
        self.snapshot_interval_seconds = max(0.25, float(snapshot_interval_seconds))
        self._created_at = time.time()
        self._lock = threading.RLock()
        self._counters: Dict[str, int] = {
            "reads": 0,
            "writes": 0,
            "deletes": 0,
            "lookups": 0,
            "lookup_hits": 0,
            "lookup_misses": 0,
            "errors": 0,
            "chunks_created": 0,
            "bytes_raw": 0,
            "bytes_stored": 0,
            "gil_released_ops": 0,
            "native_backend_ops": 0,
            "python_backend_ops": 0,
            "python_native_transitions": 0,
            "native_batch_ops": 0,
            "native_execution_ns": 0,
            "python_execution_ns": 0,
            "gil_released_ns": 0,
            "spiral_runs": 0,
            "spiral_search_traces": 0,
            "spiral_trace_sets": 0,
            "spiral_aggregations": 0,
            "spiral_finals": 0,
            "pool_reuse_count": 0,
            "pool_allocator_calls": 0,
        }
        self._timers_ns: Dict[str, int] = {
            "read_ns": 0,
            "write_ns": 0,
            "lookup_ns": 0,
            "chunk_ns": 0,
            "persistence_flush_ns": 0,
        }
        self._timer_counts: Dict[str, int] = {k: 0 for k in self._timers_ns}
        self._components: Dict[str, Dict[str, object]] = {}
        self._samplers: Dict[str, object] = {}
        self._last_snapshot_at = 0.0
        self._last_snapshot: Dict[str, object] | None = None

    def register_sampler(self, name: str, sampler) -> None:
        with self._lock:
            self._samplers[str(name)] = sampler
            self._last_snapshot = None

    def set_component(self, name: str, *, status: str = "healthy", **fields: object) -> None:
        if not self.enabled:
            return
        with self._lock:
            current = dict(self._components.get(name, {}))
            current.update(fields)
            current["status"] = status
            current["updated_at"] = time.time()
            self._components[name] = current

    def incr(self, key: str, amount: int = 1) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._counters[key] = int(self._counters.get(key, 0)) + int(amount)

    def add_bytes(self, *, raw: int = 0, stored: int = 0) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._counters["bytes_raw"] += max(0, int(raw))
            self._counters["bytes_stored"] += max(0, int(stored))

    def record_timer(self, key: str, elapsed_ns: int) -> None:
        if not self.enabled:
            return
        elapsed = max(0, int(elapsed_ns))
        with self._lock:
            if key not in self._timers_ns:
                self._timers_ns[key] = 0
                self._timer_counts[key] = 0
            self._timers_ns[key] += elapsed
            self._timer_counts[key] += 1

    def record_execution(self, *, python_ns: int = 0, native_ns: int = 0, gil_released_ns: int = 0,
                         transitions: int = 0, native_ops: int = 0, python_ops: int = 0,
                         batch_ops: int = 0) -> None:
        """Record execution-mode telemetry for performance engineering.

        This is intentionally approximate. It measures where TDS work is
        performed at subsystem boundaries: Python orchestration, native code,
        and native code run while the GIL is released. The dashboard uses this
        as engineering feedback; it is not a profiler and it does not inspect
        payload content.
        """
        if not self.enabled:
            return
        with self._lock:
            self._counters["python_execution_ns"] += max(0, int(python_ns))
            self._counters["native_execution_ns"] += max(0, int(native_ns))
            self._counters["gil_released_ns"] += max(0, int(gil_released_ns))
            self._counters["python_native_transitions"] += max(0, int(transitions))
            self._counters["native_backend_ops"] += max(0, int(native_ops))
            self._counters["python_backend_ops"] += max(0, int(python_ops))
            self._counters["native_batch_ops"] += max(0, int(batch_ops))
            self._counters["gil_released_ops"] += 1 if gil_released_ns or native_ops else 0

    def merge_native_execution_stats(self, stats: Dict[str, object]) -> None:
        """Merge optional native-extension execution counters into telemetry.

        Native counters are cumulative. This method records a safe snapshot of
        the current totals so the dashboard can display the state even if the
        Python hot path has not explicitly recorded every native transition.
        """
        if not self.enabled or not isinstance(stats, dict):
            return
        with self._lock:
            for src, dst in (
                ("python_native_transitions", "python_native_transitions"),
                ("gil_released_calls", "gil_released_ops"),
                ("native_batch_lookup_calls", "native_batch_ops"),
                ("native_batch_put_calls", "native_batch_ops"),
                ("native_batch_pop_calls", "native_batch_ops"),
                ("pool_reuse_count", "pool_reuse_count"),
                ("pool_allocator_calls", "pool_allocator_calls"),
            ):
                if src in stats:
                    self._counters[dst] = max(int(self._counters.get(dst, 0)), int(stats.get(src) or 0))
            native_calls = sum(int(stats.get(k) or 0) for k in (
                "native_put_calls", "native_lookup_calls", "native_batch_lookup_calls",
                "native_pop_calls", "native_batch_put_calls", "native_batch_pop_calls",
                "native_stats_calls", "native_checksum_calls", "native_chunk_scan_calls"
            ))
            self._counters["native_backend_ops"] = max(int(self._counters.get("native_backend_ops", 0)), native_calls)

    def record_read(self, elapsed_ns: int, *, hit: bool = True, backend: str = "") -> None:
        self.incr("reads")
        self.incr("lookups")
        self.incr("lookup_hits" if hit else "lookup_misses")
        self.record_timer("read_ns", elapsed_ns)
        self.record_timer("lookup_ns", elapsed_ns)
        if backend:
            is_native = "native" in backend.lower()
            self.incr("native_backend_ops" if is_native else "python_backend_ops")
            if is_native:
                self.incr("gil_released_ops")

    def record_write(self, elapsed_ns: int, *, raw_size: int = 0, stored_size: int = 0, backend: str = "") -> None:
        self.incr("writes")
        self.record_timer("write_ns", elapsed_ns)
        self.add_bytes(raw=raw_size, stored=stored_size)
        if backend:
            is_native = "native" in backend.lower()
            self.incr("native_backend_ops" if is_native else "python_backend_ops")
            if is_native:
                self.incr("gil_released_ops")

    def record_delete(self) -> None:
        self.incr("deletes")

    def record_error(self) -> None:
        self.incr("errors")

    def record_chunk(self, count: int, elapsed_ns: int = 0) -> None:
        self.incr("chunks_created", count)
        if elapsed_ns:
            self.record_timer("chunk_ns", elapsed_ns)

    def record_spiral_event(self, kind: str, amount: int = 1) -> None:
        """Record optional Spiral-compatible pipeline activity.

        These counters describe trace-shaped storage behavior only. They do not
        imply that TDS ranked, reasoned, rewarded, trained, or aggregated.
        """
        key_map = {
            "run_created": "spiral_runs",
            "search_trace": "spiral_search_traces",
            "trace_set": "spiral_trace_sets",
            "aggregation": "spiral_aggregations",
            "final": "spiral_finals",
        }
        self.incr(key_map.get(str(kind), str(kind)), amount)

    def _average_ms(self, total_key: str) -> float:
        total = int(self._timers_ns.get(total_key, 0))
        count = max(1, int(self._timer_counts.get(total_key, 0)))
        return (total / count) / 1_000_000.0

    def _behavior(self, counters: Dict[str, int]) -> Dict[str, object]:
        reads = counters.get("reads", 0)
        writes = counters.get("writes", 0)
        total_rw = max(1, reads + writes)
        read_pct = round(100.0 * reads / total_rw, 2)
        write_pct = round(100.0 * writes / total_rw, 2)
        if read_pct >= 70:
            mode = "read-heavy"
        elif write_pct >= 60:
            mode = "write-heavy"
        elif reads + writes == 0:
            mode = "idle"
        else:
            mode = "balanced"
        stored = max(1, counters.get("bytes_stored", 0))
        ratio = counters.get("bytes_raw", 0) / stored
        spiral_events = (
            counters.get("spiral_search_traces", 0)
            + counters.get("spiral_trace_sets", 0)
            + counters.get("spiral_aggregations", 0)
            + counters.get("spiral_finals", 0)
        )
        return {
            "workload_mode": mode,
            "read_percent": read_pct,
            "write_percent": write_pct,
            "compression_ratio": round(ratio, 3),
            "pressure": "low" if counters.get("errors", 0) == 0 else "attention",
            "current_operation": "trace_pipeline" if spiral_events else "idle",
            "spiral_trace_activity": spiral_events,
        }

    def _recommendations(self, counters: Dict[str, int], indexes: Dict[str, object], behavior: Dict[str, object]) -> List[Dict[str, str]]:
        recs: List[Dict[str, str]] = []
        ratio = float(behavior.get("compression_ratio", 0.0))
        if counters.get("bytes_raw", 0) > 0 and ratio < 1.10:
            recs.append({"severity": "info", "code": "LOW_COMPRESSION_GAIN", "message": "Compression gain is low; compression may not be beneficial for this workload."})
        swiss = indexes.get("swiss", {}) if isinstance(indexes.get("swiss"), dict) else {}
        avg_probe = float(swiss.get("average_probe", swiss.get("avg_probe", 0.0)) or 0.0)
        max_probe = int(swiss.get("max_probe", 0) or 0)
        if avg_probe >= 3.0 or max_probe >= 16:
            recs.append({"severity": "warning", "code": "SWISS_PROBE_PRESSURE", "message": "Swiss index probe pressure is high; consider resize or rebuild."})
        if counters.get("lookup_misses", 0) > counters.get("lookup_hits", 0) and counters.get("lookups", 0) > 100:
            recs.append({"severity": "info", "code": "MISS_HEAVY_LOOKUPS", "message": "Lookup misses exceed hits; verify namespace/key access patterns."})
        return recs

    def snapshot(self, *, force: bool = False) -> Dict[str, object]:
        now = time.time()
        with self._lock:
            if (not force and self._last_snapshot is not None and
                    (now - self._last_snapshot_at) < self.snapshot_interval_seconds):
                return dict(self._last_snapshot)
            counters = dict(self._counters)
            timer_counts = dict(self._timer_counts)
            uptime = max(0.001, now - self._created_at)
            indexes: Dict[str, object] = {}
            storage_extra: Dict[str, object] = {}
            components = {k: dict(v) for k, v in self._components.items()}
            samplers = dict(self._samplers)
        # Invoke samplers outside the manager lock.
        for name, sampler in samplers.items():
            try:
                value = sampler()
                if name in {"swiss", "radix"}:
                    indexes[name] = value
                elif name == "storage":
                    storage_extra.update(value if isinstance(value, dict) else {"value": value})
                elif name == "components" and isinstance(value, dict):
                    for ck, cv in value.items():
                        components[str(ck)] = dict(cv) if isinstance(cv, dict) else {"value": cv}
                else:
                    indexes[name] = value
            except Exception as exc:  # samplers should never break dashboard status
                components[f"sampler:{name}"] = {"status": "degraded", "error": str(exc), "updated_at": now}
        with self._lock:
            performance: Dict[str, float | int | str] = {
                "reads_per_sec": round(counters.get("reads", 0) / uptime, 3),
                "writes_per_sec": round(counters.get("writes", 0) / uptime, 3),
                "lookups_per_sec": round(counters.get("lookups", 0) / uptime, 3),
                "avg_read_ms": round(self._average_ms("read_ns"), 4),
                "avg_write_ms": round(self._average_ms("write_ns"), 4),
                "avg_lookup_ms": round(self._average_ms("lookup_ns"), 4),
                "read_count": counters.get("reads", 0),
                "write_count": counters.get("writes", 0),
                "lookup_count": counters.get("lookups", 0),
                "lookup_hits": counters.get("lookup_hits", 0),
                "lookup_misses": counters.get("lookup_misses", 0),
                "native_backend_ops": counters.get("native_backend_ops", 0),
                "python_backend_ops": counters.get("python_backend_ops", 0),
                "gil_released_ops": counters.get("gil_released_ops", 0),
                "python_native_transitions": counters.get("python_native_transitions", 0),
                "python_native_transitions_per_sec": round(counters.get("python_native_transitions", 0) / uptime, 3),
                "native_batch_ops": counters.get("native_batch_ops", 0),
                "native_batch_ops_per_sec": round(counters.get("native_batch_ops", 0) / uptime, 3),
                "pool_reuse_count": counters.get("pool_reuse_count", 0),
                "pool_allocator_calls": counters.get("pool_allocator_calls", 0),
                "pool_reuse_percent": round(100.0 * counters.get("pool_reuse_count", 0) / max(1, counters.get("pool_reuse_count", 0) + counters.get("pool_allocator_calls", 0)), 2),
                "timer_samples": sum(timer_counts.values()),
            }
            native_ops = float(performance.get("native_backend_ops", 0) or 0)
            python_ops = float(performance.get("python_backend_ops", 0) or 0)
            total_ops = max(1.0, native_ops + python_ops)
            performance["native_execution_percent"] = round(100.0 * native_ops / total_ops, 2)
            performance["python_execution_percent"] = round(100.0 * python_ops / total_ops, 2)
            performance["gil_released_percent"] = round(100.0 * min(float(performance.get("gil_released_ops", 0) or 0), total_ops) / total_ops, 2)
            storage: Dict[str, float | int | str] = {
                "bytes_raw": counters.get("bytes_raw", 0),
                "bytes_stored": counters.get("bytes_stored", 0),
                "chunks_created": counters.get("chunks_created", 0),
                "deletes": counters.get("deletes", 0),
                "errors": counters.get("errors", 0),
            }
            storage.update(storage_extra)
            spiral = {
                "enabled": True,
                "mode": "neutral-trace-storage",
                "runs": counters.get("spiral_runs", 0),
                "search_traces": counters.get("spiral_search_traces", 0),
                "trace_sets": counters.get("spiral_trace_sets", 0),
                "aggregations": counters.get("spiral_aggregations", 0),
                "final_outputs": counters.get("spiral_finals", 0),
                "ranking_owner": "external",
            }
            storage["spiral"] = spiral
            behavior = self._behavior(counters)
            recs = self._recommendations(counters, indexes, behavior)
            snap = TelemetrySnapshot(
                schema_version=self.schema_version,
                created_at=now,
                uptime_seconds=round(uptime, 3),
                performance=performance,
                storage=storage,
                indexes=indexes,
                behavior=behavior,
                recommendations=recs,
                components=components,
            ).to_dict()
            self._last_snapshot_at = now
            self._last_snapshot = snap
            return dict(snap)

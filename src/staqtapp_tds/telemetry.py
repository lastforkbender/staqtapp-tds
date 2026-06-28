"""Directory telemetry for Staqtapp-TDS v1.7.0."""
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


@dataclass(frozen=True)
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

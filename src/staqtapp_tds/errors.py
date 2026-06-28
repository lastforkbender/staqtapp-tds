"""Lightweight error telemetry; never replaces explicit Result statuses."""
from __future__ import annotations
import time
from collections import deque, Counter
from dataclasses import dataclass
from enum import IntEnum
from typing import Deque, Dict, List

class ErrorLogMode(IntEnum):
    OFF = 0
    LIGHT = 1
    TRACE = 2

@dataclass(frozen=True)
class ErrorRecord:
    time_ns: int
    code: str
    path: str = ""
    name: str = ""
    severity: str = "info"

class ErrorTelemetry:
    def __init__(self, mode: ErrorLogMode = ErrorLogMode.LIGHT, trace_window: int = 256):
        self.mode = ErrorLogMode(mode)
        self._counts: Counter[str] = Counter()
        self._last: ErrorRecord | None = None
        self._trace: Deque[ErrorRecord] = deque(maxlen=max(1, int(trace_window)))

    def record(self, code: str, *, path: str = "", name: str = "", severity: str = "info") -> None:
        if self.mode == ErrorLogMode.OFF:
            return
        rec = ErrorRecord(time.time_ns(), str(code), path, name, severity)
        self._counts[rec.code] += 1
        self._last = rec
        if self.mode == ErrorLogMode.TRACE:
            self._trace.append(rec)

    def snapshot(self) -> Dict[str, object]:
        return {
            "mode": self.mode.name.lower(),
            "counts": dict(self._counts),
            "last": None if self._last is None else self._last.__dict__.copy(),
            "trace": [r.__dict__.copy() for r in self._trace],
        }

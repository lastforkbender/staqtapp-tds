"""
Latency helpers for Staqtapp-TDS v1.7.0.

The VFS records operational timing only. It does not interpret latency as
reasoning quality; callers above the VFS may do that if they choose.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class LatencyBucket(IntEnum):
    HOT = 0
    WARM = 1
    COLD = 2
    SLOW = 3
    TIMEOUT = 4


def classify_latency(actual_ns: int, expected_ns: int, soft_limit_ns: int = 0, hard_limit_ns: int = 0) -> LatencyBucket:
    """Classify a lookup duration using integer-only thresholds."""
    actual = max(0, int(actual_ns))
    expected = max(1, int(expected_ns or 1))
    soft = int(soft_limit_ns or expected * 2)
    hard = int(hard_limit_ns or expected * 20)
    if actual >= hard:
        return LatencyBucket.TIMEOUT
    if actual >= soft:
        return LatencyBucket.SLOW
    if actual <= expected // 2:
        return LatencyBucket.HOT
    if actual <= expected:
        return LatencyBucket.WARM
    return LatencyBucket.COLD


def latency_ratio(actual_ns: int, expected_ns: int) -> float:
    return float(max(0, int(actual_ns))) / float(max(1, int(expected_ns or 1)))


@dataclass(frozen=True)
class LatencyPolicy:
    expected_lookup_ns: int = 50_000
    soft_limit_ns: int = 100_000
    hard_limit_ns: int = 1_000_000

    def classify(self, actual_ns: int) -> LatencyBucket:
        return classify_latency(actual_ns, self.expected_lookup_ns, self.soft_limit_ns, self.hard_limit_ns)

    def ratio(self, actual_ns: int) -> float:
        return latency_ratio(actual_ns, self.expected_lookup_ns)

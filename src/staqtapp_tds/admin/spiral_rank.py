"""Admin-facing Spiral Rank telemetry snapshots.

This module intentionally lives in the admin layer. It observes immutable
``SpiralRankRun``/``SpiralRankStats`` data records produced elsewhere and shapes them
for the browser Operations Console. It does not invoke ranking by itself, read
payloads, mutate storage, or feed decisions back into the native engine.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import time
from typing import Any, Deque, Iterable

from staqtapp_tds.spiral.rank import SpiralRankRecord, SpiralRankRun, SpiralRankStats


def _stats_to_dict(stats: SpiralRankStats | None) -> dict[str, Any]:
    if stats is None:
        return {}
    return stats.to_dict() if hasattr(stats, "to_dict") else dict(stats)  # type: ignore[arg-type]


def _result_to_dict(result: SpiralRankRecord | Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return dict(result)
    return {
        "trace_id": str(getattr(result, "trace_id", "unknown")),
        "score": float(getattr(result, "score", 0.0)),
        "source_score": float(getattr(result, "source_score", 0.0)),
        "confidence": float(getattr(result, "confidence", 0.0)),
        "depth": int(getattr(result, "depth", 0)),
        "age_ns": int(getattr(result, "age_ns", 0)),
        "rank": int(getattr(result, "rank", 0)),
        "native": bool(getattr(result, "native", False)),
        "config_id": str(getattr(result, "config_id", "")),
    }


@dataclass
class SpiralRankTelemetry:
    """Loss-tolerant observer cache for Spiral Rank browser telemetry."""

    history_limit: int = 64
    top_limit: int = 8
    _last_run: SpiralRankRun | None = None
    _history: Deque[dict[str, Any]] = field(default_factory=deque)
    _total_runs: int = 0
    _native_runs: int = 0
    _fallback_runs: int = 0
    _total_ranked: int = 0
    _total_dropped_by_limit: int = 0

    def observe_run(self, run: SpiralRankRun) -> None:
        """Record a completed rank run for cached browser feedback."""
        self._last_run = run
        stats = run.stats
        self._total_runs += 1
        if stats.native:
            self._native_runs += 1
        else:
            self._fallback_runs += 1
        self._total_ranked += int(stats.ranked_count)
        self._total_dropped_by_limit += int(stats.dropped_by_limit)
        self._history.append({
            "created_at": time(),
            "engine": stats.engine,
            "native": stats.native,
            "input_count": stats.input_count,
            "ranked_count": stats.ranked_count,
            "limited_count": stats.limited_count,
            "dropped_by_limit": stats.dropped_by_limit,
            "elapsed_ms": stats.elapsed_ms,
            "scoring_ms": stats.scoring_ms,
            "sorting_ms": stats.sorting_ms,
            "shaping_ms": stats.shaping_ms,
            "mean_score": stats.mean_score,
            "max_score": stats.max_score,
            "min_score": stats.min_score,
            "config_id": stats.config_id,
        })
        while len(self._history) > self.history_limit:
            self._history.popleft()

    def observe_stats(self, stats: SpiralRankStats, results: Iterable[SpiralRankRecord] | None = None) -> None:
        """Record stats with optional result rows as a synthetic run bundle."""
        self.observe_run(SpiralRankRun(records=tuple(results or ()), stats=stats))

    @property
    def last_stats(self) -> SpiralRankStats | None:
        return self._last_run.stats if self._last_run else None

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe immutable snapshot for the admin status payload."""
        history = list(self._history)
        last = self._last_run
        stats = last.stats if last else None
        results = tuple(last.results) if last else ()
        native_pct = (self._native_runs / self._total_runs * 100.0) if self._total_runs else 0.0
        fallback_pct = (self._fallback_runs / self._total_runs * 100.0) if self._total_runs else 0.0
        avg_elapsed = (sum(float(h.get("elapsed_ms") or 0.0) for h in history) / len(history)) if history else 0.0
        avg_ranked = (self._total_ranked / self._total_runs) if self._total_runs else 0.0
        top_results = sorted((_result_to_dict(r) for r in results), key=lambda r: int(r.get("rank") or 0))[: self.top_limit]
        return {
            "enabled": True,
            "observer_only": True,
            "status": "ready" if stats else "waiting",
            "runs_total": self._total_runs,
            "native_runs": self._native_runs,
            "fallback_runs": self._fallback_runs,
            "native_percent": native_pct,
            "fallback_percent": fallback_pct,
            "total_ranked": self._total_ranked,
            "total_dropped_by_limit": self._total_dropped_by_limit,
            "average_elapsed_ms": avg_elapsed,
            "average_ranked_count": avg_ranked,
            "last_stats": _stats_to_dict(stats),
            "top_results": top_results,
            "history": history[-24:],
            "updated_at": history[-1]["created_at"] if history else None,
        }


def spiral_rank_snapshot_from(source: Any | None) -> dict[str, Any]:
    """Best-effort extraction of Spiral Rank telemetry from an arbitrary source."""
    if source is None:
        return SpiralRankTelemetry().snapshot()
    if hasattr(source, "spiral_rank_snapshot"):
        return source.spiral_rank_snapshot()
    if hasattr(source, "spiral_rank_telemetry"):
        telemetry = source.spiral_rank_telemetry
        if hasattr(telemetry, "snapshot"):
            return telemetry.snapshot()
    if hasattr(source, "last_spiral_rank_run"):
        run = source.last_spiral_rank_run
        telemetry = SpiralRankTelemetry()
        if run is not None:
            telemetry.observe_run(run)
        return telemetry.snapshot()
    if hasattr(source, "last_stats"):
        stats = source.last_stats
        telemetry = SpiralRankTelemetry()
        if stats is not None:
            telemetry.observe_stats(stats)
        return telemetry.snapshot()
    return SpiralRankTelemetry().snapshot()

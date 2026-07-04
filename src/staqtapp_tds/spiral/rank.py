"""Native Spiral rank scoring support for caller-owned trace workflows.

The engine scores caller-supplied numeric metadata only. It does not read TDS
payloads, choose policies, reward traces, train models, or mutate storage. The C
extension performs the tight score loop when available; Python owns validation,
stable sorting, run statistics, and record shaping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Iterable, Sequence, Any

try:  # pragma: no cover - availability depends on build platform
    from staqtapp_tds import _native_index as _native
except Exception:  # pragma: no cover
    _native = None

from staqtapp_tds.result import TDSResult, TDSResultCode


@dataclass(frozen=True)
class SpiralRankConfig:
    score_weight: float = 0.72
    confidence_weight: float = 0.18
    depth_penalty: float = 0.035
    age_penalty: float = 0.000001
    config_id: str = "tds-native-spiral-rank-v288"


@dataclass(frozen=True)
class SpiralRankStats:
    """Immutable per-run observer statistics for Spiral ranking.

    These values describe a rank invocation after it has completed. They are
    intentionally advisory: they do not feed back into storage, policy, or rank
    control. The object is safe to export through telemetry or logs.
    """

    input_count: int
    ranked_count: int
    limited_count: int
    dropped_by_limit: int
    native: bool
    elapsed_ns: int
    scoring_ns: int
    sorting_ns: int
    shaping_ns: int
    min_score: float | None
    max_score: float | None
    mean_score: float | None
    config_id: str
    engine: str = "native" 
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def limit_applied(self) -> bool:
        return self.dropped_by_limit > 0

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed_ns / 1_000_000.0

    @property
    def scoring_ms(self) -> float:
        return self.scoring_ns / 1_000_000.0

    @property
    def sorting_ms(self) -> float:
        return self.sorting_ns / 1_000_000.0

    @property
    def shaping_ms(self) -> float:
        return self.shaping_ns / 1_000_000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_count": self.input_count,
            "ranked_count": self.ranked_count,
            "limited_count": self.limited_count,
            "dropped_by_limit": self.dropped_by_limit,
            "limit_applied": self.limit_applied,
            "native": self.native,
            "engine": self.engine,
            "elapsed_ns": self.elapsed_ns,
            "elapsed_ms": self.elapsed_ms,
            "scoring_ns": self.scoring_ns,
            "scoring_ms": self.scoring_ms,
            "sorting_ns": self.sorting_ns,
            "sorting_ms": self.sorting_ms,
            "shaping_ns": self.shaping_ns,
            "shaping_ms": self.shaping_ms,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "mean_score": self.mean_score,
            "config_id": self.config_id,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SpiralRankRecord:
    trace_id: str
    score: float
    source_score: float
    confidence: float
    depth: int
    age_ns: int
    rank: int
    native: bool
    config_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "score": self.score,
            "source_score": self.source_score,
            "confidence": self.confidence,
            "depth": self.depth,
            "age_ns": self.age_ns,
            "rank": self.rank,
            "native": self.native,
            "config_id": self.config_id,
        }


@dataclass(frozen=True, init=False)
class SpiralRankRun:
    """Rank output plus immutable observer statistics."""

    records: tuple[SpiralRankRecord, ...]
    stats: SpiralRankStats

    def __init__(self, records: Iterable[SpiralRankRecord] | None = None, stats: SpiralRankStats | None = None, **legacy: Any) -> None:
        if records is None and "results" in legacy:
            records = legacy.pop("results")
        if legacy:
            raise TypeError(f"unexpected SpiralRankRun argument(s): {', '.join(sorted(legacy))}")
        if stats is None:
            raise TypeError("stats is required")
        object.__setattr__(self, "records", tuple(records or ()))
        object.__setattr__(self, "stats", stats)

    @property
    def results(self) -> tuple[SpiralRankRecord, ...]:
        """Backward-compatible alias for record rows, not a result envelope."""
        return self.records

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "results": [r.to_dict() for r in self.records],  # legacy JSON key
            "stats": self.stats.to_dict(),
        }


def _materialize(values: Iterable[Any] | None, default: Any | None = None, *, n: int | None = None) -> list[Any]:
    if values is None:
        if n is None:
            raise ValueError("n is required when values is None")
        return [default for _ in range(n)]
    return list(values)


def _score_python(scores: Sequence[float], confidences: Sequence[float], depths: Sequence[int], ages_ns: Sequence[int], config: SpiralRankConfig) -> list[float]:
    out: list[float] = []
    for source, conf, depth, age in zip(scores, confidences, depths, ages_ns):
        base = min(1.0, max(0.0, float(source)))
        c = min(1.0, max(0.0, float(conf)))
        d = max(0, int(depth))
        a = max(0, int(age))
        out.append((base * config.score_weight) + (c * config.confidence_weight) - (config.depth_penalty * d) - (config.age_penalty * a))
    return out


def _score_bounds(values: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    total = float(sum(values))
    return float(min(values)), float(max(values)), total / len(values)


class NativeSpiralRankEngine:
    """Deterministic scorer/sorter for Spiral-compatible trace metadata."""

    def __init__(self, config: SpiralRankConfig | None = None, *, prefer_native: bool = True):
        self.config = config or SpiralRankConfig()
        self.prefer_native = bool(prefer_native)
        self.last_stats: SpiralRankStats | None = None

    @property
    def native_available(self) -> bool:
        return bool(self.prefer_native and _native is not None and hasattr(_native, "spiral_rank_scores"))

    def score_many(
        self,
        scores: Iterable[float],
        confidences: Iterable[float] | None = None,
        depths: Iterable[int] | None = None,
        ages_ns: Iterable[int] | None = None,
    ) -> list[float]:
        source_scores = [float(x) for x in scores]
        n = len(source_scores)
        conf = [float(x) for x in _materialize(confidences, 1.0, n=n)]
        depth = [int(x) for x in _materialize(depths, 0, n=n)]
        age = [int(x) for x in _materialize(ages_ns, 0, n=n)]
        if not (len(conf) == len(depth) == len(age) == n):
            raise ValueError("scores, confidences, depths, and ages_ns must have the same length")
        if self.native_available:
            return [float(x) for x in _native.spiral_rank_scores(
                source_scores, conf, depth, age,
                self.config.score_weight,
                self.config.confidence_weight,
                self.config.depth_penalty,
                self.config.age_penalty,
            )]
        return _score_python(source_scores, conf, depth, age, self.config)

    def rank_run(
        self,
        trace_ids: Iterable[str],
        scores: Iterable[float],
        confidences: Iterable[float] | None = None,
        depths: Iterable[int] | None = None,
        ages_ns: Iterable[int] | None = None,
        *,
        limit: int | None = None,
        descending: bool = True,
    ) -> SpiralRankRun:
        run_start = perf_counter_ns()
        ids = [str(x) for x in trace_ids]
        source_scores = [float(x) for x in scores]
        n = len(ids)
        conf = [float(x) for x in _materialize(confidences, 1.0, n=n)]
        depth = [int(x) for x in _materialize(depths, 0, n=n)]
        age = [int(x) for x in _materialize(ages_ns, 0, n=n)]
        if not (len(source_scores) == len(conf) == len(depth) == len(age) == n):
            raise ValueError("trace_ids, scores, confidences, depths, and ages_ns must have the same length")

        native = self.native_available
        score_start = perf_counter_ns()
        ranked_scores = self.score_many(source_scores, conf, depth, age)
        score_end = perf_counter_ns()

        sort_start = perf_counter_ns()
        rows = list(zip(ids, ranked_scores, source_scores, conf, depth, age))
        rows.sort(key=lambda r: (r[1], r[2], -r[4], r[0]), reverse=descending)
        original_ranked_count = len(rows)
        limited_count = original_ranked_count
        if limit is not None:
            limited_count = max(0, int(limit))
            rows = rows[:limited_count]
        sort_end = perf_counter_ns()

        shape_start = perf_counter_ns()
        results = tuple(
            SpiralRankRecord(
                trace_id=tid,
                score=float(score),
                source_score=float(source),
                confidence=float(c),
                depth=int(d),
                age_ns=int(a),
                rank=i + 1,
                native=native,
                config_id=self.config.config_id,
            )
            for i, (tid, score, source, c, d, a) in enumerate(rows)
        )
        shape_end = perf_counter_ns()
        min_score, max_score, mean_score = _score_bounds([r.score for r in results])
        warnings: list[str] = []
        if self.prefer_native and not native:
            warnings.append("native spiral rank extension unavailable; used Python fallback")
        dropped = max(0, original_ranked_count - len(results))
        stats = SpiralRankStats(
            input_count=n,
            ranked_count=original_ranked_count,
            limited_count=len(results),
            dropped_by_limit=dropped,
            native=native,
            engine="native" if native else "python",
            elapsed_ns=shape_end - run_start,
            scoring_ns=score_end - score_start,
            sorting_ns=sort_end - sort_start,
            shaping_ns=shape_end - shape_start,
            min_score=min_score,
            max_score=max_score,
            mean_score=mean_score,
            config_id=self.config.config_id,
            warnings=tuple(warnings),
        )
        self.last_stats = stats
        return SpiralRankRun(records=results, stats=stats)

    def rank(
        self,
        trace_ids: Iterable[str],
        scores: Iterable[float],
        confidences: Iterable[float] | None = None,
        depths: Iterable[int] | None = None,
        ages_ns: Iterable[int] | None = None,
        *,
        limit: int | None = None,
        descending: bool = True,
    ) -> list[SpiralRankRecord]:
        return list(self.rank_run(
            trace_ids,
            scores,
            confidences,
            depths,
            ages_ns,
            limit=limit,
            descending=descending,
        ).records)

    def rank_result(
        self,
        trace_ids: Iterable[str],
        scores: Iterable[float],
        confidences: Iterable[float] | None = None,
        depths: Iterable[int] | None = None,
        ages_ns: Iterable[int] | None = None,
        *,
        limit: int | None = None,
        descending: bool = True,
    ) -> TDSResult:
        """AI-safe rank surface: always returns TDSResult, never raises."""
        try:
            run = self.rank_run(trace_ids, scores, confidences, depths, ages_ns, limit=limit, descending=descending)
            return TDSResult.success(
                TDSResultCode.SPIRAL_RANK_OK,
                "Spiral rank completed.",
                value=run.to_dict(),
                meta={"stats": run.stats.to_dict(), "record_count": len(run.records)},
            )
        except Exception as exc:  # pragma: no cover - exercised through invalid caller input
            return TDSResult.from_exception(TDSResultCode.SPIRAL_RANK_ERROR, exc)


def rank_traces(trace_ids: Iterable[str], scores: Iterable[float], **kwargs: Any) -> list[SpiralRankRecord]:
    return NativeSpiralRankEngine().rank(trace_ids, scores, **kwargs)


def rank_trace_run(trace_ids: Iterable[str], scores: Iterable[float], **kwargs: Any) -> SpiralRankRun:
    return NativeSpiralRankEngine().rank_run(trace_ids, scores, **kwargs)


def rank_trace_result(trace_ids: Iterable[str], scores: Iterable[float], **kwargs: Any) -> TDSResult:
    return NativeSpiralRankEngine().rank_result(trace_ids, scores, **kwargs)

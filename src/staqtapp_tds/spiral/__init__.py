"""Optional Spiral-compatible trace/provenance support.

This package does not implement Spiral reasoning. It provides neutral TDS storage
helpers for trace runs, trace-set manifests, aggregation records, ranking metadata,
and provenance links.
"""
from staqtapp_tds.spiral.trace import TraceRecord, TraceRole
from staqtapp_tds.spiral.manifest import TraceSetManifest
from staqtapp_tds.spiral.provenance import AggregationRecord
from staqtapp_tds.spiral.run import SpiralRun, SpiralRunMetadata, create_spiral_run, DEFAULT_SPIRAL_ROOT
from staqtapp_tds.spiral.rank import SpiralRankConfig, SpiralRankStats, SpiralRankRecord, SpiralRankRun, NativeSpiralRankEngine, rank_traces, rank_trace_run, rank_trace_result

__all__ = [
    "TraceRecord", "TraceRole", "TraceSetManifest", "AggregationRecord",
    "SpiralRun", "SpiralRunMetadata", "create_spiral_run", "DEFAULT_SPIRAL_ROOT",
    "SpiralRankConfig", "SpiralRankStats", "SpiralRankRecord", "SpiralRankRun", "NativeSpiralRankEngine", "rank_traces", "rank_trace_run", "rank_trace_result",
]

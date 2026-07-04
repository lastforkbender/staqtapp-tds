"""Optional Spiral-compatible workflow helpers for Staqtapp-TDS.

The helpers create a directory-first trace/provenance layout while keeping TDS
neutral. They store caller-supplied traces, ranks, sets, and aggregation records;
they never rank, reason, reward, train, or aggregate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time

from staqtapp_tds.spiral.trace import TraceRecord
from staqtapp_tds.spiral.manifest import TraceSetManifest
from staqtapp_tds.spiral.provenance import AggregationRecord


DEFAULT_SPIRAL_ROOT = "spiral_runs"


@dataclass(frozen=True)
class SpiralRunMetadata:
    run_id: str
    problem_id: str = ""
    created_at: float = field(default_factory=time.time)
    description: str = ""
    spiral_version: str = "neutral-trace-v1"
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "problem_id": self.problem_id,
            "created_at": self.created_at,
            "description": self.description,
            "spiral_version": self.spiral_version,
            "tags": list(self.tags),
        }


def _mkdir_if_missing(directory, name: str):
    try:
        return directory.cd(name)
    except KeyError:
        return directory.mkdir(name)


def create_spiral_run(root, run_id: str, *, problem: Any | None = None,
                      problem_id: str = "", description: str = "",
                      tags: tuple[str, ...] = ()):
    """Create ``/spiral_runs/<run_id>/`` under a TDSDirectory.

    Returns a :class:`SpiralRun` helper bound to that run directory.
    """

    runs = _mkdir_if_missing(root, DEFAULT_SPIRAL_ROOT)
    run_dir = _mkdir_if_missing(runs, run_id)
    for child in ("search_traces", "trace_sets", "aggregations", "final", "metadata"):
        _mkdir_if_missing(run_dir, child)
    meta = SpiralRunMetadata(run_id=run_id, problem_id=problem_id, description=description, tags=tags)
    run_dir.write_json("run_metadata.json", meta.to_dict(), overwrite=True)
    if problem is not None:
        # JSON-compatible problems remain readable as plain metadata. Other
        # payloads can still be written directly by callers if needed.
        run_dir.write_json("problem.json", problem, overwrite=True)
    try:
        root.telemetry_manager.record_spiral_event("run_created")
    except AttributeError:
        pass
    return SpiralRun(run_dir=run_dir, run_id=run_id)


@dataclass
class SpiralRun:
    run_dir: Any
    run_id: str

    @property
    def traces(self):
        return self.run_dir.cd("search_traces")

    @property
    def sets(self):
        return self.run_dir.cd("trace_sets")

    @property
    def aggregations(self):
        return self.run_dir.cd("aggregations")

    @property
    def final(self):
        return self.run_dir.cd("final")

    @property
    def metadata(self):
        return self.run_dir.cd("metadata")

    def store_search_trace(self, trace_id: str, content: Any, *, rank_score: float | None = None,
                           rank_source: str = "", created_by: str = "", tags: tuple[str, ...] = ()) -> TraceRecord:
        entry_name = f"{trace_id}.tds"
        self.traces.write_result(entry_name, content)
        cfg = self.run_dir.config_registry.active()
        rec = TraceRecord(
            run_id=self.run_id,
            trace_id=trace_id,
            role="search",
            content_entry=f"search_traces/{entry_name}",
            rank_score=rank_score,
            rank_source=rank_source,
            runtime_config=cfg.config_id,
            created_by=created_by,
            tags=tags,
        )
        self.metadata.write_json(f"trace_{trace_id}.json", rec.to_dict(), overwrite=True)
        self.run_dir.telemetry_manager.record_spiral_event("search_trace")
        return rec

    def create_trace_set(self, set_id: str, trace_ids: list[str] | tuple[str, ...], *,
                         set_role: str = "search_set", rank_policy: str = "external",
                         metadata: dict[str, Any] | None = None) -> TraceSetManifest:
        manifest = TraceSetManifest(
            run_id=self.run_id,
            set_id=set_id,
            trace_ids=tuple(trace_ids),
            set_role=set_role,
            rank_policy=rank_policy,
            metadata=dict(metadata or {}),
        )
        self.sets.write_json(f"{set_id}.json", manifest.to_dict(), overwrite=True)
        self.run_dir.telemetry_manager.record_spiral_event("trace_set")
        return manifest

    def store_aggregation(self, aggregation_id: str, output: Any, *, derived_from: list[str] | tuple[str, ...],
                          aggregation_step: int = 1, rank_score: float | None = None,
                          rank_source: str = "", metadata: dict[str, Any] | None = None) -> AggregationRecord:
        entry_name = f"{aggregation_id}.tds"
        self.aggregations.write_result(entry_name, output)
        rec = AggregationRecord(
            run_id=self.run_id,
            aggregation_id=aggregation_id,
            output_entry=f"aggregations/{entry_name}",
            derived_from=tuple(derived_from),
            aggregation_step=int(aggregation_step),
            rank_score=rank_score,
            rank_source=rank_source,
            metadata=dict(metadata or {}),
        )
        self.metadata.write_json(f"aggregation_{aggregation_id}.json", rec.to_dict(), overwrite=True)
        self.run_dir.telemetry_manager.record_spiral_event("aggregation")
        return rec

    def store_final(self, name: str, output: Any, *, derived_from: list[str] | tuple[str, ...] = ()) -> None:
        self.final.write_result(name, output)
        self.metadata.write_json(f"final_{name}.json", {
            "run_id": self.run_id,
            "final_entry": f"final/{name}",
            "derived_from": list(derived_from),
            "created_at": time.time(),
        }, overwrite=True)
        self.run_dir.telemetry_manager.record_spiral_event("final")

    def ranked_traces(self, *, descending: bool = True) -> list[TraceRecord]:
        records: list[TraceRecord] = []
        for name in self.metadata.ls(sort_by_prob=False):
            clean = name.replace("[dir] ", "")
            if clean.startswith("trace_") and clean.endswith(".json"):
                records.append(TraceRecord.from_mapping(self.metadata.read_value(clean)))
        return sorted(records, key=lambda r: (-1.0 if r.rank_score is None else float(r.rank_score)), reverse=descending)

    def snapshot(self) -> dict[str, Any]:
        trace_count = len([x for x in self.traces.ls(sort_by_prob=False) if not x.startswith("[dir]")])
        set_count = len([x for x in self.sets.ls(sort_by_prob=False) if not x.startswith("[dir]")])
        aggregation_count = len([x for x in self.aggregations.ls(sort_by_prob=False) if not x.startswith("[dir]")])
        final_count = len([x for x in self.final.ls(sort_by_prob=False) if not x.startswith("[dir]")])
        return {
            "run_id": self.run_id,
            "search_traces": trace_count,
            "trace_sets": set_count,
            "aggregations": aggregation_count,
            "final_outputs": final_count,
            "layout": "directory-first",
            "reasoning_owned_by": "caller",
        }

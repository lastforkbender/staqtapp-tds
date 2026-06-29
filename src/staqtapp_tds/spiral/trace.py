"""Neutral Spiral-style trace records for Staqtapp-TDS.

This module stores metadata for sequential/parallel/aggregative trace pipelines
without performing reasoning, ranking, reward assignment, or aggregation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
import time

TraceRole = Literal["problem", "search", "trace_set", "aggregation", "final"]


@dataclass(frozen=True)
class TraceRecord:
    """Metadata describing one trace-like object stored in TDS.

    Scores and ranks are external observations supplied by an agent, verifier, or
    ranker. TDS persists them for retrieval/provenance only.
    """

    run_id: str
    trace_id: str
    role: TraceRole = "search"
    created_at: float = field(default_factory=time.time)
    content_entry: str = ""
    derived_from: tuple[str, ...] = ()
    set_ids: tuple[str, ...] = ()
    rank_score: float | None = None
    rank_source: str = ""
    status: str = "stored"
    runtime_config: str = ""
    created_by: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "role": self.role,
            "created_at": self.created_at,
            "content_entry": self.content_entry,
            "derived_from": list(self.derived_from),
            "set_ids": list(self.set_ids),
            "rank_score": self.rank_score,
            "rank_source": self.rank_source,
            "status": self.status,
            "runtime_config": self.runtime_config,
            "created_by": self.created_by,
            "tags": list(self.tags),
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TraceRecord":
        return cls(
            run_id=str(data["run_id"]),
            trace_id=str(data["trace_id"]),
            role=str(data.get("role", "search")),  # type: ignore[arg-type]
            created_at=float(data.get("created_at", time.time())),
            content_entry=str(data.get("content_entry", "")),
            derived_from=tuple(str(x) for x in data.get("derived_from", ()) or ()),
            set_ids=tuple(str(x) for x in data.get("set_ids", ()) or ()),
            rank_score=None if data.get("rank_score") is None else float(data["rank_score"]),
            rank_source=str(data.get("rank_source", "")),
            status=str(data.get("status", "stored")),
            runtime_config=str(data.get("runtime_config", "")),
            created_by=str(data.get("created_by", "")),
            tags=tuple(str(x) for x in data.get("tags", ()) or ()),
        )

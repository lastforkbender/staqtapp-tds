"""Provenance records for optional Spiral-compatible pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time


@dataclass(frozen=True)
class AggregationRecord:
    """Metadata for an aggregation output derived from one or more traces."""

    run_id: str
    aggregation_id: str
    output_entry: str
    derived_from: tuple[str, ...]
    created_at: float = field(default_factory=time.time)
    aggregation_step: int = 1
    rank_score: float | None = None
    rank_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "aggregation_id": self.aggregation_id,
            "output_entry": self.output_entry,
            "derived_from": list(self.derived_from),
            "created_at": self.created_at,
            "aggregation_step": self.aggregation_step,
            "rank_score": self.rank_score,
            "rank_source": self.rank_source,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AggregationRecord":
        return cls(
            run_id=str(data["run_id"]),
            aggregation_id=str(data["aggregation_id"]),
            output_entry=str(data["output_entry"]),
            derived_from=tuple(str(x) for x in data.get("derived_from", ()) or ()),
            created_at=float(data.get("created_at", time.time())),
            aggregation_step=int(data.get("aggregation_step", 1)),
            rank_score=None if data.get("rank_score") is None else float(data["rank_score"]),
            rank_source=str(data.get("rank_source", "")),
            metadata=dict(data.get("metadata", {}) or {}),
        )

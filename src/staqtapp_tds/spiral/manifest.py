"""Trace-set manifests for optional Spiral-compatible TDS workflows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time


@dataclass(frozen=True)
class TraceSetManifest:
    """A content-neutral grouping of trace ids.

    The set can represent SPIRAL-style parallel traces, recursive aggregation
    groups, verifier batches, or any other trace collection. TDS does not decide
    which traces belong together; callers provide the grouping.
    """

    run_id: str
    set_id: str
    trace_ids: tuple[str, ...]
    created_at: float = field(default_factory=time.time)
    set_role: str = "search_set"
    rank_policy: str = "external"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "set_id": self.set_id,
            "trace_ids": list(self.trace_ids),
            "created_at": self.created_at,
            "set_role": self.set_role,
            "rank_policy": self.rank_policy,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TraceSetManifest":
        return cls(
            run_id=str(data["run_id"]),
            set_id=str(data["set_id"]),
            trace_ids=tuple(str(x) for x in data.get("trace_ids", ()) or ()),
            created_at=float(data.get("created_at", time.time())),
            set_role=str(data.get("set_role", "search_set")),
            rank_policy=str(data.get("rank_policy", "external")),
            metadata=dict(data.get("metadata", {}) or {}),
        )

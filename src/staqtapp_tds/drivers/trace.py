"""Deterministic trace ranking fixtures for future semantic search drivers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TraceEvidence:
    driver_id: str
    path: str
    semantic_score: float
    manifest_score: float
    extraction_score: float
    lineage_trust: float = 1.0

    @property
    def rank_score(self) -> float:
        # Fixed weights keep v3.0.6 deterministic; future policy drivers can make
        # this registry-backed after the native Driver VM exists.
        return round(
            0.40 * self.semantic_score
            + 0.25 * self.manifest_score
            + 0.25 * self.extraction_score
            + 0.10 * self.lineage_trust,
            6,
        )


def rank_traces(traces: list[TraceEvidence]) -> list[TraceEvidence]:
    """Return traces in deterministic best-first order."""

    return sorted(traces, key=lambda item: (-item.rank_score, item.driver_id, item.path))

"""Compact immutable metadata records for Staqtapp-TDS.

These records are deliberately small, fixed-shape Python objects. They use
``@dataclass(slots=True, frozen=True)`` so high-volume metadata can be held
without per-instance ``__dict__`` overhead while remaining easy to serialize.
They are records only; controllers/managers stay normal Python classes.
"""

from .entry import EntryDescriptor
from .chunk import ChunkDescriptor
from .namespace import NamespaceDescriptor
from .provenance import ProvenanceRecord
from .execution import ExecutionCounters, ProbeStatistics
from .snapshot import RuntimeSnapshot
from .trace import TraceRecord, TraceRole
from .aggregation import TraceSetManifest, AggregationRecord

__all__ = [
    "EntryDescriptor", "ChunkDescriptor", "NamespaceDescriptor",
    "ProvenanceRecord", "ExecutionCounters", "ProbeStatistics",
    "RuntimeSnapshot", "TraceRecord", "TraceRole", "TraceSetManifest",
    "AggregationRecord",
]

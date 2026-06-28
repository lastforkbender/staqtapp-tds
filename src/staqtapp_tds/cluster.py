"""Minimal cluster identity feedback for related .tds files.

This is intentionally small in v1.8.0.  It gives a group of .tds shards one
stable identity and returns structured feedback for query selectors. It does
not scan huge clusters by default and does not become a reasoning layer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import numpy as np

from staqtapp_tds.provenance import ProvenanceClass, stable_id
from staqtapp_tds.result import TDSResult


CLUSTER_DTYPE = np.dtype([
    ("cluster_id", "u8"),
    ("shard_count", "u4"),
    ("entry_count", "u8"),
    ("real_count", "u8"),
    ("synthetic_count", "u8"),
    ("mixed_count", "u8"),
    ("flags", "u4"),
])


@dataclass
class TDSClusterIdentity:
    name: str
    schema_version: str = "1.8.0"
    route_stamp_version: str = "RSPEC-1"
    shards: List[str] = field(default_factory=list)
    created_ns: int = field(default_factory=time.time_ns)
    flags: int = 0

    @property
    def cluster_id(self) -> int:
        return stable_id(f"{self.name}|{self.schema_version}|{self.route_stamp_version}")

    def add_shard(self, path: str) -> None:
        if path not in self.shards:
            self.shards.append(path)

    def feedback(self, *, entry_count: int = 0, provenance_counts: Optional[Dict[str, int]] = None) -> Dict[str, object]:
        pc = provenance_counts or {}
        return {
            "cluster_id": int(self.cluster_id),
            "name": self.name,
            "schema_version": self.schema_version,
            "route_stamp_version": self.route_stamp_version,
            "shard_count": len(self.shards),
            "entry_count": int(entry_count),
            "provenance_counts": dict(pc),
            "flags": int(self.flags),
        }

    def compact_record(self, *, entry_count: int = 0, provenance_counts: Optional[Dict[str, int]] = None) -> np.ndarray:
        pc = provenance_counts or {}
        rec = np.zeros(1, dtype=CLUSTER_DTYPE)
        rec["cluster_id"][0] = np.uint64(self.cluster_id)
        rec["shard_count"][0] = np.uint32(len(self.shards))
        rec["entry_count"][0] = np.uint64(int(entry_count))
        rec["real_count"][0] = np.uint64(int(pc.get("REAL", 0)))
        rec["synthetic_count"][0] = np.uint64(int(pc.get("SYNTHETIC", 0)))
        rec["mixed_count"][0] = np.uint64(int(pc.get("MIXED", 0)))
        rec["flags"][0] = np.uint32(int(self.flags))
        return rec


def query_requires_selector(**selectors) -> TDSResult:
    active = [k for k, v in selectors.items() if v not in (None, "", [], (), {})]
    if not active and not selectors.get("scan", False):
        return TDSResult.fail("QUERY_REQUIRES_SELECTOR", "Cluster query requires at least one selector or scan=True.")
    return TDSResult.success("QUERY_ACCEPTED", "Cluster query selectors accepted.", meta={"selectors": active})

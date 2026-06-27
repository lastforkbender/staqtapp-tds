"""Semantic Routing Zone metadata for Staqtapp-TDS v1.7.0."""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import numpy as np


SRZ_DTYPE = np.dtype([
    ("route_id", "u8"),
    ("dir_handle", "i8"),
    ("expected_ns", "u8"),
    ("avg_ns", "u8"),
    ("hits", "u8"),
    ("misses", "u8"),
    ("bucket", "u1"),
    ("flags", "u4"),
])


def route_id_for(stamp: str, path: str = "") -> int:
    raw = f"{stamp}|{path}".encode("utf-8")
    h1 = zlib.adler32(raw) & 0xFFFFFFFF
    h2 = zlib.crc32(raw) & 0xFFFFFFFF
    return int((h1 << 32) | h2)


@dataclass
class SRZMetadata:
    enabled: bool = False
    route_stamp: str = ""
    source_tags: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    latent_id: Optional[int] = None
    route_id: int = 0
    flags: int = 0

    @classmethod
    def create(cls, *, enabled: bool = False, route_stamp: str = "", path: str = "", source_tags: Iterable[str] = (), aliases: Iterable[str] = (), latent_id: Optional[int] = None, flags: int = 0) -> "SRZMetadata":
        rid = route_id_for(route_stamp or path, path) if enabled else 0
        return cls(bool(enabled), route_stamp, list(source_tags), list(aliases), latent_id, rid, int(flags))

    def as_dict(self) -> Dict[str, object]:
        return {
            "enabled": self.enabled,
            "route_stamp": self.route_stamp,
            "source_tags": list(self.source_tags),
            "aliases": list(self.aliases),
            "latent_id": self.latent_id,
            "route_id": int(self.route_id),
            "flags": int(self.flags),
        }

    def compact_record(self, *, dir_handle: int = -1, expected_ns: int = 50_000, avg_ns: int = 0, hits: int = 0, misses: int = 0, bucket: int = 0) -> np.ndarray:
        rec = np.zeros(1, dtype=SRZ_DTYPE)
        rec["route_id"][0] = np.uint64(int(self.route_id))
        rec["dir_handle"][0] = np.int64(int(dir_handle))
        rec["expected_ns"][0] = np.uint64(int(expected_ns))
        rec["avg_ns"][0] = np.uint64(int(avg_ns))
        rec["hits"][0] = np.uint64(int(hits))
        rec["misses"][0] = np.uint64(int(misses))
        rec["bucket"][0] = np.uint8(int(bucket))
        rec["flags"][0] = np.uint32(int(self.flags))
        return rec

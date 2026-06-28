"""Lightweight provenance tags for Staqtapp-TDS v1.8.0.

Provenance is descriptive metadata only. TDS records whether data is REAL,
SYNTHETIC, DERIVED, SPECULATIVE, MIXED, or UNKNOWN; it does not judge truth.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Iterable, List

import numpy as np


class ProvenanceClass(IntEnum):
    UNKNOWN = 0
    REAL = 1
    SYNTHETIC = 2
    DERIVED = 3
    SPECULATIVE = 4
    MIXED = 5


PROVENANCE_DTYPE = np.dtype([
    ("entry_id", "u8"),
    ("source_id", "u8"),
    ("class_id", "u1"),
    ("trust_q16", "u4"),
    ("flags", "u4"),
])


def stable_id(text: str) -> int:
    raw = str(text).encode("utf-8")
    return int(((zlib.adler32(raw) & 0xFFFFFFFF) << 32) | (zlib.crc32(raw) & 0xFFFFFFFF))


@dataclass(frozen=True)
class ProvenanceTag:
    provenance: ProvenanceClass = ProvenanceClass.UNKNOWN
    source_id: str = ""
    source_uri: str = ""
    generation_id: str = ""
    transform_chain_hash: str = ""
    trust: float = 0.0
    flags: int = 0
    notes: List[str] = field(default_factory=list)

    @classmethod
    def create(cls, provenance: str | ProvenanceClass = ProvenanceClass.UNKNOWN, **kwargs) -> "ProvenanceTag":
        if isinstance(provenance, str):
            p = ProvenanceClass[provenance.upper()]
        else:
            p = provenance
        return cls(provenance=p, **kwargs)

    def as_dict(self) -> Dict[str, object]:
        return {
            "provenance": self.provenance.name,
            "source_id": self.source_id,
            "source_uri": self.source_uri,
            "generation_id": self.generation_id,
            "transform_chain_hash": self.transform_chain_hash,
            "trust": float(self.trust),
            "flags": int(self.flags),
            "notes": list(self.notes),
        }

    def compact_record(self, entry_key: str) -> np.ndarray:
        rec = np.zeros(1, dtype=PROVENANCE_DTYPE)
        rec["entry_id"][0] = np.uint64(stable_id(entry_key))
        rec["source_id"][0] = np.uint64(stable_id(self.source_id or self.source_uri or "unknown"))
        rec["class_id"][0] = np.uint8(int(self.provenance))
        trust = max(0.0, min(1.0, float(self.trust)))
        rec["trust_q16"][0] = np.uint32(round(trust * 65535))
        rec["flags"][0] = np.uint32(int(self.flags))
        return rec

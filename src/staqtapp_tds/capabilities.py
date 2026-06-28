"""Capability registry for Staqtapp-TDS v1.7.2."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag
from typing import Dict, Iterable, List


class ZoneCapability(IntFlag):
    NONE = 0
    SRZ = 1 << 0
    LATENCY = 1 << 1
    TELEMETRY = 1 << 2
    COMPRESSION = 1 << 3
    SHARED_ARENA = 1 << 4
    NATIVE_INDEX_READY = 1 << 5
    MANIFEST_BOUND = 1 << 6
    RESERVED_NAMESPACES = 1 << 7


CAPABILITY_NAMES: Dict[str, ZoneCapability] = {
    "srz": ZoneCapability.SRZ,
    "latency": ZoneCapability.LATENCY,
    "telemetry": ZoneCapability.TELEMETRY,
    "compression": ZoneCapability.COMPRESSION,
    "shared_arena": ZoneCapability.SHARED_ARENA,
    "native_index_ready": ZoneCapability.NATIVE_INDEX_READY,
    "manifest_bound": ZoneCapability.MANIFEST_BOUND,
    "reserved_namespaces": ZoneCapability.RESERVED_NAMESPACES,
}


@dataclass
class CapabilityRegistry:
    flags: ZoneCapability = ZoneCapability.NONE

    @classmethod
    def from_names(cls, names: Iterable[str]) -> "CapabilityRegistry":
        flags = ZoneCapability.NONE
        for name in names:
            flags |= CAPABILITY_NAMES.get(str(name).lower(), ZoneCapability.NONE)
        return cls(flags)

    def enable(self, cap: ZoneCapability) -> None:
        self.flags |= cap

    def disable(self, cap: ZoneCapability) -> None:
        self.flags &= ~cap

    def supports(self, cap: ZoneCapability | str) -> bool:
        if isinstance(cap, str):
            cap = CAPABILITY_NAMES.get(cap.lower(), ZoneCapability.NONE)
        return bool(self.flags & cap)

    def names(self) -> List[str]:
        return [name for name, flag in CAPABILITY_NAMES.items() if self.supports(flag)]

    def as_int(self) -> int:
        return int(self.flags)

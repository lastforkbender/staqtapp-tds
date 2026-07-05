"""Driver manifest draft model for the future TDS Driver Builder.

This module is intentionally pure Python and non-executing. It gives v3.0.6 a
stable manifest contract and tests before the native Driver VM is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping


class DriverSafety(str, Enum):
    """Declared driver safety class."""

    BOUNDED = "bounded"
    QUARANTINED = "quarantined"
    EXPERIMENTAL = "experimental"


_ALLOWED_KINDS = {"search", "extract", "rank", "adapter", "policy"}


@dataclass(frozen=True, slots=True)
class DriverManifest:
    """Minimal typed manifest for future compiled ``.tdd`` packages."""

    driver_id: str
    version: int
    kind: str
    description: str = ""
    safety: DriverSafety = DriverSafety.BOUNDED
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    adapters: tuple[str, ...] = field(default_factory=tuple)
    parent_id: str | None = None
    generation: int = 0

    def canonical_payload(self) -> bytes:
        """Return deterministic bytes suitable for signing or hashing."""

        parts = [
            f"driver_id={self.driver_id}",
            f"version={self.version}",
            f"kind={self.kind}",
            f"description={self.description}",
            f"safety={self.safety.value}",
            f"capabilities={','.join(sorted(self.capabilities))}",
            f"adapters={','.join(sorted(self.adapters))}",
            f"parent_id={self.parent_id or ''}",
            f"generation={self.generation}",
        ]
        return "\n".join(parts).encode("utf-8")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "DriverManifest":
        """Build a manifest from a mapping and normalize list-like fields."""

        safety_value = data.get("safety", DriverSafety.BOUNDED.value)
        safety = safety_value if isinstance(safety_value, DriverSafety) else DriverSafety(str(safety_value))
        return cls(
            driver_id=str(data["driver_id"]),
            version=int(data.get("version", 1)),
            kind=str(data["kind"]),
            description=str(data.get("description", "")),
            safety=safety,
            capabilities=tuple(_string_items(data.get("capabilities", ()))),
            adapters=tuple(_string_items(data.get("adapters", ()))),
            parent_id=None if data.get("parent_id") in (None, "") else str(data.get("parent_id")),
            generation=int(data.get("generation", 0)),
        )


def _string_items(value: object) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)  # type: ignore[arg-type]


def validate_manifest(manifest: DriverManifest) -> None:
    """Validate the draft driver manifest contract.

    Raises ``ValueError`` with deterministic messages for Builder/Studio tests.
    """

    if not manifest.driver_id or not manifest.driver_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("driver_id must be non-empty and contain only alnum, hyphen or underscore")
    if manifest.version < 1:
        raise ValueError("version must be >= 1")
    if manifest.kind not in _ALLOWED_KINDS:
        raise ValueError(f"kind must be one of {sorted(_ALLOWED_KINDS)}")
    if manifest.generation < 0:
        raise ValueError("generation must be >= 0")
    if manifest.safety is DriverSafety.BOUNDED and not manifest.capabilities:
        raise ValueError("bounded drivers must declare at least one capability")
    for capability in manifest.capabilities:
        if not capability or " " in capability:
            raise ValueError("capabilities must be non-empty dotted tokens")
    for adapter in manifest.adapters:
        if not adapter or " " in adapter:
            raise ValueError("adapters must be non-empty dotted tokens")

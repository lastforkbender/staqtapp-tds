"""Canonical 32-bit checksum registry for TDS evidence.

New evidence uses one cross-backend algorithm identity. The historical native
FNV-1a surface remains available only so already-written manifests can still be
verified; it is not the default for new artifacts.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import zlib
from typing import Any

from staqtapp_tds.native.manager import get_native_manager

CRC32_IEEE_V1 = "crc32-ieee-v1"
FNV1A32_LEGACY_V1 = "fnv1a32-legacy-v1"
DEFAULT_CHECKSUM32_ALGORITHM = CRC32_IEEE_V1
CHECKSUM32_ALGORITHMS = (CRC32_IEEE_V1, FNV1A32_LEGACY_V1)


class ChecksumAlgorithmError(ValueError):
    """Raised when a checksum algorithm identity is absent or unsupported."""


def normalize_checksum32_algorithm(algorithm: str) -> str:
    if not isinstance(algorithm, str):
        raise ChecksumAlgorithmError("checksum algorithm must be a string")
    if algorithm not in CHECKSUM32_ALGORITHMS:
        raise ChecksumAlgorithmError(f"unsupported checksum algorithm: {algorithm!r}")
    return algorithm


def _snapshot_bytes(payload: Any) -> bytes:
    if type(payload) is bytes:
        return payload
    try:
        view = memoryview(payload)
    except TypeError as exc:
        raise TypeError("checksum input must support the contiguous buffer protocol") from exc
    try:
        if not view.contiguous:
            raise TypeError("checksum input must be contiguous")
        return view.tobytes()
    finally:
        view.release()


def _fnv1a32(payload: bytes) -> int:
    value = 2166136261
    for byte in payload:
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return value or 1


def checksum32_python(payload: Any, *, algorithm: str = DEFAULT_CHECKSUM32_ALGORITHM) -> int:
    """Return the canonical Python checksum for one immutable snapshot."""

    selected = normalize_checksum32_algorithm(algorithm)
    data = _snapshot_bytes(payload)
    if selected == CRC32_IEEE_V1:
        return zlib.crc32(data) & 0xFFFFFFFF
    return _fnv1a32(data)


def _native_module_for_algorithm(algorithm: str):
    manager = get_native_manager()
    module, report = manager.inspect_module("staqtapp_tds._native_index")
    if module is None or not report.compatible:
        return None
    declared = str(getattr(module, "TDS_NATIVE_CHECKSUM_ALGORITHMS", ""))
    algorithms = {item.strip() for item in declared.split(",") if item.strip()}
    if algorithm not in algorithms:
        return None
    return module


def checksum32(
    payload: Any,
    *,
    algorithm: str = DEFAULT_CHECKSUM32_ALGORITHM,
    prefer_native: bool = True,
) -> tuple[int, str]:
    """Return ``(checksum, backend)`` for one input snapshot."""

    selected = normalize_checksum32_algorithm(algorithm)
    if prefer_native:
        module = _native_module_for_algorithm(selected)
        if module is not None and hasattr(module, "checksum32_for_algorithm"):
            return int(module.checksum32_for_algorithm(payload, selected)), "native"
    return checksum32_python(payload, algorithm=selected), "python"


def checksum32_many(
    payloads: Iterable[Any],
    *,
    algorithm: str = DEFAULT_CHECKSUM32_ALGORITHM,
    prefer_native: bool = True,
) -> tuple[list[int], str]:
    """Return checksums for one bounded input collection and the backend used."""

    selected = normalize_checksum32_algorithm(algorithm)
    items = list(payloads)
    if not items:
        return [], "empty"
    if prefer_native:
        module = _native_module_for_algorithm(selected)
        if module is not None and hasattr(module, "checksum32_many_for_algorithm"):
            return [
                int(value)
                for value in module.checksum32_many_for_algorithm(items, selected)
            ], "native"
    return [checksum32_python(item, algorithm=selected) for item in items], "python"


def manifest_checksum32_algorithm(manifest: Mapping[str, Any]) -> str:
    """Resolve a chunk manifest algorithm, including historical forms."""

    explicit = manifest.get("chunk_checksum_algorithm")
    if explicit is not None:
        return normalize_checksum32_algorithm(str(explicit))
    backend = str(manifest.get("chunk_checksum_backend", "python"))
    if backend == "native":
        return FNV1A32_LEGACY_V1
    return CRC32_IEEE_V1


__all__ = [
    "CHECKSUM32_ALGORITHMS",
    "CRC32_IEEE_V1",
    "DEFAULT_CHECKSUM32_ALGORITHM",
    "FNV1A32_LEGACY_V1",
    "ChecksumAlgorithmError",
    "checksum32",
    "checksum32_many",
    "checksum32_python",
    "manifest_checksum32_algorithm",
    "normalize_checksum32_algorithm",
]

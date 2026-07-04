"""Optional native EntryIndex boundary through the Native Engine Manager."""

from __future__ import annotations

from typing import Any

from staqtapp_tds.native.manager import get_native_manager


def load_native_backend(*, shards: int = 64, requested: str = "auto") -> Any | None:
    """Try to load the optional compiled backend without raising.

    The Native Engine Manager records platform, ABI and capability diagnostics;
    this compatibility function returns only the backend for legacy callers.
    """
    backend, _report = get_native_manager().load_index_backend(shards=shards, requested=requested)
    return backend


def load_native_backend_report(*, shards: int = 64, requested: str = "auto") -> tuple[Any | None, Any]:
    """Load the native backend and return ``(backend_or_none, NativeLoadReport)``."""
    return get_native_manager().load_index_backend(shards=shards, requested=requested)

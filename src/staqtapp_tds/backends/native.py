"""Optional native EntryIndex boundary."""

from __future__ import annotations

from typing import Any


def load_native_backend(*, shards: int = 64) -> Any | None:
    """Try to load the optional compiled native handle index backend."""
    try:
        from staqtapp_tds.backends.native_index import NativeEntryIndexBackend
    except Exception:
        return None
    try:
        return NativeEntryIndexBackend(shards=shards)
    except Exception:
        return None

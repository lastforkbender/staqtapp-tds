"""
EntryIndex facade for Staqtapp-TDS v1.7.0.

The VFS talks to this small class only. Today it defaults to a pure-Python
backend; later it can select a Cython/pybind11 backend that releases the GIL for
hot reads while keeping the same Python-facing API.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

from staqtapp_tds.backends.native import load_native_backend
from staqtapp_tds.backends.python_index import PythonEntryIndexBackend, EntryIndexStats


class EntryIndex:
    """
    Native-ready entry index facade.

    backend="auto" tries the optional native extension and falls back to Python.
    backend="python" forces the portable backend.
    """

    def __init__(self, shards: int = 64, backend: str | None = None):
        selected = (backend or os.environ.get("STAQTAPP_TDS_INDEX_BACKEND", "auto")).lower()
        if selected not in {"auto", "python", "native"}:
            raise ValueError("EntryIndex backend must be 'auto', 'python', or 'native'")
        impl = None
        if selected in {"auto", "native"}:
            impl = load_native_backend(shards=shards)
            if impl is None and selected == "native":
                raise RuntimeError("native EntryIndex backend requested but not available")
        self._impl = impl if impl is not None else PythonEntryIndexBackend(shards=shards)

    @property
    def backend_name(self) -> str:
        return getattr(self._impl, "backend_name", self._impl.__class__.__name__)

    def put(self, key: str, entry: Any) -> int:
        return int(self._impl.put(key, entry))

    def get(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self._impl.get(key, default)

    def get_handle(self, key: str) -> int:
        return int(self._impl.get_handle(key))

    def get_by_handle(self, handle: int) -> Optional[Any]:
        return self._impl.get_by_handle(handle)

    def pop(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self._impl.pop(key, default)

    def keys(self) -> List[str]:
        return list(self._impl.keys())

    def values(self) -> List[Any]:
        return list(self._impl.values())

    def items(self) -> List[Tuple[str, Any]]:
        return list(self._impl.items())

    def stats(self) -> Any:
        return self._impl.stats() if hasattr(self._impl, "stats") else EntryIndexStats(self.backend_name, len(self), -1, -1)

    def __setitem__(self, key: str, entry: Any) -> None:
        self.put(key, entry)

    def __getitem__(self, key: str) -> Any:
        entry = self.get(key)
        if entry is None:
            raise KeyError(key)
        return entry

    def __contains__(self, key: str) -> bool:
        if hasattr(self._impl, "contains"):
            return bool(self._impl.contains(key))
        return self.get_handle(key) >= 0

    def __len__(self) -> int:
        return int(len(self._impl))

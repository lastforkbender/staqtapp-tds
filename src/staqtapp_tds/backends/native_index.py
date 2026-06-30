"""Python wrapper around the optional v2.1 native handle index."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from staqtapp_tds.backends.python_index import EntryIndexStats


class NativeEntryIndexBackend:
    """EntryIndex backend using a C Swiss-table-inspired bytes->int64 handle map.

    get_handle(), get_handles(), contains(), and the native pop lookup path release the GIL inside the C extension during
    the native table lookup. Python object values remain in a Python-side
    handle table so the native backend does not know about variables, SRZ,
    manifests, or TDSEntry objects.
    """
    backend_name = "native-c-swiss"

    def __init__(self, shards: int = 64):
        from staqtapp_tds._native_index import NativeHandleIndex
        capacity = max(1024, int(shards) * 64)
        self._index = NativeHandleIndex(capacity=capacity)
        self._values: Dict[int, Any] = {}
        self._keys: Dict[int, str] = {}
        self._lock = threading.RLock()

    def put(self, key: str, entry: Any) -> int:
        handle = int(self._index.put(key.encode("utf-8")))
        with self._lock:
            self._values[handle] = entry
            self._keys[handle] = key
        return handle

    def get_handle(self, key: str) -> int:
        return int(self._index.get_handle(key.encode("utf-8")))

    def get_handles(self, keys: List[str]) -> List[int]:
        encoded = [k.encode("utf-8") for k in keys]
        return [int(h) for h in self._index.get_handles(encoded)]

    def contains(self, key: str) -> bool:
        return bool(self._index.contains(key.encode("utf-8")))

    def get(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        handle = self.get_handle(key)
        if handle < 0:
            return default
        with self._lock:
            return self._values.get(handle, default)

    def get_by_handle(self, handle: int) -> Optional[Any]:
        with self._lock:
            return self._values.get(int(handle))

    def pop(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        handle = int(self._index.pop(key.encode("utf-8")))
        if handle < 0:
            return default
        with self._lock:
            self._keys.pop(handle, None)
            return self._values.pop(handle, default)

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._keys.values())

    def values(self) -> List[Any]:
        with self._lock:
            return [self._values[h] for h in self._keys.keys() if h in self._values]

    def items(self) -> List[Tuple[str, Any]]:
        with self._lock:
            return [(k, self._values[h]) for h, k in self._keys.items() if h in self._values]

    def __len__(self) -> int:
        return int(self._index.size())

    def stats(self) -> Any:
        s = self._index.stats()
        return EntryIndexStats(
            backend=s.get("backend", self.backend_name),
            size=int(s.get("size", 0)),
            shards=-1,
            next_handle=int(s.get("next_handle", -1)),
            capacity=int(s.get("capacity", -1)),
            tombstones=int(s.get("tombstones", 0)),
            load_factor=float(s.get("load_factor", 0.0)),
            max_probe=int(s.get("max_probe", 0)),
            avg_probe=float(s.get("avg_probe", 0.0)),
        )

    def native_execution_stats(self) -> Dict[str, int | bool | str]:
        """Return raw native execution counters for dashboard telemetry."""
        s = self._index.stats()
        return {
            "backend": str(s.get("backend", self.backend_name)),
            "gil_released_put": bool(s.get("gil_released_put", False)),
            "gil_released_get_handle": bool(s.get("gil_released_get_handle", False)),
            "gil_released_get_handles": bool(s.get("gil_released_get_handles", False)),
            "gil_released_pop_lookup": bool(s.get("gil_released_pop_lookup", False)),
            "gil_released_stats_scan": bool(s.get("gil_released_stats_scan", False)),
            "native_put_calls": int(s.get("native_put_calls", 0)),
            "native_lookup_calls": int(s.get("native_lookup_calls", 0)),
            "native_batch_lookup_calls": int(s.get("native_batch_lookup_calls", 0)),
            "native_pop_calls": int(s.get("native_pop_calls", 0)),
            "native_stats_calls": int(s.get("native_stats_calls", 0)),
            "gil_released_calls": int(s.get("gil_released_calls", 0)),
            "python_native_transitions": int(s.get("python_native_transitions", 0)),
        }

"""Pure-Python EntryIndex backend for Staqtapp-TDS."""

from __future__ import annotations

import threading
import zlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class EntryIndexStats:
    backend: str
    size: int
    shards: int
    next_handle: int
    capacity: int = -1
    tombstones: int = 0
    load_factor: float = 0.0
    max_probe: int = 0
    avg_probe: float = 0.0


class PythonEntryIndexBackend:
    backend_name = "python-sharded"

    def __init__(self, shards: int = 64):
        if int(shards) <= 0:
            raise ValueError("EntryIndex shards must be positive")
        rounded = 1 << (int(shards) - 1).bit_length()
        self._shard_count = rounded
        self._mask = rounded - 1
        self._locks = [threading.RLock() for _ in range(rounded)]
        self._maps: List[Dict[str, int]] = [dict() for _ in range(rounded)]
        self._values: Dict[int, Any] = {}
        self._next_handle = 1
        self._size = 0
        self._meta_lock = threading.RLock()

    def _shard_id(self, key: str) -> int:
        return (zlib.adler32(key.encode('utf-8')) & 0xFFFFFFFF) & self._mask

    def put(self, key: str, entry: Any) -> int:
        sid = self._shard_id(key)
        with self._locks[sid], self._meta_lock:
            handle = self._maps[sid].get(key)
            if handle is None:
                handle = self._next_handle
                self._next_handle += 1
                self._maps[sid][key] = handle
                self._size += 1
            self._values[handle] = entry
            return int(handle)

    def get(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        sid = self._shard_id(key)
        with self._locks[sid]:
            handle = self._maps[sid].get(key)
            if handle is None:
                return default
        with self._meta_lock:
            return self._values.get(handle, default)

    def get_handle(self, key: str) -> int:
        sid = self._shard_id(key)
        with self._locks[sid]:
            handle = self._maps[sid].get(key)
            return int(handle) if handle is not None else -1

    def get_handles(self, keys: List[str]) -> List[int]:
        return [self.get_handle(k) for k in keys]

    def get_by_handle(self, handle: int) -> Optional[Any]:
        with self._meta_lock:
            return self._values.get(int(handle))

    def pop(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        sid = self._shard_id(key)
        with self._locks[sid], self._meta_lock:
            handle = self._maps[sid].pop(key, None)
            if handle is None:
                return default
            self._size -= 1
            return self._values.pop(handle, default)

    def keys(self) -> List[str]:
        out: List[str] = []
        for sid in range(self._shard_count):
            with self._locks[sid]:
                out.extend(self._maps[sid].keys())
        return out

    def values(self) -> List[Any]:
        handles: List[int] = []
        for sid in range(self._shard_count):
            with self._locks[sid]:
                handles.extend(self._maps[sid].values())
        with self._meta_lock:
            return [self._values[h] for h in handles if h in self._values]

    def items(self) -> List[Tuple[str, Any]]:
        pairs: List[Tuple[str, int]] = []
        for sid in range(self._shard_count):
            with self._locks[sid]:
                pairs.extend(self._maps[sid].items())
        with self._meta_lock:
            return [(k, self._values[h]) for k, h in pairs if h in self._values]

    def contains(self, key: str) -> bool:
        sid = self._shard_id(key)
        with self._locks[sid]:
            return key in self._maps[sid]

    def __len__(self) -> int:
        with self._meta_lock:
            return self._size

    def stats(self) -> EntryIndexStats:
        with self._meta_lock:
            return EntryIndexStats(
                backend=self.backend_name,
                size=self._size,
                shards=self._shard_count,
                next_handle=self._next_handle,
            )

"""Python wrapper around the optional native execution index."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from staqtapp_tds.backends.python_index import EntryIndexStats


NativeHandleRef = Tuple[int, int, int, int, int]


class NativeFrozenHandleView:
    """Handle-only immutable native snapshot for bounded request-time reads.

    The view intentionally contains no Python entry objects.  It exposes scalar
    compatibility lookups and a packed caller-owned output path whose C loop
    does not acquire the mutable index lock or allocate one object per result.
    """

    backend_name = "native-c-frozen-handle-index"

    def __init__(self, native_index: Any) -> None:
        self._index = native_index

    def identity(self) -> Dict[str, int | str]:
        return {str(key): value for key, value in self._index.identity().items()}

    @staticmethod
    def _encode_key(key: str | bytes) -> bytes:
        if isinstance(key, bytes):
            return key if type(key) is bytes else bytes(key)
        if isinstance(key, str):
            return key.encode("utf-8")
        raise TypeError("frozen native keys must be str or bytes")

    def get_handle(self, key: str | bytes) -> int:
        return int(self._index.get_handle(self._encode_key(key)))

    def contains(self, key: str | bytes) -> bool:
        return bool(self._index.contains(self._encode_key(key)))

    def lookup_packed(
        self,
        keys_blob: bytes,
        offsets_le64: bytes,
        output_le_i64: bytearray | memoryview,
    ) -> int:
        """Write canonical little-endian signed-64 handles into output.

        Missing keys are encoded as ``-1``.  The method returns only the number
        of processed keys; it never constructs a Python result list.
        """
        return int(
            self._index.lookup_packed(
                keys_blob,
                offsets_le64,
                output_le_i64,
            )
        )

    def stats(self) -> Dict[str, int | str]:
        return {str(key): value for key, value in self._index.stats().items()}

    def __len__(self) -> int:
        return int(self._index.size())


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

    def put_many(self, items: List[Tuple[str, Any]]) -> List[int]:
        """Insert many key/value pairs with one native transition."""
        pairs = list(items)
        if not pairs:
            return []
        encoded = [k.encode("utf-8") for k, _ in pairs]
        handles = [int(h) for h in self._index.put_many(encoded)]
        with self._lock:
            for (key, entry), handle in zip(pairs, handles):
                self._values[handle] = entry
                self._keys[handle] = key
        return handles

    def get_handle(self, key: str) -> int:
        return int(self._index.get_handle(key.encode("utf-8")))

    def get_handles(self, keys: List[str]) -> List[int]:
        encoded = [k.encode("utf-8") for k in keys]
        return [int(h) for h in self._index.get_handles(encoded)]

    def identity(self) -> Tuple[int, int]:
        namespace_id, index_epoch = self._index.identity()
        return int(namespace_id), int(index_epoch)

    def freeze_handles(self) -> NativeFrozenHandleView:
        """Build an off-request immutable handle-only native snapshot."""
        return NativeFrozenHandleView(self._index.freeze())

    def get_handle_ref(self, key: str) -> Optional[NativeHandleRef]:
        ref = self._index.get_handle_ref(key.encode("utf-8"))
        if ref is None:
            return None
        namespace_id, index_epoch, slot, generation, handle = ref
        return (
            int(namespace_id),
            int(index_epoch),
            int(slot),
            int(generation),
            int(handle),
        )

    def resolve_handle_ref(self, ref: NativeHandleRef) -> int:
        if len(ref) != 5:
            raise ValueError("native handle reference must contain five integers")
        return int(self._index.resolve_handle_ref(*tuple(int(part) for part in ref)))

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

    def pop_many(self, keys: List[str], default: Optional[Any] = None) -> List[Optional[Any]]:
        encoded = [k.encode("utf-8") for k in keys]
        handles = [int(h) for h in self._index.pop_many(encoded)]
        out: List[Optional[Any]] = []
        with self._lock:
            for handle in handles:
                if handle < 0:
                    out.append(default)
                else:
                    self._keys.pop(handle, None)
                    out.append(self._values.pop(handle, default))
        return out

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
            "namespace_id": int(s.get("namespace_id", 0)),
            "index_epoch": int(s.get("index_epoch", 0)),
            "handle_ref_contract": str(s.get("handle_ref_contract", "")),
            "gil_released_put": bool(s.get("gil_released_put", False)),
            "gil_released_get_handle": bool(s.get("gil_released_get_handle", False)),
            "gil_released_get_handles": bool(s.get("gil_released_get_handles", False)),
            "gil_released_pop_lookup": bool(s.get("gil_released_pop_lookup", False)),
            "gil_released_stats_scan": bool(s.get("gil_released_stats_scan", False)),
            "gil_released_put_many": bool(s.get("gil_released_put_many", False)),
            "gil_released_pop_many": bool(s.get("gil_released_pop_many", False)),
            "native_put_calls": int(s.get("native_put_calls", 0)),
            "native_batch_put_calls": int(s.get("native_batch_put_calls", 0)),
            "native_lookup_calls": int(s.get("native_lookup_calls", 0)),
            "native_batch_lookup_calls": int(s.get("native_batch_lookup_calls", 0)),
            "native_pop_calls": int(s.get("native_pop_calls", 0)),
            "native_batch_pop_calls": int(s.get("native_batch_pop_calls", 0)),
            "native_stats_calls": int(s.get("native_stats_calls", 0)),
            "native_checksum_calls": int(s.get("native_checksum_calls", 0)),
            "native_chunk_scan_calls": int(s.get("native_chunk_scan_calls", 0)),
            "gil_released_calls": int(s.get("gil_released_calls", 0)),
            "python_native_transitions": int(s.get("python_native_transitions", 0)),
            "pool_reuse_count": int(s.get("pool_reuse_count", 0)),
            "pool_allocator_calls": int(s.get("pool_allocator_calls", 0)),
            "pool_frees": int(s.get("pool_frees", 0)),
        }

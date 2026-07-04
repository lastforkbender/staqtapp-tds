"""EntryIndex facade for Staqtapp-TDS."""

from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

from staqtapp_tds.backends.native import load_native_backend_report
from staqtapp_tds.backends.python_index import PythonEntryIndexBackend, EntryIndexStats
from staqtapp_tds.result import TDSResult, TDSResultCode


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
        self._native_report = None
        if selected in {"auto", "native"}:
            impl, self._native_report = load_native_backend_report(shards=shards, requested=selected)
        self._impl = impl if impl is not None else PythonEntryIndexBackend(shards=shards)


    def native_status_result(self) -> TDSResult:
        """Return the native load status for this EntryIndex without raising."""
        report = getattr(self, "_native_report", None)
        if report is None:
            return TDSResult.success(
                TDSResultCode.NATIVE_ENGINE_FALLBACK,
                "Python EntryIndex backend selected; native load was not requested.",
                value={"backend": self.backend_name},
            )
        code = TDSResultCode.NATIVE_ENGINE_LOADED if report.native_loaded else TDSResultCode.NATIVE_ENGINE_FALLBACK
        return TDSResult.success(code, report.reason, value=report.as_dict())

    @property
    def backend_name(self) -> str:
        return getattr(self._impl, "backend_name", self._impl.__class__.__name__)

    def put(self, key: str, entry: Any) -> int:
        return int(self._impl.put(key, entry))

    def put_many(self, items: List[Tuple[str, Any]]) -> List[int]:
        pairs = list(items)
        if hasattr(self._impl, "put_many"):
            return [int(h) for h in self._impl.put_many(pairs)]
        return [self.put(k, v) for k, v in pairs]

    def get(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self._impl.get(key, default)

    def get_handle(self, key: str) -> int:
        return int(self._impl.get_handle(key))

    def get_handles(self, keys: List[str]) -> List[int]:
        if hasattr(self._impl, "get_handles"):
            return [int(h) for h in self._impl.get_handles(list(keys))]
        return [self.get_handle(k) for k in keys]

    def get_by_handle(self, handle: int) -> Optional[Any]:
        return self._impl.get_by_handle(handle)

    def pop(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self._impl.pop(key, default)

    def pop_many(self, keys: List[str], default: Optional[Any] = None) -> List[Optional[Any]]:
        if hasattr(self._impl, "pop_many"):
            return list(self._impl.pop_many(list(keys), default))
        return [self.pop(k, default) for k in keys]

    def keys(self) -> List[str]:
        return list(self._impl.keys())

    def values(self) -> List[Any]:
        return list(self._impl.values())

    def items(self) -> List[Tuple[str, Any]]:
        return list(self._impl.items())

    def stats(self) -> Any:
        return self._impl.stats() if hasattr(self._impl, "stats") else EntryIndexStats(self.backend_name, len(self), -1, -1)

    def native_execution_stats(self) -> dict:
        if hasattr(self._impl, "native_execution_stats"):
            return dict(self._impl.native_execution_stats())
        return {
            "backend": self.backend_name,
            "gil_released_put": False,
            "gil_released_get_handle": False,
            "gil_released_get_handles": False,
            "gil_released_pop_lookup": False,
            "gil_released_stats_scan": False,
            "gil_released_put_many": False,
            "gil_released_pop_many": False,
            "native_put_calls": 0,
            "native_batch_put_calls": 0,
            "native_lookup_calls": 0,
            "native_batch_lookup_calls": 0,
            "native_pop_calls": 0,
            "native_batch_pop_calls": 0,
            "native_stats_calls": 0,
            "gil_released_calls": 0,
            "python_native_transitions": 0,
            "pool_reuse_count": 0,
            "pool_allocator_calls": 0,
            "pool_frees": 0,
        }

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

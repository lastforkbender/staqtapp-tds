"""Original Staqtapp-compatible variable control layer for TDS.

This module keeps the distinctive Staqtapp variable semantics out of the core
filesystem hot path. It manages names, locks, stalk chains, and non-halting
Result feedback while delegating actual payload storage to TDSDirectory.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
import copy
import threading

from staqtapp_tds.result import TDSResult, TDSResultCode
from staqtapp_tds.errors import ErrorTelemetry, ErrorLogMode


def _merge_values(previous: Any, new_data: Any) -> Any:
    """Staqtapp residual combine rule.

    dict+dict merges, list+list extends, tuple+tuple concatenates, str+str
    concatenates, bytes+bytes concatenates, numeric values add. Other mixed
    types become a two-item list so data is not silently discarded.
    """
    if previous is None:
        return copy.deepcopy(new_data)
    if new_data is None:
        return copy.deepcopy(previous)
    if isinstance(previous, dict) and isinstance(new_data, dict):
        out = copy.deepcopy(previous)
        out.update(copy.deepcopy(new_data))
        return out
    if isinstance(previous, list) and isinstance(new_data, list):
        return copy.deepcopy(previous) + copy.deepcopy(new_data)
    if isinstance(previous, tuple) and isinstance(new_data, tuple):
        return copy.deepcopy(previous) + copy.deepcopy(new_data)
    if isinstance(previous, str) and isinstance(new_data, str):
        return previous + new_data
    if isinstance(previous, (bytes, bytearray)) and isinstance(new_data, (bytes, bytearray)):
        return bytes(previous) + bytes(new_data)
    if isinstance(previous, (int, float, complex)) and isinstance(new_data, (int, float, complex)):
        return previous + new_data
    return [copy.deepcopy(previous), copy.deepcopy(new_data)]

@dataclass
class StalkState:
    active: bool = False
    latest_index: int = 0
    latest_name: str = ""
    chain_names: List[str] = field(default_factory=list)

class VariableControl:
    def __init__(self, directory: Any, *, error_mode: ErrorLogMode = ErrorLogMode.LIGHT):
        self.directory = directory
        self.lockvars: Dict[str, bool] = {}
        self.stalkvars: Dict[str, StalkState] = {}
        self._locks: Dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self.errors = ErrorTelemetry(error_mode)

    def _path(self) -> str:
        return self.directory.path() if hasattr(self.directory, "path") else ""

    def _chain_lock(self, base: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(base)
            if lock is None:
                lock = threading.RLock()
                self._locks[base] = lock
            return lock

    def _exists(self, name: str) -> bool:
        return name in self.directory._entries

    def _delete(self, name: str) -> None:
        self.directory.delete_entry(name)

    def is_locked(self, name: str) -> bool:
        return bool(self.lockvars.get(name, False))

    def addvar(self, name: str, data: Any) -> TDSResult:
        with self._chain_lock(name):
            return self._addvar_locked(name, data)

    def _addvar_locked(self, name: str, data: Any) -> TDSResult:
        if self._exists(name):
            self.errors.record(TDSResultCode.VAR_EXISTS, path=self._path(), name=name)
            return TDSResult.fail(TDSResultCode.VAR_EXISTS, "Variable already exists; use editvar() to replace.", name=name, path=self._path())
        self.directory.write_variable(name, data)
        return TDSResult.success(TDSResultCode.VAR_ADDED, "Variable added.", name=name, path=self._path(), value=data)

    def editvar(self, name: str, data: Any, *, overwrite: bool = True) -> TDSResult:
        if self.is_locked(name):
            self.errors.record(TDSResultCode.VAR_LOCKED, path=self._path(), name=name, severity="warn")
            return TDSResult.fail(TDSResultCode.VAR_LOCKED, "Variable is locked.", name=name, path=self._path())
        if not self._exists(name):
            self.directory.write_variable(name, data)
            return TDSResult.success(TDSResultCode.VAR_CREATED, "Variable did not exist and was created.", name=name, path=self._path(), value=data)
        if not overwrite:
            self.errors.record(TDSResultCode.VAR_EXISTS, path=self._path(), name=name)
            return TDSResult.fail(TDSResultCode.VAR_EXISTS, "Variable already exists.", name=name, path=self._path())
        self.directory.write_variable(name, data)
        return TDSResult.success(TDSResultCode.VAR_EDITED, "Variable edited.", name=name, path=self._path(), value=data)

    def lockvar(self, name: str, locked: bool = True) -> TDSResult:
        with self._chain_lock(name):
            return self._lockvar_locked(name, locked)

    def _lockvar_locked(self, name: str, locked: bool = True) -> TDSResult:
        if not self._exists(name):
            self.errors.record(TDSResultCode.VAR_MISSING, path=self._path(), name=name)
            return TDSResult.fail(TDSResultCode.VAR_MISSING, "Variable does not exist.", name=name, path=self._path())
        self.lockvars[name] = bool(locked)
        return TDSResult.success(TDSResultCode.VAR_LOCKED if locked else TDSResultCode.VAR_UNLOCKED, "Variable lock state updated.", name=name, path=self._path(), meta={"locked": bool(locked)})

    def unlockvar(self, name: str) -> TDSResult:
        return self.lockvar(name, False)

    def _clear_chain(self, base: str) -> List[str]:
        state = self.stalkvars.get(base)
        if not state:
            return []
        removed: List[str] = []
        for n in list(state.chain_names):
            if self._exists(n):
                self._delete(n)
                removed.append(n)
        self.stalkvars.pop(base, None)
        return removed

    def stalkvar(self, name: str, data: Any = None) -> TDSResult:
        # Public signal: ~name means append from current latest stalk value.
        if name.startswith("~"):
            base = name[1:]
            if not base:
                return TDSResult.fail(TDSResultCode.VAR_INVALID_NAME, "Stalk variable name cannot be empty.", name=name, path=self._path())
            with self._chain_lock(base):
                if self.is_locked(base):
                    self.errors.record(TDSResultCode.VAR_LOCKED, path=self._path(), name=base, severity="warn")
                    return TDSResult.fail(TDSResultCode.VAR_LOCKED, "Base variable is locked.", name=base, path=self._path())
                if not self._exists(base):
                    self.errors.record(TDSResultCode.VAR_MISSING, path=self._path(), name=base)
                    return TDSResult.fail(TDSResultCode.VAR_MISSING, "Base variable does not exist.", name=base, path=self._path())
                state = self.stalkvars.get(base)
                if state is None:
                    state = StalkState(active=True, latest_index=0, latest_name=base, chain_names=[])
                    self.stalkvars[base] = state
                previous = self.directory.read_value(state.latest_name)
                combined = _merge_values(previous, data)
                next_index = state.latest_index + 1
                next_name = f"{base}_{next_index:04d}"
                # Avoid accidental collision outside tracked chain.
                if self._exists(next_name) and next_name not in state.chain_names:
                    self.errors.record(TDSResultCode.VAR_CHAIN_COLLISION, path=self._path(), name=next_name, severity="error")
                    return TDSResult.fail(TDSResultCode.VAR_CHAIN_COLLISION, "Next stalk increment name already exists outside the tracked chain.", name=next_name, path=self._path())
                self.directory.write_variable(next_name, combined)
                state.latest_index = next_index
                state.latest_name = next_name
                state.chain_names.append(next_name)
                return TDSResult.success(TDSResultCode.VAR_STALKED, "Stalk increment created.", name=next_name, path=self._path(), value=combined, meta={"base": base, "index": next_index, "latest": next_name})

        # No tilde: if a chain exists, clear tracked increments. If data is None,
        # keep base unchanged. If data is not None, edit/replace the base.
        base = name
        with self._chain_lock(base):
            if self.is_locked(base):
                self.errors.record(TDSResultCode.VAR_LOCKED, path=self._path(), name=base, severity="warn")
                return TDSResult.fail(TDSResultCode.VAR_LOCKED, "Variable is locked.", name=base, path=self._path())
            had_chain = base in self.stalkvars
            removed = self._clear_chain(base)
            if data is None:
                return TDSResult.success(TDSResultCode.VAR_STALK_CLEARED if had_chain else TDSResultCode.VAR_NOOP, "Stalk chain cleared; base retained." if had_chain else "No stalk chain active; base retained.", name=base, path=self._path(), meta={"removed": removed})
            if not self._exists(base):
                self.directory.write_variable(base, data)
                return TDSResult.success(TDSResultCode.VAR_CREATED, "Variable created.", name=base, path=self._path(), value=data, meta={"removed": removed})
            self.directory.write_variable(base, data)
            return TDSResult.success(TDSResultCode.VAR_EDITED, "Variable edited and stalk chain cleared." if had_chain else "Variable edited.", name=base, path=self._path(), value=data, meta={"removed": removed})

    def findvar(self, name: str) -> TDSResult:
        if not self._exists(name):
            return TDSResult.fail(TDSResultCode.VAR_MISSING, "Variable does not exist.", name=name, path=self._path())
        return TDSResult.success(TDSResultCode.VAR_FOUND, "Variable found.", name=name, path=self._path(), value=self.directory.read_value(name), meta={"locked": self.is_locked(name)})

    def loadvar(self, name: str) -> Any:
        return self.directory.read_value(name)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "lockvars": dict(self.lockvars),
            "stalkvars": {
                k: {"active": v.active, "latest_index": v.latest_index, "latest_name": v.latest_name, "chain_names": list(v.chain_names)}
                for k, v in self.stalkvars.items()
            },
            "errors": self.errors.snapshot(),
        }

    def restore(self, snap: Dict[str, Any]) -> None:
        self.lockvars = {str(k): bool(v) for k, v in (snap.get("lockvars", {}) or {}).items()}
        self.stalkvars = {}
        for k, v in (snap.get("stalkvars", {}) or {}).items():
            self.stalkvars[str(k)] = StalkState(
                active=bool(v.get("active", True)),
                latest_index=int(v.get("latest_index", 0)),
                latest_name=str(v.get("latest_name", str(k))),
                chain_names=list(v.get("chain_names", []) or []),
            )

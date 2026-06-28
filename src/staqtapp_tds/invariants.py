"""NumPy/Numba-friendly invariant checks for Staqtapp-TDS v1.7.3.

The invariant engine is a deterministic consistency checker, not an AI reasoning
layer.  It detects entropy-like disorder by checking concrete VFS facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List

import numpy as np

try:
    from numba import njit
    NUMBA_AVAILABLE = True
except Exception:
    NUMBA_AVAILABLE = False
    def njit(*args, **kwargs):
        def dec(fn): return fn
        return dec(args[0]) if args and callable(args[0]) else dec


class InvariantCode(IntEnum):
    OK = 0
    LOCKVAR_ORPHAN = 10
    STALK_BASE_MISSING = 20
    STALK_LATEST_MISSING = 21
    STALK_CHAIN_MISSING = 22
    STALK_INDEX_MISMATCH = 23
    ENTRY_COUNT_LIMIT = 30
    LOOKUP_HARD_LIMIT = 40


INVARIANT_DTYPE = np.dtype([
    ("code", "u4"),
    ("target_id", "u8"),
    ("observed", "i8"),
    ("expected", "i8"),
    ("severity", "u1"),
])


@dataclass(frozen=True)
class InvariantViolation:
    code: str
    path: str
    name: str = ""
    observed: int = 0
    expected: int = 0
    severity: str = "warn"
    message: str = ""


@dataclass
class InvariantReport:
    ok: bool
    path: str
    checked: int = 0
    violations: List[InvariantViolation] = field(default_factory=list)
    numeric_records: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=INVARIANT_DTYPE))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "path": self.path,
            "checked": self.checked,
            "violations": [v.__dict__.copy() for v in self.violations],
            "numba_available": NUMBA_AVAILABLE,
        }


@njit(cache=True)
def _check_numeric_dir_stats(entry_count: np.int64, max_entries: np.int64,
                             max_lookup_ns: np.int64, hard_limit_ns: np.int64,
                             out: np.ndarray) -> np.int64:
    n = np.int64(0)
    if max_entries >= 0 and entry_count > max_entries:
        out[n]["code"] = np.uint32(InvariantCode.ENTRY_COUNT_LIMIT)
        out[n]["target_id"] = np.uint64(0)
        out[n]["observed"] = entry_count
        out[n]["expected"] = max_entries
        out[n]["severity"] = np.uint8(2)
        n += 1
    if hard_limit_ns > 0 and max_lookup_ns > hard_limit_ns:
        out[n]["code"] = np.uint32(InvariantCode.LOOKUP_HARD_LIMIT)
        out[n]["target_id"] = np.uint64(0)
        out[n]["observed"] = max_lookup_ns
        out[n]["expected"] = hard_limit_ns
        out[n]["severity"] = np.uint8(1)
        n += 1
    return n


def _severity_name(v: int) -> str:
    return "error" if int(v) >= 2 else "warn"


class InvariantEngine:
    """Consistency checks for a TDSDirectory.

    Checks are deliberately concrete: lock tables, stalk chains, entry limits,
    and latency limits.  The expensive/human explanation is outside the Numba
    scan; numeric checks remain array-based.
    """
    def __init__(self, *, max_entries: int = -1, check_latency: bool = False):
        self.max_entries = int(max_entries)
        self.check_latency = bool(check_latency)

    def evaluate_directory(self, directory: Any) -> InvariantReport:
        path = directory.path() if hasattr(directory, "path") else ""
        violations: List[InvariantViolation] = []
        checked = 0
        with directory._lock:
            names = set(directory._entries.keys())
            entry_count = len(names)
        # Lock variable table must not point at missing variables.
        for name, locked in getattr(directory.variables, "lockvars", {}).items():
            checked += 1
            if locked and name not in names:
                violations.append(InvariantViolation(
                    code="LOCKVAR_ORPHAN", path=path, name=name, severity="error",
                    message="Locked variable does not exist in directory namespace.",
                ))
        # Stalk chains must be exact and tracked; no scan/guess strategy.
        for base, state in getattr(directory.variables, "stalkvars", {}).items():
            checked += 1
            if base not in names:
                violations.append(InvariantViolation("STALK_BASE_MISSING", path, base, severity="error", message="Stalk base variable is missing."))
            if state.latest_name and state.latest_name not in names:
                violations.append(InvariantViolation("STALK_LATEST_MISSING", path, state.latest_name, severity="error", message="Latest stalk increment is missing."))
            if int(state.latest_index) != len(state.chain_names):
                violations.append(InvariantViolation("STALK_INDEX_MISMATCH", path, base, observed=len(state.chain_names), expected=int(state.latest_index), severity="error", message="Stalk latest_index does not match tracked chain length."))
            for cname in state.chain_names:
                checked += 1
                if cname not in names:
                    violations.append(InvariantViolation("STALK_CHAIN_MISSING", path, cname, severity="error", message="Tracked stalk increment entry is missing."))
        # Numeric checks are arranged for Numba.
        numeric = np.zeros(4, dtype=INVARIANT_DTYPE)
        hard_limit = int(getattr(directory.telemetry.latency_policy, "hard_limit_ns", 0)) if (self.check_latency and hasattr(directory, "telemetry")) else 0
        max_lookup = int(directory.telemetry.snapshot().get("max_ns", 0)) if (self.check_latency and hasattr(directory, "telemetry")) else 0
        n = int(_check_numeric_dir_stats(np.int64(entry_count), np.int64(self.max_entries), np.int64(max_lookup), np.int64(hard_limit), numeric))
        for rec in numeric[:n]:
            code = InvariantCode(int(rec["code"])).name
            violations.append(InvariantViolation(code=code, path=path, observed=int(rec["observed"]), expected=int(rec["expected"]), severity=_severity_name(int(rec["severity"])), message="Numeric directory invariant failed."))
        checked += 2
        return InvariantReport(ok=(len(violations) == 0), path=path, checked=checked, violations=violations, numeric_records=numeric[:n].copy())

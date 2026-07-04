"""Central accelerated JSON backend for Staqtapp-TDS.

v2.9.0 keeps every JSON boundary behind this stateless module while making
backend selection fast and observable. Optional accelerators are imported once
at module load: ``simdjson`` is preferred for parsing and ``orjson`` is
preferred for emission. The public API preserves the existing tuple return
shape so callers can record backend telemetry without scattering JSON logic.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Tuple

try:  # optional parser accelerator
    import simdjson as _simdjson  # type: ignore
except Exception:  # pragma: no cover - depends on optional dependency
    _simdjson = None  # type: ignore[assignment]

try:  # optional serializer accelerator
    import orjson as _orjson  # type: ignore
except Exception:  # pragma: no cover - depends on optional dependency
    _orjson = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class JsonBackendInfo:
    loads_backend: str
    dumps_backend: str
    parse_ns: int = 0
    dump_ns: int = 0
    simdjson_available: bool = False
    orjson_available: bool = False


@dataclass(frozen=True, slots=True)
class JsonCodecStats:
    loads_calls: int = 0
    dumps_calls: int = 0
    parse_ns: int = 0
    dump_ns: int = 0
    simdjson_reads: int = 0
    stdlib_reads: int = 0
    orjson_writes: int = 0
    stdlib_writes: int = 0
    parse_failovers: int = 0
    dump_failovers: int = 0

    @property
    def avg_parse_ns(self) -> int:
        return int(self.parse_ns / max(1, self.loads_calls))

    @property
    def avg_dump_ns(self) -> int:
        return int(self.dump_ns / max(1, self.dumps_calls))

    def to_dict(self) -> dict[str, int | bool | str]:
        data = asdict(self)
        data["avg_parse_ns"] = self.avg_parse_ns
        data["avg_dump_ns"] = self.avg_dump_ns
        data["loads_backend"] = preferred_loads_backend()
        data["dumps_backend"] = preferred_dumps_backend()
        data["simdjson_available"] = _simdjson is not None
        data["orjson_available"] = _orjson is not None
        return data


_stats_lock = threading.Lock()
_stats = JsonCodecStats()


def _bump_stats(*, parse_ns: int = 0, dump_ns: int = 0, backend: str = "", failover: bool = False) -> None:
    global _stats
    with _stats_lock:
        data = asdict(_stats)
        if parse_ns:
            data["loads_calls"] += 1
            data["parse_ns"] += max(0, int(parse_ns))
            if backend == "simdjson":
                data["simdjson_reads"] += 1
            else:
                data["stdlib_reads"] += 1
            if failover:
                data["parse_failovers"] += 1
        if dump_ns:
            data["dumps_calls"] += 1
            data["dump_ns"] += max(0, int(dump_ns))
            if backend == "orjson":
                data["orjson_writes"] += 1
            else:
                data["stdlib_writes"] += 1
            if failover:
                data["dump_failovers"] += 1
        _stats = JsonCodecStats(**data)


def codec_stats() -> JsonCodecStats:
    with _stats_lock:
        return _stats


def reset_codec_stats() -> None:
    global _stats
    with _stats_lock:
        _stats = JsonCodecStats()


def preferred_loads_backend() -> str:
    return "simdjson" if _simdjson is not None else "stdlib"


def preferred_dumps_backend() -> str:
    return "orjson" if _orjson is not None else "stdlib"


def _as_bytes(raw: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    if isinstance(raw, memoryview):
        return raw.tobytes()
    if isinstance(raw, str):
        return raw.encode("utf-8")
    raise TypeError(f"JSON input must be bytes-like or str, got {type(raw).__name__}")


def _stdlib_loads(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))


def _stdlib_dumps(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def loads_fast(raw: bytes | bytearray | memoryview | str) -> Tuple[Any, str]:
    """Parse JSON using the fastest available centralized backend.

    ``simdjson`` is selected once at import time when installed. A fresh parser
    is still created per call to avoid document ownership/thread-sharing
    hazards, but the expensive module import/probe no longer sits in the hot
    path. Invalid JSON falls back only when the accelerator itself errors; the
    final stdlib exception remains visible to callers.
    """
    data = _as_bytes(raw)
    start = time.perf_counter_ns()
    if _simdjson is not None:
        try:
            parser = _simdjson.Parser()
            parsed = parser.parse(data, recursive=True)
            elapsed = time.perf_counter_ns() - start
            _bump_stats(parse_ns=elapsed, backend="simdjson")
            return parsed, "simdjson"
        except Exception:
            value = _stdlib_loads(data)
            elapsed = time.perf_counter_ns() - start
            _bump_stats(parse_ns=elapsed, backend="stdlib", failover=True)
            return value, "stdlib"
    value = _stdlib_loads(data)
    elapsed = time.perf_counter_ns() - start
    _bump_stats(parse_ns=elapsed, backend="stdlib")
    return value, "stdlib"


def loads_strict(raw: bytes | bytearray | memoryview | str, *, expected_type: type | tuple[type, ...] | None = None) -> Tuple[Any, str]:
    value, backend = loads_fast(raw)
    if expected_type is not None and not isinstance(value, expected_type):
        if isinstance(expected_type, tuple):
            names = ", ".join(t.__name__ for t in expected_type)
        else:
            names = expected_type.__name__
        raise TypeError(f"JSON payload expected {names}, got {type(value).__name__}")
    return value, backend


def loads_manifest(raw: bytes | bytearray | memoryview | str) -> Tuple[dict[str, Any], str]:
    value, backend = loads_strict(raw, expected_type=dict)
    if "tds_manifest_version" in value and int(value.get("tds_manifest_version", 0)) <= 0:
        raise ValueError("tds_manifest_version must be positive")
    return dict(value), backend


def loads_snapshot(raw: bytes | bytearray | memoryview | str) -> Tuple[dict[str, Any], str]:
    value, backend = loads_strict(raw, expected_type=dict)
    if "schema_version" in value and int(value.get("schema_version", 0)) <= 0:
        raise ValueError("snapshot schema_version must be positive")
    return dict(value), backend


def loads_policy(raw: bytes | bytearray | memoryview | str) -> Tuple[dict[str, Any], str]:
    value, backend = loads_strict(raw, expected_type=dict)
    return dict(value), backend


def dumps_canonical(value: Any) -> Tuple[bytes, str]:
    """Emit deterministic compact JSON bytes through the centralized codec."""
    start = time.perf_counter_ns()
    if _orjson is not None:
        try:
            raw = _orjson.dumps(value, option=_orjson.OPT_SORT_KEYS)
            elapsed = time.perf_counter_ns() - start
            _bump_stats(dump_ns=elapsed, backend="orjson")
            return raw, "orjson"
        except Exception:
            raw = _stdlib_dumps(value, pretty=False)
            elapsed = time.perf_counter_ns() - start
            _bump_stats(dump_ns=elapsed, backend="stdlib", failover=True)
            return raw, "stdlib"
    raw = _stdlib_dumps(value, pretty=False)
    elapsed = time.perf_counter_ns() - start
    _bump_stats(dump_ns=elapsed, backend="stdlib")
    return raw, "stdlib"


def dumps_status(value: Mapping[str, Any]) -> Tuple[bytes, str, int]:
    """Emit compact status/browser telemetry JSON for polling endpoints."""
    start = time.perf_counter_ns()
    raw, backend = dumps_canonical(value)
    return raw, backend, time.perf_counter_ns() - start


def dumps_pretty(value: Any) -> Tuple[str, str]:
    start = time.perf_counter_ns()
    if _orjson is not None:
        try:
            raw = _orjson.dumps(value, option=_orjson.OPT_SORT_KEYS | _orjson.OPT_INDENT_2)
            elapsed = time.perf_counter_ns() - start
            _bump_stats(dump_ns=elapsed, backend="orjson")
            return raw.decode("utf-8") + "\n", "orjson"
        except Exception:
            text = _stdlib_dumps(value, pretty=True).decode("utf-8")
            elapsed = time.perf_counter_ns() - start
            _bump_stats(dump_ns=elapsed, backend="stdlib", failover=True)
            return text, "stdlib"
    text = _stdlib_dumps(value, pretty=True).decode("utf-8")
    elapsed = time.perf_counter_ns() - start
    _bump_stats(dump_ns=elapsed, backend="stdlib")
    return text, "stdlib"


def dumps_snapshot(value: Mapping[str, Any]) -> Tuple[bytes, str, int]:
    start = time.perf_counter_ns()
    raw, backend = dumps_canonical(value)
    return raw, backend, time.perf_counter_ns() - start


def backend_probe() -> JsonBackendInfo:
    return JsonBackendInfo(
        loads_backend=preferred_loads_backend(),
        dumps_backend=preferred_dumps_backend(),
        simdjson_available=_simdjson is not None,
        orjson_available=_orjson is not None,
    )

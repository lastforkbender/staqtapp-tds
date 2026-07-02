"""Central JSON backend for Staqtapp-TDS.

v2.7.0 keeps JSON parsing and emission behind one stateless module so
simdjson/orjson can be used without thread-shared parser objects or scattered
fallback logic.  The functions never read live engine state and never retain
references to backend parser documents.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping, Tuple


@dataclass(frozen=True, slots=True)
class JsonBackendInfo:
    loads_backend: str
    dumps_backend: str
    parse_ns: int = 0
    dump_ns: int = 0


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
    """Parse JSON with simdjson when installed; fall back to stdlib.

    A fresh parser is intentionally created per call because simdjson parser
    instances retain document ownership constraints and should not be shared
    across telemetry/admin/persistence threads.
    """
    data = _as_bytes(raw)
    try:
        import simdjson  # type: ignore
        parser = simdjson.Parser()
        parsed = parser.parse(data, recursive=True)
        return parsed, "simdjson"
    except Exception:
        return _stdlib_loads(data), "stdlib"


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
    """Emit deterministic compact JSON bytes.  orjson is preferred for writes."""
    try:
        import orjson  # type: ignore
        return orjson.dumps(value, option=orjson.OPT_SORT_KEYS), "orjson"
    except Exception:
        return _stdlib_dumps(value, pretty=False), "stdlib"


def dumps_pretty(value: Any) -> Tuple[str, str]:
    try:
        import orjson  # type: ignore
        raw = orjson.dumps(value, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2)
        return raw.decode("utf-8") + "\n", "orjson"
    except Exception:
        return _stdlib_dumps(value, pretty=True).decode("utf-8"), "stdlib"


def dumps_snapshot(value: Mapping[str, Any]) -> Tuple[bytes, str, int]:
    start = time.perf_counter_ns()
    raw, backend = dumps_canonical(value)
    return raw, backend, time.perf_counter_ns() - start


def backend_probe() -> JsonBackendInfo:
    _, loads_backend = loads_fast(b"{}")
    _, dumps_backend = dumps_canonical({})
    return JsonBackendInfo(loads_backend=loads_backend, dumps_backend=dumps_backend)

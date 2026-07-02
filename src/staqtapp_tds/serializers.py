"""Payload serializer policy for Staqtapp-TDS."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Tuple

from staqtapp_tds import tds_json

import numpy as np


class PayloadKind(IntEnum):
    RAW_BINARY = 0
    NUMPY_ARRAY = 1
    PICKLE_OBJ = 2
    TEXT_UTF8 = 3
    JSON_UTF8 = 5


@dataclass(frozen=True)
class CompressionPolicy:
    enabled: bool = False
    codec: str = ""
    threshold_bytes: int = 4096

    def should_compress(self, raw_len: int, *, force: bool | None = None) -> bool:
        if force is True:
            return True
        if force is False:
            return False
        return bool(self.enabled and int(raw_len) >= int(self.threshold_bytes))


@dataclass(frozen=True)
class SerializerDecision:
    kind: PayloadKind
    fmt_name: str
    json_backend: str = "stdlib"


def content_hash_bytes(raw: bytes, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    h.update(raw)
    return h.hexdigest()


def json_dumps_fast(value: Any) -> Tuple[bytes, str]:
    """Return canonical JSON bytes and backend name via the centralized JSON layer."""
    return tds_json.dumps_canonical(value)


def json_loads_fast(raw: bytes) -> Tuple[Any, str]:
    """Parse JSON bytes through the centralized simdjson-aware layer."""
    return tds_json.loads_fast(raw)

def is_json_safe_value(value: Any) -> bool:
    # Keep this conservative so Python variable types are preserved.  Tuples,
    # sets, bytes, and custom objects remain PICKLE_OBJ.
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(is_json_safe_value(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_json_safe_value(v) for k, v in value.items())
    return False


def choose_variable_kind(value: Any) -> PayloadKind:
    if isinstance(value, np.ndarray):
        return PayloadKind.NUMPY_ARRAY
    if is_json_safe_value(value):
        return PayloadKind.JSON_UTF8
    return PayloadKind.PICKLE_OBJ


def kind_name(kind: PayloadKind | int) -> str:
    try:
        return PayloadKind(int(kind)).name
    except Exception:
        return "UNKNOWN"

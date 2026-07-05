"""Serialization Manager for TDS payload and variable APIs.

This layer is intentionally above the storage engine and below public APIs such
as addvar/loadvar/findvar/read.  It decides which stable byte codec should be
used for a Python value, and it is the only non-pickle module that is allowed to
route a Python-object compatibility payload to the restricted pickle boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Protocol

import numpy as np

from staqtapp_tds.serializers import (
    PayloadKind,
    is_json_safe_value,
    json_dumps_fast,
    json_loads_fast,
    kind_name,
)
from staqtapp_tds.tds_pickle import dumps_pickle, loads_pickle


FMT_RAW_BINARY = int(PayloadKind.RAW_BINARY)
FMT_NUMPY_MATRIX = int(PayloadKind.NUMPY_ARRAY)
FMT_PICKLE_OBJ = int(PayloadKind.PICKLE_OBJ)
FMT_TEXT_UTF8 = int(PayloadKind.TEXT_UTF8)
FMT_JSON_UTF8 = int(PayloadKind.JSON_UTF8)


@dataclass(frozen=True)
class EncodedPayload:
    """Bytes emitted by a serialization codec plus audit metadata."""

    raw: bytes
    fmt_id: int
    payload_kind: str
    codec_name: str
    json_backend: str = ""


class SerializationCodec(Protocol):
    """Minimal codec protocol used by the manager and registry."""

    name: str
    fmt_id: int

    def can_handle(self, value: Any) -> bool: ...
    def dumps(self, value: Any) -> EncodedPayload: ...
    def loads(self, raw: bytes) -> Any: ...


@dataclass(frozen=True)
class _FunctionCodec:
    name: str
    fmt_id: int
    predicate: Callable[[Any], bool]
    dump_fn: Callable[[Any], bytes | tuple[bytes, str]]
    load_fn: Callable[[bytes], Any | tuple[Any, str]]

    def can_handle(self, value: Any) -> bool:
        return bool(self.predicate(value))

    def dumps(self, value: Any) -> EncodedPayload:
        dumped = self.dump_fn(value)
        json_backend = ""
        if (
            isinstance(dumped, tuple)
            and len(dumped) == 2
            and isinstance(dumped[0], (bytes, bytearray, memoryview))
            and isinstance(dumped[1], str)
        ):
            raw, json_backend = dumped
        else:
            raw = dumped
        return EncodedPayload(
            raw=bytes(raw),
            fmt_id=int(self.fmt_id),
            payload_kind=kind_name(int(self.fmt_id)),
            codec_name=self.name,
            json_backend=json_backend,
        )

    def loads(self, raw: bytes) -> Any:
        loaded = self.load_fn(bytes(raw))
        if (
            isinstance(loaded, tuple)
            and len(loaded) == 2
            and isinstance(loaded[1], str)
            and self.name == "json_utf8"
        ):
            return loaded[0]
        return loaded


class CodecRegistry:
    """Ordered codec registry.

    Registration order matters for inference.  More specific codecs should be
    registered before broad fallbacks such as restricted pickle.
    """

    def __init__(self, codecs: Iterable[SerializationCodec] = ()):
        self._ordered: list[SerializationCodec] = []
        self._by_name: Dict[str, SerializationCodec] = {}
        self._by_fmt: Dict[int, SerializationCodec] = {}
        for codec in codecs:
            self.register(codec)

    def register(self, codec: SerializationCodec, *, replace: bool = False) -> None:
        name = str(codec.name)
        fmt_id = int(codec.fmt_id)
        if not replace and (name in self._by_name or fmt_id in self._by_fmt):
            raise ValueError(f"serialization codec already registered: {name}/{fmt_id}")
        if replace:
            self._ordered = [c for c in self._ordered if c.name != name and int(c.fmt_id) != fmt_id]
        self._ordered.append(codec)
        self._by_name[name] = codec
        self._by_fmt[fmt_id] = codec

    def codec_for_name(self, name: str) -> SerializationCodec:
        return self._by_name[str(name)]

    def codec_for_fmt(self, fmt_id: int) -> Optional[SerializationCodec]:
        return self._by_fmt.get(int(fmt_id))

    def infer(self, value: Any) -> SerializationCodec:
        for codec in self._ordered:
            if codec.can_handle(value):
                return codec
        return self._by_name["restricted_pickle"]

    def snapshot(self) -> dict[str, Any]:
        return {
            "codecs": [c.name for c in self._ordered],
            "fmt_ids": {c.name: int(c.fmt_id) for c in self._ordered},
        }


def _dumps_numpy(value: Any) -> bytes:
    import io
    buf = io.BytesIO()
    np.save(buf, value, allow_pickle=False)
    return buf.getvalue()


def _loads_numpy(raw: bytes) -> Any:
    import io
    return np.load(io.BytesIO(raw), allow_pickle=False)


def _dumps_text(value: Any) -> bytes:
    if not isinstance(value, str):
        raise TypeError(f"TEXT_UTF8 entries require str, got {type(value).__name__}")
    return value.encode("utf-8")


def _loads_text(raw: bytes) -> Any:
    return raw.decode("utf-8")


def _dumps_raw_binary(value: Any) -> bytes:
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, bytes):
        return value
    raise TypeError(f"RAW_BINARY entries require bytes-like data, got {type(value).__name__}")


class SerializationManager:
    """Single gateway for Python-value serialization and deserialization."""

    def __init__(self, registry: CodecRegistry | None = None):
        self.registry = registry or self.default_registry()

    @staticmethod
    def default_registry() -> CodecRegistry:
        return CodecRegistry([
            _FunctionCodec("raw_binary", FMT_RAW_BINARY, lambda v: isinstance(v, (bytes, bytearray, memoryview)), _dumps_raw_binary, bytes),
            _FunctionCodec("numpy_matrix", FMT_NUMPY_MATRIX, lambda v: isinstance(v, np.ndarray), _dumps_numpy, _loads_numpy),
            _FunctionCodec("text_utf8", FMT_TEXT_UTF8, lambda v: isinstance(v, str), _dumps_text, _loads_text),
            _FunctionCodec("json_utf8", FMT_JSON_UTF8, is_json_safe_value, json_dumps_fast, json_loads_fast),
            _FunctionCodec("restricted_pickle", FMT_PICKLE_OBJ, lambda _v: True, dumps_pickle, loads_pickle),
        ])

    def choose_fmt_id(self, value: Any) -> int:
        return int(self.registry.infer(value).fmt_id)

    def serialize(self, value: Any, fmt_id: int | None = None) -> EncodedPayload:
        if fmt_id is None:
            codec = self.registry.infer(value)
        else:
            codec = self.registry.codec_for_fmt(int(fmt_id))
            if codec is None:
                # Compatibility lane: unknown historical Python object formats
                # must still flow through the restricted pickle boundary.
                codec = self.registry.codec_for_name("restricted_pickle")
        return codec.dumps(value)

    def deserialize(self, raw: bytes, fmt_id: int) -> Any:
        codec = self.registry.codec_for_fmt(int(fmt_id))
        if codec is None:
            codec = self.registry.codec_for_name("restricted_pickle")
        return codec.loads(raw)

    def snapshot(self) -> dict[str, Any]:
        return self.registry.snapshot()


_DEFAULT_MANAGER = SerializationManager()


def get_default_serialization_manager() -> SerializationManager:
    return _DEFAULT_MANAGER

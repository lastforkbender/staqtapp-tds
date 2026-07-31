"""Strict UTF-8 boundary planning for bounded native and Python chunking."""
from __future__ import annotations

from typing import Any

from staqtapp_tds.native.manager import get_native_manager

UTF8_CHUNK_CONTRACT = "strict-rfc3629-complete-codepoints-v1"


def _snapshot_bytes(payload: Any) -> bytes:
    if type(payload) is bytes:
        return payload
    try:
        view = memoryview(payload)
    except TypeError as exc:
        raise TypeError("UTF-8 input must support the contiguous buffer protocol") from exc
    try:
        if not view.contiguous:
            raise TypeError("UTF-8 input must be contiguous")
        return view.tobytes()
    finally:
        view.release()


def _sequence_length(data: bytes, position: int) -> int:
    lead = data[position]
    remaining = len(data) - position

    def continuation(offset: int) -> int:
        if offset >= remaining:
            raise UnicodeDecodeError(
                "utf-8", data, position, len(data), "unexpected end of data"
            )
        value = data[position + offset]
        if value < 0x80 or value > 0xBF:
            raise UnicodeDecodeError(
                "utf-8",
                data,
                position + offset,
                position + offset + 1,
                "invalid continuation byte",
            )
        return value

    if lead <= 0x7F:
        return 1
    if 0xC2 <= lead <= 0xDF:
        continuation(1)
        return 2
    if lead == 0xE0:
        second = continuation(1)
        continuation(2)
        if second < 0xA0:
            raise UnicodeDecodeError(
                "utf-8", data, position, position + 3, "invalid overlong encoding"
            )
        return 3
    if 0xE1 <= lead <= 0xEC or 0xEE <= lead <= 0xEF:
        continuation(1)
        continuation(2)
        return 3
    if lead == 0xED:
        second = continuation(1)
        continuation(2)
        if second > 0x9F:
            raise UnicodeDecodeError(
                "utf-8", data, position, position + 3, "UTF-8 surrogate encoding"
            )
        return 3
    if lead == 0xF0:
        second = continuation(1)
        continuation(2)
        continuation(3)
        if second < 0x90:
            raise UnicodeDecodeError(
                "utf-8", data, position, position + 4, "invalid overlong encoding"
            )
        return 4
    if 0xF1 <= lead <= 0xF3:
        continuation(1)
        continuation(2)
        continuation(3)
        return 4
    if lead == 0xF4:
        second = continuation(1)
        continuation(2)
        continuation(3)
        if second > 0x8F:
            raise UnicodeDecodeError(
                "utf-8", data, position, position + 4, "code point exceeds U+10FFFF"
            )
        return 4
    raise UnicodeDecodeError("utf-8", data, position, position + 1, "invalid start byte")


def utf8_chunk_bounds_python(payload: Any, chunk_size: int) -> list[int]:
    """Return strict RFC 3629 boundaries from one immutable byte snapshot."""

    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TypeError("chunk_size must be an integer")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    data = _snapshot_bytes(payload)
    bounds: list[int] = []
    position = 0
    chunk_start = 0
    while position < len(data):
        width = _sequence_length(data, position)
        if position > chunk_start and position + width - chunk_start > chunk_size:
            bounds.append(position)
            chunk_start = position
        position += width
        if position - chunk_start >= chunk_size:
            bounds.append(position)
            chunk_start = position
    if not bounds or bounds[-1] != len(data):
        if data:
            bounds.append(len(data))
    return bounds


def _validate_bounds(data: bytes, bounds: list[int], chunk_size: int) -> None:
    start = 0
    for end in bounds:
        if isinstance(end, bool) or not isinstance(end, int):
            raise ValueError("native UTF-8 boundary is not an integer")
        if end <= start or end > len(data):
            raise ValueError("native UTF-8 boundaries are not strictly increasing")
        chunk = data[start:end]
        chunk.decode("utf-8")
        if len(chunk) > chunk_size:
            text = chunk.decode("utf-8")
            if len(text) != 1 or len(chunk) > 4:
                raise ValueError("native UTF-8 chunk exceeds the qualified budget")
        start = end
    if start != len(data):
        raise ValueError("native UTF-8 boundaries do not cover the full input")


def utf8_chunk_bounds(
    payload: Any,
    chunk_size: int,
    *,
    prefer_native: bool = True,
) -> tuple[list[int], str]:
    """Return strict boundaries and the backend that produced them."""

    data = _snapshot_bytes(payload)
    if prefer_native:
        manager = get_native_manager()
        module, report = manager.inspect_module("staqtapp_tds._native_index")
        if module is not None and report.compatible:
            contract = getattr(module, "TDS_NATIVE_UTF8_CHUNK_CONTRACT", None)
            if contract == UTF8_CHUNK_CONTRACT and hasattr(module, "utf8_chunk_bounds"):
                bounds = [
                    int(value) for value in module.utf8_chunk_bounds(data, chunk_size)
                ]
                _validate_bounds(data, bounds, chunk_size)
                return bounds, "native"
    bounds = utf8_chunk_bounds_python(data, chunk_size)
    _validate_bounds(data, bounds, chunk_size)
    return bounds, "python"


__all__ = ["UTF8_CHUNK_CONTRACT", "utf8_chunk_bounds", "utf8_chunk_bounds_python"]

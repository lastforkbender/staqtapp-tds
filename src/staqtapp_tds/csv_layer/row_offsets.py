"""Logical CSV record offset generation.

The v3.2.1 scanner keeps the public contract from v3.2.0 while moving the
hot mechanical scan to bytes + memoryview. That avoids repeated whole-string
encoding during large CSV imports and keeps this primitive ready for a future
native CSV kernel sidecar.
"""

from __future__ import annotations

import hashlib
import sys
from array import array
from collections.abc import Iterable

from .artifacts import CSVRowOffsetMap
from .dialect import CSVDialectFingerprint


def _single_byte_token(value: str | None, *, encoding: str, default: bytes) -> bytes:
    if not value:
        return default
    token = value.encode(encoding)
    if len(token) != 1:
        # The stdlib CSV contract expects one-character delimiter/quote tokens.
        # Keep the scanner deterministic by falling back to the default byte.
        return default
    return token


def pack_csv_row_offsets(row_offsets: Iterable[int]) -> bytes:
    """Pack row offsets into a compact little-endian uint64 byte vector.

    The public CSV artifacts still use JSON for v3.3.x compatibility. This
    helper defines the future packed-offset shape without changing the fixed
    import write plan or requiring native storage changes.
    """
    values = array("Q")
    for offset in row_offsets:
        value = int(offset)
        if value < 0:
            raise ValueError("row offsets must be non-negative")
        values.append(value)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def unpack_csv_row_offsets(payload: bytes | bytearray | memoryview) -> tuple[int, ...]:
    """Unpack a little-endian uint64 row-offset byte vector."""
    view = memoryview(payload).cast("B")
    if len(view) % 8 != 0:
        raise ValueError("packed row offset payload must be 8-byte aligned")
    values = array("Q")
    values.frombytes(view)
    if sys.byteorder != "little":
        values.byteswap()
    return tuple(int(value) for value in values)


def logical_record_offsets_bytes(raw: bytes | bytearray | memoryview, dialect: CSVDialectFingerprint, *, encoding: str = "utf-8") -> tuple[int, ...]:
    """Return byte offsets for logical CSV records from raw CSV bytes.

    This is the foundation scanner used by TDS CSV imports. It honors quote
    state, doubled quotes, optional escape characters, LF/CR/CRLF record
    terminators, and terminal newlines. It does not parse cell semantics; it
    only returns logical record starts so the storage layer can preserve the
    original source and write compact derived metadata.
    """
    view = memoryview(raw).cast("B")
    if len(view) == 0:
        return tuple()

    quote = _single_byte_token(dialect.quotechar, encoding=encoding, default=b'"')[0]
    escape_raw = dialect.escapechar.encode(encoding) if dialect.escapechar else b""
    escape = escape_raw[0] if len(escape_raw) == 1 else None
    doublequote = bool(dialect.doublequote)
    offsets: list[int] = [0]
    in_quotes = False
    i = 0
    n = len(view)

    while i < n:
        byte = view[i]
        if escape is not None and in_quotes and byte == escape and i + 1 < n:
            # Escaped byte inside a quoted field; skip the escaped payload byte.
            i += 2
            continue
        if byte == quote:
            next_is_quote = i + 1 < n and view[i + 1] == quote
            if in_quotes and doublequote and next_is_quote:
                i += 2
                continue
            in_quotes = not in_quotes
        elif not in_quotes and (byte == 10 or byte == 13):
            # LF or CR/CRLF outside quotes starts the next logical record.
            if byte == 13 and i + 1 < n and view[i + 1] == 10:
                i += 1
            next_offset = i + 1
            if next_offset < n:
                offsets.append(next_offset)
        i += 1

    return tuple(offsets)


def logical_record_offsets(text: str, dialect: CSVDialectFingerprint, *, encoding: str = "utf-8") -> tuple[int, ...]:
    """Return byte offsets for logical CSV records.

    The text-based public helper now encodes once and delegates to the
    memoryview/bytes scanner. A future native CSV kernel can replace the same
    mechanical primitive without changing callers.
    """
    return logical_record_offsets_bytes(text.encode(encoding), dialect, encoding=encoding)


def build_row_offset_map(
    text: str,
    dialect: CSVDialectFingerprint,
    *,
    encoding: str = "utf-8",
    raw: bytes | None = None,
) -> CSVRowOffsetMap:
    source = raw if raw is not None else text.encode(encoding)
    offsets = logical_record_offsets_bytes(source, dialect, encoding=encoding)
    return CSVRowOffsetMap(
        encoding=encoding,
        row_offsets=offsets,
        row_count=len(offsets),
        source_hash=hashlib.sha256(source).hexdigest(),
        logical_records=True,
    )

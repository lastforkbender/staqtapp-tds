"""CSV scan reference primitives for the v3.3.x CSV kernel lane.

This module is deliberately above the TDS storage engine.  It performs
mechanical byte scans over immutable CSV payloads and returns compact scan
profiles that can be compared with existing row-offset artifacts.  It is the
Python correctness reference for any future optional native CSV kernel sidecar.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

BytesLike = bytes | bytearray | memoryview

from staqtapp_tds.tds_filesystem import TDSDirectory

from .artifacts import CSVDialectFingerprint, CSVRowOffsetMap
from .importer import load_csv_manifest
from .manifest import artifact_keys


@dataclass(frozen=True, slots=True)
class CSVScanProfile:
    """Mechanical byte-scan profile for a CSV payload.

    The profile contains only scan facts: logical row starts, newline classes,
    quote/delimiter counters, and chunk-shape information. It does not infer
    schema, types, meaning, repair actions, or seed-module policy.
    """

    encoding: str
    raw_size: int
    raw_sha256: str
    row_offsets: tuple[int, ...]
    row_count: int
    newline_lf_count: int
    newline_crlf_count: int
    newline_cr_count: int
    quoted_newline_count: int
    delimiter_count: int
    quote_count: int
    escaped_quote_count: int
    escape_sequence_count: int
    max_record_span: int
    terminal_newline: bool
    ended_in_open_quote: bool
    chunk_size: int | None
    chunk_count: int
    scanner: str = "python.memoryview.reference"
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["row_offsets"] = list(self.row_offsets)
        return data

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "CSVScanProfile":
        return cls(
            encoding=str(data.get("encoding", "utf-8")),
            raw_size=int(data.get("raw_size", 0)),
            raw_sha256=str(data.get("raw_sha256", "")),
            row_offsets=tuple(int(v) for v in data.get("row_offsets", []) or []),
            row_count=int(data.get("row_count", 0)),
            newline_lf_count=int(data.get("newline_lf_count", 0)),
            newline_crlf_count=int(data.get("newline_crlf_count", 0)),
            newline_cr_count=int(data.get("newline_cr_count", 0)),
            quoted_newline_count=int(data.get("quoted_newline_count", 0)),
            delimiter_count=int(data.get("delimiter_count", 0)),
            quote_count=int(data.get("quote_count", 0)),
            escaped_quote_count=int(data.get("escaped_quote_count", 0)),
            escape_sequence_count=int(data.get("escape_sequence_count", 0)),
            max_record_span=int(data.get("max_record_span", 0)),
            terminal_newline=bool(data.get("terminal_newline", False)),
            ended_in_open_quote=bool(data.get("ended_in_open_quote", False)),
            chunk_size=(None if data.get("chunk_size") is None else int(data.get("chunk_size"))),
            chunk_count=int(data.get("chunk_count", 0)),
            scanner=str(data.get("scanner", "python.memoryview.reference")),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVScanParityReport:
    """Parity proof between a scan profile and durable CSV artifacts."""

    csv_id: str
    status: str
    raw_sha256_verified: bool
    row_offsets_match: bool
    row_count_match: bool
    scan_row_count: int
    artifact_row_count: int
    checked_artifacts: tuple[str, ...]
    errors: tuple[str, ...]
    scanner: str
    chunk_size: int | None
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "valid" and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_artifacts"] = list(self.checked_artifacts)
        data["errors"] = list(self.errors)
        data["ok"] = self.ok
        return data


@dataclass(frozen=True, slots=True)
class CSVRowAnchorProfile:
    """Exact byte-anchor hashes for logical CSV records.

    Row anchors are mechanical scan evidence, not semantic row identity. Each
    hash covers the exact original bytes for one logical CSV record, including
    its row terminator when present. This keeps future Semantic IR work grounded
    in immutable source bytes without writing one TDS artifact per row.
    """

    encoding: str
    raw_size: int
    raw_sha256: str
    row_offsets: tuple[int, ...]
    row_spans: tuple[int, ...]
    row_anchor_hashes: tuple[str, ...]
    row_count: int
    digest_algorithm: str
    chunk_size: int | None
    chunk_count: int
    scanner: str = "python.memoryview.row_anchor.reference"
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["row_offsets"] = list(self.row_offsets)
        data["row_spans"] = list(self.row_spans)
        data["row_anchor_hashes"] = list(self.row_anchor_hashes)
        return data

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "CSVRowAnchorProfile":
        return cls(
            encoding=str(data.get("encoding", "utf-8")),
            raw_size=int(data.get("raw_size", 0)),
            raw_sha256=str(data.get("raw_sha256", "")),
            row_offsets=tuple(int(v) for v in data.get("row_offsets", []) or []),
            row_spans=tuple(int(v) for v in data.get("row_spans", []) or []),
            row_anchor_hashes=tuple(str(v) for v in data.get("row_anchor_hashes", []) or []),
            row_count=int(data.get("row_count", 0)),
            digest_algorithm=str(data.get("digest_algorithm", "sha256")),
            chunk_size=(None if data.get("chunk_size") is None else int(data.get("chunk_size"))),
            chunk_count=int(data.get("chunk_count", 0)),
            scanner=str(data.get("scanner", "python.memoryview.row_anchor.reference")),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVRowAnchorParityReport:
    """Parity proof for row anchors against durable CSV scan artifacts."""

    csv_id: str
    status: str
    raw_sha256_verified: bool
    row_offsets_match: bool
    row_count_match: bool
    anchor_row_count: int
    artifact_row_count: int
    checked_artifacts: tuple[str, ...]
    errors: tuple[str, ...]
    scanner: str
    chunk_size: int | None
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "valid" and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_artifacts"] = list(self.checked_artifacts)
        data["errors"] = list(self.errors)
        data["ok"] = self.ok
        return data


def _single_byte_token(value: str | None, *, encoding: str, default: bytes) -> int:
    if not value:
        return default[0]
    try:
        token = value.encode(encoding)
    except Exception:
        return default[0]
    return token[0] if len(token) == 1 else default[0]


def _chunk_count(raw_size: int, chunk_size: int | None) -> int:
    if raw_size == 0:
        return 0
    if chunk_size is None:
        return 1
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive when provided")
    return (raw_size + chunk_size - 1) // chunk_size


def scan_csv_bytes(
    raw: BytesLike,
    dialect: CSVDialectFingerprint,
    *,
    encoding: str = "utf-8",
    chunk_size: int | None = None,
) -> CSVScanProfile:
    """Scan raw CSV bytes using the Python reference scanner.

    ``chunk_size`` exercises the same state machine across artificial chunk
    boundaries. The returned row offsets must match the existing v3.2.x row
    offset scanner; tests keep this as the correctness reference for later
    native-kernel parity.
    """
    view = memoryview(raw).cast("B")
    n = len(view)
    chunks = _chunk_count(n, chunk_size)
    raw_sha256 = hashlib.sha256(view).hexdigest()
    if n == 0:
        return CSVScanProfile(
            encoding=encoding,
            raw_size=0,
            raw_sha256=raw_sha256,
            row_offsets=tuple(),
            row_count=0,
            newline_lf_count=0,
            newline_crlf_count=0,
            newline_cr_count=0,
            quoted_newline_count=0,
            delimiter_count=0,
            quote_count=0,
            escaped_quote_count=0,
            escape_sequence_count=0,
            max_record_span=0,
            terminal_newline=False,
            ended_in_open_quote=False,
            chunk_size=chunk_size,
            chunk_count=chunks,
        )

    quote = _single_byte_token(dialect.quotechar, encoding=encoding, default=b'"')
    delimiter = _single_byte_token(dialect.delimiter, encoding=encoding, default=b",")
    escape_raw = dialect.escapechar.encode(encoding) if dialect.escapechar else b""
    escape = escape_raw[0] if len(escape_raw) == 1 else None
    doublequote = bool(dialect.doublequote)

    offsets: list[int] = [0]
    in_quotes = False
    newline_lf_count = 0
    newline_crlf_count = 0
    newline_cr_count = 0
    quoted_newline_count = 0
    delimiter_count = 0
    quote_count = 0
    escaped_quote_count = 0
    escape_sequence_count = 0

    i = 0
    last_record_start = 0
    max_record_span = 0
    while i < n:
        byte = view[i]
        if escape is not None and in_quotes and byte == escape and i + 1 < n:
            escape_sequence_count += 1
            i += 2
            continue

        if byte == quote:
            quote_count += 1
            next_is_quote = i + 1 < n and view[i + 1] == quote
            if in_quotes and doublequote and next_is_quote:
                escaped_quote_count += 1
                quote_count += 1
                i += 2
                continue
            in_quotes = not in_quotes
        elif byte == delimiter and not in_quotes:
            delimiter_count += 1
        elif byte == 10 or byte == 13:
            is_crlf = byte == 13 and i + 1 < n and view[i + 1] == 10
            if in_quotes:
                quoted_newline_count += 1
                if is_crlf:
                    i += 1
            else:
                if is_crlf:
                    newline_crlf_count += 1
                    i += 1
                elif byte == 10:
                    newline_lf_count += 1
                else:
                    newline_cr_count += 1
                next_offset = i + 1
                if next_offset < n:
                    span = next_offset - last_record_start
                    if span > max_record_span:
                        max_record_span = span
                    offsets.append(next_offset)
                    last_record_start = next_offset
        i += 1

    tail_span = n - last_record_start
    if tail_span > max_record_span:
        max_record_span = tail_span
    row_offsets = tuple(offsets)
    terminal_newline = view[n - 1] in (10, 13)
    return CSVScanProfile(
        encoding=encoding,
        raw_size=n,
        raw_sha256=raw_sha256,
        row_offsets=row_offsets,
        row_count=len(row_offsets),
        newline_lf_count=newline_lf_count,
        newline_crlf_count=newline_crlf_count,
        newline_cr_count=newline_cr_count,
        quoted_newline_count=quoted_newline_count,
        delimiter_count=delimiter_count,
        quote_count=quote_count,
        escaped_quote_count=escaped_quote_count,
        escape_sequence_count=escape_sequence_count,
        max_record_span=max_record_span,
        terminal_newline=terminal_newline,
        ended_in_open_quote=in_quotes,
        chunk_size=chunk_size,
        chunk_count=chunks,
    )


def scan_csv_text(
    text: str,
    dialect: CSVDialectFingerprint,
    *,
    encoding: str = "utf-8",
    chunk_size: int | None = None,
) -> CSVScanProfile:
    """Encode text once and scan it with the byte reference scanner."""
    return scan_csv_bytes(text.encode(encoding), dialect, encoding=encoding, chunk_size=chunk_size)


def validate_csv_scan_profile(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
) -> CSVScanParityReport:
    """Compare a fresh scan profile with durable CSV artifacts.

    This is an observational parity check. It reads the raw CSV, manifest, and
    row-offset artifact from storage, but it never writes artifacts or mutates
    native storage behavior.
    """
    keys = artifact_keys(csv_id)
    checked: list[str] = []
    errors: list[str] = []

    manifest = load_csv_manifest(directory, csv_id)
    checked.append("manifest")
    raw_value = directory.read_value(keys["raw"])
    checked.append("raw")
    if not isinstance(raw_value, str):
        raise TypeError(f"CSV raw artifact {keys['raw']!r} is not text")
    row_value = directory.read_value(keys["row_offsets"])
    checked.append("row_offsets")
    if not isinstance(row_value, dict):
        raise TypeError(f"CSV row-offset artifact {keys['row_offsets']!r} is not a JSON object")

    raw = raw_value.encode(manifest.encoding)
    profile = scan_csv_bytes(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)
    row_map = CSVRowOffsetMap.from_mapping(row_value)

    raw_sha256_verified = profile.raw_sha256 == manifest.raw_sha256 == row_map.source_hash
    if not raw_sha256_verified:
        errors.append("scan_raw_sha256_mismatch")
    row_offsets_match = profile.row_offsets == row_map.row_offsets
    if not row_offsets_match:
        errors.append("scan_row_offsets_mismatch")
    row_count_match = profile.row_count == manifest.row_count == row_map.row_count
    if not row_count_match:
        errors.append("scan_row_count_mismatch")

    status = "valid" if not errors else "invalid"
    return CSVScanParityReport(
        csv_id=csv_id,
        status=status,
        raw_sha256_verified=raw_sha256_verified,
        row_offsets_match=row_offsets_match,
        row_count_match=row_count_match,
        scan_row_count=profile.row_count,
        artifact_row_count=row_map.row_count,
        checked_artifacts=tuple(checked),
        errors=tuple(errors),
        scanner=profile.scanner,
        chunk_size=chunk_size,
    )


def scan_csv_row_anchors(
    raw: BytesLike,
    dialect: CSVDialectFingerprint,
    *,
    encoding: str = "utf-8",
    chunk_size: int | None = None,
) -> CSVRowAnchorProfile:
    """Return exact byte-anchor hashes for each logical CSV record.

    The function reuses the scan reference row offsets, then hashes memoryview
    slices of the immutable source bytes. It is intentionally separate from
    :func:`scan_csv_bytes` so routine scan profiles stay compact and callers opt
    in only when row-level anchor evidence is needed.
    """
    view = memoryview(raw).cast("B")
    n = len(view)
    profile = scan_csv_bytes(view, dialect, encoding=encoding, chunk_size=chunk_size)
    spans: list[int] = []
    hashes: list[str] = []
    offsets = profile.row_offsets
    for idx, start in enumerate(offsets):
        end = offsets[idx + 1] if idx + 1 < len(offsets) else n
        span = end - start
        spans.append(span)
        hashes.append(hashlib.sha256(view[start:end]).hexdigest())
    return CSVRowAnchorProfile(
        encoding=encoding,
        raw_size=n,
        raw_sha256=profile.raw_sha256,
        row_offsets=offsets,
        row_spans=tuple(spans),
        row_anchor_hashes=tuple(hashes),
        row_count=profile.row_count,
        digest_algorithm="sha256",
        chunk_size=chunk_size,
        chunk_count=profile.chunk_count,
    )


def scan_csv_text_row_anchors(
    text: str,
    dialect: CSVDialectFingerprint,
    *,
    encoding: str = "utf-8",
    chunk_size: int | None = None,
) -> CSVRowAnchorProfile:
    """Encode text once and build row anchors from the byte reference scanner."""
    return scan_csv_row_anchors(text.encode(encoding), dialect, encoding=encoding, chunk_size=chunk_size)


def validate_csv_row_anchors(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
) -> CSVRowAnchorParityReport:
    """Compare row-anchor scan evidence with durable CSV artifacts.

    This is read-only validation above storage. It does not persist row anchors
    yet; it proves that future row-anchor artifacts can be derived determinis-
    tically from the preserved raw source and current row-offset map.
    """
    keys = artifact_keys(csv_id)
    checked: list[str] = []
    errors: list[str] = []

    manifest = load_csv_manifest(directory, csv_id)
    checked.append("manifest")
    raw_value = directory.read_value(keys["raw"])
    checked.append("raw")
    if not isinstance(raw_value, str):
        raise TypeError(f"CSV raw artifact {keys['raw']!r} is not text")
    row_value = directory.read_value(keys["row_offsets"])
    checked.append("row_offsets")
    if not isinstance(row_value, dict):
        raise TypeError(f"CSV row-offset artifact {keys['row_offsets']!r} is not a JSON object")

    raw = raw_value.encode(manifest.encoding)
    anchors = scan_csv_row_anchors(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)
    row_map = CSVRowOffsetMap.from_mapping(row_value)

    raw_sha256_verified = anchors.raw_sha256 == manifest.raw_sha256 == row_map.source_hash
    if not raw_sha256_verified:
        errors.append("anchor_raw_sha256_mismatch")
    row_offsets_match = anchors.row_offsets == row_map.row_offsets
    if not row_offsets_match:
        errors.append("anchor_row_offsets_mismatch")
    row_count_match = anchors.row_count == manifest.row_count == row_map.row_count
    if not row_count_match:
        errors.append("anchor_row_count_mismatch")

    status = "valid" if not errors else "invalid"
    return CSVRowAnchorParityReport(
        csv_id=csv_id,
        status=status,
        raw_sha256_verified=raw_sha256_verified,
        row_offsets_match=row_offsets_match,
        row_count_match=row_count_match,
        anchor_row_count=anchors.row_count,
        artifact_row_count=row_map.row_count,
        checked_artifacts=tuple(checked),
        errors=tuple(errors),
        scanner=anchors.scanner,
        chunk_size=chunk_size,
    )

"""CSV manifest helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Iterable, Iterator

from .artifacts import CSVImportManifest, CSVImportReport, CSV_LAYER_VERSION
from .dialect import CSVDialectFingerprint, dialect_to_csv_kwargs
from .row_offsets import build_row_offset_map

CSV_ID_MAX_LENGTH = 128
_CSV_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def is_safe_csv_id(csv_id: str) -> bool:
    """Return True when *csv_id* is safe for TDS CSV artifact namespaces.

    CSV IDs become part of durable .tds artifact keys.  The accepted shape is
    intentionally narrower than general TDS entry names so future filesystem or
    native-storage integrations never inherit path separators, control bytes,
    empty names, or unbounded key material from caller input.
    """
    if not isinstance(csv_id, str):
        return False
    return bool(_CSV_ID_RE.fullmatch(csv_id))


def validate_csv_id(csv_id: str) -> str:
    """Return a validated CSV ID or raise ValueError.

    User-supplied IDs are not normalized silently: invalid identifiers fail
    closed so applications do not accidentally create ambiguous or unsafe
    .tds artifact keys.  Generated IDs should come from :func:`safe_csv_id`.
    """
    if not isinstance(csv_id, str):
        raise ValueError("csv_id must be a string")
    if not csv_id:
        raise ValueError("csv_id must not be empty")
    if len(csv_id) > CSV_ID_MAX_LENGTH:
        raise ValueError(f"csv_id must be at most {CSV_ID_MAX_LENGTH} characters")
    if not _CSV_ID_RE.fullmatch(csv_id):
        raise ValueError("csv_id contains unsafe characters or unsafe leading character")
    return csv_id


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_csv_id(source_name: str, raw: bytes) -> str:
    stem = Path(source_name or "csv_source").stem or "csv_source"
    safe = _SAFE_ID_RE.sub("_", stem).strip("._-") or "csv_source"
    suffix = sha256_hex(raw)[:12]
    max_stem = max(1, CSV_ID_MAX_LENGTH - len(suffix) - 1)
    safe = safe[:max_stem].rstrip("._-") or "csv_source"
    return validate_csv_id(f"{safe}_{suffix}")


def artifact_keys(csv_id: str) -> dict[str, str]:
    csv_id = validate_csv_id(csv_id)
    prefix = f"csv__{csv_id}"
    return {
        "raw": f"{prefix}__raw.csv",
        "manifest": f"{prefix}__manifest.json",
        "dialect": f"{prefix}__dialect.json",
        "row_offsets": f"{prefix}__row_offsets.json",
        "content_hashes": f"{prefix}__content_hashes.json",
        "import_report": f"{prefix}__import_report.json",
        "roundtrip_report": f"{prefix}__roundtrip_report.json",
    }


def iter_rows(text: str, dialect: CSVDialectFingerprint) -> Iterator[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), **dialect_to_csv_kwargs(dialect))
    for row in reader:
        yield list(row)


def read_rows(text: str, dialect: CSVDialectFingerprint) -> list[list[str]]:
    return list(iter_rows(text, dialect))


def column_count_from_rows(rows: Iterable[Iterable[str]]) -> int:
    return max((len(tuple(row)) for row in rows), default=0)


def row_count_and_column_count(text: str, dialect: CSVDialectFingerprint) -> tuple[int, int]:
    row_count = 0
    column_count = 0
    for row in iter_rows(text, dialect):
        row_count += 1
        if len(row) > column_count:
            column_count = len(row)
    return row_count, column_count


def build_manifest(
    *,
    source_name: str,
    text: str,
    raw: bytes,
    encoding: str,
    dialect: CSVDialectFingerprint,
    csv_id: str | None = None,
) -> tuple[CSVImportManifest, CSVImportReport, dict[str, object]]:
    """Build manifest/report/hash artifacts without touching storage."""
    real_csv_id = validate_csv_id(csv_id) if csv_id is not None else safe_csv_id(source_name, raw)
    keys = artifact_keys(real_csv_id)
    row_offsets = build_row_offset_map(text, dialect, encoding=encoding, raw=raw)
    row_count, column_count = row_count_and_column_count(text, dialect)
    raw_hash = sha256_hex(raw)
    warnings: list[str] = []
    if row_offsets.row_count != row_count:
        warnings.append("row_offset_count_differs_from_csv_reader_count")
    if column_count == 0 and raw:
        warnings.append("no_columns_detected")
    manifest = CSVImportManifest(
        csv_id=real_csv_id,
        layer_version=CSV_LAYER_VERSION,
        source_name=source_name,
        encoding=encoding,
        raw_size=len(raw),
        raw_sha256=raw_hash,
        row_count=row_count,
        column_count=column_count,
        has_header=dialect.has_header,
        dialect=dialect,
        artifact_keys=keys,
        warnings=tuple(warnings),
    )
    report = CSVImportReport(
        csv_id=real_csv_id,
        status="imported",
        row_count=row_count,
        column_count=column_count,
        raw_sha256=raw_hash,
        dialect_confidence=dialect.confidence,
        warnings=tuple(warnings),
    )
    hashes = {
        "raw_sha256": raw_hash,
        "row_offset_source_sha256": row_offsets.source_hash,
        "row_count": row_offsets.row_count,
        "encoding": encoding,
    }
    return manifest, report, {"row_offsets": row_offsets.to_dict(), "content_hashes": hashes}

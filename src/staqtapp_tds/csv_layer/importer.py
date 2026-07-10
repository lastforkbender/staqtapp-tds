"""TDS-backed CSV import helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from staqtapp_tds.result import TDSResult

from staqtapp_tds.tds_filesystem import TDSDirectory

from .artifacts import CSVImportManifest
from .dialect import detect_csv_dialect
from .manifest import build_manifest


def _require_write(result: TDSResult, artifact: str) -> None:
    if not result.ok:
        raise RuntimeError(f"CSV artifact write failed for {artifact}: {result.code} {result.message}")


def import_csv_bytes(
    directory: TDSDirectory,
    raw: bytes,
    *,
    source_name: str = "csv_source.csv",
    encoding: str = "utf-8",
    csv_id: str | None = None,
    overwrite: bool = False,
) -> CSVImportManifest:
    """Import CSV bytes as durable TDS artifacts.

    The original CSV text is preserved as a first-class text artifact. All
    other files are derived JSON artifacts. The native C storage/index hot path
    only sees ordinary batch-style TDS writes.
    """
    text = raw.decode(encoding)
    dialect = detect_csv_dialect(text)
    manifest, report, derived = build_manifest(
        source_name=source_name,
        text=text,
        raw=raw,
        encoding=encoding,
        dialect=dialect,
        csv_id=csv_id,
    )
    keys = manifest.artifact_keys
    # Raw source first; all follow-up writes are derived artifacts. Each write
    # is checked because TDS public write APIs are non-halting by design.
    _require_write(directory.write_text(keys["raw"], text, overwrite=overwrite, provenance="REAL"), keys["raw"])
    _require_write(directory.write_json(keys["dialect"], manifest.dialect.to_dict(), overwrite=overwrite, provenance="DERIVED"), keys["dialect"])
    _require_write(directory.write_json(keys["row_offsets"], derived["row_offsets"], overwrite=overwrite, provenance="DERIVED"), keys["row_offsets"])
    _require_write(directory.write_json(keys["content_hashes"], derived["content_hashes"], overwrite=overwrite, provenance="DERIVED"), keys["content_hashes"])
    _require_write(directory.write_json(keys["manifest"], manifest.to_dict(), overwrite=overwrite, provenance="DERIVED"), keys["manifest"])
    _require_write(directory.write_json(keys["import_report"], report.to_dict(), overwrite=overwrite, provenance="DERIVED"), keys["import_report"])
    return manifest


def import_csv_file(
    directory: TDSDirectory,
    path: str | Path,
    *,
    encoding: str = "utf-8",
    csv_id: str | None = None,
    overwrite: bool = False,
) -> CSVImportManifest:
    path = Path(path)
    return import_csv_bytes(
        directory,
        path.read_bytes(),
        source_name=path.name,
        encoding=encoding,
        csv_id=csv_id,
        overwrite=overwrite,
    )


def load_csv_manifest(directory: TDSDirectory, csv_id: str) -> CSVImportManifest:
    from .manifest import artifact_keys

    key = artifact_keys(csv_id)["manifest"]
    value: Any = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV manifest artifact {key!r} is not a JSON object")
    return CSVImportManifest.from_mapping(value)

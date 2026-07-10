"""CSV export and round-trip proof helpers."""

from __future__ import annotations

import csv
import io
from typing import Any

from staqtapp_tds.tds_filesystem import TDSDirectory

from .artifacts import CSVDialectFingerprint, CSVRoundTripReport
from .dialect import dialect_to_csv_kwargs
from .manifest import artifact_keys, read_rows, sha256_hex
from .importer import load_csv_manifest


def export_original_csv(directory: TDSDirectory, csv_id: str) -> str:
    """Return the preserved original CSV text for a managed source."""
    key = artifact_keys(csv_id)["raw"]
    value = directory.read_value(key)
    if not isinstance(value, str):
        raise TypeError(f"CSV raw artifact {key!r} is not text")
    return value


def export_canonical_csv(directory: TDSDirectory, csv_id: str, *, lineterminator: str = "\n") -> str:
    """Return a deterministic canonical CSV view derived from the source."""
    manifest = load_csv_manifest(directory, csv_id)
    text = export_original_csv(directory, csv_id)
    dialect = manifest.dialect
    rows = read_rows(text, dialect)
    out = io.StringIO()
    kwargs = dialect_to_csv_kwargs(CSVDialectFingerprint(
        delimiter=dialect.delimiter,
        quotechar=dialect.quotechar,
        escapechar=dialect.escapechar,
        doublequote=dialect.doublequote,
        skipinitialspace=False,
        lineterminator=lineterminator,
        quoting=csv.QUOTE_MINIMAL,
        has_header=dialect.has_header,
        confidence=dialect.confidence,
        source="canonical-export",
    ))
    writer = csv.writer(out, lineterminator=lineterminator, **kwargs)
    writer.writerows(rows)
    return out.getvalue()


def prove_original_roundtrip(directory: TDSDirectory, csv_id: str, *, overwrite: bool = True) -> CSVRoundTripReport:
    """Store and return a proof that original-byte export is preserved."""
    manifest = load_csv_manifest(directory, csv_id)
    text = export_original_csv(directory, csv_id)
    exported_hash = sha256_hex(text.encode(manifest.encoding))
    report = CSVRoundTripReport(
        csv_id=csv_id,
        export_mode="original-bytes",
        source_sha256=manifest.raw_sha256,
        exported_sha256=exported_hash,
        byte_equivalent=(manifest.raw_sha256 == exported_hash),
        row_count=manifest.row_count,
        column_count=manifest.column_count,
        manifest_key=manifest.artifact_keys["manifest"],
    )
    directory.write_json(manifest.artifact_keys["roundtrip_report"], report.to_dict(), overwrite=overwrite, provenance="DERIVED")
    return report


def load_csv_artifact(directory: TDSDirectory, csv_id: str, artifact: str) -> Any:
    keys = artifact_keys(csv_id)
    if artifact not in keys:
        raise KeyError(f"Unknown CSV artifact {artifact!r}")
    return directory.read_value(keys[artifact])

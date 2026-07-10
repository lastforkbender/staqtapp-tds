"""CSV artifact reload helpers.

The v3.2.3 reload path proves that CSV validation can be performed from a
TDSDirectory snapshot alone. It does not depend on the live manifest/source
objects returned during import, and it does not introduce CSV behavior into the
native storage engine.
"""

from __future__ import annotations

from typing import Any

from staqtapp_tds.tds_filesystem import TDSDirectory

from .artifacts import CSVDialectFingerprint, CSVReloadedArtifacts, CSVRowOffsetMap
from .importer import load_csv_manifest
from .manifest import artifact_keys
from .validator import validate_csv_artifacts


def _require_mapping(value: Any, artifact_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"CSV artifact {artifact_name!r} is not a JSON object")
    return value


def reload_csv_artifacts(directory: TDSDirectory, csv_id: str) -> CSVReloadedArtifacts:
    """Reload a managed CSV artifact set entirely from a TDSDirectory.

    The returned object is built only from durable storage reads and includes
    a full artifact consistency report for release checks and telemetry.
    """
    keys = artifact_keys(csv_id)
    manifest = load_csv_manifest(directory, csv_id)
    raw = directory.read_value(keys["raw"])
    if not isinstance(raw, str):
        raise TypeError(f"CSV raw artifact {keys['raw']!r} is not text")

    dialect_data = _require_mapping(directory.read_value(keys["dialect"]), "dialect")
    row_offset_data = _require_mapping(directory.read_value(keys["row_offsets"]), "row_offsets")
    content_hashes = _require_mapping(directory.read_value(keys["content_hashes"]), "content_hashes")
    import_report = _require_mapping(directory.read_value(keys["import_report"]), "import_report")

    validation_report = validate_csv_artifacts(directory, csv_id)
    return CSVReloadedArtifacts(
        csv_id=csv_id,
        raw=raw,
        manifest=manifest,
        dialect=CSVDialectFingerprint.from_mapping(dialect_data),
        row_offsets=CSVRowOffsetMap.from_mapping(row_offset_data),
        content_hashes=content_hashes,
        import_report=import_report,
        validation_report=validation_report,
    )

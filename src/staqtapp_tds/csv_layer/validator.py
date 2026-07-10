"""CSV artifact validation helpers for the TDS CSV foundation layer.

The validator checks that the small fixed CSV artifact set remains internally
consistent after reload or overwrite. It operates above storage using normal TDS
reads and derived metadata; it does not add CSV semantics to the native C
storage engine or persistence hot path.
"""

from __future__ import annotations

from typing import Any

from staqtapp_tds.tds_filesystem import TDSDirectory

from .artifacts import CSVArtifactValidationReport, CSVDialectFingerprint, CSVRowOffsetMap
from .importer import load_csv_manifest
from .manifest import artifact_keys, row_count_and_column_count, sha256_hex
from .row_offsets import logical_record_offsets_bytes

CSV_VALIDATION_VALID = "csv.validation.valid"
CSV_VALIDATION_INVALID = "csv.validation.invalid"
CSV_VALIDATION_WARNING_PREFIX = "csv.validation.warning"
CSV_VALIDATION_ERROR_PREFIX = "csv.validation.error"

_REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "raw",
    "dialect",
    "row_offsets",
    "content_hashes",
    "manifest",
    "import_report",
)


def _read(directory: TDSDirectory, key: str) -> tuple[bool, Any]:
    try:
        return True, directory.read_value(key)
    except Exception as exc:  # pragma: no cover - exact TDS read error type is intentionally abstracted
        return False, exc


def _is_strictly_increasing(values: tuple[int, ...]) -> bool:
    return all(a < b for a, b in zip(values, values[1:]))


def _stable_code_fragment(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value).lower()).strip("_") or "unknown"


def _result_codes(status: str, errors: list[str], warnings: list[str]) -> tuple[str, ...]:
    codes: list[str] = [CSV_VALIDATION_VALID if status == "valid" else CSV_VALIDATION_INVALID]
    codes.extend(f"{CSV_VALIDATION_ERROR_PREFIX}.{_stable_code_fragment(error)}" for error in errors)
    codes.extend(f"{CSV_VALIDATION_WARNING_PREFIX}.{_stable_code_fragment(warning)}" for warning in warnings)
    return tuple(dict.fromkeys(codes))


def _int_field(mapping: dict[str, Any], field_name: str, errors: list[str], *, artifact_name: str) -> int | None:
    try:
        return int(mapping.get(field_name, -1))
    except Exception:
        errors.append(f"{artifact_name}_{field_name}_not_integer")
        return None


def validate_csv_artifacts(directory: TDSDirectory, csv_id: str) -> CSVArtifactValidationReport:
    """Validate a managed CSV artifact set and return a compact report.

    The check is intentionally artifact-level rather than cell-level. It proves
    that the preserved raw CSV, manifest, dialect, row-offset map, content
    hashes, and import report still agree with one another. That is the right
    v3.2.x foundation before later Semantic IR and stack-run features are added.
    """
    errors: list[str] = []
    warnings: list[str] = []
    checked: list[str] = []
    try:
        keys = artifact_keys(csv_id)
    except Exception as exc:
        errors.append(f"csv_id_unsafe:{type(exc).__name__}:{exc}")
        return CSVArtifactValidationReport(
            csv_id=str(csv_id),
            status="invalid",
            checked_artifacts=tuple(checked),
            error_count=len(errors),
            warning_count=0,
            raw_sha256_verified=False,
            row_offsets_verified=False,
            dialect_verified=False,
            manifest_consistent=False,
            original_preserved=False,
            derived_artifacts_only=False,
            native_storage_hot_path_touched=False,
            per_cell_writes=False,
            errors=tuple(errors),
            result_codes=_result_codes("invalid", errors, warnings),
        )

    try:
        manifest = load_csv_manifest(directory, csv_id)
        checked.append("manifest")
    except Exception as exc:
        errors.append(f"manifest_unreadable:{type(exc).__name__}:{exc}")
        return CSVArtifactValidationReport(
            csv_id=csv_id,
            status="invalid",
            checked_artifacts=tuple(checked),
            error_count=len(errors),
            warning_count=0,
            raw_sha256_verified=False,
            row_offsets_verified=False,
            dialect_verified=False,
            manifest_consistent=False,
            original_preserved=False,
            derived_artifacts_only=False,
            native_storage_hot_path_touched=False,
            per_cell_writes=False,
            errors=tuple(errors),
            result_codes=_result_codes("invalid", errors, warnings),
        )

    if manifest.csv_id != csv_id:
        errors.append("manifest_csv_id_mismatch")
    expected_keys = artifact_keys(manifest.csv_id)
    if manifest.artifact_keys != expected_keys:
        errors.append("manifest_artifact_keys_mismatch")

    raw_ok, raw_value = _read(directory, keys["raw"])
    checked.append("raw")
    if not raw_ok or not isinstance(raw_value, str):
        errors.append("raw_artifact_not_text")
        raw_bytes = b""
        raw_text = ""
    else:
        raw_text = raw_value
        try:
            raw_bytes = raw_value.encode(manifest.encoding)
        except Exception as exc:
            errors.append(f"raw_encoding_error:{type(exc).__name__}")
            raw_bytes = b""

    actual_raw_hash = sha256_hex(raw_bytes)
    raw_hash_ok = bool(raw_bytes or manifest.raw_size == 0) and actual_raw_hash == manifest.raw_sha256
    if not raw_hash_ok:
        errors.append("raw_sha256_mismatch")
    if len(raw_bytes) != manifest.raw_size:
        errors.append("raw_size_mismatch")

    dialect_ok, dialect_value = _read(directory, keys["dialect"])
    checked.append("dialect")
    dialect_verified = False
    dialect = manifest.dialect
    if not dialect_ok or not isinstance(dialect_value, dict):
        errors.append("dialect_artifact_not_json_object")
    else:
        try:
            dialect = CSVDialectFingerprint.from_mapping(dialect_value)
            dialect_verified = dialect.to_dict() == manifest.dialect.to_dict()
            if not dialect_verified:
                errors.append("dialect_artifact_manifest_mismatch")
        except Exception as exc:
            errors.append(f"dialect_parse_error:{type(exc).__name__}")

    try:
        parsed_row_count, parsed_column_count = row_count_and_column_count(raw_text, dialect)
        if parsed_row_count != manifest.row_count:
            errors.append("manifest_row_count_reader_mismatch")
        if parsed_column_count != manifest.column_count:
            errors.append("manifest_column_count_reader_mismatch")
    except Exception as exc:
        errors.append(f"csv_reader_reparse_error:{type(exc).__name__}")

    row_ok, row_value = _read(directory, keys["row_offsets"])
    checked.append("row_offsets")
    row_offsets_verified = False
    if not row_ok or not isinstance(row_value, dict):
        errors.append("row_offsets_artifact_not_json_object")
    else:
        try:
            row_map = CSVRowOffsetMap.from_mapping(row_value)
            if row_map.source_hash != manifest.raw_sha256:
                errors.append("row_offsets_source_hash_mismatch")
            if row_map.source_hash != actual_raw_hash:
                errors.append("row_offsets_source_actual_hash_mismatch")
            if row_map.row_count != manifest.row_count:
                errors.append("row_offsets_row_count_mismatch")
            if row_map.row_count != len(row_map.row_offsets):
                errors.append("row_offsets_count_length_mismatch")
            if raw_bytes and (not row_map.row_offsets or row_map.row_offsets[0] != 0):
                errors.append("row_offsets_missing_zero_start")
            if not _is_strictly_increasing(row_map.row_offsets):
                errors.append("row_offsets_not_strictly_increasing")
            if any(offset < 0 or offset >= max(len(raw_bytes), 1) for offset in row_map.row_offsets):
                errors.append("row_offsets_out_of_bounds")
            recomputed = logical_record_offsets_bytes(raw_bytes, dialect, encoding=manifest.encoding)
            if tuple(row_map.row_offsets) != tuple(recomputed):
                errors.append("row_offsets_recompute_mismatch")
            row_offsets_verified = not any(err.startswith("row_offsets") for err in errors)
        except Exception as exc:
            errors.append(f"row_offsets_parse_error:{type(exc).__name__}")

    hashes_ok, hashes_value = _read(directory, keys["content_hashes"])
    checked.append("content_hashes")
    if not hashes_ok or not isinstance(hashes_value, dict):
        errors.append("content_hashes_artifact_not_json_object")
    else:
        if hashes_value.get("raw_sha256") != manifest.raw_sha256:
            errors.append("content_hashes_raw_sha256_mismatch")
        if hashes_value.get("row_offset_source_sha256") != manifest.raw_sha256:
            errors.append("content_hashes_row_offset_source_mismatch")
        hashes_row_count = _int_field(hashes_value, "row_count", errors, artifact_name="content_hashes")
        if hashes_row_count is not None and hashes_row_count != manifest.row_count:
            errors.append("content_hashes_row_count_mismatch")
        if hashes_value.get("encoding") != manifest.encoding:
            errors.append("content_hashes_encoding_mismatch")

    report_ok, report_value = _read(directory, keys["import_report"])
    checked.append("import_report")
    per_cell_writes = False
    if not report_ok or not isinstance(report_value, dict):
        errors.append("import_report_artifact_not_json_object")
    else:
        if report_value.get("status") != "imported":
            errors.append("import_report_status_mismatch")
        if report_value.get("csv_id") != manifest.csv_id:
            errors.append("import_report_csv_id_mismatch")
        if report_value.get("raw_sha256") != manifest.raw_sha256:
            errors.append("import_report_raw_sha256_mismatch")
        report_row_count = _int_field(report_value, "row_count", errors, artifact_name="import_report")
        if report_row_count is not None and report_row_count != manifest.row_count:
            errors.append("import_report_row_count_mismatch")
        report_column_count = _int_field(report_value, "column_count", errors, artifact_name="import_report")
        if report_column_count is not None and report_column_count != manifest.column_count:
            errors.append("import_report_column_count_mismatch")
        artifact_write_count = _int_field(report_value, "artifact_write_count", errors, artifact_name="import_report")
        if artifact_write_count is not None and artifact_write_count != 6:
            errors.append("import_report_artifact_write_count_mismatch")
        raw_artifact_count = _int_field(report_value, "raw_artifact_count", errors, artifact_name="import_report")
        if raw_artifact_count is not None and raw_artifact_count != 1:
            errors.append("import_report_raw_artifact_count_mismatch")
        derived_artifact_count = _int_field(report_value, "derived_artifact_count", errors, artifact_name="import_report")
        if derived_artifact_count is not None and derived_artifact_count != 5:
            errors.append("import_report_derived_artifact_count_mismatch")
        per_cell_writes = bool(report_value.get("per_cell_writes", False))
        if per_cell_writes:
            errors.append("import_report_declares_per_cell_writes")

    if manifest.warnings:
        warnings.extend(str(w) for w in manifest.warnings)

    manifest_consistent = not any(
        err.startswith("manifest_") or err.endswith("_manifest_mismatch") for err in errors
    )
    original_preserved = bool(manifest.original_preserved) and raw_hash_ok
    derived_only = bool(manifest.derived_artifacts_only) and not bool(manifest.writes_original)
    native_touched = bool(manifest.native_storage_hot_path_touched)
    if native_touched:
        errors.append("manifest_declares_native_storage_hot_path_touched")
    if not derived_only:
        errors.append("manifest_declares_non_derived_csv_writes")

    status = "valid" if not errors else "invalid"
    return CSVArtifactValidationReport(
        csv_id=csv_id,
        status=status,
        checked_artifacts=tuple(dict.fromkeys(checked)),
        error_count=len(errors),
        warning_count=len(warnings),
        raw_sha256_verified=raw_hash_ok,
        row_offsets_verified=row_offsets_verified,
        dialect_verified=dialect_verified,
        manifest_consistent=manifest_consistent,
        original_preserved=original_preserved,
        derived_artifacts_only=derived_only,
        native_storage_hot_path_touched=native_touched,
        per_cell_writes=per_cell_writes,
        errors=tuple(errors),
        warnings=tuple(warnings),
        result_codes=_result_codes(status, errors, warnings),
    )

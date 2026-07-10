"""CSV artifact transaction and recovery envelope for .tds directories.

This module stages the fixed CSV core artifact set under transaction-specific
keys, validates that staged evidence, then commits it into the normal CSV
artifact namespace.  It is intentionally above storage: no native C storage
engine hooks, no per-row writes, no per-cell writes, and no CSV semantics in the
TDS hot path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import uuid
from typing import Any, Mapping

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import TDSDirectory

from .artifacts import CSVImportManifest, CSVRowOffsetMap
from .dialect import CSVDialectFingerprint, detect_csv_dialect
from .manifest import artifact_keys, build_manifest, sha256_hex, validate_csv_id
from .validator import validate_csv_artifacts

CSV_ARTIFACT_TRANSACTION_VERSION = "1.0"
CSV_CORE_TRANSACTION_ARTIFACTS = (
    "raw",
    "dialect",
    "row_offsets",
    "content_hashes",
    "manifest",
    "import_report",
)
_TX_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def validate_csv_transaction_id(transaction_id: str) -> str:
    """Return a bounded transaction ID or raise ``ValueError``.

    Transaction IDs become part of staged .tds artifact names, so the accepted
    shape mirrors CSV IDs but with a smaller maximum length.
    """
    if not isinstance(transaction_id, str):
        raise ValueError("transaction_id must be a string")
    if not transaction_id:
        raise ValueError("transaction_id must not be empty")
    if not _TX_ID_RE.fullmatch(transaction_id):
        raise ValueError("transaction_id contains unsafe characters or unsafe leading character")
    return transaction_id


def new_csv_transaction_id() -> str:
    """Return a compact artifact-safe CSV transaction identifier."""
    return uuid.uuid4().hex[:16]


def csv_artifact_transaction_keys(csv_id: str, transaction_id: str) -> dict[str, str]:
    """Return durable keys for staged CSV transaction artifacts."""
    csv_id = validate_csv_id(csv_id)
    transaction_id = validate_csv_transaction_id(transaction_id)
    prefix = f"csv__{csv_id}__tx_{transaction_id}"
    return {
        "raw": f"{prefix}__raw.csv",
        "dialect": f"{prefix}__dialect.json",
        "row_offsets": f"{prefix}__row_offsets.json",
        "content_hashes": f"{prefix}__content_hashes.json",
        "manifest": f"{prefix}__manifest.json",
        "import_report": f"{prefix}__import_report.json",
        "transaction_report": f"{prefix}__transaction_report.json",
        "latest_transaction_report": f"csv__{csv_id}__transaction_report.json",
    }


@dataclass(frozen=True, slots=True)
class CSVArtifactTransactionReport:
    """Compact transaction/recovery report for staged CSV artifact writes."""

    csv_id: str
    transaction_id: str
    status: str
    transaction_version: str
    final_artifact_keys: Mapping[str, str]
    staged_artifact_keys: Mapping[str, str]
    report_key: str
    staged_count: int = 0
    final_count: int = 0
    committed_count: int = 0
    cleaned_staged_count: int = 0
    missing_staged_artifacts: tuple[str, ...] = field(default_factory=tuple)
    missing_final_artifacts: tuple[str, ...] = field(default_factory=tuple)
    existing_final_artifacts: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    overwrite: bool = False
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {
            "staged",
            "valid",
            "committed",
            "complete",
            "empty",
            "recovered_complete",
            "recoverable_staged",
        } and not self.errors

    @property
    def partial(self) -> bool:
        return self.status in {"partial", "partial_staged", "partial_final", "partial_unrecoverable"}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["final_artifact_keys"] = dict(self.final_artifact_keys)
        data["staged_artifact_keys"] = dict(self.staged_artifact_keys)
        data["missing_staged_artifacts"] = list(self.missing_staged_artifacts)
        data["missing_final_artifacts"] = list(self.missing_final_artifacts)
        data["existing_final_artifacts"] = list(self.existing_final_artifacts)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["partial"] = self.partial
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVArtifactTransactionReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            transaction_id=str(data.get("transaction_id", "")),
            status=str(data.get("status", "invalid")),
            transaction_version=str(data.get("transaction_version", CSV_ARTIFACT_TRANSACTION_VERSION)),
            final_artifact_keys={str(k): str(v) for k, v in (data.get("final_artifact_keys", {}) or {}).items()},
            staged_artifact_keys={str(k): str(v) for k, v in (data.get("staged_artifact_keys", {}) or {}).items()},
            report_key=str(data.get("report_key", "")),
            staged_count=int(data.get("staged_count", 0)),
            final_count=int(data.get("final_count", 0)),
            committed_count=int(data.get("committed_count", 0)),
            cleaned_staged_count=int(data.get("cleaned_staged_count", 0)),
            missing_staged_artifacts=tuple(str(v) for v in data.get("missing_staged_artifacts", []) or []),
            missing_final_artifacts=tuple(str(v) for v in data.get("missing_final_artifacts", []) or []),
            existing_final_artifacts=tuple(str(v) for v in data.get("existing_final_artifacts", []) or []),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            overwrite=bool(data.get("overwrite", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )


def _invalid_report(csv_id: str, transaction_id: str, error: str) -> CSVArtifactTransactionReport:
    return CSVArtifactTransactionReport(
        csv_id=str(csv_id),
        transaction_id=str(transaction_id),
        status="invalid",
        transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
        final_artifact_keys={},
        staged_artifact_keys={},
        report_key="",
        errors=(error,),
    )


def _exists(directory: TDSDirectory, key: str) -> bool:
    try:
        directory.read_value(key)
        return True
    except Exception:
        return False


def _read(directory: TDSDirectory, key: str) -> tuple[bool, Any]:
    try:
        return True, directory.read_value(key)
    except Exception as exc:
        return False, exc


def _require_write(result: TDSResult, artifact: str) -> None:
    if not result.ok:
        raise RuntimeError(f"CSV transaction artifact write failed for {artifact}: {result.code} {result.message}")


def _write_artifact(directory: TDSDirectory, key: str, value: Any, *, artifact_name: str, overwrite: bool) -> None:
    if artifact_name == "raw":
        if not isinstance(value, str):
            raise TypeError("staged raw CSV artifact must be text")
        _require_write(directory.write_text(key, value, overwrite=overwrite, provenance="REAL"), key)
    else:
        _require_write(directory.write_json(key, value, overwrite=overwrite, provenance="DERIVED"), key)


def _delete_present(directory: TDSDirectory, keys: Mapping[str, str]) -> int:
    count = 0
    for name in CSV_CORE_TRANSACTION_ARTIFACTS + ("transaction_report",):
        key = keys.get(name)
        if key and _exists(directory, key):
            directory.delete_entry(key)
            count += 1
    return count


def _stage_payloads(manifest: CSVImportManifest, report: Any, derived: Mapping[str, Any], text: str) -> dict[str, Any]:
    return {
        "raw": text,
        "dialect": manifest.dialect.to_dict(),
        "row_offsets": derived["row_offsets"],
        "content_hashes": derived["content_hashes"],
        "manifest": manifest.to_dict(),
        "import_report": report.to_dict(),
    }


def begin_csv_artifact_transaction(
    directory: TDSDirectory,
    raw: bytes,
    *,
    source_name: str = "csv_source.csv",
    encoding: str = "utf-8",
    csv_id: str | None = None,
    transaction_id: str | None = None,
    overwrite: bool = False,
    cleanup_existing_stage: bool = True,
) -> CSVArtifactTransactionReport:
    """Stage a fixed CSV core artifact set under transaction-specific keys.

    This does not expose the CSV under its final artifact names.  A caller must
    explicitly call :func:`commit_csv_artifact_transaction` after staged parity
    succeeds.  The ordinary ``import_csv_bytes`` path remains unchanged.
    """
    transaction_id = transaction_id or new_csv_transaction_id()
    try:
        validate_csv_transaction_id(transaction_id)
        text = raw.decode(encoding)
        dialect = detect_csv_dialect(text)
        manifest, import_report, derived = build_manifest(
            source_name=source_name,
            text=text,
            raw=raw,
            encoding=encoding,
            dialect=dialect,
            csv_id=csv_id,
        )
        final_keys = {name: key for name, key in artifact_keys(manifest.csv_id).items() if name in CSV_CORE_TRANSACTION_ARTIFACTS}
        tx_keys = csv_artifact_transaction_keys(manifest.csv_id, transaction_id)
        staged_keys = {name: tx_keys[name] for name in CSV_CORE_TRANSACTION_ARTIFACTS}
    except Exception as exc:
        return _invalid_report(str(csv_id or ""), str(transaction_id), f"transaction_begin_error:{type(exc).__name__}:{exc}")

    existing_final = tuple(name for name, key in final_keys.items() if _exists(directory, key))
    if existing_final and not overwrite:
        return CSVArtifactTransactionReport(
            csv_id=manifest.csv_id,
            transaction_id=transaction_id,
            status="invalid",
            transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
            final_artifact_keys=final_keys,
            staged_artifact_keys=staged_keys,
            report_key=tx_keys["transaction_report"],
            existing_final_artifacts=existing_final,
            errors=("final_artifacts_exist",),
            overwrite=overwrite,
        )

    if cleanup_existing_stage:
        _delete_present(directory, tx_keys)

    payloads = _stage_payloads(manifest, import_report, derived, text)
    written: list[str] = []
    try:
        for name in CSV_CORE_TRANSACTION_ARTIFACTS:
            _write_artifact(directory, staged_keys[name], payloads[name], artifact_name=name, overwrite=overwrite or cleanup_existing_stage)
            written.append(name)
        staged_report = CSVArtifactTransactionReport(
            csv_id=manifest.csv_id,
            transaction_id=transaction_id,
            status="staged",
            transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
            final_artifact_keys=final_keys,
            staged_artifact_keys=staged_keys,
            report_key=tx_keys["transaction_report"],
            staged_count=len(written),
            overwrite=overwrite,
        )
        _write_artifact(directory, tx_keys["transaction_report"], staged_report.to_dict(), artifact_name="transaction_report", overwrite=True)
        return staged_report
    except Exception as exc:
        missing = tuple(name for name in CSV_CORE_TRANSACTION_ARTIFACTS if name not in written)
        return CSVArtifactTransactionReport(
            csv_id=manifest.csv_id,
            transaction_id=transaction_id,
            status="partial_staged",
            transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
            final_artifact_keys=final_keys,
            staged_artifact_keys=staged_keys,
            report_key=tx_keys["transaction_report"],
            staged_count=len(written),
            missing_staged_artifacts=missing,
            errors=(f"stage_write_error:{type(exc).__name__}:{exc}",),
            overwrite=overwrite,
        )


def validate_csv_artifact_transaction(
    directory: TDSDirectory,
    csv_id: str,
    transaction_id: str,
) -> CSVArtifactTransactionReport:
    """Validate staged CSV artifacts before final commit."""
    try:
        final_keys = {name: key for name, key in artifact_keys(csv_id).items() if name in CSV_CORE_TRANSACTION_ARTIFACTS}
        tx_keys = csv_artifact_transaction_keys(csv_id, transaction_id)
        staged_keys = {name: tx_keys[name] for name in CSV_CORE_TRANSACTION_ARTIFACTS}
    except Exception as exc:
        return _invalid_report(str(csv_id), str(transaction_id), f"transaction_key_error:{type(exc).__name__}:{exc}")

    missing = tuple(name for name, key in staged_keys.items() if not _exists(directory, key))
    if missing:
        return CSVArtifactTransactionReport(
            csv_id=csv_id,
            transaction_id=transaction_id,
            status="partial_staged",
            transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
            final_artifact_keys=final_keys,
            staged_artifact_keys=staged_keys,
            report_key=tx_keys["transaction_report"],
            staged_count=len(CSV_CORE_TRANSACTION_ARTIFACTS) - len(missing),
            missing_staged_artifacts=missing,
            errors=("staged_artifacts_missing",),
        )

    errors: list[str] = []
    raw_ok, raw_value = _read(directory, staged_keys["raw"])
    manifest_ok, manifest_value = _read(directory, staged_keys["manifest"])
    dialect_ok, dialect_value = _read(directory, staged_keys["dialect"])
    rows_ok, rows_value = _read(directory, staged_keys["row_offsets"])
    hashes_ok, hashes_value = _read(directory, staged_keys["content_hashes"])
    import_report_ok, import_report_value = _read(directory, staged_keys["import_report"])

    if not raw_ok or not isinstance(raw_value, str):
        errors.append("staged_raw_not_text")
    if not manifest_ok or not isinstance(manifest_value, dict):
        errors.append("staged_manifest_not_json_object")
    if not dialect_ok or not isinstance(dialect_value, dict):
        errors.append("staged_dialect_not_json_object")
    if not rows_ok or not isinstance(rows_value, dict):
        errors.append("staged_row_offsets_not_json_object")
    if not hashes_ok or not isinstance(hashes_value, dict):
        errors.append("staged_content_hashes_not_json_object")
    if not import_report_ok or not isinstance(import_report_value, dict):
        errors.append("staged_import_report_not_json_object")

    if not errors:
        try:
            manifest = CSVImportManifest.from_mapping(manifest_value)
            if manifest.csv_id != csv_id:
                errors.append("staged_manifest_csv_id_mismatch")
            if {name: manifest.artifact_keys.get(name) for name in CSV_CORE_TRANSACTION_ARTIFACTS} != final_keys:
                errors.append("staged_manifest_final_keyset_mismatch")
            raw_bytes = raw_value.encode(manifest.encoding)
            actual_hash = sha256_hex(raw_bytes)
            if actual_hash != manifest.raw_sha256:
                errors.append("staged_raw_sha256_mismatch")
            if len(raw_bytes) != manifest.raw_size:
                errors.append("staged_raw_size_mismatch")
            dialect = CSVDialectFingerprint.from_mapping(dialect_value)
            if dialect.to_dict() != manifest.dialect.to_dict():
                errors.append("staged_dialect_manifest_mismatch")
            row_map = CSVRowOffsetMap.from_mapping(rows_value)
            if row_map.source_hash != manifest.raw_sha256:
                errors.append("staged_row_offsets_source_hash_mismatch")
            if row_map.row_count != manifest.row_count:
                errors.append("staged_row_offsets_row_count_mismatch")
            if hashes_value.get("raw_sha256") != manifest.raw_sha256:
                errors.append("staged_content_hashes_raw_sha256_mismatch")
            if hashes_value.get("row_offset_source_sha256") != manifest.raw_sha256:
                errors.append("staged_content_hashes_row_source_mismatch")
            if str(hashes_value.get("encoding")) != manifest.encoding:
                errors.append("staged_content_hashes_encoding_mismatch")
            if import_report_value.get("status") != "imported":
                errors.append("staged_import_report_status_mismatch")
            if import_report_value.get("csv_id") != csv_id:
                errors.append("staged_import_report_csv_id_mismatch")
            if import_report_value.get("raw_sha256") != manifest.raw_sha256:
                errors.append("staged_import_report_raw_sha256_mismatch")
            if bool(import_report_value.get("per_cell_writes", False)):
                errors.append("staged_import_report_declares_per_cell_writes")
        except Exception as exc:
            errors.append(f"staged_parse_error:{type(exc).__name__}:{exc}")

    return CSVArtifactTransactionReport(
        csv_id=csv_id,
        transaction_id=transaction_id,
        status="valid" if not errors else "invalid",
        transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
        final_artifact_keys=final_keys,
        staged_artifact_keys=staged_keys,
        report_key=tx_keys["transaction_report"],
        staged_count=len(CSV_CORE_TRANSACTION_ARTIFACTS),
        errors=tuple(dict.fromkeys(errors)),
    )


def commit_csv_artifact_transaction(
    directory: TDSDirectory,
    csv_id: str,
    transaction_id: str,
    *,
    overwrite: bool = False,
    cleanup_staged: bool = True,
) -> CSVArtifactTransactionReport:
    """Commit a valid staged CSV artifact set into the final CSV namespace."""
    validation = validate_csv_artifact_transaction(directory, csv_id, transaction_id)
    if not validation.ok:
        return CSVArtifactTransactionReport(
            csv_id=validation.csv_id,
            transaction_id=validation.transaction_id,
            status="invalid",
            transaction_version=validation.transaction_version,
            final_artifact_keys=validation.final_artifact_keys,
            staged_artifact_keys=validation.staged_artifact_keys,
            report_key=validation.report_key,
            staged_count=validation.staged_count,
            final_count=validation.final_count,
            missing_staged_artifacts=validation.missing_staged_artifacts,
            missing_final_artifacts=validation.missing_final_artifacts,
            errors=tuple(validation.errors or ("transaction_validation_failed",)),
            warnings=validation.warnings,
            overwrite=overwrite,
        )

    final_keys = dict(validation.final_artifact_keys)
    staged_keys = dict(validation.staged_artifact_keys)
    tx_keys = csv_artifact_transaction_keys(csv_id, transaction_id)
    existing_final = tuple(name for name, key in final_keys.items() if _exists(directory, key))
    if existing_final and not overwrite:
        return CSVArtifactTransactionReport(
            csv_id=csv_id,
            transaction_id=transaction_id,
            status="invalid",
            transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
            final_artifact_keys=final_keys,
            staged_artifact_keys=staged_keys,
            report_key=tx_keys["transaction_report"],
            staged_count=validation.staged_count,
            existing_final_artifacts=existing_final,
            errors=("final_artifacts_exist",),
            overwrite=overwrite,
        )

    committed: list[str] = []
    errors: list[str] = []
    for name in CSV_CORE_TRANSACTION_ARTIFACTS:
        ok, value = _read(directory, staged_keys[name])
        if not ok:
            errors.append(f"staged_{name}_lost_before_commit")
            break
        try:
            _write_artifact(directory, final_keys[name], value, artifact_name=name, overwrite=overwrite)
            committed.append(name)
        except Exception as exc:
            errors.append(f"commit_{name}_write_error:{type(exc).__name__}:{exc}")
            break

    final_validation = validate_csv_artifacts(directory, csv_id) if len(committed) == len(CSV_CORE_TRANSACTION_ARTIFACTS) else None
    if final_validation is not None and not final_validation.ok:
        errors.extend(f"final_validation:{error}" for error in final_validation.errors)

    cleaned = 0
    status = "committed" if not errors and len(committed) == len(CSV_CORE_TRANSACTION_ARTIFACTS) else "partial_final"
    if status == "committed" and cleanup_staged:
        cleaned = _delete_present(directory, tx_keys)

    report = CSVArtifactTransactionReport(
        csv_id=csv_id,
        transaction_id=transaction_id,
        status=status,
        transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
        final_artifact_keys=final_keys,
        staged_artifact_keys=staged_keys,
        report_key=tx_keys["latest_transaction_report"],
        staged_count=validation.staged_count,
        final_count=len([name for name, key in final_keys.items() if _exists(directory, key)]),
        committed_count=len(committed),
        cleaned_staged_count=cleaned,
        missing_final_artifacts=tuple(name for name in CSV_CORE_TRANSACTION_ARTIFACTS if name not in committed),
        errors=tuple(dict.fromkeys(errors)),
        overwrite=overwrite,
    )
    _write_artifact(directory, tx_keys["latest_transaction_report"], report.to_dict(), artifact_name="transaction_report", overwrite=True)
    return report


def detect_partial_csv_artifacts(
    directory: TDSDirectory,
    csv_id: str,
) -> CSVArtifactTransactionReport:
    """Detect whether final core CSV artifacts are empty, complete, or partial."""
    try:
        final_keys = {name: key for name, key in artifact_keys(csv_id).items() if name in CSV_CORE_TRANSACTION_ARTIFACTS}
    except Exception as exc:
        return _invalid_report(str(csv_id), "", f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    present = tuple(name for name, key in final_keys.items() if _exists(directory, key))
    missing = tuple(name for name in CSV_CORE_TRANSACTION_ARTIFACTS if name not in present)
    if not present:
        status = "empty"
        errors: tuple[str, ...] = tuple()
    elif not missing:
        validation = validate_csv_artifacts(directory, csv_id)
        status = "complete" if validation.ok else "partial_final"
        errors = tuple(f"final_validation:{error}" for error in validation.errors)
    else:
        status = "partial"
        errors = ("final_artifacts_partial",)

    return CSVArtifactTransactionReport(
        csv_id=csv_id,
        transaction_id="",
        status=status,
        transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
        final_artifact_keys=final_keys,
        staged_artifact_keys={},
        report_key=f"csv__{csv_id}__transaction_report.json" if status != "invalid" else "",
        final_count=len(present),
        missing_final_artifacts=missing,
        errors=errors,
    )


def recover_csv_artifact_transaction(
    directory: TDSDirectory,
    csv_id: str,
    transaction_id: str,
    *,
    commit_staged: bool = False,
    overwrite: bool = False,
    cleanup_staged: bool = True,
) -> CSVArtifactTransactionReport:
    """Inspect or recover a staged CSV artifact transaction.

    By default this is read-only and reports whether recovery is possible.  When
    ``commit_staged=True``, a valid staged transaction can repair an empty or
    partial final artifact set by committing the staged set.
    """
    final_state = detect_partial_csv_artifacts(directory, csv_id)
    if final_state.status == "complete":
        cleaned = 0
        if cleanup_staged:
            try:
                cleaned = _delete_present(directory, csv_artifact_transaction_keys(csv_id, transaction_id))
            except Exception:
                cleaned = 0
        return CSVArtifactTransactionReport(
            csv_id=csv_id,
            transaction_id=transaction_id,
            status="recovered_complete",
            transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
            final_artifact_keys=final_state.final_artifact_keys,
            staged_artifact_keys=csv_artifact_transaction_keys(csv_id, transaction_id),
            report_key=final_state.report_key,
            final_count=final_state.final_count,
            cleaned_staged_count=cleaned,
        )

    staged = validate_csv_artifact_transaction(directory, csv_id, transaction_id)
    if not staged.ok:
        return CSVArtifactTransactionReport(
            csv_id=csv_id,
            transaction_id=transaction_id,
            status="partial_unrecoverable",
            transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
            final_artifact_keys=final_state.final_artifact_keys,
            staged_artifact_keys=staged.staged_artifact_keys,
            report_key=staged.report_key,
            staged_count=staged.staged_count,
            final_count=final_state.final_count,
            missing_staged_artifacts=staged.missing_staged_artifacts,
            missing_final_artifacts=final_state.missing_final_artifacts,
            errors=tuple(dict.fromkeys(final_state.errors + staged.errors)),
        )

    if commit_staged:
        return commit_csv_artifact_transaction(
            directory,
            csv_id,
            transaction_id,
            overwrite=overwrite or bool(final_state.final_count),
            cleanup_staged=cleanup_staged,
        )

    return CSVArtifactTransactionReport(
        csv_id=csv_id,
        transaction_id=transaction_id,
        status="recoverable_staged",
        transaction_version=CSV_ARTIFACT_TRANSACTION_VERSION,
        final_artifact_keys=final_state.final_artifact_keys,
        staged_artifact_keys=staged.staged_artifact_keys,
        report_key=staged.report_key,
        staged_count=staged.staged_count,
        final_count=final_state.final_count,
        missing_final_artifacts=final_state.missing_final_artifacts,
        warnings=("staged_transaction_valid_but_not_committed",),
    )


def load_csv_artifact_transaction_report(
    directory: TDSDirectory,
    csv_id: str,
    transaction_id: str | None = None,
) -> CSVArtifactTransactionReport:
    """Load a staged or latest committed CSV transaction report."""
    if transaction_id is None:
        key = f"csv__{validate_csv_id(csv_id)}__transaction_report.json"
    else:
        key = csv_artifact_transaction_keys(csv_id, transaction_id)["transaction_report"]
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV transaction report artifact {key!r} is not a JSON object")
    return CSVArtifactTransactionReport.from_mapping(value)

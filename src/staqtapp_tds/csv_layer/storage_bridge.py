"""CSV storage bridge preflight for future native .tds integration.

This module does not write CSV data into the native storage engine.  It builds
and validates the exact artifact plan that a later storage-backed CSV adapter
must preserve: core keys, optional scan-evidence keys, payload format lanes,
provenance expectations, content hashes, and fail-closed readiness checks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any, Mapping

from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.tds_json import dumps_canonical

from .manifest import artifact_keys, sha256_hex, validate_csv_id
from .scan_artifacts import csv_scan_artifact_keys, validate_materialized_csv_scan_artifacts
from .security import validate_csv_artifact_key, validate_csv_artifact_security
from .validator import validate_csv_artifacts

CSV_STORAGE_BRIDGE_PREFLIGHT_VERSION = "1.0"

_CSV_CORE_BRIDGE_ARTIFACTS: tuple[str, ...] = (
    "raw",
    "dialect",
    "row_offsets",
    "content_hashes",
    "manifest",
    "import_report",
)
_CSV_JSON_CORE_ARTIFACTS = frozenset(_CSV_CORE_BRIDGE_ARTIFACTS) - {"raw"}
_CSV_SCAN_BRIDGE_ARTIFACTS: tuple[str, ...] = (
    "scan_profile",
    "row_anchor_profile",
    "scan_materialization_report",
)


@dataclass(frozen=True, slots=True)
class CSVStorageBridgeEntry:
    """One artifact slot in the CSV storage-bridge preflight plan."""

    artifact_name: str
    artifact_key: str
    required: bool
    expected_payload_kind: str
    expected_provenance: str
    present: bool = False
    payload_kind: str = ""
    payload_type: str = ""
    raw_size: int = 0
    stored_size: int = 0
    content_hash: str = ""
    payload_sha256: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.present and not self.error and (not self.expected_payload_kind or self.payload_kind == self.expected_payload_kind)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVStorageBridgeEntry":
        return cls(
            artifact_name=str(data.get("artifact_name", "")),
            artifact_key=str(data.get("artifact_key", "")),
            required=bool(data.get("required", False)),
            expected_payload_kind=str(data.get("expected_payload_kind", "")),
            expected_provenance=str(data.get("expected_provenance", "")),
            present=bool(data.get("present", False)),
            payload_kind=str(data.get("payload_kind", "")),
            payload_type=str(data.get("payload_type", "")),
            raw_size=int(data.get("raw_size", 0)),
            stored_size=int(data.get("stored_size", 0)),
            content_hash=str(data.get("content_hash", "")),
            payload_sha256=str(data.get("payload_sha256", "")),
            error=str(data.get("error", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVStorageBridgePreflightReport:
    """Read-only storage-readiness report for a managed CSV artifact set."""

    csv_id: str
    status: str
    bridge_version: str
    entries: tuple[CSVStorageBridgeEntry, ...]
    required_count: int
    present_required_count: int
    optional_count: int
    present_optional_count: int
    artifact_validation_status: str
    security_status: str
    scan_validation_status: str = "not_checked"
    missing_required_artifacts: tuple[str, ...] = field(default_factory=tuple)
    missing_optional_artifacts: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ready" and not self.errors

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entries"] = [entry.to_dict() for entry in self.entries]
        data["missing_required_artifacts"] = list(self.missing_required_artifacts)
        data["missing_optional_artifacts"] = list(self.missing_optional_artifacts)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["entry_count"] = self.entry_count
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVStorageBridgePreflightReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            bridge_version=str(data.get("bridge_version", CSV_STORAGE_BRIDGE_PREFLIGHT_VERSION)),
            entries=tuple(CSVStorageBridgeEntry.from_mapping(v) for v in data.get("entries", []) or []),
            required_count=int(data.get("required_count", 0)),
            present_required_count=int(data.get("present_required_count", 0)),
            optional_count=int(data.get("optional_count", 0)),
            present_optional_count=int(data.get("present_optional_count", 0)),
            artifact_validation_status=str(data.get("artifact_validation_status", "not_checked")),
            security_status=str(data.get("security_status", "not_checked")),
            scan_validation_status=str(data.get("scan_validation_status", "not_checked")),
            missing_required_artifacts=tuple(str(v) for v in data.get("missing_required_artifacts", []) or []),
            missing_optional_artifacts=tuple(str(v) for v in data.get("missing_optional_artifacts", []) or []),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )


def _planned_entry(name: str, key: str, *, required: bool) -> CSVStorageBridgeEntry:
    expected_payload_kind = "TEXT_UTF8" if name == "raw" else "JSON_UTF8"
    expected_provenance = "REAL" if name == "raw" else "DERIVED"
    return CSVStorageBridgeEntry(
        artifact_name=name,
        artifact_key=key,
        required=required,
        expected_payload_kind=expected_payload_kind,
        expected_provenance=expected_provenance,
    )


def csv_storage_bridge_plan(
    csv_id: str,
    *,
    include_scan_artifacts: bool = False,
    include_transaction_report: bool = False,
) -> tuple[CSVStorageBridgeEntry, ...]:
    """Return the read-only artifact plan for future CSV storage bridging.

    The plan is intentionally compact: six required core artifacts, plus
    optional advanced evidence artifacts when requested.  It does not inspect or
    mutate a directory and it never touches the native storage engine.
    """
    safe_id = validate_csv_id(csv_id)
    core = artifact_keys(safe_id)
    entries: list[CSVStorageBridgeEntry] = [
        _planned_entry(name, core[name], required=True) for name in _CSV_CORE_BRIDGE_ARTIFACTS
    ]
    if include_scan_artifacts:
        scan = csv_scan_artifact_keys(safe_id)
        entries.extend(_planned_entry(name, scan[name], required=False) for name in _CSV_SCAN_BRIDGE_ARTIFACTS)
    if include_transaction_report:
        entries.append(_planned_entry("transaction_report", f"csv__{safe_id}__transaction_report.json", required=False))
    return tuple(entries)


def _payload_bytes(value: Any, expected_kind: str, encoding: str) -> bytes:
    if expected_kind == "TEXT_UTF8":
        if not isinstance(value, str):
            raise TypeError("expected text artifact")
        return value.encode(encoding)
    if expected_kind == "JSON_UTF8":
        if not isinstance(value, (dict, list)):
            raise TypeError("expected JSON-compatible artifact")
        return dumps_canonical(value)[0]
    raise TypeError(f"unsupported expected payload kind: {expected_kind}")


def _inspect_entry(directory: TDSDirectory, planned: CSVStorageBridgeEntry, *, encoding: str) -> CSVStorageBridgeEntry:
    try:
        validate_csv_artifact_key(planned.artifact_key, planned.artifact_key.split("__", 2)[1])
        value = directory.read_value(planned.artifact_key)
        metadata = directory.entry_metadata(planned.artifact_key)
        raw = _payload_bytes(value, planned.expected_payload_kind, encoding)
        payload_kind = str(metadata.get("payload_kind", ""))
        error = "" if payload_kind == planned.expected_payload_kind else "payload_kind_mismatch"
        if planned.expected_payload_kind == "JSON_UTF8" and not isinstance(value, (dict, list)):
            error = "json_artifact_not_mapping_or_list"
        if planned.expected_payload_kind == "TEXT_UTF8" and not isinstance(value, str):
            error = "text_artifact_not_string"
        return CSVStorageBridgeEntry(
            artifact_name=planned.artifact_name,
            artifact_key=planned.artifact_key,
            required=planned.required,
            expected_payload_kind=planned.expected_payload_kind,
            expected_provenance=planned.expected_provenance,
            present=True,
            payload_kind=payload_kind,
            payload_type=type(value).__name__,
            raw_size=int(metadata.get("raw_size", len(raw))),
            stored_size=int(metadata.get("stored_size", 0)),
            content_hash=str(metadata.get("content_hash", "")),
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            error=error,
        )
    except Exception as exc:
        return CSVStorageBridgeEntry(
            artifact_name=planned.artifact_name,
            artifact_key=planned.artifact_key,
            required=planned.required,
            expected_payload_kind=planned.expected_payload_kind,
            expected_provenance=planned.expected_provenance,
            present=False,
            error=f"missing_or_unreadable:{type(exc).__name__}:{exc}",
        )


def validate_csv_storage_bridge_preflight(
    directory: TDSDirectory,
    csv_id: str,
    *,
    include_scan_artifacts: bool = False,
    require_scan_artifacts: bool = False,
    include_transaction_report: bool = False,
    require_transaction_report: bool = False,
    chunk_size: int | None = None,
) -> CSVStorageBridgePreflightReport:
    """Validate that CSV artifacts are ready for a later storage bridge.

    This is a read-only preflight. It verifies durable artifact validation,
    security envelope checks, expected payload lanes, stable payload hashes, and
    optional scan evidence when requested. It does not create entries, run CSV
    semantics, or call into the native storage hot path.
    """
    include_scan_artifacts = bool(include_scan_artifacts or require_scan_artifacts)
    include_transaction_report = bool(include_transaction_report or require_transaction_report)
    try:
        safe_id = validate_csv_id(csv_id)
        plan = list(csv_storage_bridge_plan(
            safe_id,
            include_scan_artifacts=include_scan_artifacts,
            include_transaction_report=include_transaction_report,
        ))
    except Exception as exc:
        return CSVStorageBridgePreflightReport(
            csv_id=str(csv_id),
            status="invalid",
            bridge_version=CSV_STORAGE_BRIDGE_PREFLIGHT_VERSION,
            entries=tuple(),
            required_count=0,
            present_required_count=0,
            optional_count=0,
            present_optional_count=0,
            artifact_validation_status="not_checked",
            security_status="invalid",
            errors=(f"csv_id_unsafe:{type(exc).__name__}:{exc}",),
        )

    errors: list[str] = []
    warnings: list[str] = []
    artifact_validation = validate_csv_artifacts(directory, safe_id)
    security = validate_csv_artifact_security(directory, safe_id, include_scan_artifacts=include_scan_artifacts and require_scan_artifacts)
    artifact_validation_status = artifact_validation.status
    security_status = security.status
    if not artifact_validation.ok:
        errors.extend(f"artifact_validation:{error}" for error in artifact_validation.errors)
    if not security.ok:
        errors.extend(f"security:{error}" for error in security.errors)

    encoding = "utf-8"
    try:
        manifest_value = directory.read_value(artifact_keys(safe_id)["manifest"])
        if isinstance(manifest_value, dict):
            encoding = str(manifest_value.get("encoding", "utf-8"))
    except Exception:
        pass

    if require_scan_artifacts:
        scan_report = None
        try:
            scan_report = validate_materialized_csv_scan_artifacts(
                directory,
                safe_id,
                require_row_anchors=True,
                chunk_size=chunk_size,
            )
            scan_validation_status = scan_report.status
            if not scan_report.ok:
                errors.extend(f"scan_validation:{error}" for error in scan_report.errors)
        except Exception as exc:
            scan_validation_status = "invalid"
            errors.append(f"scan_validation_unreadable:{type(exc).__name__}:{exc}")
    else:
        scan_validation_status = "not_required"

    entries = tuple(_inspect_entry(directory, planned, encoding=encoding) for planned in plan)
    missing_required = tuple(entry.artifact_name for entry in entries if entry.required and not entry.present)
    missing_optional = tuple(entry.artifact_name for entry in entries if not entry.required and not entry.present)

    for entry in entries:
        if entry.required and entry.error:
            errors.append(f"bridge_entry:{entry.artifact_name}:{entry.error}")
        elif not entry.required and entry.error:
            if (entry.artifact_name in _CSV_SCAN_BRIDGE_ARTIFACTS and require_scan_artifacts) or (
                entry.artifact_name == "transaction_report" and require_transaction_report
            ):
                errors.append(f"bridge_entry:{entry.artifact_name}:{entry.error}")
            else:
                warnings.append(f"optional_bridge_entry:{entry.artifact_name}:{entry.error}")

    required_count = sum(1 for entry in entries if entry.required)
    optional_count = sum(1 for entry in entries if not entry.required)
    present_required_count = sum(1 for entry in entries if entry.required and entry.present)
    present_optional_count = sum(1 for entry in entries if not entry.required and entry.present)

    if missing_required:
        status = "partial"
    elif errors:
        status = "invalid"
    else:
        status = "ready"

    return CSVStorageBridgePreflightReport(
        csv_id=safe_id,
        status=status,
        bridge_version=CSV_STORAGE_BRIDGE_PREFLIGHT_VERSION,
        entries=entries,
        required_count=required_count,
        present_required_count=present_required_count,
        optional_count=optional_count,
        present_optional_count=present_optional_count,
        artifact_validation_status=artifact_validation_status,
        security_status=security_status,
        scan_validation_status=scan_validation_status,
        missing_required_artifacts=missing_required,
        missing_optional_artifacts=missing_optional,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def csv_storage_bridge_preflight_summary(report: CSVStorageBridgePreflightReport) -> dict[str, Any]:
    """Return a compact JSON-safe summary for dashboards/API guides."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "entry_count": report.entry_count,
        "required_count": report.required_count,
        "present_required_count": report.present_required_count,
        "optional_count": report.optional_count,
        "present_optional_count": report.present_optional_count,
        "artifact_validation_status": report.artifact_validation_status,
        "security_status": report.security_status,
        "scan_validation_status": report.scan_validation_status,
        "missing_required_artifacts": list(report.missing_required_artifacts),
        "missing_optional_artifacts": list(report.missing_optional_artifacts),
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
    }

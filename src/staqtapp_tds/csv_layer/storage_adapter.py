"""CSV storage adapter contract layer for future native .tds integration.

This module still does not migrate CSV payloads into a dedicated native CSV
kernel.  It creates a durable, derived bridge-commit manifest that freezes the
validated storage bridge plan, payload lanes, provenance expectations, and
payload hashes.  It can also dry-run storage-adapter binding records from that
manifest so a later native adapter has a stable ingestion contract before any
native storage path is touched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any, Mapping

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.tds_json import dumps_canonical

from .manifest import validate_csv_id
from .storage_bridge import CSVStorageBridgePreflightReport, validate_csv_storage_bridge_preflight

CSV_STORAGE_BRIDGE_COMMIT_VERSION = "1.0"
CSV_STORAGE_ADAPTER_BINDING_VERSION = "1.0"
CSV_STORAGE_ADAPTER_REPLAY_VERSION = "1.0"
CSV_NATIVE_STORAGE_COMMIT_VERSION = "1.0"
CSV_NATIVE_STORAGE_REVALIDATION_VERSION = "1.0"

_CSV_ADAPTER_ARTIFACT_REPLAY_ORDER: tuple[str, ...] = (
    "raw",
    "dialect",
    "row_offsets",
    "content_hashes",
    "manifest",
    "import_report",
    "scan_profile",
    "row_anchor_profile",
    "scan_materialization_report",
    "transaction_report",
)


def _ordered_adapter_artifact_items(artifact_keys: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    order = {name: index for index, name in enumerate(_CSV_ADAPTER_ARTIFACT_REPLAY_ORDER)}
    return tuple(
        sorted(
            ((str(name), str(key)) for name, key in artifact_keys.items()),
            key=lambda item: (order.get(item[0], len(order)), item[0]),
        )
    )


def csv_storage_bridge_commit_report_key(csv_id: str) -> str:
    """Return the durable key for the CSV storage-bridge commit manifest."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__storage_bridge_commit_report.json"


@dataclass(frozen=True, slots=True)
class CSVStorageBridgeCommitReport:
    """Durable bridge-commit manifest for storage-ready CSV artifacts.

    The report is intentionally compact and evidence-oriented.  It records the
    artifact keys and payload hashes that passed preflight without copying row
    data or activating native CSV storage behavior.
    """

    csv_id: str
    status: str
    adapter_version: str
    report_key: str
    mode: str
    preflight_status: str
    entry_count: int
    required_count: int
    optional_count: int
    committed_count: int = 0
    artifact_keys: Mapping[str, str] = field(default_factory=dict)
    payload_hashes: Mapping[str, str] = field(default_factory=dict)
    payload_kinds: Mapping[str, str] = field(default_factory=dict)
    provenance_lanes: Mapping[str, str] = field(default_factory=dict)
    include_scan_artifacts: bool = False
    require_scan_artifacts: bool = False
    include_transaction_report: bool = False
    require_transaction_report: bool = False
    scan_validation_status: str = "not_checked"
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"ready", "committed", "valid"} and not self.errors

    @property
    def drifted(self) -> bool:
        return self.status == "drifted"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["artifact_keys"] = dict(self.artifact_keys)
        data["payload_hashes"] = dict(self.payload_hashes)
        data["payload_kinds"] = dict(self.payload_kinds)
        data["provenance_lanes"] = dict(self.provenance_lanes)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["drifted"] = self.drifted
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVStorageBridgeCommitReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            adapter_version=str(data.get("adapter_version", CSV_STORAGE_BRIDGE_COMMIT_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "unknown")),
            preflight_status=str(data.get("preflight_status", "not_checked")),
            entry_count=int(data.get("entry_count", 0)),
            required_count=int(data.get("required_count", 0)),
            optional_count=int(data.get("optional_count", 0)),
            committed_count=int(data.get("committed_count", 0)),
            artifact_keys={str(k): str(v) for k, v in (data.get("artifact_keys", {}) or {}).items()},
            payload_hashes={str(k): str(v) for k, v in (data.get("payload_hashes", {}) or {}).items()},
            payload_kinds={str(k): str(v) for k, v in (data.get("payload_kinds", {}) or {}).items()},
            provenance_lanes={str(k): str(v) for k, v in (data.get("provenance_lanes", {}) or {}).items()},
            include_scan_artifacts=bool(data.get("include_scan_artifacts", False)),
            require_scan_artifacts=bool(data.get("require_scan_artifacts", False)),
            include_transaction_report=bool(data.get("include_transaction_report", False)),
            require_transaction_report=bool(data.get("require_transaction_report", False)),
            scan_validation_status=str(data.get("scan_validation_status", "not_checked")),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )



def _payload_bytes(value: Any, expected_kind: str, encoding: str = "utf-8") -> bytes:
    """Return the canonical payload bytes used by CSV bridge/storage proofs."""
    if expected_kind == "TEXT_UTF8":
        if not isinstance(value, str):
            raise TypeError("expected text artifact")
        return value.encode(encoding)
    if expected_kind == "JSON_UTF8":
        if not isinstance(value, (dict, list)):
            raise TypeError("expected JSON-compatible artifact")
        return dumps_canonical(value)[0]
    raise TypeError(f"unsupported expected payload kind: {expected_kind}")


def _storage_entry_key(csv_id: str, artifact_name: str) -> str:
    """Return the deterministic future-adapter binding key for an artifact."""
    safe_id = validate_csv_id(csv_id)
    return f"csv_storage::{safe_id}::{artifact_name}"


@dataclass(frozen=True, slots=True)
class CSVStorageAdapterBinding:
    """One dry-run binding from a bridge-commit artifact to future storage."""

    artifact_name: str
    artifact_key: str
    storage_entry_key: str
    required: bool
    status: str
    expected_payload_kind: str
    expected_provenance: str
    payload_kind: str = ""
    stored_payload_sha256: str = ""
    current_payload_sha256: str = ""
    raw_size: int = 0
    stored_size: int = 0
    error: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def ok(self) -> bool:
        return self.status in {"ready", "optional_missing"} and not self.error

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ready"] = self.ready
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVStorageAdapterBinding":
        return cls(
            artifact_name=str(data.get("artifact_name", "")),
            artifact_key=str(data.get("artifact_key", "")),
            storage_entry_key=str(data.get("storage_entry_key", "")),
            required=bool(data.get("required", False)),
            status=str(data.get("status", "rejected")),
            expected_payload_kind=str(data.get("expected_payload_kind", "")),
            expected_provenance=str(data.get("expected_provenance", "")),
            payload_kind=str(data.get("payload_kind", "")),
            stored_payload_sha256=str(data.get("stored_payload_sha256", "")),
            current_payload_sha256=str(data.get("current_payload_sha256", "")),
            raw_size=int(data.get("raw_size", 0)),
            stored_size=int(data.get("stored_size", 0)),
            error=str(data.get("error", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVStorageAdapterBindingReport:
    """Read-only storage-adapter binding contract report for CSV artifacts."""

    csv_id: str
    status: str
    adapter_version: str
    source_commit_report_key: str
    mode: str
    bindings: tuple[CSVStorageAdapterBinding, ...]
    binding_count: int
    ready_count: int
    missing_count: int
    drifted_count: int
    optional_missing_count: int
    rejected_count: int
    preflight_status: str = "not_checked"
    commit_validation_status: str = "not_checked"
    include_scan_artifacts: bool = False
    require_scan_artifacts: bool = False
    include_transaction_report: bool = False
    require_transaction_report: bool = False
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
    def bindable_count(self) -> int:
        return self.ready_count

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bindings"] = [binding.to_dict() for binding in self.bindings]
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["bindable_count"] = self.bindable_count
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVStorageAdapterBindingReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            adapter_version=str(data.get("adapter_version", CSV_STORAGE_ADAPTER_BINDING_VERSION)),
            source_commit_report_key=str(data.get("source_commit_report_key", "")),
            mode=str(data.get("mode", "unknown")),
            bindings=tuple(CSVStorageAdapterBinding.from_mapping(v) for v in data.get("bindings", []) or []),
            binding_count=int(data.get("binding_count", 0)),
            ready_count=int(data.get("ready_count", 0)),
            missing_count=int(data.get("missing_count", 0)),
            drifted_count=int(data.get("drifted_count", 0)),
            optional_missing_count=int(data.get("optional_missing_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
            preflight_status=str(data.get("preflight_status", "not_checked")),
            commit_validation_status=str(data.get("commit_validation_status", "not_checked")),
            include_scan_artifacts=bool(data.get("include_scan_artifacts", False)),
            require_scan_artifacts=bool(data.get("require_scan_artifacts", False)),
            include_transaction_report=bool(data.get("include_transaction_report", False)),
            require_transaction_report=bool(data.get("require_transaction_report", False)),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )

def _report_from_preflight(
    preflight: CSVStorageBridgePreflightReport,
    *,
    report_key: str,
    status: str,
    mode: str,
    committed_count: int = 0,
    errors: tuple[str, ...] | None = None,
    warnings: tuple[str, ...] | None = None,
    include_scan_artifacts: bool = False,
    require_scan_artifacts: bool = False,
    include_transaction_report: bool = False,
    require_transaction_report: bool = False,
) -> CSVStorageBridgeCommitReport:
    entries = preflight.entries
    combined_errors = tuple(dict.fromkeys(tuple(errors or ()) + tuple(preflight.errors)))
    combined_warnings = tuple(dict.fromkeys(tuple(warnings or ()) + tuple(preflight.warnings)))
    return CSVStorageBridgeCommitReport(
        csv_id=preflight.csv_id,
        status=status,
        adapter_version=CSV_STORAGE_BRIDGE_COMMIT_VERSION,
        report_key=report_key,
        mode=mode,
        preflight_status=preflight.status,
        entry_count=preflight.entry_count,
        required_count=preflight.required_count,
        optional_count=preflight.optional_count,
        committed_count=committed_count,
        artifact_keys={entry.artifact_name: entry.artifact_key for entry in entries},
        payload_hashes={entry.artifact_name: entry.payload_sha256 for entry in entries if entry.present},
        payload_kinds={entry.artifact_name: entry.payload_kind for entry in entries if entry.present},
        provenance_lanes={entry.artifact_name: entry.expected_provenance for entry in entries},
        include_scan_artifacts=bool(include_scan_artifacts),
        require_scan_artifacts=bool(require_scan_artifacts),
        include_transaction_report=bool(include_transaction_report),
        require_transaction_report=bool(require_transaction_report),
        scan_validation_status=preflight.scan_validation_status,
        errors=combined_errors,
        warnings=combined_warnings,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def _invalid_report(csv_id: str, error: str, *, report_key: str = "") -> CSVStorageBridgeCommitReport:
    return CSVStorageBridgeCommitReport(
        csv_id=str(csv_id),
        status="invalid",
        adapter_version=CSV_STORAGE_BRIDGE_COMMIT_VERSION,
        report_key=report_key,
        mode="invalid",
        preflight_status="not_checked",
        entry_count=0,
        required_count=0,
        optional_count=0,
        errors=(error,),
    )


def prepare_csv_storage_bridge_commit(
    directory: TDSDirectory,
    csv_id: str,
    *,
    include_scan_artifacts: bool = False,
    require_scan_artifacts: bool = False,
    include_transaction_report: bool = False,
    require_transaction_report: bool = False,
    chunk_size: int | None = None,
) -> CSVStorageBridgeCommitReport:
    """Build a dry-run bridge commit manifest without writing anything."""
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_storage_bridge_commit_report_key(safe_id)
    except Exception as exc:
        return _invalid_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    preflight = validate_csv_storage_bridge_preflight(
        directory,
        safe_id,
        include_scan_artifacts=include_scan_artifacts,
        require_scan_artifacts=require_scan_artifacts,
        include_transaction_report=include_transaction_report,
        require_transaction_report=require_transaction_report,
        chunk_size=chunk_size,
    )
    status = "ready" if preflight.ok else "invalid"
    return _report_from_preflight(
        preflight,
        report_key=report_key,
        status=status,
        mode="dry_run",
        include_scan_artifacts=include_scan_artifacts,
        require_scan_artifacts=require_scan_artifacts,
        include_transaction_report=include_transaction_report,
        require_transaction_report=require_transaction_report,
    )


def commit_csv_storage_bridge_manifest(
    directory: TDSDirectory,
    csv_id: str,
    *,
    include_scan_artifacts: bool = False,
    require_scan_artifacts: bool = False,
    include_transaction_report: bool = False,
    require_transaction_report: bool = False,
    chunk_size: int | None = None,
    overwrite: bool = False,
) -> CSVStorageBridgeCommitReport:
    """Persist a derived bridge-commit manifest after successful preflight."""
    prepared = prepare_csv_storage_bridge_commit(
        directory,
        csv_id,
        include_scan_artifacts=include_scan_artifacts,
        require_scan_artifacts=require_scan_artifacts,
        include_transaction_report=include_transaction_report,
        require_transaction_report=require_transaction_report,
        chunk_size=chunk_size,
    )
    if not prepared.ok:
        return prepared

    committed = CSVStorageBridgeCommitReport(
        csv_id=prepared.csv_id,
        status="committed",
        adapter_version=prepared.adapter_version,
        report_key=prepared.report_key,
        mode="manifest_commit",
        preflight_status=prepared.preflight_status,
        entry_count=prepared.entry_count,
        required_count=prepared.required_count,
        optional_count=prepared.optional_count,
        committed_count=prepared.entry_count,
        artifact_keys=dict(prepared.artifact_keys),
        payload_hashes=dict(prepared.payload_hashes),
        payload_kinds=dict(prepared.payload_kinds),
        provenance_lanes=dict(prepared.provenance_lanes),
        include_scan_artifacts=prepared.include_scan_artifacts,
        require_scan_artifacts=prepared.require_scan_artifacts,
        include_transaction_report=prepared.include_transaction_report,
        require_transaction_report=prepared.require_transaction_report,
        scan_validation_status=prepared.scan_validation_status,
        warnings=prepared.warnings,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )
    result: TDSResult = directory.write_json(
        committed.report_key,
        committed.to_dict(),
        overwrite=overwrite,
        provenance="DERIVED",
    )
    if not result.ok:
        return CSVStorageBridgeCommitReport(
            csv_id=committed.csv_id,
            status="invalid",
            adapter_version=committed.adapter_version,
            report_key=committed.report_key,
            mode="manifest_commit",
            preflight_status=committed.preflight_status,
            entry_count=committed.entry_count,
            required_count=committed.required_count,
            optional_count=committed.optional_count,
            artifact_keys=dict(committed.artifact_keys),
            payload_hashes=dict(committed.payload_hashes),
            payload_kinds=dict(committed.payload_kinds),
            provenance_lanes=dict(committed.provenance_lanes),
            include_scan_artifacts=committed.include_scan_artifacts,
            require_scan_artifacts=committed.require_scan_artifacts,
            include_transaction_report=committed.include_transaction_report,
            require_transaction_report=committed.require_transaction_report,
            scan_validation_status=committed.scan_validation_status,
            errors=(f"commit_report_write_failed:{result.code}:{result.message}",),
            warnings=committed.warnings,
        )
    return committed


def load_csv_storage_bridge_commit_report(directory: TDSDirectory, csv_id: str) -> CSVStorageBridgeCommitReport:
    """Load a persisted CSV storage-bridge commit report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_storage_bridge_commit_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV storage bridge commit report {key!r} is not a JSON object")
    return CSVStorageBridgeCommitReport.from_mapping(value)


def validate_csv_storage_bridge_commit(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
) -> CSVStorageBridgeCommitReport:
    """Validate a persisted bridge-commit manifest against current artifacts."""
    try:
        stored = load_csv_storage_bridge_commit_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_storage_bridge_commit_report_key(csv_id)
        except Exception:
            report_key = ""
        return _invalid_report(str(csv_id), f"commit_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    preflight = validate_csv_storage_bridge_preflight(
        directory,
        stored.csv_id,
        include_scan_artifacts=stored.include_scan_artifacts,
        require_scan_artifacts=stored.require_scan_artifacts,
        include_transaction_report=stored.include_transaction_report,
        require_transaction_report=stored.require_transaction_report,
        chunk_size=chunk_size,
    )
    errors: list[str] = []
    warnings: list[str] = list(stored.warnings)
    if stored.status != "committed":
        errors.append(f"stored_report_not_committed:{stored.status}")
    if not preflight.ok:
        errors.extend(f"preflight:{error}" for error in preflight.errors)

    current_keys = {entry.artifact_name: entry.artifact_key for entry in preflight.entries}
    current_hashes = {entry.artifact_name: entry.payload_sha256 for entry in preflight.entries if entry.present}
    current_kinds = {entry.artifact_name: entry.payload_kind for entry in preflight.entries if entry.present}

    if dict(stored.artifact_keys) != current_keys:
        errors.append("artifact_key_plan_drift")
    for name, expected_hash in stored.payload_hashes.items():
        actual_hash = current_hashes.get(name)
        if actual_hash != expected_hash:
            errors.append(f"payload_hash_drift:{name}")
    for name, expected_kind in stored.payload_kinds.items():
        actual_kind = current_kinds.get(name)
        if actual_kind != expected_kind:
            errors.append(f"payload_kind_drift:{name}")

    status = "valid" if not errors else "drifted"
    return _report_from_preflight(
        preflight,
        report_key=stored.report_key,
        status=status,
        mode="validation",
        committed_count=stored.committed_count,
        errors=tuple(errors),
        warnings=tuple(warnings),
        include_scan_artifacts=stored.include_scan_artifacts,
        require_scan_artifacts=stored.require_scan_artifacts,
        include_transaction_report=stored.include_transaction_report,
        require_transaction_report=stored.require_transaction_report,
    )



def _invalid_binding_report(csv_id: str, error: str, *, source_commit_report_key: str = "") -> CSVStorageAdapterBindingReport:
    return CSVStorageAdapterBindingReport(
        csv_id=str(csv_id),
        status="invalid",
        adapter_version=CSV_STORAGE_ADAPTER_BINDING_VERSION,
        source_commit_report_key=source_commit_report_key,
        mode="invalid",
        bindings=tuple(),
        binding_count=0,
        ready_count=0,
        missing_count=0,
        drifted_count=0,
        optional_missing_count=0,
        rejected_count=0,
        errors=(error,),
    )


def _binding_from_entry(
    *,
    csv_id: str,
    artifact_name: str,
    artifact_key: str,
    stored: CSVStorageBridgeCommitReport,
    current_entry: Any,
) -> CSVStorageAdapterBinding:
    stored_hash = str(stored.payload_hashes.get(artifact_name, ""))
    stored_kind = str(stored.payload_kinds.get(artifact_name, ""))
    stored_lane = str(stored.provenance_lanes.get(artifact_name, ""))
    storage_key = _storage_entry_key(csv_id, artifact_name)

    if current_entry is None:
        return CSVStorageAdapterBinding(
            artifact_name=artifact_name,
            artifact_key=artifact_key,
            storage_entry_key=storage_key,
            required=bool(stored_hash),
            status="rejected",
            expected_payload_kind=stored_kind,
            expected_provenance=stored_lane,
            stored_payload_sha256=stored_hash,
            error="artifact_not_in_current_bridge_plan",
        )

    if current_entry.artifact_key != artifact_key:
        return CSVStorageAdapterBinding(
            artifact_name=artifact_name,
            artifact_key=artifact_key,
            storage_entry_key=storage_key,
            required=current_entry.required,
            status="rejected",
            expected_payload_kind=current_entry.expected_payload_kind,
            expected_provenance=current_entry.expected_provenance,
            payload_kind=current_entry.payload_kind,
            stored_payload_sha256=stored_hash,
            current_payload_sha256=current_entry.payload_sha256,
            raw_size=current_entry.raw_size,
            stored_size=current_entry.stored_size,
            error="artifact_key_plan_drift",
        )

    if not current_entry.present:
        if not current_entry.required and not stored_hash:
            return CSVStorageAdapterBinding(
                artifact_name=artifact_name,
                artifact_key=artifact_key,
                storage_entry_key=storage_key,
                required=False,
                status="optional_missing",
                expected_payload_kind=current_entry.expected_payload_kind,
                expected_provenance=current_entry.expected_provenance,
            )
        return CSVStorageAdapterBinding(
            artifact_name=artifact_name,
            artifact_key=artifact_key,
            storage_entry_key=storage_key,
            required=current_entry.required,
            status="missing",
            expected_payload_kind=current_entry.expected_payload_kind,
            expected_provenance=current_entry.expected_provenance,
            stored_payload_sha256=stored_hash,
            error=current_entry.error or "artifact_missing",
        )

    if current_entry.error:
        return CSVStorageAdapterBinding(
            artifact_name=artifact_name,
            artifact_key=artifact_key,
            storage_entry_key=storage_key,
            required=current_entry.required,
            status="rejected",
            expected_payload_kind=current_entry.expected_payload_kind,
            expected_provenance=current_entry.expected_provenance,
            payload_kind=current_entry.payload_kind,
            stored_payload_sha256=stored_hash,
            current_payload_sha256=current_entry.payload_sha256,
            raw_size=current_entry.raw_size,
            stored_size=current_entry.stored_size,
            error=current_entry.error,
        )

    if stored_kind and current_entry.payload_kind != stored_kind:
        return CSVStorageAdapterBinding(
            artifact_name=artifact_name,
            artifact_key=artifact_key,
            storage_entry_key=storage_key,
            required=current_entry.required,
            status="drifted",
            expected_payload_kind=stored_kind,
            expected_provenance=current_entry.expected_provenance,
            payload_kind=current_entry.payload_kind,
            stored_payload_sha256=stored_hash,
            current_payload_sha256=current_entry.payload_sha256,
            raw_size=current_entry.raw_size,
            stored_size=current_entry.stored_size,
            error="payload_kind_drift",
        )

    if stored_lane and current_entry.expected_provenance != stored_lane:
        return CSVStorageAdapterBinding(
            artifact_name=artifact_name,
            artifact_key=artifact_key,
            storage_entry_key=storage_key,
            required=current_entry.required,
            status="drifted",
            expected_payload_kind=current_entry.expected_payload_kind,
            expected_provenance=stored_lane,
            payload_kind=current_entry.payload_kind,
            stored_payload_sha256=stored_hash,
            current_payload_sha256=current_entry.payload_sha256,
            raw_size=current_entry.raw_size,
            stored_size=current_entry.stored_size,
            error="provenance_lane_drift",
        )

    if stored_hash and current_entry.payload_sha256 != stored_hash:
        return CSVStorageAdapterBinding(
            artifact_name=artifact_name,
            artifact_key=artifact_key,
            storage_entry_key=storage_key,
            required=current_entry.required,
            status="drifted",
            expected_payload_kind=current_entry.expected_payload_kind,
            expected_provenance=current_entry.expected_provenance,
            payload_kind=current_entry.payload_kind,
            stored_payload_sha256=stored_hash,
            current_payload_sha256=current_entry.payload_sha256,
            raw_size=current_entry.raw_size,
            stored_size=current_entry.stored_size,
            error="payload_hash_drift",
        )

    return CSVStorageAdapterBinding(
        artifact_name=artifact_name,
        artifact_key=artifact_key,
        storage_entry_key=storage_key,
        required=current_entry.required,
        status="ready",
        expected_payload_kind=current_entry.expected_payload_kind,
        expected_provenance=current_entry.expected_provenance,
        payload_kind=current_entry.payload_kind,
        stored_payload_sha256=stored_hash,
        current_payload_sha256=current_entry.payload_sha256,
        raw_size=current_entry.raw_size,
        stored_size=current_entry.stored_size,
    )


def _binding_report_from_parts(
    *,
    stored: CSVStorageBridgeCommitReport,
    preflight: CSVStorageBridgePreflightReport,
    commit_validation: CSVStorageBridgeCommitReport,
    mode: str,
) -> CSVStorageAdapterBindingReport:
    current_by_name = {entry.artifact_name: entry for entry in preflight.entries}
    bindings = tuple(
        _binding_from_entry(
            csv_id=stored.csv_id,
            artifact_name=name,
            artifact_key=key,
            stored=stored,
            current_entry=current_by_name.get(name),
        )
        for name, key in _ordered_adapter_artifact_items(stored.artifact_keys)
    )

    ready_count = sum(1 for binding in bindings if binding.status == "ready")
    missing_count = sum(1 for binding in bindings if binding.status == "missing")
    drifted_count = sum(1 for binding in bindings if binding.status == "drifted")
    optional_missing_count = sum(1 for binding in bindings if binding.status == "optional_missing")
    rejected_count = sum(1 for binding in bindings if binding.status == "rejected")

    errors: list[str] = []
    warnings: list[str] = list(dict.fromkeys(tuple(preflight.warnings) + tuple(commit_validation.warnings)))
    if stored.status != "committed":
        errors.append(f"stored_report_not_committed:{stored.status}")
    for error in commit_validation.errors:
        errors.append(f"commit_validation:{error}")
    for binding in bindings:
        if binding.status in {"missing", "drifted", "rejected"}:
            errors.append(f"binding:{binding.artifact_name}:{binding.status}:{binding.error}")
        elif binding.status == "optional_missing":
            warnings.append(f"binding:{binding.artifact_name}:optional_missing")

    status = "ready" if not errors else "invalid"
    return CSVStorageAdapterBindingReport(
        csv_id=stored.csv_id,
        status=status,
        adapter_version=CSV_STORAGE_ADAPTER_BINDING_VERSION,
        source_commit_report_key=stored.report_key,
        mode=mode,
        bindings=bindings,
        binding_count=len(bindings),
        ready_count=ready_count,
        missing_count=missing_count,
        drifted_count=drifted_count,
        optional_missing_count=optional_missing_count,
        rejected_count=rejected_count,
        preflight_status=preflight.status,
        commit_validation_status=commit_validation.status,
        include_scan_artifacts=stored.include_scan_artifacts,
        require_scan_artifacts=stored.require_scan_artifacts,
        include_transaction_report=stored.include_transaction_report,
        require_transaction_report=stored.require_transaction_report,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def prepare_csv_storage_adapter_binding(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
) -> CSVStorageAdapterBindingReport:
    """Build a read-only future storage-adapter binding report.

    The function requires an existing committed bridge manifest. It revalidates
    that manifest, resolves each artifact into a deterministic adapter binding,
    and reports ready/missing/drifted/optional-missing/rejected statuses without
    writing entries or touching the native storage engine.
    """
    try:
        stored = load_csv_storage_bridge_commit_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_storage_bridge_commit_report_key(csv_id)
        except Exception:
            report_key = ""
        return _invalid_binding_report(
            str(csv_id),
            f"commit_report_unreadable:{type(exc).__name__}:{exc}",
            source_commit_report_key=report_key,
        )

    preflight = validate_csv_storage_bridge_preflight(
        directory,
        stored.csv_id,
        include_scan_artifacts=stored.include_scan_artifacts,
        require_scan_artifacts=stored.require_scan_artifacts,
        include_transaction_report=stored.include_transaction_report,
        require_transaction_report=stored.require_transaction_report,
        chunk_size=chunk_size,
    )
    commit_validation = validate_csv_storage_bridge_commit(directory, stored.csv_id, chunk_size=chunk_size)
    return _binding_report_from_parts(
        stored=stored,
        preflight=preflight,
        commit_validation=commit_validation,
        mode="dry_run",
    )


def validate_csv_storage_adapter_binding(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
) -> CSVStorageAdapterBindingReport:
    """Validate the current storage-adapter binding contract for a CSV set."""
    report = prepare_csv_storage_adapter_binding(directory, csv_id, chunk_size=chunk_size)
    if report.mode == "invalid":
        return report
    return CSVStorageAdapterBindingReport(
        csv_id=report.csv_id,
        status=report.status,
        adapter_version=report.adapter_version,
        source_commit_report_key=report.source_commit_report_key,
        mode="validation",
        bindings=report.bindings,
        binding_count=report.binding_count,
        ready_count=report.ready_count,
        missing_count=report.missing_count,
        drifted_count=report.drifted_count,
        optional_missing_count=report.optional_missing_count,
        rejected_count=report.rejected_count,
        preflight_status=report.preflight_status,
        commit_validation_status=report.commit_validation_status,
        include_scan_artifacts=report.include_scan_artifacts,
        require_scan_artifacts=report.require_scan_artifacts,
        include_transaction_report=report.include_transaction_report,
        require_transaction_report=report.require_transaction_report,
        errors=report.errors,
        warnings=report.warnings,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def csv_storage_adapter_replay_report_key(csv_id: str) -> str:
    """Return the durable key for a simulated CSV storage-adapter replay report."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__storage_adapter_replay_report.json"


@dataclass(frozen=True, slots=True)
class CSVStorageAdapterReplayStep:
    """One deterministic simulated storage-adapter operation.

    A replay step is not a native write. It records what a future adapter would
    do after binding validation: open a transaction, stage payloads, verify
    hashes, commit payloads, skip optional missing artifacts, or reject unsafe
    bindings before the native storage path is reached.
    """

    step_index: int
    operation: str
    status: str
    artifact_name: str = ""
    artifact_key: str = ""
    storage_entry_key: str = ""
    required: bool = False
    expected_payload_kind: str = ""
    expected_provenance: str = ""
    payload_sha256: str = ""
    raw_size: int = 0
    stored_size: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"planned", "staged", "committed", "skipped_optional"} and not self.error

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVStorageAdapterReplayStep":
        return cls(
            step_index=int(data.get("step_index", 0)),
            operation=str(data.get("operation", "")),
            status=str(data.get("status", "rejected")),
            artifact_name=str(data.get("artifact_name", "")),
            artifact_key=str(data.get("artifact_key", "")),
            storage_entry_key=str(data.get("storage_entry_key", "")),
            required=bool(data.get("required", False)),
            expected_payload_kind=str(data.get("expected_payload_kind", "")),
            expected_provenance=str(data.get("expected_provenance", "")),
            payload_sha256=str(data.get("payload_sha256", "")),
            raw_size=int(data.get("raw_size", 0)),
            stored_size=int(data.get("stored_size", 0)),
            error=str(data.get("error", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVStorageAdapterReplayReport:
    """Commit-simulation replay proof for future CSV storage integration."""

    csv_id: str
    status: str
    adapter_version: str
    source_commit_report_key: str
    report_key: str
    mode: str
    transaction_id: str
    replay_fingerprint: str
    binding_validation_status: str
    binding_count: int
    replay_steps: tuple[CSVStorageAdapterReplayStep, ...]
    step_count: int
    planned_count: int
    staged_count: int
    committed_count: int
    skipped_optional_count: int
    rejected_count: int
    failed_hash_check_count: int
    failed_binding_validation_count: int
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    tds_artifact_writes: int = 0
    native_storage_writes: bool = False
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"simulated", "replay_committed", "valid"} and not self.errors

    @property
    def simulated_payload_commits(self) -> int:
        return self.committed_count

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["replay_steps"] = [step.to_dict() for step in self.replay_steps]
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["simulated_payload_commits"] = self.simulated_payload_commits
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVStorageAdapterReplayReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            adapter_version=str(data.get("adapter_version", CSV_STORAGE_ADAPTER_REPLAY_VERSION)),
            source_commit_report_key=str(data.get("source_commit_report_key", "")),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "unknown")),
            transaction_id=str(data.get("transaction_id", "")),
            replay_fingerprint=str(data.get("replay_fingerprint", "")),
            binding_validation_status=str(data.get("binding_validation_status", "not_checked")),
            binding_count=int(data.get("binding_count", 0)),
            replay_steps=tuple(CSVStorageAdapterReplayStep.from_mapping(v) for v in data.get("replay_steps", []) or []),
            step_count=int(data.get("step_count", 0)),
            planned_count=int(data.get("planned_count", 0)),
            staged_count=int(data.get("staged_count", 0)),
            committed_count=int(data.get("committed_count", 0)),
            skipped_optional_count=int(data.get("skipped_optional_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
            failed_hash_check_count=int(data.get("failed_hash_check_count", 0)),
            failed_binding_validation_count=int(data.get("failed_binding_validation_count", 0)),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )


def _replay_transaction_id(csv_id: str, bindings: tuple[CSVStorageAdapterBinding, ...]) -> str:
    payload = {
        "csv_id": csv_id,
        "bindings": [
            {
                "artifact_name": binding.artifact_name,
                "artifact_key": binding.artifact_key,
                "storage_entry_key": binding.storage_entry_key,
                "stored_payload_sha256": binding.stored_payload_sha256,
                "current_payload_sha256": binding.current_payload_sha256,
                "status": binding.status,
            }
            for binding in bindings
        ],
    }
    raw, _ = dumps_canonical(payload)
    return "csv_replay_" + hashlib.sha256(raw).hexdigest()[:16]


def _replay_fingerprint(steps: tuple[CSVStorageAdapterReplayStep, ...]) -> str:
    raw, _ = dumps_canonical([
        {
            "step_index": step.step_index,
            "operation": step.operation,
            "status": step.status,
            "artifact_name": step.artifact_name,
            "artifact_key": step.artifact_key,
            "storage_entry_key": step.storage_entry_key,
            "payload_sha256": step.payload_sha256,
            "error": step.error,
        }
        for step in steps
    ])
    return hashlib.sha256(raw).hexdigest()


def _step_from_binding(index: int, operation: str, status: str, binding: CSVStorageAdapterBinding, *, error: str = "") -> CSVStorageAdapterReplayStep:
    return CSVStorageAdapterReplayStep(
        step_index=index,
        operation=operation,
        status=status,
        artifact_name=binding.artifact_name,
        artifact_key=binding.artifact_key,
        storage_entry_key=binding.storage_entry_key,
        required=binding.required,
        expected_payload_kind=binding.expected_payload_kind,
        expected_provenance=binding.expected_provenance,
        payload_sha256=binding.current_payload_sha256 or binding.stored_payload_sha256,
        raw_size=binding.raw_size,
        stored_size=binding.stored_size,
        error=error,
    )


def _build_replay_steps(binding_report: CSVStorageAdapterBindingReport) -> tuple[CSVStorageAdapterReplayStep, ...]:
    steps: list[CSVStorageAdapterReplayStep] = []
    index = 1
    steps.append(CSVStorageAdapterReplayStep(
        step_index=index,
        operation="open_adapter_transaction",
        status="planned",
    ))
    index += 1

    for binding in binding_report.bindings:
        if binding.status == "ready":
            steps.append(_step_from_binding(index, "stage_payload", "staged", binding))
            index += 1
            steps.append(_step_from_binding(index, "verify_payload_hash", "planned", binding))
            index += 1
            steps.append(_step_from_binding(index, "commit_payload", "committed", binding))
            index += 1
        elif binding.status == "optional_missing":
            steps.append(_step_from_binding(index, "skip_optional_payload", "skipped_optional", binding))
            index += 1
        elif binding.status == "drifted" and binding.error == "payload_hash_drift":
            steps.append(_step_from_binding(index, "verify_payload_hash", "failed_hash_check", binding, error=binding.error))
            index += 1
        else:
            steps.append(_step_from_binding(index, "validate_binding", "failed_binding_validation", binding, error=binding.error or binding.status))
            index += 1

    steps.append(CSVStorageAdapterReplayStep(
        step_index=index,
        operation="record_replay_result",
        status="planned",
    ))
    return tuple(steps)


def _invalid_replay_report(csv_id: str, error: str, *, report_key: str = "", source_commit_report_key: str = "") -> CSVStorageAdapterReplayReport:
    return CSVStorageAdapterReplayReport(
        csv_id=str(csv_id),
        status="invalid",
        adapter_version=CSV_STORAGE_ADAPTER_REPLAY_VERSION,
        source_commit_report_key=source_commit_report_key,
        report_key=report_key,
        mode="invalid",
        transaction_id="",
        replay_fingerprint="",
        binding_validation_status="not_checked",
        binding_count=0,
        replay_steps=tuple(),
        step_count=0,
        planned_count=0,
        staged_count=0,
        committed_count=0,
        skipped_optional_count=0,
        rejected_count=0,
        failed_hash_check_count=0,
        failed_binding_validation_count=0,
        errors=(error,),
    )


def _replay_report_from_binding(binding_report: CSVStorageAdapterBindingReport, *, mode: str, tds_artifact_writes: int = 0) -> CSVStorageAdapterReplayReport:
    steps = _build_replay_steps(binding_report)
    planned_count = sum(1 for step in steps if step.status == "planned")
    staged_count = sum(1 for step in steps if step.status == "staged")
    committed_count = sum(1 for step in steps if step.status == "committed")
    skipped_optional_count = sum(1 for step in steps if step.status == "skipped_optional")
    rejected_count = sum(1 for step in steps if step.status == "rejected")
    failed_hash_check_count = sum(1 for step in steps if step.status == "failed_hash_check")
    failed_binding_validation_count = sum(1 for step in steps if step.status == "failed_binding_validation")

    errors: list[str] = list(binding_report.errors)
    for step in steps:
        if step.status == "failed_hash_check":
            errors.append(f"replay:{step.artifact_name}:failed_hash_check:{step.error}")
        elif step.status in {"rejected", "failed_binding_validation"}:
            errors.append(f"replay:{step.artifact_name}:failed_binding_validation:{step.error}")
    status = "simulated" if not errors else "invalid"
    return CSVStorageAdapterReplayReport(
        csv_id=binding_report.csv_id,
        status=status,
        adapter_version=CSV_STORAGE_ADAPTER_REPLAY_VERSION,
        source_commit_report_key=binding_report.source_commit_report_key,
        report_key=csv_storage_adapter_replay_report_key(binding_report.csv_id),
        mode=mode,
        transaction_id=_replay_transaction_id(binding_report.csv_id, binding_report.bindings),
        replay_fingerprint=_replay_fingerprint(steps),
        binding_validation_status=binding_report.status,
        binding_count=binding_report.binding_count,
        replay_steps=steps,
        step_count=len(steps),
        planned_count=planned_count,
        staged_count=staged_count,
        committed_count=committed_count,
        skipped_optional_count=skipped_optional_count,
        rejected_count=rejected_count,
        failed_hash_check_count=failed_hash_check_count,
        failed_binding_validation_count=failed_binding_validation_count,
        errors=tuple(dict.fromkeys(errors)),
        warnings=binding_report.warnings,
        tds_artifact_writes=tds_artifact_writes,
        native_storage_writes=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def prepare_csv_storage_adapter_replay(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
) -> CSVStorageAdapterReplayReport:
    """Build a deterministic simulated native-storage commit replay.

    This consumes the storage-adapter binding contract, creates an ordered mock
    operation stream, and classifies each artifact before any native storage
    commit is attempted. It writes nothing.
    """
    try:
        report_key = csv_storage_adapter_replay_report_key(csv_id)
    except Exception as exc:
        return _invalid_replay_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    binding_report = validate_csv_storage_adapter_binding(directory, csv_id, chunk_size=chunk_size)
    if binding_report.mode == "invalid" and not binding_report.bindings:
        return _invalid_replay_report(
            str(csv_id),
            ";".join(binding_report.errors) or "binding_report_invalid",
            report_key=report_key,
            source_commit_report_key=binding_report.source_commit_report_key,
        )
    return _replay_report_from_binding(binding_report, mode="commit_simulation")


def commit_csv_storage_adapter_replay_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    overwrite: bool = False,
) -> CSVStorageAdapterReplayReport:
    """Persist the simulated replay proof as a derived report, never native CSV data."""
    prepared = prepare_csv_storage_adapter_replay(directory, csv_id, chunk_size=chunk_size)
    if not prepared.ok:
        return prepared
    committed = CSVStorageAdapterReplayReport(
        csv_id=prepared.csv_id,
        status="replay_committed",
        adapter_version=prepared.adapter_version,
        source_commit_report_key=prepared.source_commit_report_key,
        report_key=prepared.report_key,
        mode="replay_report_commit",
        transaction_id=prepared.transaction_id,
        replay_fingerprint=prepared.replay_fingerprint,
        binding_validation_status=prepared.binding_validation_status,
        binding_count=prepared.binding_count,
        replay_steps=prepared.replay_steps,
        step_count=prepared.step_count,
        planned_count=prepared.planned_count,
        staged_count=prepared.staged_count,
        committed_count=prepared.committed_count,
        skipped_optional_count=prepared.skipped_optional_count,
        rejected_count=prepared.rejected_count,
        failed_hash_check_count=prepared.failed_hash_check_count,
        failed_binding_validation_count=prepared.failed_binding_validation_count,
        warnings=prepared.warnings,
        tds_artifact_writes=1,
        native_storage_writes=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )
    result: TDSResult = directory.write_json(
        committed.report_key,
        committed.to_dict(),
        overwrite=overwrite,
        provenance="DERIVED",
    )
    if not result.ok:
        return CSVStorageAdapterReplayReport(
            csv_id=committed.csv_id,
            status="invalid",
            adapter_version=committed.adapter_version,
            source_commit_report_key=committed.source_commit_report_key,
            report_key=committed.report_key,
            mode="replay_report_commit",
            transaction_id=committed.transaction_id,
            replay_fingerprint=committed.replay_fingerprint,
            binding_validation_status=committed.binding_validation_status,
            binding_count=committed.binding_count,
            replay_steps=committed.replay_steps,
            step_count=committed.step_count,
            planned_count=committed.planned_count,
            staged_count=committed.staged_count,
            committed_count=committed.committed_count,
            skipped_optional_count=committed.skipped_optional_count,
            rejected_count=committed.rejected_count,
            failed_hash_check_count=committed.failed_hash_check_count,
            failed_binding_validation_count=committed.failed_binding_validation_count,
            errors=(f"replay_report_write_failed:{result.code}:{result.message}",),
            warnings=committed.warnings,
            tds_artifact_writes=0,
            native_storage_writes=False,
            per_row_writes=False,
            per_cell_writes=False,
            native_storage_hot_path_touched=False,
            semantic_reasoning=False,
        )
    return committed


def load_csv_storage_adapter_replay_report(directory: TDSDirectory, csv_id: str) -> CSVStorageAdapterReplayReport:
    """Load a persisted CSV storage-adapter replay report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_storage_adapter_replay_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV storage adapter replay report {key!r} is not a JSON object")
    return CSVStorageAdapterReplayReport.from_mapping(value)


def validate_csv_storage_adapter_replay(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
) -> CSVStorageAdapterReplayReport:
    """Validate the current or persisted simulated replay proof for a CSV set."""
    fresh = prepare_csv_storage_adapter_replay(directory, csv_id, chunk_size=chunk_size)
    if fresh.mode == "invalid":
        return fresh

    try:
        stored = load_csv_storage_adapter_replay_report(directory, csv_id)
    except Exception:
        return CSVStorageAdapterReplayReport(
            csv_id=fresh.csv_id,
            status=fresh.status,
            adapter_version=fresh.adapter_version,
            source_commit_report_key=fresh.source_commit_report_key,
            report_key=fresh.report_key,
            mode="validation",
            transaction_id=fresh.transaction_id,
            replay_fingerprint=fresh.replay_fingerprint,
            binding_validation_status=fresh.binding_validation_status,
            binding_count=fresh.binding_count,
            replay_steps=fresh.replay_steps,
            step_count=fresh.step_count,
            planned_count=fresh.planned_count,
            staged_count=fresh.staged_count,
            committed_count=fresh.committed_count,
            skipped_optional_count=fresh.skipped_optional_count,
            rejected_count=fresh.rejected_count,
            failed_hash_check_count=fresh.failed_hash_check_count,
            failed_binding_validation_count=fresh.failed_binding_validation_count,
            errors=fresh.errors,
            warnings=fresh.warnings,
            tds_artifact_writes=0,
            native_storage_writes=False,
            per_row_writes=False,
            per_cell_writes=False,
            native_storage_hot_path_touched=False,
            semantic_reasoning=False,
        )

    errors: list[str] = []
    warnings: list[str] = list(stored.warnings)
    if stored.status != "replay_committed":
        errors.append(f"stored_replay_not_committed:{stored.status}")
    if stored.replay_fingerprint != fresh.replay_fingerprint:
        errors.append("replay_fingerprint_drift")
    if stored.transaction_id != fresh.transaction_id:
        errors.append("replay_transaction_drift")
    errors.extend(fresh.errors)
    status = "valid" if not errors else "drifted"
    return CSVStorageAdapterReplayReport(
        csv_id=fresh.csv_id,
        status=status,
        adapter_version=fresh.adapter_version,
        source_commit_report_key=fresh.source_commit_report_key,
        report_key=fresh.report_key,
        mode="validation",
        transaction_id=fresh.transaction_id,
        replay_fingerprint=fresh.replay_fingerprint,
        binding_validation_status=fresh.binding_validation_status,
        binding_count=fresh.binding_count,
        replay_steps=fresh.replay_steps,
        step_count=fresh.step_count,
        planned_count=fresh.planned_count,
        staged_count=fresh.staged_count,
        committed_count=fresh.committed_count,
        skipped_optional_count=fresh.skipped_optional_count,
        rejected_count=fresh.rejected_count,
        failed_hash_check_count=fresh.failed_hash_check_count,
        failed_binding_validation_count=fresh.failed_binding_validation_count,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings + list(fresh.warnings))),
        tds_artifact_writes=0,
        native_storage_writes=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def csv_storage_adapter_replay_summary(report: CSVStorageAdapterReplayReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for a storage-adapter replay report."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "mode": report.mode,
        "transaction_id": report.transaction_id,
        "replay_fingerprint": report.replay_fingerprint,
        "binding_validation_status": report.binding_validation_status,
        "binding_count": report.binding_count,
        "step_count": report.step_count,
        "planned_count": report.planned_count,
        "staged_count": report.staged_count,
        "committed_count": report.committed_count,
        "simulated_payload_commits": report.simulated_payload_commits,
        "skipped_optional_count": report.skipped_optional_count,
        "rejected_count": report.rejected_count,
        "failed_hash_check_count": report.failed_hash_check_count,
        "failed_binding_validation_count": report.failed_binding_validation_count,
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_writes": report.native_storage_writes,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
    }


def csv_storage_adapter_binding_summary(report: CSVStorageAdapterBindingReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for a binding report."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "mode": report.mode,
        "binding_count": report.binding_count,
        "bindable_count": report.bindable_count,
        "ready_count": report.ready_count,
        "missing_count": report.missing_count,
        "drifted_count": report.drifted_count,
        "optional_missing_count": report.optional_missing_count,
        "rejected_count": report.rejected_count,
        "preflight_status": report.preflight_status,
        "commit_validation_status": report.commit_validation_status,
        "include_scan_artifacts": report.include_scan_artifacts,
        "require_scan_artifacts": report.require_scan_artifacts,
        "include_transaction_report": report.include_transaction_report,
        "require_transaction_report": report.require_transaction_report,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
    }



def csv_native_storage_commit_report_key(csv_id: str) -> str:
    """Return the durable report key for a controlled CSV native-storage commit."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__native_storage_commit_report.json"


@dataclass(frozen=True, slots=True)
class CSVNativeStorageCommitEntry:
    """One fixed-artifact write into the storage-backed CSV namespace.

    This is the v3.4.0 beginning of CSV native storage integration. It is still
    artifact-level only: the adapter writes whole CSV evidence artifacts to the
    deterministic storage binding keys that were proven by the bridge/binding/
    replay sequence. It never writes per-row or per-cell records.
    """

    artifact_name: str
    artifact_key: str
    storage_entry_key: str
    required: bool
    status: str
    expected_payload_kind: str
    expected_provenance: str
    payload_sha256: str = ""
    storage_payload_sha256: str = ""
    raw_size: int = 0
    stored_size: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"committed", "already_present", "skipped_optional", "verified"} and not self.error

    @property
    def wrote_storage_entry(self) -> bool:
        return self.status == "committed"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["wrote_storage_entry"] = self.wrote_storage_entry
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVNativeStorageCommitEntry":
        return cls(
            artifact_name=str(data.get("artifact_name", "")),
            artifact_key=str(data.get("artifact_key", "")),
            storage_entry_key=str(data.get("storage_entry_key", "")),
            required=bool(data.get("required", False)),
            status=str(data.get("status", "rejected")),
            expected_payload_kind=str(data.get("expected_payload_kind", "")),
            expected_provenance=str(data.get("expected_provenance", "")),
            payload_sha256=str(data.get("payload_sha256", "")),
            storage_payload_sha256=str(data.get("storage_payload_sha256", "")),
            raw_size=int(data.get("raw_size", 0)),
            stored_size=int(data.get("stored_size", 0)),
            error=str(data.get("error", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVNativeStorageCommitReport:
    """Controlled artifact-level native-storage commit report for CSV evidence."""

    csv_id: str
    status: str
    adapter_version: str
    report_key: str
    source_replay_report_key: str
    source_commit_report_key: str
    mode: str
    transaction_id: str
    replay_fingerprint: str
    entries: tuple[CSVNativeStorageCommitEntry, ...]
    entry_count: int
    committed_count: int
    already_present_count: int
    skipped_optional_count: int
    rejected_count: int
    failed_write_count: int
    hash_verified_count: int
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    tds_artifact_writes: int = 0
    native_storage_entry_writes: int = 0
    native_storage_writes: bool = False
    native_c_engine_changed: bool = False
    native_csv_kernel_used: bool = False
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"native_storage_committed", "valid"} and not self.errors

    @property
    def storage_payload_commits(self) -> int:
        return self.committed_count

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entries"] = [entry.to_dict() for entry in self.entries]
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["storage_payload_commits"] = self.storage_payload_commits
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVNativeStorageCommitReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            adapter_version=str(data.get("adapter_version", CSV_NATIVE_STORAGE_COMMIT_VERSION)),
            report_key=str(data.get("report_key", "")),
            source_replay_report_key=str(data.get("source_replay_report_key", "")),
            source_commit_report_key=str(data.get("source_commit_report_key", "")),
            mode=str(data.get("mode", "unknown")),
            transaction_id=str(data.get("transaction_id", "")),
            replay_fingerprint=str(data.get("replay_fingerprint", "")),
            entries=tuple(CSVNativeStorageCommitEntry.from_mapping(v) for v in data.get("entries", []) or []),
            entry_count=int(data.get("entry_count", 0)),
            committed_count=int(data.get("committed_count", 0)),
            already_present_count=int(data.get("already_present_count", 0)),
            skipped_optional_count=int(data.get("skipped_optional_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
            failed_write_count=int(data.get("failed_write_count", 0)),
            hash_verified_count=int(data.get("hash_verified_count", 0)),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            native_storage_entry_writes=int(data.get("native_storage_entry_writes", 0)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            native_c_engine_changed=bool(data.get("native_c_engine_changed", False)),
            native_csv_kernel_used=bool(data.get("native_csv_kernel_used", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )


def _storage_payload_sha256(directory: TDSDirectory, key: str, expected_kind: str, *, encoding: str = "utf-8") -> tuple[str, int, int, str]:
    value = directory.read_value(key)
    metadata = directory.entry_metadata(key)
    raw = _payload_bytes(value, expected_kind, encoding)
    return hashlib.sha256(raw).hexdigest(), int(metadata.get("raw_size", len(raw))), int(metadata.get("stored_size", 0)), str(metadata.get("payload_kind", ""))


def _entry_from_failed_binding(binding: CSVStorageAdapterBinding, status: str, error: str) -> CSVNativeStorageCommitEntry:
    return CSVNativeStorageCommitEntry(
        artifact_name=binding.artifact_name,
        artifact_key=binding.artifact_key,
        storage_entry_key=binding.storage_entry_key,
        required=binding.required,
        status=status,
        expected_payload_kind=binding.expected_payload_kind,
        expected_provenance=binding.expected_provenance,
        payload_sha256=binding.current_payload_sha256 or binding.stored_payload_sha256,
        error=error,
    )


def _storage_commit_counts(entries: tuple[CSVNativeStorageCommitEntry, ...]) -> dict[str, int]:
    return {
        "committed_count": sum(1 for entry in entries if entry.status == "committed"),
        "already_present_count": sum(1 for entry in entries if entry.status == "already_present"),
        "skipped_optional_count": sum(1 for entry in entries if entry.status == "skipped_optional"),
        "rejected_count": sum(1 for entry in entries if entry.status == "rejected"),
        "failed_write_count": sum(1 for entry in entries if entry.status == "failed_write"),
        "hash_verified_count": sum(1 for entry in entries if entry.status in {"committed", "already_present", "verified"} and entry.storage_payload_sha256 == entry.payload_sha256),
    }


def _invalid_native_storage_commit_report(csv_id: str, error: str, *, report_key: str = "", source_replay_report_key: str = "", source_commit_report_key: str = "") -> CSVNativeStorageCommitReport:
    return CSVNativeStorageCommitReport(
        csv_id=str(csv_id),
        status="invalid",
        adapter_version=CSV_NATIVE_STORAGE_COMMIT_VERSION,
        report_key=report_key,
        source_replay_report_key=source_replay_report_key,
        source_commit_report_key=source_commit_report_key,
        mode="invalid",
        transaction_id="",
        replay_fingerprint="",
        entries=tuple(),
        entry_count=0,
        committed_count=0,
        already_present_count=0,
        skipped_optional_count=0,
        rejected_count=0,
        failed_write_count=0,
        hash_verified_count=0,
        errors=(error,),
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def _commit_storage_binding(directory: TDSDirectory, binding: CSVStorageAdapterBinding, *, overwrite: bool, encoding: str) -> CSVNativeStorageCommitEntry:
    if binding.status == "optional_missing":
        return CSVNativeStorageCommitEntry(
            artifact_name=binding.artifact_name,
            artifact_key=binding.artifact_key,
            storage_entry_key=binding.storage_entry_key,
            required=False,
            status="skipped_optional",
            expected_payload_kind=binding.expected_payload_kind,
            expected_provenance=binding.expected_provenance,
        )
    if binding.status != "ready":
        return _entry_from_failed_binding(binding, "rejected", binding.error or binding.status)

    try:
        value = directory.read_value(binding.artifact_key)
        source_raw = _payload_bytes(value, binding.expected_payload_kind, encoding)
        source_hash = hashlib.sha256(source_raw).hexdigest()
        if source_hash != binding.current_payload_sha256:
            return _entry_from_failed_binding(binding, "rejected", "source_payload_hash_drift")
    except Exception as exc:
        return _entry_from_failed_binding(binding, "rejected", f"source_artifact_unreadable:{type(exc).__name__}:{exc}")

    try:
        existing_hash, raw_size, stored_size, payload_kind = _storage_payload_sha256(directory, binding.storage_entry_key, binding.expected_payload_kind, encoding=encoding)
        if not overwrite:
            if existing_hash == binding.current_payload_sha256 and payload_kind == binding.expected_payload_kind:
                return CSVNativeStorageCommitEntry(
                    artifact_name=binding.artifact_name,
                    artifact_key=binding.artifact_key,
                    storage_entry_key=binding.storage_entry_key,
                    required=binding.required,
                    status="already_present",
                    expected_payload_kind=binding.expected_payload_kind,
                    expected_provenance=binding.expected_provenance,
                    payload_sha256=binding.current_payload_sha256,
                    storage_payload_sha256=existing_hash,
                    raw_size=raw_size,
                    stored_size=stored_size,
                )
            return _entry_from_failed_binding(binding, "rejected", "storage_entry_exists_with_different_payload")
    except Exception:
        pass

    if binding.expected_payload_kind == "TEXT_UTF8":
        result = directory.write_text(binding.storage_entry_key, value, overwrite=overwrite, provenance=binding.expected_provenance)
    elif binding.expected_payload_kind == "JSON_UTF8":
        result = directory.write_json(binding.storage_entry_key, value, overwrite=overwrite, provenance=binding.expected_provenance)
    else:
        return _entry_from_failed_binding(binding, "rejected", f"unsupported_payload_kind:{binding.expected_payload_kind}")

    if not result.ok:
        return _entry_from_failed_binding(binding, "failed_write", f"storage_write_failed:{result.code}:{result.message}")

    try:
        stored_hash, raw_size, stored_size, payload_kind = _storage_payload_sha256(directory, binding.storage_entry_key, binding.expected_payload_kind, encoding=encoding)
    except Exception as exc:
        return _entry_from_failed_binding(binding, "failed_write", f"storage_entry_unreadable_after_write:{type(exc).__name__}:{exc}")

    if payload_kind != binding.expected_payload_kind:
        return CSVNativeStorageCommitEntry(
            artifact_name=binding.artifact_name,
            artifact_key=binding.artifact_key,
            storage_entry_key=binding.storage_entry_key,
            required=binding.required,
            status="failed_write",
            expected_payload_kind=binding.expected_payload_kind,
            expected_provenance=binding.expected_provenance,
            payload_sha256=binding.current_payload_sha256,
            storage_payload_sha256=stored_hash,
            raw_size=raw_size,
            stored_size=stored_size,
            error="storage_payload_kind_mismatch",
        )
    if stored_hash != binding.current_payload_sha256:
        return CSVNativeStorageCommitEntry(
            artifact_name=binding.artifact_name,
            artifact_key=binding.artifact_key,
            storage_entry_key=binding.storage_entry_key,
            required=binding.required,
            status="failed_write",
            expected_payload_kind=binding.expected_payload_kind,
            expected_provenance=binding.expected_provenance,
            payload_sha256=binding.current_payload_sha256,
            storage_payload_sha256=stored_hash,
            raw_size=raw_size,
            stored_size=stored_size,
            error="storage_payload_hash_mismatch",
        )
    return CSVNativeStorageCommitEntry(
        artifact_name=binding.artifact_name,
        artifact_key=binding.artifact_key,
        storage_entry_key=binding.storage_entry_key,
        required=binding.required,
        status="committed",
        expected_payload_kind=binding.expected_payload_kind,
        expected_provenance=binding.expected_provenance,
        payload_sha256=binding.current_payload_sha256,
        storage_payload_sha256=stored_hash,
        raw_size=raw_size,
        stored_size=stored_size,
    )


def commit_csv_native_storage_artifacts(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    overwrite: bool = False,
    encoding: str = "utf-8",
) -> CSVNativeStorageCommitReport:
    """Commit fixed CSV evidence artifacts into deterministic storage bindings.

    v3.4.0 intentionally begins native-storage integration at artifact granularity.
    The adapter requires a persisted replay proof, revalidates it, then writes only
    the fixed CSV artifact set to the previously proven storage binding keys. It
    does not write rows/cells, does not call a native CSV kernel, and does not
    change the native C engine.
    """
    try:
        report_key = csv_native_storage_commit_report_key(csv_id)
        replay_key = csv_storage_adapter_replay_report_key(csv_id)
    except Exception as exc:
        return _invalid_native_storage_commit_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    try:
        persisted_replay = load_csv_storage_adapter_replay_report(directory, csv_id)
    except Exception as exc:
        return _invalid_native_storage_commit_report(
            str(csv_id),
            f"replay_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
            source_replay_report_key=replay_key,
        )

    replay_validation = validate_csv_storage_adapter_replay(directory, csv_id, chunk_size=chunk_size)
    if not replay_validation.ok:
        return _invalid_native_storage_commit_report(
            str(csv_id),
            ";".join(replay_validation.errors) or f"replay_validation_not_ready:{replay_validation.status}",
            report_key=report_key,
            source_replay_report_key=replay_key,
            source_commit_report_key=persisted_replay.source_commit_report_key,
        )

    binding_report = validate_csv_storage_adapter_binding(directory, csv_id, chunk_size=chunk_size)
    if not binding_report.ok:
        return _invalid_native_storage_commit_report(
            str(csv_id),
            ";".join(binding_report.errors) or f"binding_validation_not_ready:{binding_report.status}",
            report_key=report_key,
            source_replay_report_key=replay_key,
            source_commit_report_key=binding_report.source_commit_report_key,
        )

    entries = tuple(
        _commit_storage_binding(directory, binding, overwrite=overwrite, encoding=encoding)
        for binding in binding_report.bindings
    )
    counts = _storage_commit_counts(entries)
    errors: list[str] = []
    warnings: list[str] = list(dict.fromkeys(tuple(replay_validation.warnings) + tuple(binding_report.warnings)))
    for entry in entries:
        if entry.status in {"rejected", "failed_write"}:
            errors.append(f"storage_commit:{entry.artifact_name}:{entry.status}:{entry.error}")
        elif entry.status == "skipped_optional":
            warnings.append(f"storage_commit:{entry.artifact_name}:skipped_optional")
        elif entry.status == "already_present":
            warnings.append(f"storage_commit:{entry.artifact_name}:already_present")

    status = "native_storage_committed" if not errors else "invalid"
    native_entry_writes = int(counts["committed_count"])
    report = CSVNativeStorageCommitReport(
        csv_id=binding_report.csv_id,
        status=status,
        adapter_version=CSV_NATIVE_STORAGE_COMMIT_VERSION,
        report_key=report_key,
        source_replay_report_key=replay_key,
        source_commit_report_key=binding_report.source_commit_report_key,
        mode="native_storage_commit",
        transaction_id=replay_validation.transaction_id,
        replay_fingerprint=replay_validation.replay_fingerprint,
        entries=entries,
        entry_count=len(entries),
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        tds_artifact_writes=native_entry_writes,
        native_storage_entry_writes=native_entry_writes,
        native_storage_writes=native_entry_writes > 0,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=native_entry_writes > 0,
        semantic_reasoning=False,
        **counts,
    )
    if not report.ok:
        return report

    result: TDSResult = directory.write_json(report.report_key, report.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return CSVNativeStorageCommitReport(
            csv_id=report.csv_id,
            status="invalid",
            adapter_version=report.adapter_version,
            report_key=report.report_key,
            source_replay_report_key=report.source_replay_report_key,
            source_commit_report_key=report.source_commit_report_key,
            mode=report.mode,
            transaction_id=report.transaction_id,
            replay_fingerprint=report.replay_fingerprint,
            entries=report.entries,
            entry_count=report.entry_count,
            committed_count=report.committed_count,
            already_present_count=report.already_present_count,
            skipped_optional_count=report.skipped_optional_count,
            rejected_count=report.rejected_count,
            failed_write_count=report.failed_write_count,
            hash_verified_count=report.hash_verified_count,
            errors=(f"native_storage_commit_report_write_failed:{result.code}:{result.message}",),
            warnings=report.warnings,
            tds_artifact_writes=report.native_storage_entry_writes,
            native_storage_entry_writes=report.native_storage_entry_writes,
            native_storage_writes=report.native_storage_writes,
            native_c_engine_changed=False,
            native_csv_kernel_used=False,
            per_row_writes=False,
            per_cell_writes=False,
            native_storage_hot_path_touched=report.native_storage_hot_path_touched,
            semantic_reasoning=False,
        )
    return CSVNativeStorageCommitReport(
        csv_id=report.csv_id,
        status=report.status,
        adapter_version=report.adapter_version,
        report_key=report.report_key,
        source_replay_report_key=report.source_replay_report_key,
        source_commit_report_key=report.source_commit_report_key,
        mode=report.mode,
        transaction_id=report.transaction_id,
        replay_fingerprint=report.replay_fingerprint,
        entries=report.entries,
        entry_count=report.entry_count,
        committed_count=report.committed_count,
        already_present_count=report.already_present_count,
        skipped_optional_count=report.skipped_optional_count,
        rejected_count=report.rejected_count,
        failed_write_count=report.failed_write_count,
        hash_verified_count=report.hash_verified_count,
        warnings=report.warnings,
        tds_artifact_writes=report.tds_artifact_writes + 1,
        native_storage_entry_writes=report.native_storage_entry_writes,
        native_storage_writes=report.native_storage_writes,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=report.native_storage_hot_path_touched,
        semantic_reasoning=False,
    )


def load_csv_native_storage_commit_report(directory: TDSDirectory, csv_id: str) -> CSVNativeStorageCommitReport:
    """Load a persisted CSV native-storage commit report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_native_storage_commit_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV native storage commit report {key!r} is not a JSON object")
    return CSVNativeStorageCommitReport.from_mapping(value)


def validate_csv_native_storage_commit(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVNativeStorageCommitReport:
    """Validate persisted CSV storage-backed artifact bindings against source proof."""
    try:
        stored = load_csv_native_storage_commit_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_native_storage_commit_report_key(csv_id)
        except Exception:
            report_key = ""
        return _invalid_native_storage_commit_report(str(csv_id), f"native_storage_commit_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    replay_validation = validate_csv_storage_adapter_replay(directory, csv_id, chunk_size=chunk_size)
    binding_report = validate_csv_storage_adapter_binding(directory, csv_id, chunk_size=chunk_size)
    errors: list[str] = []
    warnings: list[str] = list(stored.warnings)
    if stored.status != "native_storage_committed":
        errors.append(f"stored_native_commit_not_committed:{stored.status}")
    if not replay_validation.ok:
        errors.extend(f"replay_validation:{error}" for error in replay_validation.errors)
    if not binding_report.ok:
        errors.extend(f"binding_validation:{error}" for error in binding_report.errors)
    if stored.transaction_id != replay_validation.transaction_id:
        errors.append("native_storage_transaction_drift")
    if stored.replay_fingerprint != replay_validation.replay_fingerprint:
        errors.append("native_storage_replay_fingerprint_drift")

    current_by_name = {binding.artifact_name: binding for binding in binding_report.bindings}
    verified_entries: list[CSVNativeStorageCommitEntry] = []
    for entry in stored.entries:
        binding = current_by_name.get(entry.artifact_name)
        if entry.status == "skipped_optional":
            verified_entries.append(entry)
            continue
        if binding is None:
            errors.append(f"storage_entry_binding_missing:{entry.artifact_name}")
            verified_entries.append(CSVNativeStorageCommitEntry.from_mapping({**entry.to_dict(), "status": "rejected", "error": "binding_missing"}))
            continue
        try:
            storage_hash, raw_size, stored_size, payload_kind = _storage_payload_sha256(directory, entry.storage_entry_key, entry.expected_payload_kind, encoding=encoding)
        except Exception as exc:
            errors.append(f"storage_entry_unreadable:{entry.artifact_name}:{type(exc).__name__}:{exc}")
            verified_entries.append(CSVNativeStorageCommitEntry.from_mapping({**entry.to_dict(), "status": "rejected", "error": "storage_entry_unreadable"}))
            continue
        if payload_kind != entry.expected_payload_kind:
            errors.append(f"storage_payload_kind_drift:{entry.artifact_name}")
        if storage_hash != entry.payload_sha256 or (binding.current_payload_sha256 and storage_hash != binding.current_payload_sha256):
            errors.append(f"storage_payload_hash_drift:{entry.artifact_name}")
        verified_entries.append(CSVNativeStorageCommitEntry(
            artifact_name=entry.artifact_name,
            artifact_key=entry.artifact_key,
            storage_entry_key=entry.storage_entry_key,
            required=entry.required,
            status="verified" if not errors or not any(err.endswith(f":{entry.artifact_name}") for err in errors) else "rejected",
            expected_payload_kind=entry.expected_payload_kind,
            expected_provenance=entry.expected_provenance,
            payload_sha256=entry.payload_sha256,
            storage_payload_sha256=storage_hash,
            raw_size=raw_size,
            stored_size=stored_size,
            error="" if storage_hash == entry.payload_sha256 and payload_kind == entry.expected_payload_kind else "storage_entry_drift",
        ))

    counts = _storage_commit_counts(tuple(verified_entries))
    status = "valid" if not errors else "drifted"
    return CSVNativeStorageCommitReport(
        csv_id=stored.csv_id,
        status=status,
        adapter_version=stored.adapter_version,
        report_key=stored.report_key,
        source_replay_report_key=stored.source_replay_report_key,
        source_commit_report_key=stored.source_commit_report_key,
        mode="validation",
        transaction_id=replay_validation.transaction_id,
        replay_fingerprint=replay_validation.replay_fingerprint,
        entries=tuple(verified_entries),
        entry_count=len(verified_entries),
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings + list(replay_validation.warnings) + list(binding_report.warnings))),
        tds_artifact_writes=0,
        native_storage_entry_writes=stored.native_storage_entry_writes,
        native_storage_writes=stored.native_storage_writes,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        **counts,
    )


def csv_native_storage_commit_summary(report: CSVNativeStorageCommitReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for a CSV native-storage commit report."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "mode": report.mode,
        "transaction_id": report.transaction_id,
        "replay_fingerprint": report.replay_fingerprint,
        "entry_count": report.entry_count,
        "committed_count": report.committed_count,
        "already_present_count": report.already_present_count,
        "skipped_optional_count": report.skipped_optional_count,
        "rejected_count": report.rejected_count,
        "failed_write_count": report.failed_write_count,
        "hash_verified_count": report.hash_verified_count,
        "storage_payload_commits": report.storage_payload_commits,
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_entry_writes": report.native_storage_entry_writes,
        "native_storage_writes": report.native_storage_writes,
        "native_c_engine_changed": report.native_c_engine_changed,
        "native_csv_kernel_used": report.native_csv_kernel_used,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
    }



def csv_native_storage_revalidation_report_key(csv_id: str) -> str:
    """Return the durable report key for a CSV native-storage revalidation guard."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__native_storage_revalidation_report.json"


@dataclass(frozen=True, slots=True)
class CSVNativeStorageRevalidationEntry:
    """One artifact-level revalidation result for storage-backed CSV evidence."""

    artifact_name: str
    artifact_key: str
    storage_entry_key: str
    required: bool
    status: str
    expected_payload_kind: str
    expected_provenance: str
    committed_payload_sha256: str = ""
    source_payload_sha256: str = ""
    storage_payload_sha256: str = ""
    binding_payload_sha256: str = ""
    source_status: str = "not_checked"
    storage_status: str = "not_checked"
    proof_status: str = "not_checked"
    raw_size: int = 0
    stored_size: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"verified", "skipped_optional"} and not self.error

    @property
    def drifted(self) -> bool:
        return self.status in {"source_drift", "storage_drift", "proof_drift"}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["drifted"] = self.drifted
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVNativeStorageRevalidationEntry":
        return cls(
            artifact_name=str(data.get("artifact_name", "")),
            artifact_key=str(data.get("artifact_key", "")),
            storage_entry_key=str(data.get("storage_entry_key", "")),
            required=bool(data.get("required", False)),
            status=str(data.get("status", "rejected")),
            expected_payload_kind=str(data.get("expected_payload_kind", "")),
            expected_provenance=str(data.get("expected_provenance", "")),
            committed_payload_sha256=str(data.get("committed_payload_sha256", "")),
            source_payload_sha256=str(data.get("source_payload_sha256", "")),
            storage_payload_sha256=str(data.get("storage_payload_sha256", "")),
            binding_payload_sha256=str(data.get("binding_payload_sha256", "")),
            source_status=str(data.get("source_status", "not_checked")),
            storage_status=str(data.get("storage_status", "not_checked")),
            proof_status=str(data.get("proof_status", "not_checked")),
            raw_size=int(data.get("raw_size", 0)),
            stored_size=int(data.get("stored_size", 0)),
            error=str(data.get("error", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVNativeStorageRevalidationReport:
    """Drift-guard snapshot for a storage-backed CSV artifact commit.

    This report is intentionally separate from the v3.4.0 commit report: the
    commit report remains the historical write proof, while revalidation reports
    are repeatable guard snapshots that compare source artifacts, bridge/binding/
    replay proofs, and storage-backed payloads without writing native payloads.
    """

    csv_id: str
    status: str
    adapter_version: str
    report_key: str
    source_native_commit_report_key: str
    source_replay_report_key: str
    source_commit_report_key: str
    mode: str
    transaction_id: str
    replay_fingerprint: str
    revalidation_fingerprint: str
    native_commit_validation_status: str
    replay_validation_status: str
    binding_validation_status: str
    entries: tuple[CSVNativeStorageRevalidationEntry, ...]
    entry_count: int
    verified_count: int
    source_drift_count: int
    storage_drift_count: int
    proof_drift_count: int
    missing_count: int
    skipped_optional_count: int
    rejected_count: int
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    tds_artifact_writes: int = 0
    native_storage_writes: bool = False
    native_c_engine_changed: bool = False
    native_csv_kernel_used: bool = False
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"revalidated", "valid"} and not self.errors

    @property
    def drifted(self) -> bool:
        return self.status == "drifted"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entries"] = [entry.to_dict() for entry in self.entries]
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["drifted"] = self.drifted
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVNativeStorageRevalidationReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            adapter_version=str(data.get("adapter_version", CSV_NATIVE_STORAGE_REVALIDATION_VERSION)),
            report_key=str(data.get("report_key", "")),
            source_native_commit_report_key=str(data.get("source_native_commit_report_key", "")),
            source_replay_report_key=str(data.get("source_replay_report_key", "")),
            source_commit_report_key=str(data.get("source_commit_report_key", "")),
            mode=str(data.get("mode", "unknown")),
            transaction_id=str(data.get("transaction_id", "")),
            replay_fingerprint=str(data.get("replay_fingerprint", "")),
            revalidation_fingerprint=str(data.get("revalidation_fingerprint", "")),
            native_commit_validation_status=str(data.get("native_commit_validation_status", "not_checked")),
            replay_validation_status=str(data.get("replay_validation_status", "not_checked")),
            binding_validation_status=str(data.get("binding_validation_status", "not_checked")),
            entries=tuple(CSVNativeStorageRevalidationEntry.from_mapping(v) for v in data.get("entries", []) or []),
            entry_count=int(data.get("entry_count", 0)),
            verified_count=int(data.get("verified_count", 0)),
            source_drift_count=int(data.get("source_drift_count", 0)),
            storage_drift_count=int(data.get("storage_drift_count", 0)),
            proof_drift_count=int(data.get("proof_drift_count", 0)),
            missing_count=int(data.get("missing_count", 0)),
            skipped_optional_count=int(data.get("skipped_optional_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            native_c_engine_changed=bool(data.get("native_c_engine_changed", False)),
            native_csv_kernel_used=bool(data.get("native_csv_kernel_used", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )


def _native_revalidation_counts(entries: tuple[CSVNativeStorageRevalidationEntry, ...]) -> dict[str, int]:
    return {
        "verified_count": sum(1 for entry in entries if entry.status == "verified"),
        "source_drift_count": sum(1 for entry in entries if entry.status == "source_drift"),
        "storage_drift_count": sum(1 for entry in entries if entry.status == "storage_drift"),
        "proof_drift_count": sum(1 for entry in entries if entry.status == "proof_drift"),
        "missing_count": sum(1 for entry in entries if entry.status == "missing"),
        "skipped_optional_count": sum(1 for entry in entries if entry.status == "skipped_optional"),
        "rejected_count": sum(1 for entry in entries if entry.status == "rejected"),
    }


def _native_revalidation_fingerprint(
    *,
    csv_id: str,
    transaction_id: str,
    replay_fingerprint: str,
    entries: tuple[CSVNativeStorageRevalidationEntry, ...],
    errors: tuple[str, ...],
) -> str:
    payload = {
        "version": CSV_NATIVE_STORAGE_REVALIDATION_VERSION,
        "csv_id": csv_id,
        "transaction_id": transaction_id,
        "replay_fingerprint": replay_fingerprint,
        "entries": [entry.to_dict() for entry in entries],
        "errors": list(errors),
    }
    return hashlib.sha256(dumps_canonical(payload)[0]).hexdigest()


def _invalid_native_revalidation_report(csv_id: str, error: str, *, report_key: str = "") -> CSVNativeStorageRevalidationReport:
    return CSVNativeStorageRevalidationReport(
        csv_id=str(csv_id),
        status="invalid",
        adapter_version=CSV_NATIVE_STORAGE_REVALIDATION_VERSION,
        report_key=report_key,
        source_native_commit_report_key="",
        source_replay_report_key="",
        source_commit_report_key="",
        mode="invalid",
        transaction_id="",
        replay_fingerprint="",
        revalidation_fingerprint="",
        native_commit_validation_status="not_checked",
        replay_validation_status="not_checked",
        binding_validation_status="not_checked",
        entries=tuple(),
        entry_count=0,
        verified_count=0,
        source_drift_count=0,
        storage_drift_count=0,
        proof_drift_count=0,
        missing_count=0,
        skipped_optional_count=0,
        rejected_count=0,
        errors=(error,),
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def _revalidation_entry_from_commit(
    directory: TDSDirectory,
    commit_entry: CSVNativeStorageCommitEntry,
    binding: CSVStorageAdapterBinding | None,
    *,
    proof_ok: bool,
    encoding: str,
) -> CSVNativeStorageRevalidationEntry:
    if commit_entry.status == "skipped_optional":
        return CSVNativeStorageRevalidationEntry(
            artifact_name=commit_entry.artifact_name,
            artifact_key=commit_entry.artifact_key,
            storage_entry_key=commit_entry.storage_entry_key,
            required=False,
            status="skipped_optional",
            expected_payload_kind=commit_entry.expected_payload_kind,
            expected_provenance=commit_entry.expected_provenance,
            committed_payload_sha256=commit_entry.payload_sha256,
            proof_status="valid" if proof_ok else "drifted",
        )

    source_status = "missing"
    source_hash = ""
    binding_hash = ""
    if binding is None:
        source_status = "binding_missing"
    else:
        source_status = binding.status
        binding_hash = binding.current_payload_sha256 or binding.stored_payload_sha256
        if binding.status == "ready":
            source_hash = binding.current_payload_sha256
        elif binding.status == "missing":
            source_status = "missing"
        elif binding.status == "drifted":
            source_hash = binding.current_payload_sha256
        elif binding.status == "rejected":
            source_status = f"rejected:{binding.error}"

    storage_status = "not_checked"
    storage_hash = ""
    raw_size = 0
    stored_size = 0
    storage_error = ""
    try:
        storage_hash, raw_size, stored_size, payload_kind = _storage_payload_sha256(
            directory,
            commit_entry.storage_entry_key,
            commit_entry.expected_payload_kind,
            encoding=encoding,
        )
        storage_status = "ready" if payload_kind == commit_entry.expected_payload_kind else "payload_kind_drift"
    except Exception as exc:
        storage_status = "missing"
        storage_error = f"storage_entry_unreadable:{type(exc).__name__}:{exc}"

    proof_status = "valid" if proof_ok else "drifted"
    committed_hash = commit_entry.payload_sha256

    if storage_status == "missing":
        status = "missing"
        error = storage_error or "storage_entry_missing"
    elif storage_hash != committed_hash or storage_status != "ready":
        status = "storage_drift"
        error = "storage_payload_hash_drift" if storage_hash != committed_hash else "storage_payload_kind_drift"
    elif source_status == "missing":
        status = "missing"
        error = "source_artifact_missing"
    elif binding is None:
        status = "proof_drift"
        error = "binding_missing"
    elif binding.status in {"drifted", "rejected"} or (binding_hash and binding_hash != committed_hash):
        status = "source_drift"
        error = binding.error or "source_payload_drift"
    elif not proof_ok:
        status = "proof_drift"
        error = "proof_validation_drift"
    else:
        status = "verified"
        error = ""

    return CSVNativeStorageRevalidationEntry(
        artifact_name=commit_entry.artifact_name,
        artifact_key=commit_entry.artifact_key,
        storage_entry_key=commit_entry.storage_entry_key,
        required=commit_entry.required,
        status=status,
        expected_payload_kind=commit_entry.expected_payload_kind,
        expected_provenance=commit_entry.expected_provenance,
        committed_payload_sha256=committed_hash,
        source_payload_sha256=source_hash,
        storage_payload_sha256=storage_hash,
        binding_payload_sha256=binding_hash,
        source_status=source_status,
        storage_status=storage_status,
        proof_status=proof_status,
        raw_size=raw_size,
        stored_size=stored_size,
        error=error,
    )


def prepare_csv_native_storage_revalidation(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVNativeStorageRevalidationReport:
    """Build a v3.4.1 native-storage drift-guard snapshot without writes."""
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_native_storage_revalidation_report_key(safe_id)
        native_commit_key = csv_native_storage_commit_report_key(safe_id)
    except Exception as exc:
        return _invalid_native_revalidation_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    try:
        stored_commit = load_csv_native_storage_commit_report(directory, safe_id)
    except Exception as exc:
        return _invalid_native_revalidation_report(
            safe_id,
            f"native_storage_commit_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
        )

    native_validation = validate_csv_native_storage_commit(directory, safe_id, chunk_size=chunk_size, encoding=encoding)
    replay_validation = validate_csv_storage_adapter_replay(directory, safe_id, chunk_size=chunk_size)
    binding_report = validate_csv_storage_adapter_binding(directory, safe_id, chunk_size=chunk_size)
    proof_ok = native_validation.ok and replay_validation.ok and binding_report.ok
    binding_by_name = {binding.artifact_name: binding for binding in binding_report.bindings}

    entries = tuple(
        _revalidation_entry_from_commit(
            directory,
            entry,
            binding_by_name.get(entry.artifact_name),
            proof_ok=proof_ok,
            encoding=encoding,
        )
        for entry in stored_commit.entries
    )
    counts = _native_revalidation_counts(entries)

    errors: list[str] = []
    warnings: list[str] = list(dict.fromkeys(tuple(stored_commit.warnings) + tuple(native_validation.warnings) + tuple(replay_validation.warnings) + tuple(binding_report.warnings)))
    if stored_commit.status != "native_storage_committed":
        errors.append(f"stored_native_commit_not_committed:{stored_commit.status}")
    if not replay_validation.ok:
        errors.extend(f"replay_validation:{error}" for error in replay_validation.errors)
    if not binding_report.ok:
        errors.extend(f"binding_validation:{error}" for error in binding_report.errors)
    if not native_validation.ok:
        errors.extend(f"native_commit_validation:{error}" for error in native_validation.errors)
    for entry in entries:
        if entry.status in {"source_drift", "storage_drift", "proof_drift", "missing", "rejected"}:
            errors.append(f"revalidation:{entry.artifact_name}:{entry.status}:{entry.error}")
        elif entry.status == "skipped_optional":
            warnings.append(f"revalidation:{entry.artifact_name}:skipped_optional")

    unique_errors = tuple(dict.fromkeys(errors))
    status = "revalidated" if not unique_errors else "drifted"
    fingerprint = _native_revalidation_fingerprint(
        csv_id=stored_commit.csv_id,
        transaction_id=stored_commit.transaction_id,
        replay_fingerprint=stored_commit.replay_fingerprint,
        entries=entries,
        errors=unique_errors,
    )
    return CSVNativeStorageRevalidationReport(
        csv_id=stored_commit.csv_id,
        status=status,
        adapter_version=CSV_NATIVE_STORAGE_REVALIDATION_VERSION,
        report_key=report_key,
        source_native_commit_report_key=native_commit_key,
        source_replay_report_key=stored_commit.source_replay_report_key,
        source_commit_report_key=stored_commit.source_commit_report_key,
        mode="revalidation",
        transaction_id=stored_commit.transaction_id,
        replay_fingerprint=stored_commit.replay_fingerprint,
        revalidation_fingerprint=fingerprint,
        native_commit_validation_status=native_validation.status,
        replay_validation_status=replay_validation.status,
        binding_validation_status=binding_report.status,
        entries=entries,
        entry_count=len(entries),
        errors=unique_errors,
        warnings=tuple(dict.fromkeys(warnings)),
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        **counts,
    )


def commit_csv_native_storage_revalidation_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    overwrite: bool = False,
    encoding: str = "utf-8",
) -> CSVNativeStorageRevalidationReport:
    """Persist a derived v3.4.1 CSV native-storage revalidation guard report."""
    report = prepare_csv_native_storage_revalidation(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    if not report.ok:
        return report
    result: TDSResult = directory.write_json(report.report_key, report.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return CSVNativeStorageRevalidationReport(
            csv_id=report.csv_id,
            status="invalid",
            adapter_version=report.adapter_version,
            report_key=report.report_key,
            source_native_commit_report_key=report.source_native_commit_report_key,
            source_replay_report_key=report.source_replay_report_key,
            source_commit_report_key=report.source_commit_report_key,
            mode=report.mode,
            transaction_id=report.transaction_id,
            replay_fingerprint=report.replay_fingerprint,
            revalidation_fingerprint=report.revalidation_fingerprint,
            native_commit_validation_status=report.native_commit_validation_status,
            replay_validation_status=report.replay_validation_status,
            binding_validation_status=report.binding_validation_status,
            entries=report.entries,
            entry_count=report.entry_count,
            verified_count=report.verified_count,
            source_drift_count=report.source_drift_count,
            storage_drift_count=report.storage_drift_count,
            proof_drift_count=report.proof_drift_count,
            missing_count=report.missing_count,
            skipped_optional_count=report.skipped_optional_count,
            rejected_count=report.rejected_count,
            errors=(f"native_storage_revalidation_report_write_failed:{result.code}:{result.message}",),
            warnings=report.warnings,
            tds_artifact_writes=0,
            native_storage_writes=False,
            native_c_engine_changed=False,
            native_csv_kernel_used=False,
            per_row_writes=False,
            per_cell_writes=False,
            native_storage_hot_path_touched=False,
            semantic_reasoning=False,
        )
    return CSVNativeStorageRevalidationReport(
        csv_id=report.csv_id,
        status=report.status,
        adapter_version=report.adapter_version,
        report_key=report.report_key,
        source_native_commit_report_key=report.source_native_commit_report_key,
        source_replay_report_key=report.source_replay_report_key,
        source_commit_report_key=report.source_commit_report_key,
        mode="revalidation_commit",
        transaction_id=report.transaction_id,
        replay_fingerprint=report.replay_fingerprint,
        revalidation_fingerprint=report.revalidation_fingerprint,
        native_commit_validation_status=report.native_commit_validation_status,
        replay_validation_status=report.replay_validation_status,
        binding_validation_status=report.binding_validation_status,
        entries=report.entries,
        entry_count=report.entry_count,
        verified_count=report.verified_count,
        source_drift_count=report.source_drift_count,
        storage_drift_count=report.storage_drift_count,
        proof_drift_count=report.proof_drift_count,
        missing_count=report.missing_count,
        skipped_optional_count=report.skipped_optional_count,
        rejected_count=report.rejected_count,
        warnings=report.warnings,
        tds_artifact_writes=1,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def load_csv_native_storage_revalidation_report(directory: TDSDirectory, csv_id: str) -> CSVNativeStorageRevalidationReport:
    """Load a persisted CSV native-storage revalidation guard report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_native_storage_revalidation_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV native storage revalidation report {key!r} is not a JSON object")
    return CSVNativeStorageRevalidationReport.from_mapping(value)


def validate_csv_native_storage_revalidation(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVNativeStorageRevalidationReport:
    """Validate a persisted revalidation guard against a fresh no-write snapshot."""
    try:
        stored = load_csv_native_storage_revalidation_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_native_storage_revalidation_report_key(csv_id)
        except Exception:
            report_key = ""
        return _invalid_native_revalidation_report(str(csv_id), f"native_storage_revalidation_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_native_storage_revalidation(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    errors: list[str] = list(fresh.errors)
    warnings: list[str] = list(dict.fromkeys(tuple(stored.warnings) + tuple(fresh.warnings)))
    if not fresh.ok:
        errors.extend(fresh.errors)
    if stored.status not in {"revalidated", "valid"}:
        errors.append(f"stored_revalidation_not_clean:{stored.status}")
    if stored.revalidation_fingerprint != fresh.revalidation_fingerprint:
        errors.append("revalidation_fingerprint_drift")
    if stored.transaction_id != fresh.transaction_id:
        errors.append("revalidation_transaction_drift")
    if stored.replay_fingerprint != fresh.replay_fingerprint:
        errors.append("revalidation_replay_fingerprint_drift")

    unique_errors = tuple(dict.fromkeys(errors))
    status = "valid" if not unique_errors else "drifted"
    return CSVNativeStorageRevalidationReport(
        csv_id=fresh.csv_id,
        status=status,
        adapter_version=fresh.adapter_version,
        report_key=stored.report_key,
        source_native_commit_report_key=fresh.source_native_commit_report_key,
        source_replay_report_key=fresh.source_replay_report_key,
        source_commit_report_key=fresh.source_commit_report_key,
        mode="validation",
        transaction_id=fresh.transaction_id,
        replay_fingerprint=fresh.replay_fingerprint,
        revalidation_fingerprint=fresh.revalidation_fingerprint,
        native_commit_validation_status=fresh.native_commit_validation_status,
        replay_validation_status=fresh.replay_validation_status,
        binding_validation_status=fresh.binding_validation_status,
        entries=fresh.entries,
        entry_count=fresh.entry_count,
        verified_count=fresh.verified_count,
        source_drift_count=fresh.source_drift_count,
        storage_drift_count=fresh.storage_drift_count,
        proof_drift_count=fresh.proof_drift_count,
        missing_count=fresh.missing_count,
        skipped_optional_count=fresh.skipped_optional_count,
        rejected_count=fresh.rejected_count,
        errors=unique_errors,
        warnings=tuple(dict.fromkeys(warnings)),
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def csv_native_storage_revalidation_summary(report: CSVNativeStorageRevalidationReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for a v3.4.1 revalidation guard."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "drifted": report.drifted,
        "mode": report.mode,
        "transaction_id": report.transaction_id,
        "replay_fingerprint": report.replay_fingerprint,
        "revalidation_fingerprint": report.revalidation_fingerprint,
        "native_commit_validation_status": report.native_commit_validation_status,
        "replay_validation_status": report.replay_validation_status,
        "binding_validation_status": report.binding_validation_status,
        "entry_count": report.entry_count,
        "verified_count": report.verified_count,
        "source_drift_count": report.source_drift_count,
        "storage_drift_count": report.storage_drift_count,
        "proof_drift_count": report.proof_drift_count,
        "missing_count": report.missing_count,
        "skipped_optional_count": report.skipped_optional_count,
        "rejected_count": report.rejected_count,
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_writes": report.native_storage_writes,
        "native_c_engine_changed": report.native_c_engine_changed,
        "native_csv_kernel_used": report.native_csv_kernel_used,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
    }

def csv_storage_bridge_commit_summary(report: CSVStorageBridgeCommitReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for a bridge-commit report."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "drifted": report.drifted,
        "mode": report.mode,
        "entry_count": report.entry_count,
        "required_count": report.required_count,
        "optional_count": report.optional_count,
        "committed_count": report.committed_count,
        "preflight_status": report.preflight_status,
        "scan_validation_status": report.scan_validation_status,
        "include_scan_artifacts": report.include_scan_artifacts,
        "require_scan_artifacts": report.require_scan_artifacts,
        "include_transaction_report": report.include_transaction_report,
        "require_transaction_report": report.require_transaction_report,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
    }

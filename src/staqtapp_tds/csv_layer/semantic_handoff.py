"""Read-only CSV suite closure and Semantic IR handoff contract.

This module closes the v3.4.x CSV evidence line without implementing Semantic
IR.  It validates the complete durable CSV/storage/Interpole/kernel/Browser
chain, emits immutable evidence references, and proves that preparing the
handoff does not mutate TDS artifacts or enter the native storage hot path.

The resulting report is an admission-readiness contract only.  A later,
explicit Semantic IR API must still decide how to consume the references.  No
schema, type, entity, row identity, cell meaning, or semantic conclusion is
inferred here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
from importlib.resources import files
import json
from typing import Any, Callable, Mapping

from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.version import __version__

from .browser_monitor import (
    CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT,
    CSVInterpoleBrowserMonitorSnapshot,
    csv_interpole_browser_monitor_display_contract,
    csv_interpole_browser_monitor_display_contract_fingerprint,
    csv_interpole_browser_monitor_snapshot_fingerprint,
    csv_interpole_monitor_icon_registry,
    prepare_csv_interpole_browser_monitor_snapshot,
    replay_csv_interpole_browser_monitor_snapshot,
    validate_csv_interpole_browser_monitor_snapshot,
    validate_csv_interpole_monitor_icon_registry,
)
from .exporter import export_original_csv
from .importer import load_csv_manifest
from .interpole import (
    validate_csv_interpole_determinant_vector,
    validate_csv_interpole_timeline,
    validate_csv_interpole_timeline_ring,
)
from .kernel import validate_csv_kernel_readiness_contract
from .manifest import validate_csv_id
from .native_row_anchor import validate_csv_native_row_anchor_kernel
from .native_scan import validate_csv_native_scan_kernel_prototype
from .performance_gates import validate_csv_kernel_performance_gate_report
from .security import validate_csv_artifact_security
from .storage_adapter import (
    validate_csv_native_storage_commit,
    validate_csv_native_storage_revalidation,
    validate_csv_storage_adapter_replay,
    validate_csv_storage_bridge_commit,
)
from .storage_bridge import validate_csv_storage_bridge_preflight
from .validator import validate_csv_artifacts


CSV_SEMANTIC_IR_HANDOFF_VERSION = "1.0"
CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT = 131_072

CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES: tuple[str, ...] = (
    "core_artifact_integrity",
    "original_byte_identity",
    "artifact_security_envelope",
    "storage_bridge_preflight",
    "storage_bridge_commit",
    "storage_adapter_replay",
    "native_storage_commit",
    "native_storage_revalidation",
    "interpole_timeline",
    "interpole_determinant_vector",
    "interpole_timeline_ring",
    "kernel_readiness_contract",
    "native_scan_parity",
    "native_row_anchor_parity",
    "kernel_performance_gates",
    "browser_monitor_snapshot",
    "browser_monitor_replay",
    "browser_monitor_display_contract",
    "browser_monitor_icon_registry",
)

CSV_SEMANTIC_IR_HANDOFF_CONTRACT_KEYS: tuple[str, ...] = (
    "csv_id",
    "status",
    "handoff_version",
    "suite_release_version",
    "mode",
    "raw_sha256",
    "row_count",
    "column_count",
    "evidence",
    "required_evidence_names",
    "artifact_chain_status",
    "storage_chain_status",
    "interpole_chain_status",
    "kernel_chain_status",
    "monitor_chain_status",
    "semantic_ir_candidate_ready",
    "explicit_opt_in_required",
    "evidence_references_only",
    "immutable_source_evidence_required",
    "payload_byte_limit",
    "directory_state_fingerprint_before",
    "directory_state_fingerprint_after",
    "directory_state_unchanged",
    "tds_artifact_writes",
    "source_artifact_mutation",
    "retroactive_csv_artifact_mutation",
    "native_storage_writes",
    "native_storage_hot_path_touched",
    "native_storage_locks_controlled",
    "native_c_storage_engine_changed",
    "interpole_mutation",
    "per_row_writes",
    "per_cell_writes",
    "semantic_reasoning",
    "semantic_conclusions",
    "schema_inference",
    "type_inference",
    "entity_inference",
    "row_identity_inference",
    "cell_meaning_inference",
    "formal_ir_committed",
    "warnings",
    "errors",
)


@dataclass(frozen=True, slots=True)
class CSVSemanticIRHandoffEvidence:
    """One immutable evidence reference in the CSV-to-IR handoff."""

    evidence_name: str
    evidence_kind: str
    status: str
    source_status: str
    source_key: str
    fingerprint: str
    required: bool = True
    read_only: bool = True
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.status == "ready"
            and not self.errors
            and self.required
            and self.read_only
            and _is_sha256(self.fingerprint)
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRHandoffEvidence":
        return cls(
            evidence_name=str(data.get("evidence_name", "")),
            evidence_kind=str(data.get("evidence_kind", "validation")),
            status=str(data.get("status", "blocked")),
            source_status=str(data.get("source_status", "unknown")),
            source_key=str(data.get("source_key", "")),
            fingerprint=str(data.get("fingerprint", "")),
            required=bool(data.get("required", True)),
            read_only=bool(data.get("read_only", True)),
            errors=tuple(str(v) for v in data.get("errors", ()) or ()),
            warnings=tuple(str(v) for v in data.get("warnings", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRHandoffReport:
    """Complete read-only CSV suite closure report for a future IR API."""

    csv_id: str
    status: str
    handoff_version: str
    suite_release_version: str
    mode: str
    closure_fingerprint: str
    raw_sha256: str
    row_count: int
    column_count: int
    evidence: tuple[CSVSemanticIRHandoffEvidence, ...]
    required_evidence_names: tuple[str, ...]
    artifact_chain_status: str
    storage_chain_status: str
    interpole_chain_status: str
    kernel_chain_status: str
    monitor_chain_status: str
    semantic_ir_candidate_ready: bool
    explicit_opt_in_required: bool = True
    evidence_references_only: bool = True
    immutable_source_evidence_required: bool = True
    directory_state_fingerprint_before: str = ""
    directory_state_fingerprint_after: str = ""
    directory_state_unchanged: bool = True
    payload_bytes: int = 0
    payload_byte_limit: int = CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT
    tds_artifact_writes: int = 0
    source_artifact_mutation: bool = False
    retroactive_csv_artifact_mutation: bool = False
    native_storage_writes: bool = False
    native_storage_hot_path_touched: bool = False
    native_storage_locks_controlled: bool = False
    native_c_storage_engine_changed: bool = False
    interpole_mutation: bool = False
    per_row_writes: bool = False
    per_cell_writes: bool = False
    semantic_reasoning: bool = False
    semantic_conclusions: bool = False
    schema_inference: bool = False
    type_inference: bool = False
    entity_inference: bool = False
    row_identity_inference: bool = False
    cell_meaning_inference: bool = False
    formal_ir_committed: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.status == "ir_handoff_ready"
            and self.handoff_version == CSV_SEMANTIC_IR_HANDOFF_VERSION
            and self.semantic_ir_candidate_ready
            and self.explicit_opt_in_required
            and self.evidence_references_only
            and self.immutable_source_evidence_required
            and self.required_evidence_names == CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES
            and tuple(item.evidence_name for item in self.evidence) == CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES
            and all(item.ok for item in self.evidence)
            and self.directory_state_unchanged
            and self.tds_artifact_writes == 0
            and not self.errors
            and not self.source_artifact_mutation
            and not self.retroactive_csv_artifact_mutation
            and not self.native_storage_writes
            and not self.native_storage_hot_path_touched
            and not self.native_storage_locks_controlled
            and not self.native_c_storage_engine_changed
            and not self.interpole_mutation
            and not self.per_row_writes
            and not self.per_cell_writes
            and not self.semantic_reasoning
            and not self.semantic_conclusions
            and not self.schema_inference
            and not self.type_inference
            and not self.entity_inference
            and not self.row_identity_inference
            and not self.cell_meaning_inference
            and not self.formal_ir_committed
            and _is_sha256(self.closure_fingerprint)
            and self.payload_bytes <= self.payload_byte_limit
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        data["required_evidence_names"] = list(self.required_evidence_names)
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["evidence_count"] = len(self.evidence)
        data["ready_evidence_count"] = sum(1 for item in self.evidence if item.ok)
        data["blocked_evidence_count"] = sum(1 for item in self.evidence if not item.ok)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRHandoffReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "ir_handoff_blocked")),
            handoff_version=str(data.get("handoff_version", CSV_SEMANTIC_IR_HANDOFF_VERSION)),
            suite_release_version=str(data.get("suite_release_version", "")),
            mode=str(data.get("mode", "semantic_ir_admission_readiness")),
            closure_fingerprint=str(data.get("closure_fingerprint", "")),
            raw_sha256=str(data.get("raw_sha256", "")),
            row_count=int(data.get("row_count", 0)),
            column_count=int(data.get("column_count", 0)),
            evidence=tuple(CSVSemanticIRHandoffEvidence.from_mapping(v) for v in data.get("evidence", ()) or ()),
            required_evidence_names=tuple(str(v) for v in data.get("required_evidence_names", ()) or ()),
            artifact_chain_status=str(data.get("artifact_chain_status", "blocked")),
            storage_chain_status=str(data.get("storage_chain_status", "blocked")),
            interpole_chain_status=str(data.get("interpole_chain_status", "blocked")),
            kernel_chain_status=str(data.get("kernel_chain_status", "blocked")),
            monitor_chain_status=str(data.get("monitor_chain_status", "blocked")),
            semantic_ir_candidate_ready=bool(data.get("semantic_ir_candidate_ready", False)),
            explicit_opt_in_required=bool(data.get("explicit_opt_in_required", True)),
            evidence_references_only=bool(data.get("evidence_references_only", True)),
            immutable_source_evidence_required=bool(data.get("immutable_source_evidence_required", True)),
            directory_state_fingerprint_before=str(data.get("directory_state_fingerprint_before", "")),
            directory_state_fingerprint_after=str(data.get("directory_state_fingerprint_after", "")),
            directory_state_unchanged=bool(data.get("directory_state_unchanged", False)),
            payload_bytes=int(data.get("payload_bytes", 0)),
            payload_byte_limit=int(data.get("payload_byte_limit", CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT)),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            source_artifact_mutation=bool(data.get("source_artifact_mutation", False)),
            retroactive_csv_artifact_mutation=bool(data.get("retroactive_csv_artifact_mutation", False)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            native_storage_locks_controlled=bool(data.get("native_storage_locks_controlled", False)),
            native_c_storage_engine_changed=bool(data.get("native_c_storage_engine_changed", False)),
            interpole_mutation=bool(data.get("interpole_mutation", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
            semantic_conclusions=bool(data.get("semantic_conclusions", False)),
            schema_inference=bool(data.get("schema_inference", False)),
            type_inference=bool(data.get("type_inference", False)),
            entity_inference=bool(data.get("entity_inference", False)),
            row_identity_inference=bool(data.get("row_identity_inference", False)),
            cell_meaning_inference=bool(data.get("cell_meaning_inference", False)),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
            warnings=tuple(str(v) for v in data.get("warnings", ()) or ()),
            errors=tuple(str(v) for v in data.get("errors", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRHandoffValidationReport:
    """Integrity validation for a serialized handoff report."""

    csv_id: str
    status: str
    handoff_version: str
    source_closure_fingerprint: str
    recomputed_closure_fingerprint: str
    source_payload_bytes: int
    recomputed_payload_bytes: int
    payload_byte_limit: int
    missing_contract_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_evidence_names: tuple[str, ...] = field(default_factory=tuple)
    unexpected_evidence_names: tuple[str, ...] = field(default_factory=tuple)
    duplicate_evidence_names: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    tds_artifact_writes: int = 0
    native_storage_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False
    semantic_conclusions: bool = False
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.status == "handoff_valid"
            and not self.errors
            and self.source_closure_fingerprint == self.recomputed_closure_fingerprint
            and self.source_payload_bytes == self.recomputed_payload_bytes
            and self.source_payload_bytes <= self.payload_byte_limit
            and not self.missing_contract_keys
            and not self.missing_evidence_names
            and not self.unexpected_evidence_names
            and not self.duplicate_evidence_names
            and self.tds_artifact_writes == 0
            and not self.native_storage_writes
            and not self.native_storage_hot_path_touched
            and not self.semantic_reasoning
            and not self.semantic_conclusions
            and not self.formal_ir_committed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name in (
            "missing_contract_keys",
            "missing_evidence_names",
            "unexpected_evidence_names",
            "duplicate_evidence_names",
            "errors",
            "warnings",
        ):
            data[name] = list(getattr(self, name))
        data["ok"] = self.ok
        return data


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: str) -> bool:
    if len(str(value)) != 64:
        return False
    try:
        int(str(value), 16)
    except ValueError:
        return False
    return str(value).lower() == str(value)


def _report_dict(report: Any) -> dict[str, Any]:
    if hasattr(report, "to_dict"):
        data = report.to_dict()
        if isinstance(data, dict):
            return data
    if isinstance(report, Mapping):
        return dict(report)
    return {"value": repr(report)}


def _report_fingerprint(report: Any) -> str:
    return _sha256_json(_report_dict(report))


def _report_errors(report: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in (getattr(report, "errors", ()) or ()))


def _report_warnings(report: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in (getattr(report, "warnings", ()) or ()))


def _report_ok(report: Any) -> bool:
    return bool(getattr(report, "ok", False))


def _evidence_from_report(
    evidence_name: str,
    evidence_kind: str,
    report: Any,
    *,
    source_key: str = "",
    fingerprint: str = "",
) -> CSVSemanticIRHandoffEvidence:
    errors = _report_errors(report)
    warnings = _report_warnings(report)
    ready = _report_ok(report)
    stable_fingerprint = str(fingerprint or _report_fingerprint(report))
    return CSVSemanticIRHandoffEvidence(
        evidence_name=evidence_name,
        evidence_kind=evidence_kind,
        status="ready" if ready else "blocked",
        source_status=str(getattr(report, "status", "valid" if ready else "blocked")),
        source_key=str(source_key),
        fingerprint=stable_fingerprint,
        required=True,
        read_only=True,
        errors=errors if not ready else (),
        warnings=warnings,
    )


def _evidence_from_call(
    evidence_name: str,
    evidence_kind: str,
    call: Callable[[], Any],
    *,
    source_key: Callable[[Any], str] | None = None,
    fingerprint: Callable[[Any], str] | None = None,
) -> tuple[CSVSemanticIRHandoffEvidence, Any | None]:
    try:
        report = call()
    except Exception as exc:
        error = f"{evidence_name}_unreadable:{type(exc).__name__}:{exc}"
        evidence = CSVSemanticIRHandoffEvidence(
            evidence_name=evidence_name,
            evidence_kind=evidence_kind,
            status="blocked",
            source_status="unreadable",
            source_key="",
            fingerprint=_sha256_json({"evidence_name": evidence_name, "error": error}),
            errors=(error,),
        )
        return evidence, None
    try:
        key = source_key(report) if source_key is not None else str(getattr(report, "report_key", ""))
    except Exception:
        key = ""
    try:
        fp = fingerprint(report) if fingerprint is not None else ""
    except Exception:
        fp = ""
    return _evidence_from_report(evidence_name, evidence_kind, report, source_key=key, fingerprint=fp), report


def _value_fingerprint(value: Any) -> str:
    if isinstance(value, bytes):
        payload = b"bytes\0" + value
    elif isinstance(value, bytearray):
        payload = b"bytearray\0" + bytes(value)
    elif isinstance(value, memoryview):
        payload = b"memoryview\0" + value.tobytes()
    elif isinstance(value, str):
        payload = b"str\0" + value.encode("utf-8")
    else:
        try:
            payload = b"json\0" + _canonical_json_bytes(value)
        except Exception:
            payload = b"repr\0" + repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _directory_state_fingerprint(directory: TDSDirectory, csv_id: str) -> str:
    records: list[dict[str, str]] = []
    entries = getattr(directory, "_entries", None)
    if entries is None:
        return _sha256_json(records)
    try:
        keys = tuple(sorted(str(key) for key in entries.keys() if str(csv_id) in str(key)))
    except Exception:
        keys = ()
    for key in keys:
        try:
            value = directory.read_value(key)
            value_fingerprint = _value_fingerprint(value)
        except Exception as exc:
            value_fingerprint = _sha256_json({"error": type(exc).__name__, "message": str(exc)})
        records.append({"key": key, "value_fingerprint": value_fingerprint})
    return _sha256_json(records)


def _handoff_projection(report: CSVSemanticIRHandoffReport | Mapping[str, Any]) -> dict[str, Any]:
    data = report.to_dict() if isinstance(report, CSVSemanticIRHandoffReport) else dict(report)
    return {key: data.get(key) for key in CSV_SEMANTIC_IR_HANDOFF_CONTRACT_KEYS}


def csv_semantic_ir_handoff_fingerprint(report: CSVSemanticIRHandoffReport | Mapping[str, Any]) -> str:
    """Fingerprint the stable closure projection, excluding integrity metadata."""
    return _sha256_json(_handoff_projection(report))


def _handoff_payload_bytes(report: CSVSemanticIRHandoffReport | Mapping[str, Any]) -> int:
    return len(_canonical_json_bytes(_handoff_projection(report)))


def _finalize_handoff_integrity(report: CSVSemanticIRHandoffReport) -> CSVSemanticIRHandoffReport:
    fingerprint = csv_semantic_ir_handoff_fingerprint(report)
    payload_bytes = _handoff_payload_bytes(report)
    return replace(report, closure_fingerprint=fingerprint, payload_bytes=payload_bytes)


def _chain_status(evidence: tuple[CSVSemanticIRHandoffEvidence, ...], names: tuple[str, ...]) -> str:
    by_name = {item.evidence_name: item for item in evidence}
    return "ready" if all(name in by_name and by_name[name].ok for name in names) else "blocked"


def _blocked_handoff(
    csv_id: str,
    error: str,
    *,
    payload_byte_limit: int,
    state_before: str,
    state_after: str,
) -> CSVSemanticIRHandoffReport:
    report = CSVSemanticIRHandoffReport(
        csv_id=str(csv_id),
        status="ir_handoff_blocked",
        handoff_version=CSV_SEMANTIC_IR_HANDOFF_VERSION,
        suite_release_version=__version__,
        mode="semantic_ir_admission_readiness",
        closure_fingerprint="",
        raw_sha256="",
        row_count=0,
        column_count=0,
        evidence=(),
        required_evidence_names=CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES,
        artifact_chain_status="blocked",
        storage_chain_status="blocked",
        interpole_chain_status="blocked",
        kernel_chain_status="blocked",
        monitor_chain_status="blocked",
        semantic_ir_candidate_ready=False,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=(state_before == state_after),
        payload_byte_limit=max(1, int(payload_byte_limit)),
        tds_artifact_writes=0 if state_before == state_after else 1,
        source_artifact_mutation=(state_before != state_after),
        errors=(str(error),),
    )
    return _finalize_handoff_integrity(report)


def _load_packaged_monitor_svg_payloads() -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    root = files("staqtapp_tds.admin")
    for name in csv_interpole_monitor_icon_registry():
        payloads[name] = root.joinpath("static", "icons", f"{name}.svg").read_bytes()
    return payloads


def prepare_csv_semantic_ir_handoff(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
    source_monitor_snapshot: CSVInterpoleBrowserMonitorSnapshot | Mapping[str, Any] | None = None,
    payload_byte_limit: int = CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT,
) -> CSVSemanticIRHandoffReport:
    """Validate the complete CSV suite and emit a read-only IR handoff report.

    The function invokes validation, load, snapshot, and replay APIs only.  It
    does not call any CSV commit API and verifies the relevant TDS directory
    state before and after the full closure pass.
    """
    effective_limit = max(1, min(int(payload_byte_limit), CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT))
    state_before = _directory_state_fingerprint(directory, str(csv_id))
    try:
        safe_id = validate_csv_id(csv_id)
    except Exception as exc:
        state_after = _directory_state_fingerprint(directory, str(csv_id))
        return _blocked_handoff(
            str(csv_id),
            f"csv_id_unsafe:{type(exc).__name__}:{exc}",
            payload_byte_limit=effective_limit,
            state_before=state_before,
            state_after=state_after,
        )

    evidence: list[CSVSemanticIRHandoffEvidence] = []
    aggregate_errors: list[str] = []
    aggregate_warnings: list[str] = []

    manifest = None
    raw_sha256 = ""
    row_count = 0
    column_count = 0
    try:
        manifest = load_csv_manifest(directory, safe_id)
        raw_sha256 = str(manifest.raw_sha256)
        row_count = int(manifest.row_count)
        column_count = int(manifest.column_count)
        manifest_key = str(manifest.artifact_keys.get("manifest", ""))
        raw_key = str(manifest.artifact_keys.get("raw", ""))
    except Exception:
        manifest_key = ""
        raw_key = ""

    item, artifact_report = _evidence_from_call(
        "core_artifact_integrity",
        "validation",
        lambda: validate_csv_artifacts(directory, safe_id),
        source_key=lambda _: manifest_key,
    )
    evidence.append(item)

    try:
        if manifest is None:
            manifest = load_csv_manifest(directory, safe_id)
            raw_sha256 = str(manifest.raw_sha256)
            row_count = int(manifest.row_count)
            column_count = int(manifest.column_count)
            manifest_key = str(manifest.artifact_keys.get("manifest", ""))
            raw_key = str(manifest.artifact_keys.get("raw", ""))
        raw_text = export_original_csv(directory, safe_id)
        exported_sha256 = hashlib.sha256(raw_text.encode(manifest.encoding)).hexdigest()
        original_ok = exported_sha256 == manifest.raw_sha256
        original_error = () if original_ok else ("original_byte_identity_mismatch",)
        original_evidence = CSVSemanticIRHandoffEvidence(
            evidence_name="original_byte_identity",
            evidence_kind="source_identity",
            status="ready" if original_ok else "blocked",
            source_status="byte_equivalent" if original_ok else "drifted",
            source_key=raw_key,
            fingerprint=exported_sha256,
            errors=original_error,
        )
    except Exception as exc:
        error = f"original_byte_identity_unreadable:{type(exc).__name__}:{exc}"
        original_evidence = CSVSemanticIRHandoffEvidence(
            evidence_name="original_byte_identity",
            evidence_kind="source_identity",
            status="blocked",
            source_status="unreadable",
            source_key=raw_key,
            fingerprint=_sha256_json({"evidence_name": "original_byte_identity", "error": error}),
            errors=(error,),
        )
    evidence.append(original_evidence)

    validation_calls: tuple[tuple[str, str, Callable[[], Any], Callable[[Any], str] | None, Callable[[Any], str] | None], ...] = (
        (
            "artifact_security_envelope",
            "security",
            lambda: validate_csv_artifact_security(directory, safe_id),
            lambda _: manifest_key,
            None,
        ),
        (
            "storage_bridge_preflight",
            "storage_validation",
            lambda: validate_csv_storage_bridge_preflight(directory, safe_id, chunk_size=chunk_size),
            lambda _: manifest_key,
            None,
        ),
        (
            "storage_bridge_commit",
            "stored_report",
            lambda: validate_csv_storage_bridge_commit(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            None,
        ),
        (
            "storage_adapter_replay",
            "stored_report",
            lambda: validate_csv_storage_adapter_replay(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.replay_fingerprint),
        ),
        (
            "native_storage_commit",
            "stored_report",
            lambda: validate_csv_native_storage_commit(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            None,
        ),
        (
            "native_storage_revalidation",
            "stored_report",
            lambda: validate_csv_native_storage_revalidation(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.revalidation_fingerprint),
        ),
        (
            "interpole_timeline",
            "interpole_evidence",
            lambda: validate_csv_interpole_timeline(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.timeline.timeline_fingerprint),
        ),
        (
            "interpole_determinant_vector",
            "interpole_evidence",
            lambda: validate_csv_interpole_determinant_vector(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.vector.vector_fingerprint),
        ),
        (
            "interpole_timeline_ring",
            "interpole_evidence",
            lambda: validate_csv_interpole_timeline_ring(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.ring.ring_fingerprint),
        ),
        (
            "kernel_readiness_contract",
            "kernel_contract",
            lambda: validate_csv_kernel_readiness_contract(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.contract_fingerprint),
        ),
        (
            "native_scan_parity",
            "kernel_evidence",
            lambda: validate_csv_native_scan_kernel_prototype(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.scan_fingerprint),
        ),
        (
            "native_row_anchor_parity",
            "kernel_evidence",
            lambda: validate_csv_native_row_anchor_kernel(directory, safe_id, chunk_size=chunk_size),
            lambda report: str(report.report_key),
            lambda report: str(report.anchor_fingerprint),
        ),
        (
            "kernel_performance_gates",
            "kernel_evidence",
            lambda: validate_csv_kernel_performance_gate_report(directory, safe_id),
            lambda report: str(report.report_key),
            lambda report: str(report.performance_gate_fingerprint),
        ),
    )

    for evidence_name, evidence_kind, call, key_fn, fp_fn in validation_calls:
        item, _ = _evidence_from_call(
            evidence_name,
            evidence_kind,
            call,
            source_key=key_fn,
            fingerprint=fp_fn,
        )
        evidence.append(item)

    try:
        fresh_monitor = prepare_csv_interpole_browser_monitor_snapshot(directory, safe_id, chunk_size=chunk_size)
        monitor_validation = validate_csv_interpole_browser_monitor_snapshot(fresh_monitor)
        monitor_item = _evidence_from_report(
            "browser_monitor_snapshot",
            "browser_projection",
            monitor_validation,
            source_key="browser_monitor:read_only_snapshot",
            fingerprint=csv_interpole_browser_monitor_snapshot_fingerprint(fresh_monitor),
        )
    except Exception as exc:
        error = f"browser_monitor_snapshot_unreadable:{type(exc).__name__}:{exc}"
        fresh_monitor = None
        monitor_item = CSVSemanticIRHandoffEvidence(
            evidence_name="browser_monitor_snapshot",
            evidence_kind="browser_projection",
            status="blocked",
            source_status="unreadable",
            source_key="browser_monitor:read_only_snapshot",
            fingerprint=_sha256_json({"evidence_name": "browser_monitor_snapshot", "error": error}),
            errors=(error,),
        )
    evidence.append(monitor_item)

    try:
        replay_source = source_monitor_snapshot if source_monitor_snapshot is not None else fresh_monitor
        if replay_source is None:
            raise ValueError("monitor_snapshot_unavailable")
        replay_report = replay_csv_interpole_browser_monitor_snapshot(
            directory,
            safe_id,
            replay_source,
            chunk_size=chunk_size,
            payload_byte_limit=CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT,
        )
        replay_item = _evidence_from_report(
            "browser_monitor_replay",
            "browser_replay",
            replay_report,
            source_key="browser_monitor:canonical_replay",
            fingerprint=_report_fingerprint(replay_report),
        )
    except Exception as exc:
        error = f"browser_monitor_replay_unreadable:{type(exc).__name__}:{exc}"
        replay_item = CSVSemanticIRHandoffEvidence(
            evidence_name="browser_monitor_replay",
            evidence_kind="browser_replay",
            status="blocked",
            source_status="unreadable",
            source_key="browser_monitor:canonical_replay",
            fingerprint=_sha256_json({"evidence_name": "browser_monitor_replay", "error": error}),
            errors=(error,),
        )
    evidence.append(replay_item)

    try:
        display_contract = csv_interpole_browser_monitor_display_contract()
        display_fingerprint = csv_interpole_browser_monitor_display_contract_fingerprint()
        display_ok = bool(display_contract) and _is_sha256(display_fingerprint)
        display_item = CSVSemanticIRHandoffEvidence(
            evidence_name="browser_monitor_display_contract",
            evidence_kind="browser_contract",
            status="ready" if display_ok else "blocked",
            source_status="valid" if display_ok else "invalid",
            source_key="browser_monitor:display_contract",
            fingerprint=display_fingerprint or _sha256_json(display_contract),
            errors=() if display_ok else ("browser_monitor_display_contract_invalid",),
        )
    except Exception as exc:
        error = f"browser_monitor_display_contract_unreadable:{type(exc).__name__}:{exc}"
        display_item = CSVSemanticIRHandoffEvidence(
            evidence_name="browser_monitor_display_contract",
            evidence_kind="browser_contract",
            status="blocked",
            source_status="unreadable",
            source_key="browser_monitor:display_contract",
            fingerprint=_sha256_json({"evidence_name": "browser_monitor_display_contract", "error": error}),
            errors=(error,),
        )
    evidence.append(display_item)

    try:
        registry = csv_interpole_monitor_icon_registry()
        icon_payloads = _load_packaged_monitor_svg_payloads()
        icon_report = validate_csv_interpole_monitor_icon_registry(registry, svg_payloads=icon_payloads)
        icon_item = _evidence_from_report(
            "browser_monitor_icon_registry",
            "packaged_asset_registry",
            icon_report,
            source_key="staqtapp_tds.admin:static/icons",
            fingerprint=str(icon_report.registry_fingerprint),
        )
    except Exception as exc:
        error = f"browser_monitor_icon_registry_unreadable:{type(exc).__name__}:{exc}"
        icon_item = CSVSemanticIRHandoffEvidence(
            evidence_name="browser_monitor_icon_registry",
            evidence_kind="packaged_asset_registry",
            status="blocked",
            source_status="unreadable",
            source_key="staqtapp_tds.admin:static/icons",
            fingerprint=_sha256_json({"evidence_name": "browser_monitor_icon_registry", "error": error}),
            errors=(error,),
        )
    evidence.append(icon_item)

    evidence_tuple = tuple(evidence)
    for item in evidence_tuple:
        aggregate_errors.extend(f"{item.evidence_name}:{error}" for error in item.errors)
        aggregate_warnings.extend(f"{item.evidence_name}:{warning}" for warning in item.warnings)

    state_after = _directory_state_fingerprint(directory, safe_id)
    state_unchanged = state_before == state_after
    if not state_unchanged:
        aggregate_errors.append("csv_handoff_mutated_tds_directory_state")

    artifact_names = (
        "core_artifact_integrity",
        "original_byte_identity",
        "artifact_security_envelope",
    )
    storage_names = (
        "storage_bridge_preflight",
        "storage_bridge_commit",
        "storage_adapter_replay",
        "native_storage_commit",
        "native_storage_revalidation",
    )
    interpole_names = (
        "interpole_timeline",
        "interpole_determinant_vector",
        "interpole_timeline_ring",
    )
    kernel_names = (
        "kernel_readiness_contract",
        "native_scan_parity",
        "native_row_anchor_parity",
        "kernel_performance_gates",
    )
    monitor_names = (
        "browser_monitor_snapshot",
        "browser_monitor_replay",
        "browser_monitor_display_contract",
        "browser_monitor_icon_registry",
    )

    artifact_status = _chain_status(evidence_tuple, artifact_names)
    storage_status = _chain_status(evidence_tuple, storage_names)
    interpole_status = _chain_status(evidence_tuple, interpole_names)
    kernel_status = _chain_status(evidence_tuple, kernel_names)
    monitor_status = _chain_status(evidence_tuple, monitor_names)
    candidate_ready = (
        tuple(item.evidence_name for item in evidence_tuple) == CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES
        and all(item.ok for item in evidence_tuple)
        and state_unchanged
        and not aggregate_errors
        and all(status == "ready" for status in (artifact_status, storage_status, interpole_status, kernel_status, monitor_status))
    )

    report = CSVSemanticIRHandoffReport(
        csv_id=safe_id,
        status="ir_handoff_ready" if candidate_ready else "ir_handoff_blocked",
        handoff_version=CSV_SEMANTIC_IR_HANDOFF_VERSION,
        suite_release_version=__version__,
        mode="semantic_ir_admission_readiness",
        closure_fingerprint="",
        raw_sha256=raw_sha256,
        row_count=row_count,
        column_count=column_count,
        evidence=evidence_tuple,
        required_evidence_names=CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES,
        artifact_chain_status=artifact_status,
        storage_chain_status=storage_status,
        interpole_chain_status=interpole_status,
        kernel_chain_status=kernel_status,
        monitor_chain_status=monitor_status,
        semantic_ir_candidate_ready=candidate_ready,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=state_unchanged,
        payload_byte_limit=effective_limit,
        tds_artifact_writes=0 if state_unchanged else 1,
        source_artifact_mutation=not state_unchanged,
        warnings=tuple(dict.fromkeys(aggregate_warnings)),
        errors=tuple(dict.fromkeys(aggregate_errors)),
    )
    report = _finalize_handoff_integrity(report)
    if report.payload_bytes > effective_limit:
        report = replace(
            report,
            status="ir_handoff_blocked",
            semantic_ir_candidate_ready=False,
            errors=tuple(dict.fromkeys(report.errors + (f"handoff_payload_too_large:{report.payload_bytes}>{effective_limit}",))),
        )
        report = _finalize_handoff_integrity(report)
    return report


def validate_csv_semantic_ir_handoff(
    report: CSVSemanticIRHandoffReport | Mapping[str, Any],
) -> CSVSemanticIRHandoffValidationReport:
    """Validate a serialized handoff contract without reading or writing TDS."""
    try:
        raw_mapping = report.to_dict() if isinstance(report, CSVSemanticIRHandoffReport) else dict(report)
        obj = report if isinstance(report, CSVSemanticIRHandoffReport) else CSVSemanticIRHandoffReport.from_mapping(raw_mapping)
        recomputed_fingerprint = csv_semantic_ir_handoff_fingerprint(obj)
        recomputed_payload_bytes = _handoff_payload_bytes(obj)
    except Exception as exc:
        error = f"handoff_unreadable:{type(exc).__name__}:{exc}"
        return CSVSemanticIRHandoffValidationReport(
            csv_id="",
            status="handoff_blocked",
            handoff_version=CSV_SEMANTIC_IR_HANDOFF_VERSION,
            source_closure_fingerprint="",
            recomputed_closure_fingerprint="",
            source_payload_bytes=0,
            recomputed_payload_bytes=0,
            payload_byte_limit=CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT,
            errors=(error,),
        )

    errors: list[str] = []
    warnings: list[str] = []
    missing_contract_keys = tuple(key for key in CSV_SEMANTIC_IR_HANDOFF_CONTRACT_KEYS if key not in raw_mapping)
    errors.extend(f"handoff_contract_missing:{key}" for key in missing_contract_keys)
    for key in ("closure_fingerprint", "payload_bytes", "payload_byte_limit"):
        if key not in raw_mapping:
            errors.append(f"handoff_integrity_field_missing:{key}")

    names = tuple(item.evidence_name for item in obj.evidence)
    expected = set(CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES)
    actual = set(names)
    missing_evidence = tuple(sorted(expected - actual))
    unexpected_evidence = tuple(sorted(actual - expected))
    duplicate_evidence = tuple(sorted(name for name in actual if names.count(name) > 1))
    errors.extend(f"required_evidence_missing:{name}" for name in missing_evidence)
    errors.extend(f"unexpected_evidence:{name}" for name in unexpected_evidence)
    errors.extend(f"duplicate_evidence:{name}" for name in duplicate_evidence)
    if names != CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES:
        errors.append("evidence_order_mismatch")

    if obj.handoff_version != CSV_SEMANTIC_IR_HANDOFF_VERSION:
        errors.append(f"handoff_version_mismatch:{obj.handoff_version}")
    if obj.suite_release_version != __version__:
        errors.append(f"suite_release_version_mismatch:{obj.suite_release_version}")
    if obj.mode != "semantic_ir_admission_readiness":
        errors.append(f"handoff_mode_mismatch:{obj.mode}")
    if obj.closure_fingerprint != recomputed_fingerprint:
        errors.append("closure_fingerprint_mismatch")
    if obj.payload_bytes != recomputed_payload_bytes:
        errors.append(f"payload_size_mismatch:{obj.payload_bytes}!={recomputed_payload_bytes}")
    if obj.payload_bytes > obj.payload_byte_limit:
        errors.append(f"handoff_payload_too_large:{obj.payload_bytes}>{obj.payload_byte_limit}")
    if obj.payload_byte_limit > CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT:
        errors.append(f"handoff_payload_limit_unbounded:{obj.payload_byte_limit}")
    if not _is_sha256(obj.raw_sha256):
        errors.append("raw_sha256_invalid")
    if not _is_sha256(obj.directory_state_fingerprint_before) or not _is_sha256(obj.directory_state_fingerprint_after):
        errors.append("directory_state_fingerprint_invalid")
    if obj.directory_state_fingerprint_before != obj.directory_state_fingerprint_after or not obj.directory_state_unchanged:
        errors.append("directory_state_changed")
    if obj.status not in {"ir_handoff_ready", "ir_handoff_blocked"}:
        errors.append(f"handoff_status_invalid:{obj.status}")
    if obj.status == "ir_handoff_ready" and not obj.semantic_ir_candidate_ready:
        errors.append("candidate_readiness_false")
    if obj.status == "ir_handoff_ready" and not all(item.ok for item in obj.evidence):
        errors.append("evidence_not_ready")
    if obj.status == "ir_handoff_ready" and not obj.ok:
        errors.append("handoff_not_ready")
    for item in obj.evidence:
        if not item.required:
            errors.append(f"evidence_not_required:{item.evidence_name}")
        if not item.read_only:
            errors.append(f"evidence_not_read_only:{item.evidence_name}")
        if not _is_sha256(item.fingerprint):
            errors.append(f"evidence_fingerprint_invalid:{item.evidence_name}")
        if obj.status == "ir_handoff_ready" and item.status != "ready":
            errors.append(f"evidence_status_not_ready:{item.evidence_name}")
        if obj.status == "ir_handoff_ready" and not item.source_key:
            errors.append(f"evidence_source_key_empty:{item.evidence_name}")
    if not obj.explicit_opt_in_required:
        errors.append("explicit_opt_in_not_required")
    if not obj.evidence_references_only:
        errors.append("evidence_reference_boundary_disabled")
    if not obj.immutable_source_evidence_required:
        errors.append("immutable_source_boundary_disabled")

    evidence_by_name = {item.evidence_name: item for item in obj.evidence}
    chain_specs = (
        ("artifact_chain_status", ("core_artifact_integrity", "original_byte_identity", "artifact_security_envelope")),
        ("storage_chain_status", ("storage_bridge_preflight", "storage_bridge_commit", "storage_adapter_replay", "native_storage_commit", "native_storage_revalidation")),
        ("interpole_chain_status", ("interpole_timeline", "interpole_determinant_vector", "interpole_timeline_ring")),
        ("kernel_chain_status", ("kernel_readiness_contract", "native_scan_parity", "native_row_anchor_parity", "kernel_performance_gates")),
        ("monitor_chain_status", ("browser_monitor_snapshot", "browser_monitor_replay", "browser_monitor_display_contract", "browser_monitor_icon_registry")),
    )
    for field_name, chain_names in chain_specs:
        expected_status = "ready" if all(name in evidence_by_name and evidence_by_name[name].ok for name in chain_names) else "blocked"
        if getattr(obj, field_name) != expected_status:
            errors.append(f"chain_status_mismatch:{field_name}")

    forbidden_true_fields = (
        "source_artifact_mutation",
        "retroactive_csv_artifact_mutation",
        "native_storage_writes",
        "native_storage_hot_path_touched",
        "native_storage_locks_controlled",
        "native_c_storage_engine_changed",
        "interpole_mutation",
        "per_row_writes",
        "per_cell_writes",
        "semantic_reasoning",
        "semantic_conclusions",
        "schema_inference",
        "type_inference",
        "entity_inference",
        "row_identity_inference",
        "cell_meaning_inference",
        "formal_ir_committed",
    )
    for field_name in forbidden_true_fields:
        if bool(getattr(obj, field_name)):
            errors.append(f"forbidden_handoff_field_true:{field_name}")
    if obj.tds_artifact_writes != 0:
        errors.append(f"tds_artifact_writes_nonzero:{obj.tds_artifact_writes}")
    if obj.status == "ir_handoff_ready" and obj.errors:
        errors.append("ready_handoff_contains_errors")

    if "evidence_count" in raw_mapping and int(raw_mapping.get("evidence_count", -1)) != len(obj.evidence):
        errors.append("evidence_count_mismatch")
    if "ready_evidence_count" in raw_mapping and int(raw_mapping.get("ready_evidence_count", -1)) != sum(1 for item in obj.evidence if item.ok):
        errors.append("ready_evidence_count_mismatch")
    if "blocked_evidence_count" in raw_mapping and int(raw_mapping.get("blocked_evidence_count", -1)) != sum(1 for item in obj.evidence if not item.ok):
        errors.append("blocked_evidence_count_mismatch")

    return CSVSemanticIRHandoffValidationReport(
        csv_id=obj.csv_id,
        status="handoff_valid" if not errors else "handoff_blocked",
        handoff_version=obj.handoff_version,
        source_closure_fingerprint=obj.closure_fingerprint,
        recomputed_closure_fingerprint=recomputed_fingerprint,
        source_payload_bytes=obj.payload_bytes,
        recomputed_payload_bytes=recomputed_payload_bytes,
        payload_byte_limit=obj.payload_byte_limit,
        missing_contract_keys=missing_contract_keys,
        missing_evidence_names=missing_evidence,
        unexpected_evidence_names=unexpected_evidence,
        duplicate_evidence_names=duplicate_evidence,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def csv_semantic_ir_handoff_summary(report: CSVSemanticIRHandoffReport) -> dict[str, Any]:
    """Return the compact JSON-safe handoff summary for Browser or tooling."""
    return report.to_dict()

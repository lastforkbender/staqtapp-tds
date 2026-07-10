"""CSV kernel performance-gate contract for v3.4.8.

The v3.4.8 lane turns the v3.4.6/v3.4.7 native CSV kernel evidence into
admission gates for later benchmark and browser-monitor work.  These gates are
intentionally deterministic: they validate fresh parity evidence, compact report
shape, bounded linear work shape, fallback safety, and isolation from native
storage/semantic paths without depending on noisy wall-clock timing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Mapping

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import TDSDirectory

from .manifest import validate_csv_id
from .native_row_anchor import (
    CSVNativeRowAnchorKernelReport,
    csv_native_row_anchor_kernel_report_key,
    load_csv_native_row_anchor_kernel_report,
    validate_csv_native_row_anchor_kernel,
)
from .native_scan import (
    CSVNativeScanKernelReport,
    csv_native_scan_kernel_report_key,
    load_csv_native_scan_kernel_prototype_report,
    validate_csv_native_scan_kernel_prototype,
)

CSV_KERNEL_PERFORMANCE_GATE_VERSION = "1.0"


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def csv_kernel_performance_gate_report_key(csv_id: str) -> str:
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__kernel_performance_gate_report.json"


def _dict_from_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(k): v for k, v in (value or {}).items()}


def _string_dict_from_mapping(value: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (value or {}).items()}


@dataclass(frozen=True, slots=True)
class CSVKernelPerformanceGate:
    """One deterministic performance-admission gate.

    A gate describes bounded work shape or isolation behavior.  It deliberately
    avoids runtime timing as the pass/fail signal so CI variability cannot
    convert a good kernel into a false regression.
    """

    gate_index: int
    gate_name: str
    category: str
    status: str
    required: bool = True
    metric_name: str = ""
    metric_value: Any = None
    metric_limit: Any = None
    comparator: str = ""
    evidence_hashes: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
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
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        if self.required and self.status not in {"passed", "guarded", "declared"}:
            return False
        return (
            not self.errors
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
            and not self.formal_ir_committed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_hashes"] = dict(self.evidence_hashes)
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVKernelPerformanceGate":
        return cls(
            gate_index=int(data.get("gate_index", 0)),
            gate_name=str(data.get("gate_name", "")),
            category=str(data.get("category", "performance")),
            status=str(data.get("status", "blocked")),
            required=bool(data.get("required", True)),
            metric_name=str(data.get("metric_name", "")),
            metric_value=data.get("metric_value"),
            metric_limit=data.get("metric_limit"),
            comparator=str(data.get("comparator", "")),
            evidence_hashes=_string_dict_from_mapping(data.get("evidence_hashes", {}) or {}),
            warnings=tuple(str(v) for v in data.get("warnings", ()) or ()),
            errors=tuple(str(v) for v in data.get("errors", ()) or ()),
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
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVKernelPerformanceGateReport:
    """Deterministic performance-gate evidence for native CSV kernels."""

    csv_id: str
    status: str
    kernel_performance_gate_version: str
    report_key: str
    mode: str
    source_native_row_anchor_report_key: str
    source_native_scan_report_key: str
    source_anchor_fingerprint: str
    source_reference_anchor_fingerprint: str
    source_scan_fingerprint: str
    source_reference_scan_fingerprint: str
    performance_gate_fingerprint: str
    raw_sha256: str
    row_anchor_validation_status: str
    native_scan_validation_status: str
    scan_parity_status: str
    row_anchor_parity_status: str
    gate_count: int
    required_count: int
    passed_count: int
    blocked_count: int
    warning_count: int
    gates: tuple[CSVKernelPerformanceGate, ...]
    raw_size: int
    row_count: int
    chunk_size: int | None
    chunk_count: int
    max_record_span: int
    estimated_linear_scan_work_units: int
    estimated_anchor_digest_work_units: int
    max_linear_scan_work_units: int
    max_anchor_digest_work_units: int
    max_work_amplification: int
    estimated_gate_json_bytes: int
    max_report_json_bytes: int
    native_backend_available: bool
    native_backend_used: bool
    requested_native: bool
    force_native: bool
    python_reference_fallback_available: bool
    python_reference_fallback_used: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    tds_artifact_writes: int = 0
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
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.status in {"performance_gates_ready", "performance_gates_committed", "valid"}
            and not self.errors
            and self.gate_count > 0
            and self.passed_count == self.required_count
            and self.blocked_count == 0
            and self.source_anchor_fingerprint != ""
            and self.source_reference_anchor_fingerprint != ""
            and self.source_anchor_fingerprint == self.source_reference_anchor_fingerprint
            and self.source_scan_fingerprint != ""
            and self.source_reference_scan_fingerprint != ""
            and self.source_scan_fingerprint == self.source_reference_scan_fingerprint
            and self.performance_gate_fingerprint != ""
            and self.row_anchor_validation_status == "valid"
            and self.native_scan_validation_status == "valid"
            and self.scan_parity_status == "valid"
            and self.row_anchor_parity_status == "valid"
            and self.estimated_linear_scan_work_units <= self.max_linear_scan_work_units
            and self.estimated_anchor_digest_work_units <= self.max_anchor_digest_work_units
            and self.estimated_gate_json_bytes <= self.max_report_json_bytes
            and self.python_reference_fallback_available
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
            and not self.formal_ir_committed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gates"] = [gate.to_dict() for gate in self.gates]
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVKernelPerformanceGateReport":
        gates = tuple(CSVKernelPerformanceGate.from_mapping(v) for v in data.get("gates", ()) or ())
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            kernel_performance_gate_version=str(data.get("kernel_performance_gate_version", CSV_KERNEL_PERFORMANCE_GATE_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "")),
            source_native_row_anchor_report_key=str(data.get("source_native_row_anchor_report_key", "")),
            source_native_scan_report_key=str(data.get("source_native_scan_report_key", "")),
            source_anchor_fingerprint=str(data.get("source_anchor_fingerprint", "")),
            source_reference_anchor_fingerprint=str(data.get("source_reference_anchor_fingerprint", "")),
            source_scan_fingerprint=str(data.get("source_scan_fingerprint", "")),
            source_reference_scan_fingerprint=str(data.get("source_reference_scan_fingerprint", "")),
            performance_gate_fingerprint=str(data.get("performance_gate_fingerprint", "")),
            raw_sha256=str(data.get("raw_sha256", "")),
            row_anchor_validation_status=str(data.get("row_anchor_validation_status", "not_checked")),
            native_scan_validation_status=str(data.get("native_scan_validation_status", "not_checked")),
            scan_parity_status=str(data.get("scan_parity_status", "not_checked")),
            row_anchor_parity_status=str(data.get("row_anchor_parity_status", "not_checked")),
            gate_count=int(data.get("gate_count", len(gates))),
            required_count=int(data.get("required_count", sum(1 for gate in gates if gate.required))),
            passed_count=int(data.get("passed_count", sum(1 for gate in gates if gate.required and gate.ok))),
            blocked_count=int(data.get("blocked_count", sum(1 for gate in gates if gate.required and not gate.ok))),
            warning_count=int(data.get("warning_count", sum(len(gate.warnings) for gate in gates))),
            gates=gates,
            raw_size=int(data.get("raw_size", 0)),
            row_count=int(data.get("row_count", 0)),
            chunk_size=(None if data.get("chunk_size") is None else int(data.get("chunk_size"))),
            chunk_count=int(data.get("chunk_count", 0)),
            max_record_span=int(data.get("max_record_span", 0)),
            estimated_linear_scan_work_units=int(data.get("estimated_linear_scan_work_units", 0)),
            estimated_anchor_digest_work_units=int(data.get("estimated_anchor_digest_work_units", 0)),
            max_linear_scan_work_units=int(data.get("max_linear_scan_work_units", 0)),
            max_anchor_digest_work_units=int(data.get("max_anchor_digest_work_units", 0)),
            max_work_amplification=int(data.get("max_work_amplification", 0)),
            estimated_gate_json_bytes=int(data.get("estimated_gate_json_bytes", 0)),
            max_report_json_bytes=int(data.get("max_report_json_bytes", 0)),
            native_backend_available=bool(data.get("native_backend_available", False)),
            native_backend_used=bool(data.get("native_backend_used", False)),
            requested_native=bool(data.get("requested_native", False)),
            force_native=bool(data.get("force_native", False)),
            python_reference_fallback_available=bool(data.get("python_reference_fallback_available", True)),
            python_reference_fallback_used=bool(data.get("python_reference_fallback_used", False)),
            warnings=tuple(str(v) for v in data.get("warnings", ()) or ()),
            errors=tuple(str(v) for v in data.get("errors", ()) or ()),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
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
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
        )


def _empty_performance_gate_report(
    csv_id: str,
    error: str,
    *,
    report_key: str = "",
    max_report_json_bytes: int = 65536,
    max_work_amplification: int = 4,
) -> CSVKernelPerformanceGateReport:
    gate = CSVKernelPerformanceGate(
        gate_index=1,
        gate_name="performance_gate_prepare_failed",
        category="admission",
        status="blocked",
        errors=(error,),
    )
    return CSVKernelPerformanceGateReport(
        csv_id=csv_id,
        status="invalid",
        kernel_performance_gate_version=CSV_KERNEL_PERFORMANCE_GATE_VERSION,
        report_key=report_key,
        mode="performance_gate_prepare",
        source_native_row_anchor_report_key="",
        source_native_scan_report_key="",
        source_anchor_fingerprint="",
        source_reference_anchor_fingerprint="",
        source_scan_fingerprint="",
        source_reference_scan_fingerprint="",
        performance_gate_fingerprint="",
        raw_sha256="",
        row_anchor_validation_status="not_checked",
        native_scan_validation_status="not_checked",
        scan_parity_status="not_checked",
        row_anchor_parity_status="not_checked",
        gate_count=1,
        required_count=1,
        passed_count=0,
        blocked_count=1,
        warning_count=0,
        gates=(gate,),
        raw_size=0,
        row_count=0,
        chunk_size=None,
        chunk_count=0,
        max_record_span=0,
        estimated_linear_scan_work_units=0,
        estimated_anchor_digest_work_units=0,
        max_linear_scan_work_units=0,
        max_anchor_digest_work_units=0,
        max_work_amplification=max_work_amplification,
        estimated_gate_json_bytes=0,
        max_report_json_bytes=max_report_json_bytes,
        native_backend_available=False,
        native_backend_used=False,
        requested_native=False,
        force_native=False,
        python_reference_fallback_available=True,
        python_reference_fallback_used=False,
        warnings=tuple(),
        errors=(error,),
    )


def _gate(
    index: int,
    name: str,
    category: str,
    condition: bool,
    *,
    metric_name: str = "",
    metric_value: Any = None,
    metric_limit: Any = None,
    comparator: str = "",
    evidence_hashes: Mapping[str, str] | None = None,
    error: str | None = None,
    warning: str | None = None,
) -> CSVKernelPerformanceGate:
    errors = tuple() if condition else (error or f"{name}_failed",)
    warnings = (warning,) if warning else tuple()
    return CSVKernelPerformanceGate(
        gate_index=index,
        gate_name=name,
        category=category,
        status="passed" if condition else "blocked",
        metric_name=metric_name,
        metric_value=metric_value,
        metric_limit=metric_limit,
        comparator=comparator,
        evidence_hashes=dict(evidence_hashes or {}),
        warnings=warnings,
        errors=errors,
    )


def _gate_fingerprint(gates: tuple[CSVKernelPerformanceGate, ...], *, csv_id: str, raw_sha256: str, raw_size: int, row_count: int) -> str:
    return _canonical_sha256(
        {
            "version": CSV_KERNEL_PERFORMANCE_GATE_VERSION,
            "csv_id": csv_id,
            "raw_sha256": raw_sha256,
            "raw_size": raw_size,
            "row_count": row_count,
            "gates": [gate.to_dict() for gate in gates],
        }
    )


def _gate_payload_bytes(gates: tuple[CSVKernelPerformanceGate, ...]) -> int:
    return len(json.dumps([gate.to_dict() for gate in gates], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _load_sources(directory: TDSDirectory, csv_id: str) -> tuple[CSVNativeRowAnchorKernelReport, CSVNativeScanKernelReport]:
    row_anchor_report = load_csv_native_row_anchor_kernel_report(directory, csv_id)
    native_scan_report = load_csv_native_scan_kernel_prototype_report(directory, csv_id)
    return row_anchor_report, native_scan_report


def prepare_csv_kernel_performance_gates(
    directory: TDSDirectory,
    csv_id: str,
    *,
    max_report_json_bytes: int = 65536,
    max_work_amplification: int = 4,
) -> CSVKernelPerformanceGateReport:
    """Build a no-write deterministic performance-gate report.

    The report requires a committed v3.4.7 native row-anchor report and the
    source v3.4.6 native scan report.  It then validates both against fresh
    evidence and checks bounded work/report shapes without timing assertions.
    """
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_kernel_performance_gate_report_key(safe_id)
    except Exception as exc:
        return _empty_performance_gate_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    if max_report_json_bytes <= 0:
        return _empty_performance_gate_report(
            safe_id,
            "max_report_json_bytes_must_be_positive",
            report_key=report_key,
            max_report_json_bytes=max_report_json_bytes,
            max_work_amplification=max_work_amplification,
        )
    if max_work_amplification <= 0:
        return _empty_performance_gate_report(
            safe_id,
            "max_work_amplification_must_be_positive",
            report_key=report_key,
            max_report_json_bytes=max_report_json_bytes,
            max_work_amplification=max_work_amplification,
        )

    try:
        row_anchor_report, native_scan_report = _load_sources(directory, safe_id)
        row_anchor_validation = validate_csv_native_row_anchor_kernel(directory, safe_id, chunk_size=row_anchor_report.chunk_size)
        native_scan_validation = validate_csv_native_scan_kernel_prototype(directory, safe_id, chunk_size=native_scan_report.chunk_size)
    except Exception as exc:
        return _empty_performance_gate_report(
            safe_id,
            f"performance_gate_sources_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
            max_report_json_bytes=max_report_json_bytes,
            max_work_amplification=max_work_amplification,
        )

    raw_size = max(int(row_anchor_report.raw_size), 0)
    row_count = max(int(row_anchor_report.row_count), 0)
    chunk_count = max(int(row_anchor_report.chunk_count), 0)
    max_record_span = max(int(row_anchor_report.max_record_span), 0)
    estimated_linear_scan_work_units = raw_size + row_count + chunk_count + max_record_span
    estimated_anchor_digest_work_units = row_count + max_record_span
    max_linear_scan_work_units = max(1, max_work_amplification * max(1, raw_size + row_count + chunk_count + max_record_span))
    max_anchor_digest_work_units = max(1, max_work_amplification * max(1, row_count + max_record_span))

    source_hashes = {
        "native_row_anchor_report_key": csv_native_row_anchor_kernel_report_key(safe_id),
        "native_scan_report_key": csv_native_scan_kernel_report_key(safe_id),
        "anchor_fingerprint": row_anchor_report.anchor_fingerprint,
        "reference_anchor_fingerprint": row_anchor_report.reference_anchor_fingerprint,
        "scan_fingerprint": native_scan_report.scan_fingerprint,
        "reference_scan_fingerprint": native_scan_report.reference_scan_fingerprint,
        "raw_sha256": row_anchor_report.raw_sha256,
    }

    gates: list[CSVKernelPerformanceGate] = []
    gates.append(
        _gate(
            1,
            "source_reports_committed",
            "admission",
            row_anchor_report.status in {"native_row_anchor_committed", "valid"}
            and native_scan_report.status in {"native_scan_committed", "valid"},
            metric_name="source_statuses",
            metric_value=f"{row_anchor_report.status}|{native_scan_report.status}",
            metric_limit="committed_or_valid",
            comparator="in",
            evidence_hashes=source_hashes,
            error="source_kernel_reports_not_committed",
        )
    )
    gates.append(
        _gate(
            2,
            "fresh_validation_valid",
            "admission",
            row_anchor_validation.ok and native_scan_validation.ok,
            metric_name="validation_statuses",
            metric_value=f"{row_anchor_validation.status}|{native_scan_validation.status}",
            metric_limit="valid|valid",
            comparator="==",
            evidence_hashes=source_hashes,
            error="fresh_kernel_validation_not_valid",
        )
    )
    gates.append(
        _gate(
            3,
            "scan_fingerprint_parity",
            "parity",
            native_scan_report.scan_fingerprint == native_scan_report.reference_scan_fingerprint,
            metric_name="scan_fingerprint_match",
            metric_value=native_scan_report.scan_fingerprint == native_scan_report.reference_scan_fingerprint,
            metric_limit=True,
            comparator="==",
            evidence_hashes=source_hashes,
            error="scan_fingerprint_mismatch_reference",
        )
    )
    gates.append(
        _gate(
            4,
            "anchor_fingerprint_parity",
            "parity",
            row_anchor_report.anchor_fingerprint == row_anchor_report.reference_anchor_fingerprint,
            metric_name="anchor_fingerprint_match",
            metric_value=row_anchor_report.anchor_fingerprint == row_anchor_report.reference_anchor_fingerprint,
            metric_limit=True,
            comparator="==",
            evidence_hashes=source_hashes,
            error="anchor_fingerprint_mismatch_reference",
        )
    )
    gates.append(
        _gate(
            5,
            "linear_scan_work_budget",
            "work_shape",
            estimated_linear_scan_work_units <= max_linear_scan_work_units,
            metric_name="estimated_linear_scan_work_units",
            metric_value=estimated_linear_scan_work_units,
            metric_limit=max_linear_scan_work_units,
            comparator="<=",
            evidence_hashes=source_hashes,
            error="linear_scan_work_budget_exceeded",
        )
    )
    gates.append(
        _gate(
            6,
            "anchor_digest_work_budget",
            "work_shape",
            estimated_anchor_digest_work_units <= max_anchor_digest_work_units,
            metric_name="estimated_anchor_digest_work_units",
            metric_value=estimated_anchor_digest_work_units,
            metric_limit=max_anchor_digest_work_units,
            comparator="<=",
            evidence_hashes=source_hashes,
            error="anchor_digest_work_budget_exceeded",
        )
    )
    gates.append(
        _gate(
            7,
            "chunk_boundary_shape_preserved",
            "work_shape",
            (raw_size == 0 and chunk_count == 0) or (raw_size > 0 and chunk_count >= 1),
            metric_name="chunk_count",
            metric_value=chunk_count,
            metric_limit="0_for_empty_or_positive",
            comparator="shape",
            evidence_hashes=source_hashes,
            error="chunk_boundary_shape_invalid",
        )
    )
    gates.append(
        _gate(
            8,
            "report_compaction_preserved",
            "artifact_shape",
            bool(row_anchor_report.row_offsets_packed_sha256)
            and bool(row_anchor_report.row_spans_sha256)
            and bool(row_anchor_report.row_anchor_hashes_sha256),
            metric_name="compact_hash_fields_present",
            metric_value=True,
            metric_limit=True,
            comparator="==",
            evidence_hashes=source_hashes,
            error="compact_hash_fields_missing",
        )
    )
    gates.append(
        _gate(
            9,
            "fallback_safety_preserved",
            "safety",
            row_anchor_report.python_reference_fallback_available and native_scan_report.python_reference_fallback_available,
            metric_name="python_reference_fallback_available",
            metric_value=row_anchor_report.python_reference_fallback_available and native_scan_report.python_reference_fallback_available,
            metric_limit=True,
            comparator="==",
            evidence_hashes=source_hashes,
            error="python_reference_fallback_unavailable",
        )
    )
    gates.append(
        _gate(
            10,
            "native_storage_hot_path_isolated",
            "safety",
            not row_anchor_report.native_storage_writes
            and not row_anchor_report.native_storage_hot_path_touched
            and not row_anchor_report.native_storage_locks_controlled
            and not row_anchor_report.native_c_storage_engine_changed
            and not native_scan_report.native_storage_writes
            and not native_scan_report.native_storage_hot_path_touched
            and not native_scan_report.native_storage_locks_controlled
            and not native_scan_report.native_c_storage_engine_changed,
            metric_name="native_storage_isolation",
            metric_value=True,
            metric_limit=True,
            comparator="==",
            evidence_hashes=source_hashes,
            error="native_storage_hot_path_isolation_failed",
        )
    )
    gates.append(
        _gate(
            11,
            "write_amplification_blocked",
            "safety",
            not row_anchor_report.per_row_writes
            and not row_anchor_report.per_cell_writes
            and not native_scan_report.per_row_writes
            and not native_scan_report.per_cell_writes,
            metric_name="per_row_cell_writes",
            metric_value=False,
            metric_limit=False,
            comparator="==",
            evidence_hashes=source_hashes,
            error="per_row_or_per_cell_writes_detected",
        )
    )
    gates.append(
        _gate(
            12,
            "semantic_exclusion_preserved",
            "safety",
            not row_anchor_report.semantic_reasoning
            and not row_anchor_report.semantic_conclusions
            and not row_anchor_report.schema_inference
            and not row_anchor_report.type_inference
            and not row_anchor_report.entity_inference
            and not row_anchor_report.formal_ir_committed
            and not native_scan_report.semantic_reasoning
            and not native_scan_report.semantic_conclusions
            and not native_scan_report.schema_inference
            and not native_scan_report.type_inference
            and not native_scan_report.entity_inference
            and not native_scan_report.formal_ir_committed,
            metric_name="semantic_exclusion",
            metric_value=True,
            metric_limit=True,
            comparator="==",
            evidence_hashes=source_hashes,
            error="semantic_or_ir_path_detected",
        )
    )

    estimated_gate_json_bytes = _gate_payload_bytes(tuple(gates))
    gates.append(
        _gate(
            13,
            "performance_gate_report_bounded",
            "artifact_shape",
            estimated_gate_json_bytes <= max_report_json_bytes,
            metric_name="estimated_gate_json_bytes",
            metric_value=estimated_gate_json_bytes,
            metric_limit=max_report_json_bytes,
            comparator="<=",
            evidence_hashes={"gate_payload_sha256": _canonical_sha256([gate.to_dict() for gate in gates])},
            error="performance_gate_report_size_exceeded",
        )
    )

    final_gates = tuple(gates)
    errors: list[str] = []
    warnings: list[str] = []
    for gate in final_gates:
        errors.extend(gate.errors)
        warnings.extend(gate.warnings)
    if row_anchor_validation.errors:
        errors.extend(str(v) for v in row_anchor_validation.errors)
    if native_scan_validation.errors:
        errors.extend(str(v) for v in native_scan_validation.errors)

    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    required_count = sum(1 for gate in final_gates if gate.required)
    passed_count = sum(1 for gate in final_gates if gate.required and gate.ok)
    blocked_count = required_count - passed_count
    warning_count = len(unique_warnings) + sum(len(gate.warnings) for gate in final_gates)
    status = "performance_gates_ready" if not unique_errors and blocked_count == 0 else "blocked"

    return CSVKernelPerformanceGateReport(
        csv_id=safe_id,
        status=status,
        kernel_performance_gate_version=CSV_KERNEL_PERFORMANCE_GATE_VERSION,
        report_key=report_key,
        mode="performance_gate_prepare",
        source_native_row_anchor_report_key=csv_native_row_anchor_kernel_report_key(safe_id),
        source_native_scan_report_key=csv_native_scan_kernel_report_key(safe_id),
        source_anchor_fingerprint=row_anchor_report.anchor_fingerprint,
        source_reference_anchor_fingerprint=row_anchor_report.reference_anchor_fingerprint,
        source_scan_fingerprint=native_scan_report.scan_fingerprint,
        source_reference_scan_fingerprint=native_scan_report.reference_scan_fingerprint,
        performance_gate_fingerprint=_gate_fingerprint(final_gates, csv_id=safe_id, raw_sha256=row_anchor_report.raw_sha256, raw_size=raw_size, row_count=row_count),
        raw_sha256=row_anchor_report.raw_sha256,
        row_anchor_validation_status=row_anchor_validation.status,
        native_scan_validation_status=native_scan_validation.status,
        scan_parity_status=row_anchor_report.scan_parity_status,
        row_anchor_parity_status=row_anchor_report.row_anchor_parity_status,
        gate_count=len(final_gates),
        required_count=required_count,
        passed_count=passed_count,
        blocked_count=blocked_count,
        warning_count=warning_count,
        gates=final_gates,
        raw_size=raw_size,
        row_count=row_count,
        chunk_size=row_anchor_report.chunk_size,
        chunk_count=chunk_count,
        max_record_span=max_record_span,
        estimated_linear_scan_work_units=estimated_linear_scan_work_units,
        estimated_anchor_digest_work_units=estimated_anchor_digest_work_units,
        max_linear_scan_work_units=max_linear_scan_work_units,
        max_anchor_digest_work_units=max_anchor_digest_work_units,
        max_work_amplification=max_work_amplification,
        estimated_gate_json_bytes=estimated_gate_json_bytes,
        max_report_json_bytes=max_report_json_bytes,
        native_backend_available=row_anchor_report.native_backend_available or native_scan_report.native_backend_available,
        native_backend_used=row_anchor_report.native_backend_used or native_scan_report.native_backend_used,
        requested_native=row_anchor_report.requested_native or native_scan_report.requested_native,
        force_native=row_anchor_report.force_native or native_scan_report.force_native,
        python_reference_fallback_available=row_anchor_report.python_reference_fallback_available and native_scan_report.python_reference_fallback_available,
        python_reference_fallback_used=row_anchor_report.python_reference_fallback_used or native_scan_report.python_reference_fallback_used,
        warnings=unique_warnings,
        errors=unique_errors,
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_storage_hot_path_touched=False,
        native_storage_locks_controlled=False,
        native_c_storage_engine_changed=False,
        interpole_mutation=False,
        per_row_writes=False,
        per_cell_writes=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        schema_inference=False,
        type_inference=False,
        entity_inference=False,
        formal_ir_committed=False,
    )


def commit_csv_kernel_performance_gate_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    max_report_json_bytes: int = 65536,
    max_work_amplification: int = 4,
    overwrite: bool = False,
) -> CSVKernelPerformanceGateReport:
    """Persist a compact v3.4.8 performance-gate report."""
    report = prepare_csv_kernel_performance_gates(
        directory,
        csv_id,
        max_report_json_bytes=max_report_json_bytes,
        max_work_amplification=max_work_amplification,
    )
    if not report.ok:
        return report
    committed = replace(report, status="performance_gates_committed", mode="performance_gate_commit", tds_artifact_writes=1)
    result: TDSResult = directory.write_json(committed.report_key, committed.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return replace(committed, status="blocked", errors=(f"performance_gate_report_write_failed:{result.code}",), tds_artifact_writes=0)
    return committed


def load_csv_kernel_performance_gate_report(directory: TDSDirectory, csv_id: str) -> CSVKernelPerformanceGateReport:
    """Load a committed v3.4.8 performance-gate report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_kernel_performance_gate_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV kernel performance-gate report {key!r} is not a JSON object")
    return CSVKernelPerformanceGateReport.from_mapping(value)


def validate_csv_kernel_performance_gate_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    max_report_json_bytes: int | None = None,
    max_work_amplification: int | None = None,
) -> CSVKernelPerformanceGateReport:
    """Validate a committed performance-gate report against fresh evidence."""
    try:
        stored = load_csv_kernel_performance_gate_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_kernel_performance_gate_report_key(csv_id)
        except Exception:
            report_key = ""
        return _empty_performance_gate_report(str(csv_id), f"performance_gate_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_kernel_performance_gates(
        directory,
        stored.csv_id,
        max_report_json_bytes=stored.max_report_json_bytes if max_report_json_bytes is None else max_report_json_bytes,
        max_work_amplification=stored.max_work_amplification if max_work_amplification is None else max_work_amplification,
    )
    errors = list(fresh.errors)
    warnings = list(fresh.warnings)
    if stored.status not in {"performance_gates_committed", "valid"}:
        errors.append(f"stored_performance_gate_report_not_committed:{stored.status}")
    if stored.source_anchor_fingerprint != fresh.source_anchor_fingerprint:
        errors.append("performance_gate_source_anchor_fingerprint_drift")
    if stored.source_reference_anchor_fingerprint != fresh.source_reference_anchor_fingerprint:
        errors.append("performance_gate_source_reference_anchor_fingerprint_drift")
    if stored.source_scan_fingerprint != fresh.source_scan_fingerprint:
        errors.append("performance_gate_source_scan_fingerprint_drift")
    if stored.source_reference_scan_fingerprint != fresh.source_reference_scan_fingerprint:
        errors.append("performance_gate_source_reference_scan_fingerprint_drift")
    if stored.performance_gate_fingerprint != fresh.performance_gate_fingerprint:
        errors.append("performance_gate_fingerprint_drift")
    if stored.raw_sha256 != fresh.raw_sha256:
        errors.append("performance_gate_raw_sha256_drift")
    if stored.raw_size != fresh.raw_size:
        errors.append("performance_gate_raw_size_drift")
    if stored.row_count != fresh.row_count:
        errors.append("performance_gate_row_count_drift")
    if stored.chunk_count != fresh.chunk_count:
        errors.append("performance_gate_chunk_count_drift")
    if stored.estimated_gate_json_bytes != fresh.estimated_gate_json_bytes:
        errors.append("performance_gate_json_size_drift")

    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    status = "valid" if not unique_errors and fresh.ok else "drifted"
    return replace(fresh, status=status, mode="validation", warnings=unique_warnings, errors=unique_errors, tds_artifact_writes=0)


def csv_kernel_performance_gate_summary(report: CSVKernelPerformanceGateReport) -> dict[str, Any]:
    """Return a compact UI/API summary for v3.4.8 performance gates."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "version": report.kernel_performance_gate_version,
        "report_key": report.report_key,
        "mode": report.mode,
        "source_native_row_anchor_report_key": report.source_native_row_anchor_report_key,
        "source_native_scan_report_key": report.source_native_scan_report_key,
        "source_anchor_fingerprint": report.source_anchor_fingerprint,
        "source_reference_anchor_fingerprint": report.source_reference_anchor_fingerprint,
        "source_scan_fingerprint": report.source_scan_fingerprint,
        "source_reference_scan_fingerprint": report.source_reference_scan_fingerprint,
        "performance_gate_fingerprint": report.performance_gate_fingerprint,
        "raw_sha256": report.raw_sha256,
        "row_anchor_validation_status": report.row_anchor_validation_status,
        "native_scan_validation_status": report.native_scan_validation_status,
        "scan_parity_status": report.scan_parity_status,
        "row_anchor_parity_status": report.row_anchor_parity_status,
        "gate_count": report.gate_count,
        "required_count": report.required_count,
        "passed_count": report.passed_count,
        "blocked_count": report.blocked_count,
        "warning_count": report.warning_count,
        "raw_size": report.raw_size,
        "row_count": report.row_count,
        "chunk_size": report.chunk_size,
        "chunk_count": report.chunk_count,
        "max_record_span": report.max_record_span,
        "estimated_linear_scan_work_units": report.estimated_linear_scan_work_units,
        "estimated_anchor_digest_work_units": report.estimated_anchor_digest_work_units,
        "max_linear_scan_work_units": report.max_linear_scan_work_units,
        "max_anchor_digest_work_units": report.max_anchor_digest_work_units,
        "max_work_amplification": report.max_work_amplification,
        "estimated_gate_json_bytes": report.estimated_gate_json_bytes,
        "max_report_json_bytes": report.max_report_json_bytes,
        "native_backend_available": report.native_backend_available,
        "native_backend_used": report.native_backend_used,
        "requested_native": report.requested_native,
        "force_native": report.force_native,
        "python_reference_fallback_available": report.python_reference_fallback_available,
        "python_reference_fallback_used": report.python_reference_fallback_used,
        "native_storage_writes": report.native_storage_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "native_storage_locks_controlled": report.native_storage_locks_controlled,
        "native_c_storage_engine_changed": report.native_c_storage_engine_changed,
        "interpole_mutation": report.interpole_mutation,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "semantic_reasoning": report.semantic_reasoning,
        "semantic_conclusions": report.semantic_conclusions,
        "formal_ir_committed": report.formal_ir_committed,
        "gates": [
            {
                "gate_index": gate.gate_index,
                "gate_name": gate.gate_name,
                "category": gate.category,
                "status": gate.status,
                "ok": gate.ok,
                "metric_name": gate.metric_name,
                "metric_value": gate.metric_value,
                "metric_limit": gate.metric_limit,
                "comparator": gate.comparator,
                "errors": list(gate.errors),
            }
            for gate in report.gates
        ],
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }

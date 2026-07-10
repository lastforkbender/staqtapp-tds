"""CSV kernel readiness contract for future native CSV sidecar work.

This module deliberately does not implement a native CSV kernel.  It freezes the
readiness contract that a later native sidecar must satisfy: input/output shape,
Python reference parity, fallback behavior, failure modes, hot-path isolation,
and semantic exclusion.  It is an intelligence-storage contract layer, not an AI
or semantic IR layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any, Mapping

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.tds_json import dumps_canonical

from .importer import load_csv_manifest
from .interpole import load_csv_interpole_timeline_ring_report, validate_csv_interpole_timeline_ring
from .manifest import artifact_keys, validate_csv_id
from .scanner import validate_csv_row_anchors, validate_csv_scan_profile


CSV_KERNEL_READINESS_VERSION = "1.0"


_KERNEL_REQUIREMENT_ORDER: tuple[str, ...] = (
    "kernel_input_raw_bytes_contract",
    "kernel_input_dialect_contract",
    "scan_profile_output_contract",
    "row_offset_parity_contract",
    "row_anchor_output_contract",
    "chunk_boundary_state_contract",
    "python_reference_fallback_contract",
    "failure_mode_fail_closed_contract",
    "native_storage_hot_path_isolation_contract",
    "semantic_exclusion_contract",
    "per_row_cell_write_exclusion_contract",
    "interpole_ring_readiness_contract",
    "benchmark_gate_shape_contract",
)


def csv_kernel_readiness_report_key(csv_id: str) -> str:
    """Return the durable key for the CSV kernel readiness contract report."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__kernel_readiness_report.json"


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(dumps_canonical(value)[0]).hexdigest()


def _dict_from_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(k): v for k, v in (value or {}).items()}


def _string_dict_from_mapping(value: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (value or {}).items()}


@dataclass(frozen=True, slots=True)
class CSVKernelReadinessRequirement:
    """One bounded kernel-readiness requirement.

    Requirements describe what a future native CSV sidecar must preserve.  They
    are contract facts only: no native kernel code is loaded, no storage hot-path
    lock is touched, and no CSV semantics or IR decisions are emitted.
    """

    requirement_index: int
    requirement_name: str
    requirement_kind: str
    status: str
    required: bool = True
    source: str = ""
    evidence_hashes: Mapping[str, str] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    fallback: str = "python_reference"
    error: str = ""
    warning: str = ""
    native_kernel_required: bool = False
    native_kernel_used: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False
    semantic_conclusion: bool = False
    schema_inference: bool = False
    type_inference: bool = False
    entity_inference: bool = False
    ir_candidate: bool = False
    per_row_writes: bool = False
    per_cell_writes: bool = False

    @property
    def ok(self) -> bool:
        if self.required and self.status not in {"ready", "declared", "guarded"}:
            return False
        return (
            not self.error
            and not self.native_kernel_required
            and not self.native_kernel_used
            and not self.native_storage_hot_path_touched
            and not self.semantic_reasoning
            and not self.semantic_conclusion
            and not self.schema_inference
            and not self.type_inference
            and not self.entity_inference
            and not self.ir_candidate
            and not self.per_row_writes
            and not self.per_cell_writes
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_hashes"] = dict(self.evidence_hashes)
        data["metrics"] = dict(self.metrics)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVKernelReadinessRequirement":
        return cls(
            requirement_index=int(data.get("requirement_index", 0)),
            requirement_name=str(data.get("requirement_name", "")),
            requirement_kind=str(data.get("requirement_kind", "contract")),
            status=str(data.get("status", "blocked")),
            required=bool(data.get("required", True)),
            source=str(data.get("source", "")),
            evidence_hashes=_string_dict_from_mapping(data.get("evidence_hashes", {}) or {}),
            metrics=_dict_from_mapping(data.get("metrics", {}) or {}),
            fallback=str(data.get("fallback", "python_reference")),
            error=str(data.get("error", "")),
            warning=str(data.get("warning", "")),
            native_kernel_required=bool(data.get("native_kernel_required", False)),
            native_kernel_used=bool(data.get("native_kernel_used", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
            semantic_conclusion=bool(data.get("semantic_conclusion", False)),
            schema_inference=bool(data.get("schema_inference", False)),
            type_inference=bool(data.get("type_inference", False)),
            entity_inference=bool(data.get("entity_inference", False)),
            ir_candidate=bool(data.get("ir_candidate", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVKernelReadinessReport:
    """Readiness contract for future native CSV kernel work.

    The report freezes the contract and parity expectations.  It does not
    provide a native scanner implementation.  Later v3.4.x native work can use
    this report as the admission gate before C-side scan kernels are accepted.
    """

    csv_id: str
    status: str
    kernel_readiness_version: str
    report_key: str
    mode: str
    contract_fingerprint: str
    input_contract_sha256: str
    output_contract_sha256: str
    failure_contract_sha256: str
    benchmark_contract_sha256: str
    source_timeline_ring_report_key: str = ""
    source_ring_fingerprint: str = ""
    source_mirror_fingerprint: str = ""
    timeline_ring_validation_status: str = "not_checked"
    scan_parity_status: str = "not_checked"
    row_anchor_parity_status: str = "not_checked"
    requirements: tuple[CSVKernelReadinessRequirement, ...] = field(default_factory=tuple)
    requirement_count: int = 0
    required_count: int = 0
    ready_count: int = 0
    blocked_count: int = 0
    warning_count: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    tds_artifact_writes: int = 0
    native_storage_writes: bool = False
    native_c_engine_changed: bool = False
    native_csv_kernel_implemented: bool = False
    native_csv_kernel_used: bool = False
    native_storage_hot_path_touched: bool = False
    python_reference_fallback_available: bool = True
    per_row_writes: bool = False
    per_cell_writes: bool = False
    semantic_reasoning: bool = False
    semantic_conclusions: bool = False
    determinant_vectoring: bool = True
    timeline_ring_materialized: bool = True
    invertible_mirror_feedback: bool = True
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.status in {"kernel_contract_ready", "kernel_contract_committed", "valid"}
            and not self.errors
            and self.requirement_count > 0
            and self.ready_count == self.required_count
            and self.blocked_count == 0
            and not self.native_csv_kernel_implemented
            and not self.native_csv_kernel_used
            and not self.native_storage_hot_path_touched
            and not self.semantic_reasoning
            and not self.semantic_conclusions
            and not self.formal_ir_committed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requirements"] = [req.to_dict() for req in self.requirements]
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVKernelReadinessReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            kernel_readiness_version=str(data.get("kernel_readiness_version", CSV_KERNEL_READINESS_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "unknown")),
            contract_fingerprint=str(data.get("contract_fingerprint", "")),
            input_contract_sha256=str(data.get("input_contract_sha256", "")),
            output_contract_sha256=str(data.get("output_contract_sha256", "")),
            failure_contract_sha256=str(data.get("failure_contract_sha256", "")),
            benchmark_contract_sha256=str(data.get("benchmark_contract_sha256", "")),
            source_timeline_ring_report_key=str(data.get("source_timeline_ring_report_key", "")),
            source_ring_fingerprint=str(data.get("source_ring_fingerprint", "")),
            source_mirror_fingerprint=str(data.get("source_mirror_fingerprint", "")),
            timeline_ring_validation_status=str(data.get("timeline_ring_validation_status", "not_checked")),
            scan_parity_status=str(data.get("scan_parity_status", "not_checked")),
            row_anchor_parity_status=str(data.get("row_anchor_parity_status", "not_checked")),
            requirements=tuple(CSVKernelReadinessRequirement.from_mapping(v) for v in data.get("requirements", []) or []),
            requirement_count=int(data.get("requirement_count", 0)),
            required_count=int(data.get("required_count", 0)),
            ready_count=int(data.get("ready_count", 0)),
            blocked_count=int(data.get("blocked_count", 0)),
            warning_count=int(data.get("warning_count", 0)),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            native_c_engine_changed=bool(data.get("native_c_engine_changed", False)),
            native_csv_kernel_implemented=bool(data.get("native_csv_kernel_implemented", False)),
            native_csv_kernel_used=bool(data.get("native_csv_kernel_used", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            python_reference_fallback_available=bool(data.get("python_reference_fallback_available", True)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
            semantic_conclusions=bool(data.get("semantic_conclusions", False)),
            determinant_vectoring=bool(data.get("determinant_vectoring", True)),
            timeline_ring_materialized=bool(data.get("timeline_ring_materialized", True)),
            invertible_mirror_feedback=bool(data.get("invertible_mirror_feedback", True)),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
        )


def _empty_kernel_report(csv_id: str, error: str, *, report_key: str = "") -> CSVKernelReadinessReport:
    return CSVKernelReadinessReport(
        csv_id=str(csv_id),
        status="invalid",
        kernel_readiness_version=CSV_KERNEL_READINESS_VERSION,
        report_key=report_key,
        mode="invalid",
        contract_fingerprint="",
        input_contract_sha256="",
        output_contract_sha256="",
        failure_contract_sha256="",
        benchmark_contract_sha256="",
        errors=(error,),
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_implemented=False,
        native_csv_kernel_used=False,
        native_storage_hot_path_touched=False,
        python_reference_fallback_available=True,
        per_row_writes=False,
        per_cell_writes=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        formal_ir_committed=False,
    )


def _requirement(
    index: int,
    name: str,
    kind: str,
    *,
    status: str = "ready",
    required: bool = True,
    source: str = "",
    evidence_hashes: Mapping[str, str] | None = None,
    metrics: Mapping[str, Any] | None = None,
    fallback: str = "python_reference",
    error: str = "",
    warning: str = "",
) -> CSVKernelReadinessRequirement:
    return CSVKernelReadinessRequirement(
        requirement_index=index,
        requirement_name=name,
        requirement_kind=kind,
        status=status,
        required=required,
        source=source,
        evidence_hashes=dict(evidence_hashes or {}),
        metrics=dict(metrics or {}),
        fallback=fallback,
        error=error,
        warning=warning,
        native_kernel_required=False,
        native_kernel_used=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusion=False,
        schema_inference=False,
        type_inference=False,
        entity_inference=False,
        ir_candidate=False,
        per_row_writes=False,
        per_cell_writes=False,
    )


def _input_contract(manifest: Any) -> dict[str, Any]:
    return {
        "contract": "csv_kernel_input",
        "version": CSV_KERNEL_READINESS_VERSION,
        "accepted_payloads": ["bytes", "bytearray", "memoryview", "mmap_readonly"],
        "required_facts": ["raw_bytes", "encoding", "dialect_fingerprint", "raw_sha256", "row_offset_artifact"],
        "csv_id": str(getattr(manifest, "csv_id", "")),
        "encoding": str(getattr(manifest, "encoding", "utf-8")),
        "raw_size": int(getattr(manifest, "raw_size", 0)),
        "row_count": int(getattr(manifest, "row_count", 0)),
        "column_count": int(getattr(manifest, "column_count", 0)),
        "raw_sha256": str(getattr(manifest, "raw_sha256", "")),
    }


def _output_contract() -> dict[str, Any]:
    return {
        "contract": "csv_kernel_output",
        "version": CSV_KERNEL_READINESS_VERSION,
        "required_outputs": [
            "CSVScanProfile parity",
            "row_offsets parity",
            "CSVRowAnchorProfile parity",
            "payload hash preservation",
            "fail_closed_error_codes",
        ],
        "forbidden_outputs": ["schema inference", "type inference", "entity inference", "IR commitment", "per_cell_entries"],
        "scanner_identity": "native.csv.scan.sidecar.future",
        "reference_identity": "python.memoryview.reference",
    }


def _failure_contract() -> dict[str, Any]:
    return {
        "contract": "csv_kernel_failure_modes",
        "version": CSV_KERNEL_READINESS_VERSION,
        "fail_closed_on": [
            "raw_sha256_mismatch",
            "row_offset_mismatch",
            "row_count_mismatch",
            "anchor_hash_mismatch",
            "open_quote_state_mismatch",
            "unsupported_encoding",
            "unsafe_csv_id",
            "storage_binding_drift",
            "interpole_ring_drift",
        ],
        "fallback": "python_reference",
        "native_storage_hot_path_control": False,
    }


def _benchmark_contract() -> dict[str, Any]:
    return {
        "contract": "csv_kernel_benchmark_gates",
        "version": CSV_KERNEL_READINESS_VERSION,
        "gate_shape_only": True,
        "throughput_gate_required_before_default_native": True,
        "parity_gate_required_before_performance_gate": True,
        "required_benchmarks": [
            "benchmark_v331_csv_scan.py",
            "benchmark_v332_csv_row_anchors.py",
            "future_native_csv_scan_kernel.py",
        ],
    }


def _requirements(
    *,
    manifest: Any,
    input_contract_sha256: str,
    output_contract_sha256: str,
    failure_contract_sha256: str,
    benchmark_contract_sha256: str,
    ring_validation: Any,
    stored_ring: Any,
    scan_parity: Any,
    row_anchor_parity: Any,
) -> tuple[CSVKernelReadinessRequirement, ...]:
    keys = artifact_keys(str(getattr(manifest, "csv_id", "")))
    reqs: list[CSVKernelReadinessRequirement] = []
    reqs.append(
        _requirement(
            0,
            "kernel_input_raw_bytes_contract",
            "input_contract",
            status="ready" if bool(getattr(scan_parity, "raw_sha256_verified", False)) else "blocked",
            source=keys["raw"],
            evidence_hashes={"input_contract_sha256": input_contract_sha256, "raw_sha256": str(getattr(manifest, "raw_sha256", ""))},
            metrics={"raw_size": int(getattr(manifest, "raw_size", 0)), "encoding": str(getattr(manifest, "encoding", "utf-8"))},
            error="kernel_input_raw_sha256_not_verified" if not bool(getattr(scan_parity, "raw_sha256_verified", False)) else "",
        )
    )
    reqs.append(
        _requirement(
            1,
            "kernel_input_dialect_contract",
            "input_contract",
            status="ready",
            source=keys["dialect"],
            evidence_hashes={"input_contract_sha256": input_contract_sha256},
            metrics={
                "delimiter": str(getattr(getattr(manifest, "dialect", None), "delimiter", ",")),
                "quotechar": str(getattr(getattr(manifest, "dialect", None), "quotechar", '"')),
                "dialect_confidence": float(getattr(getattr(manifest, "dialect", None), "confidence", 0.0)),
            },
        )
    )
    reqs.append(
        _requirement(
            2,
            "scan_profile_output_contract",
            "output_contract",
            status="ready" if str(getattr(scan_parity, "status", "")) == "valid" else "blocked",
            source="validate_csv_scan_profile",
            evidence_hashes={"output_contract_sha256": output_contract_sha256},
            metrics={
                "scanner": str(getattr(scan_parity, "scanner", "")),
                "scan_row_count": int(getattr(scan_parity, "scan_row_count", 0)),
                "artifact_row_count": int(getattr(scan_parity, "artifact_row_count", 0)),
                "chunk_size": getattr(scan_parity, "chunk_size", None),
            },
            error="scan_profile_parity_not_valid" if str(getattr(scan_parity, "status", "")) != "valid" else "",
        )
    )
    reqs.append(
        _requirement(
            3,
            "row_offset_parity_contract",
            "output_contract",
            status="ready" if bool(getattr(scan_parity, "row_offsets_match", False)) else "blocked",
            source=keys["row_offsets"],
            evidence_hashes={"output_contract_sha256": output_contract_sha256},
            metrics={"row_offsets_match": bool(getattr(scan_parity, "row_offsets_match", False))},
            error="row_offset_parity_not_valid" if not bool(getattr(scan_parity, "row_offsets_match", False)) else "",
        )
    )
    reqs.append(
        _requirement(
            4,
            "row_anchor_output_contract",
            "output_contract",
            status="ready" if str(getattr(row_anchor_parity, "status", "")) == "valid" else "blocked",
            source="validate_csv_row_anchors",
            evidence_hashes={"output_contract_sha256": output_contract_sha256},
            metrics={
                "scanner": str(getattr(row_anchor_parity, "scanner", "")),
                "anchor_row_count": int(getattr(row_anchor_parity, "anchor_row_count", 0)),
                "artifact_row_count": int(getattr(row_anchor_parity, "artifact_row_count", 0)),
                "chunk_size": getattr(row_anchor_parity, "chunk_size", None),
            },
            error="row_anchor_parity_not_valid" if str(getattr(row_anchor_parity, "status", "")) != "valid" else "",
        )
    )
    reqs.append(
        _requirement(
            5,
            "chunk_boundary_state_contract",
            "kernel_state_contract",
            status="ready" if getattr(scan_parity, "chunk_size", None) is not None and getattr(row_anchor_parity, "chunk_size", None) is not None else "guarded",
            source="python.memoryview.reference",
            evidence_hashes={"failure_contract_sha256": failure_contract_sha256},
            metrics={"scan_chunk_size": getattr(scan_parity, "chunk_size", None), "anchor_chunk_size": getattr(row_anchor_parity, "chunk_size", None)},
            warning="chunk_boundary_checked_as_single_chunk" if getattr(scan_parity, "chunk_size", None) is None else "",
        )
    )
    reqs.append(
        _requirement(
            6,
            "python_reference_fallback_contract",
            "fallback_contract",
            status="ready",
            source="python.memoryview.reference",
            evidence_hashes={"failure_contract_sha256": failure_contract_sha256},
            metrics={"fallback_available": True, "native_kernel_required": False},
            fallback="python_reference_required",
        )
    )
    reqs.append(
        _requirement(
            7,
            "failure_mode_fail_closed_contract",
            "failure_contract",
            status="declared",
            source="kernel_readiness_contract",
            evidence_hashes={"failure_contract_sha256": failure_contract_sha256},
            metrics={"fail_closed": True, "fallback": "python_reference"},
        )
    )
    reqs.append(
        _requirement(
            8,
            "native_storage_hot_path_isolation_contract",
            "safety_contract",
            status="guarded" if not bool(getattr(scan_parity, "native_storage_hot_path_touched", False)) and not bool(getattr(row_anchor_parity, "native_storage_hot_path_touched", False)) else "blocked",
            source="scanner_parity_reports",
            evidence_hashes={"failure_contract_sha256": failure_contract_sha256},
            metrics={
                "scan_hot_path_touched": bool(getattr(scan_parity, "native_storage_hot_path_touched", False)),
                "anchor_hot_path_touched": bool(getattr(row_anchor_parity, "native_storage_hot_path_touched", False)),
                "native_storage_hot_path_control": False,
            },
            error="native_storage_hot_path_touched" if bool(getattr(scan_parity, "native_storage_hot_path_touched", False)) or bool(getattr(row_anchor_parity, "native_storage_hot_path_touched", False)) else "",
        )
    )
    reqs.append(
        _requirement(
            9,
            "semantic_exclusion_contract",
            "safety_contract",
            status="guarded",
            source="kernel_readiness_contract",
            evidence_hashes={"output_contract_sha256": output_contract_sha256},
            metrics={"semantic_reasoning": False, "semantic_conclusions": False, "formal_ir_committed": False},
        )
    )
    reqs.append(
        _requirement(
            10,
            "per_row_cell_write_exclusion_contract",
            "safety_contract",
            status="guarded",
            source="kernel_readiness_contract",
            evidence_hashes={"failure_contract_sha256": failure_contract_sha256},
            metrics={"per_row_writes": False, "per_cell_writes": False},
        )
    )
    ring_ready = str(getattr(ring_validation, "status", "")) == "valid" and not tuple(getattr(ring_validation, "errors", ()) or ())
    reqs.append(
        _requirement(
            11,
            "interpole_ring_readiness_contract",
            "interpole_contract",
            status="ready" if ring_ready else "blocked",
            source=str(getattr(stored_ring, "report_key", "")),
            evidence_hashes={
                "ring_fingerprint": str(getattr(ring_validation, "ring_fingerprint", "")),
                "mirror_fingerprint": str(getattr(ring_validation, "mirror_fingerprint", "")),
            },
            metrics={
                "timeline_ring_validation_status": str(getattr(ring_validation, "status", "not_checked")),
                "node_count": int(getattr(ring_validation, "node_count", 0)),
                "discrete_feedback": list(getattr(ring_validation, "discrete_feedback", ()) or ()),
            },
            error="interpole_timeline_ring_not_valid" if not ring_ready else "",
        )
    )
    reqs.append(
        _requirement(
            12,
            "benchmark_gate_shape_contract",
            "benchmark_contract",
            status="declared",
            required=True,
            source="benchmarks",
            evidence_hashes={"benchmark_contract_sha256": benchmark_contract_sha256},
            metrics={"gate_shape_only": True, "native_default_blocked_until_parity_and_throughput": True},
            warning="production_native_throughput_gate_not_run_yet",
        )
    )
    return tuple(reqs)


def _contract_fingerprint(
    *,
    csv_id: str,
    input_contract_sha256: str,
    output_contract_sha256: str,
    failure_contract_sha256: str,
    benchmark_contract_sha256: str,
    ring_validation: Any,
    scan_parity: Any,
    row_anchor_parity: Any,
    requirements: tuple[CSVKernelReadinessRequirement, ...],
) -> str:
    return _canonical_sha256(
        {
            "version": CSV_KERNEL_READINESS_VERSION,
            "csv_id": csv_id,
            "input_contract_sha256": input_contract_sha256,
            "output_contract_sha256": output_contract_sha256,
            "failure_contract_sha256": failure_contract_sha256,
            "benchmark_contract_sha256": benchmark_contract_sha256,
            "source_ring_fingerprint": str(getattr(ring_validation, "ring_fingerprint", "")),
            "source_mirror_fingerprint": str(getattr(ring_validation, "mirror_fingerprint", "")),
            "scan_parity_status": str(getattr(scan_parity, "status", "not_checked")),
            "row_anchor_parity_status": str(getattr(row_anchor_parity, "status", "not_checked")),
            "requirements": [
                {
                    "name": req.requirement_name,
                    "kind": req.requirement_kind,
                    "status": req.status,
                    "required": req.required,
                    "evidence_hashes": dict(req.evidence_hashes),
                    "metrics": dict(req.metrics),
                    "fallback": req.fallback,
                    "error": req.error,
                    "warning": req.warning,
                }
                for req in requirements
            ],
            "native_csv_kernel_implemented": False,
            "native_csv_kernel_used": False,
            "semantic_conclusions": False,
            "formal_ir_committed": False,
        }
    )


def prepare_csv_kernel_readiness_contract(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
) -> CSVKernelReadinessReport:
    """Build a no-write CSV kernel readiness contract report.

    The contract requires a committed Interpole timeline ring and fresh clean
    scan/row-anchor parity.  It only declares readiness and gates; it does not
    load or execute native kernel code.
    """
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_kernel_readiness_report_key(safe_id)
    except Exception as exc:
        return _empty_kernel_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    try:
        stored_ring = load_csv_interpole_timeline_ring_report(directory, safe_id)
    except Exception as exc:
        return _empty_kernel_report(
            safe_id,
            f"interpole_timeline_ring_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
        )

    try:
        manifest = load_csv_manifest(directory, safe_id)
        ring_validation = validate_csv_interpole_timeline_ring(directory, safe_id, chunk_size=chunk_size)
        scan_parity = validate_csv_scan_profile(directory, safe_id, chunk_size=chunk_size)
        row_anchor_parity = validate_csv_row_anchors(directory, safe_id, chunk_size=chunk_size)
    except Exception as exc:
        return _empty_kernel_report(safe_id, f"kernel_readiness_prepare_failed:{type(exc).__name__}:{exc}", report_key=report_key)

    input_contract_sha256 = _canonical_sha256(_input_contract(manifest))
    output_contract_sha256 = _canonical_sha256(_output_contract())
    failure_contract_sha256 = _canonical_sha256(_failure_contract())
    benchmark_contract_sha256 = _canonical_sha256(_benchmark_contract())
    reqs = _requirements(
        manifest=manifest,
        input_contract_sha256=input_contract_sha256,
        output_contract_sha256=output_contract_sha256,
        failure_contract_sha256=failure_contract_sha256,
        benchmark_contract_sha256=benchmark_contract_sha256,
        ring_validation=ring_validation,
        stored_ring=stored_ring,
        scan_parity=scan_parity,
        row_anchor_parity=row_anchor_parity,
    )
    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(str(v) for v in getattr(ring_validation, "errors", ()) or ())
    errors.extend(str(v) for v in getattr(scan_parity, "errors", ()) or ())
    errors.extend(str(v) for v in getattr(row_anchor_parity, "errors", ()) or ())
    if stored_ring.status not in {"ring_committed", "valid"}:
        errors.append(f"stored_interpole_timeline_ring_not_committed:{stored_ring.status}")
    for req in reqs:
        if req.error:
            errors.append(f"kernel_requirement:{req.requirement_name}:{req.error}")
        if req.warning:
            warnings.append(f"kernel_requirement:{req.requirement_name}:{req.warning}")
    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    required_count = sum(1 for req in reqs if req.required)
    ready_count = sum(1 for req in reqs if req.required and req.ok)
    blocked_count = sum(1 for req in reqs if req.required and not req.ok)
    warning_count = sum(1 for req in reqs if req.warning)
    fingerprint = _contract_fingerprint(
        csv_id=safe_id,
        input_contract_sha256=input_contract_sha256,
        output_contract_sha256=output_contract_sha256,
        failure_contract_sha256=failure_contract_sha256,
        benchmark_contract_sha256=benchmark_contract_sha256,
        ring_validation=ring_validation,
        scan_parity=scan_parity,
        row_anchor_parity=row_anchor_parity,
        requirements=reqs,
    )
    status = "kernel_contract_ready" if not unique_errors and blocked_count == 0 else "blocked"
    return CSVKernelReadinessReport(
        csv_id=safe_id,
        status=status,
        kernel_readiness_version=CSV_KERNEL_READINESS_VERSION,
        report_key=report_key,
        mode="kernel_readiness_prepare",
        contract_fingerprint=fingerprint,
        input_contract_sha256=input_contract_sha256,
        output_contract_sha256=output_contract_sha256,
        failure_contract_sha256=failure_contract_sha256,
        benchmark_contract_sha256=benchmark_contract_sha256,
        source_timeline_ring_report_key=stored_ring.report_key,
        source_ring_fingerprint=ring_validation.ring_fingerprint,
        source_mirror_fingerprint=ring_validation.mirror_fingerprint,
        timeline_ring_validation_status=ring_validation.status,
        scan_parity_status=scan_parity.status,
        row_anchor_parity_status=row_anchor_parity.status,
        requirements=reqs,
        requirement_count=len(reqs),
        required_count=required_count,
        ready_count=ready_count,
        blocked_count=blocked_count,
        warning_count=warning_count,
        errors=unique_errors,
        warnings=unique_warnings,
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_implemented=False,
        native_csv_kernel_used=False,
        native_storage_hot_path_touched=False,
        python_reference_fallback_available=True,
        per_row_writes=False,
        per_cell_writes=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=True,
        invertible_mirror_feedback=True,
        formal_ir_committed=False,
    )


def commit_csv_kernel_readiness_contract_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
    overwrite: bool = False,
) -> CSVKernelReadinessReport:
    """Persist a compact derived CSV kernel readiness contract report."""
    report = prepare_csv_kernel_readiness_contract(directory, csv_id, chunk_size=chunk_size)
    if not report.ok:
        return report
    committed = CSVKernelReadinessReport(
        csv_id=report.csv_id,
        status="kernel_contract_committed",
        kernel_readiness_version=report.kernel_readiness_version,
        report_key=report.report_key,
        mode="kernel_readiness_commit",
        contract_fingerprint=report.contract_fingerprint,
        input_contract_sha256=report.input_contract_sha256,
        output_contract_sha256=report.output_contract_sha256,
        failure_contract_sha256=report.failure_contract_sha256,
        benchmark_contract_sha256=report.benchmark_contract_sha256,
        source_timeline_ring_report_key=report.source_timeline_ring_report_key,
        source_ring_fingerprint=report.source_ring_fingerprint,
        source_mirror_fingerprint=report.source_mirror_fingerprint,
        timeline_ring_validation_status=report.timeline_ring_validation_status,
        scan_parity_status=report.scan_parity_status,
        row_anchor_parity_status=report.row_anchor_parity_status,
        requirements=report.requirements,
        requirement_count=report.requirement_count,
        required_count=report.required_count,
        ready_count=report.ready_count,
        blocked_count=report.blocked_count,
        warning_count=report.warning_count,
        warnings=report.warnings,
        tds_artifact_writes=1,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_implemented=False,
        native_csv_kernel_used=False,
        native_storage_hot_path_touched=False,
        python_reference_fallback_available=True,
        per_row_writes=False,
        per_cell_writes=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=True,
        invertible_mirror_feedback=True,
        formal_ir_committed=False,
    )
    result: TDSResult = directory.write_json(committed.report_key, committed.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return CSVKernelReadinessReport(
            csv_id=report.csv_id,
            status="invalid",
            kernel_readiness_version=report.kernel_readiness_version,
            report_key=report.report_key,
            mode="kernel_readiness_commit",
            contract_fingerprint=report.contract_fingerprint,
            input_contract_sha256=report.input_contract_sha256,
            output_contract_sha256=report.output_contract_sha256,
            failure_contract_sha256=report.failure_contract_sha256,
            benchmark_contract_sha256=report.benchmark_contract_sha256,
            source_timeline_ring_report_key=report.source_timeline_ring_report_key,
            source_ring_fingerprint=report.source_ring_fingerprint,
            source_mirror_fingerprint=report.source_mirror_fingerprint,
            timeline_ring_validation_status=report.timeline_ring_validation_status,
            scan_parity_status=report.scan_parity_status,
            row_anchor_parity_status=report.row_anchor_parity_status,
            requirements=report.requirements,
            requirement_count=report.requirement_count,
            required_count=report.required_count,
            ready_count=report.ready_count,
            blocked_count=report.blocked_count,
            warning_count=report.warning_count,
            errors=(f"kernel_readiness_report_write_failed:{result.code}:{result.message}",),
            warnings=report.warnings,
            native_storage_writes=False,
            native_c_engine_changed=False,
            native_csv_kernel_implemented=False,
            native_csv_kernel_used=False,
            native_storage_hot_path_touched=False,
            python_reference_fallback_available=True,
            per_row_writes=False,
            per_cell_writes=False,
            semantic_reasoning=False,
            semantic_conclusions=False,
            formal_ir_committed=False,
        )
    return committed


def load_csv_kernel_readiness_contract_report(directory: TDSDirectory, csv_id: str) -> CSVKernelReadinessReport:
    """Load a persisted CSV kernel readiness contract report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_kernel_readiness_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV kernel readiness report {key!r} is not a JSON object")
    return CSVKernelReadinessReport.from_mapping(value)


def validate_csv_kernel_readiness_contract(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
) -> CSVKernelReadinessReport:
    """Validate a persisted kernel readiness report against fresh evidence."""
    try:
        stored = load_csv_kernel_readiness_contract_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_kernel_readiness_report_key(csv_id)
        except Exception:
            report_key = ""
        return _empty_kernel_report(str(csv_id), f"kernel_readiness_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_kernel_readiness_contract(directory, csv_id, chunk_size=chunk_size)
    errors: list[str] = list(fresh.errors)
    warnings: list[str] = list(dict.fromkeys(tuple(stored.warnings) + tuple(fresh.warnings)))
    if stored.status not in {"kernel_contract_committed", "valid"}:
        errors.append(f"stored_kernel_readiness_not_committed:{stored.status}")
    if stored.contract_fingerprint != fresh.contract_fingerprint:
        errors.append("kernel_readiness_contract_fingerprint_drift")
    if stored.source_ring_fingerprint != fresh.source_ring_fingerprint:
        errors.append("kernel_readiness_source_ring_fingerprint_drift")
    if stored.source_mirror_fingerprint != fresh.source_mirror_fingerprint:
        errors.append("kernel_readiness_source_mirror_fingerprint_drift")
    if stored.requirement_count != fresh.requirement_count:
        errors.append("kernel_readiness_requirement_count_drift")
    if stored.input_contract_sha256 != fresh.input_contract_sha256:
        errors.append("kernel_readiness_input_contract_drift")
    if stored.output_contract_sha256 != fresh.output_contract_sha256:
        errors.append("kernel_readiness_output_contract_drift")
    if stored.failure_contract_sha256 != fresh.failure_contract_sha256:
        errors.append("kernel_readiness_failure_contract_drift")
    if stored.benchmark_contract_sha256 != fresh.benchmark_contract_sha256:
        errors.append("kernel_readiness_benchmark_contract_drift")

    unique_errors = tuple(dict.fromkeys(errors))
    status = "valid" if not unique_errors else "drifted"
    return CSVKernelReadinessReport(
        csv_id=fresh.csv_id,
        status=status,
        kernel_readiness_version=fresh.kernel_readiness_version,
        report_key=stored.report_key,
        mode="validation",
        contract_fingerprint=fresh.contract_fingerprint,
        input_contract_sha256=fresh.input_contract_sha256,
        output_contract_sha256=fresh.output_contract_sha256,
        failure_contract_sha256=fresh.failure_contract_sha256,
        benchmark_contract_sha256=fresh.benchmark_contract_sha256,
        source_timeline_ring_report_key=fresh.source_timeline_ring_report_key,
        source_ring_fingerprint=fresh.source_ring_fingerprint,
        source_mirror_fingerprint=fresh.source_mirror_fingerprint,
        timeline_ring_validation_status=fresh.timeline_ring_validation_status,
        scan_parity_status=fresh.scan_parity_status,
        row_anchor_parity_status=fresh.row_anchor_parity_status,
        requirements=fresh.requirements,
        requirement_count=fresh.requirement_count,
        required_count=fresh.required_count,
        ready_count=fresh.ready_count,
        blocked_count=fresh.blocked_count,
        warning_count=fresh.warning_count,
        errors=unique_errors,
        warnings=tuple(dict.fromkeys(warnings)),
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_implemented=False,
        native_csv_kernel_used=False,
        native_storage_hot_path_touched=False,
        python_reference_fallback_available=True,
        per_row_writes=False,
        per_cell_writes=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=True,
        invertible_mirror_feedback=True,
        formal_ir_committed=False,
    )


def csv_kernel_readiness_contract_summary(report: CSVKernelReadinessReport) -> dict[str, Any]:
    """Return a compact API/dashboard summary for a kernel readiness report."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "mode": report.mode,
        "kernel_readiness_version": report.kernel_readiness_version,
        "contract_fingerprint": report.contract_fingerprint,
        "input_contract_sha256": report.input_contract_sha256,
        "output_contract_sha256": report.output_contract_sha256,
        "failure_contract_sha256": report.failure_contract_sha256,
        "benchmark_contract_sha256": report.benchmark_contract_sha256,
        "source_ring_fingerprint": report.source_ring_fingerprint,
        "source_mirror_fingerprint": report.source_mirror_fingerprint,
        "timeline_ring_validation_status": report.timeline_ring_validation_status,
        "scan_parity_status": report.scan_parity_status,
        "row_anchor_parity_status": report.row_anchor_parity_status,
        "requirement_count": report.requirement_count,
        "required_count": report.required_count,
        "ready_count": report.ready_count,
        "blocked_count": report.blocked_count,
        "warning_count": report.warning_count,
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_writes": report.native_storage_writes,
        "native_c_engine_changed": report.native_c_engine_changed,
        "native_csv_kernel_implemented": report.native_csv_kernel_implemented,
        "native_csv_kernel_used": report.native_csv_kernel_used,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "python_reference_fallback_available": report.python_reference_fallback_available,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "semantic_reasoning": report.semantic_reasoning,
        "semantic_conclusions": report.semantic_conclusions,
        "formal_ir_committed": report.formal_ir_committed,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
    }

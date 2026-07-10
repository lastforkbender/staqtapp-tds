"""CSV Interpole foundation for staged semantic-evolution readiness.

The Interpole layer sits after native-storage commit/revalidation and before
formal semantic IR.  It stores evidence-bound timeline readiness facts and, in
the determinant-vector release, optional compact signals that measure semantic
evolution readiness without declaring meaning, committing IR candidates, or
running invertible mirror feedback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any, Mapping

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.tds_json import dumps_canonical

from .exporter import export_canonical_csv
from .importer import load_csv_manifest
from .manifest import artifact_keys, validate_csv_id
from .storage_adapter import (
    load_csv_native_storage_commit_report,
    load_csv_native_storage_revalidation_report,
    validate_csv_native_storage_revalidation,
)
from .validator import validate_csv_artifacts


CSV_INTERPOLE_TIMELINE_VERSION = "1.0"


_INTERPOLE_FOUNDATION_STAGE_NAMES: tuple[str, ...] = (
    "evidence_baseline",
    "structure_baseline",
    "canonical_export_baseline",
    "native_storage_commit_baseline",
    "native_revalidation_baseline",
    "ir_readiness_baseline",
)


def csv_interpole_timeline_report_key(csv_id: str) -> str:
    """Return the durable key for a CSV Interpole timeline foundation report."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__interpole_timeline_report.json"


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(dumps_canonical(value)[0]).hexdigest()


def _dict_from_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(k): v for k, v in (value or {}).items()}


def _string_dict_from_mapping(value: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (value or {}).items()}


@dataclass(frozen=True, slots=True)
class CSVInterpoleSignature:
    """One compact signature for an Interpole timeline stage.

    A signature records evidence-derived readiness facts for later semantic
    evolution.  It is not a semantic conclusion and does not declare column,
    row, or cell meaning.
    """

    stage_name: str
    signature_sha256: str
    signature_kind: str
    source_hashes: Mapping[str, str] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    semantic_conclusion: bool = False
    determinant_vector: bool = False
    ir_candidate: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_hashes"] = dict(self.source_hashes)
        data["metrics"] = dict(self.metrics)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleSignature":
        return cls(
            stage_name=str(data.get("stage_name", "")),
            signature_sha256=str(data.get("signature_sha256", "")),
            signature_kind=str(data.get("signature_kind", "baseline")),
            source_hashes=_string_dict_from_mapping(data.get("source_hashes", {}) or {}),
            metrics=_dict_from_mapping(data.get("metrics", {}) or {}),
            semantic_conclusion=bool(data.get("semantic_conclusion", False)),
            determinant_vector=bool(data.get("determinant_vector", False)),
            ir_candidate=bool(data.get("ir_candidate", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleStage:
    """One ordered foundation stage in a CSV Interpole timeline."""

    stage_index: int
    stage_name: str
    status: str
    signature: CSVInterpoleSignature
    source_key: str = ""
    source_status: str = "ready"
    error: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status in {"ready", "stable", "skipped_optional"} and not self.error

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signature"] = self.signature.to_dict()
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleStage":
        return cls(
            stage_index=int(data.get("stage_index", 0)),
            stage_name=str(data.get("stage_name", "")),
            status=str(data.get("status", "blocked")),
            signature=CSVInterpoleSignature.from_mapping(data.get("signature", {}) or {}),
            source_key=str(data.get("source_key", "")),
            source_status=str(data.get("source_status", "ready")),
            error=str(data.get("error", "")),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleTimeline:
    """Ordered staged baseline timeline for future semantic propagation."""

    csv_id: str
    timeline_fingerprint: str
    stages: tuple[CSVInterpoleStage, ...]
    stage_count: int
    ready_stage_count: int
    blocked_stage_count: int
    missing_stage_count: int
    drifted_stage_count: int

    @property
    def ok(self) -> bool:
        return self.stage_count == self.ready_stage_count and self.blocked_stage_count == 0 and self.missing_stage_count == 0 and self.drifted_stage_count == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stages"] = [stage.to_dict() for stage in self.stages]
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleTimeline":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            timeline_fingerprint=str(data.get("timeline_fingerprint", "")),
            stages=tuple(CSVInterpoleStage.from_mapping(v) for v in data.get("stages", []) or []),
            stage_count=int(data.get("stage_count", 0)),
            ready_stage_count=int(data.get("ready_stage_count", 0)),
            blocked_stage_count=int(data.get("blocked_stage_count", 0)),
            missing_stage_count=int(data.get("missing_stage_count", 0)),
            drifted_stage_count=int(data.get("drifted_stage_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleTimelineReport:
    """CSV Interpole foundation report.

    The report stores readiness signatures for later semantic evolution.  It is
    deliberately evidence-neutral: no determinant vectors, invertible mirrors,
    formal IR candidates, or semantic conclusions are emitted by the foundation timeline.
    """

    csv_id: str
    status: str
    interpole_version: str
    report_key: str
    mode: str
    timeline: CSVInterpoleTimeline
    source_native_commit_report_key: str = ""
    source_revalidation_report_key: str = ""
    source_revalidation_fingerprint: str = ""
    artifact_validation_status: str = "not_checked"
    native_revalidation_status: str = "not_checked"
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
    semantic_conclusions: bool = False
    determinant_vectoring: bool = False
    timeline_ring_materialized: bool = False
    invertible_mirror_feedback: bool = False
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"interpole_ready", "timeline_committed", "valid"} and not self.errors

    @property
    def timeline_fingerprint(self) -> str:
        return self.timeline.timeline_fingerprint

    @property
    def stage_count(self) -> int:
        return self.timeline.stage_count

    @property
    def ready_stage_count(self) -> int:
        return self.timeline.ready_stage_count

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timeline"] = self.timeline.to_dict()
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["timeline_fingerprint"] = self.timeline_fingerprint
        data["stage_count"] = self.stage_count
        data["ready_stage_count"] = self.ready_stage_count
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleTimelineReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            interpole_version=str(data.get("interpole_version", CSV_INTERPOLE_TIMELINE_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "unknown")),
            timeline=CSVInterpoleTimeline.from_mapping(data.get("timeline", {}) or {}),
            source_native_commit_report_key=str(data.get("source_native_commit_report_key", "")),
            source_revalidation_report_key=str(data.get("source_revalidation_report_key", "")),
            source_revalidation_fingerprint=str(data.get("source_revalidation_fingerprint", "")),
            artifact_validation_status=str(data.get("artifact_validation_status", "not_checked")),
            native_revalidation_status=str(data.get("native_revalidation_status", "not_checked")),
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
            semantic_conclusions=bool(data.get("semantic_conclusions", False)),
            determinant_vectoring=bool(data.get("determinant_vectoring", False)),
            timeline_ring_materialized=bool(data.get("timeline_ring_materialized", False)),
            invertible_mirror_feedback=bool(data.get("invertible_mirror_feedback", False)),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
        )


def _signature(stage_name: str, *, source_hashes: Mapping[str, str] | None = None, metrics: Mapping[str, Any] | None = None, signature_kind: str = "baseline") -> CSVInterpoleSignature:
    payload = {
        "version": CSV_INTERPOLE_TIMELINE_VERSION,
        "stage_name": stage_name,
        "signature_kind": signature_kind,
        "source_hashes": dict(source_hashes or {}),
        "metrics": dict(metrics or {}),
        "semantic_conclusion": False,
        "determinant_vector": False,
        "ir_candidate": False,
    }
    return CSVInterpoleSignature(
        stage_name=stage_name,
        signature_sha256=_canonical_sha256(payload),
        signature_kind=signature_kind,
        source_hashes=dict(source_hashes or {}),
        metrics=dict(metrics or {}),
        semantic_conclusion=False,
        determinant_vector=False,
        ir_candidate=False,
    )


def _stage(index: int, stage_name: str, *, source_hashes: Mapping[str, str] | None = None, metrics: Mapping[str, Any] | None = None, source_key: str = "", source_status: str = "ready", status: str = "ready", error: str = "", warnings: tuple[str, ...] = ()) -> CSVInterpoleStage:
    return CSVInterpoleStage(
        stage_index=index,
        stage_name=stage_name,
        status=status,
        signature=_signature(stage_name, source_hashes=source_hashes, metrics=metrics),
        source_key=source_key,
        source_status=source_status,
        error=error,
        warnings=warnings,
    )


def _timeline(csv_id: str, stages: tuple[CSVInterpoleStage, ...]) -> CSVInterpoleTimeline:
    ready_count = sum(1 for stage in stages if stage.status in {"ready", "stable"} and not stage.error)
    blocked_count = sum(1 for stage in stages if stage.status == "blocked")
    missing_count = sum(1 for stage in stages if stage.status == "missing")
    drifted_count = sum(1 for stage in stages if stage.status == "drifted")
    fingerprint = _canonical_sha256(
        {
            "version": CSV_INTERPOLE_TIMELINE_VERSION,
            "csv_id": csv_id,
            "stage_order": [stage.stage_name for stage in stages],
            "signatures": [stage.signature.signature_sha256 for stage in stages],
            "statuses": [stage.status for stage in stages],
            "errors": [stage.error for stage in stages],
        }
    )
    return CSVInterpoleTimeline(
        csv_id=csv_id,
        timeline_fingerprint=fingerprint,
        stages=stages,
        stage_count=len(stages),
        ready_stage_count=ready_count,
        blocked_stage_count=blocked_count,
        missing_stage_count=missing_count,
        drifted_stage_count=drifted_count,
    )


def _empty_timeline(csv_id: str) -> CSVInterpoleTimeline:
    return _timeline(str(csv_id), tuple())


def _invalid_interpole_report(csv_id: str, error: str, *, report_key: str = "") -> CSVInterpoleTimelineReport:
    return CSVInterpoleTimelineReport(
        csv_id=str(csv_id),
        status="invalid",
        interpole_version=CSV_INTERPOLE_TIMELINE_VERSION,
        report_key=report_key,
        mode="invalid",
        timeline=_empty_timeline(str(csv_id)),
        errors=(error,),
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=False,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )


def _build_interpole_stages(
    directory: TDSDirectory,
    csv_id: str,
    *,
    artifact_validation_status: str,
    native_revalidation_status: str,
    revalidation_clean: bool,
    stored_revalidation: Any,
    native_commit: Any,
) -> tuple[CSVInterpoleStage, ...]:
    manifest = load_csv_manifest(directory, csv_id)
    keys = artifact_keys(csv_id)
    row_offsets = directory.read_value(keys["row_offsets"])
    content_hashes = directory.read_value(keys["content_hashes"])
    dialect = directory.read_value(keys["dialect"])
    canonical = export_canonical_csv(directory, csv_id)

    row_offsets_hash = _canonical_sha256(row_offsets)
    content_hashes_hash = _canonical_sha256(content_hashes)
    dialect_hash = _canonical_sha256(dialect)
    canonical_sha256 = hashlib.sha256(canonical.encode(manifest.encoding)).hexdigest()

    revalidation_errors = tuple(str(error) for error in getattr(stored_revalidation, "errors", ()) or ())
    native_commit_errors = tuple(str(error) for error in getattr(native_commit, "errors", ()) or ())

    stages = (
        _stage(
            0,
            "evidence_baseline",
            source_key=keys["manifest"],
            source_hashes={"raw_sha256": manifest.raw_sha256},
            metrics={
                "source_name": manifest.source_name,
                "encoding": manifest.encoding,
                "raw_size": manifest.raw_size,
                "row_count": manifest.row_count,
                "column_count": manifest.column_count,
                "has_header": manifest.has_header,
                "artifact_count": 6,
            },
        ),
        _stage(
            1,
            "structure_baseline",
            source_key=keys["row_offsets"],
            source_hashes={
                "row_offsets_sha256": row_offsets_hash,
                "content_hashes_sha256": content_hashes_hash,
                "dialect_sha256": dialect_hash,
            },
            metrics={
                "row_count": manifest.row_count,
                "column_count": manifest.column_count,
                "dialect_confidence": float(manifest.dialect.confidence),
                "row_offset_count": int((row_offsets or {}).get("row_count", 0)) if isinstance(row_offsets, dict) else 0,
                "artifact_validation_status": artifact_validation_status,
            },
            status="ready" if artifact_validation_status == "valid" else "blocked",
            error="artifact_validation_not_clean" if artifact_validation_status != "valid" else "",
        ),
        _stage(
            2,
            "canonical_export_baseline",
            source_key=keys["raw"],
            source_hashes={"raw_sha256": manifest.raw_sha256, "canonical_sha256": canonical_sha256},
            metrics={
                "canonical_size": len(canonical.encode(manifest.encoding)),
                "canonical_line_count": canonical.count("\n"),
                "canonical_materialized": False,
            },
        ),
        _stage(
            3,
            "native_storage_commit_baseline",
            source_key=getattr(native_commit, "report_key", ""),
            source_hashes={
                "replay_fingerprint": str(getattr(native_commit, "replay_fingerprint", "")),
                "transaction_id": str(getattr(native_commit, "transaction_id", "")),
            },
            metrics={
                "native_commit_status": str(getattr(native_commit, "status", "not_checked")),
                "entry_count": int(getattr(native_commit, "entry_count", 0)),
                "committed_count": int(getattr(native_commit, "committed_count", 0)),
                "skipped_optional_count": int(getattr(native_commit, "skipped_optional_count", 0)),
                "native_storage_entry_writes": int(getattr(native_commit, "native_storage_entry_writes", 0)),
            },
            status="ready" if str(getattr(native_commit, "status", "")) == "native_storage_committed" and not native_commit_errors else "blocked",
            error="native_commit_not_clean" if str(getattr(native_commit, "status", "")) != "native_storage_committed" or native_commit_errors else "",
            warnings=tuple(str(w) for w in getattr(native_commit, "warnings", ()) or ()),
        ),
        _stage(
            4,
            "native_revalidation_baseline",
            source_key=getattr(stored_revalidation, "report_key", ""),
            source_hashes={
                "revalidation_fingerprint": str(getattr(stored_revalidation, "revalidation_fingerprint", "")),
                "replay_fingerprint": str(getattr(stored_revalidation, "replay_fingerprint", "")),
            },
            metrics={
                "native_revalidation_status": native_revalidation_status,
                "stored_revalidation_status": str(getattr(stored_revalidation, "status", "not_checked")),
                "entry_count": int(getattr(stored_revalidation, "entry_count", 0)),
                "verified_count": int(getattr(stored_revalidation, "verified_count", 0)),
                "source_drift_count": int(getattr(stored_revalidation, "source_drift_count", 0)),
                "storage_drift_count": int(getattr(stored_revalidation, "storage_drift_count", 0)),
                "proof_drift_count": int(getattr(stored_revalidation, "proof_drift_count", 0)),
                "skipped_optional_count": int(getattr(stored_revalidation, "skipped_optional_count", 0)),
            },
            status="ready" if revalidation_clean and not revalidation_errors else "drifted",
            error="native_revalidation_not_clean" if not revalidation_clean or revalidation_errors else "",
            warnings=tuple(str(w) for w in getattr(stored_revalidation, "warnings", ()) or ()),
        ),
        _stage(
            5,
            "ir_readiness_baseline",
            source_key=getattr(stored_revalidation, "report_key", ""),
            source_hashes={
                "raw_sha256": manifest.raw_sha256,
                "timeline_input_revalidation_fingerprint": str(getattr(stored_revalidation, "revalidation_fingerprint", "")),
            },
            metrics={
                "ready_for_future_determinants": bool(artifact_validation_status == "valid" and revalidation_clean),
                "semantic_conclusions": False,
                "determinant_vectoring": False,
                "timeline_ring_materialized": False,
                "invertible_mirror_feedback": False,
                "formal_ir_committed": False,
            },
            status="ready" if artifact_validation_status == "valid" and revalidation_clean else "blocked",
            error="ir_readiness_blocked_by_drift_or_validation" if artifact_validation_status != "valid" or not revalidation_clean else "",
        ),
    )
    return stages


def prepare_csv_interpole_timeline(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVInterpoleTimelineReport:
    """Build a no-write CSV Interpole foundation timeline.

    The timeline requires a persisted native-storage revalidation guard.  This
    keeps Interpole above the proven storage path and prevents semantic-evolution
    readiness from being generated on top of uncommitted or drifted evidence.
    """
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_interpole_timeline_report_key(safe_id)
    except Exception as exc:
        return _invalid_interpole_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    try:
        stored_revalidation = load_csv_native_storage_revalidation_report(directory, safe_id)
    except Exception as exc:
        return _invalid_interpole_report(
            safe_id,
            f"native_storage_revalidation_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
        )

    try:
        native_commit = load_csv_native_storage_commit_report(directory, safe_id)
    except Exception as exc:
        return _invalid_interpole_report(
            safe_id,
            f"native_storage_commit_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
        )

    artifact_validation = validate_csv_artifacts(directory, safe_id)
    native_revalidation = validate_csv_native_storage_revalidation(directory, safe_id, chunk_size=chunk_size, encoding=encoding)
    errors: list[str] = []
    warnings: list[str] = []
    if not artifact_validation.ok:
        errors.extend(f"artifact_validation:{error}" for error in artifact_validation.errors)
        warnings.extend(str(warning) for warning in artifact_validation.warnings)
    if not native_revalidation.ok:
        errors.extend(f"native_revalidation:{error}" for error in native_revalidation.errors)
        warnings.extend(str(warning) for warning in native_revalidation.warnings)
    if stored_revalidation.status not in {"revalidated", "valid"}:
        errors.append(f"stored_revalidation_not_clean:{stored_revalidation.status}")
    if stored_revalidation.revalidation_fingerprint != native_revalidation.revalidation_fingerprint:
        errors.append("stored_revalidation_fingerprint_mismatch")

    try:
        stages = _build_interpole_stages(
            directory,
            safe_id,
            artifact_validation_status=artifact_validation.status,
            native_revalidation_status=native_revalidation.status,
            revalidation_clean=native_revalidation.ok and stored_revalidation.status in {"revalidated", "valid"},
            stored_revalidation=stored_revalidation,
            native_commit=native_commit,
        )
    except Exception as exc:
        return _invalid_interpole_report(safe_id, f"interpole_stage_build_failed:{type(exc).__name__}:{exc}", report_key=report_key)

    timeline = _timeline(safe_id, stages)
    for stage in stages:
        if stage.error:
            errors.append(f"interpole_stage:{stage.stage_name}:{stage.status}:{stage.error}")
        warnings.extend(stage.warnings)
    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    status = "interpole_ready" if not unique_errors and timeline.ok else "drifted"
    return CSVInterpoleTimelineReport(
        csv_id=safe_id,
        status=status,
        interpole_version=CSV_INTERPOLE_TIMELINE_VERSION,
        report_key=report_key,
        mode="timeline_prepare",
        timeline=timeline,
        source_native_commit_report_key=native_commit.report_key,
        source_revalidation_report_key=stored_revalidation.report_key,
        source_revalidation_fingerprint=stored_revalidation.revalidation_fingerprint,
        artifact_validation_status=artifact_validation.status,
        native_revalidation_status=native_revalidation.status,
        errors=unique_errors,
        warnings=unique_warnings,
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=False,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )


def commit_csv_interpole_timeline_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    overwrite: bool = False,
    encoding: str = "utf-8",
) -> CSVInterpoleTimelineReport:
    """Persist a compact derived CSV Interpole foundation timeline report."""
    report = prepare_csv_interpole_timeline(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    if not report.ok:
        return report
    committed = CSVInterpoleTimelineReport(
        csv_id=report.csv_id,
        status="timeline_committed",
        interpole_version=report.interpole_version,
        report_key=report.report_key,
        mode="timeline_commit",
        timeline=report.timeline,
        source_native_commit_report_key=report.source_native_commit_report_key,
        source_revalidation_report_key=report.source_revalidation_report_key,
        source_revalidation_fingerprint=report.source_revalidation_fingerprint,
        artifact_validation_status=report.artifact_validation_status,
        native_revalidation_status=report.native_revalidation_status,
        warnings=report.warnings,
        tds_artifact_writes=1,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=False,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )
    result: TDSResult = directory.write_json(committed.report_key, committed.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return CSVInterpoleTimelineReport(
            csv_id=report.csv_id,
            status="invalid",
            interpole_version=report.interpole_version,
            report_key=report.report_key,
            mode="timeline_commit",
            timeline=report.timeline,
            source_native_commit_report_key=report.source_native_commit_report_key,
            source_revalidation_report_key=report.source_revalidation_report_key,
            source_revalidation_fingerprint=report.source_revalidation_fingerprint,
            artifact_validation_status=report.artifact_validation_status,
            native_revalidation_status=report.native_revalidation_status,
            errors=(f"interpole_timeline_report_write_failed:{result.code}:{result.message}",),
            warnings=report.warnings,
            tds_artifact_writes=0,
            native_storage_writes=False,
            native_c_engine_changed=False,
            native_csv_kernel_used=False,
            per_row_writes=False,
            per_cell_writes=False,
            native_storage_hot_path_touched=False,
            semantic_reasoning=False,
            semantic_conclusions=False,
            determinant_vectoring=False,
            timeline_ring_materialized=False,
            invertible_mirror_feedback=False,
            formal_ir_committed=False,
        )
    return committed


def load_csv_interpole_timeline_report(directory: TDSDirectory, csv_id: str) -> CSVInterpoleTimelineReport:
    """Load a persisted CSV Interpole timeline foundation report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_interpole_timeline_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV Interpole timeline report {key!r} is not a JSON object")
    return CSVInterpoleTimelineReport.from_mapping(value)


def validate_csv_interpole_timeline(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVInterpoleTimelineReport:
    """Validate a persisted Interpole timeline against a fresh no-write timeline."""
    try:
        stored = load_csv_interpole_timeline_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_interpole_timeline_report_key(csv_id)
        except Exception:
            report_key = ""
        return _invalid_interpole_report(str(csv_id), f"interpole_timeline_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_interpole_timeline(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    errors: list[str] = list(fresh.errors)
    warnings: list[str] = list(dict.fromkeys(tuple(stored.warnings) + tuple(fresh.warnings)))
    if stored.status not in {"timeline_committed", "valid"}:
        errors.append(f"stored_interpole_timeline_not_committed:{stored.status}")
    if stored.timeline_fingerprint != fresh.timeline_fingerprint:
        errors.append("interpole_timeline_fingerprint_drift")
    if stored.source_revalidation_fingerprint != fresh.source_revalidation_fingerprint:
        errors.append("interpole_source_revalidation_fingerprint_drift")
    if stored.timeline.stage_count != fresh.timeline.stage_count:
        errors.append("interpole_stage_count_drift")

    unique_errors = tuple(dict.fromkeys(errors))
    status = "valid" if not unique_errors else "drifted"
    return CSVInterpoleTimelineReport(
        csv_id=fresh.csv_id,
        status=status,
        interpole_version=fresh.interpole_version,
        report_key=stored.report_key,
        mode="validation",
        timeline=fresh.timeline,
        source_native_commit_report_key=fresh.source_native_commit_report_key,
        source_revalidation_report_key=fresh.source_revalidation_report_key,
        source_revalidation_fingerprint=fresh.source_revalidation_fingerprint,
        artifact_validation_status=fresh.artifact_validation_status,
        native_revalidation_status=fresh.native_revalidation_status,
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
        semantic_conclusions=False,
        determinant_vectoring=False,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )


def csv_interpole_timeline_summary(report: CSVInterpoleTimelineReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for an Interpole foundation report."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "mode": report.mode,
        "interpole_version": report.interpole_version,
        "timeline_fingerprint": report.timeline_fingerprint,
        "stage_count": report.stage_count,
        "ready_stage_count": report.ready_stage_count,
        "blocked_stage_count": report.timeline.blocked_stage_count,
        "missing_stage_count": report.timeline.missing_stage_count,
        "drifted_stage_count": report.timeline.drifted_stage_count,
        "artifact_validation_status": report.artifact_validation_status,
        "native_revalidation_status": report.native_revalidation_status,
        "source_revalidation_fingerprint": report.source_revalidation_fingerprint,
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_writes": report.native_storage_writes,
        "native_c_engine_changed": report.native_c_engine_changed,
        "native_csv_kernel_used": report.native_csv_kernel_used,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
        "semantic_conclusions": report.semantic_conclusions,
        "determinant_vectoring": report.determinant_vectoring,
        "timeline_ring_materialized": report.timeline_ring_materialized,
        "invertible_mirror_feedback": report.invertible_mirror_feedback,
        "formal_ir_committed": report.formal_ir_committed,
    }



CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION = "1.0"


_DETERMINANT_STAGE_ORDER: tuple[str, ...] = _INTERPOLE_FOUNDATION_STAGE_NAMES


def csv_interpole_determinant_vector_report_key(csv_id: str) -> str:
    """Return the durable key for a CSV Interpole determinant vector report."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__interpole_determinant_vector_report.json"


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def _ratio(numerator: Any, denominator: Any, *, empty_value: float = 0.0) -> float:
    try:
        den = float(denominator)
        num = float(numerator)
    except (TypeError, ValueError):
        return empty_value
    if den <= 0.0:
        return empty_value
    return _clamp01(num / den)


def _direction_for_magnitude(magnitude: float) -> str:
    if magnitude >= 0.875:
        return "strengthening"
    if magnitude >= 0.5:
        return "stable"
    if magnitude > 0.0:
        return "weakening"
    return "blocked"


@dataclass(frozen=True, slots=True)
class CSVInterpoleDeterminantSignal:
    """One bounded determinant signal derived from an Interpole stage.

    Signals are compact, normalized evidence measurements.  They intentionally
    do not infer schema, type, entity, row, or cell semantics.
    """

    signal_name: str
    signal_kind: str
    source_stage_name: str
    source_stage_index: int
    source_signature_sha256: str
    magnitude: float
    direction: str
    confidence: float
    weight: float = 1.0
    evidence_hashes: Mapping[str, str] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    semantic_conclusion: bool = False
    schema_inference: bool = False
    type_inference: bool = False
    entity_inference: bool = False
    ir_candidate: bool = False

    @property
    def weighted_magnitude(self) -> float:
        return _clamp01(self.magnitude) * _clamp01(self.weight)

    @property
    def ok(self) -> bool:
        return (
            0.0 <= self.magnitude <= 1.0
            and 0.0 <= self.confidence <= 1.0
            and 0.0 <= self.weight <= 1.0
            and not self.semantic_conclusion
            and not self.schema_inference
            and not self.type_inference
            and not self.entity_inference
            and not self.ir_candidate
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_hashes"] = dict(self.evidence_hashes)
        data["metrics"] = dict(self.metrics)
        data["weighted_magnitude"] = self.weighted_magnitude
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleDeterminantSignal":
        return cls(
            signal_name=str(data.get("signal_name", "")),
            signal_kind=str(data.get("signal_kind", "determinant")),
            source_stage_name=str(data.get("source_stage_name", "")),
            source_stage_index=int(data.get("source_stage_index", 0)),
            source_signature_sha256=str(data.get("source_signature_sha256", "")),
            magnitude=_clamp01(data.get("magnitude", 0.0)),
            direction=str(data.get("direction", "blocked")),
            confidence=_clamp01(data.get("confidence", 0.0)),
            weight=_clamp01(data.get("weight", 1.0)),
            evidence_hashes=_string_dict_from_mapping(data.get("evidence_hashes", {}) or {}),
            metrics=_dict_from_mapping(data.get("metrics", {}) or {}),
            semantic_conclusion=bool(data.get("semantic_conclusion", False)),
            schema_inference=bool(data.get("schema_inference", False)),
            type_inference=bool(data.get("type_inference", False)),
            entity_inference=bool(data.get("entity_inference", False)),
            ir_candidate=bool(data.get("ir_candidate", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleDeterminantVector:
    """Composite determinant vector for a staged Interpole timeline.

    The vector is a whole-signature object: later timeline rings and invertible
    mirrors can compare it as one deterministic semantic-evolution readiness
    signature while still inspecting its individual signals.
    """

    csv_id: str
    vector_fingerprint: str
    composite_signature_sha256: str
    source_timeline_fingerprint: str
    stage_order: tuple[str, ...]
    signals: tuple[CSVInterpoleDeterminantSignal, ...]
    signal_count: int
    active_signal_count: int
    negative_signal_count: int
    wrapped_stage_count: int
    confidence_average: float
    weighted_magnitude_average: float
    stability_score: float
    ir_readiness_score: float

    @property
    def ok(self) -> bool:
        return self.signal_count > 0 and self.active_signal_count == self.signal_count and self.negative_signal_count == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage_order"] = list(self.stage_order)
        data["signals"] = [signal.to_dict() for signal in self.signals]
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleDeterminantVector":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            vector_fingerprint=str(data.get("vector_fingerprint", "")),
            composite_signature_sha256=str(data.get("composite_signature_sha256", "")),
            source_timeline_fingerprint=str(data.get("source_timeline_fingerprint", "")),
            stage_order=tuple(str(v) for v in data.get("stage_order", []) or []),
            signals=tuple(CSVInterpoleDeterminantSignal.from_mapping(v) for v in data.get("signals", []) or []),
            signal_count=int(data.get("signal_count", 0)),
            active_signal_count=int(data.get("active_signal_count", 0)),
            negative_signal_count=int(data.get("negative_signal_count", 0)),
            wrapped_stage_count=int(data.get("wrapped_stage_count", 0)),
            confidence_average=_clamp01(data.get("confidence_average", 0.0)),
            weighted_magnitude_average=_clamp01(data.get("weighted_magnitude_average", 0.0)),
            stability_score=_clamp01(data.get("stability_score", 0.0)),
            ir_readiness_score=_clamp01(data.get("ir_readiness_score", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleDeterminantVectorReport:
    """CSV Interpole determinant-vector report.

    This report begins the vectoring strategy for semantic-evolution readiness.
    It is optional and compact.  It does not materialize a timeline ring, run the
    invertible mirror, infer semantic types, or commit formal IR.
    """

    csv_id: str
    status: str
    interpole_version: str
    determinant_vector_version: str
    report_key: str
    mode: str
    vector: CSVInterpoleDeterminantVector
    source_timeline_report_key: str = ""
    source_timeline_fingerprint: str = ""
    timeline_validation_status: str = "not_checked"
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
    semantic_conclusions: bool = False
    determinant_vectoring: bool = True
    timeline_ring_materialized: bool = False
    invertible_mirror_feedback: bool = False
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"determinants_ready", "determinants_committed", "valid"} and not self.errors and self.vector.ok

    @property
    def vector_fingerprint(self) -> str:
        return self.vector.vector_fingerprint

    @property
    def signal_count(self) -> int:
        return self.vector.signal_count

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["vector"] = self.vector.to_dict()
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["vector_fingerprint"] = self.vector_fingerprint
        data["signal_count"] = self.signal_count
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleDeterminantVectorReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            interpole_version=str(data.get("interpole_version", CSV_INTERPOLE_TIMELINE_VERSION)),
            determinant_vector_version=str(data.get("determinant_vector_version", CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "unknown")),
            vector=CSVInterpoleDeterminantVector.from_mapping(data.get("vector", {}) or {}),
            source_timeline_report_key=str(data.get("source_timeline_report_key", "")),
            source_timeline_fingerprint=str(data.get("source_timeline_fingerprint", "")),
            timeline_validation_status=str(data.get("timeline_validation_status", "not_checked")),
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
            semantic_conclusions=bool(data.get("semantic_conclusions", False)),
            determinant_vectoring=bool(data.get("determinant_vectoring", True)),
            timeline_ring_materialized=bool(data.get("timeline_ring_materialized", False)),
            invertible_mirror_feedback=bool(data.get("invertible_mirror_feedback", False)),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
        )


def _empty_determinant_vector(csv_id: str, source_timeline_fingerprint: str = "") -> CSVInterpoleDeterminantVector:
    fingerprint = _canonical_sha256(
        {
            "version": CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION,
            "csv_id": str(csv_id),
            "source_timeline_fingerprint": source_timeline_fingerprint,
            "signals": [],
        }
    )
    return CSVInterpoleDeterminantVector(
        csv_id=str(csv_id),
        vector_fingerprint=fingerprint,
        composite_signature_sha256=fingerprint,
        source_timeline_fingerprint=source_timeline_fingerprint,
        stage_order=tuple(),
        signals=tuple(),
        signal_count=0,
        active_signal_count=0,
        negative_signal_count=0,
        wrapped_stage_count=0,
        confidence_average=0.0,
        weighted_magnitude_average=0.0,
        stability_score=0.0,
        ir_readiness_score=0.0,
    )


def _invalid_determinant_report(csv_id: str, error: str, *, report_key: str = "") -> CSVInterpoleDeterminantVectorReport:
    return CSVInterpoleDeterminantVectorReport(
        csv_id=str(csv_id),
        status="invalid",
        interpole_version=CSV_INTERPOLE_TIMELINE_VERSION,
        determinant_vector_version=CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION,
        report_key=report_key,
        mode="invalid",
        vector=_empty_determinant_vector(str(csv_id)),
        errors=(error,),
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )


def _signal(
    stage: CSVInterpoleStage,
    signal_name: str,
    signal_kind: str,
    magnitude: Any,
    *,
    confidence: Any = 1.0,
    weight: Any = 1.0,
    metrics: Mapping[str, Any] | None = None,
    evidence_hashes: Mapping[str, str] | None = None,
    direction: str | None = None,
) -> CSVInterpoleDeterminantSignal:
    mag = _clamp01(magnitude)
    conf = _clamp01(confidence)
    wt = _clamp01(weight)
    return CSVInterpoleDeterminantSignal(
        signal_name=signal_name,
        signal_kind=signal_kind,
        source_stage_name=stage.stage_name,
        source_stage_index=stage.stage_index,
        source_signature_sha256=stage.signature.signature_sha256,
        magnitude=mag,
        direction=direction or _direction_for_magnitude(mag),
        confidence=conf,
        weight=wt,
        evidence_hashes=dict(evidence_hashes if evidence_hashes is not None else stage.signature.source_hashes),
        metrics=dict(metrics or {}),
        semantic_conclusion=False,
        schema_inference=False,
        type_inference=False,
        entity_inference=False,
        ir_candidate=False,
    )


def _stage_by_name(timeline: CSVInterpoleTimeline) -> dict[str, CSVInterpoleStage]:
    return {stage.stage_name: stage for stage in timeline.stages}


def _build_determinant_signals(timeline: CSVInterpoleTimeline) -> tuple[CSVInterpoleDeterminantSignal, ...]:
    stages = _stage_by_name(timeline)
    signals: list[CSVInterpoleDeterminantSignal] = []

    evidence = stages.get("evidence_baseline")
    if evidence is not None:
        m = evidence.signature.metrics
        artifact_count = int(m.get("artifact_count", 0) or 0)
        row_count = int(m.get("row_count", 0) or 0)
        column_count = int(m.get("column_count", 0) or 0)
        density = row_count * max(column_count, 1)
        signals.append(
            _signal(
                evidence,
                "artifact_shape_pressure",
                "evidence_integrity",
                1.0 if artifact_count == 6 else 0.0,
                metrics={"artifact_count": artifact_count, "expected_artifact_count": 6},
                weight=1.0,
            )
        )
        signals.append(
            _signal(
                evidence,
                "evidence_volume_pressure",
                "evidence_shape",
                min(1.0, density / 1024.0) if density > 0 else 0.0,
                confidence=1.0 if row_count > 0 and column_count > 0 else 0.5,
                metrics={"row_count": row_count, "column_count": column_count, "cell_slot_count": density},
                weight=0.45,
                direction="stable" if density > 0 else "blocked",
            )
        )
        signals.append(
            _signal(
                evidence,
                "header_observation_pressure",
                "structure_hint",
                1.0 if bool(m.get("has_header", False)) else 0.0,
                confidence=0.75,
                metrics={"has_header": bool(m.get("has_header", False))},
                weight=0.35,
                direction="stable" if bool(m.get("has_header", False)) else "neutral",
            )
        )

    structure = stages.get("structure_baseline")
    if structure is not None:
        m = structure.signature.metrics
        row_count = int(m.get("row_count", 0) or 0)
        row_offset_count = int(m.get("row_offset_count", 0) or 0)
        signals.append(
            _signal(
                structure,
                "row_offset_alignment",
                "structure_integrity",
                _ratio(row_offset_count, row_count, empty_value=0.0),
                metrics={"row_offset_count": row_offset_count, "row_count": row_count},
                weight=1.0,
            )
        )
        signals.append(
            _signal(
                structure,
                "dialect_confidence_pressure",
                "dialect_evidence",
                _clamp01(m.get("dialect_confidence", 0.0)),
                confidence=0.9,
                metrics={"dialect_confidence": float(m.get("dialect_confidence", 0.0) or 0.0)},
                weight=0.8,
            )
        )
        signals.append(
            _signal(
                structure,
                "artifact_validation_pressure",
                "validation_integrity",
                1.0 if str(m.get("artifact_validation_status", "")) == "valid" else 0.0,
                metrics={"artifact_validation_status": str(m.get("artifact_validation_status", ""))},
                weight=1.0,
            )
        )

    canonical = stages.get("canonical_export_baseline")
    if canonical is not None:
        m = canonical.signature.metrics
        canonical_line_count = int(m.get("canonical_line_count", 0) or 0)
        canonical_size = int(m.get("canonical_size", 0) or 0)
        expected_lines = 0
        if evidence is not None:
            em = evidence.signature.metrics
            expected_lines = int(em.get("row_count", 0) or 0) + (1 if bool(em.get("has_header", False)) else 0)
        signals.append(
            _signal(
                canonical,
                "canonical_line_alignment",
                "canonical_stability",
                _ratio(canonical_line_count, expected_lines, empty_value=0.0),
                metrics={"canonical_line_count": canonical_line_count, "expected_line_count": expected_lines},
                weight=0.85,
            )
        )
        signals.append(
            _signal(
                canonical,
                "canonical_boundary_pressure",
                "materialization_boundary",
                1.0 if not bool(m.get("canonical_materialized", False)) and canonical_size >= 0 else 0.0,
                confidence=0.9,
                metrics={"canonical_materialized": bool(m.get("canonical_materialized", False)), "canonical_size": canonical_size},
                weight=0.5,
            )
        )

    native_commit = stages.get("native_storage_commit_baseline")
    if native_commit is not None:
        m = native_commit.signature.metrics
        entry_count = int(m.get("entry_count", 0) or 0)
        committed_count = int(m.get("committed_count", 0) or 0)
        write_count = int(m.get("native_storage_entry_writes", 0) or 0)
        signals.append(
            _signal(
                native_commit,
                "native_commit_completion",
                "storage_binding_integrity",
                _ratio(committed_count, entry_count, empty_value=0.0),
                metrics={"committed_count": committed_count, "entry_count": entry_count},
                weight=1.0,
            )
        )
        signals.append(
            _signal(
                native_commit,
                "native_write_boundary_alignment",
                "storage_boundary",
                _ratio(write_count, committed_count, empty_value=1.0),
                confidence=0.9,
                metrics={"native_storage_entry_writes": write_count, "committed_count": committed_count},
                weight=0.65,
            )
        )

    revalidation = stages.get("native_revalidation_baseline")
    if revalidation is not None:
        m = revalidation.signature.metrics
        entry_count = int(m.get("entry_count", 0) or 0)
        verified_count = int(m.get("verified_count", 0) or 0)
        source_drift = int(m.get("source_drift_count", 0) or 0)
        storage_drift = int(m.get("storage_drift_count", 0) or 0)
        proof_drift = int(m.get("proof_drift_count", 0) or 0)
        drift_total = source_drift + storage_drift + proof_drift
        skipped_optional = int(m.get("skipped_optional_count", 0) or 0)
        signals.append(
            _signal(
                revalidation,
                "native_revalidation_completion",
                "revalidation_integrity",
                _ratio(verified_count, entry_count, empty_value=0.0),
                metrics={"verified_count": verified_count, "entry_count": entry_count},
                weight=1.0,
            )
        )
        drift_absence_magnitude = 0.0 if revalidation.status == "drifted" or revalidation.error else 1.0 - _ratio(drift_total, max(entry_count, 1), empty_value=0.0)
        signals.append(
            _signal(
                revalidation,
                "drift_absence_pressure",
                "drift_guard",
                drift_absence_magnitude,
                metrics={
                    "source_drift_count": source_drift,
                    "storage_drift_count": storage_drift,
                    "proof_drift_count": proof_drift,
                    "drift_total": drift_total,
                    "entry_count": entry_count,
                },
                weight=1.0,
            )
        )
        signals.append(
            _signal(
                revalidation,
                "optional_scan_skip_pressure",
                "optional_evidence_boundary",
                1.0 if skipped_optional >= 0 else 0.0,
                confidence=0.8,
                metrics={"skipped_optional_count": skipped_optional},
                weight=0.25,
                direction="neutral" if skipped_optional else "stable",
            )
        )

    readiness = stages.get("ir_readiness_baseline")
    if readiness is not None:
        m = readiness.signature.metrics
        ready_for_future_determinants = bool(m.get("ready_for_future_determinants", False))
        signals.append(
            _signal(
                readiness,
                "future_determinant_readiness",
                "ir_readiness_boundary",
                1.0 if ready_for_future_determinants else 0.0,
                metrics={"ready_for_future_determinants": ready_for_future_determinants},
                weight=1.0,
            )
        )
        semantic_neutral = not bool(m.get("semantic_conclusions", False)) and not bool(m.get("formal_ir_committed", False))
        signals.append(
            _signal(
                readiness,
                "semantic_neutrality_lock",
                "semantic_boundary",
                1.0 if semantic_neutral else 0.0,
                confidence=1.0,
                metrics={
                    "semantic_conclusions": bool(m.get("semantic_conclusions", False)),
                    "formal_ir_committed": bool(m.get("formal_ir_committed", False)),
                    "timeline_ring_materialized": bool(m.get("timeline_ring_materialized", False)),
                    "invertible_mirror_feedback": bool(m.get("invertible_mirror_feedback", False)),
                },
                weight=1.0,
            )
        )

    return tuple(signals)


def _determinant_vector(csv_id: str, timeline: CSVInterpoleTimeline) -> CSVInterpoleDeterminantVector:
    signals = _build_determinant_signals(timeline)
    signal_count = len(signals)
    active_signal_count = sum(1 for signal in signals if signal.ok)
    negative_signal_count = sum(1 for signal in signals if signal.direction == "blocked")
    confidence_average = sum(signal.confidence for signal in signals) / signal_count if signal_count else 0.0
    weighted_magnitude_average = sum(signal.weighted_magnitude for signal in signals) / signal_count if signal_count else 0.0
    high_integrity = sum(1 for signal in signals if signal.magnitude >= 0.875) / signal_count if signal_count else 0.0
    stability_score = _clamp01((weighted_magnitude_average * 0.65) + (confidence_average * 0.20) + (high_integrity * 0.15))
    readiness_signal_names = {"future_determinant_readiness", "semantic_neutrality_lock", "drift_absence_pressure"}
    readiness_signals = [signal for signal in signals if signal.signal_name in readiness_signal_names]
    ir_readiness_score = (
        sum(signal.magnitude for signal in readiness_signals) / len(readiness_signals)
        if readiness_signals
        else 0.0
    )
    stage_order = tuple(stage.stage_name for stage in timeline.stages)
    payload = {
        "version": CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION,
        "csv_id": csv_id,
        "source_timeline_fingerprint": timeline.timeline_fingerprint,
        "stage_order": stage_order,
        "signal_signatures": [
            {
                "signal_name": signal.signal_name,
                "signal_kind": signal.signal_kind,
                "source_stage_name": signal.source_stage_name,
                "source_signature_sha256": signal.source_signature_sha256,
                "magnitude": signal.magnitude,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "weight": signal.weight,
                "metrics": dict(signal.metrics),
                "evidence_hashes": dict(signal.evidence_hashes),
            }
            for signal in signals
        ],
        "confidence_average": confidence_average,
        "weighted_magnitude_average": weighted_magnitude_average,
        "stability_score": stability_score,
        "ir_readiness_score": ir_readiness_score,
    }
    fingerprint = _canonical_sha256(payload)
    return CSVInterpoleDeterminantVector(
        csv_id=csv_id,
        vector_fingerprint=fingerprint,
        composite_signature_sha256=fingerprint,
        source_timeline_fingerprint=timeline.timeline_fingerprint,
        stage_order=stage_order,
        signals=signals,
        signal_count=signal_count,
        active_signal_count=active_signal_count,
        negative_signal_count=negative_signal_count,
        wrapped_stage_count=len(stage_order),
        confidence_average=_clamp01(confidence_average),
        weighted_magnitude_average=_clamp01(weighted_magnitude_average),
        stability_score=stability_score,
        ir_readiness_score=_clamp01(ir_readiness_score),
    )


def prepare_csv_interpole_determinant_vector(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVInterpoleDeterminantVectorReport:
    """Build a no-write CSV Interpole determinant vector from a persisted timeline.

    The vector layer requires a committed Interpole timeline and a clean fresh
    timeline validation.  It measures semantic-evolution readiness but does not
    infer, decide, or commit semantics.
    """
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_interpole_determinant_vector_report_key(safe_id)
    except Exception as exc:
        return _invalid_determinant_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    try:
        stored_timeline = load_csv_interpole_timeline_report(directory, safe_id)
    except Exception as exc:
        return _invalid_determinant_report(
            safe_id,
            f"interpole_timeline_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
        )

    timeline_validation = validate_csv_interpole_timeline(directory, safe_id, chunk_size=chunk_size, encoding=encoding)
    vector = _determinant_vector(safe_id, timeline_validation.timeline)
    errors: list[str] = list(timeline_validation.errors)
    warnings: list[str] = list(timeline_validation.warnings)
    if stored_timeline.status not in {"timeline_committed", "valid"}:
        errors.append(f"stored_interpole_timeline_not_committed:{stored_timeline.status}")
    if stored_timeline.timeline_fingerprint != timeline_validation.timeline_fingerprint:
        errors.append("stored_interpole_timeline_fingerprint_mismatch")
    if not vector.ok:
        errors.append("interpole_determinant_vector_not_clean")

    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    status = "determinants_ready" if not unique_errors else "drifted"
    return CSVInterpoleDeterminantVectorReport(
        csv_id=safe_id,
        status=status,
        interpole_version=CSV_INTERPOLE_TIMELINE_VERSION,
        determinant_vector_version=CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION,
        report_key=report_key,
        mode="determinant_prepare",
        vector=vector,
        source_timeline_report_key=stored_timeline.report_key,
        source_timeline_fingerprint=timeline_validation.timeline_fingerprint,
        timeline_validation_status=timeline_validation.status,
        errors=unique_errors,
        warnings=unique_warnings,
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )


def commit_csv_interpole_determinant_vector_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    overwrite: bool = False,
    encoding: str = "utf-8",
) -> CSVInterpoleDeterminantVectorReport:
    """Persist a compact derived CSV Interpole determinant vector report."""
    report = prepare_csv_interpole_determinant_vector(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    if not report.ok:
        return report
    committed = CSVInterpoleDeterminantVectorReport(
        csv_id=report.csv_id,
        status="determinants_committed",
        interpole_version=report.interpole_version,
        determinant_vector_version=report.determinant_vector_version,
        report_key=report.report_key,
        mode="determinant_commit",
        vector=report.vector,
        source_timeline_report_key=report.source_timeline_report_key,
        source_timeline_fingerprint=report.source_timeline_fingerprint,
        timeline_validation_status=report.timeline_validation_status,
        warnings=report.warnings,
        tds_artifact_writes=1,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )
    result: TDSResult = directory.write_json(committed.report_key, committed.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return CSVInterpoleDeterminantVectorReport(
            csv_id=report.csv_id,
            status="invalid",
            interpole_version=report.interpole_version,
            determinant_vector_version=report.determinant_vector_version,
            report_key=report.report_key,
            mode="determinant_commit",
            vector=report.vector,
            source_timeline_report_key=report.source_timeline_report_key,
            source_timeline_fingerprint=report.source_timeline_fingerprint,
            timeline_validation_status=report.timeline_validation_status,
            errors=(f"interpole_determinant_vector_report_write_failed:{result.code}:{result.message}",),
            warnings=report.warnings,
            tds_artifact_writes=0,
            native_storage_writes=False,
            native_c_engine_changed=False,
            native_csv_kernel_used=False,
            per_row_writes=False,
            per_cell_writes=False,
            native_storage_hot_path_touched=False,
            semantic_reasoning=False,
            semantic_conclusions=False,
            determinant_vectoring=True,
            timeline_ring_materialized=False,
            invertible_mirror_feedback=False,
            formal_ir_committed=False,
        )
    return committed


def load_csv_interpole_determinant_vector_report(directory: TDSDirectory, csv_id: str) -> CSVInterpoleDeterminantVectorReport:
    """Load a persisted CSV Interpole determinant vector report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_interpole_determinant_vector_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV Interpole determinant vector report {key!r} is not a JSON object")
    return CSVInterpoleDeterminantVectorReport.from_mapping(value)


def validate_csv_interpole_determinant_vector(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVInterpoleDeterminantVectorReport:
    """Validate a persisted Interpole determinant vector against fresh evidence."""
    try:
        stored = load_csv_interpole_determinant_vector_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_interpole_determinant_vector_report_key(csv_id)
        except Exception:
            report_key = ""
        return _invalid_determinant_report(str(csv_id), f"interpole_determinant_vector_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_interpole_determinant_vector(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    errors: list[str] = list(fresh.errors)
    warnings: list[str] = list(dict.fromkeys(tuple(stored.warnings) + tuple(fresh.warnings)))
    if stored.status not in {"determinants_committed", "valid"}:
        errors.append(f"stored_interpole_determinant_vector_not_committed:{stored.status}")
    if stored.vector_fingerprint != fresh.vector_fingerprint:
        errors.append("interpole_determinant_vector_fingerprint_drift")
    if stored.source_timeline_fingerprint != fresh.source_timeline_fingerprint:
        errors.append("interpole_determinant_source_timeline_fingerprint_drift")
    if stored.signal_count != fresh.signal_count:
        errors.append("interpole_determinant_signal_count_drift")
    if stored.vector.composite_signature_sha256 != fresh.vector.composite_signature_sha256:
        errors.append("interpole_determinant_composite_signature_drift")

    unique_errors = tuple(dict.fromkeys(errors))
    status = "valid" if not unique_errors else "drifted"
    return CSVInterpoleDeterminantVectorReport(
        csv_id=fresh.csv_id,
        status=status,
        interpole_version=fresh.interpole_version,
        determinant_vector_version=fresh.determinant_vector_version,
        report_key=stored.report_key,
        mode="validation",
        vector=fresh.vector,
        source_timeline_report_key=fresh.source_timeline_report_key,
        source_timeline_fingerprint=fresh.source_timeline_fingerprint,
        timeline_validation_status=fresh.timeline_validation_status,
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
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=False,
        invertible_mirror_feedback=False,
        formal_ir_committed=False,
    )


def csv_interpole_determinant_vector_summary(report: CSVInterpoleDeterminantVectorReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for a determinant vector report."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "mode": report.mode,
        "interpole_version": report.interpole_version,
        "determinant_vector_version": report.determinant_vector_version,
        "vector_fingerprint": report.vector_fingerprint,
        "composite_signature_sha256": report.vector.composite_signature_sha256,
        "source_timeline_fingerprint": report.source_timeline_fingerprint,
        "timeline_validation_status": report.timeline_validation_status,
        "signal_count": report.signal_count,
        "active_signal_count": report.vector.active_signal_count,
        "negative_signal_count": report.vector.negative_signal_count,
        "wrapped_stage_count": report.vector.wrapped_stage_count,
        "confidence_average": report.vector.confidence_average,
        "weighted_magnitude_average": report.vector.weighted_magnitude_average,
        "stability_score": report.vector.stability_score,
        "ir_readiness_score": report.vector.ir_readiness_score,
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_writes": report.native_storage_writes,
        "native_c_engine_changed": report.native_c_engine_changed,
        "native_csv_kernel_used": report.native_csv_kernel_used,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
        "semantic_conclusions": report.semantic_conclusions,
        "determinant_vectoring": report.determinant_vectoring,
        "timeline_ring_materialized": report.timeline_ring_materialized,
        "invertible_mirror_feedback": report.invertible_mirror_feedback,
        "formal_ir_committed": report.formal_ir_committed,
    }


CSV_INTERPOLE_TIMELINE_RING_VERSION = "1.0"


def csv_interpole_timeline_ring_report_key(csv_id: str) -> str:
    """Return the durable key for a CSV Interpole timeline-ring mirror report."""
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__interpole_timeline_ring_report.json"


def _average(values: tuple[float, ...] | list[float], *, empty_value: float = 0.0) -> float:
    if not values:
        return empty_value
    return _clamp01(sum(values) / len(values))


def _signal_metrics(signals: tuple[CSVInterpoleDeterminantSignal, ...]) -> dict[str, Any]:
    magnitudes = [_clamp01(signal.magnitude) for signal in signals]
    confidences = [_clamp01(signal.confidence) for signal in signals]
    weighted = [_clamp01(signal.weighted_magnitude) for signal in signals]
    by_name = {signal.signal_name: signal for signal in signals}
    drift_absence = _clamp01(by_name.get("drift_absence_pressure").magnitude) if "drift_absence_pressure" in by_name else 1.0
    ir_readiness = _clamp01(by_name.get("ir_readiness_pressure").magnitude) if "ir_readiness_pressure" in by_name else _average(magnitudes)
    semantic_lock = _clamp01(by_name.get("semantic_neutrality_lock").magnitude) if "semantic_neutrality_lock" in by_name else 1.0
    return {
        "signal_count": len(signals),
        "magnitude_average": _average(magnitudes),
        "confidence_average": _average(confidences),
        "weighted_magnitude_average": _average(weighted),
        "drift_pressure": _clamp01(1.0 - drift_absence),
        "ir_readiness_pressure": ir_readiness,
        "semantic_neutrality_lock": semantic_lock,
    }


def _ring_direction(magnitude_average: float, drift_pressure: float) -> str:
    if drift_pressure >= 0.25:
        return "drifted"
    if magnitude_average >= 0.875:
        return "stable"
    if magnitude_average >= 0.5:
        return "watch"
    if magnitude_average > 0.0:
        return "weakening"
    return "blocked"


@dataclass(frozen=True, slots=True)
class CSVInterpoleTimelineRingNode:
    """One node in the CSV Interpole timeline ring.

    A node wraps all determinant signals for one Interpole stage.  It preserves
    semantic-evolution movement as evidence-neutral pressure, not as schema,
    type, entity, row, or cell meaning.
    """

    node_index: int
    stage_name: str
    node_fingerprint: str
    source_vector_fingerprint: str
    source_timeline_fingerprint: str
    source_signature_sha256: str
    signal_fingerprints: tuple[str, ...]
    signal_count: int
    magnitude_average: float
    confidence_average: float
    weighted_magnitude_average: float
    drift_pressure: float
    ir_readiness_pressure: float
    direction: str
    status: str
    feedback_hint: str
    semantic_conclusion: bool = False
    schema_inference: bool = False
    type_inference: bool = False
    entity_inference: bool = False
    ir_candidate: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.signal_count > 0
            and self.status in {"stable", "watch"}
            and self.direction not in {"blocked", "drifted"}
            and not self.semantic_conclusion
            and not self.schema_inference
            and not self.type_inference
            and not self.entity_inference
            and not self.ir_candidate
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signal_fingerprints"] = list(self.signal_fingerprints)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleTimelineRingNode":
        return cls(
            node_index=int(data.get("node_index", 0)),
            stage_name=str(data.get("stage_name", "")),
            node_fingerprint=str(data.get("node_fingerprint", "")),
            source_vector_fingerprint=str(data.get("source_vector_fingerprint", "")),
            source_timeline_fingerprint=str(data.get("source_timeline_fingerprint", "")),
            source_signature_sha256=str(data.get("source_signature_sha256", "")),
            signal_fingerprints=tuple(str(v) for v in data.get("signal_fingerprints", []) or []),
            signal_count=int(data.get("signal_count", 0)),
            magnitude_average=_clamp01(data.get("magnitude_average", 0.0)),
            confidence_average=_clamp01(data.get("confidence_average", 0.0)),
            weighted_magnitude_average=_clamp01(data.get("weighted_magnitude_average", 0.0)),
            drift_pressure=_clamp01(data.get("drift_pressure", 0.0)),
            ir_readiness_pressure=_clamp01(data.get("ir_readiness_pressure", 0.0)),
            direction=str(data.get("direction", "blocked")),
            status=str(data.get("status", "blocked")),
            feedback_hint=str(data.get("feedback_hint", "ir_blocked")),
            semantic_conclusion=bool(data.get("semantic_conclusion", False)),
            schema_inference=bool(data.get("schema_inference", False)),
            type_inference=bool(data.get("type_inference", False)),
            entity_inference=bool(data.get("entity_inference", False)),
            ir_candidate=bool(data.get("ir_candidate", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleTimelineRing:
    """Ordered determinant-ring timeline for Interpole evolution monitoring."""

    csv_id: str
    ring_fingerprint: str
    source_vector_fingerprint: str
    source_timeline_fingerprint: str
    nodes: tuple[CSVInterpoleTimelineRingNode, ...]
    node_count: int
    stable_node_count: int
    watch_node_count: int
    weakened_node_count: int
    blocked_node_count: int
    drifted_node_count: int
    ring_stability_score: float
    ring_ir_readiness_score: float

    @property
    def ok(self) -> bool:
        return self.node_count > 0 and self.blocked_node_count == 0 and self.drifted_node_count == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["nodes"] = [node.to_dict() for node in self.nodes]
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleTimelineRing":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            ring_fingerprint=str(data.get("ring_fingerprint", "")),
            source_vector_fingerprint=str(data.get("source_vector_fingerprint", "")),
            source_timeline_fingerprint=str(data.get("source_timeline_fingerprint", "")),
            nodes=tuple(CSVInterpoleTimelineRingNode.from_mapping(v) for v in data.get("nodes", []) or []),
            node_count=int(data.get("node_count", 0)),
            stable_node_count=int(data.get("stable_node_count", 0)),
            watch_node_count=int(data.get("watch_node_count", 0)),
            weakened_node_count=int(data.get("weakened_node_count", 0)),
            blocked_node_count=int(data.get("blocked_node_count", 0)),
            drifted_node_count=int(data.get("drifted_node_count", 0)),
            ring_stability_score=_clamp01(data.get("ring_stability_score", 0.0)),
            ring_ir_readiness_score=_clamp01(data.get("ring_ir_readiness_score", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleMirrorDelta:
    """Bidirectional mirror check between previous and current determinant vectors.

    Invertible here means the evolution relationship is checkable in both
    directions from stored signatures and delta proofs.  It does not mean CSV
    evidence can be reconstructed from semantics.
    """

    previous_vector_fingerprint: str
    current_vector_fingerprint: str
    forward_delta_sha256: str
    inverse_delta_sha256: str
    mirror_fingerprint: str
    delta_magnitude: float
    stability_delta: float
    ir_readiness_delta: float
    signal_count_delta: int
    inverse_check_passed: bool
    discrete_feedback: tuple[str, ...]

    @property
    def ok(self) -> bool:
        blocking = {"determinant_conflict", "semantic_jump", "inverse_mismatch", "drift_confirmed", "ir_blocked"}
        return self.inverse_check_passed and not any(item in blocking for item in self.discrete_feedback)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["discrete_feedback"] = list(self.discrete_feedback)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleMirrorDelta":
        return cls(
            previous_vector_fingerprint=str(data.get("previous_vector_fingerprint", "")),
            current_vector_fingerprint=str(data.get("current_vector_fingerprint", "")),
            forward_delta_sha256=str(data.get("forward_delta_sha256", "")),
            inverse_delta_sha256=str(data.get("inverse_delta_sha256", "")),
            mirror_fingerprint=str(data.get("mirror_fingerprint", "")),
            delta_magnitude=_clamp01(data.get("delta_magnitude", 0.0)),
            stability_delta=float(data.get("stability_delta", 0.0)),
            ir_readiness_delta=float(data.get("ir_readiness_delta", 0.0)),
            signal_count_delta=int(data.get("signal_count_delta", 0)),
            inverse_check_passed=bool(data.get("inverse_check_passed", False)),
            discrete_feedback=tuple(str(v) for v in data.get("discrete_feedback", []) or []),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleTimelineRingReport:
    """CSV Interpole timeline-ring and invertible-mirror feedback report.

    The report materializes optional determinant-ring monitoring and mirror
    feedback for semantic-evolution movement.  It remains evidence-neutral and
    does not infer semantics or commit formal IR.
    """

    csv_id: str
    status: str
    interpole_version: str
    determinant_vector_version: str
    timeline_ring_version: str
    report_key: str
    mode: str
    ring: CSVInterpoleTimelineRing
    mirror_delta: CSVInterpoleMirrorDelta
    source_determinant_vector_report_key: str = ""
    source_vector_fingerprint: str = ""
    determinant_validation_status: str = "not_checked"
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
    semantic_conclusions: bool = False
    determinant_vectoring: bool = True
    timeline_ring_materialized: bool = True
    invertible_mirror_feedback: bool = True
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"ring_ready", "ring_committed", "valid"} and not self.errors and self.ring.ok and self.mirror_delta.ok

    @property
    def ring_fingerprint(self) -> str:
        return self.ring.ring_fingerprint

    @property
    def mirror_fingerprint(self) -> str:
        return self.mirror_delta.mirror_fingerprint

    @property
    def node_count(self) -> int:
        return self.ring.node_count

    @property
    def discrete_feedback(self) -> tuple[str, ...]:
        return self.mirror_delta.discrete_feedback

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ring"] = self.ring.to_dict()
        data["mirror_delta"] = self.mirror_delta.to_dict()
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        data["ring_fingerprint"] = self.ring_fingerprint
        data["mirror_fingerprint"] = self.mirror_fingerprint
        data["node_count"] = self.node_count
        data["discrete_feedback"] = list(self.discrete_feedback)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleTimelineRingReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            interpole_version=str(data.get("interpole_version", CSV_INTERPOLE_TIMELINE_VERSION)),
            determinant_vector_version=str(data.get("determinant_vector_version", CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION)),
            timeline_ring_version=str(data.get("timeline_ring_version", CSV_INTERPOLE_TIMELINE_RING_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "unknown")),
            ring=CSVInterpoleTimelineRing.from_mapping(data.get("ring", {}) or {}),
            mirror_delta=CSVInterpoleMirrorDelta.from_mapping(data.get("mirror_delta", {}) or {}),
            source_determinant_vector_report_key=str(data.get("source_determinant_vector_report_key", "")),
            source_vector_fingerprint=str(data.get("source_vector_fingerprint", "")),
            determinant_validation_status=str(data.get("determinant_validation_status", "not_checked")),
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
            semantic_conclusions=bool(data.get("semantic_conclusions", False)),
            determinant_vectoring=bool(data.get("determinant_vectoring", True)),
            timeline_ring_materialized=bool(data.get("timeline_ring_materialized", True)),
            invertible_mirror_feedback=bool(data.get("invertible_mirror_feedback", True)),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
        )


def _empty_timeline_ring(csv_id: str, source_vector_fingerprint: str = "") -> CSVInterpoleTimelineRing:
    return CSVInterpoleTimelineRing(
        csv_id=csv_id,
        ring_fingerprint="",
        source_vector_fingerprint=source_vector_fingerprint,
        source_timeline_fingerprint="",
        nodes=(),
        node_count=0,
        stable_node_count=0,
        watch_node_count=0,
        weakened_node_count=0,
        blocked_node_count=0,
        drifted_node_count=0,
        ring_stability_score=0.0,
        ring_ir_readiness_score=0.0,
    )


def _empty_mirror_delta(previous_vector_fingerprint: str = "", current_vector_fingerprint: str = "") -> CSVInterpoleMirrorDelta:
    return CSVInterpoleMirrorDelta(
        previous_vector_fingerprint=previous_vector_fingerprint,
        current_vector_fingerprint=current_vector_fingerprint,
        forward_delta_sha256="",
        inverse_delta_sha256="",
        mirror_fingerprint="",
        delta_magnitude=0.0,
        stability_delta=0.0,
        ir_readiness_delta=0.0,
        signal_count_delta=0,
        inverse_check_passed=False,
        discrete_feedback=("ir_blocked",),
    )


def _invalid_timeline_ring_report(csv_id: str, error: str, *, report_key: str = "") -> CSVInterpoleTimelineRingReport:
    return CSVInterpoleTimelineRingReport(
        csv_id=csv_id,
        status="invalid",
        interpole_version=CSV_INTERPOLE_TIMELINE_VERSION,
        determinant_vector_version=CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION,
        timeline_ring_version=CSV_INTERPOLE_TIMELINE_RING_VERSION,
        report_key=report_key,
        mode="invalid",
        ring=_empty_timeline_ring(csv_id),
        mirror_delta=_empty_mirror_delta(),
        errors=(error,),
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=True,
        invertible_mirror_feedback=True,
        formal_ir_committed=False,
    )


def _signals_by_stage(vector: CSVInterpoleDeterminantVector) -> dict[str, tuple[CSVInterpoleDeterminantSignal, ...]]:
    grouped: dict[str, list[CSVInterpoleDeterminantSignal]] = {stage_name: [] for stage_name in vector.stage_order}
    for signal in vector.signals:
        grouped.setdefault(signal.source_stage_name, []).append(signal)
    return {stage_name: tuple(values) for stage_name, values in grouped.items()}


def _timeline_ring_node(index: int, stage_name: str, vector: CSVInterpoleDeterminantVector, signals: tuple[CSVInterpoleDeterminantSignal, ...]) -> CSVInterpoleTimelineRingNode:
    metrics = _signal_metrics(signals)
    direction = _ring_direction(metrics["magnitude_average"], metrics["drift_pressure"])
    status = "stable" if direction == "stable" else "watch" if direction == "watch" else "drifted" if direction == "drifted" else direction
    if status == "stable" and metrics["ir_readiness_pressure"] >= 0.875:
        feedback_hint = "ir_ready"
    elif status == "drifted":
        feedback_hint = "drift_confirmed"
    elif status == "blocked":
        feedback_hint = "ir_blocked"
    else:
        feedback_hint = "semantic_watch"
    signal_fingerprints = tuple(_canonical_sha256(signal.to_dict()) for signal in signals)
    source_signature = signals[0].source_signature_sha256 if signals else ""
    node_payload = {
        "csv_id": vector.csv_id,
        "node_index": index,
        "stage_name": stage_name,
        "source_vector_fingerprint": vector.vector_fingerprint,
        "source_timeline_fingerprint": vector.source_timeline_fingerprint,
        "source_signature_sha256": source_signature,
        "signal_fingerprints": signal_fingerprints,
        "metrics": metrics,
        "direction": direction,
        "status": status,
        "feedback_hint": feedback_hint,
        "semantic_conclusion": False,
        "ir_candidate": False,
    }
    return CSVInterpoleTimelineRingNode(
        node_index=index,
        stage_name=stage_name,
        node_fingerprint=_canonical_sha256(node_payload),
        source_vector_fingerprint=vector.vector_fingerprint,
        source_timeline_fingerprint=vector.source_timeline_fingerprint,
        source_signature_sha256=source_signature,
        signal_fingerprints=signal_fingerprints,
        signal_count=int(metrics["signal_count"]),
        magnitude_average=_clamp01(metrics["magnitude_average"]),
        confidence_average=_clamp01(metrics["confidence_average"]),
        weighted_magnitude_average=_clamp01(metrics["weighted_magnitude_average"]),
        drift_pressure=_clamp01(metrics["drift_pressure"]),
        ir_readiness_pressure=_clamp01(metrics["ir_readiness_pressure"]),
        direction=direction,
        status=status,
        feedback_hint=feedback_hint,
        semantic_conclusion=False,
        schema_inference=False,
        type_inference=False,
        entity_inference=False,
        ir_candidate=False,
    )


def _timeline_ring(csv_id: str, vector: CSVInterpoleDeterminantVector) -> CSVInterpoleTimelineRing:
    grouped = _signals_by_stage(vector)
    nodes = tuple(_timeline_ring_node(index, stage_name, vector, grouped.get(stage_name, ())) for index, stage_name in enumerate(vector.stage_order))
    stable_node_count = sum(1 for node in nodes if node.status == "stable")
    watch_node_count = sum(1 for node in nodes if node.status == "watch")
    weakened_node_count = sum(1 for node in nodes if node.status == "weakening")
    blocked_node_count = sum(1 for node in nodes if node.status == "blocked")
    drifted_node_count = sum(1 for node in nodes if node.status == "drifted")
    ring_stability_score = _average([node.magnitude_average for node in nodes])
    ring_ir_readiness_score = _average([node.ir_readiness_pressure for node in nodes])
    ring_payload = {
        "csv_id": csv_id,
        "source_vector_fingerprint": vector.vector_fingerprint,
        "source_timeline_fingerprint": vector.source_timeline_fingerprint,
        "node_fingerprints": [node.node_fingerprint for node in nodes],
        "node_count": len(nodes),
        "stable_node_count": stable_node_count,
        "watch_node_count": watch_node_count,
        "weakened_node_count": weakened_node_count,
        "blocked_node_count": blocked_node_count,
        "drifted_node_count": drifted_node_count,
        "ring_stability_score": ring_stability_score,
        "ring_ir_readiness_score": ring_ir_readiness_score,
        "semantic_conclusions": False,
        "formal_ir_committed": False,
    }
    return CSVInterpoleTimelineRing(
        csv_id=csv_id,
        ring_fingerprint=_canonical_sha256(ring_payload),
        source_vector_fingerprint=vector.vector_fingerprint,
        source_timeline_fingerprint=vector.source_timeline_fingerprint,
        nodes=nodes,
        node_count=len(nodes),
        stable_node_count=stable_node_count,
        watch_node_count=watch_node_count,
        weakened_node_count=weakened_node_count,
        blocked_node_count=blocked_node_count,
        drifted_node_count=drifted_node_count,
        ring_stability_score=ring_stability_score,
        ring_ir_readiness_score=ring_ir_readiness_score,
    )


def _mirror_delta(previous: CSVInterpoleDeterminantVector, current: CSVInterpoleDeterminantVector, *, validation_errors: tuple[str, ...] = ()) -> CSVInterpoleMirrorDelta:
    stability_delta_raw = current.stability_score - previous.stability_score
    ir_delta_raw = current.ir_readiness_score - previous.ir_readiness_score
    signal_count_delta = current.signal_count - previous.signal_count
    delta_magnitude = _clamp01((abs(stability_delta_raw) + abs(ir_delta_raw)) / 2.0)
    forward_delta = _canonical_sha256(
        {
            "direction": "forward",
            "previous_vector_fingerprint": previous.vector_fingerprint,
            "current_vector_fingerprint": current.vector_fingerprint,
            "previous_stability_score": previous.stability_score,
            "current_stability_score": current.stability_score,
            "previous_ir_readiness_score": previous.ir_readiness_score,
            "current_ir_readiness_score": current.ir_readiness_score,
            "signal_count_delta": signal_count_delta,
        }
    )
    inverse_delta = _canonical_sha256(
        {
            "direction": "inverse",
            "current_vector_fingerprint": current.vector_fingerprint,
            "previous_vector_fingerprint": previous.vector_fingerprint,
            "current_stability_score": current.stability_score,
            "previous_stability_score": previous.stability_score,
            "current_ir_readiness_score": current.ir_readiness_score,
            "previous_ir_readiness_score": previous.ir_readiness_score,
            "signal_count_delta": -signal_count_delta,
        }
    )
    inverse_check_passed = bool(previous.vector_fingerprint and current.vector_fingerprint and len(forward_delta) == 64 and len(inverse_delta) == 64)
    feedback: list[str] = []
    if validation_errors:
        feedback.append("drift_confirmed")
    if signal_count_delta != 0:
        feedback.append("determinant_conflict")
    if not inverse_check_passed:
        feedback.append("inverse_mismatch")
    if previous.vector_fingerprint == current.vector_fingerprint and not validation_errors:
        feedback.append("stable_progression")
    elif ir_delta_raw > 0.02 and not validation_errors:
        feedback.append("strengthened_progression")
    elif ir_delta_raw < -0.02 or stability_delta_raw < -0.02:
        feedback.append("weakened_progression")
    if delta_magnitude > 0.25:
        feedback.append("semantic_jump")
    if current.ok and not validation_errors and current.stability_score >= 0.75 and current.ir_readiness_score >= 0.875:
        feedback.append("ir_ready")
    else:
        feedback.append("ir_blocked")
    unique_feedback = tuple(dict.fromkeys(feedback))
    mirror_fingerprint = _canonical_sha256(
        {
            "previous_vector_fingerprint": previous.vector_fingerprint,
            "current_vector_fingerprint": current.vector_fingerprint,
            "forward_delta_sha256": forward_delta,
            "inverse_delta_sha256": inverse_delta,
            "delta_magnitude": delta_magnitude,
            "stability_delta": round(stability_delta_raw, 12),
            "ir_readiness_delta": round(ir_delta_raw, 12),
            "signal_count_delta": signal_count_delta,
            "inverse_check_passed": inverse_check_passed,
            "discrete_feedback": unique_feedback,
            "semantic_conclusions": False,
            "formal_ir_committed": False,
        }
    )
    return CSVInterpoleMirrorDelta(
        previous_vector_fingerprint=previous.vector_fingerprint,
        current_vector_fingerprint=current.vector_fingerprint,
        forward_delta_sha256=forward_delta,
        inverse_delta_sha256=inverse_delta,
        mirror_fingerprint=mirror_fingerprint,
        delta_magnitude=delta_magnitude,
        stability_delta=round(stability_delta_raw, 12),
        ir_readiness_delta=round(ir_delta_raw, 12),
        signal_count_delta=signal_count_delta,
        inverse_check_passed=inverse_check_passed,
        discrete_feedback=unique_feedback,
    )


def prepare_csv_interpole_timeline_ring(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVInterpoleTimelineRingReport:
    """Build a no-write CSV Interpole timeline ring with mirror feedback.

    The ring requires a committed determinant vector.  It compares the persisted
    vector with a fresh validation vector and emits discrete progression
    feedback.  It does not infer semantics or commit IR.
    """
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_interpole_timeline_ring_report_key(safe_id)
    except Exception as exc:
        return _invalid_timeline_ring_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    try:
        stored_vector_report = load_csv_interpole_determinant_vector_report(directory, safe_id)
    except Exception as exc:
        return _invalid_timeline_ring_report(
            safe_id,
            f"interpole_determinant_vector_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
        )

    determinant_validation = validate_csv_interpole_determinant_vector(directory, safe_id, chunk_size=chunk_size, encoding=encoding)
    ring = _timeline_ring(safe_id, determinant_validation.vector)
    errors: list[str] = list(determinant_validation.errors)
    warnings: list[str] = list(determinant_validation.warnings)
    if stored_vector_report.status not in {"determinants_committed", "valid"}:
        errors.append(f"stored_interpole_determinant_vector_not_committed:{stored_vector_report.status}")
    if not determinant_validation.vector.ok:
        errors.append("interpole_timeline_ring_vector_not_clean")
    if not ring.ok:
        errors.append("interpole_timeline_ring_not_clean")
    mirror = _mirror_delta(stored_vector_report.vector, determinant_validation.vector, validation_errors=tuple(dict.fromkeys(errors)))
    if not mirror.inverse_check_passed:
        errors.append("interpole_timeline_ring_inverse_check_failed")
    if "determinant_conflict" in mirror.discrete_feedback:
        errors.append("interpole_timeline_ring_determinant_conflict")
    if "semantic_jump" in mirror.discrete_feedback:
        warnings.append("interpole_timeline_ring_semantic_jump_observed")

    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    status = "ring_ready" if not unique_errors else "drifted"
    return CSVInterpoleTimelineRingReport(
        csv_id=safe_id,
        status=status,
        interpole_version=CSV_INTERPOLE_TIMELINE_VERSION,
        determinant_vector_version=CSV_INTERPOLE_DETERMINANT_VECTOR_VERSION,
        timeline_ring_version=CSV_INTERPOLE_TIMELINE_RING_VERSION,
        report_key=report_key,
        mode="timeline_ring_prepare",
        ring=ring,
        mirror_delta=mirror,
        source_determinant_vector_report_key=stored_vector_report.report_key,
        source_vector_fingerprint=stored_vector_report.vector_fingerprint,
        determinant_validation_status=determinant_validation.status,
        errors=unique_errors,
        warnings=unique_warnings,
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=True,
        invertible_mirror_feedback=True,
        formal_ir_committed=False,
    )


def commit_csv_interpole_timeline_ring_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    overwrite: bool = False,
    encoding: str = "utf-8",
) -> CSVInterpoleTimelineRingReport:
    """Persist a compact derived Interpole timeline-ring mirror report."""
    report = prepare_csv_interpole_timeline_ring(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    if not report.ok:
        return report
    committed = CSVInterpoleTimelineRingReport(
        csv_id=report.csv_id,
        status="ring_committed",
        interpole_version=report.interpole_version,
        determinant_vector_version=report.determinant_vector_version,
        timeline_ring_version=report.timeline_ring_version,
        report_key=report.report_key,
        mode="timeline_ring_commit",
        ring=report.ring,
        mirror_delta=report.mirror_delta,
        source_determinant_vector_report_key=report.source_determinant_vector_report_key,
        source_vector_fingerprint=report.source_vector_fingerprint,
        determinant_validation_status=report.determinant_validation_status,
        warnings=report.warnings,
        tds_artifact_writes=1,
        native_storage_writes=False,
        native_c_engine_changed=False,
        native_csv_kernel_used=False,
        per_row_writes=False,
        per_cell_writes=False,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=True,
        invertible_mirror_feedback=True,
        formal_ir_committed=False,
    )
    result: TDSResult = directory.write_json(committed.report_key, committed.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return CSVInterpoleTimelineRingReport(
            csv_id=report.csv_id,
            status="invalid",
            interpole_version=report.interpole_version,
            determinant_vector_version=report.determinant_vector_version,
            timeline_ring_version=report.timeline_ring_version,
            report_key=report.report_key,
            mode="timeline_ring_commit",
            ring=report.ring,
            mirror_delta=report.mirror_delta,
            source_determinant_vector_report_key=report.source_determinant_vector_report_key,
            source_vector_fingerprint=report.source_vector_fingerprint,
            determinant_validation_status=report.determinant_validation_status,
            errors=(f"interpole_timeline_ring_report_write_failed:{result.code}:{result.message}",),
            warnings=report.warnings,
            tds_artifact_writes=0,
            native_storage_writes=False,
            native_c_engine_changed=False,
            native_csv_kernel_used=False,
            per_row_writes=False,
            per_cell_writes=False,
            native_storage_hot_path_touched=False,
            semantic_reasoning=False,
            semantic_conclusions=False,
            determinant_vectoring=True,
            timeline_ring_materialized=True,
            invertible_mirror_feedback=True,
            formal_ir_committed=False,
        )
    return committed


def load_csv_interpole_timeline_ring_report(directory: TDSDirectory, csv_id: str) -> CSVInterpoleTimelineRingReport:
    """Load a persisted CSV Interpole timeline-ring mirror report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_interpole_timeline_ring_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV Interpole timeline ring report {key!r} is not a JSON object")
    return CSVInterpoleTimelineRingReport.from_mapping(value)


def validate_csv_interpole_timeline_ring(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = None,
    encoding: str = "utf-8",
) -> CSVInterpoleTimelineRingReport:
    """Validate a persisted Interpole timeline ring against fresh evidence."""
    try:
        stored = load_csv_interpole_timeline_ring_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_interpole_timeline_ring_report_key(csv_id)
        except Exception:
            report_key = ""
        return _invalid_timeline_ring_report(str(csv_id), f"interpole_timeline_ring_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_interpole_timeline_ring(directory, csv_id, chunk_size=chunk_size, encoding=encoding)
    errors: list[str] = list(fresh.errors)
    warnings: list[str] = list(dict.fromkeys(tuple(stored.warnings) + tuple(fresh.warnings)))
    if stored.status not in {"ring_committed", "valid"}:
        errors.append(f"stored_interpole_timeline_ring_not_committed:{stored.status}")
    if stored.ring_fingerprint != fresh.ring_fingerprint:
        errors.append("interpole_timeline_ring_fingerprint_drift")
    if stored.mirror_fingerprint != fresh.mirror_fingerprint:
        errors.append("interpole_timeline_ring_mirror_fingerprint_drift")
    if stored.source_vector_fingerprint != fresh.source_vector_fingerprint:
        errors.append("interpole_timeline_ring_source_vector_fingerprint_drift")
    if stored.node_count != fresh.node_count:
        errors.append("interpole_timeline_ring_node_count_drift")

    unique_errors = tuple(dict.fromkeys(errors))
    status = "valid" if not unique_errors else "drifted"
    return CSVInterpoleTimelineRingReport(
        csv_id=fresh.csv_id,
        status=status,
        interpole_version=fresh.interpole_version,
        determinant_vector_version=fresh.determinant_vector_version,
        timeline_ring_version=fresh.timeline_ring_version,
        report_key=stored.report_key,
        mode="validation",
        ring=fresh.ring,
        mirror_delta=fresh.mirror_delta,
        source_determinant_vector_report_key=fresh.source_determinant_vector_report_key,
        source_vector_fingerprint=fresh.source_vector_fingerprint,
        determinant_validation_status=fresh.determinant_validation_status,
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
        semantic_conclusions=False,
        determinant_vectoring=True,
        timeline_ring_materialized=True,
        invertible_mirror_feedback=True,
        formal_ir_committed=False,
    )


def csv_interpole_timeline_ring_summary(report: CSVInterpoleTimelineRingReport) -> dict[str, Any]:
    """Return a compact dashboard/API summary for an Interpole timeline ring."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "mode": report.mode,
        "interpole_version": report.interpole_version,
        "determinant_vector_version": report.determinant_vector_version,
        "timeline_ring_version": report.timeline_ring_version,
        "ring_fingerprint": report.ring_fingerprint,
        "mirror_fingerprint": report.mirror_fingerprint,
        "source_vector_fingerprint": report.source_vector_fingerprint,
        "determinant_validation_status": report.determinant_validation_status,
        "node_count": report.node_count,
        "stable_node_count": report.ring.stable_node_count,
        "watch_node_count": report.ring.watch_node_count,
        "weakened_node_count": report.ring.weakened_node_count,
        "blocked_node_count": report.ring.blocked_node_count,
        "drifted_node_count": report.ring.drifted_node_count,
        "ring_stability_score": report.ring.ring_stability_score,
        "ring_ir_readiness_score": report.ring.ring_ir_readiness_score,
        "delta_magnitude": report.mirror_delta.delta_magnitude,
        "stability_delta": report.mirror_delta.stability_delta,
        "ir_readiness_delta": report.mirror_delta.ir_readiness_delta,
        "signal_count_delta": report.mirror_delta.signal_count_delta,
        "inverse_check_passed": report.mirror_delta.inverse_check_passed,
        "discrete_feedback": list(report.discrete_feedback),
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_writes": report.native_storage_writes,
        "native_c_engine_changed": report.native_c_engine_changed,
        "native_csv_kernel_used": report.native_csv_kernel_used,
        "per_row_writes": report.per_row_writes,
        "per_cell_writes": report.per_cell_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "semantic_reasoning": report.semantic_reasoning,
        "semantic_conclusions": report.semantic_conclusions,
        "determinant_vectoring": report.determinant_vectoring,
        "timeline_ring_materialized": report.timeline_ring_materialized,
        "invertible_mirror_feedback": report.invertible_mirror_feedback,
        "formal_ir_committed": report.formal_ir_committed,
    }

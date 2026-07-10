"""Optional durable CSV scan artifacts for the v3.3.x scan/kernel lane.

The scanner and row-anchor primitives remain above storage.  This module
materializes their compact profiles as ordinary JSON artifacts when an
application explicitly asks for scan evidence to become part of a .tds dataset.
Routine CSV import remains fixed-shape and does not write these artifacts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import TDSDirectory

from .importer import load_csv_manifest
from .manifest import artifact_keys, validate_csv_id
from .scanner import (
    CSVRowAnchorProfile,
    CSVScanProfile,
    scan_csv_bytes,
    scan_csv_row_anchors,
    validate_csv_row_anchors,
    validate_csv_scan_profile,
)


def csv_scan_artifact_keys(csv_id: str) -> dict[str, str]:
    """Return optional scan-artifact keys for a managed CSV source.

    These keys are intentionally separate from :func:`artifact_keys` so the
    core import manifest and fixed write count remain stable.  They are advanced
    evidence artifacts a caller may opt into after import/reload validation.
    """
    csv_id = validate_csv_id(csv_id)
    prefix = f"csv__{csv_id}"
    return {
        "scan_profile": f"{prefix}__scan_profile.json",
        "row_anchor_profile": f"{prefix}__row_anchor_profile.json",
        "scan_materialization_report": f"{prefix}__scan_materialization_report.json",
    }


@dataclass(frozen=True, slots=True)
class CSVScanArtifactReport:
    """Materialization/validation report for optional CSV scan artifacts."""

    csv_id: str
    status: str
    scan_profile_key: str
    row_anchor_profile_key: str
    materialization_report_key: str
    wrote_scan_profile: bool
    wrote_row_anchor_profile: bool
    write_count: int
    checked_artifacts: tuple[str, ...]
    raw_sha256_verified: bool
    row_offsets_match: bool
    row_count_match: bool
    scan_profile_match: bool
    row_anchor_profile_match: bool
    row_anchor_hash_count: int
    chunk_size: int | None
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"materialized", "valid"} and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_artifacts"] = list(self.checked_artifacts)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVScanArtifactReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            scan_profile_key=str(data.get("scan_profile_key", "")),
            row_anchor_profile_key=str(data.get("row_anchor_profile_key", "")),
            materialization_report_key=str(data.get("materialization_report_key", "")),
            wrote_scan_profile=bool(data.get("wrote_scan_profile", False)),
            wrote_row_anchor_profile=bool(data.get("wrote_row_anchor_profile", False)),
            write_count=int(data.get("write_count", 0)),
            checked_artifacts=tuple(str(v) for v in data.get("checked_artifacts", []) or []),
            raw_sha256_verified=bool(data.get("raw_sha256_verified", False)),
            row_offsets_match=bool(data.get("row_offsets_match", False)),
            row_count_match=bool(data.get("row_count_match", False)),
            scan_profile_match=bool(data.get("scan_profile_match", False)),
            row_anchor_profile_match=bool(data.get("row_anchor_profile_match", False)),
            row_anchor_hash_count=int(data.get("row_anchor_hash_count", 0)),
            chunk_size=(None if data.get("chunk_size") is None else int(data.get("chunk_size"))),
            errors=tuple(str(v) for v in data.get("errors", []) or []),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
        )




def _invalid_scan_artifact_report(csv_id: str, *, chunk_size: int | None, error: str) -> CSVScanArtifactReport:
    return CSVScanArtifactReport(
        csv_id=str(csv_id),
        status="invalid",
        scan_profile_key="",
        row_anchor_profile_key="",
        materialization_report_key="",
        wrote_scan_profile=False,
        wrote_row_anchor_profile=False,
        write_count=0,
        checked_artifacts=tuple(),
        raw_sha256_verified=False,
        row_offsets_match=False,
        row_count_match=False,
        scan_profile_match=False,
        row_anchor_profile_match=False,
        row_anchor_hash_count=0,
        chunk_size=chunk_size,
        errors=(error,),
    )

def _require_mapping(value: Any, artifact_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"CSV scan artifact {artifact_name!r} is not a JSON object")
    return value


def _require_write(result: TDSResult, artifact: str) -> None:
    if not result.ok:
        raise RuntimeError(f"CSV scan artifact write failed for {artifact}: {result.code} {result.message}")


def _read_raw_bytes(directory: TDSDirectory, csv_id: str) -> tuple[bytes, Any]:
    manifest = load_csv_manifest(directory, csv_id)
    raw_key = artifact_keys(csv_id)["raw"]
    raw_value = directory.read_value(raw_key)
    if not isinstance(raw_value, str):
        raise TypeError(f"CSV raw artifact {raw_key!r} is not text")
    return raw_value.encode(manifest.encoding), manifest


def load_csv_scan_profile(directory: TDSDirectory, csv_id: str) -> CSVScanProfile:
    """Load a materialized CSV scan profile from .tds storage."""
    key = csv_scan_artifact_keys(csv_id)["scan_profile"]
    return CSVScanProfile.from_mapping(_require_mapping(directory.read_value(key), "scan_profile"))


def load_csv_row_anchor_profile(directory: TDSDirectory, csv_id: str) -> CSVRowAnchorProfile:
    """Load a materialized CSV row-anchor profile from .tds storage."""
    key = csv_scan_artifact_keys(csv_id)["row_anchor_profile"]
    return CSVRowAnchorProfile.from_mapping(_require_mapping(directory.read_value(key), "row_anchor_profile"))


def load_csv_scan_materialization_report(directory: TDSDirectory, csv_id: str) -> CSVScanArtifactReport:
    """Load the latest CSV scan materialization report."""
    key = csv_scan_artifact_keys(csv_id)["scan_materialization_report"]
    return CSVScanArtifactReport.from_mapping(_require_mapping(directory.read_value(key), "scan_materialization_report"))


def materialize_csv_scan_artifacts(
    directory: TDSDirectory,
    csv_id: str,
    *,
    include_row_anchors: bool = True,
    chunk_size: int | None = None,
    overwrite: bool = False,
) -> CSVScanArtifactReport:
    """Persist optional scan evidence as compact derived JSON artifacts.

    The function validates durable raw/manifest/row-offset parity before any
    scan artifact is written.  It writes one scan profile, optionally one
    row-anchor profile, and one materialization report; it never writes per-row
    or per-cell artifacts and never changes the native storage hot path.
    """
    try:
        keys = csv_scan_artifact_keys(csv_id)
    except Exception as exc:
        return _invalid_scan_artifact_report(csv_id, chunk_size=chunk_size, error=f"csv_id_unsafe:{type(exc).__name__}:{exc}")
    checked = ["manifest", "raw", "row_offsets"]
    errors: list[str] = []

    scan_parity = validate_csv_scan_profile(directory, csv_id, chunk_size=chunk_size)
    if not scan_parity.ok:
        errors.extend(scan_parity.errors)

    anchor_parity = None
    if include_row_anchors:
        anchor_parity = validate_csv_row_anchors(directory, csv_id, chunk_size=chunk_size)
        if not anchor_parity.ok:
            errors.extend(anchor_parity.errors)

    if errors:
        return CSVScanArtifactReport(
            csv_id=csv_id,
            status="invalid",
            scan_profile_key=keys["scan_profile"],
            row_anchor_profile_key=keys["row_anchor_profile"],
            materialization_report_key=keys["scan_materialization_report"],
            wrote_scan_profile=False,
            wrote_row_anchor_profile=False,
            write_count=0,
            checked_artifacts=tuple(dict.fromkeys(checked)),
            raw_sha256_verified=scan_parity.raw_sha256_verified,
            row_offsets_match=scan_parity.row_offsets_match,
            row_count_match=scan_parity.row_count_match,
            scan_profile_match=False,
            row_anchor_profile_match=False,
            row_anchor_hash_count=0,
            chunk_size=chunk_size,
            errors=tuple(dict.fromkeys(errors)),
        )

    raw, manifest = _read_raw_bytes(directory, csv_id)
    profile = scan_csv_bytes(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)
    anchors = None
    if include_row_anchors:
        anchors = scan_csv_row_anchors(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)

    write_count = 0
    _require_write(directory.write_json(keys["scan_profile"], profile.to_dict(), overwrite=overwrite, provenance="DERIVED"), keys["scan_profile"])
    write_count += 1
    if anchors is not None:
        _require_write(directory.write_json(keys["row_anchor_profile"], anchors.to_dict(), overwrite=overwrite, provenance="DERIVED"), keys["row_anchor_profile"])
        write_count += 1
    checked.extend(["scan_profile"] + (["row_anchor_profile"] if anchors is not None else []))

    report = CSVScanArtifactReport(
        csv_id=csv_id,
        status="materialized",
        scan_profile_key=keys["scan_profile"],
        row_anchor_profile_key=keys["row_anchor_profile"],
        materialization_report_key=keys["scan_materialization_report"],
        wrote_scan_profile=True,
        wrote_row_anchor_profile=anchors is not None,
        write_count=write_count + 1,
        checked_artifacts=tuple(dict.fromkeys(checked)),
        raw_sha256_verified=scan_parity.raw_sha256_verified,
        row_offsets_match=scan_parity.row_offsets_match,
        row_count_match=scan_parity.row_count_match,
        scan_profile_match=True,
        row_anchor_profile_match=anchors is not None or not include_row_anchors,
        row_anchor_hash_count=0 if anchors is None else anchors.row_count,
        chunk_size=chunk_size,
    )
    _require_write(directory.write_json(keys["scan_materialization_report"], report.to_dict(), overwrite=overwrite, provenance="DERIVED"), keys["scan_materialization_report"])
    return report


def validate_materialized_csv_scan_artifacts(
    directory: TDSDirectory,
    csv_id: str,
    *,
    require_row_anchors: bool = True,
    chunk_size: int | None = None,
) -> CSVScanArtifactReport:
    """Validate materialized scan evidence against the current durable source."""
    try:
        keys = csv_scan_artifact_keys(csv_id)
    except Exception as exc:
        return _invalid_scan_artifact_report(csv_id, chunk_size=chunk_size, error=f"csv_id_unsafe:{type(exc).__name__}:{exc}")
    errors: list[str] = []
    checked = ["manifest", "raw", "row_offsets", "scan_profile"]

    raw, manifest = _read_raw_bytes(directory, csv_id)
    fresh_profile = scan_csv_bytes(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)
    stored_profile = load_csv_scan_profile(directory, csv_id)
    scan_profile_match = stored_profile.to_dict() == fresh_profile.to_dict()
    if not scan_profile_match:
        if stored_profile.raw_sha256 != fresh_profile.raw_sha256:
            errors.append("materialized_scan_profile_raw_sha256_mismatch")
        if stored_profile.row_offsets != fresh_profile.row_offsets:
            errors.append("materialized_scan_profile_row_offsets_mismatch")
        if stored_profile.row_count != fresh_profile.row_count:
            errors.append("materialized_scan_profile_row_count_mismatch")
        if stored_profile.to_dict() != fresh_profile.to_dict() and not errors:
            errors.append("materialized_scan_profile_shape_mismatch")

    row_anchor_profile_match = not require_row_anchors
    row_anchor_hash_count = 0
    if require_row_anchors:
        checked.append("row_anchor_profile")
        fresh_anchors = scan_csv_row_anchors(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)
        stored_anchors = load_csv_row_anchor_profile(directory, csv_id)
        row_anchor_hash_count = stored_anchors.row_count
        row_anchor_profile_match = stored_anchors.to_dict() == fresh_anchors.to_dict()
        if not row_anchor_profile_match:
            if stored_anchors.raw_sha256 != fresh_anchors.raw_sha256:
                errors.append("materialized_row_anchor_raw_sha256_mismatch")
            if stored_anchors.row_offsets != fresh_anchors.row_offsets:
                errors.append("materialized_row_anchor_offsets_mismatch")
            if stored_anchors.row_anchor_hashes != fresh_anchors.row_anchor_hashes:
                errors.append("materialized_row_anchor_hashes_mismatch")
            if stored_anchors.row_count != fresh_anchors.row_count:
                errors.append("materialized_row_anchor_count_mismatch")
            if stored_anchors.to_dict() != fresh_anchors.to_dict() and not any(error.startswith("materialized_row_anchor") for error in errors):
                errors.append("materialized_row_anchor_shape_mismatch")

    return CSVScanArtifactReport(
        csv_id=csv_id,
        status="valid" if not errors else "invalid",
        scan_profile_key=keys["scan_profile"],
        row_anchor_profile_key=keys["row_anchor_profile"],
        materialization_report_key=keys["scan_materialization_report"],
        wrote_scan_profile=False,
        wrote_row_anchor_profile=False,
        write_count=0,
        checked_artifacts=tuple(dict.fromkeys(checked)),
        raw_sha256_verified=stored_profile.raw_sha256 == fresh_profile.raw_sha256,
        row_offsets_match=stored_profile.row_offsets == fresh_profile.row_offsets,
        row_count_match=stored_profile.row_count == fresh_profile.row_count,
        scan_profile_match=scan_profile_match,
        row_anchor_profile_match=row_anchor_profile_match,
        row_anchor_hash_count=row_anchor_hash_count,
        chunk_size=chunk_size,
        errors=tuple(dict.fromkeys(errors)),
    )

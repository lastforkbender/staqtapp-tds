"""Optional native row-anchor / row-offset parity kernel for v3.4.7.

This module advances the CSV kernel lane one step beyond the v3.4.6 scan
prototype: the optional native sidecar may now provide logical row offsets and
row spans used to derive row-anchor hashes.  The hashes remain mechanical byte
anchors only.  They do not define semantic row identity, infer schemas, or move
CSV work into the native storage hot path.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import TDSDirectory

from .artifacts import CSVDialectFingerprint
from .importer import load_csv_manifest
from .manifest import artifact_keys, validate_csv_id
from .row_offsets import pack_csv_row_offsets
from .scanner import (
    CSVRowAnchorProfile,
    scan_csv_row_anchors,
    validate_csv_row_anchors,
    validate_csv_scan_profile,
)
from .native_scan import (
    CSV_NATIVE_SCAN_KERNEL_BACKEND,
    CSV_NATIVE_SCAN_KERNEL_FALLBACK,
    csv_native_scan_kernel_report_key,
    load_csv_native_scan_kernel_prototype_report,
    validate_csv_native_scan_kernel_prototype,
)

CSV_NATIVE_ROW_ANCHOR_KERNEL_VERSION = "1.0"
CSV_NATIVE_ROW_ANCHOR_KERNEL_BACKEND = "native.c.csv_scan.row_anchor_offsets.v1"
CSV_NATIVE_ROW_ANCHOR_KERNEL_FALLBACK = "python.memoryview.row_anchor.reference"


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def csv_native_row_anchor_kernel_report_key(csv_id: str) -> str:
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__native_row_anchor_kernel_report.json"


@dataclass(frozen=True, slots=True)
class CSVNativeRowAnchorKernelReport:
    """Parity-gated report for native row-offset / row-anchor evidence."""

    csv_id: str
    status: str
    native_row_anchor_kernel_version: str
    report_key: str
    mode: str
    source_native_scan_report_key: str
    source_native_scan_fingerprint: str
    source_reference_scan_fingerprint: str
    anchor_fingerprint: str
    reference_anchor_fingerprint: str
    raw_sha256: str
    native_scan_validation_status: str
    scan_parity_status: str
    row_anchor_parity_status: str
    native_backend_available: bool
    native_backend_used: bool
    native_backend_name: str
    requested_native: bool
    force_native: bool
    python_reference_fallback_available: bool
    python_reference_fallback_used: bool
    fallback_reason: str
    native_offsets_match_reference: bool
    native_spans_match_reference: bool
    native_anchor_hashes_match_reference: bool
    native_anchor_fingerprint_match_reference: bool
    raw_sha256_verified: bool
    row_count_match: bool
    max_record_span_match: bool
    scanner: str
    reference_scanner: str
    chunk_size: int | None
    chunk_count: int
    raw_size: int
    row_count: int
    max_record_span: int
    digest_algorithm: str
    row_offsets_packed_sha256: str
    row_spans_sha256: str
    row_anchor_hashes_sha256: str
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
            self.status in {"native_row_anchor_ready", "native_row_anchor_committed", "valid"}
            and not self.errors
            and self.source_native_scan_fingerprint != ""
            and self.source_reference_scan_fingerprint != ""
            and self.anchor_fingerprint != ""
            and self.reference_anchor_fingerprint != ""
            and self.anchor_fingerprint == self.reference_anchor_fingerprint
            and self.native_scan_validation_status == "valid"
            and self.scan_parity_status == "valid"
            and self.row_anchor_parity_status == "valid"
            and self.native_offsets_match_reference
            and self.native_spans_match_reference
            and self.native_anchor_hashes_match_reference
            and self.native_anchor_fingerprint_match_reference
            and self.raw_sha256_verified
            and self.row_count_match
            and self.max_record_span_match
            and self.digest_algorithm == "sha256"
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
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "CSVNativeRowAnchorKernelReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            native_row_anchor_kernel_version=str(data.get("native_row_anchor_kernel_version", CSV_NATIVE_ROW_ANCHOR_KERNEL_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "")),
            source_native_scan_report_key=str(data.get("source_native_scan_report_key", "")),
            source_native_scan_fingerprint=str(data.get("source_native_scan_fingerprint", "")),
            source_reference_scan_fingerprint=str(data.get("source_reference_scan_fingerprint", "")),
            anchor_fingerprint=str(data.get("anchor_fingerprint", "")),
            reference_anchor_fingerprint=str(data.get("reference_anchor_fingerprint", "")),
            raw_sha256=str(data.get("raw_sha256", "")),
            native_scan_validation_status=str(data.get("native_scan_validation_status", "not_checked")),
            scan_parity_status=str(data.get("scan_parity_status", "not_checked")),
            row_anchor_parity_status=str(data.get("row_anchor_parity_status", "not_checked")),
            native_backend_available=bool(data.get("native_backend_available", False)),
            native_backend_used=bool(data.get("native_backend_used", False)),
            native_backend_name=str(data.get("native_backend_name", "")),
            requested_native=bool(data.get("requested_native", False)),
            force_native=bool(data.get("force_native", False)),
            python_reference_fallback_available=bool(data.get("python_reference_fallback_available", True)),
            python_reference_fallback_used=bool(data.get("python_reference_fallback_used", False)),
            fallback_reason=str(data.get("fallback_reason", "")),
            native_offsets_match_reference=bool(data.get("native_offsets_match_reference", False)),
            native_spans_match_reference=bool(data.get("native_spans_match_reference", False)),
            native_anchor_hashes_match_reference=bool(data.get("native_anchor_hashes_match_reference", False)),
            native_anchor_fingerprint_match_reference=bool(data.get("native_anchor_fingerprint_match_reference", False)),
            raw_sha256_verified=bool(data.get("raw_sha256_verified", False)),
            row_count_match=bool(data.get("row_count_match", False)),
            max_record_span_match=bool(data.get("max_record_span_match", False)),
            scanner=str(data.get("scanner", "")),
            reference_scanner=str(data.get("reference_scanner", CSV_NATIVE_ROW_ANCHOR_KERNEL_FALLBACK)),
            chunk_size=(None if data.get("chunk_size") is None else int(data.get("chunk_size"))),
            chunk_count=int(data.get("chunk_count", 0)),
            raw_size=int(data.get("raw_size", 0)),
            row_count=int(data.get("row_count", 0)),
            max_record_span=int(data.get("max_record_span", 0)),
            digest_algorithm=str(data.get("digest_algorithm", "sha256")),
            row_offsets_packed_sha256=str(data.get("row_offsets_packed_sha256", "")),
            row_spans_sha256=str(data.get("row_spans_sha256", "")),
            row_anchor_hashes_sha256=str(data.get("row_anchor_hashes_sha256", "")),
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


def _empty_native_row_anchor_report(
    csv_id: str,
    error: str,
    *,
    report_key: str = "",
    requested_native: bool = False,
    force_native: bool = False,
) -> CSVNativeRowAnchorKernelReport:
    return CSVNativeRowAnchorKernelReport(
        csv_id=csv_id,
        status="invalid",
        native_row_anchor_kernel_version=CSV_NATIVE_ROW_ANCHOR_KERNEL_VERSION,
        report_key=report_key,
        mode="native_row_anchor_prepare",
        source_native_scan_report_key="",
        source_native_scan_fingerprint="",
        source_reference_scan_fingerprint="",
        anchor_fingerprint="",
        reference_anchor_fingerprint="",
        raw_sha256="",
        native_scan_validation_status="not_checked",
        scan_parity_status="not_checked",
        row_anchor_parity_status="not_checked",
        native_backend_available=False,
        native_backend_used=False,
        native_backend_name="",
        requested_native=requested_native,
        force_native=force_native,
        python_reference_fallback_available=True,
        python_reference_fallback_used=False,
        fallback_reason="",
        native_offsets_match_reference=False,
        native_spans_match_reference=False,
        native_anchor_hashes_match_reference=False,
        native_anchor_fingerprint_match_reference=False,
        raw_sha256_verified=False,
        row_count_match=False,
        max_record_span_match=False,
        scanner="",
        reference_scanner=CSV_NATIVE_ROW_ANCHOR_KERNEL_FALLBACK,
        chunk_size=None,
        chunk_count=0,
        raw_size=0,
        row_count=0,
        max_record_span=0,
        digest_algorithm="sha256",
        row_offsets_packed_sha256="",
        row_spans_sha256="",
        row_anchor_hashes_sha256="",
        warnings=tuple(),
        errors=(error,),
    )


def _single_byte_token(value: str | None, *, encoding: str, default: bytes) -> int:
    if not value:
        return default[0]
    try:
        token = value.encode(encoding)
    except Exception:
        return default[0]
    return token[0] if len(token) == 1 else default[0]


def _load_native_backend() -> tuple[Any | None, str, tuple[str, ...]]:
    try:
        module = importlib.import_module("staqtapp_tds._csv_scan_kernel")
    except Exception as exc:
        return None, "", (f"native_csv_row_anchor_kernel_unavailable:{type(exc).__name__}:{exc}",)
    if not hasattr(module, "row_offsets"):
        return None, "", ("native_csv_row_anchor_kernel_missing_row_offsets",)
    base = str(getattr(module, "CSV_NATIVE_SCAN_KERNEL_BACKEND", CSV_NATIVE_SCAN_KERNEL_BACKEND))
    return module, f"{base}.row_offsets", tuple()


def _row_anchor_fingerprint(profile: CSVRowAnchorProfile) -> str:
    return _canonical_sha256(
        {
            "version": CSV_NATIVE_ROW_ANCHOR_KERNEL_VERSION,
            "encoding": profile.encoding,
            "raw_size": profile.raw_size,
            "raw_sha256": profile.raw_sha256,
            "row_offsets": list(profile.row_offsets),
            "row_spans": list(profile.row_spans),
            "row_anchor_hashes": list(profile.row_anchor_hashes),
            "row_count": profile.row_count,
            "digest_algorithm": profile.digest_algorithm,
            "chunk_size": profile.chunk_size,
            "chunk_count": profile.chunk_count,
        }
    )


def _tuple_sha256(values: tuple[Any, ...]) -> str:
    return _canonical_sha256(list(values))


def _max_record_span(spans: tuple[int, ...]) -> int:
    return max(spans) if spans else 0


def _native_row_anchor_profile(
    raw: bytes,
    dialect: CSVDialectFingerprint,
    *,
    encoding: str,
    chunk_size: int | None,
    backend: Any,
    backend_name: str,
) -> CSVRowAnchorProfile:
    quote = _single_byte_token(dialect.quotechar, encoding=encoding, default=b'"')
    escape = -1
    if dialect.escapechar:
        escape_raw = dialect.escapechar.encode(encoding)
        if len(escape_raw) == 1:
            escape = escape_raw[0]
    c_data = backend.row_offsets(
        raw,
        quote=quote,
        escape=escape,
        doublequote=1 if dialect.doublequote else 0,
        chunk_size=0 if chunk_size is None else int(chunk_size),
    )
    view = memoryview(raw).cast("B")
    offsets = tuple(int(v) for v in c_data["row_offsets"])
    spans = tuple(int(v) for v in c_data["row_spans"])
    if len(offsets) != len(spans):
        raise ValueError("native CSV row-offset kernel returned mismatched offsets/spans")
    if any(offset < 0 or offset > len(view) for offset in offsets):
        raise ValueError("native CSV row-offset kernel returned out-of-range offset")
    hashes: list[str] = []
    for start, span in zip(offsets, spans, strict=True):
        if span < 0 or start + span > len(view):
            raise ValueError("native CSV row-offset kernel returned out-of-range span")
        hashes.append(hashlib.sha256(view[start : start + span]).hexdigest())
    return CSVRowAnchorProfile(
        encoding=encoding,
        raw_size=int(c_data["raw_size"]),
        raw_sha256=hashlib.sha256(view).hexdigest(),
        row_offsets=offsets,
        row_spans=spans,
        row_anchor_hashes=tuple(hashes),
        row_count=int(c_data["row_count"]),
        digest_algorithm="sha256",
        chunk_size=chunk_size,
        chunk_count=int(c_data["chunk_count"]),
        scanner=backend_name or CSV_NATIVE_ROW_ANCHOR_KERNEL_BACKEND,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def prepare_csv_native_row_anchor_kernel(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
    use_native: bool = False,
    force_native: bool = False,
) -> CSVNativeRowAnchorKernelReport:
    """Build a no-write native row-anchor parity report.

    The v3.4.7 report requires a committed v3.4.6 native scan report and then
    proves that fresh row offsets, row spans, and row-anchor hashes match the
    Python reference and durable CSV artifacts.  Missing native support falls
    back to the Python reference unless ``force_native`` is set.
    """
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_native_row_anchor_kernel_report_key(safe_id)
    except Exception as exc:
        return _empty_native_row_anchor_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}", requested_native=use_native, force_native=force_native)

    try:
        native_scan_report = load_csv_native_scan_kernel_prototype_report(directory, safe_id)
    except Exception as exc:
        return _empty_native_row_anchor_report(
            safe_id,
            f"native_scan_kernel_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
            requested_native=use_native,
            force_native=force_native,
        )

    errors: list[str] = []
    warnings: list[str] = []
    try:
        # The v3.4.6 scan report fingerprint intentionally includes its
        # artificial chunk size. Revalidate that committed report with its own
        # stored chunk shape, while allowing this row-anchor check to exercise a
        # separate chunk boundary for fresh row-anchor parity.
        native_scan_validation = validate_csv_native_scan_kernel_prototype(directory, safe_id, chunk_size=native_scan_report.chunk_size)
        manifest = load_csv_manifest(directory, safe_id)
        raw_value = directory.read_value(artifact_keys(safe_id)["raw"])
        if not isinstance(raw_value, str):
            raise TypeError("CSV raw artifact is not text")
        raw = raw_value.encode(manifest.encoding)
        reference_profile = scan_csv_row_anchors(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)
        scan_parity = validate_csv_scan_profile(directory, safe_id, chunk_size=chunk_size)
        row_anchor_parity = validate_csv_row_anchors(directory, safe_id, chunk_size=chunk_size)
    except Exception as exc:
        return _empty_native_row_anchor_report(
            safe_id,
            f"native_row_anchor_prepare_failed:{type(exc).__name__}:{exc}",
            report_key=report_key,
            requested_native=use_native,
            force_native=force_native,
        )

    if native_scan_report.status not in {"native_scan_committed", "valid"}:
        errors.append(f"native_scan_kernel_report_not_committed:{native_scan_report.status}")
    if not native_scan_validation.ok:
        errors.append(f"native_scan_kernel_validation_not_valid:{native_scan_validation.status}")
        errors.extend(str(v) for v in native_scan_validation.errors)
    if scan_parity.status != "valid":
        errors.append(f"scan_parity_not_valid:{scan_parity.status}")
        errors.extend(str(v) for v in scan_parity.errors)
    if row_anchor_parity.status != "valid":
        errors.append(f"row_anchor_parity_not_valid:{row_anchor_parity.status}")
        errors.extend(str(v) for v in row_anchor_parity.errors)

    backend_module, backend_name, backend_errors = _load_native_backend()
    native_available = backend_module is not None
    native_used = False
    fallback_used = False
    fallback_reason = ""
    profile = reference_profile

    if use_native:
        if native_available:
            try:
                profile = _native_row_anchor_profile(
                    raw,
                    manifest.dialect,
                    encoding=manifest.encoding,
                    chunk_size=chunk_size,
                    backend=backend_module,
                    backend_name=backend_name,
                )
                native_used = True
            except Exception as exc:
                native_available = False
                backend_name = ""
                backend_errors = (f"native_csv_row_anchor_kernel_failed:{type(exc).__name__}:{exc}",)
        if not native_used:
            fallback_reason = backend_errors[0] if backend_errors else "native_csv_row_anchor_kernel_not_used"
            if force_native:
                errors.append(fallback_reason)
            else:
                fallback_used = True
                warnings.append(f"python_reference_fallback_used:{fallback_reason}")
                profile = reference_profile

    native_offsets_match_reference = profile.row_offsets == reference_profile.row_offsets
    native_spans_match_reference = profile.row_spans == reference_profile.row_spans
    native_anchor_hashes_match_reference = profile.row_anchor_hashes == reference_profile.row_anchor_hashes
    reference_fingerprint = _row_anchor_fingerprint(reference_profile)
    profile_fingerprint = _row_anchor_fingerprint(profile)
    native_anchor_fingerprint_match_reference = profile_fingerprint == reference_fingerprint
    raw_sha256_verified = profile.raw_sha256 == reference_profile.raw_sha256 == manifest.raw_sha256
    row_count_match = profile.row_count == reference_profile.row_count == manifest.row_count
    max_record_span_match = _max_record_span(profile.row_spans) == _max_record_span(reference_profile.row_spans)

    if not native_offsets_match_reference:
        errors.append("native_row_anchor_offsets_mismatch_reference")
    if not native_spans_match_reference:
        errors.append("native_row_anchor_spans_mismatch_reference")
    if not native_anchor_hashes_match_reference:
        errors.append("native_row_anchor_hashes_mismatch_reference")
    if not native_anchor_fingerprint_match_reference:
        errors.append("native_row_anchor_fingerprint_mismatch_reference")
    if not raw_sha256_verified:
        errors.append("native_row_anchor_raw_sha256_mismatch")
    if not row_count_match:
        errors.append("native_row_anchor_row_count_mismatch")
    if not max_record_span_match:
        errors.append("native_row_anchor_max_record_span_mismatch")

    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    status = "native_row_anchor_ready" if not unique_errors else "blocked"
    return CSVNativeRowAnchorKernelReport(
        csv_id=safe_id,
        status=status,
        native_row_anchor_kernel_version=CSV_NATIVE_ROW_ANCHOR_KERNEL_VERSION,
        report_key=report_key,
        mode="native_row_anchor_prepare",
        source_native_scan_report_key=csv_native_scan_kernel_report_key(safe_id),
        source_native_scan_fingerprint=native_scan_report.scan_fingerprint,
        source_reference_scan_fingerprint=native_scan_report.reference_scan_fingerprint,
        anchor_fingerprint=profile_fingerprint,
        reference_anchor_fingerprint=reference_fingerprint,
        raw_sha256=profile.raw_sha256,
        native_scan_validation_status=native_scan_validation.status,
        scan_parity_status=scan_parity.status,
        row_anchor_parity_status=row_anchor_parity.status,
        native_backend_available=native_available,
        native_backend_used=native_used,
        native_backend_name=backend_name if native_available else "",
        requested_native=use_native,
        force_native=force_native,
        python_reference_fallback_available=True,
        python_reference_fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        native_offsets_match_reference=native_offsets_match_reference,
        native_spans_match_reference=native_spans_match_reference,
        native_anchor_hashes_match_reference=native_anchor_hashes_match_reference,
        native_anchor_fingerprint_match_reference=native_anchor_fingerprint_match_reference,
        raw_sha256_verified=raw_sha256_verified,
        row_count_match=row_count_match,
        max_record_span_match=max_record_span_match,
        scanner=profile.scanner,
        reference_scanner=reference_profile.scanner,
        chunk_size=chunk_size,
        chunk_count=profile.chunk_count,
        raw_size=profile.raw_size,
        row_count=profile.row_count,
        max_record_span=_max_record_span(profile.row_spans),
        digest_algorithm=profile.digest_algorithm,
        row_offsets_packed_sha256=hashlib.sha256(pack_csv_row_offsets(profile.row_offsets)).hexdigest(),
        row_spans_sha256=_tuple_sha256(profile.row_spans),
        row_anchor_hashes_sha256=_tuple_sha256(profile.row_anchor_hashes),
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


def commit_csv_native_row_anchor_kernel_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
    use_native: bool = False,
    force_native: bool = False,
    overwrite: bool = False,
) -> CSVNativeRowAnchorKernelReport:
    """Persist a compact native row-anchor parity report."""
    report = prepare_csv_native_row_anchor_kernel(
        directory,
        csv_id,
        chunk_size=chunk_size,
        use_native=use_native,
        force_native=force_native,
    )
    if not report.ok:
        return report
    committed = replace(report, status="native_row_anchor_committed", mode="native_row_anchor_commit", tds_artifact_writes=1)
    result: TDSResult = directory.write_json(committed.report_key, committed.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return replace(committed, status="blocked", errors=(f"native_row_anchor_kernel_report_write_failed:{result.code}",), tds_artifact_writes=0)
    return committed


def load_csv_native_row_anchor_kernel_report(directory: TDSDirectory, csv_id: str) -> CSVNativeRowAnchorKernelReport:
    """Load a committed native row-anchor parity report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_native_row_anchor_kernel_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV native row-anchor kernel report {key!r} is not a JSON object")
    return CSVNativeRowAnchorKernelReport.from_mapping(value)


def validate_csv_native_row_anchor_kernel(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
) -> CSVNativeRowAnchorKernelReport:
    """Validate a committed native row-anchor report against fresh evidence."""
    try:
        stored = load_csv_native_row_anchor_kernel_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_native_row_anchor_kernel_report_key(csv_id)
        except Exception:
            report_key = ""
        return _empty_native_row_anchor_report(str(csv_id), f"native_row_anchor_kernel_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_native_row_anchor_kernel(
        directory,
        stored.csv_id,
        chunk_size=chunk_size,
        use_native=stored.requested_native,
        force_native=stored.force_native,
    )
    errors = list(fresh.errors)
    warnings = list(fresh.warnings)
    if stored.status not in {"native_row_anchor_committed", "valid"}:
        errors.append(f"stored_native_row_anchor_kernel_not_committed:{stored.status}")
    if stored.source_native_scan_fingerprint != fresh.source_native_scan_fingerprint:
        errors.append("native_row_anchor_source_scan_fingerprint_drift")
    if stored.source_reference_scan_fingerprint != fresh.source_reference_scan_fingerprint:
        errors.append("native_row_anchor_source_reference_scan_fingerprint_drift")
    if stored.anchor_fingerprint != fresh.anchor_fingerprint:
        errors.append("native_row_anchor_fingerprint_drift")
    if stored.reference_anchor_fingerprint != fresh.reference_anchor_fingerprint:
        errors.append("native_row_anchor_reference_fingerprint_drift")
    if stored.raw_sha256 != fresh.raw_sha256:
        errors.append("native_row_anchor_raw_sha256_drift")
    if stored.row_offsets_packed_sha256 != fresh.row_offsets_packed_sha256:
        errors.append("native_row_anchor_row_offsets_hash_drift")
    if stored.row_spans_sha256 != fresh.row_spans_sha256:
        errors.append("native_row_anchor_row_spans_hash_drift")
    if stored.row_anchor_hashes_sha256 != fresh.row_anchor_hashes_sha256:
        errors.append("native_row_anchor_hash_list_drift")

    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    status = "valid" if not unique_errors and fresh.ok else "drifted"
    return replace(
        fresh,
        status=status,
        mode="validation",
        warnings=unique_warnings,
        errors=unique_errors,
        tds_artifact_writes=0,
    )


def csv_native_row_anchor_kernel_summary(report: CSVNativeRowAnchorKernelReport) -> dict[str, Any]:
    """Return a compact UI/API summary for v3.4.7 row-anchor reports."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "version": report.native_row_anchor_kernel_version,
        "report_key": report.report_key,
        "mode": report.mode,
        "source_native_scan_report_key": report.source_native_scan_report_key,
        "source_native_scan_fingerprint": report.source_native_scan_fingerprint,
        "source_reference_scan_fingerprint": report.source_reference_scan_fingerprint,
        "anchor_fingerprint": report.anchor_fingerprint,
        "reference_anchor_fingerprint": report.reference_anchor_fingerprint,
        "raw_sha256": report.raw_sha256,
        "native_scan_validation_status": report.native_scan_validation_status,
        "scan_parity_status": report.scan_parity_status,
        "row_anchor_parity_status": report.row_anchor_parity_status,
        "native_backend_available": report.native_backend_available,
        "native_backend_used": report.native_backend_used,
        "native_backend_name": report.native_backend_name,
        "requested_native": report.requested_native,
        "force_native": report.force_native,
        "python_reference_fallback_used": report.python_reference_fallback_used,
        "fallback_reason": report.fallback_reason,
        "scanner": report.scanner,
        "reference_scanner": report.reference_scanner,
        "chunk_size": report.chunk_size,
        "chunk_count": report.chunk_count,
        "raw_size": report.raw_size,
        "row_count": report.row_count,
        "max_record_span": report.max_record_span,
        "digest_algorithm": report.digest_algorithm,
        "native_offsets_match_reference": report.native_offsets_match_reference,
        "native_spans_match_reference": report.native_spans_match_reference,
        "native_anchor_hashes_match_reference": report.native_anchor_hashes_match_reference,
        "native_anchor_fingerprint_match_reference": report.native_anchor_fingerprint_match_reference,
        "raw_sha256_verified": report.raw_sha256_verified,
        "row_count_match": report.row_count_match,
        "max_record_span_match": report.max_record_span_match,
        "row_offsets_packed_sha256": report.row_offsets_packed_sha256,
        "row_spans_sha256": report.row_spans_sha256,
        "row_anchor_hashes_sha256": report.row_anchor_hashes_sha256,
        "tds_artifact_writes": report.tds_artifact_writes,
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
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }

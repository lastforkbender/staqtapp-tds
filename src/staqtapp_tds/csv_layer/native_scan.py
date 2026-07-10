"""Optional CSV native scan-kernel prototype for v3.4.6.

The v3.4.6 lane introduces the first optional native CSV scan sidecar while
keeping the v3.4.5 readiness contract as the admission gate.  The native path is
never a storage hot path controller: it reads immutable CSV bytes, produces a
mechanical scan profile, and must prove parity against the Python reference
scanner before the report can be committed.
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
from .kernel import (
    csv_kernel_readiness_report_key,
    load_csv_kernel_readiness_contract_report,
    validate_csv_kernel_readiness_contract,
)
from .manifest import artifact_keys, validate_csv_id
from .scanner import CSVScanProfile, scan_csv_bytes, validate_csv_row_anchors, validate_csv_scan_profile

CSV_NATIVE_SCAN_KERNEL_VERSION = "1.0"
CSV_NATIVE_SCAN_KERNEL_BACKEND = "native.c.csv_scan.prototype"
CSV_NATIVE_SCAN_KERNEL_FALLBACK = "python.memoryview.reference"


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def csv_native_scan_kernel_report_key(csv_id: str) -> str:
    safe_id = validate_csv_id(csv_id)
    return f"csv__{safe_id}__native_scan_kernel_report.json"


@dataclass(frozen=True, slots=True)
class CSVNativeScanKernelReport:
    """Parity-gated report for the optional native CSV scan prototype."""

    csv_id: str
    status: str
    native_scan_kernel_version: str
    report_key: str
    mode: str
    source_kernel_readiness_report_key: str
    source_contract_fingerprint: str
    scan_fingerprint: str
    reference_scan_fingerprint: str
    raw_sha256: str
    scan_parity_status: str
    row_anchor_parity_status: str
    readiness_validation_status: str
    native_backend_available: bool
    native_backend_used: bool
    native_backend_name: str
    requested_native: bool
    force_native: bool
    python_reference_fallback_available: bool
    python_reference_fallback_used: bool
    fallback_reason: str
    kernel_row_offsets_match_reference: bool
    kernel_counts_match_reference: bool
    raw_sha256_verified: bool
    row_count_match: bool
    scanner: str
    reference_scanner: str
    chunk_size: int | None
    chunk_count: int
    raw_size: int
    row_count: int
    newline_lf_count: int
    newline_crlf_count: int
    newline_cr_count: int
    quoted_newline_count: int
    delimiter_count: int
    quote_count: int
    escaped_quote_count: int
    escape_sequence_count: int
    max_record_span: int
    terminal_newline: bool
    ended_in_open_quote: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    tds_artifact_writes: int = 0
    native_storage_writes: bool = False
    native_storage_hot_path_touched: bool = False
    native_storage_locks_controlled: bool = False
    native_c_storage_engine_changed: bool = False
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
            self.status in {"native_scan_ready", "native_scan_committed", "valid"}
            and not self.errors
            and self.source_contract_fingerprint != ""
            and self.scan_fingerprint != ""
            and self.reference_scan_fingerprint != ""
            and self.scan_fingerprint == self.reference_scan_fingerprint
            and self.scan_parity_status == "valid"
            and self.row_anchor_parity_status == "valid"
            and self.readiness_validation_status == "valid"
            and self.kernel_row_offsets_match_reference
            and self.kernel_counts_match_reference
            and self.raw_sha256_verified
            and self.row_count_match
            and self.python_reference_fallback_available
            and not self.native_storage_writes
            and not self.native_storage_hot_path_touched
            and not self.native_storage_locks_controlled
            and not self.native_c_storage_engine_changed
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
    def from_mapping(cls, data: dict[str, Any]) -> "CSVNativeScanKernelReport":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            native_scan_kernel_version=str(data.get("native_scan_kernel_version", CSV_NATIVE_SCAN_KERNEL_VERSION)),
            report_key=str(data.get("report_key", "")),
            mode=str(data.get("mode", "")),
            source_kernel_readiness_report_key=str(data.get("source_kernel_readiness_report_key", "")),
            source_contract_fingerprint=str(data.get("source_contract_fingerprint", "")),
            scan_fingerprint=str(data.get("scan_fingerprint", "")),
            reference_scan_fingerprint=str(data.get("reference_scan_fingerprint", "")),
            raw_sha256=str(data.get("raw_sha256", "")),
            scan_parity_status=str(data.get("scan_parity_status", "not_checked")),
            row_anchor_parity_status=str(data.get("row_anchor_parity_status", "not_checked")),
            readiness_validation_status=str(data.get("readiness_validation_status", "not_checked")),
            native_backend_available=bool(data.get("native_backend_available", False)),
            native_backend_used=bool(data.get("native_backend_used", False)),
            native_backend_name=str(data.get("native_backend_name", "")),
            requested_native=bool(data.get("requested_native", False)),
            force_native=bool(data.get("force_native", False)),
            python_reference_fallback_available=bool(data.get("python_reference_fallback_available", True)),
            python_reference_fallback_used=bool(data.get("python_reference_fallback_used", False)),
            fallback_reason=str(data.get("fallback_reason", "")),
            kernel_row_offsets_match_reference=bool(data.get("kernel_row_offsets_match_reference", False)),
            kernel_counts_match_reference=bool(data.get("kernel_counts_match_reference", False)),
            raw_sha256_verified=bool(data.get("raw_sha256_verified", False)),
            row_count_match=bool(data.get("row_count_match", False)),
            scanner=str(data.get("scanner", "")),
            reference_scanner=str(data.get("reference_scanner", CSV_NATIVE_SCAN_KERNEL_FALLBACK)),
            chunk_size=(None if data.get("chunk_size") is None else int(data.get("chunk_size"))),
            chunk_count=int(data.get("chunk_count", 0)),
            raw_size=int(data.get("raw_size", 0)),
            row_count=int(data.get("row_count", 0)),
            newline_lf_count=int(data.get("newline_lf_count", 0)),
            newline_crlf_count=int(data.get("newline_crlf_count", 0)),
            newline_cr_count=int(data.get("newline_cr_count", 0)),
            quoted_newline_count=int(data.get("quoted_newline_count", 0)),
            delimiter_count=int(data.get("delimiter_count", 0)),
            quote_count=int(data.get("quote_count", 0)),
            escaped_quote_count=int(data.get("escaped_quote_count", 0)),
            escape_sequence_count=int(data.get("escape_sequence_count", 0)),
            max_record_span=int(data.get("max_record_span", 0)),
            terminal_newline=bool(data.get("terminal_newline", False)),
            ended_in_open_quote=bool(data.get("ended_in_open_quote", False)),
            warnings=tuple(str(v) for v in data.get("warnings", ()) or ()),
            errors=tuple(str(v) for v in data.get("errors", ()) or ()),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            native_storage_locks_controlled=bool(data.get("native_storage_locks_controlled", False)),
            native_c_storage_engine_changed=bool(data.get("native_c_storage_engine_changed", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            semantic_reasoning=bool(data.get("semantic_reasoning", False)),
            semantic_conclusions=bool(data.get("semantic_conclusions", False)),
            schema_inference=bool(data.get("schema_inference", False)),
            type_inference=bool(data.get("type_inference", False)),
            entity_inference=bool(data.get("entity_inference", False)),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
        )


def _empty_native_scan_report(
    csv_id: str,
    error: str,
    *,
    report_key: str = "",
    requested_native: bool = False,
    force_native: bool = False,
) -> CSVNativeScanKernelReport:
    return CSVNativeScanKernelReport(
        csv_id=csv_id,
        status="invalid",
        native_scan_kernel_version=CSV_NATIVE_SCAN_KERNEL_VERSION,
        report_key=report_key,
        mode="native_scan_prepare",
        source_kernel_readiness_report_key="",
        source_contract_fingerprint="",
        scan_fingerprint="",
        reference_scan_fingerprint="",
        raw_sha256="",
        scan_parity_status="not_checked",
        row_anchor_parity_status="not_checked",
        readiness_validation_status="not_checked",
        native_backend_available=False,
        native_backend_used=False,
        native_backend_name="",
        requested_native=requested_native,
        force_native=force_native,
        python_reference_fallback_available=True,
        python_reference_fallback_used=False,
        fallback_reason="",
        kernel_row_offsets_match_reference=False,
        kernel_counts_match_reference=False,
        raw_sha256_verified=False,
        row_count_match=False,
        scanner="",
        reference_scanner=CSV_NATIVE_SCAN_KERNEL_FALLBACK,
        chunk_size=None,
        chunk_count=0,
        raw_size=0,
        row_count=0,
        newline_lf_count=0,
        newline_crlf_count=0,
        newline_cr_count=0,
        quoted_newline_count=0,
        delimiter_count=0,
        quote_count=0,
        escaped_quote_count=0,
        escape_sequence_count=0,
        max_record_span=0,
        terminal_newline=False,
        ended_in_open_quote=False,
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
        return None, "", (f"native_csv_scan_kernel_unavailable:{type(exc).__name__}:{exc}",)
    if not hasattr(module, "scan_bytes"):
        return None, "", ("native_csv_scan_kernel_missing_scan_bytes",)
    backend = str(getattr(module, "CSV_NATIVE_SCAN_KERNEL_BACKEND", CSV_NATIVE_SCAN_KERNEL_BACKEND))
    return module, backend, tuple()


def _scan_profile_fingerprint(profile: CSVScanProfile) -> str:
    """Fingerprint mechanical scan evidence, intentionally excluding backend labels."""
    return _canonical_sha256(
        {
            "version": CSV_NATIVE_SCAN_KERNEL_VERSION,
            "encoding": profile.encoding,
            "raw_size": profile.raw_size,
            "raw_sha256": profile.raw_sha256,
            "row_offsets": list(profile.row_offsets),
            "row_count": profile.row_count,
            "newline_lf_count": profile.newline_lf_count,
            "newline_crlf_count": profile.newline_crlf_count,
            "newline_cr_count": profile.newline_cr_count,
            "quoted_newline_count": profile.quoted_newline_count,
            "delimiter_count": profile.delimiter_count,
            "quote_count": profile.quote_count,
            "escaped_quote_count": profile.escaped_quote_count,
            "escape_sequence_count": profile.escape_sequence_count,
            "max_record_span": profile.max_record_span,
            "terminal_newline": profile.terminal_newline,
            "ended_in_open_quote": profile.ended_in_open_quote,
            "chunk_size": profile.chunk_size,
            "chunk_count": profile.chunk_count,
        }
    )


def _counts_tuple(profile: CSVScanProfile) -> tuple[Any, ...]:
    return (
        profile.raw_size,
        profile.row_count,
        profile.newline_lf_count,
        profile.newline_crlf_count,
        profile.newline_cr_count,
        profile.quoted_newline_count,
        profile.delimiter_count,
        profile.quote_count,
        profile.escaped_quote_count,
        profile.escape_sequence_count,
        profile.max_record_span,
        profile.terminal_newline,
        profile.ended_in_open_quote,
        profile.chunk_size,
        profile.chunk_count,
    )


def _native_scan_profile(
    raw: bytes,
    dialect: CSVDialectFingerprint,
    *,
    encoding: str,
    chunk_size: int | None,
    backend: Any,
    backend_name: str,
) -> CSVScanProfile:
    delimiter = _single_byte_token(dialect.delimiter, encoding=encoding, default=b",")
    quote = _single_byte_token(dialect.quotechar, encoding=encoding, default=b'"')
    escape = -1
    if dialect.escapechar:
        escape_raw = dialect.escapechar.encode(encoding)
        if len(escape_raw) == 1:
            escape = escape_raw[0]
    c_data = backend.scan_bytes(
        raw,
        delimiter=delimiter,
        quote=quote,
        escape=escape,
        doublequote=1 if dialect.doublequote else 0,
        chunk_size=0 if chunk_size is None else int(chunk_size),
    )
    raw_hash = hashlib.sha256(memoryview(raw).cast("B")).hexdigest()
    return CSVScanProfile(
        encoding=encoding,
        raw_size=int(c_data["raw_size"]),
        raw_sha256=raw_hash,
        row_offsets=tuple(int(v) for v in c_data["row_offsets"]),
        row_count=int(c_data["row_count"]),
        newline_lf_count=int(c_data["newline_lf_count"]),
        newline_crlf_count=int(c_data["newline_crlf_count"]),
        newline_cr_count=int(c_data["newline_cr_count"]),
        quoted_newline_count=int(c_data["quoted_newline_count"]),
        delimiter_count=int(c_data["delimiter_count"]),
        quote_count=int(c_data["quote_count"]),
        escaped_quote_count=int(c_data["escaped_quote_count"]),
        escape_sequence_count=int(c_data["escape_sequence_count"]),
        max_record_span=int(c_data["max_record_span"]),
        terminal_newline=bool(c_data["terminal_newline"]),
        ended_in_open_quote=bool(c_data["ended_in_open_quote"]),
        chunk_size=chunk_size,
        chunk_count=int(c_data["chunk_count"]),
        scanner=backend_name or CSV_NATIVE_SCAN_KERNEL_BACKEND,
        native_storage_hot_path_touched=False,
        semantic_reasoning=False,
    )


def prepare_csv_native_scan_kernel_prototype(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
    use_native: bool = False,
    force_native: bool = False,
) -> CSVNativeScanKernelReport:
    """Build a no-write report for the optional native CSV scan prototype.

    ``use_native`` asks for the sidecar when it is importable. ``force_native``
    turns missing native support into a fail-closed block. Without either flag,
    the Python reference remains the default-safe execution path.
    """
    try:
        safe_id = validate_csv_id(csv_id)
        report_key = csv_native_scan_kernel_report_key(safe_id)
    except Exception as exc:
        return _empty_native_scan_report(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}", requested_native=use_native, force_native=force_native)

    try:
        readiness = load_csv_kernel_readiness_contract_report(directory, safe_id)
    except Exception as exc:
        return _empty_native_scan_report(
            safe_id,
            f"kernel_readiness_contract_report_unreadable:{type(exc).__name__}:{exc}",
            report_key=report_key,
            requested_native=use_native,
            force_native=force_native,
        )

    warnings: list[str] = []
    errors: list[str] = []
    try:
        readiness_validation = validate_csv_kernel_readiness_contract(directory, safe_id)
        manifest = load_csv_manifest(directory, safe_id)
        raw_value = directory.read_value(artifact_keys(safe_id)["raw"])
        if not isinstance(raw_value, str):
            raise TypeError("CSV raw artifact is not text")
        raw = raw_value.encode(manifest.encoding)
        reference_profile = scan_csv_bytes(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=chunk_size)
        scan_parity = validate_csv_scan_profile(directory, safe_id, chunk_size=chunk_size)
        row_anchor_parity = validate_csv_row_anchors(directory, safe_id, chunk_size=chunk_size)
    except Exception as exc:
        return _empty_native_scan_report(
            safe_id,
            f"native_scan_prepare_failed:{type(exc).__name__}:{exc}",
            report_key=report_key,
            requested_native=use_native,
            force_native=force_native,
        )

    if readiness.status not in {"kernel_contract_committed", "valid"}:
        errors.append(f"kernel_readiness_contract_not_committed:{readiness.status}")
    if not readiness_validation.ok:
        errors.append(f"kernel_readiness_contract_validation_not_valid:{readiness_validation.status}")
        errors.extend(str(v) for v in readiness_validation.errors)
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
                profile = _native_scan_profile(
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
                backend_errors = (f"native_csv_scan_kernel_failed:{type(exc).__name__}:{exc}",)
        if not native_used:
            fallback_reason = backend_errors[0] if backend_errors else "native_csv_scan_kernel_not_used"
            if force_native:
                errors.append(fallback_reason)
            else:
                fallback_used = True
                warnings.append(f"python_reference_fallback_used:{fallback_reason}")
                profile = reference_profile

    kernel_row_offsets_match_reference = profile.row_offsets == reference_profile.row_offsets
    kernel_counts_match_reference = _counts_tuple(profile) == _counts_tuple(reference_profile)
    raw_sha256_verified = profile.raw_sha256 == reference_profile.raw_sha256 == manifest.raw_sha256
    row_count_match = profile.row_count == reference_profile.row_count == manifest.row_count
    if not kernel_row_offsets_match_reference:
        errors.append("native_scan_row_offsets_mismatch_reference")
    if not kernel_counts_match_reference:
        errors.append("native_scan_counts_mismatch_reference")
    if not raw_sha256_verified:
        errors.append("native_scan_raw_sha256_mismatch")
    if not row_count_match:
        errors.append("native_scan_row_count_mismatch")

    reference_fingerprint = _scan_profile_fingerprint(reference_profile)
    profile_fingerprint = _scan_profile_fingerprint(profile)
    if profile_fingerprint != reference_fingerprint:
        errors.append("native_scan_fingerprint_mismatch_reference")

    unique_errors = tuple(dict.fromkeys(errors))
    unique_warnings = tuple(dict.fromkeys(warnings))
    status = "native_scan_ready" if not unique_errors else "blocked"
    return CSVNativeScanKernelReport(
        csv_id=safe_id,
        status=status,
        native_scan_kernel_version=CSV_NATIVE_SCAN_KERNEL_VERSION,
        report_key=report_key,
        mode="native_scan_prepare",
        source_kernel_readiness_report_key=csv_kernel_readiness_report_key(safe_id),
        source_contract_fingerprint=readiness.contract_fingerprint,
        scan_fingerprint=profile_fingerprint,
        reference_scan_fingerprint=reference_fingerprint,
        raw_sha256=profile.raw_sha256,
        scan_parity_status=scan_parity.status,
        row_anchor_parity_status=row_anchor_parity.status,
        readiness_validation_status=readiness_validation.status,
        native_backend_available=native_available,
        native_backend_used=native_used,
        native_backend_name=backend_name if native_available else "",
        requested_native=use_native,
        force_native=force_native,
        python_reference_fallback_available=True,
        python_reference_fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        kernel_row_offsets_match_reference=kernel_row_offsets_match_reference,
        kernel_counts_match_reference=kernel_counts_match_reference,
        raw_sha256_verified=raw_sha256_verified,
        row_count_match=row_count_match,
        scanner=profile.scanner,
        reference_scanner=reference_profile.scanner,
        chunk_size=chunk_size,
        chunk_count=profile.chunk_count,
        raw_size=profile.raw_size,
        row_count=profile.row_count,
        newline_lf_count=profile.newline_lf_count,
        newline_crlf_count=profile.newline_crlf_count,
        newline_cr_count=profile.newline_cr_count,
        quoted_newline_count=profile.quoted_newline_count,
        delimiter_count=profile.delimiter_count,
        quote_count=profile.quote_count,
        escaped_quote_count=profile.escaped_quote_count,
        escape_sequence_count=profile.escape_sequence_count,
        max_record_span=profile.max_record_span,
        terminal_newline=profile.terminal_newline,
        ended_in_open_quote=profile.ended_in_open_quote,
        warnings=unique_warnings,
        errors=unique_errors,
        tds_artifact_writes=0,
        native_storage_writes=False,
        native_storage_hot_path_touched=False,
        native_storage_locks_controlled=False,
        native_c_storage_engine_changed=False,
        per_row_writes=False,
        per_cell_writes=False,
        semantic_reasoning=False,
        semantic_conclusions=False,
        schema_inference=False,
        type_inference=False,
        entity_inference=False,
        formal_ir_committed=False,
    )


def commit_csv_native_scan_kernel_prototype_report(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
    use_native: bool = False,
    force_native: bool = False,
    overwrite: bool = False,
) -> CSVNativeScanKernelReport:
    """Persist a compact parity-gated native scan prototype report."""
    report = prepare_csv_native_scan_kernel_prototype(
        directory,
        csv_id,
        chunk_size=chunk_size,
        use_native=use_native,
        force_native=force_native,
    )
    if not report.ok:
        return report
    committed = replace(report, status="native_scan_committed", mode="native_scan_commit", tds_artifact_writes=1)
    result: TDSResult = directory.write_json(committed.report_key, committed.to_dict(), overwrite=overwrite, provenance="DERIVED")
    if not result.ok:
        return replace(committed, status="blocked", errors=(f"native_scan_kernel_report_write_failed:{result.code}",), tds_artifact_writes=0)
    return committed


def load_csv_native_scan_kernel_prototype_report(directory: TDSDirectory, csv_id: str) -> CSVNativeScanKernelReport:
    """Load a committed native scan prototype report."""
    safe_id = validate_csv_id(csv_id)
    key = csv_native_scan_kernel_report_key(safe_id)
    value = directory.read_value(key)
    if not isinstance(value, dict):
        raise TypeError(f"CSV native scan kernel report {key!r} is not a JSON object")
    return CSVNativeScanKernelReport.from_mapping(value)


def validate_csv_native_scan_kernel_prototype(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
) -> CSVNativeScanKernelReport:
    """Validate a committed native scan prototype report against fresh evidence."""
    try:
        stored = load_csv_native_scan_kernel_prototype_report(directory, csv_id)
    except Exception as exc:
        try:
            report_key = csv_native_scan_kernel_report_key(csv_id)
        except Exception:
            report_key = ""
        return _empty_native_scan_report(str(csv_id), f"native_scan_kernel_report_unreadable:{type(exc).__name__}:{exc}", report_key=report_key)

    fresh = prepare_csv_native_scan_kernel_prototype(
        directory,
        stored.csv_id,
        chunk_size=chunk_size,
        use_native=stored.requested_native,
        force_native=stored.force_native,
    )
    errors = list(fresh.errors)
    warnings = list(fresh.warnings)
    if stored.status not in {"native_scan_committed", "valid"}:
        errors.append(f"stored_native_scan_kernel_not_committed:{stored.status}")
    if stored.source_contract_fingerprint != fresh.source_contract_fingerprint:
        errors.append("native_scan_source_contract_fingerprint_drift")
    if stored.scan_fingerprint != fresh.scan_fingerprint:
        errors.append("native_scan_profile_fingerprint_drift")
    if stored.reference_scan_fingerprint != fresh.reference_scan_fingerprint:
        errors.append("native_scan_reference_profile_fingerprint_drift")
    if stored.raw_sha256 != fresh.raw_sha256:
        errors.append("native_scan_raw_sha256_drift")

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


def csv_native_scan_kernel_summary(report: CSVNativeScanKernelReport) -> dict[str, Any]:
    """Return a compact UI/API summary for v3.4.6 native scan prototype reports."""
    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "ok": report.ok,
        "version": report.native_scan_kernel_version,
        "report_key": report.report_key,
        "mode": report.mode,
        "source_contract_fingerprint": report.source_contract_fingerprint,
        "scan_fingerprint": report.scan_fingerprint,
        "reference_scan_fingerprint": report.reference_scan_fingerprint,
        "raw_sha256": report.raw_sha256,
        "scan_parity_status": report.scan_parity_status,
        "row_anchor_parity_status": report.row_anchor_parity_status,
        "readiness_validation_status": report.readiness_validation_status,
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
        "kernel_row_offsets_match_reference": report.kernel_row_offsets_match_reference,
        "kernel_counts_match_reference": report.kernel_counts_match_reference,
        "raw_sha256_verified": report.raw_sha256_verified,
        "row_count_match": report.row_count_match,
        "tds_artifact_writes": report.tds_artifact_writes,
        "native_storage_writes": report.native_storage_writes,
        "native_storage_hot_path_touched": report.native_storage_hot_path_touched,
        "native_storage_locks_controlled": report.native_storage_locks_controlled,
        "native_c_storage_engine_changed": report.native_c_storage_engine_changed,
        "semantic_reasoning": report.semantic_reasoning,
        "semantic_conclusions": report.semantic_conclusions,
        "formal_ir_committed": report.formal_ir_committed,
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }

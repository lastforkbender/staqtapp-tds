"""CSV artifact data structures for the TDS CSV foundation layer.

The CSV layer intentionally lives above the native storage engine.  It stores
raw CSV bytes/text, manifests, row-offset maps, dialect fingerprints, and
round-trip reports as normal TDS artifacts without adding CSV intelligence to
native lookup or persistence hot paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


CSV_LAYER_VERSION = "1.0"
CSV_NAMESPACE_PREFIX = "csv"


@dataclass(frozen=True, slots=True)
class CSVDialectFingerprint:
    """Stable, JSON-safe description of how a CSV source is parsed."""

    delimiter: str = ","
    quotechar: str = '"'
    escapechar: str | None = None
    doublequote: bool = True
    skipinitialspace: bool = False
    lineterminator: str = "\n"
    quoting: int = 0
    has_header: bool = False
    confidence: float = 0.0
    source: str = "sniffer"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVDialectFingerprint":
        return cls(
            delimiter=str(data.get("delimiter", ",")),
            quotechar=str(data.get("quotechar", '"')),
            escapechar=(None if data.get("escapechar") is None else str(data.get("escapechar"))),
            doublequote=bool(data.get("doublequote", True)),
            skipinitialspace=bool(data.get("skipinitialspace", False)),
            lineterminator=str(data.get("lineterminator", "\n")),
            quoting=int(data.get("quoting", 0)),
            has_header=bool(data.get("has_header", False)),
            confidence=float(data.get("confidence", 0.0)),
            source=str(data.get("source", "sniffer")),
        )


@dataclass(frozen=True, slots=True)
class CSVRowOffsetMap:
    """Logical record start offsets for a CSV source.

    Offsets are byte offsets into the original UTF-8 artifact. They are derived
    artifacts and never mutate the source payload.
    """

    encoding: str
    row_offsets: tuple[int, ...]
    row_count: int
    source_hash: str
    logical_records: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["row_offsets"] = list(self.row_offsets)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVRowOffsetMap":
        return cls(
            encoding=str(data.get("encoding", "utf-8")),
            row_offsets=tuple(int(v) for v in data.get("row_offsets", []) or []),
            row_count=int(data.get("row_count", 0)),
            source_hash=str(data.get("source_hash", "")),
            logical_records=bool(data.get("logical_records", True)),
        )


@dataclass(frozen=True, slots=True)
class CSVImportManifest:
    """Durable manifest for a TDS-managed CSV source."""

    csv_id: str
    layer_version: str
    source_name: str
    encoding: str
    raw_size: int
    raw_sha256: str
    row_count: int
    column_count: int
    has_header: bool
    dialect: CSVDialectFingerprint
    artifact_keys: dict[str, str]
    original_preserved: bool = True
    native_storage_hot_path_touched: bool = False
    writes_original: bool = False
    derived_artifacts_only: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dialect"] = self.dialect.to_dict()
        data["warnings"] = list(self.warnings)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVImportManifest":
        return cls(
            csv_id=str(data["csv_id"]),
            layer_version=str(data.get("layer_version", CSV_LAYER_VERSION)),
            source_name=str(data.get("source_name", "")),
            encoding=str(data.get("encoding", "utf-8")),
            raw_size=int(data.get("raw_size", 0)),
            raw_sha256=str(data.get("raw_sha256", "")),
            row_count=int(data.get("row_count", 0)),
            column_count=int(data.get("column_count", 0)),
            has_header=bool(data.get("has_header", False)),
            dialect=CSVDialectFingerprint.from_mapping(data.get("dialect", {}) or {}),
            artifact_keys={str(k): str(v) for k, v in (data.get("artifact_keys", {}) or {}).items()},
            original_preserved=bool(data.get("original_preserved", True)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            writes_original=bool(data.get("writes_original", False)),
            derived_artifacts_only=bool(data.get("derived_artifacts_only", True)),
            warnings=tuple(str(v) for v in data.get("warnings", []) or []),
        )


@dataclass(frozen=True, slots=True)
class CSVArtifactWritePlan:
    """Shape contract for CSV imports.

    The CSV foundation deliberately writes a small fixed artifact set instead
    of one TDS entry per cell or row. Browser telemetry and tests can use this
    plan to verify that CSV imports remain batch-artifact oriented.
    """

    artifact_count: int
    raw_artifact_count: int
    derived_artifact_count: int
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CSVImportReport:
    """Operational import result for Browser/telemetry consumption."""

    csv_id: str
    status: str
    row_count: int
    column_count: int
    raw_sha256: str
    dialect_confidence: float
    artifact_write_count: int = 6
    raw_artifact_count: int = 1
    derived_artifact_count: int = 5
    per_cell_writes: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True, slots=True)
class CSVRoundTripReport:
    """Proof report for original-byte or canonical CSV export."""

    csv_id: str
    export_mode: str
    source_sha256: str
    exported_sha256: str
    byte_equivalent: bool
    row_count: int
    column_count: int
    manifest_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True, slots=True)
class CSVArtifactValidationReport:
    """Integrity and shape report for a managed CSV artifact set.

    This report is deliberately small and JSON-safe so Browser telemetry can
    observe CSV artifact health without walking every row or cell. It validates
    durable artifact consistency above TDS storage; it does not add CSV logic to
    the native storage engine.
    """

    csv_id: str
    status: str
    checked_artifacts: tuple[str, ...]
    error_count: int
    warning_count: int
    raw_sha256_verified: bool
    row_offsets_verified: bool
    dialect_verified: bool
    manifest_consistent: bool
    original_preserved: bool
    derived_artifacts_only: bool
    native_storage_hot_path_touched: bool
    per_cell_writes: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    result_codes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "valid" and self.error_count == 0

    @property
    def primary_result_code(self) -> str:
        if self.result_codes:
            return self.result_codes[0]
        return "csv.validation.valid" if self.ok else "csv.validation.invalid"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_artifacts"] = list(self.checked_artifacts)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["result_codes"] = list(self.result_codes)
        data["primary_result_code"] = self.primary_result_code
        data["ok"] = self.ok
        return data


@dataclass(frozen=True, slots=True)
class CSVReloadedArtifacts:
    """Durable CSV artifacts rehydrated from a TDSDirectory snapshot.

    The reload model deliberately contains only values read back from storage.
    It is used to prove that CSV validation does not depend on the in-memory
    manifest or source objects created during import.
    """

    csv_id: str
    raw: str
    manifest: CSVImportManifest
    dialect: CSVDialectFingerprint
    row_offsets: CSVRowOffsetMap
    content_hashes: Mapping[str, Any]
    import_report: Mapping[str, Any]
    validation_report: CSVArtifactValidationReport

    @property
    def ok(self) -> bool:
        return self.validation_report.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "csv_id": self.csv_id,
            "raw_size": len(self.raw.encode(self.manifest.encoding)),
            "manifest": self.manifest.to_dict(),
            "dialect": self.dialect.to_dict(),
            "row_offsets": self.row_offsets.to_dict(),
            "content_hashes": dict(self.content_hashes),
            "import_report": dict(self.import_report),
            "validation_report": self.validation_report.to_dict(),
            "ok": self.ok,
        }


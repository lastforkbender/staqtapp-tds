"""Read-only CSV Interpole Browser monitor snapshots for v3.4.9/v3.4.10.

The Browser monitor turns already-committed CSV / Interpole / kernel evidence
into a compact operations-console payload.  It is intentionally snapshot-only:
it performs fresh validations, derives display cards, lanes, ring nodes, and
small event rows, but never writes CSV artifacts, mutates Interpole state, or
commits formal semantic IR.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any, Mapping

from staqtapp_tds.tds_filesystem import TDSDirectory

from .interpole import (
    CSVInterpoleDeterminantSignal,
    load_csv_interpole_determinant_vector_report,
    load_csv_interpole_timeline_ring_report,
    validate_csv_interpole_determinant_vector,
    validate_csv_interpole_timeline_ring,
)
from .kernel import load_csv_kernel_readiness_contract_report, validate_csv_kernel_readiness_contract
from .manifest import validate_csv_id
from .native_row_anchor import load_csv_native_row_anchor_kernel_report, validate_csv_native_row_anchor_kernel
from .native_scan import load_csv_native_scan_kernel_prototype_report, validate_csv_native_scan_kernel_prototype
from .performance_gates import load_csv_kernel_performance_gate_report, validate_csv_kernel_performance_gate_report


CSV_INTERPOLE_BROWSER_MONITOR_VERSION = "1.0"
CSV_INTERPOLE_MONITOR_REPLAY_VERSION = "1.0"
CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT = 65_536

CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS: tuple[str, ...] = (
    "csv_id",
    "status",
    "monitor_version",
    "mode",
    "ring_state",
    "mirror_state",
    "kernel_readiness_state",
    "performance_gate_state",
    "ring_fingerprint",
    "mirror_fingerprint",
    "source_vector_fingerprint",
    "kernel_contract_fingerprint",
    "performance_gate_fingerprint",
    "ring_stability_score",
    "ring_ir_readiness_score",
    "inverse_check_passed",
    "discrete_feedback",
    "cards",
    "ring_nodes",
    "gate_rows",
    "signal_lanes",
    "event_rows",
    "icon_names",
    "warnings",
    "errors",
    "tds_artifact_writes",
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
    "formal_ir_committed",
)

CSV_INTERPOLE_MONITOR_REQUIRED_CARD_NAMES: tuple[str, ...] = (
    "Ring State",
    "Mirror Feedback",
    "Kernel Readiness",
    "Performance Gates",
    "Native Scan Parity",
    "Row Anchor Parity",
    "Fallback Bridge",
    "Semantic Boundary",
)

CSV_INTERPOLE_MONITOR_REQUIRED_EVENT_KINDS: tuple[str, ...] = (
    "timeline_ring",
    "mirror_feedback",
    "kernel_readiness",
    "performance_gates",
    "semantic_boundary",
)

CSV_INTERPOLE_MONITOR_ICON_NAMES: tuple[str, ...] = (
    "csv-interpole",
    "csv-timeline-ring",
    "csv-mirror-delta",
    "csv-determinant-vector",
    "csv-evidence-anchor",
    "csv-parity-pair",
    "csv-readiness-gate",
    "csv-drift-flag",
    "csv-semantic-boundary",
    "csv-fallback-bridge",
    "csv-hotpath-isolation",
    "csv-compact-snapshot",
    "csv-performance-gate",
)


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorStatusCard:
    """One compact Browser card for the CSV Interpole monitor."""

    card_name: str
    icon_name: str
    status: str
    value: str
    detail: str
    severity: str = "info"

    @property
    def ok(self) -> bool:
        return self.severity in {"ok", "info", "watch"} and self.status not in {"failed", "blocked", "drifted", "invalid"}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleMonitorStatusCard":
        return cls(
            card_name=str(data.get("card_name", "")),
            icon_name=str(data.get("icon_name", "csv-compact-snapshot")),
            status=str(data.get("status", "unknown")),
            value=str(data.get("value", "—")),
            detail=str(data.get("detail", "")),
            severity=str(data.get("severity", "info")),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorRingNode:
    """Browser-safe ring node projection.

    This preserves staged movement signals without exposing row/cell content or
    declaring schema, type, entity, or IR semantics.
    """

    node_index: int
    stage_name: str
    status: str
    direction: str
    feedback_hint: str
    signal_count: int
    magnitude_average: float
    confidence_average: float
    drift_pressure: float
    ir_readiness_pressure: float
    node_fingerprint_suffix: str

    @property
    def ok(self) -> bool:
        return self.status in {"stable", "watch"} and self.direction not in {"blocked", "drifted"}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleMonitorRingNode":
        return cls(
            node_index=int(data.get("node_index", 0)),
            stage_name=str(data.get("stage_name", "")),
            status=str(data.get("status", "blocked")),
            direction=str(data.get("direction", "blocked")),
            feedback_hint=str(data.get("feedback_hint", "ir_blocked")),
            signal_count=int(data.get("signal_count", 0)),
            magnitude_average=float(data.get("magnitude_average", 0.0)),
            confidence_average=float(data.get("confidence_average", 0.0)),
            drift_pressure=float(data.get("drift_pressure", 0.0)),
            ir_readiness_pressure=float(data.get("ir_readiness_pressure", 0.0)),
            node_fingerprint_suffix=str(data.get("node_fingerprint_suffix", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorSignalLane:
    """One determinant-pressure lane for the Browser page."""

    lane_name: str
    icon_name: str
    source_stage_name: str
    direction: str
    magnitude: float
    confidence: float
    weighted_magnitude: float
    fingerprint_suffix: str
    pressure_label: str

    @property
    def ok(self) -> bool:
        return self.pressure_label in {"stable", "ready", "watch"} and self.direction not in {"blocked", "drifted"}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleMonitorSignalLane":
        return cls(
            lane_name=str(data.get("lane_name", "")),
            icon_name=str(data.get("icon_name", "csv-determinant-vector")),
            source_stage_name=str(data.get("source_stage_name", "")),
            direction=str(data.get("direction", "blocked")),
            magnitude=float(data.get("magnitude", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            weighted_magnitude=float(data.get("weighted_magnitude", 0.0)),
            fingerprint_suffix=str(data.get("fingerprint_suffix", "")),
            pressure_label=str(data.get("pressure_label", "watch")),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorGateRow:
    """One readiness/performance gate row in the Browser gate stack."""

    gate_name: str
    icon_name: str
    status: str
    detail: str
    fingerprint_suffix: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"ready", "valid", "passed", "guarded", "declared"}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleMonitorGateRow":
        return cls(
            gate_name=str(data.get("gate_name", "")),
            icon_name=str(data.get("icon_name", "csv-readiness-gate")),
            status=str(data.get("status", "blocked")),
            detail=str(data.get("detail", "")),
            fingerprint_suffix=str(data.get("fingerprint_suffix", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorEventRow:
    """One compact read-only Browser event row."""

    event_index: int
    event_kind: str
    status: str
    message: str
    fingerprint_suffix: str = ""

    @property
    def ok(self) -> bool:
        return self.status not in {"failed", "blocked", "drifted", "invalid"}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleMonitorEventRow":
        return cls(
            event_index=int(data.get("event_index", 0)),
            event_kind=str(data.get("event_kind", "event")),
            status=str(data.get("status", "info")),
            message=str(data.get("message", "")),
            fingerprint_suffix=str(data.get("fingerprint_suffix", "")),
        )


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorIconRegistryReport:
    """Validation report for the packaged CSV Interpole SVG icon registry."""

    status: str
    icon_count: int
    registry_fingerprint: str
    missing_icons: tuple[str, ...] = field(default_factory=tuple)
    unexpected_icons: tuple[str, ...] = field(default_factory=tuple)
    invalid_paths: tuple[str, ...] = field(default_factory=tuple)
    unsafe_svg_names: tuple[str, ...] = field(default_factory=tuple)
    unbounded_svg_names: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "valid" and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["missing_icons"] = list(self.missing_icons)
        data["unexpected_icons"] = list(self.unexpected_icons)
        data["invalid_paths"] = list(self.invalid_paths)
        data["unsafe_svg_names"] = list(self.unsafe_svg_names)
        data["unbounded_svg_names"] = list(self.unbounded_svg_names)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorReplayReport:
    """Read-only replay/hardening report for a Browser monitor snapshot."""

    csv_id: str
    status: str
    replay_version: str
    mode: str
    source_snapshot_fingerprint: str
    reconstructed_snapshot_fingerprint: str
    display_contract_fingerprint: str
    source_payload_bytes: int
    reconstructed_payload_bytes: int
    compared_fields: tuple[str, ...]
    matching_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]
    icon_registry_status: str
    display_contract_status: str
    payload_status: str
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
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
            self.status in {"replay_valid", "snapshot_valid"}
            and not self.errors
            and self.payload_status == "bounded"
            and self.display_contract_status == "valid"
            and self.icon_registry_status == "valid"
            and not self.mismatched_fields
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
        data["ok"] = self.ok
        data["compared_fields"] = list(self.compared_fields)
        data["matching_fields"] = list(self.matching_fields)
        data["mismatched_fields"] = list(self.mismatched_fields)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True, slots=True)
class CSVInterpoleMonitorDeliveryManifest:
    """Small release-delivery manifest object for v3.4.10 bundles."""

    release_version: str
    package_name: str
    state_packet_name: str
    sha256sums_name: str
    validation_name: str
    required_member_names: tuple[str, ...]
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.release_version == "3.4.10" and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["required_member_names"] = list(self.required_member_names)
        data["errors"] = list(self.errors)
        return data


@dataclass(frozen=True, slots=True)
class CSVInterpoleBrowserMonitorSnapshot:
    """Compact Browser-facing CSV Interpole monitor snapshot.

    The snapshot is the whole v3.4.9 contract: read-only, evidence-neutral,
    compact, and suitable for the existing TDS Browser status payload.
    """

    csv_id: str
    status: str
    monitor_version: str
    mode: str
    ring_state: str
    mirror_state: str
    kernel_readiness_state: str
    performance_gate_state: str
    ring_fingerprint: str
    mirror_fingerprint: str
    source_vector_fingerprint: str
    kernel_contract_fingerprint: str
    performance_gate_fingerprint: str
    ring_stability_score: float
    ring_ir_readiness_score: float
    inverse_check_passed: bool
    discrete_feedback: tuple[str, ...]
    cards: tuple[CSVInterpoleMonitorStatusCard, ...]
    ring_nodes: tuple[CSVInterpoleMonitorRingNode, ...]
    gate_rows: tuple[CSVInterpoleMonitorGateRow, ...]
    signal_lanes: tuple[CSVInterpoleMonitorSignalLane, ...]
    event_rows: tuple[CSVInterpoleMonitorEventRow, ...]
    icon_names: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
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
            self.status in {"monitor_ready", "valid"}
            and not self.errors
            and self.ring_state in {"stable", "watch"}
            and self.mirror_state == "coherent"
            and self.kernel_readiness_state == "ready"
            and self.performance_gate_state == "passed"
            and self.ring_fingerprint != ""
            and self.mirror_fingerprint != ""
            and self.kernel_contract_fingerprint != ""
            and self.performance_gate_fingerprint != ""
            and self.cards
            and self.ring_nodes
            and self.gate_rows
            and self.signal_lanes
            and self.icon_names == CSV_INTERPOLE_MONITOR_ICON_NAMES
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
        data["discrete_feedback"] = list(self.discrete_feedback)
        data["cards"] = [card.to_dict() for card in self.cards]
        data["ring_nodes"] = [node.to_dict() for node in self.ring_nodes]
        data["gate_rows"] = [gate.to_dict() for gate in self.gate_rows]
        data["signal_lanes"] = [lane.to_dict() for lane in self.signal_lanes]
        data["event_rows"] = [event.to_dict() for event in self.event_rows]
        data["icon_names"] = list(self.icon_names)
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["card_count"] = len(self.cards)
        data["ring_node_count"] = len(self.ring_nodes)
        data["gate_row_count"] = len(self.gate_rows)
        data["signal_lane_count"] = len(self.signal_lanes)
        data["event_row_count"] = len(self.event_rows)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVInterpoleBrowserMonitorSnapshot":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "invalid")),
            monitor_version=str(data.get("monitor_version", CSV_INTERPOLE_BROWSER_MONITOR_VERSION)),
            mode=str(data.get("mode", "browser_monitor_snapshot")),
            ring_state=str(data.get("ring_state", "blocked")),
            mirror_state=str(data.get("mirror_state", "blocked")),
            kernel_readiness_state=str(data.get("kernel_readiness_state", "blocked")),
            performance_gate_state=str(data.get("performance_gate_state", "failed")),
            ring_fingerprint=str(data.get("ring_fingerprint", "")),
            mirror_fingerprint=str(data.get("mirror_fingerprint", "")),
            source_vector_fingerprint=str(data.get("source_vector_fingerprint", "")),
            kernel_contract_fingerprint=str(data.get("kernel_contract_fingerprint", "")),
            performance_gate_fingerprint=str(data.get("performance_gate_fingerprint", "")),
            ring_stability_score=float(data.get("ring_stability_score", 0.0)),
            ring_ir_readiness_score=float(data.get("ring_ir_readiness_score", 0.0)),
            inverse_check_passed=bool(data.get("inverse_check_passed", False)),
            discrete_feedback=tuple(str(v) for v in data.get("discrete_feedback", ()) or ()),
            cards=tuple(CSVInterpoleMonitorStatusCard.from_mapping(v) for v in data.get("cards", ()) or ()),
            ring_nodes=tuple(CSVInterpoleMonitorRingNode.from_mapping(v) for v in data.get("ring_nodes", ()) or ()),
            gate_rows=tuple(CSVInterpoleMonitorGateRow.from_mapping(v) for v in data.get("gate_rows", ()) or ()),
            signal_lanes=tuple(CSVInterpoleMonitorSignalLane.from_mapping(v) for v in data.get("signal_lanes", ()) or ()),
            event_rows=tuple(CSVInterpoleMonitorEventRow.from_mapping(v) for v in data.get("event_rows", ()) or ()),
            icon_names=tuple(str(v) for v in data.get("icon_names", ()) or ()),
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


def csv_interpole_monitor_icon_registry() -> dict[str, str]:
    """Return the Browser icon names and packaged SVG asset paths."""
    return {name: f"/static/icons/{name}.svg" for name in CSV_INTERPOLE_MONITOR_ICON_NAMES}


def _suffix(value: str, *, width: int = 12) -> str:
    value = str(value or "")
    if not value:
        return ""
    return value[:width]


def _severity(ok: bool, *, watch: bool = False) -> str:
    if ok and not watch:
        return "ok"
    if ok and watch:
        return "watch"
    return "critical"


def _ring_state(report: Any) -> str:
    if getattr(report, "ok", False):
        watch_count = int(getattr(getattr(report, "ring", None), "watch_node_count", 0) or 0)
        weakened_count = int(getattr(getattr(report, "ring", None), "weakened_node_count", 0) or 0)
        return "watch" if watch_count or weakened_count else "stable"
    if str(getattr(report, "status", "")) == "drifted":
        return "drifted"
    return "blocked"


def _mirror_state(report: Any) -> str:
    mirror = getattr(report, "mirror_delta", None)
    if mirror is not None and getattr(mirror, "ok", False):
        return "coherent"
    if mirror is not None and not bool(getattr(mirror, "inverse_check_passed", False)):
        return "inverse_mismatch"
    if str(getattr(report, "status", "")) == "drifted":
        return "drifted"
    return "blocked"


def _pressure_label(signal: CSVInterpoleDeterminantSignal) -> str:
    if signal.direction == "blocked":
        return "blocked"
    if "drift" in signal.signal_name and signal.magnitude > 0.25:
        return "watch"
    if signal.magnitude >= 0.875:
        return "ready"
    return "stable" if signal.magnitude >= 0.5 else "watch"


def _signal_icon(signal_name: str) -> str:
    if "anchor" in signal_name or "evidence" in signal_name:
        return "csv-evidence-anchor"
    if "ir" in signal_name or "readiness" in signal_name:
        return "csv-readiness-gate"
    if "semantic" in signal_name:
        return "csv-semantic-boundary"
    if "drift" in signal_name:
        return "csv-drift-flag"
    return "csv-determinant-vector"


def _invalid_monitor_snapshot(csv_id: str, error: str) -> CSVInterpoleBrowserMonitorSnapshot:
    return CSVInterpoleBrowserMonitorSnapshot(
        csv_id=str(csv_id),
        status="invalid",
        monitor_version=CSV_INTERPOLE_BROWSER_MONITOR_VERSION,
        mode="browser_monitor_snapshot",
        ring_state="blocked",
        mirror_state="blocked",
        kernel_readiness_state="blocked",
        performance_gate_state="failed",
        ring_fingerprint="",
        mirror_fingerprint="",
        source_vector_fingerprint="",
        kernel_contract_fingerprint="",
        performance_gate_fingerprint="",
        ring_stability_score=0.0,
        ring_ir_readiness_score=0.0,
        inverse_check_passed=False,
        discrete_feedback=("ir_blocked",),
        cards=(
            CSVInterpoleMonitorStatusCard("Monitor Sources", "csv-compact-snapshot", "invalid", "blocked", error, "critical"),
            CSVInterpoleMonitorStatusCard("Semantic Boundary", "csv-semantic-boundary", "guarded", "IR deferred", "No semantic conclusion was committed.", "ok"),
        ),
        ring_nodes=(),
        gate_rows=(),
        signal_lanes=(),
        event_rows=(CSVInterpoleMonitorEventRow(0, "monitor_source", "invalid", error),),
        icon_names=CSV_INTERPOLE_MONITOR_ICON_NAMES,
        errors=(error,),
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


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def csv_interpole_browser_monitor_display_contract() -> dict[str, Any]:
    """Return the frozen Browser display contract for the CSV monitor page."""
    return {
        "monitor_version": CSV_INTERPOLE_BROWSER_MONITOR_VERSION,
        "replay_version": CSV_INTERPOLE_MONITOR_REPLAY_VERSION,
        "payload_byte_limit": CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT,
        "display_contract_keys": list(CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS),
        "required_card_names": list(CSV_INTERPOLE_MONITOR_REQUIRED_CARD_NAMES),
        "required_event_kinds": list(CSV_INTERPOLE_MONITOR_REQUIRED_EVENT_KINDS),
        "icon_names": list(CSV_INTERPOLE_MONITOR_ICON_NAMES),
        "semantic_exclusion_fields": [
            "semantic_reasoning",
            "semantic_conclusions",
            "schema_inference",
            "type_inference",
            "entity_inference",
            "formal_ir_committed",
        ],
        "mutation_exclusion_fields": [
            "tds_artifact_writes",
            "native_storage_writes",
            "native_storage_hot_path_touched",
            "native_storage_locks_controlled",
            "native_c_storage_engine_changed",
            "interpole_mutation",
            "per_row_writes",
            "per_cell_writes",
        ],
    }


def csv_interpole_browser_monitor_display_contract_fingerprint() -> str:
    """Return a stable fingerprint for the v3.4.10 monitor display contract."""
    return _sha256_json(csv_interpole_browser_monitor_display_contract())


def _snapshot_display_projection(snapshot: CSVInterpoleBrowserMonitorSnapshot | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(snapshot, CSVInterpoleBrowserMonitorSnapshot):
        data = snapshot.to_dict()
    else:
        data = dict(snapshot)
    return {key: data.get(key) for key in CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS}


def csv_interpole_browser_monitor_snapshot_fingerprint(snapshot: CSVInterpoleBrowserMonitorSnapshot | Mapping[str, Any]) -> str:
    """Fingerprint the Browser display projection, not raw/private runtime objects."""
    return _sha256_json(_snapshot_display_projection(snapshot))


def _snapshot_payload_bytes(snapshot: CSVInterpoleBrowserMonitorSnapshot | Mapping[str, Any]) -> int:
    return len(_canonical_json_bytes(_snapshot_display_projection(snapshot)))


def validate_csv_interpole_monitor_icon_registry(
    registry: Mapping[str, str] | None = None,
    *,
    svg_payloads: Mapping[str, bytes | str] | None = None,
    max_svg_bytes: int = 16_384,
) -> CSVInterpoleMonitorIconRegistryReport:
    """Validate icon names, registry paths, and optional packaged SVG payloads.

    The monitor uses SVG assets only.  This validator rejects missing icons,
    unexpected registry names, path drift, script-bearing SVG payloads, and SVGs
    without a bounded viewport signal.
    """
    reg = dict(registry or csv_interpole_monitor_icon_registry())
    expected = set(CSV_INTERPOLE_MONITOR_ICON_NAMES)
    actual = set(str(k) for k in reg)
    missing = tuple(sorted(expected - actual))
    unexpected = tuple(sorted(actual - expected))
    invalid_paths: list[str] = []
    unsafe_svg_names: list[str] = []
    unbounded_svg_names: list[str] = []
    for name in sorted(actual & expected):
        path = str(reg.get(name, ""))
        if path != f"/static/icons/{name}.svg":
            invalid_paths.append(name)
    if svg_payloads is not None:
        for name in CSV_INTERPOLE_MONITOR_ICON_NAMES:
            raw = svg_payloads.get(name)
            if raw is None:
                unsafe_svg_names.append(name)
                continue
            data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            text = data.decode("utf-8", errors="ignore").lower()
            if len(data) > max(1, int(max_svg_bytes)) or "<svg" not in text or "<script" in text or "javascript:" in text:
                unsafe_svg_names.append(name)
            if "viewbox" not in text and ("width=" not in text or "height=" not in text):
                unbounded_svg_names.append(name)
    errors: list[str] = []
    errors.extend(f"missing_icon:{name}" for name in missing)
    errors.extend(f"unexpected_icon:{name}" for name in unexpected)
    errors.extend(f"invalid_icon_path:{name}" for name in invalid_paths)
    errors.extend(f"unsafe_svg:{name}" for name in unsafe_svg_names)
    errors.extend(f"unbounded_svg:{name}" for name in unbounded_svg_names)
    fingerprint = _sha256_json({"icons": {name: reg.get(name, "") for name in sorted(expected)}})
    return CSVInterpoleMonitorIconRegistryReport(
        status="valid" if not errors else "blocked",
        icon_count=len(reg),
        registry_fingerprint=fingerprint,
        missing_icons=missing,
        unexpected_icons=unexpected,
        invalid_paths=tuple(invalid_paths),
        unsafe_svg_names=tuple(unsafe_svg_names),
        unbounded_svg_names=tuple(unbounded_svg_names),
        errors=tuple(errors),
        warnings=(),
    )


def _monitor_replay_report(
    *,
    csv_id: str,
    status: str,
    source_snapshot_fingerprint: str = "",
    reconstructed_snapshot_fingerprint: str = "",
    source_payload_bytes: int = 0,
    reconstructed_payload_bytes: int = 0,
    compared_fields: tuple[str, ...] = (),
    matching_fields: tuple[str, ...] = (),
    mismatched_fields: tuple[str, ...] = (),
    icon_registry_status: str = "valid",
    display_contract_status: str = "valid",
    payload_status: str = "bounded",
    errors: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> CSVInterpoleMonitorReplayReport:
    return CSVInterpoleMonitorReplayReport(
        csv_id=str(csv_id),
        status=status,
        replay_version=CSV_INTERPOLE_MONITOR_REPLAY_VERSION,
        mode="browser_monitor_replay",
        source_snapshot_fingerprint=source_snapshot_fingerprint,
        reconstructed_snapshot_fingerprint=reconstructed_snapshot_fingerprint,
        display_contract_fingerprint=csv_interpole_browser_monitor_display_contract_fingerprint(),
        source_payload_bytes=int(source_payload_bytes),
        reconstructed_payload_bytes=int(reconstructed_payload_bytes),
        compared_fields=compared_fields,
        matching_fields=matching_fields,
        mismatched_fields=mismatched_fields,
        icon_registry_status=icon_registry_status,
        display_contract_status=display_contract_status,
        payload_status=payload_status,
        errors=errors,
        warnings=warnings,
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


def validate_csv_interpole_browser_monitor_snapshot(
    snapshot: CSVInterpoleBrowserMonitorSnapshot | Mapping[str, Any],
    *,
    payload_byte_limit: int = CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT,
) -> CSVInterpoleMonitorReplayReport:
    """Validate a monitor snapshot mapping without writing or re-reading sources."""
    try:
        raw_mapping = snapshot.to_dict() if isinstance(snapshot, CSVInterpoleBrowserMonitorSnapshot) else dict(snapshot)
        obj = snapshot if isinstance(snapshot, CSVInterpoleBrowserMonitorSnapshot) else CSVInterpoleBrowserMonitorSnapshot.from_mapping(raw_mapping)
        projection = _snapshot_display_projection(obj)
        payload_bytes = _snapshot_payload_bytes(obj)
        snapshot_fingerprint = csv_interpole_browser_monitor_snapshot_fingerprint(obj)
    except Exception as exc:
        return _monitor_replay_report(
            csv_id="",
            status="snapshot_blocked",
            icon_registry_status="blocked",
            display_contract_status="blocked",
            payload_status="invalid",
            errors=(f"snapshot_unreadable:{type(exc).__name__}:{exc}",),
        )

    errors: list[str] = []
    warnings: list[str] = []
    missing_keys = tuple(key for key in CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS if key not in raw_mapping)
    if missing_keys:
        errors.extend(f"display_contract_missing:{key}" for key in missing_keys)
    if obj.monitor_version != CSV_INTERPOLE_BROWSER_MONITOR_VERSION:
        errors.append(f"monitor_version_mismatch:{obj.monitor_version}")
    if obj.mode != "browser_monitor_snapshot":
        errors.append(f"mode_mismatch:{obj.mode}")
    if tuple(obj.icon_names) != CSV_INTERPOLE_MONITOR_ICON_NAMES:
        errors.append("icon_registry_mismatch")
    card_names = tuple(card.card_name for card in obj.cards)
    event_kinds = tuple(event.event_kind for event in obj.event_rows)
    for card_name in CSV_INTERPOLE_MONITOR_REQUIRED_CARD_NAMES:
        if card_name not in card_names:
            errors.append(f"required_card_missing:{card_name}")
    for event_kind in CSV_INTERPOLE_MONITOR_REQUIRED_EVENT_KINDS:
        if event_kind not in event_kinds:
            errors.append(f"required_event_missing:{event_kind}")
    if len(set(card_names)) != len(card_names):
        errors.append("duplicate_card_name")
    if len(set(event_kinds)) != len(event_kinds):
        errors.append("duplicate_event_kind")
    if obj.status == "monitor_ready":
        if card_names != CSV_INTERPOLE_MONITOR_REQUIRED_CARD_NAMES:
            errors.append("card_contract_mismatch")
        if event_kinds != CSV_INTERPOLE_MONITOR_REQUIRED_EVENT_KINDS:
            errors.append("event_contract_mismatch")
    if tuple(node.node_index for node in obj.ring_nodes) != tuple(range(len(obj.ring_nodes))):
        errors.append("ring_node_index_sequence_invalid")
    if tuple(event.event_index for event in obj.event_rows) != tuple(range(len(obj.event_rows))):
        errors.append("event_index_sequence_invalid")
    allowed_icons = set(CSV_INTERPOLE_MONITOR_ICON_NAMES)
    used_icons = tuple(card.icon_name for card in obj.cards) + tuple(gate.icon_name for gate in obj.gate_rows) + tuple(lane.icon_name for lane in obj.signal_lanes)
    for icon_name in used_icons:
        if icon_name not in allowed_icons:
            errors.append(f"unregistered_icon_reference:{icon_name}")
    for field_name, value in (
        ("ring_stability_score", obj.ring_stability_score),
        ("ring_ir_readiness_score", obj.ring_ir_readiness_score),
    ):
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            errors.append(f"numeric_contract_invalid:{field_name}")
    if len(obj.cards) > 32 or len(obj.ring_nodes) > 64 or len(obj.gate_rows) > 64 or len(obj.signal_lanes) > 64 or len(obj.event_rows) > 64:
        errors.append("display_collection_bound_exceeded")
    if payload_bytes > max(1, int(payload_byte_limit)):
        errors.append(f"payload_too_large:{payload_bytes}>{int(payload_byte_limit)}")
    if obj.status == "monitor_ready":
        if not obj.ring_fingerprint:
            errors.append("ring_fingerprint_empty")
        if not obj.mirror_fingerprint:
            errors.append("mirror_fingerprint_empty")
        if not obj.kernel_contract_fingerprint:
            errors.append("kernel_contract_fingerprint_empty")
        if not obj.performance_gate_fingerprint:
            errors.append("performance_gate_fingerprint_empty")
        if obj.mirror_state != "coherent":
            errors.append(f"mirror_state_not_coherent:{obj.mirror_state}")
        if obj.kernel_readiness_state != "ready":
            errors.append(f"kernel_readiness_not_ready:{obj.kernel_readiness_state}")
        if obj.performance_gate_state != "passed":
            errors.append(f"performance_gates_not_passed:{obj.performance_gate_state}")
    forbidden_true_fields = (
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
        "formal_ir_committed",
    )
    for field_name in forbidden_true_fields:
        if bool(getattr(obj, field_name)):
            errors.append(f"forbidden_monitor_field_true:{field_name}")
    if int(getattr(obj, "tds_artifact_writes", 0)) != 0:
        errors.append(f"tds_artifact_writes_nonzero:{obj.tds_artifact_writes}")
    icon_report = validate_csv_interpole_monitor_icon_registry()
    payload_status = "bounded" if payload_bytes <= max(1, int(payload_byte_limit)) else "oversized"
    display_contract_status = "valid" if not [e for e in errors if e.startswith("display_contract_") or e.startswith("required_")] else "blocked"
    if not icon_report.ok:
        errors.extend(icon_report.errors)
    return _monitor_replay_report(
        csv_id=obj.csv_id,
        status="snapshot_valid" if not errors else "snapshot_blocked",
        source_snapshot_fingerprint=snapshot_fingerprint,
        reconstructed_snapshot_fingerprint=snapshot_fingerprint,
        source_payload_bytes=payload_bytes,
        reconstructed_payload_bytes=payload_bytes,
        compared_fields=CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS,
        matching_fields=CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS if not errors else (),
        mismatched_fields=(),
        icon_registry_status=icon_report.status,
        display_contract_status=display_contract_status,
        payload_status=payload_status,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def replay_csv_interpole_browser_monitor_snapshot(
    directory: TDSDirectory,
    csv_id: str,
    source_snapshot: CSVInterpoleBrowserMonitorSnapshot | Mapping[str, Any],
    *,
    chunk_size: int | None = 7,
    max_signal_lanes: int = 12,
    max_event_rows: int = 12,
    payload_byte_limit: int = CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT,
) -> CSVInterpoleMonitorReplayReport:
    """Reconstruct a monitor snapshot and compare it with a supplied snapshot.

    This is the v3.4.10 replay contract.  It proves that Browser state can be
    recreated from committed evidence and that the supplied display payload did
    not drift.  It never commits artifacts or writes monitor state.
    """
    before_keys = set(getattr(directory, "_entries", {}).keys()) if hasattr(directory, "_entries") else set()
    try:
        safe_id = validate_csv_id(csv_id)
    except Exception as exc:
        return _monitor_replay_report(
            csv_id=str(csv_id),
            status="replay_blocked",
            icon_registry_status="blocked",
            display_contract_status="blocked",
            payload_status="invalid",
            errors=(f"csv_id_unsafe:{type(exc).__name__}:{exc}",),
        )
    source_validation = validate_csv_interpole_browser_monitor_snapshot(source_snapshot, payload_byte_limit=payload_byte_limit)
    if not source_validation.ok:
        return _monitor_replay_report(
            csv_id=safe_id,
            status="replay_blocked",
            source_snapshot_fingerprint=source_validation.source_snapshot_fingerprint,
            reconstructed_snapshot_fingerprint="",
            source_payload_bytes=source_validation.source_payload_bytes,
            reconstructed_payload_bytes=0,
            compared_fields=source_validation.compared_fields,
            icon_registry_status=source_validation.icon_registry_status,
            display_contract_status=source_validation.display_contract_status,
            payload_status=source_validation.payload_status,
            errors=tuple(dict.fromkeys(("source_snapshot_invalid",) + source_validation.errors)),
            warnings=source_validation.warnings,
        )
    try:
        source_obj = source_snapshot if isinstance(source_snapshot, CSVInterpoleBrowserMonitorSnapshot) else CSVInterpoleBrowserMonitorSnapshot.from_mapping(source_snapshot)
        reconstructed = prepare_csv_interpole_browser_monitor_snapshot(
            directory,
            safe_id,
            chunk_size=chunk_size,
            max_signal_lanes=max_signal_lanes,
            max_event_rows=max_event_rows,
        )
        reconstructed_validation = validate_csv_interpole_browser_monitor_snapshot(reconstructed, payload_byte_limit=payload_byte_limit)
    except Exception as exc:
        return _monitor_replay_report(
            csv_id=safe_id,
            status="replay_blocked",
            source_snapshot_fingerprint=source_validation.source_snapshot_fingerprint,
            reconstructed_snapshot_fingerprint="",
            source_payload_bytes=source_validation.source_payload_bytes,
            reconstructed_payload_bytes=0,
            compared_fields=CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS,
            icon_registry_status=source_validation.icon_registry_status,
            display_contract_status="blocked",
            payload_status="invalid",
            errors=(f"replay_reconstruction_failed:{type(exc).__name__}:{exc}",),
        )
    compared_fields = CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS
    source_dict = source_obj.to_dict()
    reconstructed_dict = reconstructed.to_dict()
    matching: list[str] = []
    mismatched: list[str] = []
    for field_name in compared_fields:
        if source_dict.get(field_name) == reconstructed_dict.get(field_name):
            matching.append(field_name)
        else:
            mismatched.append(field_name)
    for count_name in ("card_count", "ring_node_count", "gate_row_count", "signal_lane_count", "event_row_count"):
        if source_dict.get(count_name) == reconstructed_dict.get(count_name):
            matching.append(count_name)
        else:
            mismatched.append(count_name)
    source_fingerprint = source_validation.source_snapshot_fingerprint
    reconstructed_fingerprint = reconstructed_validation.source_snapshot_fingerprint
    if source_fingerprint != reconstructed_fingerprint and "display_projection" not in mismatched:
        mismatched.append("display_projection")
    errors: list[str] = []
    if not reconstructed_validation.ok:
        errors.extend(f"reconstructed:{error}" for error in reconstructed_validation.errors)
    errors.extend(f"snapshot_mismatch:{name}" for name in mismatched)
    after_keys = set(getattr(directory, "_entries", {}).keys()) if hasattr(directory, "_entries") else before_keys
    if after_keys != before_keys:
        errors.append("replay_wrote_tds_artifacts")
    payload_status = "bounded" if max(source_validation.source_payload_bytes, reconstructed_validation.source_payload_bytes) <= max(1, int(payload_byte_limit)) else "oversized"
    return _monitor_replay_report(
        csv_id=safe_id,
        status="replay_valid" if not errors else "replay_blocked",
        source_snapshot_fingerprint=source_validation.source_snapshot_fingerprint,
        reconstructed_snapshot_fingerprint=reconstructed_validation.source_snapshot_fingerprint,
        source_payload_bytes=source_validation.source_payload_bytes,
        reconstructed_payload_bytes=reconstructed_validation.source_payload_bytes,
        compared_fields=compared_fields + ("card_count", "ring_node_count", "gate_row_count", "signal_lane_count", "event_row_count"),
        matching_fields=tuple(matching),
        mismatched_fields=tuple(mismatched),
        icon_registry_status=reconstructed_validation.icon_registry_status,
        display_contract_status="valid" if not errors else "blocked",
        payload_status=payload_status,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(source_validation.warnings + reconstructed_validation.warnings)),
    )


def csv_interpole_browser_monitor_replay_summary(report: CSVInterpoleMonitorReplayReport) -> dict[str, Any]:
    """Return a compact summary for replay/hardening results."""
    return report.to_dict()


def csv_interpole_monitor_delivery_manifest(
    *,
    release_version: str = "3.4.10",
    package_name: str = "staqtapp_tds_v3_4_10_csv_interpole_monitor_replay_hardening.zip",
    state_packet_name: str = "TDS_v3_4_10_CSV_State_Packet.txt",
    sha256sums_name: str = "SHA256SUMS.txt",
    validation_name: str = "RELEASE_VALIDATION.txt",
) -> CSVInterpoleMonitorDeliveryManifest:
    required = (package_name, state_packet_name, sha256sums_name, validation_name)
    errors: list[str] = []
    if release_version != "3.4.10":
        errors.append(f"release_version_mismatch:{release_version}")
    for name in required:
        if not str(name):
            errors.append("delivery_member_name_empty")
    return CSVInterpoleMonitorDeliveryManifest(
        release_version=release_version,
        package_name=package_name,
        state_packet_name=state_packet_name,
        sha256sums_name=sha256sums_name,
        validation_name=validation_name,
        required_member_names=required,
        errors=tuple(errors),
    )


def prepare_csv_interpole_browser_monitor_snapshot(
    directory: TDSDirectory,
    csv_id: str,
    *,
    chunk_size: int | None = 7,
    max_signal_lanes: int = 12,
    max_event_rows: int = 12,
) -> CSVInterpoleBrowserMonitorSnapshot:
    """Build a read-only Browser monitor snapshot for one CSV artifact family.

    The function validates all source reports freshly before creating display
    data.  It never calls commit APIs and must remain safe to run from Browser
    status refresh paths.
    """
    try:
        safe_id = validate_csv_id(csv_id)
    except Exception as exc:
        return _invalid_monitor_snapshot(str(csv_id), f"csv_id_unsafe:{type(exc).__name__}:{exc}")

    try:
        stored_ring = load_csv_interpole_timeline_ring_report(directory, safe_id)
        stored_vector = load_csv_interpole_determinant_vector_report(directory, safe_id)
        stored_readiness = load_csv_kernel_readiness_contract_report(directory, safe_id)
        stored_scan = load_csv_native_scan_kernel_prototype_report(directory, safe_id)
        stored_anchor = load_csv_native_row_anchor_kernel_report(directory, safe_id)
        stored_performance = load_csv_kernel_performance_gate_report(directory, safe_id)
    except Exception as exc:
        return _invalid_monitor_snapshot(safe_id, f"csv_interpole_monitor_sources_unreadable:{type(exc).__name__}:{exc}")

    ring_validation = validate_csv_interpole_timeline_ring(directory, safe_id, chunk_size=chunk_size)
    vector_validation = validate_csv_interpole_determinant_vector(directory, safe_id, chunk_size=chunk_size)
    readiness_validation = validate_csv_kernel_readiness_contract(directory, safe_id, chunk_size=chunk_size)
    scan_validation = validate_csv_native_scan_kernel_prototype(directory, safe_id, chunk_size=chunk_size)
    anchor_validation = validate_csv_native_row_anchor_kernel(directory, safe_id, chunk_size=chunk_size)
    performance_validation = validate_csv_kernel_performance_gate_report(directory, safe_id)

    errors: list[str] = []
    warnings: list[str] = []
    for label, report in (
        ("timeline_ring", ring_validation),
        ("determinant_vector", vector_validation),
        ("kernel_readiness", readiness_validation),
        ("native_scan", scan_validation),
        ("native_row_anchor", anchor_validation),
        ("performance_gates", performance_validation),
    ):
        errors.extend(f"{label}:{error}" for error in getattr(report, "errors", ()) or ())
        warnings.extend(f"{label}:{warning}" for warning in getattr(report, "warnings", ()) or ())
    for label, report, committed_states in (
        ("stored_timeline_ring", stored_ring, {"ring_committed", "valid"}),
        ("stored_determinant_vector", stored_vector, {"determinants_committed", "valid"}),
        ("stored_kernel_readiness", stored_readiness, {"kernel_contract_committed", "valid"}),
        ("stored_native_scan", stored_scan, {"native_scan_committed", "valid"}),
        ("stored_native_row_anchor", stored_anchor, {"native_row_anchor_committed", "valid"}),
        ("stored_performance_gates", stored_performance, {"performance_gates_committed", "valid"}),
    ):
        if str(getattr(report, "status", "")) not in committed_states:
            errors.append(f"{label}_not_committed:{getattr(report, 'status', 'unknown')}")

    ring_state = _ring_state(ring_validation)
    mirror_state = _mirror_state(ring_validation)
    kernel_state = "ready" if getattr(readiness_validation, "ok", False) else "blocked"
    performance_state = "passed" if getattr(performance_validation, "ok", False) else "failed"
    status = "monitor_ready" if not errors and ring_state in {"stable", "watch"} and mirror_state == "coherent" and kernel_state == "ready" and performance_state == "passed" else "blocked"

    ring = getattr(ring_validation, "ring", None)
    mirror = getattr(ring_validation, "mirror_delta", None)
    nodes = tuple(
        CSVInterpoleMonitorRingNode(
            node_index=int(node.node_index),
            stage_name=str(node.stage_name),
            status=str(node.status),
            direction=str(node.direction),
            feedback_hint=str(node.feedback_hint),
            signal_count=int(node.signal_count),
            magnitude_average=float(node.magnitude_average),
            confidence_average=float(node.confidence_average),
            drift_pressure=float(node.drift_pressure),
            ir_readiness_pressure=float(node.ir_readiness_pressure),
            node_fingerprint_suffix=_suffix(node.node_fingerprint),
        )
        for node in (getattr(ring, "nodes", ()) or ())
    )

    signals = tuple(getattr(getattr(vector_validation, "vector", None), "signals", ()) or ())
    sorted_signals = sorted(
        signals,
        key=lambda signal: (float(getattr(signal, "weighted_magnitude", 0.0)), float(getattr(signal, "confidence", 0.0))),
        reverse=True,
    )[: max(0, int(max_signal_lanes))]
    lanes = tuple(
        CSVInterpoleMonitorSignalLane(
            lane_name=str(signal.signal_name),
            icon_name=_signal_icon(str(signal.signal_name)),
            source_stage_name=str(signal.source_stage_name),
            direction=str(signal.direction),
            magnitude=float(signal.magnitude),
            confidence=float(signal.confidence),
            weighted_magnitude=float(signal.weighted_magnitude),
            fingerprint_suffix=_suffix(str(signal.source_signature_sha256)),
            pressure_label=_pressure_label(signal),
        )
        for signal in sorted_signals
    )

    cards = (
        CSVInterpoleMonitorStatusCard(
            "Ring State",
            "csv-timeline-ring",
            ring_state,
            f"{getattr(ring, 'node_count', 0)} nodes",
            f"stability {float(getattr(ring, 'ring_stability_score', 0.0)):.2f} · IR readiness {float(getattr(ring, 'ring_ir_readiness_score', 0.0)):.2f}",
            _severity(ring_state in {"stable", "watch"}, watch=ring_state == "watch"),
        ),
        CSVInterpoleMonitorStatusCard(
            "Mirror Feedback",
            "csv-mirror-delta",
            mirror_state,
            "coherent" if mirror_state == "coherent" else "blocked",
            " · ".join(str(v) for v in getattr(ring_validation, "discrete_feedback", ()) or ()) or "no feedback",
            _severity(mirror_state == "coherent"),
        ),
        CSVInterpoleMonitorStatusCard(
            "Kernel Readiness",
            "csv-readiness-gate",
            kernel_state,
            str(getattr(readiness_validation, "status", "blocked")),
            f"{getattr(readiness_validation, 'ready_count', 0)}/{getattr(readiness_validation, 'required_count', 0)} requirements ready",
            _severity(kernel_state == "ready"),
        ),
        CSVInterpoleMonitorStatusCard(
            "Performance Gates",
            "csv-performance-gate",
            performance_state,
            str(getattr(performance_validation, "status", "failed")),
            f"{getattr(performance_validation, 'passed_count', 0)}/{getattr(performance_validation, 'required_count', 0)} gates passed",
            _severity(performance_state == "passed"),
        ),
        CSVInterpoleMonitorStatusCard(
            "Native Scan Parity",
            "csv-parity-pair",
            str(getattr(scan_validation, "scan_parity_status", getattr(scan_validation, "status", "blocked"))),
            "native/reference",
            f"scan {_suffix(str(getattr(scan_validation, 'scan_fingerprint', '')))} · reference {_suffix(str(getattr(scan_validation, 'reference_scan_fingerprint', '')))}",
            _severity(getattr(scan_validation, "ok", False)),
        ),
        CSVInterpoleMonitorStatusCard(
            "Row Anchor Parity",
            "csv-evidence-anchor",
            str(getattr(anchor_validation, "row_anchor_parity_status", getattr(anchor_validation, "status", "blocked"))),
            "offset/anchor",
            f"anchor {_suffix(str(getattr(anchor_validation, 'anchor_fingerprint', '')))}",
            _severity(getattr(anchor_validation, "ok", False)),
        ),
        CSVInterpoleMonitorStatusCard(
            "Fallback Bridge",
            "csv-fallback-bridge",
            "ready" if bool(getattr(performance_validation, "python_reference_fallback_available", False)) else "blocked",
            "Python reference",
            "fallback is available and native path remains optional",
            _severity(bool(getattr(performance_validation, "python_reference_fallback_available", False))),
        ),
        CSVInterpoleMonitorStatusCard(
            "Semantic Boundary",
            "csv-semantic-boundary",
            "guarded",
            "IR deferred",
            "no schema, type, entity, row, cell, or formal IR conclusion committed",
            "ok",
        ),
    )

    gate_rows = tuple(
        CSVInterpoleMonitorGateRow(
            gate_name=str(gate.gate_name),
            icon_name="csv-performance-gate" if str(gate.category).startswith("performance") else "csv-readiness-gate",
            status=str(gate.status),
            detail=f"{gate.metric_name}={gate.metric_value}" if gate.metric_name else str(gate.category),
            fingerprint_suffix=_suffix(next(iter(dict(gate.evidence_hashes).values()), "")),
        )
        for gate in tuple(getattr(performance_validation, "gates", ()) or ())[:10]
    )

    events = [
        CSVInterpoleMonitorEventRow(0, "timeline_ring", ring_state, f"ring {_suffix(str(getattr(ring_validation, 'ring_fingerprint', '')))}", _suffix(str(getattr(ring_validation, "ring_fingerprint", "")))),
        CSVInterpoleMonitorEventRow(1, "mirror_feedback", mirror_state, " · ".join(str(v) for v in getattr(ring_validation, "discrete_feedback", ()) or ()), _suffix(str(getattr(ring_validation, "mirror_fingerprint", "")))),
        CSVInterpoleMonitorEventRow(2, "kernel_readiness", kernel_state, f"contract {_suffix(str(getattr(readiness_validation, 'contract_fingerprint', '')))}", _suffix(str(getattr(readiness_validation, "contract_fingerprint", "")))),
        CSVInterpoleMonitorEventRow(3, "performance_gates", performance_state, f"gate {_suffix(str(getattr(performance_validation, 'performance_gate_fingerprint', '')))}", _suffix(str(getattr(performance_validation, "performance_gate_fingerprint", "")))),
        CSVInterpoleMonitorEventRow(4, "semantic_boundary", "guarded", "formal IR remains deferred", ""),
    ]
    if errors:
        events.append(CSVInterpoleMonitorEventRow(5, "monitor_errors", "blocked", errors[0], ""))
    event_rows = tuple(events[: max(0, int(max_event_rows))])

    return CSVInterpoleBrowserMonitorSnapshot(
        csv_id=safe_id,
        status=status,
        monitor_version=CSV_INTERPOLE_BROWSER_MONITOR_VERSION,
        mode="browser_monitor_snapshot",
        ring_state=ring_state,
        mirror_state=mirror_state,
        kernel_readiness_state=kernel_state,
        performance_gate_state=performance_state,
        ring_fingerprint=str(getattr(ring_validation, "ring_fingerprint", "")),
        mirror_fingerprint=str(getattr(ring_validation, "mirror_fingerprint", "")),
        source_vector_fingerprint=str(getattr(ring_validation, "source_vector_fingerprint", "")),
        kernel_contract_fingerprint=str(getattr(readiness_validation, "contract_fingerprint", "")),
        performance_gate_fingerprint=str(getattr(performance_validation, "performance_gate_fingerprint", "")),
        ring_stability_score=float(getattr(ring, "ring_stability_score", 0.0)),
        ring_ir_readiness_score=float(getattr(ring, "ring_ir_readiness_score", 0.0)),
        inverse_check_passed=bool(getattr(mirror, "inverse_check_passed", False)),
        discrete_feedback=tuple(str(v) for v in getattr(ring_validation, "discrete_feedback", ()) or ()),
        cards=cards,
        ring_nodes=nodes,
        gate_rows=gate_rows,
        signal_lanes=lanes,
        event_rows=event_rows,
        icon_names=CSV_INTERPOLE_MONITOR_ICON_NAMES,
        warnings=tuple(dict.fromkeys(warnings)),
        errors=tuple(dict.fromkeys(errors)),
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


def csv_interpole_browser_monitor_summary(snapshot: CSVInterpoleBrowserMonitorSnapshot) -> dict[str, Any]:
    """Return a compact API/UI summary for the Browser CSV Interpole monitor."""
    return {
        "csv_id": snapshot.csv_id,
        "status": snapshot.status,
        "ok": snapshot.ok,
        "monitor_version": snapshot.monitor_version,
        "mode": snapshot.mode,
        "ring_state": snapshot.ring_state,
        "mirror_state": snapshot.mirror_state,
        "kernel_readiness_state": snapshot.kernel_readiness_state,
        "performance_gate_state": snapshot.performance_gate_state,
        "ring_fingerprint": snapshot.ring_fingerprint,
        "mirror_fingerprint": snapshot.mirror_fingerprint,
        "source_vector_fingerprint": snapshot.source_vector_fingerprint,
        "kernel_contract_fingerprint": snapshot.kernel_contract_fingerprint,
        "performance_gate_fingerprint": snapshot.performance_gate_fingerprint,
        "ring_stability_score": snapshot.ring_stability_score,
        "ring_ir_readiness_score": snapshot.ring_ir_readiness_score,
        "inverse_check_passed": snapshot.inverse_check_passed,
        "discrete_feedback": list(snapshot.discrete_feedback),
        "card_count": len(snapshot.cards),
        "ring_node_count": len(snapshot.ring_nodes),
        "gate_row_count": len(snapshot.gate_rows),
        "signal_lane_count": len(snapshot.signal_lanes),
        "event_row_count": len(snapshot.event_rows),
        "icon_names": list(snapshot.icon_names),
        "cards": [card.to_dict() for card in snapshot.cards],
        "ring_nodes": [node.to_dict() for node in snapshot.ring_nodes],
        "gate_rows": [gate.to_dict() for gate in snapshot.gate_rows],
        "signal_lanes": [lane.to_dict() for lane in snapshot.signal_lanes],
        "event_rows": [event.to_dict() for event in snapshot.event_rows],
        "tds_artifact_writes": snapshot.tds_artifact_writes,
        "native_storage_writes": snapshot.native_storage_writes,
        "native_storage_hot_path_touched": snapshot.native_storage_hot_path_touched,
        "native_storage_locks_controlled": snapshot.native_storage_locks_controlled,
        "native_c_storage_engine_changed": snapshot.native_c_storage_engine_changed,
        "interpole_mutation": snapshot.interpole_mutation,
        "per_row_writes": snapshot.per_row_writes,
        "per_cell_writes": snapshot.per_cell_writes,
        "semantic_reasoning": snapshot.semantic_reasoning,
        "semantic_conclusions": snapshot.semantic_conclusions,
        "schema_inference": snapshot.schema_inference,
        "type_inference": snapshot.type_inference,
        "entity_inference": snapshot.entity_inference,
        "formal_ir_committed": snapshot.formal_ir_committed,
        "warnings": list(snapshot.warnings),
        "errors": list(snapshot.errors),
        "display_contract_keys": list(CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS),
        "display_contract_fingerprint": csv_interpole_browser_monitor_display_contract_fingerprint(),
        "snapshot_fingerprint": csv_interpole_browser_monitor_snapshot_fingerprint(snapshot),
        "payload_bytes": _snapshot_payload_bytes(snapshot),
        "payload_byte_limit": CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT,
    }

"""Non-GUI Driver Studio certification quick-test model.

v3.0.9 adds a Class A readiness layer for the future PyQt5 Driver Studio.
It does not render a UI and it does not execute drivers. Instead, it models the
same gated workflow the Studio must enforce: learn, validate, compile, audit,
load, and registry-sign only after each previous gate passes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .audit import audit_vm_contract
from .bytecode import BytecodePackage, compile_tddl
from .evidence import DriverEvidenceBundle, EvidenceBundleExporter, EvidenceIntegrityStatus
from .manifest import DriverManifest
from .registry import DriverRegistry, DriverState
from .signature import SignaturePolicy, SignatureVerdict, sign_payload
from .tddl import TDDLValidationError, instruction_specs, parse_tddl
from .vm import DriverVMSkeleton, VMState


class StudioGate(str, Enum):
    """Ordered Driver Studio certification gates."""

    LEARN = "learn"
    SYNTAX = "syntax"
    CAPABILITIES = "capabilities"
    BYTECODE = "bytecode"
    VM_AUDIT = "vm_audit"
    VM_LOAD = "vm_load"
    REGISTRY_POLICY = "registry_policy"
    SIGNING = "signing"
    COMPLETE = "complete"


_STUDIO_GATE_ORDER: tuple[StudioGate, ...] = (
    StudioGate.LEARN,
    StudioGate.SYNTAX,
    StudioGate.CAPABILITIES,
    StudioGate.BYTECODE,
    StudioGate.VM_AUDIT,
    StudioGate.VM_LOAD,
    StudioGate.REGISTRY_POLICY,
    StudioGate.SIGNING,
    StudioGate.COMPLETE,
)


@dataclass(frozen=True, slots=True)
class StudioGateResult:
    gate: StudioGate
    passed: bool
    detail: str


@dataclass(slots=True)
class DriverStudioSession:
    """Minimal gated certification session for future Driver Studio UX tests."""

    completed: list[StudioGate] = field(default_factory=list)

    def pass_gate(self, gate: StudioGate) -> None:
        expected = _STUDIO_GATE_ORDER[len(self.completed)]
        if gate is not expected:
            raise RuntimeError(f"cannot pass {gate.value} before {expected.value}")
        self.completed.append(gate)

    @property
    def next_gate(self) -> StudioGate:
        if len(self.completed) >= len(_STUDIO_GATE_ORDER):
            return StudioGate.COMPLETE
        return _STUDIO_GATE_ORDER[len(self.completed)]


@dataclass(frozen=True, slots=True)
class DriverStudioQuickTestReport:
    """Immutable report emitted by the Class A Studio quick test."""

    ok: bool
    driver_id: str
    driver_class: str
    package_hash: str
    registry_state: DriverState
    gate_results: tuple[StudioGateResult, ...]

    @property
    def passed_gates(self) -> tuple[str, ...]:
        return tuple(result.gate.value for result in self.gate_results if result.passed)


def studio_instruction_reference() -> Mapping[str, Mapping[str, object]]:
    """Return compact instruction reference data for the future Learn panel."""

    reference: dict[str, Mapping[str, object]] = {}
    for name, spec in instruction_specs().items():
        reference[name] = {
            "required": tuple(sorted(spec.required)),
            "optional": tuple(sorted(spec.optional)),
            "allowed_operands": tuple(sorted(spec.allowed)),
            "allowed_values": {key: tuple(sorted(values)) for key, values in spec.allowed_values.items()},
        }
    return reference


def run_studio_quick_test(
    source: str,
    *,
    signer: str = "studio-admin",
    secret: bytes = b"local-driver-studio-secret",
) -> DriverStudioQuickTestReport:
    """Run the non-GUI Driver Studio Class A certification path.

    The path deliberately mirrors the future PyQt5 Studio workflow. Each gate
    must pass before the next is attempted. Any validation failure propagates so
    tests and the eventual UI can display the precise fail-closed reason.
    """

    session = DriverStudioSession()
    results: list[StudioGateResult] = []

    reference = studio_instruction_reference()
    if not reference:
        raise RuntimeError("instruction reference is empty")
    session.pass_gate(StudioGate.LEARN)
    results.append(StudioGateResult(StudioGate.LEARN, True, "instruction reference available"))

    program = parse_tddl(source)
    session.pass_gate(StudioGate.SYNTAX)
    results.append(StudioGateResult(StudioGate.SYNTAX, True, f"parsed {len(program.instructions)} instructions"))

    if not program.capabilities:
        raise TDDLValidationError("driver must declare capabilities before Studio progression")
    session.pass_gate(StudioGate.CAPABILITIES)
    results.append(StudioGateResult(StudioGate.CAPABILITIES, True, f"{len(program.capabilities)} capabilities declared"))

    package = compile_tddl(program)
    session.pass_gate(StudioGate.BYTECODE)
    results.append(StudioGateResult(StudioGate.BYTECODE, True, f"compiled package {package.package_hash[:12]}"))

    audit_vm_contract(package)
    session.pass_gate(StudioGate.VM_AUDIT)
    results.append(StudioGateResult(StudioGate.VM_AUDIT, True, "VM contract audit passed"))

    vm = DriverVMSkeleton()
    loaded = vm.load(package)
    if vm.state is not VMState.LOADED:
        raise RuntimeError("VM skeleton did not load validated package")
    session.pass_gate(StudioGate.VM_LOAD)
    results.append(StudioGateResult(StudioGate.VM_LOAD, True, f"loaded {loaded.instruction_count} instructions"))

    manifest = _manifest_from_package(package)
    policy = SignaturePolicy()
    policy.approve_signer(signer, secret)
    registry = DriverRegistry(signature_policy=policy)
    test_report_hash = _test_report_hash(package, results)
    registry.add_candidate(manifest, test_report_hash=test_report_hash)
    registry.approve(manifest.driver_id)
    session.pass_gate(StudioGate.REGISTRY_POLICY)
    results.append(StudioGateResult(StudioGate.REGISTRY_POLICY, True, "candidate approved with test report"))

    signature = sign_payload(manifest.canonical_payload(), signer=signer, secret=secret)
    if policy.evaluate(manifest.canonical_payload(), signature) is not SignatureVerdict.ACCEPT:
        raise RuntimeError("generated Studio signature was not accepted")
    registry.attach_signature(manifest.driver_id, signature)
    record = registry.activate(manifest.driver_id)
    session.pass_gate(StudioGate.SIGNING)
    results.append(StudioGateResult(StudioGate.SIGNING, True, "driver signed and activated"))

    session.pass_gate(StudioGate.COMPLETE)
    results.append(StudioGateResult(StudioGate.COMPLETE, True, "Studio quick test complete"))

    return DriverStudioQuickTestReport(
        ok=True,
        driver_id=manifest.driver_id,
        driver_class=manifest.kind,
        package_hash=package.package_hash,
        registry_state=record.state,
        gate_results=tuple(results),
    )


def _manifest_from_package(package: BytecodePackage) -> DriverManifest:
    return DriverManifest.from_mapping(
        {
            "driver_id": str(package.header["driver_id"]),
            "version": int(package.header["driver_version"]),
            "kind": str(package.manifest["kind"]),
            "description": str(package.manifest.get("description", "")),
            "safety": str(package.manifest.get("safety", "bounded")),
            "capabilities": tuple(package.capabilities),
            "adapters": tuple(package.adapters),
            "generation": 0,
        }
    )


def _test_report_hash(package: BytecodePackage, results: list[StudioGateResult]) -> str:
    h = hashlib.sha256()
    h.update(package.package_hash.encode("utf-8"))
    for result in results:
        h.update(result.gate.value.encode("utf-8"))
        h.update(b"\0")
        h.update(str(result.passed).encode("utf-8"))
        h.update(b"\0")
        h.update(result.detail.encode("utf-8"))
    return h.hexdigest()


class StudioPanelKind(str, Enum):
    """Stable panel identifiers for the future PyQt5 Driver Studio."""

    DRIVER_QUEUE = "driver_queue"
    EVIDENCE_BUNDLE = "evidence_bundle"
    AUDIT_TRAIL = "audit_trail"
    EVIDENCE_TIMELINE = "evidence_timeline"
    FIXTURE_REPLAY = "fixture_replay"
    RISK_CARD = "risk_card"
    REGISTRY_STATE = "registry_state"
    EXPORT_INTEGRITY = "export_integrity"
    EXPORT_AUDIT_CONSOLE = "export_audit_console"
    MANUAL_DRIVER_BUILDER = "manual_driver_builder"
    EVENT_CONSOLE = "event_console"


class StudioPanelStatus(str, Enum):
    """Read-only rendering status for one Studio panel."""

    READY = "ready"
    PARTIAL = "partial"
    EMPTY = "empty"
    INTEGRITY_MISMATCH = "integrity_mismatched"
    INPUT_REJECTED = "input_rejected"


class StudioConsoleStatus(str, Enum):
    """Top-level read-only console status derived from an evidence bundle."""

    READY = "ready"
    PARTIAL = "partial"
    EMPTY = "empty"
    INTEGRITY_MISMATCH = "integrity_mismatched"
    INPUT_REJECTED = "input_rejected"


@dataclass(frozen=True, slots=True)
class DriverStudioQueueItem:
    """One driver row for the Studio review queue panel."""

    driver_id: str | None
    driver_version: int | None
    decision_status: str
    risk_level: str
    final_action: str
    registry_state_before: str | None = None
    registry_state_after: str | None = None
    package_hash: str | None = None
    regression_report_hash: str | None = None
    review_hash: str | None = None
    selected: bool = False

    @property
    def needs_attention(self) -> bool:
        return self.decision_status not in {"approval_ready", "registry_approved"}


@dataclass(frozen=True, slots=True)
class DriverStudioRiskCard:
    """Human-readable, read-only driver risk summary for Studio inspectors."""

    driver_id: str | None
    risk_level: str
    decision_status: str
    summary: str
    reasons: tuple[str, ...]
    blocked_authority: tuple[str, ...]
    fault_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverStudioEventRow:
    """Compact event-console row derived from the audit trail."""

    event_id: str
    event_type: str
    actor_id: str
    action: str | None
    driver_id: str | None
    timestamp: str
    reason: str


@dataclass(frozen=True, slots=True)
class DriverStudioPanelSnapshot:
    """One immutable panel payload for a PyQt5 view model to render."""

    kind: StudioPanelKind
    status: StudioPanelStatus
    title: str
    summary: str
    rows: tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverStudioConsoleSnapshot:
    """Complete read-only evidence-console snapshot.

    This object is intentionally GUI-neutral. A PyQt5 Studio can map the stable
    panel payloads into widgets, tables, cards, and timelines without receiving
    approval, signing, activation, VM execution, storage, or private-key power.
    """

    ok: bool
    status: StudioConsoleStatus
    reason: str
    bundle_id: str | None
    bundle_hash: str | None
    integrity_status: str
    selected_driver_id: str | None
    console_hash: str
    panels: tuple[DriverStudioPanelSnapshot, ...]
    queue: tuple[DriverStudioQueueItem, ...]
    risk_cards: tuple[DriverStudioRiskCard, ...]
    event_console: tuple[DriverStudioEventRow, ...]
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    def panel(self, kind: StudioPanelKind | str) -> DriverStudioPanelSnapshot:
        wanted = kind if isinstance(kind, StudioPanelKind) else StudioPanelKind(str(kind))
        for panel in self.panels:
            if panel.kind is wanted:
                return panel
        raise KeyError(wanted.value)

    def to_dict(self) -> Mapping[str, Any]:
        return _console_snapshot_map(self)

    def to_json(self) -> str:
        return _studio_canonical_json(self.to_dict())


class DriverStudioReadOnlyConsole:
    """Read-only evidence-console model for the future PyQt5 Driver Studio.

    The console consumes evidence bundle exports and emits panel snapshots. It
    never approves, rejects, signs, activates, edits TDDL, edits bytecode, runs
    the Driver VM, writes storage, mutates the Registry, or stores private keys.
    """

    def __init__(self, *, exporter: EvidenceBundleExporter | None = None) -> None:
        self.exporter = exporter or EvidenceBundleExporter()

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the read-only Studio authority boundary."""

        return {
            "load_evidence_bundle": True,
            "render_driver_queue": True,
            "render_evidence_bundle": True,
            "render_audit_trail": True,
            "render_evidence_timeline": True,
            "render_fixture_replay": True,
            "render_risk_cards": True,
            "render_risk_intelligence_cards": True,
            "render_registry_state": True,
            "render_manual_driver_builder": True,
            "render_export_audit_console": True,
            "prepare_export_audit_manifest": True,
            "verify_export_integrity": True,
            "record_public_signature_metadata": True,
            "preview_manual_driver_proposals": True,
            "route_manual_driver_proposals_to_foundry": True,
            "include_private_keys": False,
            "approve_driver": False,
            "reject_driver": False,
            "call_registry_approve": False,
            "sign_driver": False,
            "attach_signature": False,
            "activate_driver": False,
            "edit_tddl": False,
            "edit_bytecode": False,
            "run_driver_vm": False,
            "write_storage": False,
            "execute_python": False,
            "mutate_registry": False,
            "bypass_policy": False,
        }

    def open_bundle(
        self,
        bundle: DriverEvidenceBundle | Mapping[str, Any] | str,
        *,
        selected_driver_id: str | None = None,
    ) -> DriverStudioConsoleSnapshot:
        """Load an evidence bundle into read-only Studio panel snapshots."""

        payload = _bundle_payload_for_studio(bundle)
        integrity = self.exporter.verify_bundle(bundle)
        status = _console_status(payload, integrity)
        records = tuple(_as_mapping(record) for record in payload.get("records", ()))
        events = tuple(_as_mapping(event) for event in _as_mapping(payload.get("audit_trail", {})).get("events", ()))
        selected = _resolve_selected_driver(records, selected_driver_id)
        matrix = self.capability_matrix()
        queue = tuple(_queue_item(record, selected) for record in records)
        risk_cards = tuple(_risk_card(record, matrix) for record in records)
        event_rows = tuple(_event_row(event) for event in events)
        panels = (
            _queue_panel(queue),
            _evidence_bundle_panel(payload, status),
            _audit_trail_panel(payload, events),
            _evidence_timeline_panel(payload, records, events, selected),
            _fixture_replay_panel(records, selected),
            _risk_card_panel(risk_cards, selected),
            _registry_state_panel(records, events, selected),
            _export_integrity_panel(payload, integrity),
            _export_audit_console_panel(payload, records, events, selected),
            _manual_driver_builder_panel(selected),
            _event_console_panel(event_rows),
        )
        base = {
            "ok": bool(payload.get("ok")) and integrity is EvidenceIntegrityStatus.VERIFIED,
            "status": status.value,
            "reason": _console_reason(payload, integrity, status),
            "bundle_id": _optional_text(payload.get("bundle_id")),
            "bundle_hash": _optional_text(payload.get("bundle_hash")),
            "integrity_status": integrity.value,
            "selected_driver_id": selected,
            "panels": [_panel_map(panel) for panel in panels],
            "queue": [_queue_map(item) for item in queue],
            "risk_cards": [_risk_card_map(card) for card in risk_cards],
            "event_console": [_event_row_map(row) for row in event_rows],
            "capability_matrix": matrix,
        }
        console_hash = _studio_hash_payload(base)
        return DriverStudioConsoleSnapshot(
            ok=bool(base["ok"]),
            status=status,
            reason=str(base["reason"]),
            bundle_id=base["bundle_id"],
            bundle_hash=base["bundle_hash"],
            integrity_status=integrity.value,
            selected_driver_id=selected,
            console_hash=console_hash,
            panels=panels,
            queue=queue,
            risk_cards=risk_cards,
            event_console=event_rows,
            capability_matrix=matrix,
        )

    # Short aliases for service/UI code.
    load_bundle = open_bundle
    render = open_bundle


def studio_readonly_capability_matrix() -> Mapping[str, bool]:
    """Convenience function for displaying Studio read-only authority."""

    return DriverStudioReadOnlyConsole().capability_matrix()


def _bundle_payload_for_studio(bundle: DriverEvidenceBundle | Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(bundle, DriverEvidenceBundle):
        return bundle.to_dict()
    if isinstance(bundle, str):
        try:
            loaded = json.loads(bundle)
        except Exception:
            return {"ok": False, "status": "input_rejected", "reason": "bundle JSON could not be parsed", "records": (), "audit_trail": {"events": ()}}
        if isinstance(loaded, Mapping):
            return loaded
        return {"ok": False, "status": "input_rejected", "reason": "bundle JSON did not contain an object", "records": (), "audit_trail": {"events": ()}}
    if isinstance(bundle, Mapping):
        return bundle
    raise TypeError("Studio console requires a DriverEvidenceBundle, mapping, or JSON string")


def _console_status(payload: Mapping[str, Any], integrity: EvidenceIntegrityStatus) -> StudioConsoleStatus:
    if integrity is EvidenceIntegrityStatus.MISMATCHED:
        return StudioConsoleStatus.INTEGRITY_MISMATCH
    records = payload.get("records", ())
    if not records:
        return StudioConsoleStatus.EMPTY
    raw_status = str(payload.get("status", "partial"))
    if raw_status == "ready" and integrity is EvidenceIntegrityStatus.VERIFIED:
        return StudioConsoleStatus.READY
    if raw_status == "input_rejected":
        return StudioConsoleStatus.INPUT_REJECTED
    return StudioConsoleStatus.PARTIAL


def _console_reason(payload: Mapping[str, Any], integrity: EvidenceIntegrityStatus, status: StudioConsoleStatus) -> str:
    if integrity is EvidenceIntegrityStatus.MISMATCHED:
        return "evidence bundle integrity mismatch; Studio rendering is read-only and not approval eligible"
    if status is StudioConsoleStatus.EMPTY:
        return "evidence bundle contains no driver records"
    return str(payload.get("reason", "read-only evidence console ready"))


def _resolve_selected_driver(records: Sequence[Mapping[str, Any]], selected_driver_id: str | None) -> str | None:
    ids = tuple(_optional_text(record.get("driver_id")) for record in records if record.get("driver_id") is not None)
    if selected_driver_id and selected_driver_id in ids:
        return selected_driver_id
    return ids[0] if ids else None


def _queue_item(record: Mapping[str, Any], selected_driver_id: str | None) -> DriverStudioQueueItem:
    driver_id = _optional_text(record.get("driver_id"))
    return DriverStudioQueueItem(
        driver_id=driver_id,
        driver_version=_optional_int(record.get("driver_version")),
        decision_status=str(record.get("decision_status", "unknown")),
        risk_level=str(record.get("risk_level", "unknown")),
        final_action=str(record.get("final_action", "unknown")),
        registry_state_before=_optional_text(record.get("registry_state_before")),
        registry_state_after=_optional_text(record.get("registry_state_after")),
        package_hash=_optional_text(record.get("package_hash")),
        regression_report_hash=_optional_text(record.get("regression_report_hash")),
        review_hash=_optional_text(record.get("review_hash")),
        selected=driver_id == selected_driver_id,
    )


def _risk_card(record: Mapping[str, Any], matrix: Mapping[str, bool]) -> DriverStudioRiskCard:
    driver_id = _optional_text(record.get("driver_id"))
    decision_status = str(record.get("decision_status", "unknown"))
    risk_level = str(record.get("risk_level", "unknown"))
    fixtures = tuple(_as_mapping(item) for item in record.get("fixture_results", ()))
    faults = tuple(_as_mapping(item) for item in record.get("faults", ()))
    fault_codes = tuple(str(fault.get("code")) for fault in faults if fault.get("code") is not None)
    reasons: list[str] = []
    if fixtures:
        passed = sum(1 for item in fixtures if bool(item.get("passed")))
        reasons.append(f"fixture replay summaries attached: {passed}/{len(fixtures)} passed")
    else:
        reasons.append("no fixture replay details attached; review decision is still visible")
    if faults:
        reasons.append("review faults are present: " + ", ".join(fault_codes or ("unknown",)))
    else:
        reasons.append("no review faults recorded")
    if decision_status in {"approval_ready", "registry_approved"}:
        reasons.append("driver is review-clean but signing and activation remain outside Studio")
        summary = f"{risk_level} risk; {decision_status.replace('_', ' ')}"
    elif decision_status in {"held", "quarantined"}:
        reasons.append("driver needs more evidence or manual review before approval")
        summary = f"{risk_level} risk; attention required"
    elif decision_status in {"rejected", "registry_rejected", "input_rejected"}:
        reasons.append("driver is not approval eligible from this evidence bundle")
        summary = f"{risk_level} risk; not approval eligible"
    else:
        reasons.append("decision status is unknown to the read-only console")
        summary = f"{risk_level} risk; unknown status"
    blocked = tuple(key for key in ("approve_driver", "reject_driver", "sign_driver", "activate_driver", "run_driver_vm", "write_storage", "mutate_registry") if matrix.get(key) is False)
    return DriverStudioRiskCard(
        driver_id=driver_id,
        risk_level=risk_level,
        decision_status=decision_status,
        summary=summary,
        reasons=tuple(reasons),
        blocked_authority=blocked,
        fault_codes=fault_codes,
    )


def _event_row(event: Mapping[str, Any]) -> DriverStudioEventRow:
    return DriverStudioEventRow(
        event_id=str(event.get("event_id", "")),
        event_type=str(event.get("event_type", "unknown")),
        actor_id=str(event.get("actor_id", "unknown")),
        action=_optional_text(event.get("action")),
        driver_id=_optional_text(event.get("driver_id")),
        timestamp=str(event.get("timestamp", "undated")),
        reason=str(event.get("reason", "")),
    )


def _queue_panel(queue: Sequence[DriverStudioQueueItem]) -> DriverStudioPanelSnapshot:
    attention = sum(1 for item in queue if item.needs_attention)
    rows = tuple(_queue_map(item) for item in queue)
    status = StudioPanelStatus.READY if queue else StudioPanelStatus.EMPTY
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.DRIVER_QUEUE,
        status=status,
        title="Driver Evidence Queue",
        summary=f"{len(queue)} drivers loaded; {attention} need attention",
        rows=rows,
        metrics={"driver_count": len(queue), "attention_count": attention},
    )


def _evidence_bundle_panel(payload: Mapping[str, Any], status: StudioConsoleStatus) -> DriverStudioPanelSnapshot:
    manifest = _as_mapping(payload.get("manifest", {}))
    rows = (
        {
            "bundle_id": payload.get("bundle_id"),
            "bundle_hash": payload.get("bundle_hash"),
            "schema": manifest.get("schema"),
            "tds_version": manifest.get("tds_version"),
            "created_by": manifest.get("created_by"),
            "created_at": manifest.get("created_at"),
            "driver_count": manifest.get("driver_count"),
            "audit_event_count": manifest.get("audit_event_count"),
            "private_keys_included": manifest.get("private_keys_included"),
            "mutable_authority": manifest.get("mutable_authority"),
        },
    )
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.EVIDENCE_BUNDLE,
        status=_panel_status_from_console(status),
        title="Evidence Bundle Viewer",
        summary=str(payload.get("reason", "read-only evidence bundle loaded")),
        rows=rows,
        metrics={"component_hash_count": len(_as_mapping(manifest.get("component_hashes", {})))},
    )


def _audit_trail_panel(payload: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> DriverStudioPanelSnapshot:
    trail = _as_mapping(payload.get("audit_trail", {}))
    status = StudioPanelStatus.READY if events else StudioPanelStatus.EMPTY
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.AUDIT_TRAIL,
        status=status,
        title="Audit Trail Panel",
        summary=f"{len(events)} chain-of-custody events; trail status {trail.get('status', 'unknown')}",
        rows=tuple(dict(event) for event in events),
        metrics={"event_count": len(events), "trail_hash": trail.get("trail_hash"), "trail_status": trail.get("status")},
    )


def _evidence_timeline_panel(
    payload: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    selected_driver_id: str | None,
) -> DriverStudioPanelSnapshot:
    """Build a chronological trust-history panel without granting authority."""

    rows: list[Mapping[str, Any]] = []
    manifest = _as_mapping(payload.get("manifest", {}))
    for record in _selected_records(records, selected_driver_id):
        driver_id = _optional_text(record.get("driver_id"))
        rows.extend(
            _lifecycle_rows_for_record(
                record,
                driver_id=driver_id,
                bundle_id=_optional_text(payload.get("bundle_id")),
                bundle_hash=_optional_text(payload.get("bundle_hash")),
                created_at=str(manifest.get("created_at") or "undated"),
            )
        )
    for event in events:
        if selected_driver_id is not None and event.get("driver_id") not in {None, selected_driver_id}:
            continue
        event_type = str(event.get("event_type") or "audit_event")
        stage = _timeline_stage_from_event(event)
        rows.append(
            {
                "timestamp": str(event.get("timestamp") or "undated"),
                "stage": stage,
                "status": _timeline_status_from_event(event),
                "severity": _timeline_severity_from_event(event),
                "driver_id": event.get("driver_id"),
                "actor_id": event.get("actor_id"),
                "label": event_type.replace("_", " ").title(),
                "detail": event.get("reason") or event_type,
                "source_event_id": event.get("event_id"),
                "package_hash": None,
                "regression_report_hash": event.get("regression_report_hash"),
                "evidence_hash": event.get("runtime_evidence_hash") or event.get("evidence_bundle_hash"),
                "review_hash": event.get("review_hash"),
                "registry_state": event.get("resulting_status") or event.get("previous_status"),
                "export_hash": event.get("evidence_bundle_hash") or payload.get("bundle_hash"),
                "authority": "observe_only",
            }
        )
    rows = _dedupe_timeline_rows(rows)
    status = StudioPanelStatus.READY if rows else StudioPanelStatus.EMPTY
    registry_rows = sum(1 for row in rows if str(row.get("stage")) in {"registry-approval-requested", "approved", "signed", "active", "observed-active"})
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.EVIDENCE_TIMELINE,
        status=status,
        title="Evidence Timeline",
        summary=f"{len(rows)} chronological lifecycle events; {registry_rows} registry observations" if rows else "no timeline evidence loaded",
        rows=tuple(rows),
        metrics={
            "timeline_event_count": len(rows),
            "registry_observation_count": registry_rows,
            "selected_driver_id": selected_driver_id,
            "authority": "observe_only",
            "export_ready": bool(payload.get("bundle_hash")),
        },
        warnings=() if payload.get("bundle_hash") else ("timeline is not export-hash bound",),
    )


def _lifecycle_rows_for_record(
    record: Mapping[str, Any],
    *,
    driver_id: str | None,
    bundle_id: str | None,
    bundle_hash: str | None,
    created_at: str,
) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    version = record.get("driver_version")
    package_hash = _optional_text(record.get("package_hash"))
    regression_hash = _optional_text(record.get("regression_report_hash"))
    review_hash = _optional_text(record.get("review_hash"))
    decision_status = str(record.get("decision_status") or "unknown")
    final_action = str(record.get("final_action") or "unknown")
    registry_after = _optional_text(record.get("registry_state_after"))
    evidence_summary = _as_mapping(record.get("evidence_summary", {}))
    fixture_results = tuple(_as_mapping(item) for item in record.get("fixture_results", ()) or ())

    rows.append(_timeline_row(created_at, "proposal", "complete" if driver_id else "partial", "info", driver_id, "Driver proposal recorded", f"driver v{version} entered evidence review", package_hash=package_hash))
    rows.append(_timeline_row(created_at, "validated", "complete" if evidence_summary.get("runtime_ok", True) else "attention", "success" if evidence_summary.get("runtime_ok", True) else "warning", driver_id, "Validation evidence attached", str(record.get("reason") or "validation evidence recorded"), package_hash=package_hash, regression_report_hash=regression_hash))
    if package_hash:
        rows.append(_timeline_row(created_at, "compiled", "complete", "success", driver_id, "Bytecode package hash captured", "compiled bytecode hash is included in evidence", package_hash=package_hash))
    if fixture_results:
        passed = sum(1 for fixture in fixture_results if bool(fixture.get("passed")))
        status = "complete" if passed == len(fixture_results) else "attention"
        severity = "success" if status == "complete" else "warning"
        rows.append(_timeline_row(created_at, "fixture-tested", status, severity, driver_id, "Fixture replay summarized", f"{passed}/{len(fixture_results)} fixture cases passed", package_hash=package_hash, regression_report_hash=regression_hash))
    if bundle_hash:
        rows.append(_timeline_row(created_at, "evidence-ready", "complete", "success", driver_id, "Evidence bundle hash captured", f"bundle {bundle_id or 'unlabeled'} is hash-bound", package_hash=package_hash, regression_report_hash=regression_hash, evidence_hash=bundle_hash))
    if review_hash:
        rows.append(_timeline_row(created_at, "review-submitted", "complete", "info", driver_id, "Review decision captured", f"requested {record.get('requested_action')} / final {final_action}", package_hash=package_hash, regression_report_hash=regression_hash, review_hash=review_hash))
        reviewed_status = "complete" if decision_status in {"approval_ready", "registry_approved", "held", "rejected", "quarantined"} else "attention"
        rows.append(_timeline_row(created_at, "reviewed", reviewed_status, "success" if reviewed_status == "complete" else "warning", driver_id, "Review status resolved", decision_status, package_hash=package_hash, regression_report_hash=regression_hash, review_hash=review_hash))
    if registry_after:
        rows.append(_timeline_row(created_at, _registry_stage(registry_after, decision_status), "observed", "info", driver_id, "Registry state observed", registry_after, package_hash=package_hash, regression_report_hash=regression_hash, review_hash=review_hash, registry_state=registry_after))
    if bundle_hash:
        rows.append(_timeline_row(created_at, "exported", "complete", "success", driver_id, "Export manifest prepared", "timeline-ready evidence can feed export/audit packets", package_hash=package_hash, regression_report_hash=regression_hash, review_hash=review_hash, evidence_hash=bundle_hash, export_hash=bundle_hash))
    return tuple(rows)


def _timeline_row(
    timestamp: str,
    stage: str,
    status: str,
    severity: str,
    driver_id: str | None,
    label: str,
    detail: str,
    *,
    source_event_id: str | None = None,
    package_hash: str | None = None,
    regression_report_hash: str | None = None,
    evidence_hash: str | None = None,
    review_hash: str | None = None,
    registry_state: str | None = None,
    export_hash: str | None = None,
) -> Mapping[str, Any]:
    return {
        "timestamp": timestamp,
        "stage": stage,
        "status": status,
        "severity": severity,
        "driver_id": driver_id,
        "actor_id": "studio-evidence",
        "label": label,
        "detail": detail,
        "source_event_id": source_event_id,
        "package_hash": package_hash,
        "regression_report_hash": regression_report_hash,
        "evidence_hash": evidence_hash,
        "review_hash": review_hash,
        "registry_state": registry_state,
        "export_hash": export_hash,
        "authority": "observe_only",
    }


def _timeline_stage_from_event(event: Mapping[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    action = str(event.get("action") or "")
    resulting = str(event.get("resulting_status") or "")
    if event_type == "regression_attached":
        return "fixture-tested"
    if event_type == "admin_reviewed":
        return "reviewed" if action else "review-submitted"
    if event_type == "registry_state_observed":
        return _registry_stage(resulting, action)
    if event_type == "export_created":
        return "exported"
    if event_type == "export_verified":
        return "exported"
    return "evidence-ready"


def _registry_stage(registry_state: str, decision_status: str = "") -> str:
    lowered = str(registry_state or decision_status).lower()
    if lowered in {"approved", "registry_approved", "approval_ready"}:
        return "approved"
    if lowered == "signed":
        return "signed"
    if lowered == "active":
        return "observed-active"
    if lowered in {"candidate", "draft"}:
        return "registry-approval-requested"
    return "registry-approval-requested"


def _timeline_status_from_event(event: Mapping[str, Any]) -> str:
    resulting = str(event.get("resulting_status") or event.get("action") or "observed").lower()
    if resulting in {"rejected", "registry_rejected", "quarantined", "input_rejected"}:
        return "attention"
    if resulting in {"held", "hold"}:
        return "pending"
    return "observed" if event.get("event_type") == "registry_state_observed" else "complete"


def _timeline_severity_from_event(event: Mapping[str, Any]) -> str:
    status = _timeline_status_from_event(event)
    if status == "attention":
        return "warning"
    if str(event.get("event_type")) in {"export_created", "export_verified", "regression_attached"}:
        return "success"
    return "info"


def _dedupe_timeline_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[Mapping[str, Any]] = []
    for row in rows:
        key = (row.get("stage"), row.get("driver_id"), row.get("source_event_id"), row.get("package_hash"), row.get("review_hash"), row.get("label"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return sorted(out, key=lambda row: (str(row.get("timestamp") or ""), _stage_order(str(row.get("stage") or "")), str(row.get("source_event_id") or ""), str(row.get("label") or "")))


def _stage_order(stage: str) -> int:
    order = {
        "draft": 0,
        "proposal": 1,
        "validated": 2,
        "compiled": 3,
        "fixture-tested": 4,
        "evidence-ready": 5,
        "review-submitted": 6,
        "reviewed": 7,
        "registry-approval-requested": 8,
        "approved": 9,
        "signed": 10,
        "active": 11,
        "observed-active": 12,
        "exported": 13,
    }
    return order.get(stage, 99)


def _fixture_replay_panel(records: Sequence[Mapping[str, Any]], selected_driver_id: str | None) -> DriverStudioPanelSnapshot:
    selected_records = _selected_records(records, selected_driver_id)
    rows: list[Mapping[str, Any]] = []
    for record in selected_records:
        for fixture in record.get("fixture_results", ()):
            rows.append(dict(_as_mapping(fixture), driver_id=record.get("driver_id")))
    passed = sum(1 for row in rows if bool(row.get("passed")))
    status = StudioPanelStatus.READY if rows else StudioPanelStatus.EMPTY
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.FIXTURE_REPLAY,
        status=status,
        title="Fixture Replay Summary",
        summary=f"{passed}/{len(rows)} fixture summaries passed for selected driver" if rows else "no fixture replay details attached",
        rows=tuple(rows),
        metrics={"fixture_count": len(rows), "passed_count": passed, "selected_driver_id": selected_driver_id},
    )


def _risk_card_panel(risk_cards: Sequence[DriverStudioRiskCard], selected_driver_id: str | None) -> DriverStudioPanelSnapshot:
    cards = tuple(card for card in risk_cards if selected_driver_id is None or card.driver_id == selected_driver_id)
    rows = tuple(_risk_card_map(card) for card in cards)
    status = StudioPanelStatus.READY if rows else StudioPanelStatus.EMPTY
    summary = rows[0]["summary"] if rows else "no risk card available"
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.RISK_CARD,
        status=status,
        title="Risk Card Inspector",
        summary=str(summary),
        rows=rows,
        metrics={"card_count": len(rows), "selected_driver_id": selected_driver_id},
    )


def _registry_state_panel(records: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], selected_driver_id: str | None) -> DriverStudioPanelSnapshot:
    rows: list[Mapping[str, Any]] = []
    for record in _selected_records(records, selected_driver_id):
        rows.append(
            {
                "driver_id": record.get("driver_id"),
                "registry_state_before": record.get("registry_state_before"),
                "registry_state_after": record.get("registry_state_after"),
                "decision_status": record.get("decision_status"),
                "review_hash": record.get("review_hash"),
            }
        )
    for event in events:
        if event.get("event_type") == "registry_state_observed" and (selected_driver_id is None or event.get("driver_id") == selected_driver_id):
            rows.append(
                {
                    "driver_id": event.get("driver_id"),
                    "registry_event": event.get("action"),
                    "previous_status": event.get("previous_status"),
                    "resulting_status": event.get("resulting_status"),
                    "public_key_fingerprint": event.get("public_key_fingerprint"),
                    "signature_status": event.get("signature_status"),
                }
            )
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.REGISTRY_STATE,
        status=StudioPanelStatus.READY if rows else StudioPanelStatus.EMPTY,
        title="Registry State Observer",
        summary="registry state is displayed only; Studio has no registry mutation authority",
        rows=tuple(rows),
        metrics={"row_count": len(rows), "selected_driver_id": selected_driver_id},
    )


def _export_integrity_panel(payload: Mapping[str, Any], integrity: EvidenceIntegrityStatus) -> DriverStudioPanelSnapshot:
    status = StudioPanelStatus.READY if integrity is EvidenceIntegrityStatus.VERIFIED else StudioPanelStatus.INTEGRITY_MISMATCH
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.EXPORT_INTEGRITY,
        status=status,
        title="Export Integrity Verifier",
        summary=f"export integrity is {integrity.value}",
        rows=(
            {
                "bundle_id": payload.get("bundle_id"),
                "bundle_hash": payload.get("bundle_hash"),
                "integrity_status": integrity.value,
            },
        ),
        metrics={"verified": integrity is EvidenceIntegrityStatus.VERIFIED},
        warnings=() if integrity is EvidenceIntegrityStatus.VERIFIED else ("bundle hash did not verify",),
    )


def _export_audit_console_panel(
    payload: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    selected_driver_id: str | None,
) -> DriverStudioPanelSnapshot:
    """Build a selected-driver export/audit preparation panel.

    The panel packages observable evidence metadata only.  It does not create a
    signed export, approve/reject drivers, mutate Registry state, or write
    storage.
    """

    selected_records = _selected_records(records, selected_driver_id)
    timeline_rows = tuple(_as_mapping(row) for row in _evidence_timeline_panel(payload, records, events, selected_driver_id).rows)
    audit_events = tuple(_as_mapping(event) for event in events)
    registry_rows = tuple(row for row in timeline_rows if str(row.get("stage")) in {"registry-approval-requested", "approved", "signed", "active", "observed-active"})
    rows: list[Mapping[str, Any]] = []
    for record in selected_records:
        driver_id = _optional_text(record.get("driver_id"))
        driver_timeline = tuple(row for row in timeline_rows if row.get("driver_id") in {None, driver_id})
        driver_registry = tuple(row for row in registry_rows if row.get("driver_id") in {None, driver_id})
        fixture_results = tuple(_as_mapping(item) for item in record.get("fixture_results", ()) or ())
        package_hash = _optional_text(record.get("package_hash"))
        regression_report_hash = _optional_text(record.get("regression_report_hash"))
        review_hash = _optional_text(record.get("review_hash"))
        missing: list[str] = []
        if not driver_id:
            missing.append("driver_identity")
        if not payload.get("bundle_hash"):
            missing.append("evidence_bundle_hash")
        if not package_hash:
            missing.append("compiled_bytecode_hash")
        if not regression_report_hash:
            missing.append("fixture_replay_summary")
        if not review_hash:
            missing.append("review_action_history")
        if not driver_timeline:
            missing.append("evidence_timeline")
        # Registry observations are export-mapped when present, but approval,
        # signing, and activation can legitimately still be pending.  Absence is
        # noted by count instead of blocking packet preview preparation.
        readiness = "packet_ready" if not missing else "partial"
        rows.append(
            {
                "driver_id": driver_id,
                "bundle_id": payload.get("bundle_id"),
                "bundle_hash": payload.get("bundle_hash"),
                "package_hash": package_hash,
                "regression_report_hash": regression_report_hash,
                "review_hash": review_hash,
                "audit_event_count": len(audit_events),
                "timeline_event_count": len(driver_timeline),
                "registry_observation_count": len(driver_registry),
                "fixture_result_count": len(fixture_results),
                "readiness_status": readiness,
                "missing_items": tuple(missing),
                "authority": "prepare_only",
            }
        )
    if not rows and payload.get("bundle_hash"):
        rows.append(
            {
                "driver_id": selected_driver_id,
                "bundle_id": payload.get("bundle_id"),
                "bundle_hash": payload.get("bundle_hash"),
                "audit_event_count": len(audit_events),
                "timeline_event_count": len(timeline_rows),
                "registry_observation_count": len(registry_rows),
                "fixture_result_count": 0,
                "readiness_status": "partial",
                "missing_items": ("driver_identity",),
                "authority": "prepare_only",
            }
        )
    ready_count = sum(1 for row in rows if row.get("readiness_status") == "packet_ready")
    status = StudioPanelStatus.READY if ready_count else StudioPanelStatus.PARTIAL if rows else StudioPanelStatus.EMPTY
    warnings = () if ready_count else ("export/audit packet preview is missing required evidence rows",) if rows else ("no selected driver evidence available for export/audit preview",)
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.EXPORT_AUDIT_CONSOLE,
        status=status,
        title="Export / Audit Console",
        summary=f"{ready_count}/{len(rows)} selected export packet previews are ready" if rows else "no export/audit packet preview available",
        rows=tuple(rows),
        metrics={
            "preview_count": len(rows),
            "ready_count": ready_count,
            "audit_event_count": len(audit_events),
            "timeline_event_count": len(timeline_rows),
            "registry_observation_count": len(registry_rows),
            "selected_driver_id": selected_driver_id,
            "authority": "prepare_only",
        },
        warnings=warnings,
    )


def _manual_driver_builder_panel(selected_driver_id: str | None) -> DriverStudioPanelSnapshot:
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.MANUAL_DRIVER_BUILDER,
        status=StudioPanelStatus.READY,
        title="Manual Driver Builder",
        summary="visual task forms create Foundry proposals only; trust authority remains external",
        rows=(
            {
                "selected_driver_id": selected_driver_id,
                "workbench_state": "proposal_ready",
                "routes_to": "DriverFoundry",
                "authority_state": "no_registry_no_signing_no_activation",
            },
        ),
        metrics={
            "proposal_authority": True,
            "registry_authority": False,
            "signing_authority": False,
            "activation_authority": False,
        },
        warnings=("manual driver builder emits proposals, not trusted active drivers",),
    )


def _event_console_panel(events: Sequence[DriverStudioEventRow]) -> DriverStudioPanelSnapshot:
    rows = tuple(_event_row_map(event) for event in events)
    return DriverStudioPanelSnapshot(
        kind=StudioPanelKind.EVENT_CONSOLE,
        status=StudioPanelStatus.READY if events else StudioPanelStatus.EMPTY,
        title="Bottom Event Console",
        summary=f"{len(events)} non-mutating audit events loaded",
        rows=rows,
        metrics={"event_count": len(events)},
    )


def _selected_records(records: Sequence[Mapping[str, Any]], selected_driver_id: str | None) -> tuple[Mapping[str, Any], ...]:
    if selected_driver_id is None:
        return tuple(records)
    return tuple(record for record in records if record.get("driver_id") == selected_driver_id)


def _panel_status_from_console(status: StudioConsoleStatus) -> StudioPanelStatus:
    if status is StudioConsoleStatus.READY:
        return StudioPanelStatus.READY
    if status is StudioConsoleStatus.EMPTY:
        return StudioPanelStatus.EMPTY
    if status is StudioConsoleStatus.INPUT_REJECTED:
        return StudioPanelStatus.INPUT_REJECTED
    if status is StudioConsoleStatus.INTEGRITY_MISMATCH:
        return StudioPanelStatus.INTEGRITY_MISMATCH
    return StudioPanelStatus.PARTIAL


def _console_snapshot_map(snapshot: DriverStudioConsoleSnapshot) -> Mapping[str, Any]:
    return {
        "ok": snapshot.ok,
        "status": snapshot.status.value,
        "reason": snapshot.reason,
        "bundle_id": snapshot.bundle_id,
        "bundle_hash": snapshot.bundle_hash,
        "integrity_status": snapshot.integrity_status,
        "selected_driver_id": snapshot.selected_driver_id,
        "console_hash": snapshot.console_hash,
        "panels": [_panel_map(panel) for panel in snapshot.panels],
        "queue": [_queue_map(item) for item in snapshot.queue],
        "risk_cards": [_risk_card_map(card) for card in snapshot.risk_cards],
        "event_console": [_event_row_map(row) for row in snapshot.event_console],
        "capability_matrix": dict(snapshot.capability_matrix),
    }


def _panel_map(panel: DriverStudioPanelSnapshot) -> Mapping[str, Any]:
    return {
        "kind": panel.kind.value,
        "status": panel.status.value,
        "title": panel.title,
        "summary": panel.summary,
        "rows": [dict(row) for row in panel.rows],
        "metrics": dict(panel.metrics),
        "warnings": list(panel.warnings),
    }


def _queue_map(item: DriverStudioQueueItem) -> Mapping[str, Any]:
    return {
        "driver_id": item.driver_id,
        "driver_version": item.driver_version,
        "decision_status": item.decision_status,
        "risk_level": item.risk_level,
        "final_action": item.final_action,
        "registry_state_before": item.registry_state_before,
        "registry_state_after": item.registry_state_after,
        "package_hash": item.package_hash,
        "regression_report_hash": item.regression_report_hash,
        "review_hash": item.review_hash,
        "selected": item.selected,
        "needs_attention": item.needs_attention,
    }


def _risk_card_map(card: DriverStudioRiskCard) -> Mapping[str, Any]:
    return {
        "driver_id": card.driver_id,
        "risk_level": card.risk_level,
        "decision_status": card.decision_status,
        "summary": card.summary,
        "reasons": list(card.reasons),
        "blocked_authority": list(card.blocked_authority),
        "fault_codes": list(card.fault_codes),
    }


def _event_row_map(row: DriverStudioEventRow) -> Mapping[str, Any]:
    return {
        "event_id": row.event_id,
        "event_type": row.event_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "driver_id": row.driver_id,
        "timestamp": row.timestamp,
        "reason": row.reason,
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _studio_hash_payload(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_studio_canonical_json(_studio_normalize(value)).encode("utf-8")).hexdigest()


def _studio_normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _studio_normalize(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_studio_normalize(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _studio_canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)

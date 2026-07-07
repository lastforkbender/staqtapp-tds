"""Hydrated Driver Studio cockpit panel view-models.

v3.1.11 keeps the optional PyQt5 layer import-safe while making the cockpit
panels far more concrete for a real GUI.  The hydrator converts the compact
v3.1.9/v3.1.10 bridge snapshots into table schemas, cards, timelines, and
review-action descriptors.  It does not approve, sign, activate, execute,
mutate Registry state, write storage, or store private keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from staqtapp_tds.drivers.review import ReviewAction
from staqtapp_tds.drivers.studio import StudioPanelKind
from staqtapp_tds.drivers.studio_builder import StudioManualDriverTask
from .bridge import StudioQtPanelViewModel, StudioQtShellState


@dataclass(frozen=True, slots=True)
class StudioTableColumn:
    """Stable table-column metadata for a hydrated Studio panel."""

    key: str
    label: str
    width_hint: int = 140
    align: str = "left"
    monospace: bool = False


@dataclass(frozen=True, slots=True)
class StudioPanelCard:
    """Card payload for evidence, risk, registry, integrity, and builder views."""

    title: str
    subtitle: str = ""
    severity: str = "info"
    fields: Mapping[str, Any] = field(default_factory=dict)
    badges: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StudioTimelineItem:
    """Event stream row prepared for a timeline/list widget."""

    timestamp: str
    label: str
    severity: str
    actor_id: str
    driver_id: str | None
    detail: str
    source_event_id: str


@dataclass(frozen=True, slots=True)
class StudioPanelActionDescriptor:
    """Button/action metadata for review-intent controls.

    These are UI descriptors only. Invoking them must still call
    ``StudioQtBridge.build_action_request`` and ``submit_review_action``.
    """

    action_id: str
    label: str
    requested_action: str
    source_panel: StudioPanelKind
    enabled: bool
    reason: str
    requires_rationale: bool = False
    dangerous: bool = False


@dataclass(frozen=True, slots=True)
class StudioFormField:
    """Manual-builder field metadata for a real Qt form."""

    name: str
    label: str
    widget: str
    default: Any
    required: bool = False
    options: tuple[Any, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    help_text: str = ""


@dataclass(frozen=True, slots=True)
class StudioHydratedPanel:
    """A GUI-ready panel model with richer surface semantics."""

    kind: StudioPanelKind
    title: str
    icon_name: str
    dock_area: str
    primary_surface: str
    status: str
    severity: str
    summary: str
    columns: tuple[StudioTableColumn, ...] = ()
    rows: tuple[Mapping[str, Any], ...] = ()
    cards: tuple[StudioPanelCard, ...] = ()
    timeline: tuple[StudioTimelineItem, ...] = ()
    actions: tuple[StudioPanelActionDescriptor, ...] = ()
    form_fields: tuple[StudioFormField, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    empty_hint: str = ""
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class StudioHydratedCockpitState:
    """Whole-cockpit hydration result consumed by a PyQt5 main window."""

    ok: bool
    status: str
    severity: str
    reason: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None
    panels: tuple[StudioHydratedPanel, ...]
    event_stream: tuple[StudioTimelineItem, ...]
    metrics: Mapping[str, Any]
    capability_matrix: Mapping[str, bool]

    def panel(self, kind: StudioPanelKind | str) -> StudioHydratedPanel:
        wanted = kind if isinstance(kind, StudioPanelKind) else StudioPanelKind(str(kind))
        for panel in self.panels:
            if panel.kind is wanted:
                return panel
        raise KeyError(wanted.value)


class StudioCockpitHydrator:
    """Pure-Python hydrator for optional Driver Studio PyQt5 views."""

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the hydration authority boundary."""

        return {
            "hydrate_panel_view_models": True,
            "render_table_columns": True,
            "render_card_surfaces": True,
            "render_timeline_stream": True,
            "render_evidence_lifecycle_timeline": True,
            "render_risk_intelligence_cards": True,
            "render_review_action_descriptors": True,
            "render_manual_builder_form_schema": True,
            "render_manual_builder_ui_runtime": True,
            "render_visual_quality_review": True,
            "render_export_audit_console": True,
            "render_export_audit_packet_preview": True,
            "render_export_integrity_workflow": True,
            "submit_review_actions": False,
            "approve_driver": False,
            "reject_driver": False,
            "quarantine_driver": False,
            "call_registry_approve": False,
            "sign_driver": False,
            "attach_signature": False,
            "activate_driver": False,
            "run_driver_vm": False,
            "write_storage": False,
            "execute_python": False,
            "mutate_registry": False,
            "store_private_keys": False,
            "bypass_policy": False,
        }

    def hydrate(self, state: StudioQtShellState) -> StudioHydratedCockpitState:
        """Hydrate an immutable shell state for concrete Qt widgets."""

        panels = tuple(self.hydrate_panel(panel, state=state) for panel in state.panels)
        event_stream = tuple(item for panel in panels if panel.kind is StudioPanelKind.EVENT_CONSOLE for item in panel.timeline)
        metrics = {
            "panel_count": len(panels),
            "ready_panel_count": sum(1 for panel in panels if panel.status == "ready"),
            "warning_count": sum(len(panel.warnings) for panel in panels),
            "event_count": len(event_stream),
            "selected_driver_id": state.selected_driver_id,
        }
        matrix = dict(state.capability_matrix)
        matrix.update(self.capability_matrix())
        return StudioHydratedCockpitState(
            ok=state.ok,
            status=state.status,
            severity=_severity_from_status(state.status),
            reason=state.reason,
            selected_driver_id=state.selected_driver_id,
            bundle_id=state.bundle_id,
            bundle_hash=state.bundle_hash,
            console_hash=state.console_hash,
            panels=panels,
            event_stream=event_stream,
            metrics=metrics,
            capability_matrix=matrix,
        )

    def hydrate_panel(self, panel: StudioQtPanelViewModel, *, state: StudioQtShellState) -> StudioHydratedPanel:
        """Hydrate one compact panel view-model."""

        columns = _columns_for(panel.kind)
        cards = _cards_for(panel, state=state)
        timeline = _timeline_for(panel) if panel.kind in {StudioPanelKind.EVENT_CONSOLE, StudioPanelKind.EVIDENCE_TIMELINE} else ()
        actions = _actions_for(panel, state=state)
        form_fields = manual_builder_form_schema() if panel.kind is StudioPanelKind.MANUAL_DRIVER_BUILDER else ()
        return StudioHydratedPanel(
            kind=panel.kind,
            title=panel.title,
            icon_name=panel.icon_name,
            dock_area=panel.dock_area,
            primary_surface=panel.primary_surface,
            status=panel.status,
            severity=_panel_severity(panel),
            summary=panel.summary,
            columns=columns,
            rows=tuple(dict(row) for row in panel.rows),
            cards=cards,
            timeline=timeline,
            actions=actions,
            form_fields=form_fields,
            metrics=dict(panel.metrics),
            warnings=tuple(panel.warnings),
            empty_hint=_empty_hint(panel.kind),
            read_only=panel.read_only,
        )


_DEFAULT_TASK = StudioManualDriverTask(
    driver_id="ManualPolicyDriver",
    description="Manual cockpit proposal for policy-routing manifests",
)


def manual_builder_form_schema() -> tuple[StudioFormField, ...]:
    """Return stable form fields for the Manual Driver Builder panel."""

    task = _DEFAULT_TASK
    return (
        StudioFormField("driver_id", "Driver ID", "line_edit", task.driver_id, required=True, help_text="TDDL token; proposal identity only."),
        StudioFormField("description", "Description", "text_edit", task.description, required=True, help_text="Human-readable proposal rationale."),
        StudioFormField("driver_version", "Version", "spin_box", task.driver_version, required=True, minimum=1, maximum=9999),
        StudioFormField("kind", "Driver Kind", "combo_box", task.kind, required=True, options=("search", "extract", "rank", "adapter", "policy")),
        StudioFormField("safety", "Safety Class", "combo_box", task.safety, required=True, options=("bounded", "restricted", "experimental")),
        StudioFormField("scan_scope", "Scan Scope", "line_edit", task.scan_scope, required=True, help_text="Must remain inside .tds."),
        StudioFormField("recursive", "Recursive Scan", "check_box", task.recursive),
        StudioFormField("scan_limit", "Scan Limit", "spin_box", task.scan_limit, minimum=1, maximum=100000),
        StudioFormField("max_depth", "Max Depth", "spin_box", task.max_depth, minimum=0, maximum=64),
        StudioFormField("timeout_ms", "Timeout ms", "spin_box", task.timeout_ms, minimum=1, maximum=60000),
        StudioFormField("match_field", "Match Field", "line_edit", task.match_field, required=True),
        StudioFormField("match_eq", "Match Equals", "line_edit", task.match_eq),
        StudioFormField("semantic_query", "Semantic Query", "line_edit", task.semantic_query),
        StudioFormField("semantic_threshold", "Semantic Threshold", "double_spin_box", task.semantic_threshold, minimum=0.0, maximum=1.0),
        StudioFormField("capabilities", "Capabilities", "text_edit", ", ".join(task.capabilities), required=True, help_text="Comma-separated dotted capabilities; unsafe Python/eval/import/socket/subprocess tokens are rejected."),
        StudioFormField("adapters", "Adapters", "text_edit", ", ".join(task.adapters), help_text="Comma-separated bounded predicate/scorer adapters."),
        StudioFormField("extract_fields", "Extract Fields", "text_edit", ", ".join(task.extract_fields), required=True, help_text="Comma-separated manifest fields projected by EXTRACT."),
        StudioFormField("score_adapter", "Score Adapter", "line_edit", task.score_adapter),
        StudioFormField("score_weight", "Score Weight", "combo_box", task.score_weight, options=("semantic", "recency", "confidence", "safety", "balanced")),
        StudioFormField("score_threshold", "Score Threshold", "double_spin_box", task.score_threshold, minimum=0.0, maximum=1.0),
        StudioFormField("emit_mode", "Emit Mode", "combo_box", task.emit_mode, options=("ranked", "list", "first", "proposal")),
        StudioFormField("emit_limit", "Emit Limit", "spin_box", task.emit_limit, minimum=1, maximum=10000),
        StudioFormField("trace_event", "Trace Event", "line_edit", task.trace_event),
        StudioFormField("evolution", "Evolution Rules", "text_edit", "\n".join(task.evolution), help_text="One bounded evolution rule per line; deny external_io is preserved."),
        StudioFormField("tags", "Tags", "line_edit", ", ".join(task.tags), help_text="Optional comma-separated Studio tags."),
    )


def studio_cockpit_hydration_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying hydration boundaries."""

    return StudioCockpitHydrator().capability_matrix()


def _columns_for(kind: StudioPanelKind) -> tuple[StudioTableColumn, ...]:
    specs: Mapping[StudioPanelKind, tuple[tuple[str, str, int, bool], ...]] = {
        StudioPanelKind.DRIVER_QUEUE: (
            ("selected", "Sel", 54, False),
            ("driver_id", "Driver", 190, True),
            ("driver_version", "Ver", 70, False),
            ("decision_status", "Decision", 150, False),
            ("risk_level", "Risk", 90, False),
            ("final_action", "Final Action", 140, False),
            ("needs_attention", "Attention", 100, False),
        ),
        StudioPanelKind.EVIDENCE_BUNDLE: (
            ("bundle_id", "Bundle", 190, True),
            ("tds_version", "TDS", 90, False),
            ("driver_count", "Drivers", 90, False),
            ("audit_event_count", "Audit Events", 120, False),
            ("private_keys_included", "Private Keys", 120, False),
            ("mutable_authority", "Mutable", 100, False),
        ),
        StudioPanelKind.AUDIT_TRAIL: (
            ("timestamp", "Timestamp", 190, True),
            ("event_type", "Type", 190, False),
            ("actor_id", "Actor", 150, True),
            ("driver_id", "Driver", 190, True),
            ("action", "Action", 140, False),
            ("reason", "Reason", 260, False),
        ),
        StudioPanelKind.EVIDENCE_TIMELINE: (
            ("timestamp", "Timestamp", 190, True),
            ("stage", "Lifecycle Stage", 190, False),
            ("status", "Status", 120, False),
            ("severity", "Severity", 100, False),
            ("driver_id", "Driver", 190, True),
            ("label", "Event", 220, False),
            ("registry_state", "Registry", 130, False),
            ("detail", "Detail", 320, False),
        ),
        StudioPanelKind.FIXTURE_REPLAY: (
            ("driver_id", "Driver", 190, True),
            ("case_id", "Fixture", 190, True),
            ("passed", "Passed", 90, False),
            ("status", "Status", 120, False),
            ("expected_vm_status", "Expected VM", 140, False),
            ("emitted_count", "Emitted", 90, False),
        ),
        StudioPanelKind.RISK_CARD: (
            ("driver_id", "Driver", 190, True),
            ("risk_level", "Risk", 90, False),
            ("decision_status", "Decision", 150, False),
            ("summary", "Summary", 260, False),
        ),
        StudioPanelKind.REGISTRY_STATE: (
            ("driver_id", "Driver", 190, True),
            ("registry_state_before", "Before", 130, False),
            ("registry_state_after", "After", 130, False),
            ("decision_status", "Decision", 150, False),
            ("signature_status", "Signature", 130, False),
        ),
        StudioPanelKind.EXPORT_INTEGRITY: (
            ("bundle_id", "Bundle", 190, True),
            ("integrity_status", "Integrity", 120, False),
            ("bundle_hash", "Hash", 300, True),
            ("workflow_status", "Workflow", 130, False),
            ("manifest_hash", "Manifest Hash", 260, True),
            ("packet_hash", "Packet Hash", 260, True),
        ),
        StudioPanelKind.EXPORT_AUDIT_CONSOLE: (
            ("driver_id", "Driver", 190, True),
            ("readiness_status", "Readiness", 150, False),
            ("bundle_hash", "Bundle Hash", 260, True),
            ("package_hash", "Package Hash", 260, True),
            ("review_hash", "Review Hash", 240, True),
            ("timeline_event_count", "Timeline", 100, False),
            ("registry_observation_count", "Registry", 100, False),
            ("missing_items", "Missing", 280, False),
        ),
        StudioPanelKind.EVENT_CONSOLE: (
            ("timestamp", "Timestamp", 190, True),
            ("event_type", "Type", 190, False),
            ("actor_id", "Actor", 150, True),
            ("driver_id", "Driver", 190, True),
            ("reason", "Reason", 280, False),
        ),
        StudioPanelKind.MANUAL_DRIVER_BUILDER: (
            ("workbench_state", "Workbench", 150, False),
            ("routes_to", "Routes To", 150, False),
            ("authority_state", "Authority", 260, False),
        ),
    }
    return tuple(StudioTableColumn(key, label, width, monospace=mono) for key, label, width, mono in specs.get(kind, ()))


def _cards_for(panel: StudioQtPanelViewModel, *, state: StudioQtShellState) -> tuple[StudioPanelCard, ...]:
    if panel.kind is StudioPanelKind.RISK_CARD:
        return tuple(
            StudioPanelCard(
                title=str(row.get("driver_id") or "Unknown driver"),
                subtitle=str(row.get("summary") or panel.summary),
                severity=_risk_severity(str(row.get("risk_level", "unknown")), str(row.get("decision_status", "unknown"))),
                fields={
                    "risk_level": row.get("risk_level"),
                    "decision_status": row.get("decision_status"),
                    "fault_codes": row.get("fault_codes", ()),
                    "blocked_authority": row.get("blocked_authority", ()),
                    "reasons": row.get("reasons", ()),
                    "intelligence_surface": "risk_intelligence_cards",
                },
                badges=tuple(str(item) for item in row.get("fault_codes", ()) or ()) or ("risk-intelligence-ready",),
            )
            for row in panel.rows
        )
    if panel.kind is StudioPanelKind.EVIDENCE_TIMELINE:
        stages = tuple(str(row.get("stage")) for row in panel.rows if row.get("stage"))
        registry_count = sum(1 for stage in stages if stage in {"registry-approval-requested", "approved", "signed", "active", "observed-active"})
        return (
            StudioPanelCard(
                title="Timeline Integrity",
                subtitle="Chronological trust history prepared for export/audit review.",
                severity="success" if panel.rows else "muted",
                fields={
                    "timeline_event_count": len(panel.rows),
                    "unique_stage_count": len(set(stages)),
                    "registry_observation_count": registry_count,
                    "selected_driver_id": state.selected_driver_id,
                    "authority": "observe_only",
                },
                badges=("chronological", "export-ready", "observe-only"),
            ),
        )
    if panel.kind is StudioPanelKind.EXPORT_INTEGRITY:
        row = dict(panel.rows[0]) if panel.rows else {}
        return (
            StudioPanelCard(
                title="Export Integrity Workflow",
                subtitle=str(row.get("workflow_status") or row.get("integrity_status") or panel.status),
                severity="success" if row.get("integrity_status") == "verified" else "danger",
                fields={
                    "bundle_id": row.get("bundle_id"),
                    "bundle_hash": row.get("bundle_hash"),
                    "workflow_status": row.get("workflow_status", "bundle_verified" if row.get("integrity_status") == "verified" else "mismatch"),
                    "verify_only": True,
                },
                badges=("verified",) if row.get("integrity_status") == "verified" else ("mismatch",),
            ),
        )
    if panel.kind is StudioPanelKind.EXPORT_AUDIT_CONSOLE:
        row = dict(panel.rows[0]) if panel.rows else {}
        ready = str(row.get("readiness_status") or "empty") == "packet_ready"
        return (
            StudioPanelCard(
                title="Export / Audit Packet Preview",
                subtitle="Hash-backed evidence packaging preview; no Registry trust authority.",
                severity="success" if ready else "warning" if panel.rows else "muted",
                fields={
                    "driver_id": row.get("driver_id"),
                    "bundle_hash": row.get("bundle_hash"),
                    "package_hash": row.get("package_hash"),
                    "review_hash": row.get("review_hash"),
                    "timeline_event_count": row.get("timeline_event_count", 0),
                    "registry_observation_count": row.get("registry_observation_count", 0),
                    "readiness_status": row.get("readiness_status", panel.status),
                    "missing_items": row.get("missing_items", ()),
                    "authority": "prepare_only",
                },
                badges=("packet-ready", "hash-backed", "prepare-only") if ready else ("partial", "prepare-only"),
            ),
        )
    if panel.kind is StudioPanelKind.MANUAL_DRIVER_BUILDER:
        return (
            StudioPanelCard(
                title="Manual Proposal Workbench",
                subtitle="Form data becomes deterministic TDDL, then Foundry evidence only.",
                severity="info",
                fields={
                    "field_count": len(manual_builder_form_schema()),
                    "routes_to": "DriverFoundry",
                    "selected_driver_id": state.selected_driver_id,
                    "registry_authority": False,
                    "signing_authority": False,
                    "activation_authority": False,
                },
                badges=("proposal-only", "foundry-routed", "no-keys"),
            ),
        )
    if panel.kind is StudioPanelKind.EVIDENCE_BUNDLE:
        row = dict(panel.rows[0]) if panel.rows else {}
        return (
            StudioPanelCard(
                title=str(row.get("bundle_id") or "Evidence Bundle"),
                subtitle=panel.summary,
                severity=_panel_severity(panel),
                fields=row,
                badges=("read-only", "hash-bound"),
            ),
        )
    if panel.kind is StudioPanelKind.REGISTRY_STATE:
        return (
            StudioPanelCard(
                title="Registry State Observer",
                subtitle="State is rendered only; mutation remains outside Studio.",
                severity="info",
                fields={"row_count": len(panel.rows), "selected_driver_id": state.selected_driver_id, "mutate_registry": False},
                badges=("observe-only",),
            ),
        )
    return ()


def _timeline_for(panel: StudioQtPanelViewModel) -> tuple[StudioTimelineItem, ...]:
    items: list[StudioTimelineItem] = []
    for row in panel.rows:
        if panel.kind is StudioPanelKind.EVIDENCE_TIMELINE:
            stage = str(row.get("stage") or "evidence-ready")
            label = str(row.get("label") or stage.replace("-", " ").title())
            items.append(
                StudioTimelineItem(
                    timestamp=str(row.get("timestamp") or "undated"),
                    label=f"{stage.replace('-', ' ').title()}: {label}",
                    severity=str(row.get("severity") or "info"),
                    actor_id=str(row.get("actor_id") or "studio-evidence"),
                    driver_id=_optional_text(row.get("driver_id")),
                    detail=str(row.get("detail") or ""),
                    source_event_id=str(row.get("source_event_id") or row.get("event_id") or ""),
                )
            )
            continue
        event_type = str(row.get("event_type") or "unknown")
        action = row.get("action")
        label = event_type.replace("_", " ").title()
        if action:
            label = f"{label}: {action}"
        items.append(
            StudioTimelineItem(
                timestamp=str(row.get("timestamp") or "undated"),
                label=label,
                severity=_event_severity(event_type),
                actor_id=str(row.get("actor_id") or "unknown"),
                driver_id=_optional_text(row.get("driver_id")),
                detail=str(row.get("reason") or ""),
                source_event_id=str(row.get("event_id") or ""),
            )
        )
    return tuple(items)


def _actions_for(panel: StudioQtPanelViewModel, *, state: StudioQtShellState) -> tuple[StudioPanelActionDescriptor, ...]:
    if not panel.allows_admin_action_buttons:
        return ()
    selected = bool(state.selected_driver_id)
    approval_enabled = bool(selected and state.ok)
    source = panel.kind
    return (
        StudioPanelActionDescriptor(
            action_id=f"{source.value}.request_approve",
            label="Request Approve",
            requested_action=ReviewAction.APPROVE.value,
            source_panel=source,
            enabled=approval_enabled,
            reason="submits approval intent only; Registry approval/signing/activation remain external" if approval_enabled else "requires selected verified evidence",
        ),
        StudioPanelActionDescriptor(
            action_id=f"{source.value}.request_hold",
            label="Request Hold",
            requested_action=ReviewAction.HOLD.value,
            source_panel=source,
            enabled=selected,
            reason="submits hold intent to the Studio action layer" if selected else "requires selected driver",
        ),
        StudioPanelActionDescriptor(
            action_id=f"{source.value}.request_reject",
            label="Request Reject",
            requested_action=ReviewAction.REJECT.value,
            source_panel=source,
            enabled=selected,
            reason="requires rationale and routes to Review Board; Studio cannot reject by itself" if selected else "requires selected driver",
            requires_rationale=True,
            dangerous=True,
        ),
        StudioPanelActionDescriptor(
            action_id=f"{source.value}.request_quarantine",
            label="Request Quarantine",
            requested_action=ReviewAction.QUARANTINE.value,
            source_panel=source,
            enabled=selected,
            reason="requires rationale and routes to Review Board; Studio cannot quarantine by itself" if selected else "requires selected driver",
            requires_rationale=True,
            dangerous=True,
        ),
    )


def _severity_from_status(status: str) -> str:
    if status == "ready":
        return "success"
    if status == "empty":
        return "muted"
    if status in {"integrity_mismatched", "input_rejected"}:
        return "danger"
    return "warning"


def _panel_severity(panel: StudioQtPanelViewModel) -> str:
    if panel.kind is StudioPanelKind.RISK_CARD and panel.rows:
        first = panel.rows[0]
        return _risk_severity(str(first.get("risk_level", "unknown")), str(first.get("decision_status", "unknown")))
    return _severity_from_status(panel.status)


def _risk_severity(risk_level: str, decision_status: str) -> str:
    lowered_risk = risk_level.lower()
    lowered_status = decision_status.lower()
    if lowered_status in {"rejected", "registry_rejected", "input_rejected"}:
        return "danger"
    if lowered_status in {"held", "quarantined"} or lowered_risk in {"high", "critical"}:
        return "warning"
    if lowered_status in {"approval_ready", "registry_approved"} and lowered_risk in {"low", "bounded", "unknown"}:
        return "success"
    return "info"


def _event_severity(event_type: str) -> str:
    lowered = event_type.lower()
    if any(token in lowered for token in ("reject", "mismatch", "fault", "denied", "quarantine")):
        return "danger"
    if any(token in lowered for token in ("hold", "warning", "manual")):
        return "warning"
    if any(token in lowered for token in ("verified", "approved", "ready", "exported")):
        return "success"
    return "info"


def _empty_hint(kind: StudioPanelKind) -> str:
    hints = {
        StudioPanelKind.DRIVER_QUEUE: "Load an evidence bundle to populate the review queue.",
        StudioPanelKind.EVIDENCE_BUNDLE: "Load a bundle export to view manifest and hash details.",
        StudioPanelKind.AUDIT_TRAIL: "Verified bundle audit events appear here.",
        StudioPanelKind.EVIDENCE_TIMELINE: "Chronological driver lifecycle evidence appears here.",
        StudioPanelKind.FIXTURE_REPLAY: "Select a driver with regression evidence to inspect fixtures.",
        StudioPanelKind.RISK_CARD: "Select a driver to inspect risk and authority boundaries.",
        StudioPanelKind.REGISTRY_STATE: "Registry observations are rendered without mutation authority.",
        StudioPanelKind.EXPORT_INTEGRITY: "Bundle and export packet integrity workflow appears here after load.",
        StudioPanelKind.EXPORT_AUDIT_CONSOLE: "Selected-driver export/audit packet previews appear here.",
        StudioPanelKind.MANUAL_DRIVER_BUILDER: "Use form fields to preview Foundry-routed proposals only.",
        StudioPanelKind.EVENT_CONSOLE: "Audit and Studio events stream here.",
    }
    return hints[kind]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)

"""Pure-Python bridge between Driver Studio backends and the PyQt5 shell.

This bridge is the critical v3.1.14 boundary: Qt widgets may render snapshots and
submit review-action requests, but all trust decisions remain owned by the
Runtime Manager, Review Board, and Registry layers introduced earlier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from staqtapp_tds.drivers.evidence import DriverEvidenceBundle
from staqtapp_tds.drivers.review import ReviewAction
from staqtapp_tds.drivers.studio import (
    DriverStudioConsoleSnapshot,
    DriverStudioReadOnlyConsole,
    StudioPanelKind,
)
from staqtapp_tds.drivers.studio_builder import (
    DriverStudioManualProposalBuilder,
    StudioManualDriverTask,
    StudioManualProposalPreview,
    StudioManualProposalReport,
)
from staqtapp_tds.drivers.studio_actions import (
    DriverStudioAdminReviewActions,
    StudioReviewActionRequest,
    StudioReviewSubmissionReport,
)
from .panels import STUDIO_PANEL_DESCRIPTORS


@dataclass(frozen=True, slots=True)
class StudioQtPanelViewModel:
    """Widget-neutral payload prepared for a PyQt5 panel."""

    kind: StudioPanelKind
    title: str
    icon_name: str
    dock_area: str
    primary_surface: str
    status: str
    summary: str
    rows: tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    allows_admin_action_buttons: bool = False
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class StudioQtShellState:
    """Immutable shell state consumed by optional Qt widgets."""

    ok: bool
    status: str
    reason: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None
    panels: tuple[StudioQtPanelViewModel, ...]
    event_count: int
    capability_matrix: Mapping[str, bool]

    def panel(self, kind: StudioPanelKind | str) -> StudioQtPanelViewModel:
        wanted = kind if isinstance(kind, StudioPanelKind) else StudioPanelKind(str(kind))
        for panel in self.panels:
            if panel.kind is wanted:
                return panel
        raise KeyError(wanted.value)


class StudioQtBridge:
    """Headless bridge for the v3.1.13 Driver Studio PyQt5 cockpit shell."""

    def __init__(
        self,
        *,
        readonly_console: DriverStudioReadOnlyConsole | None = None,
        action_layer: DriverStudioAdminReviewActions | None = None,
        manual_builder: DriverStudioManualProposalBuilder | None = None,
    ) -> None:
        self.readonly_console = readonly_console or DriverStudioReadOnlyConsole()
        self.action_layer = action_layer or DriverStudioAdminReviewActions(readonly_console=self.readonly_console)
        self.manual_builder = manual_builder or DriverStudioManualProposalBuilder()
        self._console: DriverStudioConsoleSnapshot | None = None
        self._source_bundle: DriverEvidenceBundle | Mapping[str, Any] | str | None = None

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the GUI shell authority boundary."""

        return {
            "pyqt5_shell": True,
            "render_cockpit": True,
            "render_svg_iconography": True,
            "render_readonly_panels": True,
            "show_action_buttons": True,
            "render_manual_builder": True,
            "create_manual_builder_ui_runtime": True,
            "preview_manual_driver_proposals": True,
            "route_manual_driver_proposals_to_foundry": True,
            "submit_review_actions": True,
            "route_to_studio_action_layer": True,
            "create_live_event_bridge": True,
            "coordinate_selected_context": True,
            "panel_refresh_contracts": True,
            "create_live_panel_runtime": True,
            "create_review_workflow_console": True,
            "create_evidence_timeline": True,
            "create_risk_intelligence_cards": True,
            "run_visual_quality_review": True,
            "create_manual_builder_ui_runtime": True,
            "create_export_audit_console": True,
            "prepare_export_audit_manifest": True,
            "create_export_integrity_workflow": True,
            "verify_export_packet_integrity": True,
            "load_evidence_bundle": True,
            "verify_export_integrity": True,
            "submit_candidate": False,
            "approve_driver": False,
            "reject_driver": False,
            "quarantine_driver": False,
            "call_registry_approve": False,
            "sign_driver": False,
            "attach_signature": False,
            "activate_driver": False,
            "run_driver_vm": False,
            "edit_tddl": False,
            "edit_bytecode": False,
            "write_storage": False,
            "execute_python": False,
            "mutate_registry": False,
            "store_private_keys": False,
            "bypass_policy": False,
        }

    @property
    def console_snapshot(self) -> DriverStudioConsoleSnapshot | None:
        return self._console

    def load_bundle(
        self,
        bundle: DriverEvidenceBundle | Mapping[str, Any] | str,
        *,
        selected_driver_id: str | None = None,
    ) -> StudioQtShellState:
        """Load an evidence bundle into immutable shell state."""

        self._source_bundle = bundle
        self._console = self.readonly_console.open_bundle(bundle, selected_driver_id=selected_driver_id)
        return self.shell_state()

    def select_driver(self, driver_id: str | None) -> StudioQtShellState:
        """Re-render the current bundle with a selected queue row."""

        if self._source_bundle is None:
            return self.shell_state()
        self._console = self.readonly_console.open_bundle(self._source_bundle, selected_driver_id=driver_id)
        return self.shell_state()

    def shell_state(self) -> StudioQtShellState:
        """Return immutable state even before a bundle has been opened."""

        if self._console is None:
            return StudioQtShellState(
                ok=False,
                status="empty",
                reason="No evidence bundle loaded",
                selected_driver_id=None,
                bundle_id=None,
                bundle_hash=None,
                console_hash=None,
                panels=_empty_panel_view_models(),
                event_count=0,
                capability_matrix=self.capability_matrix(),
            )
        panels = tuple(_panel_view_model(panel) for panel in self._console.panels)
        return StudioQtShellState(
            ok=self._console.ok,
            status=self._console.status.value,
            reason=self._console.reason,
            selected_driver_id=self._console.selected_driver_id,
            bundle_id=self._console.bundle_id,
            bundle_hash=self._console.bundle_hash,
            console_hash=self._console.console_hash,
            panels=panels,
            event_count=len(self._console.event_console),
            capability_matrix=self.capability_matrix(),
        )


    def hydrated_shell_state(self):
        """Return GUI-ready hydrated cockpit state."""

        from .hydration import StudioCockpitHydrator

        return StudioCockpitHydrator().hydrate(self.shell_state())

    def hydrate_panel(self, kind: StudioPanelKind | str):
        """Return one hydrated panel by kind."""

        from .hydration import StudioCockpitHydrator

        state = self.shell_state()
        panel = state.panel(kind)
        return StudioCockpitHydrator().hydrate_panel(panel, state=state)

    def manual_builder_form_schema(self):
        """Return stable form fields for the Manual Driver Builder Qt panel."""

        from .hydration import manual_builder_form_schema

        return manual_builder_form_schema()

    def panel_refresh_contracts(self):
        """Return v3.1.12 refresh contracts for live cockpit panels."""

        from .live import studio_panel_refresh_contracts

        return studio_panel_refresh_contracts()

    def live_event_bridge(self, *, max_events: int = 256):
        """Create a bounded live-event bridge around this Studio bridge."""

        from .live import StudioCockpitEventBridge

        return StudioCockpitEventBridge(bridge=self, max_events=max_events)

    def live_panel_runtime(self, *, max_events: int = 256):
        """Create a v3.1.13 live panel runtime around this Studio bridge."""

        from .runtime import StudioLivePanelRuntime

        return StudioLivePanelRuntime(event_bridge=self.live_event_bridge(max_events=max_events))

    def review_workflow_console(self, *, max_events: int = 256):
        """Create a v3.1.14 Review Workflow Console around this Studio bridge."""

        from .review_workflow import StudioReviewWorkflowConsole

        return StudioReviewWorkflowConsole(runtime=self.live_panel_runtime(max_events=max_events))

    def evidence_timeline(self, *, max_events: int = 256):
        """Create a v3.1.16 Evidence Timeline around this Studio bridge."""

        from .evidence_timeline import StudioEvidenceTimeline

        return StudioEvidenceTimeline(runtime=self.live_panel_runtime(max_events=max_events))

    def risk_intelligence_cards(self, *, max_events: int = 256):
        """Create v3.1.16 Risk Intelligence Cards around this Studio bridge."""

        from .risk_intelligence import StudioRiskIntelligenceCards

        return StudioRiskIntelligenceCards(runtime=self.live_panel_runtime(max_events=max_events))

    def manual_builder_ui_runtime(self, *, max_events: int = 256):
        """Create the v3.1.18 Manual Builder UI Runtime around this bridge."""

        from .manual_builder_runtime import StudioManualBuilderUIRuntime

        return StudioManualBuilderUIRuntime(bridge=self)


    def export_audit_console(self, *, max_events: int = 256):
        """Create the v3.1.20 Export / Audit Console around this bridge."""

        from .export_audit import StudioExportAuditConsole

        return StudioExportAuditConsole(runtime=self.live_panel_runtime(max_events=max_events))

    def export_integrity_workflow(self, *, max_events: int = 256):
        """Create the v3.1.20 Export Integrity Workflow around this bridge."""

        from .export_integrity_workflow import StudioExportIntegrityWorkflow

        return StudioExportIntegrityWorkflow(runtime=self.live_panel_runtime(max_events=max_events))


    def visual_quality_review(self):
        """Run the v3.1.18 static PyQt5 cockpit visual-quality review."""

        from .manual_builder_runtime import studio_qt_visual_quality_review

        return studio_qt_visual_quality_review()

    def build_action_request(
        self,
        driver_id: str,
        action: ReviewAction | str,
        *,
        reviewer_id: str = "studio-admin",
        rationale: str = "",
        source_panel: StudioPanelKind | str = StudioPanelKind.DRIVER_QUEUE,
        tags: Sequence[str] = (),
    ) -> StudioReviewActionRequest:
        """Create the safe request object used by action buttons."""

        return StudioReviewActionRequest(
            driver_id=driver_id,
            requested_action=action,
            reviewer_id=reviewer_id,
            rationale=rationale,
            source_panel=source_panel.value if isinstance(source_panel, StudioPanelKind) else str(source_panel),
            tags=tuple(str(tag) for tag in tags),
        )

    def submit_review_action(
        self,
        request: StudioReviewActionRequest | Mapping[str, Any],
        *,
        submitted_at: str = "undated",
    ) -> StudioReviewSubmissionReport:
        """Record an action through v3.1.8; does not route authority by default."""

        if self._console is None:
            raise RuntimeError("cannot submit Studio review action before an evidence bundle is loaded")
        return self.action_layer.submit_actions(self._console, (request,), submitted_at=submitted_at)

    def preview_manual_driver_task(self, task: StudioManualDriverTask) -> StudioManualProposalPreview:
        """Render a manual-builder proposal preview without trust authority."""

        return self.manual_builder.preview_task(task)

    def propose_manual_driver_task(
        self,
        task: StudioManualDriverTask,
        *,
        fixtures: Mapping[str, Any] | None = None,
    ) -> StudioManualProposalReport:
        """Route a cockpit-built driver task through Driver Foundry only."""

        return self.manual_builder.propose_task(task, fixtures=fixtures)

    # Deliberately no approve/sign/activate/execute helpers on this bridge.


def _panel_view_model(panel: Any) -> StudioQtPanelViewModel:
    descriptor = STUDIO_PANEL_DESCRIPTORS[panel.kind]
    return StudioQtPanelViewModel(
        kind=panel.kind,
        title=descriptor.title,
        icon_name=descriptor.icon_name,
        dock_area=descriptor.dock_area,
        primary_surface=descriptor.primary_surface,
        status=panel.status.value,
        summary=panel.summary,
        rows=tuple(dict(row) for row in panel.rows),
        metrics=dict(panel.metrics),
        warnings=tuple(panel.warnings),
        allows_admin_action_buttons=descriptor.allows_admin_action_buttons,
        read_only=descriptor.read_only,
    )


def _empty_panel_view_models() -> tuple[StudioQtPanelViewModel, ...]:
    empty = []
    for descriptor in STUDIO_PANEL_DESCRIPTORS.values():
        empty.append(
            StudioQtPanelViewModel(
                kind=descriptor.kind,
                title=descriptor.title,
                icon_name=descriptor.icon_name,
                dock_area=descriptor.dock_area,
                primary_surface=descriptor.primary_surface,
                status="empty",
                summary="No evidence bundle loaded",
                allows_admin_action_buttons=descriptor.allows_admin_action_buttons,
                read_only=descriptor.read_only,
            )
        )
    return tuple(empty)


def studio_pyqt5_shell_capability_matrix() -> Mapping[str, bool]:
    """Convenience function for rendering shell authority boundaries."""

    return StudioQtBridge().capability_matrix()

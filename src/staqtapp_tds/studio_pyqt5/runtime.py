"""Live panel runtime for the optional Driver Studio PyQt5 cockpit.

v3.1.13 sits above the v3.1.12 live event bridge and turns retained live
cockpit events into deterministic panel refresh packets.  The runtime is a GUI
coordination layer only: it marks panels dirty, hydrates immutable snapshots,
and emits Qt-friendly payloads.  It never approves, signs, activates, executes
trusted drivers, mutates Registry state, writes storage, stores private keys, or
bypasses Runtime Manager / Foundry / Review Board policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from staqtapp_tds.drivers.evidence import DriverEvidenceBundle
from staqtapp_tds.drivers.review import ReviewAction
from staqtapp_tds.drivers.studio import StudioPanelKind
from staqtapp_tds.drivers.studio_builder import (
    StudioManualDriverTask,
    StudioManualProposalPreview,
    StudioManualProposalReport,
)
from staqtapp_tds.drivers.studio_actions import StudioReviewActionRequest, StudioReviewSubmissionReport
from .hydration import StudioHydratedPanel
from .live import (
    StudioCockpitEventBridge,
    StudioCockpitSelection,
    StudioLiveCockpitState,
    StudioLiveEvent,
    StudioLiveEventKind,
    StudioPanelRefreshContract,
    studio_panel_refresh_contracts,
)


@dataclass(frozen=True, slots=True)
class StudioPanelDirtyMark:
    """One reason that a cockpit panel should refresh.

    The mark is derived from live events and refresh contracts.  It is not a
    backend mutation request and it carries no trust authority.
    """

    panel_kind: StudioPanelKind
    reason_event_id: str
    reason_event_kind: StudioLiveEventKind
    refresh_mode: str
    debounce_ms: int
    depends_on_selection: bool
    authority: str
    severity: str = "info"

    def as_row(self) -> Mapping[str, Any]:
        return {
            "panel_kind": self.panel_kind.value,
            "reason_event_id": self.reason_event_id,
            "reason_event_kind": self.reason_event_kind.value,
            "refresh_mode": self.refresh_mode,
            "debounce_ms": self.debounce_ms,
            "depends_on_selection": self.depends_on_selection,
            "authority": self.authority,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class StudioPanelRefreshPacket:
    """Qt-ready immutable panel refresh payload.

    It wraps a hydrated panel with the live generation/cursor and dirty reasons
    that caused the panel to be refreshed.
    """

    panel: StudioHydratedPanel
    generation: int
    cursor: int
    selection: StudioCockpitSelection
    reason_event_ids: tuple[str, ...]
    refresh_mode: str
    debounce_ms: int
    authority: str
    dirty: bool = True
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> StudioPanelKind:
        return self.panel.kind

    def signal_payload(self) -> Mapping[str, Any]:
        """Return compact JSON-friendly data for Qt signals/model updates."""

        return {
            "panel_kind": self.panel.kind.value,
            "title": self.panel.title,
            "status": self.panel.status,
            "severity": self.panel.severity,
            "generation": self.generation,
            "cursor": self.cursor,
            "selected_driver_id": self.selection.selected_driver_id,
            "bundle_id": self.selection.bundle_id,
            "bundle_hash": self.selection.bundle_hash,
            "console_hash": self.selection.console_hash,
            "dirty": self.dirty,
            "reason_event_ids": self.reason_event_ids,
            "refresh_mode": self.refresh_mode,
            "debounce_ms": self.debounce_ms,
            "authority": self.authority,
            "row_count": len(self.panel.rows),
            "card_count": len(self.panel.cards),
            "timeline_count": len(self.panel.timeline),
            "action_count": len(self.panel.actions),
            "form_field_count": len(self.panel.form_fields),
            "warnings": tuple(self.panel.warnings),
            "metrics": dict(self.panel.metrics),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class StudioPanelRuntimeState:
    """Complete state produced by the live panel runtime."""

    generation: int
    cursor: int
    consumed_cursor: int
    selection: StudioCockpitSelection
    events: tuple[StudioLiveEvent, ...]
    dirty_marks: tuple[StudioPanelDirtyMark, ...]
    refresh_packets: tuple[StudioPanelRefreshPacket, ...]
    live_state: StudioLiveCockpitState
    capability_matrix: Mapping[str, bool]
    event_retention_gap: bool = False
    dropped_event_count: int = 0
    runtime_warnings: tuple[str, ...] = ()

    @property
    def dirty_panel_kinds(self) -> tuple[StudioPanelKind, ...]:
        seen: set[StudioPanelKind] = set()
        ordered: list[StudioPanelKind] = []
        for mark in self.dirty_marks:
            if mark.panel_kind not in seen:
                seen.add(mark.panel_kind)
                ordered.append(mark.panel_kind)
        return tuple(ordered)

    def packet(self, kind: StudioPanelKind | str) -> StudioPanelRefreshPacket:
        wanted = kind if isinstance(kind, StudioPanelKind) else StudioPanelKind(str(kind))
        for packet in self.refresh_packets:
            if packet.panel.kind is wanted:
                return packet
        raise KeyError(wanted.value)

    def signal_payload(self) -> Mapping[str, Any]:
        """Return compact state for one Qt signal emission."""

        return {
            "generation": self.generation,
            "cursor": self.cursor,
            "consumed_cursor": self.consumed_cursor,
            "selected_driver_id": self.selection.selected_driver_id,
            "bundle_id": self.selection.bundle_id,
            "bundle_hash": self.selection.bundle_hash,
            "console_hash": self.selection.console_hash,
            "event_count": len(self.events),
            "event_retention_gap": self.event_retention_gap,
            "dropped_event_count": self.dropped_event_count,
            "runtime_warnings": self.runtime_warnings,
            "dirty_panel_kinds": tuple(kind.value for kind in self.dirty_panel_kinds),
            "refresh_packet_count": len(self.refresh_packets),
            "refresh_packets": tuple(packet.signal_payload() for packet in self.refresh_packets),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioLivePanelRuntime:
    """Coordinate live events into refreshed hydrated cockpit panels.

    The runtime may be polled from a PyQt5 timer or connected to Qt signals by a
    thin GUI wrapper.  It tracks the last consumed cursor so callers can ask for
    only newly dirty panels after each live bridge operation.
    """

    def __init__(
        self,
        *,
        event_bridge: StudioCockpitEventBridge | None = None,
        max_events: int = 256,
        contracts: Sequence[StudioPanelRefreshContract] | None = None,
    ) -> None:
        self.event_bridge = event_bridge or StudioCockpitEventBridge(max_events=max_events)
        self.contracts = tuple(contracts) if contracts is not None else studio_panel_refresh_contracts()
        self._last_consumed_cursor = 0

    @property
    def cursor(self) -> int:
        return self.event_bridge.cursor

    @property
    def consumed_cursor(self) -> int:
        return self._last_consumed_cursor

    def capability_matrix(self) -> Mapping[str, bool]:
        matrix = dict(self.event_bridge.capability_matrix())
        matrix.update(
            {
                "live_panel_runtime": True,
                "create_review_workflow_console": True,
                "create_evidence_timeline": True,
                "create_risk_intelligence_cards": True,
                "create_manual_builder_ui_runtime": True,
                "create_export_audit_console": True,
                "create_export_integrity_workflow": True,
                "verify_export_packet_integrity": True,
                "dirty_panel_tracking": True,
                "panel_refresh_packets": True,
                "qt_model_update_payloads": True,
                "event_to_panel_routing": True,
                "selection_aware_panel_refresh": True,
                "consume_incremental_events": True,
                "detect_event_retention_gap": True,
                "runtime_warning_payloads": True,
                "live_runtime_mutates_backend": False,
                "submit_candidate": False,
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
        )
        return matrix

    def current_state(self, *, include_packets: bool = False) -> StudioPanelRuntimeState:
        """Return current runtime state without advancing the consumed cursor."""

        live_state = self.event_bridge.current_state()
        events = live_state.events_since(self._last_consumed_cursor)
        retention_gap = live_state.has_retention_gap_since(self._last_consumed_cursor)
        dirty = self.plan_refresh(events)
        packets = self.refresh_packets(dirty, live_state=live_state) if include_packets else ()
        return StudioPanelRuntimeState(
            generation=live_state.generation,
            cursor=live_state.cursor,
            consumed_cursor=self._last_consumed_cursor,
            selection=live_state.selection,
            events=events,
            dirty_marks=dirty,
            refresh_packets=packets,
            live_state=live_state,
            capability_matrix=self.capability_matrix(),
            event_retention_gap=retention_gap,
            dropped_event_count=live_state.dropped_event_count,
            runtime_warnings=_runtime_warnings(retention_gap=retention_gap),
        )

    def consume(self, *, include_packets: bool = True) -> StudioPanelRuntimeState:
        """Consume newly retained events and advance the runtime cursor."""

        state = self.current_state(include_packets=include_packets)
        self._last_consumed_cursor = state.cursor
        return state

    def mark_all_dirty(self, *, reason: str = "initial runtime hydration") -> StudioPanelRuntimeState:
        """Emit a snapshot refresh and return refresh packets for every panel."""

        self.event_bridge.refresh(reason=reason)
        live_state = self.event_bridge.current_state()
        event = live_state.events[-1] if live_state.events else StudioLiveEvent(
            event_id="live-000000",
            kind=StudioLiveEventKind.SNAPSHOT_REFRESH,
            timestamp="undated",
            source="studio_live_panel_runtime",
            message=reason,
        )
        dirty = tuple(
            StudioPanelDirtyMark(
                panel_kind=contract.kind,
                reason_event_id=event.event_id,
                reason_event_kind=event.kind,
                refresh_mode=contract.refresh_mode,
                debounce_ms=contract.debounce_ms,
                depends_on_selection=contract.depends_on_selection,
                authority=contract.authority,
                severity=event.severity,
            )
            for contract in self.contracts
        )
        packets = self.refresh_packets(dirty, live_state=live_state)
        retention_gap = live_state.has_retention_gap_since(self._last_consumed_cursor)
        state = StudioPanelRuntimeState(
            generation=live_state.generation,
            cursor=live_state.cursor,
            consumed_cursor=self._last_consumed_cursor,
            selection=live_state.selection,
            events=live_state.events_since(self._last_consumed_cursor),
            dirty_marks=dirty,
            refresh_packets=packets,
            live_state=live_state,
            capability_matrix=self.capability_matrix(),
            event_retention_gap=retention_gap,
            dropped_event_count=live_state.dropped_event_count,
            runtime_warnings=_runtime_warnings(retention_gap=retention_gap),
        )
        self._last_consumed_cursor = state.cursor
        return state

    def plan_refresh(self, events: Sequence[StudioLiveEvent]) -> tuple[StudioPanelDirtyMark, ...]:
        """Map live events to deterministic panel dirty marks."""

        marks: list[StudioPanelDirtyMark] = []
        for event in events:
            for contract in self.contracts:
                if event.kind in contract.event_kinds:
                    marks.append(
                        StudioPanelDirtyMark(
                            panel_kind=contract.kind,
                            reason_event_id=event.event_id,
                            reason_event_kind=event.kind,
                            refresh_mode=contract.refresh_mode,
                            debounce_ms=contract.debounce_ms,
                            depends_on_selection=contract.depends_on_selection,
                            authority=contract.authority,
                            severity=event.severity,
                        )
                    )
        return tuple(marks)

    def refresh_packets(
        self,
        dirty_marks: Sequence[StudioPanelDirtyMark],
        *,
        live_state: StudioLiveCockpitState | None = None,
    ) -> tuple[StudioPanelRefreshPacket, ...]:
        """Hydrate each dirty panel once and preserve its dirty reasons."""

        live_state = live_state or self.event_bridge.current_state()
        grouped: dict[StudioPanelKind, list[StudioPanelDirtyMark]] = {}
        for mark in dirty_marks:
            grouped.setdefault(mark.panel_kind, []).append(mark)

        packets: list[StudioPanelRefreshPacket] = []
        for kind in _panel_order(grouped.keys()):
            marks = tuple(grouped[kind])
            panel = live_state.panel(kind)
            contract = _contract_for(kind, self.contracts)
            packets.append(
                StudioPanelRefreshPacket(
                    panel=panel,
                    generation=live_state.generation,
                    cursor=live_state.cursor,
                    selection=live_state.selection,
                    reason_event_ids=tuple(mark.reason_event_id for mark in marks),
                    refresh_mode=contract.refresh_mode,
                    debounce_ms=contract.debounce_ms,
                    authority=contract.authority,
                    dirty=True,
                    payload={
                        "reason_event_kinds": tuple(mark.reason_event_kind.value for mark in marks),
                        "depends_on_selection": contract.depends_on_selection,
                        "mutable_backend": contract.mutable_backend,
                    },
                )
            )
        return tuple(packets)

    # Delegating operations below preserve the v3.1.12 bridge authority model and
    # then expose consumed panel refresh packets for GUI code.

    def load_bundle(
        self,
        bundle: DriverEvidenceBundle | Mapping[str, Any] | str,
        *,
        selected_driver_id: str | None = None,
        timestamp: str = "undated",
    ) -> StudioPanelRuntimeState:
        self.event_bridge.load_bundle(bundle, selected_driver_id=selected_driver_id, timestamp=timestamp)
        return self.consume(include_packets=True)

    def select_driver(self, driver_id: str | None, *, timestamp: str = "undated") -> StudioPanelRuntimeState:
        self.event_bridge.select_driver(driver_id, timestamp=timestamp)
        return self.consume(include_packets=True)

    def refresh(self, *, reason: str = "manual refresh", timestamp: str = "undated") -> StudioPanelRuntimeState:
        self.event_bridge.refresh(reason=reason, timestamp=timestamp)
        return self.consume(include_packets=True)

    def refresh_panel(self, kind: StudioPanelKind | str, *, timestamp: str = "undated") -> StudioPanelRuntimeState:
        self.event_bridge.refresh_panel(kind, timestamp=timestamp)
        return self.consume(include_packets=True)

    def submit_review_action(
        self,
        request: StudioReviewActionRequest | Mapping[str, Any],
        *,
        submitted_at: str = "undated",
    ) -> tuple[StudioReviewSubmissionReport, StudioPanelRuntimeState]:
        report = self.event_bridge.submit_review_action(request, submitted_at=submitted_at)
        return report, self.consume(include_packets=True)

    def preview_manual_driver_task(
        self,
        task: StudioManualDriverTask,
        *,
        timestamp: str = "undated",
    ) -> tuple[StudioManualProposalPreview, StudioPanelRuntimeState]:
        preview = self.event_bridge.preview_manual_driver_task(task, timestamp=timestamp)
        return preview, self.consume(include_packets=True)

    def propose_manual_driver_task(
        self,
        task: StudioManualDriverTask,
        *,
        fixtures: Mapping[str, Any] | None = None,
        timestamp: str = "undated",
    ) -> tuple[StudioManualProposalReport, StudioPanelRuntimeState]:
        report = self.event_bridge.propose_manual_driver_task(task, fixtures=fixtures, timestamp=timestamp)
        return report, self.consume(include_packets=True)

    def risk_intelligence_cards(self):
        """Create v3.1.16 Risk Intelligence Cards on this live runtime."""

        from .risk_intelligence import StudioRiskIntelligenceCards

        return StudioRiskIntelligenceCards(runtime=self)

    def visual_quality_review(self):
        """Run the v3.1.18 static PyQt5 cockpit visual-quality review."""

        from .manual_builder_runtime import studio_qt_visual_quality_review

        return studio_qt_visual_quality_review()

    def signal_payload(self) -> Mapping[str, Any]:
        """Return the current unconsumed runtime state as a Qt-friendly payload."""

        return self.current_state(include_packets=True).signal_payload()

    def manual_builder_ui_runtime(self):
        """Create the v3.1.18 Manual Builder UI Runtime on this live runtime."""

        from .manual_builder_runtime import StudioManualBuilderUIRuntime

        return StudioManualBuilderUIRuntime(bridge=self.event_bridge.bridge)

    def review_workflow_console(self):
        """Create a v3.1.14 Review Workflow Console on this live runtime."""

        from .review_workflow import StudioReviewWorkflowConsole

        return StudioReviewWorkflowConsole(runtime=self)

    def evidence_timeline(self):
        """Create a v3.1.16 Evidence Timeline on this live runtime."""

        from .evidence_timeline import StudioEvidenceTimeline

        return StudioEvidenceTimeline(runtime=self)


    def export_audit_console(self):
        """Create a v3.1.20 Export / Audit Console on this live runtime."""

        from .export_audit import StudioExportAuditConsole

        return StudioExportAuditConsole(runtime=self)

    def export_integrity_workflow(self):
        """Create a v3.1.20 Export Integrity Workflow on this live runtime."""

        from .export_integrity_workflow import StudioExportIntegrityWorkflow

        return StudioExportIntegrityWorkflow(runtime=self)


def _runtime_warnings(*, retention_gap: bool) -> tuple[str, ...]:
    if not retention_gap:
        return ()
    return ("live event retention gap detected; older events were dropped before runtime consumption",)


def studio_live_panel_runtime_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying v3.1.13 runtime boundaries."""

    return StudioLivePanelRuntime().capability_matrix()


def _contract_for(kind: StudioPanelKind, contracts: Sequence[StudioPanelRefreshContract]) -> StudioPanelRefreshContract:
    for contract in contracts:
        if contract.kind is kind:
            return contract
    raise KeyError(kind.value)


def _panel_order(kinds: Sequence[StudioPanelKind] | set[StudioPanelKind]) -> tuple[StudioPanelKind, ...]:
    wanted = set(kinds)
    return tuple(kind for kind in StudioPanelKind if kind in wanted)

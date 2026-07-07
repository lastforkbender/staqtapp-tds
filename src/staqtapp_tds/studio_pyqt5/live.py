"""Live event bridge for the optional Driver Studio PyQt5 cockpit.

v3.1.12 adds a bounded, GUI-neutral event stream above the v3.1.11
hydration layer.  The bridge coordinates snapshot refreshes, selected-driver
state, selected-bundle state, and panel refresh contracts for a real Qt
cockpit.  It deliberately remains a rendering/coordination layer: it does not
approve, sign, activate, execute drivers, mutate Registry state, write storage,
hold private keys, or bypass policy.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from enum import Enum
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
from .bridge import StudioQtBridge
from .hydration import StudioHydratedCockpitState, StudioHydratedPanel


class StudioLiveEventKind(str, Enum):
    """Stable event kinds emitted by the live cockpit bridge."""

    SNAPSHOT_REFRESH = "snapshot_refresh"
    BUNDLE_LOADED = "bundle_loaded"
    DRIVER_SELECTED = "driver_selected"
    PANEL_REFRESHED = "panel_refreshed"
    REVIEW_ACTION_SUBMITTED = "review_action_submitted"
    MANUAL_PROPOSAL_PREVIEWED = "manual_proposal_previewed"
    MANUAL_PROPOSAL_SUBMITTED = "manual_proposal_submitted"


@dataclass(frozen=True, slots=True)
class StudioLiveEvent:
    """One bounded event-console item for the PyQt5 live bridge."""

    event_id: str
    kind: StudioLiveEventKind
    timestamp: str
    source: str
    message: str
    severity: str = "info"
    driver_id: str | None = None
    bundle_id: str | None = None
    console_hash: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_row(self) -> Mapping[str, Any]:
        """Return a compact row suitable for Qt table/list models."""

        return {
            "event_id": self.event_id,
            "event_type": self.kind.value,
            "timestamp": self.timestamp,
            "source": self.source,
            "severity": self.severity,
            "driver_id": self.driver_id,
            "bundle_id": self.bundle_id,
            "console_hash": self.console_hash,
            "message": self.message,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class StudioCockpitSelection:
    """Selected bundle/driver identity coordinated across Studio panels."""

    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None


@dataclass(frozen=True, slots=True)
class StudioPanelRefreshContract:
    """Refresh policy metadata for one cockpit panel.

    This is a UI contract only.  It tells a Qt shell when a panel should refresh
    from a new immutable snapshot.  It never grants mutation or trust authority.
    """

    kind: StudioPanelKind
    refresh_mode: str
    debounce_ms: int
    depends_on_selection: bool
    event_kinds: tuple[StudioLiveEventKind, ...]
    mutable_backend: bool = False
    authority: str = "observe_only"


@dataclass(frozen=True, slots=True)
class StudioLiveCockpitState:
    """Complete live-state payload consumed by a PyQt5 shell."""

    generation: int
    cursor: int
    hydrated: StudioHydratedCockpitState
    selection: StudioCockpitSelection
    events: tuple[StudioLiveEvent, ...]
    refresh_contracts: tuple[StudioPanelRefreshContract, ...]
    capability_matrix: Mapping[str, bool]
    retained_cursor_floor: int = 0
    dropped_event_count: int = 0

    @property
    def event_retention_gap(self) -> bool:
        """Whether the retained stream has dropped earlier live events."""

        return self.dropped_event_count > 0

    @property
    def latest_event_id(self) -> str | None:
        return self.events[-1].event_id if self.events else None

    def panel(self, kind: StudioPanelKind | str) -> StudioHydratedPanel:
        return self.hydrated.panel(kind)

    def events_since(self, cursor: int) -> tuple[StudioLiveEvent, ...]:
        """Return retained events with sequence numbers above ``cursor``."""

        return tuple(event for event in self.events if _event_sequence(event.event_id) > int(cursor))

    def has_retention_gap_since(self, cursor: int) -> bool:
        """Return True when older events were dropped before ``cursor`` caught up."""

        if not self.events:
            return False
        return int(cursor) < self.retained_cursor_floor - 1

    def signal_payload(self) -> Mapping[str, Any]:
        """Return JSON-friendly payload data for Qt signal emission."""

        return {
            "generation": self.generation,
            "cursor": self.cursor,
            "status": self.hydrated.status,
            "severity": self.hydrated.severity,
            "selected_driver_id": self.selection.selected_driver_id,
            "bundle_id": self.selection.bundle_id,
            "bundle_hash": self.selection.bundle_hash,
            "console_hash": self.selection.console_hash,
            "event_count": len(self.events),
            "latest_event_id": self.latest_event_id,
            "retained_cursor_floor": self.retained_cursor_floor,
            "dropped_event_count": self.dropped_event_count,
            "event_retention_gap": self.event_retention_gap,
            "panel_status": {panel.kind.value: panel.status for panel in self.hydrated.panels},
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioCockpitEventBridge:
    """Bounded live-update bridge for the Driver Studio cockpit.

    The object wraps ``StudioQtBridge`` and emits immutable state changes that a
    PyQt5 shell can poll or forward through signals.  All backend actions still
    route through the existing bridge, Foundry, and review-action layer.
    """

    def __init__(self, *, bridge: StudioQtBridge | None = None, max_events: int = 256) -> None:
        if int(max_events) < 1:
            raise ValueError("max_events must be >= 1")
        self.bridge = bridge or StudioQtBridge()
        self.max_events = int(max_events)
        self._events: deque[StudioLiveEvent] = deque(maxlen=self.max_events)
        self._sequence = 0
        self._generation = 0
        self._dropped_event_count = 0

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def cursor(self) -> int:
        return self._sequence

    @property
    def events(self) -> tuple[StudioLiveEvent, ...]:
        return tuple(self._events)

    @property
    def dropped_event_count(self) -> int:
        return self._dropped_event_count

    @property
    def retained_cursor_floor(self) -> int:
        if not self._events:
            return self._sequence
        return _event_sequence(self._events[0].event_id)

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return live-bridge capabilities and denied authority."""

        matrix = dict(self.bridge.capability_matrix())
        matrix.update(
            {
                "live_cockpit_event_bridge": True,
                "bounded_event_stream": True,
                "snapshot_refresh_semantics": True,
                "coordinate_selected_context": True,
                "panel_refresh_contracts": True,
                "emit_qt_signal_payloads": True,
                "timeline_refresh_contracts": True,
                "risk_intelligence_refresh_contracts": True,
                "manual_builder_ui_runtime_events": True,
                "export_audit_console_refresh_contracts": True,
                "export_integrity_workflow_state": True,
                "safe_polling_bridge": True,
                "detect_event_retention_gap": True,
                "event_stream_drop_accounting": True,
                "live_bridge_mutates_backend": False,
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

    def current_state(self) -> StudioLiveCockpitState:
        """Return current hydrated live state without recording a new event."""

        hydrated = self.bridge.hydrated_shell_state()
        return StudioLiveCockpitState(
            generation=self._generation,
            cursor=self._sequence,
            hydrated=hydrated,
            selection=StudioCockpitSelection(
                selected_driver_id=hydrated.selected_driver_id,
                bundle_id=hydrated.bundle_id,
                bundle_hash=hydrated.bundle_hash,
                console_hash=hydrated.console_hash,
            ),
            events=tuple(self._events),
            refresh_contracts=studio_panel_refresh_contracts(),
            capability_matrix=self.capability_matrix(),
            retained_cursor_floor=self.retained_cursor_floor,
            dropped_event_count=self._dropped_event_count,
        )

    def refresh(self, *, reason: str = "manual refresh", timestamp: str = "undated") -> StudioLiveCockpitState:
        """Emit a snapshot-refresh event and return the hydrated state."""

        state = self.bridge.hydrated_shell_state()
        self._record_event(
            StudioLiveEventKind.SNAPSHOT_REFRESH,
            timestamp=timestamp,
            source="studio_live_bridge",
            message=reason,
            severity=state.severity,
            driver_id=state.selected_driver_id,
            bundle_id=state.bundle_id,
            console_hash=state.console_hash,
            payload={"status": state.status, "panel_count": len(state.panels)},
        )
        return self.current_state()

    def load_bundle(
        self,
        bundle: DriverEvidenceBundle | Mapping[str, Any] | str,
        *,
        selected_driver_id: str | None = None,
        timestamp: str = "undated",
    ) -> StudioLiveCockpitState:
        """Load a bundle through StudioQtBridge and record a safe UI event."""

        shell = self.bridge.load_bundle(bundle, selected_driver_id=selected_driver_id)
        self._record_event(
            StudioLiveEventKind.BUNDLE_LOADED,
            timestamp=timestamp,
            source="studio_qt_bridge",
            message="evidence bundle loaded into Driver Studio cockpit",
            severity="success" if shell.ok else "warning",
            driver_id=shell.selected_driver_id,
            bundle_id=shell.bundle_id,
            console_hash=shell.console_hash,
            payload={"status": shell.status, "event_count": shell.event_count},
        )
        return self.current_state()

    def select_driver(self, driver_id: str | None, *, timestamp: str = "undated") -> StudioLiveCockpitState:
        """Re-render selection through the bridge and record selected context."""

        shell = self.bridge.select_driver(driver_id)
        self._record_event(
            StudioLiveEventKind.DRIVER_SELECTED,
            timestamp=timestamp,
            source="studio_qt_bridge",
            message="selected driver context changed" if driver_id else "driver selection cleared",
            severity="info" if shell.status != "empty" else "muted",
            driver_id=shell.selected_driver_id,
            bundle_id=shell.bundle_id,
            console_hash=shell.console_hash,
            payload={"requested_driver_id": driver_id, "status": shell.status},
        )
        return self.current_state()

    def refresh_panel(self, kind: StudioPanelKind | str, *, timestamp: str = "undated") -> StudioHydratedPanel:
        """Hydrate one panel and record a panel-refresh event."""

        resolved = kind if isinstance(kind, StudioPanelKind) else StudioPanelKind(str(kind))
        panel = self.bridge.hydrate_panel(resolved)
        shell = self.bridge.shell_state()
        self._record_event(
            StudioLiveEventKind.PANEL_REFRESHED,
            timestamp=timestamp,
            source="studio_cockpit_hydrator",
            message=f"panel refreshed: {resolved.value}",
            severity=panel.severity,
            driver_id=shell.selected_driver_id,
            bundle_id=shell.bundle_id,
            console_hash=shell.console_hash,
            payload={"panel": resolved.value, "status": panel.status},
        )
        return panel

    def submit_review_action(
        self,
        request: StudioReviewActionRequest | Mapping[str, Any],
        *,
        submitted_at: str = "undated",
    ) -> StudioReviewSubmissionReport:
        """Submit review intent through the existing action layer and emit an event."""

        report = self.bridge.submit_review_action(request, submitted_at=submitted_at)
        shell = self.bridge.shell_state()
        action = _request_action_value(request)
        self._record_event(
            StudioLiveEventKind.REVIEW_ACTION_SUBMITTED,
            timestamp=submitted_at,
            source="studio_action_layer",
            message=f"review intent submitted: {action}",
            severity="success" if report.ok else "warning",
            driver_id=_request_driver_id(request) or shell.selected_driver_id,
            bundle_id=shell.bundle_id,
            console_hash=shell.console_hash,
            payload={"ok": report.ok, "decision_count": len(report.decisions), "action": action},
        )
        return report

    def preview_manual_driver_task(
        self,
        task: StudioManualDriverTask,
        *,
        timestamp: str = "undated",
    ) -> StudioManualProposalPreview:
        """Preview a manual task and emit a proposal-preview event."""

        preview = self.bridge.preview_manual_driver_task(task)
        shell = self.bridge.shell_state()
        self._record_event(
            StudioLiveEventKind.MANUAL_PROPOSAL_PREVIEWED,
            timestamp=timestamp,
            source="manual_driver_builder",
            message="manual driver proposal previewed" if preview.ok else "manual driver proposal rejected during preview",
            severity="success" if preview.ok else "danger",
            driver_id=task.driver_id if preview.ok else None,
            bundle_id=shell.bundle_id,
            console_hash=shell.console_hash,
            payload={"ok": preview.ok, "source_hash": preview.source_hash, "status": preview.status.value},
        )
        return preview

    def propose_manual_driver_task(
        self,
        task: StudioManualDriverTask,
        *,
        fixtures: Mapping[str, Any] | None = None,
        timestamp: str = "undated",
    ) -> StudioManualProposalReport:
        """Route manual task through Foundry and emit a proposal event."""

        report = self.bridge.propose_manual_driver_task(task, fixtures=fixtures)
        shell = self.bridge.shell_state()
        self._record_event(
            StudioLiveEventKind.MANUAL_PROPOSAL_SUBMITTED,
            timestamp=timestamp,
            source="driver_foundry",
            message="manual proposal routed through Foundry" if report.ok else "manual proposal failed before trust authority",
            severity="success" if report.ok else "warning",
            driver_id=report.task.driver_id if report.task is not None else task.driver_id,
            bundle_id=shell.bundle_id,
            console_hash=shell.console_hash,
            payload={"ok": report.ok, "source_hash": report.source_hash, "status": report.status.value},
        )
        return report

    def events_since(self, cursor: int) -> tuple[StudioLiveEvent, ...]:
        """Return retained live events after cursor."""

        return self.current_state().events_since(cursor)

    def signal_payload(self) -> Mapping[str, Any]:
        """Return current state as a compact Qt-signal-friendly mapping."""

        return self.current_state().signal_payload()

    def _record_event(
        self,
        kind: StudioLiveEventKind,
        *,
        timestamp: str,
        source: str,
        message: str,
        severity: str,
        driver_id: str | None,
        bundle_id: str | None,
        console_hash: str | None,
        payload: Mapping[str, Any] | None = None,
    ) -> StudioLiveEvent:
        if len(self._events) == self.max_events:
            self._dropped_event_count += 1
        self._sequence += 1
        self._generation += 1
        event = StudioLiveEvent(
            event_id=f"live-{self._sequence:06d}",
            kind=kind,
            timestamp=str(timestamp),
            source=str(source),
            message=str(message),
            severity=str(severity),
            driver_id=driver_id,
            bundle_id=bundle_id,
            console_hash=console_hash,
            payload=dict(payload or {}),
        )
        self._events.append(event)
        return event


_REFRESH_CONTRACTS: Mapping[StudioPanelKind, StudioPanelRefreshContract] = {
    StudioPanelKind.DRIVER_QUEUE: StudioPanelRefreshContract(
        StudioPanelKind.DRIVER_QUEUE,
        refresh_mode="snapshot",
        debounce_ms=100,
        depends_on_selection=False,
        event_kinds=(StudioLiveEventKind.BUNDLE_LOADED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.EVIDENCE_BUNDLE: StudioPanelRefreshContract(
        StudioPanelKind.EVIDENCE_BUNDLE,
        refresh_mode="snapshot",
        debounce_ms=150,
        depends_on_selection=False,
        event_kinds=(StudioLiveEventKind.BUNDLE_LOADED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.AUDIT_TRAIL: StudioPanelRefreshContract(
        StudioPanelKind.AUDIT_TRAIL,
        refresh_mode="appendable_timeline",
        debounce_ms=100,
        depends_on_selection=False,
        event_kinds=(StudioLiveEventKind.BUNDLE_LOADED, StudioLiveEventKind.REVIEW_ACTION_SUBMITTED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.EVIDENCE_TIMELINE: StudioPanelRefreshContract(
        StudioPanelKind.EVIDENCE_TIMELINE,
        refresh_mode="lifecycle_timeline",
        debounce_ms=90,
        depends_on_selection=True,
        event_kinds=(StudioLiveEventKind.BUNDLE_LOADED, StudioLiveEventKind.DRIVER_SELECTED, StudioLiveEventKind.REVIEW_ACTION_SUBMITTED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.FIXTURE_REPLAY: StudioPanelRefreshContract(
        StudioPanelKind.FIXTURE_REPLAY,
        refresh_mode="snapshot",
        debounce_ms=150,
        depends_on_selection=True,
        event_kinds=(StudioLiveEventKind.DRIVER_SELECTED, StudioLiveEventKind.BUNDLE_LOADED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.RISK_CARD: StudioPanelRefreshContract(
        StudioPanelKind.RISK_CARD,
        refresh_mode="selected_snapshot",
        debounce_ms=80,
        depends_on_selection=True,
        event_kinds=(StudioLiveEventKind.DRIVER_SELECTED, StudioLiveEventKind.REVIEW_ACTION_SUBMITTED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.REGISTRY_STATE: StudioPanelRefreshContract(
        StudioPanelKind.REGISTRY_STATE,
        refresh_mode="observe_only_snapshot",
        debounce_ms=150,
        depends_on_selection=True,
        event_kinds=(StudioLiveEventKind.DRIVER_SELECTED, StudioLiveEventKind.BUNDLE_LOADED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.EXPORT_INTEGRITY: StudioPanelRefreshContract(
        StudioPanelKind.EXPORT_INTEGRITY,
        refresh_mode="hash_snapshot",
        debounce_ms=250,
        depends_on_selection=False,
        event_kinds=(StudioLiveEventKind.BUNDLE_LOADED, StudioLiveEventKind.SNAPSHOT_REFRESH),
    ),
    StudioPanelKind.EXPORT_AUDIT_CONSOLE: StudioPanelRefreshContract(
        StudioPanelKind.EXPORT_AUDIT_CONSOLE,
        refresh_mode="audit_packet_preview",
        debounce_ms=180,
        depends_on_selection=True,
        event_kinds=(
            StudioLiveEventKind.BUNDLE_LOADED,
            StudioLiveEventKind.DRIVER_SELECTED,
            StudioLiveEventKind.REVIEW_ACTION_SUBMITTED,
            StudioLiveEventKind.SNAPSHOT_REFRESH,
        ),
        authority="prepare_only",
    ),
    StudioPanelKind.MANUAL_DRIVER_BUILDER: StudioPanelRefreshContract(
        StudioPanelKind.MANUAL_DRIVER_BUILDER,
        refresh_mode="form_state",
        debounce_ms=120,
        depends_on_selection=False,
        event_kinds=(StudioLiveEventKind.MANUAL_PROPOSAL_PREVIEWED, StudioLiveEventKind.MANUAL_PROPOSAL_SUBMITTED),
        authority="proposal_only",
    ),
    StudioPanelKind.EVENT_CONSOLE: StudioPanelRefreshContract(
        StudioPanelKind.EVENT_CONSOLE,
        refresh_mode="bounded_append_stream",
        debounce_ms=50,
        depends_on_selection=False,
        event_kinds=tuple(StudioLiveEventKind),
    ),
}


def studio_panel_refresh_contracts() -> tuple[StudioPanelRefreshContract, ...]:
    """Return stable panel refresh contracts for the live cockpit."""

    return tuple(_REFRESH_CONTRACTS[kind] for kind in StudioPanelKind)


def studio_live_event_bridge_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying v3.1.12 live bridge boundaries."""

    return StudioCockpitEventBridge().capability_matrix()


def _event_sequence(event_id: str) -> int:
    try:
        return int(str(event_id).rsplit("-", 1)[-1])
    except Exception:
        return -1


def _request_action_value(request: StudioReviewActionRequest | Mapping[str, Any]) -> str:
    value: Any
    if isinstance(request, MappingABC):
        value = request.get("requested_action") or request.get("action")
    else:
        value = request.requested_action
    if isinstance(value, ReviewAction):
        return value.value
    return str(value)


def _request_driver_id(request: StudioReviewActionRequest | Mapping[str, Any]) -> str | None:
    if isinstance(request, MappingABC):
        value = request.get("driver_id")
    else:
        value = request.driver_id
    return None if value is None else str(value)

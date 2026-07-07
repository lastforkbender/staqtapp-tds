"""Pure-Python panel descriptors for the optional PyQt5 shell."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from staqtapp_tds.drivers.studio import StudioPanelKind


@dataclass(frozen=True, slots=True)
class StudioPanelDescriptor:
    """Stable panel metadata for Qt docks, tests, and documentation."""

    kind: StudioPanelKind
    title: str
    icon_name: str
    dock_area: str
    primary_surface: str
    allows_admin_action_buttons: bool = False
    read_only: bool = True


STUDIO_PANEL_DESCRIPTORS: Mapping[StudioPanelKind, StudioPanelDescriptor] = {
    StudioPanelKind.DRIVER_QUEUE: StudioPanelDescriptor(
        StudioPanelKind.DRIVER_QUEUE,
        "Driver Evidence Queue",
        "driver_queue",
        "left",
        "table",
        allows_admin_action_buttons=True,
    ),
    StudioPanelKind.EVIDENCE_BUNDLE: StudioPanelDescriptor(
        StudioPanelKind.EVIDENCE_BUNDLE,
        "Evidence Bundle Viewer",
        "evidence_bundle",
        "center",
        "json_card",
    ),
    StudioPanelKind.AUDIT_TRAIL: StudioPanelDescriptor(
        StudioPanelKind.AUDIT_TRAIL,
        "Audit Trail Panel",
        "audit_trail",
        "right",
        "timeline",
    ),
    StudioPanelKind.EVIDENCE_TIMELINE: StudioPanelDescriptor(
        StudioPanelKind.EVIDENCE_TIMELINE,
        "Evidence Timeline",
        "evidence_timeline",
        "right",
        "lifecycle_timeline",
    ),
    StudioPanelKind.FIXTURE_REPLAY: StudioPanelDescriptor(
        StudioPanelKind.FIXTURE_REPLAY,
        "Fixture Replay Summary",
        "fixture_replay",
        "center",
        "table",
    ),
    StudioPanelKind.RISK_CARD: StudioPanelDescriptor(
        StudioPanelKind.RISK_CARD,
        "Risk Card Inspector",
        "risk_card",
        "right",
        "card_stack",
        allows_admin_action_buttons=True,
    ),
    StudioPanelKind.REGISTRY_STATE: StudioPanelDescriptor(
        StudioPanelKind.REGISTRY_STATE,
        "Registry State Observer",
        "registry_state",
        "right",
        "state_table",
    ),
    StudioPanelKind.EXPORT_INTEGRITY: StudioPanelDescriptor(
        StudioPanelKind.EXPORT_INTEGRITY,
        "Export Integrity Verifier",
        "export_integrity",
        "bottom",
        "integrity_card",
    ),
    StudioPanelKind.EXPORT_AUDIT_CONSOLE: StudioPanelDescriptor(
        StudioPanelKind.EXPORT_AUDIT_CONSOLE,
        "Export / Audit Console",
        "export_audit_console",
        "bottom",
        "audit_packet_preview",
    ),
    StudioPanelKind.MANUAL_DRIVER_BUILDER: StudioPanelDescriptor(
        StudioPanelKind.MANUAL_DRIVER_BUILDER,
        "Manual Driver Builder",
        "manual_driver_builder",
        "center",
        "proposal_workbench",
        allows_admin_action_buttons=False,
        read_only=False,
    ),
    StudioPanelKind.EVENT_CONSOLE: StudioPanelDescriptor(
        StudioPanelKind.EVENT_CONSOLE,
        "Bottom Event Console",
        "event_console",
        "bottom",
        "event_stream",
    ),
}


def panel_descriptor(kind: StudioPanelKind | str) -> StudioPanelDescriptor:
    resolved = kind if isinstance(kind, StudioPanelKind) else StudioPanelKind(str(kind))
    return STUDIO_PANEL_DESCRIPTORS[resolved]

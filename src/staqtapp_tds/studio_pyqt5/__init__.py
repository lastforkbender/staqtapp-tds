"""v3.1.20 Driver Studio PyQt5 cockpit shell, live runtime, review workflow console, evidence timeline, risk intelligence cards, manual builder UI runtime, export/audit console, and export integrity workflow.

The package is import-safe without PyQt5. Headless tests and services can use
``StudioQtBridge`` and related view models; GUI launchers can construct
``DriverStudioMainWindow`` only when PyQt5 is installed.
"""
from __future__ import annotations

from .availability import PyQt5Availability, PyQt5UnavailableError, pyqt5_availability, pyqt5_available, require_pyqt5
from .bridge import StudioQtBridge, StudioQtPanelViewModel, StudioQtShellState, studio_pyqt5_shell_capability_matrix
from staqtapp_tds.drivers.studio_builder import DriverStudioManualProposalBuilder, StudioManualDriverTask, StudioManualProposalPreview, StudioManualProposalReport, StudioManualProposalStatus, studio_manual_builder_capability_matrix
from .hydration import StudioCockpitHydrator, StudioFormField, StudioHydratedCockpitState, StudioHydratedPanel, StudioPanelActionDescriptor, StudioPanelCard, StudioTableColumn, StudioTimelineItem, manual_builder_form_schema, studio_cockpit_hydration_capability_matrix
from .live import StudioCockpitEventBridge, StudioCockpitSelection, StudioLiveCockpitState, StudioLiveEvent, StudioLiveEventKind, StudioPanelRefreshContract, studio_live_event_bridge_capability_matrix, studio_panel_refresh_contracts
from .runtime import StudioLivePanelRuntime, StudioPanelDirtyMark, StudioPanelRefreshPacket, StudioPanelRuntimeState, studio_live_panel_runtime_capability_matrix
from .review_workflow import StudioReviewActionEligibility, StudioReviewHistoryEntry, StudioReviewRationaleTemplate, StudioReviewWorkflowConsole, StudioReviewWorkflowConsoleState, StudioReviewWorkflowItem, StudioReviewWorkflowStatus, studio_review_rationale_templates, studio_review_workflow_capability_matrix
from .evidence_timeline import StudioDriverLifecycleStage, StudioEvidenceTimeline, StudioEvidenceTimelineIntegrityCard, StudioEvidenceTimelineItem, StudioEvidenceTimelineState, StudioRegistryObservationItem, studio_evidence_timeline_capability_matrix
from .risk_intelligence import StudioRiskIntelligenceBand, StudioRiskIntelligenceCards, StudioRiskIntelligenceCard, StudioRiskIntelligenceFactor, StudioRiskIntelligenceState, studio_risk_intelligence_capability_matrix
from .manual_builder_runtime import StudioManualBuilderJoin, StudioManualBuilderRuntimeState, StudioManualBuilderRuntimeStatus, StudioManualBuilderRuntimeStep, StudioManualBuilderUIRuntime, StudioQtVisualQualityReport, StudioQtVisualQualityRule, studio_manual_builder_ui_runtime_capability_matrix, studio_qt_visual_quality_capability_matrix, studio_qt_visual_quality_review
from .export_audit import StudioExportAuditChecklist, StudioExportAuditConsole, StudioExportAuditConsoleState, StudioExportAuditIntegrityItem, StudioExportAuditManifest, StudioExportAuditPacketPreview, StudioExportAuditReadinessCard, StudioExportAuditStatus, studio_export_audit_capability_matrix
from .export_integrity_workflow import StudioExportIntegrityCheckpoint, StudioExportIntegrityCheckpointStatus, StudioExportIntegrityManifestComparison, StudioExportIntegrityReviewGate, StudioExportIntegrityWorkflow, StudioExportIntegrityWorkflowState, StudioExportIntegrityWorkflowStatus, studio_export_integrity_workflow_capability_matrix
from .icons import STUDIO_SVG_ICONS, studio_svg_icon
from .main_window import DriverStudioMainWindow, create_driver_studio_window
from .panels import STUDIO_PANEL_DESCRIPTORS, StudioPanelDescriptor, panel_descriptor
from .theme import DEFAULT_STUDIO_QT_THEME, StudioQtTheme

__all__ = [
    "DEFAULT_STUDIO_QT_THEME",
    "DriverStudioMainWindow",
    "DriverStudioManualProposalBuilder",
    "PyQt5Availability",
    "PyQt5UnavailableError",
    "STUDIO_PANEL_DESCRIPTORS",
    "STUDIO_SVG_ICONS",
    "StudioPanelDescriptor",
    "StudioManualDriverTask",
    "StudioManualProposalPreview",
    "StudioManualProposalReport",
    "StudioManualProposalStatus",
    "StudioCockpitEventBridge",
    "StudioCockpitSelection",
    "StudioLiveCockpitState",
    "StudioLiveEvent",
    "StudioLiveEventKind",
    "StudioPanelRefreshContract",
    "studio_live_event_bridge_capability_matrix",
    "studio_panel_refresh_contracts",
    "StudioLivePanelRuntime",
    "StudioPanelDirtyMark",
    "StudioPanelRefreshPacket",
    "StudioPanelRuntimeState",
    "studio_live_panel_runtime_capability_matrix",
    "StudioReviewActionEligibility",
    "StudioReviewHistoryEntry",
    "StudioReviewRationaleTemplate",
    "StudioReviewWorkflowConsole",
    "StudioReviewWorkflowConsoleState",
    "StudioReviewWorkflowItem",
    "StudioReviewWorkflowStatus",
    "StudioDriverLifecycleStage",
    "StudioEvidenceTimeline",
    "StudioEvidenceTimelineIntegrityCard",
    "StudioEvidenceTimelineItem",
    "StudioEvidenceTimelineState",
    "StudioRegistryObservationItem",
    "studio_evidence_timeline_capability_matrix",
    "StudioRiskIntelligenceBand",
    "StudioRiskIntelligenceCards",
    "StudioRiskIntelligenceCard",
    "StudioRiskIntelligenceFactor",
    "StudioRiskIntelligenceState",
    "studio_risk_intelligence_capability_matrix",
    "StudioExportAuditChecklist",
    "StudioExportAuditConsole",
    "StudioExportAuditConsoleState",
    "StudioExportAuditIntegrityItem",
    "StudioExportAuditManifest",
    "StudioExportAuditPacketPreview",
    "StudioExportAuditReadinessCard",
    "StudioExportAuditStatus",
    "studio_export_audit_capability_matrix",
    "StudioExportIntegrityCheckpoint",
    "StudioExportIntegrityCheckpointStatus",
    "StudioExportIntegrityManifestComparison",
    "StudioExportIntegrityReviewGate",
    "StudioExportIntegrityWorkflow",
    "StudioExportIntegrityWorkflowState",
    "StudioExportIntegrityWorkflowStatus",
    "studio_export_integrity_workflow_capability_matrix",
    "StudioManualBuilderJoin",
    "StudioManualBuilderRuntimeState",
    "StudioManualBuilderRuntimeStatus",
    "StudioManualBuilderRuntimeStep",
    "StudioManualBuilderUIRuntime",
    "StudioQtVisualQualityReport",
    "StudioQtVisualQualityRule",
    "studio_manual_builder_ui_runtime_capability_matrix",
    "studio_qt_visual_quality_capability_matrix",
    "studio_qt_visual_quality_review",
    "studio_review_rationale_templates",
    "studio_review_workflow_capability_matrix",
    "StudioCockpitHydrator",
    "StudioFormField",
    "StudioHydratedCockpitState",
    "StudioHydratedPanel",
    "StudioPanelActionDescriptor",
    "StudioPanelCard",
    "StudioTableColumn",
    "StudioTimelineItem",
    "manual_builder_form_schema",
    "studio_cockpit_hydration_capability_matrix",
    "StudioQtBridge",
    "StudioQtPanelViewModel",
    "StudioQtShellState",
    "StudioQtTheme",
    "create_driver_studio_window",
    "panel_descriptor",
    "pyqt5_availability",
    "pyqt5_available",
    "require_pyqt5",
    "studio_pyqt5_shell_capability_matrix",
    "studio_manual_builder_capability_matrix",
    "studio_svg_icon",
]

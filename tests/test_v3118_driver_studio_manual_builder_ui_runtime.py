from staqtapp_tds import __version__
from staqtapp_tds.drivers import StudioPanelKind
from staqtapp_tds.studio_pyqt5 import (
    DEFAULT_STUDIO_QT_THEME,
    StudioManualBuilderRuntimeState,
    StudioManualBuilderRuntimeStatus,
    StudioManualBuilderRuntimeStep,
    StudioManualBuilderUIRuntime,
    StudioQtBridge,
    StudioQtVisualQualityReport,
    studio_manual_builder_ui_runtime_capability_matrix,
    studio_qt_visual_quality_review,
)


def test_v3118_version():
    assert __version__ == "3.1.25"


def test_manual_builder_ui_runtime_is_import_safe_and_not_authority():
    matrix = studio_manual_builder_ui_runtime_capability_matrix()

    assert matrix["manual_builder_ui_runtime"] is True
    assert matrix["import_safe_without_pyqt5"] is True
    assert matrix["normalize_form_payloads"] is True
    assert matrix["preview_tddl_source"] is True
    assert matrix["route_to_foundry"] is True
    assert matrix["join_builder_preview_evidence_review"] is True
    assert matrix["render_visual_quality_review"] is True
    assert matrix["auto_runs_foundry"] is False
    assert matrix["auto_submits_review_action"] is False
    assert matrix["approve_driver"] is False
    assert matrix["reject_driver"] is False
    assert matrix["quarantine_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["store_private_keys"] is False
    assert matrix["bypass_policy"] is False


def test_manual_builder_ui_runtime_previews_form_payload_without_foundry_routing():
    runtime = StudioManualBuilderUIRuntime()
    payload = dict(runtime.default_form_payload())
    payload.update({"driver_id": "ManualSearchDriver", "semantic_query": "registry activation evidence"})

    state = runtime.preview_form_payload(payload)

    assert isinstance(state, StudioManualBuilderRuntimeState)
    assert state.ok is True
    assert state.status is StudioManualBuilderRuntimeStatus.PREVIEW_READY
    assert state.step is StudioManualBuilderRuntimeStep.PREVIEW
    assert state.task is not None
    assert state.task.driver_id == "ManualSearchDriver"
    assert state.preview is not None
    assert state.preview.ok is True
    assert state.report is None
    assert "driver ManualSearchDriver v1" in state.source
    assert state.source_hash.startswith("sha256:")
    assert state.metrics["form_field_count"] >= 16
    assert state.signal_payload()["foundry_ok"] is None
    assert state.capability_matrix["auto_runs_foundry"] is False


def test_manual_builder_ui_runtime_routes_explicit_proposal_to_foundry_only():
    bridge = StudioQtBridge()
    runtime = bridge.manual_builder_ui_runtime()
    payload = dict(runtime.default_form_payload())
    payload["driver_id"] = "ManualFoundryDriver"

    state = runtime.propose_form_payload(payload)

    assert state.status in {StudioManualBuilderRuntimeStatus.PROPOSAL_ROUTED, StudioManualBuilderRuntimeStatus.INPUT_REJECTED}
    assert state.step is StudioManualBuilderRuntimeStep.FOUNDRY
    assert state.preview is not None
    assert state.report is not None
    assert state.source_hash.startswith("sha256:")
    assert {join.target_panel for join in state.joins} >= {
        StudioPanelKind.MANUAL_DRIVER_BUILDER,
        StudioPanelKind.EVIDENCE_BUNDLE,
        StudioPanelKind.EVIDENCE_TIMELINE,
        StudioPanelKind.RISK_CARD,
        StudioPanelKind.DRIVER_QUEUE,
    }
    assert state.visual_quality is not None
    assert state.visual_quality.ok is True
    assert state.signal_payload()["capability_matrix"]["activate_driver"] is False
    assert bridge.capability_matrix()["create_manual_builder_ui_runtime"] is True


def test_manual_builder_ui_runtime_rejects_bad_form_before_foundry():
    runtime = StudioManualBuilderUIRuntime()
    payload = dict(runtime.default_form_payload())
    payload["driver_id"] = "bad driver id with spaces"

    state = runtime.preview_form_payload(payload)

    assert state.ok is False
    assert state.status is StudioManualBuilderRuntimeStatus.INPUT_REJECTED
    assert state.preview is None
    assert state.report is None
    assert "driver_id" in state.reason
    assert state.capability_matrix["route_to_foundry"] is True
    assert state.capability_matrix["approve_driver"] is False


def test_visual_quality_review_checks_legibility_and_layout_contracts():
    report = studio_qt_visual_quality_review()

    assert isinstance(report, StudioQtVisualQualityReport)
    assert report.ok is True
    assert report.minimum_font_px >= 12
    assert report.body_font_px >= 13
    assert report.title_font_px >= 16
    assert all(rule.passed for rule in report.rules)
    payload = report.signal_payload()
    assert payload["capability_matrix"]["checks_font_legibility"] is True
    assert payload["capability_matrix"]["requires_pyqt5"] is False
    assert DEFAULT_STUDIO_QT_THEME.minimum_font_px >= 12
    assert "font-size" in DEFAULT_STUDIO_QT_THEME.stylesheet()

import copy

import pytest

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverRegressionHarness,
    EvidenceBundleExporter,
    ReviewAction,
    RuntimeManagerStatus,
    VMStatus,
    compile_tddl,
)
from staqtapp_tds.drivers.studio import StudioPanelKind
from staqtapp_tds.studio_pyqt5 import (
    DEFAULT_STUDIO_QT_THEME,
    DriverStudioMainWindow,
    PyQt5UnavailableError,
    STUDIO_PANEL_DESCRIPTORS,
    STUDIO_SVG_ICONS,
    StudioQtBridge,
    pyqt5_available,
    studio_pyqt5_shell_capability_matrix,
)


SEARCH_DRIVER = '''
driver SearchPolicyDrivers v1

manifest:
  kind = "search"
  description = "Find policy-related driver manifests"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read
  capability trace.write
  adapter predicate.semantic_manifest.v1
  adapter scorer.trace_rank.v1

limits:
  max_scan = 5000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=5000 depth=8
  READ target="manifest"
  MATCH field="manifest.kind" eq="driver"
  MATCH using="predicate.semantic_manifest.v1" query="policy routing" threshold=0.80
  EXTRACT from="manifest" fields=["driver_id", "version", "capabilities", "safety"]
  SCORE using="scorer.trace_rank.v1" weight="semantic" threshold=0.75
  TRACE event="policy_driver_candidate"
  EMIT mode="ranked" limit=2
  HALT

evolution:
  deny external_io
  max_delta = 1
'''

RECORDS = [
    {
        "path": ".tds/drivers/policy_routing",
        "manifest": {
            "kind": "driver",
            "driver_id": "PolicyRoutingA",
            "version": 3,
            "capabilities": ["policy", "routing", "search"],
            "safety": "bounded",
        },
        "semantic_score": 0.93,
    },
]


def _bundle():
    package = compile_tddl(SEARCH_DRIVER)
    case = DriverFixtureCase(
        "policy-hit",
        {"records": copy.deepcopy(RECORDS)},
        expected_ok=True,
        expected_status=RuntimeManagerStatus.EXECUTED,
        expected_recommendation="candidate_ready",
        expected_vm_status=VMStatus.HALTED,
        expected_emitted_count=1,
        expected_trace_complete=True,
        tags=("golden",),
    )
    report = DriverRegressionHarness().run_package(package, (case,))
    batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v319")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T04:00:00Z",
    )


def test_v319_version():
    assert __version__ == "3.1.25"


def test_studio_pyqt5_module_imports_without_requiring_qt():
    availability = pyqt5_available()
    assert isinstance(availability, bool)
    assert StudioQtBridge().shell_state().status == "empty"
    assert len(StudioQtBridge().shell_state().panels) == len(tuple(StudioPanelKind))


def test_studio_pyqt5_shell_capability_matrix_is_not_authority():
    matrix = studio_pyqt5_shell_capability_matrix()

    assert matrix["pyqt5_shell"] is True
    assert matrix["render_cockpit"] is True
    assert matrix["render_svg_iconography"] is True
    assert matrix["submit_review_actions"] is True
    assert matrix["route_to_studio_action_layer"] is True
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

    assert not hasattr(StudioQtBridge(), "approve")
    assert not hasattr(StudioQtBridge(), "sign")
    assert not hasattr(StudioQtBridge(), "activate")
    assert not hasattr(StudioQtBridge(), "execute")


def test_studio_pyqt5_panel_descriptors_theme_and_svg_iconography():
    assert set(STUDIO_PANEL_DESCRIPTORS) == set(StudioPanelKind)
    assert STUDIO_PANEL_DESCRIPTORS[StudioPanelKind.DRIVER_QUEUE].allows_admin_action_buttons is True
    assert STUDIO_PANEL_DESCRIPTORS[StudioPanelKind.RISK_CARD].allows_admin_action_buttons is True
    assert STUDIO_PANEL_DESCRIPTORS[StudioPanelKind.EVENT_CONSOLE].dock_area == "bottom"

    palette = DEFAULT_STUDIO_QT_THEME.palette()
    assert palette["telemetry_blue"] == "#3aa8ff"
    assert palette["telemetry_purple"] == "#8f5cff"
    assert palette["telemetry_orange"] == "#ff9d42"
    assert "QMainWindow" in DEFAULT_STUDIO_QT_THEME.stylesheet()

    assert set(STUDIO_SVG_ICONS) >= {descriptor.icon_name for descriptor in STUDIO_PANEL_DESCRIPTORS.values()}
    for icon in STUDIO_SVG_ICONS.values():
        assert icon.startswith("<svg")
        assert "emoji" not in icon.lower()
        assert "#3aa8ff" in icon or "#8f5cff" in icon or "#ff9d42" in icon


def test_studio_pyqt5_bridge_renders_bundle_to_panel_view_models():
    bridge = StudioQtBridge()
    state = bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")

    assert state.ok is True
    assert state.status == "ready"
    assert state.selected_driver_id == "SearchPolicyDrivers"
    assert state.console_hash.startswith("sha256:")
    assert state.bundle_hash.startswith("sha256:")
    assert state.event_count >= 1

    queue = state.panel(StudioPanelKind.DRIVER_QUEUE)
    assert queue.title == "Driver Evidence Queue"
    assert queue.allows_admin_action_buttons is True
    assert queue.read_only is True
    assert queue.rows[0]["driver_id"] == "SearchPolicyDrivers"

    event_console = state.panel("event_console")
    assert event_console.dock_area == "bottom"
    assert event_console.primary_surface == "event_stream"


def test_studio_pyqt5_bridge_submits_actions_through_existing_action_layer():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    request = bridge.build_action_request(
        "SearchPolicyDrivers",
        ReviewAction.HOLD,
        reviewer_id="studio-admin",
        rationale="manual shell hold",
        source_panel=StudioPanelKind.RISK_CARD,
        tags=("shell",),
    )
    submission = bridge.submit_review_action(request, submitted_at="fixed")

    assert submission.ok is True
    assert submission.decisions[0].requested_action is ReviewAction.HOLD
    assert submission.decisions[0].rationale == "manual shell hold"
    assert submission.decisions[0].tags == ("shell",)
    assert submission.authority_report is None
    assert submission.capability_matrix["call_registry_approve"] is False
    assert submission.capability_matrix["activate_driver"] is False


def test_studio_pyqt5_window_constructor_fails_clearly_without_qt():
    if pyqt5_available():
        pytest.skip("PyQt5 is available in this environment; GUI construction is integration-tested manually")
    with pytest.raises(PyQt5UnavailableError):
        DriverStudioMainWindow()

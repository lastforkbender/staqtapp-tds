import copy

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverRegressionHarness,
    EvidenceBundleExporter,
    ReviewAction,
    RuntimeManagerStatus,
    StudioManualDriverTask,
    StudioPanelKind,
    VMStatus,
    compile_tddl,
)
from staqtapp_tds.studio_pyqt5 import (
    StudioCockpitEventBridge,
    StudioLiveCockpitState,
    StudioLiveEventKind,
    StudioPanelRefreshContract,
    StudioQtBridge,
    studio_live_event_bridge_capability_matrix,
    studio_panel_refresh_contracts,
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
    batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v3112")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T06:00:00Z",
    )


def _task() -> StudioManualDriverTask:
    return StudioManualDriverTask(
        driver_id="ManualPolicyDriver",
        description="Manual live bridge proposal for policy-routing manifests",
        semantic_query="policy routing",
        emit_limit=2,
        tags=("manual", "live"),
    )


def test_v3112_version():
    assert __version__ == "3.1.20"


def test_live_bridge_capability_matrix_and_refresh_contracts_do_not_grant_authority():
    matrix = studio_live_event_bridge_capability_matrix()

    assert matrix["live_cockpit_event_bridge"] is True
    assert matrix["bounded_event_stream"] is True
    assert matrix["snapshot_refresh_semantics"] is True
    assert matrix["coordinate_selected_context"] is True
    assert matrix["panel_refresh_contracts"] is True
    assert matrix["emit_qt_signal_payloads"] is True
    assert matrix["safe_polling_bridge"] is True
    assert matrix["live_bridge_mutates_backend"] is False
    assert matrix["approve_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["store_private_keys"] is False
    assert matrix["bypass_policy"] is False

    contracts = studio_panel_refresh_contracts()
    assert len(contracts) == len(tuple(StudioPanelKind))
    assert all(isinstance(contract, StudioPanelRefreshContract) for contract in contracts)
    assert all(contract.mutable_backend is False for contract in contracts)
    assert {contract.kind for contract in contracts} == set(StudioPanelKind)
    assert any(contract.kind is StudioPanelKind.EVENT_CONSOLE and contract.refresh_mode == "bounded_append_stream" for contract in contracts)
    assert any(contract.kind is StudioPanelKind.MANUAL_DRIVER_BUILDER and contract.authority == "proposal_only" for contract in contracts)

    bridge = StudioCockpitEventBridge()
    assert not hasattr(bridge, "approve")
    assert not hasattr(bridge, "sign")
    assert not hasattr(bridge, "activate")


def test_live_bridge_load_select_refresh_and_bounded_event_stream():
    live = StudioCockpitEventBridge(max_events=3)
    empty = live.current_state()

    assert isinstance(empty, StudioLiveCockpitState)
    assert empty.hydrated.status == "empty"
    assert empty.events == ()
    assert empty.signal_payload()["status"] == "empty"

    loaded = live.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers", timestamp="t1")
    selected = live.select_driver("SearchPolicyDrivers", timestamp="t2")
    live.refresh_panel(StudioPanelKind.RISK_CARD, timestamp="t3")
    refreshed = live.refresh(reason="poll tick", timestamp="t4")

    assert loaded.selection.selected_driver_id == "SearchPolicyDrivers"
    assert selected.selection.bundle_id == loaded.selection.bundle_id
    assert refreshed.generation == 4
    assert refreshed.cursor == 4
    assert refreshed.latest_event_id == "live-000004"
    assert len(refreshed.events) == 3  # bounded ring behavior
    assert [event.kind for event in refreshed.events] == [
        StudioLiveEventKind.DRIVER_SELECTED,
        StudioLiveEventKind.PANEL_REFRESHED,
        StudioLiveEventKind.SNAPSHOT_REFRESH,
    ]
    assert len(refreshed.events_since(2)) == 2
    assert refreshed.panel(StudioPanelKind.RISK_CARD).cards[0].title == "SearchPolicyDrivers"

    payload = refreshed.signal_payload()
    assert payload["generation"] == 4
    assert payload["cursor"] == 4
    assert payload["selected_driver_id"] == "SearchPolicyDrivers"
    assert payload["event_count"] == 3
    assert payload["panel_status"]["risk_card"] == "ready"
    assert payload["capability_matrix"]["activate_driver"] is False


def test_bridge_can_create_live_event_bridge_for_existing_shell_state():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    live = bridge.live_event_bridge(max_events=8)
    state = live.refresh(reason="initial hydration", timestamp="fixed")

    assert state.selection.selected_driver_id == "SearchPolicyDrivers"
    assert state.hydrated.status == "ready"
    assert state.events[0].kind is StudioLiveEventKind.SNAPSHOT_REFRESH
    assert bridge.panel_refresh_contracts()[0].kind is StudioPanelKind.DRIVER_QUEUE
    assert bridge.capability_matrix()["create_live_event_bridge"] is True
    assert bridge.capability_matrix()["panel_refresh_contracts"] is True
    assert bridge.capability_matrix()["activate_driver"] is False


def test_live_bridge_routes_review_and_manual_builder_events_without_authority():
    live = StudioCockpitEventBridge(max_events=8)
    live.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers", timestamp="load")

    request = live.bridge.build_action_request(
        "SearchPolicyDrivers",
        ReviewAction.HOLD,
        reviewer_id="studio-admin",
        rationale="live bridge hold",
        source_panel=StudioPanelKind.RISK_CARD,
        tags=("live",),
    )
    review = live.submit_review_action(request, submitted_at="review")
    preview = live.preview_manual_driver_task(_task(), timestamp="preview")
    proposal = live.propose_manual_driver_task(_task(), fixtures={"records": RECORDS}, timestamp="foundry")
    state = live.current_state()

    assert review.ok is True
    assert preview.ok is True
    assert proposal.ok is True
    assert [event.kind for event in state.events][-3:] == [
        StudioLiveEventKind.REVIEW_ACTION_SUBMITTED,
        StudioLiveEventKind.MANUAL_PROPOSAL_PREVIEWED,
        StudioLiveEventKind.MANUAL_PROPOSAL_SUBMITTED,
    ]
    assert state.events[-1].source == "driver_foundry"
    assert state.events[-1].payload["ok"] is True
    assert state.capability_matrix["submit_candidate"] is False
    assert state.capability_matrix["approve_driver"] is False
    assert state.capability_matrix["activate_driver"] is False

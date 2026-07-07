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
    StudioLiveEventKind,
    StudioLivePanelRuntime,
    StudioPanelDirtyMark,
    StudioPanelRefreshPacket,
    StudioPanelRuntimeState,
    StudioQtBridge,
    studio_live_panel_runtime_capability_matrix,
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
    batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v3113")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T07:00:00Z",
    )


def _task() -> StudioManualDriverTask:
    return StudioManualDriverTask(
        driver_id="ManualPolicyDriver",
        description="Manual live panel runtime proposal for policy-routing manifests",
        semantic_query="policy routing",
        emit_limit=2,
        tags=("manual", "runtime"),
    )


def _kinds(state: StudioPanelRuntimeState):
    return {kind.value for kind in state.dirty_panel_kinds}


def test_v3113_version():
    assert __version__ == "3.1.23"


def test_live_panel_runtime_capability_matrix_has_no_authority():
    matrix = studio_live_panel_runtime_capability_matrix()

    assert matrix["live_panel_runtime"] is True
    assert matrix["dirty_panel_tracking"] is True
    assert matrix["panel_refresh_packets"] is True
    assert matrix["qt_model_update_payloads"] is True
    assert matrix["event_to_panel_routing"] is True
    assert matrix["selection_aware_panel_refresh"] is True
    assert matrix["consume_incremental_events"] is True
    assert matrix["live_runtime_mutates_backend"] is False
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

    runtime = StudioLivePanelRuntime()
    assert not hasattr(runtime, "approve")
    assert not hasattr(runtime, "sign")
    assert not hasattr(runtime, "activate")


def test_live_panel_runtime_load_bundle_produces_incremental_refresh_packets():
    runtime = StudioLivePanelRuntime(max_events=8)
    initial = runtime.current_state(include_packets=True)

    assert initial.cursor == 0
    assert initial.refresh_packets == ()
    assert initial.dirty_marks == ()

    state = runtime.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers", timestamp="load")

    assert state.cursor == 1
    assert state.consumed_cursor == 0
    assert state.selection.selected_driver_id == "SearchPolicyDrivers"
    assert state.events[0].kind is StudioLiveEventKind.BUNDLE_LOADED
    assert all(isinstance(mark, StudioPanelDirtyMark) for mark in state.dirty_marks)
    assert all(isinstance(packet, StudioPanelRefreshPacket) for packet in state.refresh_packets)
    assert _kinds(state) == {
        "driver_queue",
        "evidence_bundle",
        "audit_trail",
        "evidence_timeline",
        "fixture_replay",
        "registry_state",
        "export_integrity",
        "export_audit_console",
        "event_console",
    }
    assert runtime.consumed_cursor == 1

    queue_packet = state.packet(StudioPanelKind.DRIVER_QUEUE)
    assert queue_packet.signal_payload()["panel_kind"] == "driver_queue"
    assert queue_packet.signal_payload()["row_count"] == 1
    assert queue_packet.authority == "observe_only"
    assert queue_packet.payload["mutable_backend"] is False

    assert runtime.current_state(include_packets=True).dirty_marks == ()


def test_live_panel_runtime_selection_and_panel_refresh_route_only_affected_panels():
    runtime = StudioLivePanelRuntime(max_events=16)
    runtime.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers", timestamp="load")

    selected = runtime.select_driver("SearchPolicyDrivers", timestamp="select")
    assert selected.cursor == 2
    assert selected.events[0].kind is StudioLiveEventKind.DRIVER_SELECTED
    assert _kinds(selected) == {"evidence_timeline", "fixture_replay", "risk_card", "registry_state", "export_audit_console", "event_console"}
    assert selected.packet("risk_card").panel.cards[0].title == "SearchPolicyDrivers"

    refreshed = runtime.refresh_panel(StudioPanelKind.RISK_CARD, timestamp="risk-refresh")
    assert refreshed.cursor == 3
    assert refreshed.events[0].kind is StudioLiveEventKind.PANEL_REFRESHED
    assert _kinds(refreshed) == {"event_console"}
    assert refreshed.signal_payload()["refresh_packet_count"] == 1
    assert refreshed.signal_payload()["refresh_packets"][0]["panel_kind"] == "event_console"


def test_live_panel_runtime_review_and_manual_builder_events_feed_correct_packets():
    runtime = StudioLivePanelRuntime(max_events=16)
    runtime.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers", timestamp="load")

    request = runtime.event_bridge.bridge.build_action_request(
        "SearchPolicyDrivers",
        ReviewAction.HOLD,
        reviewer_id="studio-admin",
        rationale="runtime hold",
        source_panel=StudioPanelKind.RISK_CARD,
        tags=("runtime",),
    )
    review, review_state = runtime.submit_review_action(request, submitted_at="review")
    assert review.ok is True
    assert _kinds(review_state) == {"audit_trail", "evidence_timeline", "risk_card", "export_audit_console", "event_console"}
    assert review_state.events[0].kind is StudioLiveEventKind.REVIEW_ACTION_SUBMITTED

    preview, preview_state = runtime.preview_manual_driver_task(_task(), timestamp="preview")
    assert preview.ok is True
    assert _kinds(preview_state) == {"manual_driver_builder", "event_console"}
    assert preview_state.packet("manual_driver_builder").authority == "proposal_only"

    proposal, proposal_state = runtime.propose_manual_driver_task(_task(), fixtures={"records": RECORDS}, timestamp="foundry")
    assert proposal.ok is True
    assert _kinds(proposal_state) == {"manual_driver_builder", "event_console"}
    assert proposal_state.events[0].kind is StudioLiveEventKind.MANUAL_PROPOSAL_SUBMITTED
    assert proposal_state.capability_matrix["activate_driver"] is False
    assert proposal_state.capability_matrix["mutate_registry"] is False


def test_bridge_can_create_live_panel_runtime_and_force_initial_hydration():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    state = runtime.mark_all_dirty(reason="first Qt paint")

    assert bridge.capability_matrix()["create_live_panel_runtime"] is True
    assert len(state.dirty_panel_kinds) == len(tuple(StudioPanelKind))
    assert state.packet(StudioPanelKind.MANUAL_DRIVER_BUILDER).authority == "proposal_only"
    assert state.packet(StudioPanelKind.EXPORT_INTEGRITY).panel.status == "ready"
    assert state.signal_payload()["capability_matrix"]["approve_driver"] is False

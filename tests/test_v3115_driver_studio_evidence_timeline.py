import copy

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverRegressionHarness,
    EvidenceBundleExporter,
    ReviewAction,
    RuntimeManagerStatus,
    StudioPanelKind,
    VMStatus,
    compile_tddl,
)
from staqtapp_tds.studio_pyqt5 import (
    StudioDriverLifecycleStage,
    StudioEvidenceTimeline,
    StudioEvidenceTimelineIntegrityCard,
    StudioEvidenceTimelineItem,
    StudioEvidenceTimelineState,
    StudioQtBridge,
    studio_evidence_timeline_capability_matrix,
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
    batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v3115")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T08:00:00Z",
    )


def test_v3115_version():
    assert __version__ == "3.1.26"


def test_evidence_timeline_capability_matrix_is_observe_only():
    matrix = studio_evidence_timeline_capability_matrix()

    assert matrix["evidence_timeline"] is True
    assert matrix["render_chronological_trust_history"] is True
    assert matrix["render_driver_lifecycle_stages"] is True
    assert matrix["render_registry_observations"] is True
    assert matrix["render_timeline_integrity_card"] is True
    assert matrix["prepare_export_audit_context"] is True
    assert matrix["evidence_timeline_mutates_backend"] is False
    assert matrix["evidence_timeline_is_authority"] is False
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

    timeline = StudioEvidenceTimeline()
    assert not hasattr(timeline, "approve")
    assert not hasattr(timeline, "sign")
    assert not hasattr(timeline, "activate")


def test_hydrated_evidence_timeline_panel_exposes_lifecycle_rows_cards_and_timeline():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    hydrated = bridge.hydrated_shell_state()
    panel = hydrated.panel(StudioPanelKind.EVIDENCE_TIMELINE)

    assert panel.title == "Evidence Timeline"
    assert panel.primary_surface == "lifecycle_timeline"
    assert panel.rows
    assert panel.timeline
    assert panel.cards[0].badges == ("chronological", "export-ready", "observe-only")
    assert {row["stage"] for row in panel.rows} >= {
        "proposal",
        "validated",
        "compiled",
        "fixture-tested",
        "evidence-ready",
        "review-submitted",
        "reviewed",
        "exported",
    }
    assert all(row["authority"] == "observe_only" for row in panel.rows)
    assert panel.metrics["authority"] == "observe_only"


def test_evidence_timeline_state_prepares_export_audit_spine():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    runtime.mark_all_dirty(reason="initial evidence timeline paint")
    timeline = runtime.evidence_timeline()

    state = timeline.current_state()

    assert isinstance(state, StudioEvidenceTimelineState)
    assert state.ok is True
    assert state.selected_driver_id == "SearchPolicyDrivers"
    assert state.export_ready is True
    assert state.latest_stage is StudioDriverLifecycleStage.EXPORTED
    assert isinstance(state.integrity_card, StudioEvidenceTimelineIntegrityCard)
    assert state.integrity_card.export_ready is True
    assert state.integrity_card.missing_stages == ()
    assert any(isinstance(item, StudioEvidenceTimelineItem) for item in state.items)
    assert state.items_for_stage(StudioDriverLifecycleStage.FIXTURE_TESTED)
    assert state.signal_payload()["integrity_card"]["authority"] == "observe_only"
    assert state.signal_payload()["capability_matrix"]["mutate_registry"] is False


def test_evidence_timeline_connects_review_workflow_events_without_authority():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    workflow = runtime.review_workflow_console()

    report, runtime_state, _workflow_state = workflow.submit_selected_action(
        ReviewAction.HOLD,
        reviewer_id="studio-admin",
        template_id="hold.more_evidence",
        submitted_at="timeline-review",
        tags=("timeline",),
    )
    timeline = runtime.evidence_timeline().current_state(runtime_state)

    assert report.ok is True
    assert StudioPanelKind.EVIDENCE_TIMELINE in runtime_state.dirty_panel_kinds
    assert any(item.source_event_id and item.authority == "review_intent_only" for item in timeline.items)
    assert timeline.signal_payload()["capability_matrix"]["activate_driver"] is False


def test_bridge_can_create_evidence_timeline():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    timeline = bridge.evidence_timeline(max_events=16)
    state = timeline.current_state()

    assert bridge.capability_matrix()["create_evidence_timeline"] is True
    assert state.items_for_stage("compiled")
    assert state.signal_payload()["item_count"] >= 8

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
    StudioRiskIntelligenceBand,
    StudioRiskIntelligenceCard,
    StudioRiskIntelligenceCards,
    StudioRiskIntelligenceFactor,
    StudioRiskIntelligenceState,
    StudioQtBridge,
    studio_risk_intelligence_capability_matrix,
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


def _bundle(*, action=ReviewAction.APPROVE):
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
    batch = DriverBatchReviewBoard().review_reports(
        (report,),
        reviewer_id="admin-1",
        requested_action=action,
        rationale="risk intelligence test path",
        batch_id="batch-v3116",
    )
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T08:00:00Z",
    )


def test_v3116_version():
    assert __version__ == "3.5.2"


def test_risk_intelligence_capability_matrix_is_analysis_only():
    matrix = studio_risk_intelligence_capability_matrix()

    assert matrix["risk_intelligence_cards"] is True
    assert matrix["render_risk_pressure"] is True
    assert matrix["render_evidence_gap_factors"] is True
    assert matrix["render_timeline_risk_context"] is True
    assert matrix["render_fixture_risk_context"] is True
    assert matrix["render_review_action_hints"] is True
    assert matrix["risk_to_review_workflow_context"] is True
    assert matrix["risk_to_evidence_timeline_context"] is True
    assert matrix["risk_intelligence_mutates_backend"] is False
    assert matrix["risk_intelligence_is_authority"] is False
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

    cards = StudioRiskIntelligenceCards()
    assert not hasattr(cards, "approve")
    assert not hasattr(cards, "sign")
    assert not hasattr(cards, "activate")


def test_risk_intelligence_cards_cross_link_risk_timeline_fixture_and_review_context():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    runtime.mark_all_dirty(reason="initial risk intelligence paint")

    state = runtime.risk_intelligence_cards().current_state()

    assert isinstance(state, StudioRiskIntelligenceState)
    assert state.ok is True
    assert state.selected_driver_id == "SearchPolicyDrivers"
    assert state.aggregate_pressure_score <= 10
    assert state.attention_count == 0
    assert state.evidence_gap_count == 0
    assert state.selected_card is not None
    assert isinstance(state.selected_card, StudioRiskIntelligenceCard)
    assert state.selected_card.band is StudioRiskIntelligenceBand.LOW
    assert state.selected_card.review_action_hint is ReviewAction.APPROVE
    assert state.selected_card.readiness_label == "review_ready"
    assert state.selected_card.latest_lifecycle_stage == "exported"
    assert state.selected_card.timeline_event_count >= 8
    assert any(isinstance(factor, StudioRiskIntelligenceFactor) for factor in state.selected_card.factors)
    assert {factor.factor_id for factor in state.selected_card.factors} >= {
        "risk.level",
        "review.decision_status",
        "fixture.coverage_clean",
        "registry.observed_state",
    }
    assert state.panel_cards[-1].badges == ("risk-intelligence", "timeline-linked", "observe-only")
    assert state.signal_payload()["capability_matrix"]["mutate_registry"] is False


def test_risk_intelligence_identifies_hold_posture_without_granting_authority():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(action=ReviewAction.HOLD), selected_driver_id="SearchPolicyDrivers")
    state = bridge.risk_intelligence_cards(max_events=16).current_state()

    assert state.selected_card is not None
    assert state.selected_card.decision_status == "held"
    assert state.selected_card.band is StudioRiskIntelligenceBand.MODERATE
    assert state.selected_card.review_action_hint is ReviewAction.HOLD
    assert state.selected_card.attention_required is False
    assert state.selected_card.readiness_label == "review_with_caution"
    assert state.signal_payload()["selected_card"]["authority"] == "observe_only"
    assert state.signal_payload()["selected_card"]["review_action_hint"] == "hold"
    assert bridge.capability_matrix()["create_risk_intelligence_cards"] is True


def test_risk_intelligence_observes_live_review_intent_as_factor_only():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    workflow = runtime.review_workflow_console()

    report, runtime_state, _workflow_state = workflow.submit_selected_action(
        ReviewAction.HOLD,
        reviewer_id="studio-admin",
        template_id="hold.more_evidence",
        submitted_at="risk-intelligence-review",
        tags=("risk",),
    )
    state = runtime.risk_intelligence_cards().current_state(runtime_state)

    assert report.ok is True
    assert StudioPanelKind.RISK_CARD in runtime_state.dirty_panel_kinds
    assert state.selected_card is not None
    live_factors = [factor for factor in state.selected_card.factors if factor.factor_id == "live.review_intent_submitted"]
    assert live_factors
    assert live_factors[0].authority == "review_intent_only"
    assert state.capability_matrix["approve_driver"] is False
    assert state.capability_matrix["activate_driver"] is False

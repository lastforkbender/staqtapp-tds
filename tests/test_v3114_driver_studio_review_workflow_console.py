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
    StudioReviewActionEligibility,
    StudioReviewRationaleTemplate,
    StudioReviewWorkflowConsole,
    StudioReviewWorkflowConsoleState,
    StudioReviewWorkflowStatus,
    StudioQtBridge,
    studio_review_rationale_templates,
    studio_review_workflow_capability_matrix,
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
    batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v3114")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T08:00:00Z",
    )


def test_v3114_version():
    assert __version__ == "3.1.20"


def test_review_workflow_capability_matrix_is_decision_support_not_authority():
    matrix = studio_review_workflow_capability_matrix()

    assert matrix["review_workflow_console"] is True
    assert matrix["render_review_readiness"] is True
    assert matrix["render_action_eligibility"] is True
    assert matrix["render_rationale_templates"] is True
    assert matrix["render_review_history"] is True
    assert matrix["build_review_action_request"] is True
    assert matrix["submit_review_intent"] is True
    assert matrix["review_workflow_mutates_backend"] is False
    assert matrix["review_workflow_is_authority"] is False
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

    console = StudioReviewWorkflowConsole()
    assert not hasattr(console, "approve")
    assert not hasattr(console, "sign")
    assert not hasattr(console, "activate")


def test_rationale_templates_are_stable_and_renderable():
    templates = studio_review_rationale_templates()
    by_id = {template.template_id: template for template in templates}

    assert isinstance(by_id["approve.clean_evidence"], StudioReviewRationaleTemplate)
    assert by_id["approve.clean_evidence"].requested_action is ReviewAction.APPROVE
    assert by_id["approve.clean_evidence"].requires_edit is False
    assert by_id["reject.policy_failure"].requested_action is ReviewAction.REJECT
    assert by_id["quarantine.risk_or_integrity"].requested_action is ReviewAction.QUARANTINE
    rendered = by_id["hold.more_evidence"].render(driver_id="SearchPolicyDrivers", reason="fixture coverage needs expansion")
    assert "SearchPolicyDrivers" in rendered
    assert "fixture coverage" in rendered


def test_review_workflow_state_explains_selected_driver_readiness_and_actions():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    runtime.mark_all_dirty(reason="initial review workflow paint")
    console = runtime.review_workflow_console()

    state = console.current_state()

    assert isinstance(state, StudioReviewWorkflowConsoleState)
    assert state.status is StudioReviewWorkflowStatus.READY
    assert state.ok is True
    assert state.selected_driver_id == "SearchPolicyDrivers"
    assert state.selected_item is not None
    assert state.selected_item.driver_id == "SearchPolicyDrivers"
    assert state.selected_item.readiness_score >= 90
    assert state.selected_item.recommended_action is ReviewAction.APPROVE
    assert state.ready_count == 1
    assert state.attention_count == 0
    assert state.cards[0].badges == ("review-intent-only", "no-registry-mutation")

    approve = state.selected_item.action(ReviewAction.APPROVE)
    reject = state.selected_item.action(ReviewAction.REJECT)
    quarantine = state.selected_item.action(ReviewAction.QUARANTINE)

    assert isinstance(approve, StudioReviewActionEligibility)
    assert approve.enabled is True
    assert approve.authority == "review_intent_only"
    assert approve.rationale_template_id == "approve.clean_evidence"
    assert reject.enabled is False
    assert reject.requires_rationale is True
    assert reject.dangerous is True
    assert quarantine.enabled is False
    assert state.signal_payload()["capability_matrix"]["mutate_registry"] is False


def test_review_workflow_builds_and_submits_selected_review_intent_through_runtime():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    console = runtime.review_workflow_console()

    request = console.build_selected_request(
        ReviewAction.APPROVE,
        reviewer_id="studio-admin",
        template_id="approve.clean_evidence",
        tags=("workflow",),
    )
    assert request.driver_id == "SearchPolicyDrivers"
    assert request.requested_action is ReviewAction.APPROVE
    assert "verified evidence" in request.rationale
    assert request.source_panel == StudioPanelKind.RISK_CARD.value

    report, runtime_state, workflow_state = console.submit_selected_action(
        ReviewAction.HOLD,
        reviewer_id="studio-admin",
        template_id="hold.more_evidence",
        submitted_at="review-workflow",
        tags=("workflow", "hold"),
    )

    assert report.ok is True
    assert report.decisions[0].requested_action is ReviewAction.HOLD
    assert runtime_state.dirty_panel_kinds
    assert {kind.value for kind in runtime_state.dirty_panel_kinds} == {"audit_trail", "evidence_timeline", "risk_card", "export_audit_console", "event_console"}
    assert workflow_state.history
    assert workflow_state.signal_payload()["history"][-1]["action"] == "hold"
    assert workflow_state.capability_matrix["approve_driver"] is False
    assert workflow_state.capability_matrix["activate_driver"] is False


def test_bridge_can_create_review_workflow_console():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    console = bridge.review_workflow_console(max_events=16)
    state = console.current_state()

    assert bridge.capability_matrix()["create_review_workflow_console"] is True
    assert state.item("SearchPolicyDrivers").action("approve").enabled is True
    assert state.signal_payload()["item_count"] == 1

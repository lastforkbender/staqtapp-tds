import copy
import json

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    BatchReviewPolicy,
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverManifest,
    DriverRegistry,
    DriverRegressionHarness,
    DriverState,
    DriverStudioAdminReviewActions,
    EvidenceBundleExporter,
    ReviewAction,
    RuntimeManagerStatus,
    StudioReviewActionRequest,
    StudioReviewActionStatus,
    StudioReviewSubmissionPolicy,
    StudioReviewSubmissionStatus,
    VMStatus,
    compile_tddl,
    studio_admin_review_capability_matrix,
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


def _clean_report():
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
    return package, DriverRegressionHarness().run_package(package, (case,))


def _bundle(report):
    batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v318")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T03:00:00Z",
    )


def test_v318_version():
    assert __version__ == "3.1.25"


def test_studio_admin_review_capability_matrix_allows_submission_not_authority():
    matrix = studio_admin_review_capability_matrix()

    assert matrix["load_readonly_console_snapshot"] is True
    assert matrix["submit_review_actions"] is True
    assert matrix["create_action_audit_records"] is True
    assert matrix["route_to_batch_review_authority"] is True
    assert matrix["request_registry_approval_route"] is False
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

    request_matrix = studio_admin_review_capability_matrix(
        StudioReviewSubmissionPolicy(allow_registry_approval_request=True)
    )
    assert request_matrix["request_registry_approval_route"] is True
    assert request_matrix["call_registry_approve"] is False
    assert request_matrix["activate_driver"] is False


def test_studio_records_actions_without_regression_reports_or_registry_mutation():
    _package, report = _clean_report()
    bundle = _bundle(report)
    actions = DriverStudioAdminReviewActions()

    submission = actions.submit_actions(
        bundle,
        (StudioReviewActionRequest("SearchPolicyDrivers", ReviewAction.HOLD, reviewer_id="studio-admin", rationale="defer"),),
        submitted_at="fixed",
    )

    assert submission.ok is True
    assert submission.status is StudioReviewSubmissionStatus.SUBMITTED
    assert submission.authority_report is None
    assert submission.decisions[0].status is StudioReviewActionStatus.RECORDED
    assert submission.decisions[0].source_review_hash.startswith("sha256:")
    assert submission.audit_events[0].event_type == "studio_review_action_submitted"
    assert submission.audit_events[0].submission_hash == submission.submission_hash
    assert submission.capability_matrix["call_registry_approve"] is False
    assert submission.to_json() == actions.submit_actions(
        bundle,
        (StudioReviewActionRequest("SearchPolicyDrivers", ReviewAction.HOLD, reviewer_id="studio-admin", rationale="defer"),),
        submitted_at="fixed",
    ).to_json()


def test_studio_routes_actions_to_batch_review_authority_not_direct_approval():
    _package, report = _clean_report()
    bundle = _bundle(report)
    actions = DriverStudioAdminReviewActions()

    submission = actions.submit_actions(
        bundle,
        ({"driver_id": "SearchPolicyDrivers", "requested_action": "approve", "reviewer_id": "studio-admin", "rationale": "golden evidence clean"},),
        regression_reports=(report,),
        submitted_at="fixed",
        authority_batch_id="authority-v318",
    )

    assert submission.ok is True
    assert submission.status is StudioReviewSubmissionStatus.AUTHORITY_ACCEPTED
    assert submission.authority_report is not None
    assert submission.authority_report.approved_count == 1
    assert submission.authority_report.registry_approved_count == 0
    assert submission.decisions[0].status is StudioReviewActionStatus.AUTHORITY_ACCEPTED
    assert submission.decisions[0].authority_status == "approval_ready"
    assert submission.decisions[0].registry_state_after is None
    assert submission.authority_batch_hash == submission.authority_report.batch_hash
    assert submission.audit_events[0].authority_status == "approval_ready"
    assert not hasattr(DriverStudioAdminReviewActions(), "approve")
    assert not hasattr(DriverStudioAdminReviewActions(), "sign")
    assert not hasattr(DriverStudioAdminReviewActions(), "activate")
    assert not hasattr(DriverStudioAdminReviewActions(), "execute")


def test_studio_rejects_tampered_bundle_before_authority_routing():
    _package, report = _clean_report()
    payload = json.loads(_bundle(report).to_json())
    payload["records"][0]["risk_level"] = "tampered"

    submission = DriverStudioAdminReviewActions().submit_actions(
        payload,
        (StudioReviewActionRequest("SearchPolicyDrivers", ReviewAction.APPROVE),),
        regression_reports=(report,),
    )

    assert submission.ok is False
    assert submission.status is StudioReviewSubmissionStatus.INPUT_REJECTED
    assert submission.authority_report is None
    assert submission.decisions[0].status is StudioReviewActionStatus.INPUT_REJECTED
    assert "verified evidence bundle" in submission.reason


def test_registry_approval_route_requires_studio_policy_and_review_board_authority():
    _package, report = _clean_report()
    bundle = _bundle(report)
    registry = DriverRegistry()
    registry.add_candidate(
        DriverManifest.from_mapping(
            {
                "driver_id": report.driver_id,
                "version": report.driver_version,
                "kind": "search",
                "description": "candidate from regression report",
                "safety": "bounded",
                "capabilities": ("registry.scan", "manifest.read", "trace.write"),
            }
        ),
        test_report_hash=report.report_hash,
    )

    denied = DriverStudioAdminReviewActions().submit_actions(
        bundle,
        (StudioReviewActionRequest("SearchPolicyDrivers", ReviewAction.APPROVE, rationale="clean"),),
        regression_reports=(report,),
        registry=registry,
        request_registry_approval=True,
    )

    assert denied.ok is False
    assert denied.status is StudioReviewSubmissionStatus.POLICY_REJECTED
    assert registry.require("SearchPolicyDrivers").state is DriverState.CANDIDATE

    routed_but_board_denied = DriverStudioAdminReviewActions(
        policy=StudioReviewSubmissionPolicy(allow_registry_approval_request=True)
    ).submit_actions(
        bundle,
        (StudioReviewActionRequest("SearchPolicyDrivers", ReviewAction.APPROVE, rationale="clean"),),
        regression_reports=(report,),
        registry=registry,
        request_registry_approval=True,
    )

    assert routed_but_board_denied.ok is False
    assert routed_but_board_denied.status is StudioReviewSubmissionStatus.AUTHORITY_REJECTED
    assert routed_but_board_denied.decisions[0].fault_code == "review.policy.registry_approval_disabled"
    assert registry.require("SearchPolicyDrivers").state is DriverState.CANDIDATE

    approved = DriverStudioAdminReviewActions(
        policy=StudioReviewSubmissionPolicy(allow_registry_approval_request=True)
    ).submit_actions(
        bundle,
        (StudioReviewActionRequest("SearchPolicyDrivers", ReviewAction.APPROVE, rationale="clean"),),
        regression_reports=(report,),
        review_board=DriverBatchReviewBoard(policy=BatchReviewPolicy(allow_registry_approval=True)),
        registry=registry,
        request_registry_approval=True,
    )

    assert approved.ok is True
    assert approved.status is StudioReviewSubmissionStatus.AUTHORITY_ACCEPTED
    assert approved.authority_report.registry_approved_count == 1
    assert approved.decisions[0].authority_status == "registry_approved"
    assert approved.decisions[0].registry_state_before == DriverState.CANDIDATE.value
    assert approved.decisions[0].registry_state_after == DriverState.APPROVED.value
    assert registry.require("SearchPolicyDrivers").state is DriverState.APPROVED
    assert approved.capability_matrix["call_registry_approve"] is False
    assert approved.capability_matrix["activate_driver"] is False

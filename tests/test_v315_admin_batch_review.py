import copy

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    BatchReviewPolicy,
    BatchReviewStatus,
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverManifest,
    DriverRegressionHarness,
    DriverRegistry,
    DriverState,
    ReviewAction,
    ReviewDecisionStatus,
    RuntimeManagerStatus,
    VMStatus,
    batch_review_capability_matrix,
    compile_tddl,
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

EXTRACT_DRIVER = SEARCH_DRIVER.replace("SearchPolicyDrivers", "ExtractPolicyDrivers").replace('kind = "search"', 'kind = "extract"')

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


def _clean_report(source=SEARCH_DRIVER):
    package = compile_tddl(source)
    case = DriverFixtureCase(
        "policy-hit",
        {"records": copy.deepcopy(RECORDS)},
        expected_ok=True,
        expected_status=RuntimeManagerStatus.EXECUTED,
        expected_recommendation="candidate_ready",
        expected_vm_status=VMStatus.HALTED,
        expected_emitted_count=1,
        expected_trace_complete=True,
    )
    return package, DriverRegressionHarness().run_package(package, (case,))


def _failed_report():
    package = compile_tddl(SEARCH_DRIVER)
    case = DriverFixtureCase(
        "bad-golden-count",
        {"records": copy.deepcopy(RECORDS)},
        expected_ok=True,
        expected_status=RuntimeManagerStatus.EXECUTED,
        expected_vm_status=VMStatus.HALTED,
        expected_emitted_count=999,
    )
    return DriverRegressionHarness().run_package(package, (case,))


def test_v315_version():
    assert __version__ == "3.5.2"


def test_batch_review_capability_matrix_denies_signing_activation_execution_and_storage():
    matrix = batch_review_capability_matrix()

    assert matrix["consume_regression_reports"] is True
    assert matrix["create_batch_review_records"] is True
    assert matrix["create_per_driver_audit_decisions"] is True
    assert matrix["approve_clean_candidate_decision"] is True
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False
    assert matrix["execute_python"] is False
    assert matrix["bypass_policy"] is False

    approval_matrix = batch_review_capability_matrix(BatchReviewPolicy(allow_registry_approval=True))
    assert approval_matrix["call_registry_approve"] is True
    assert approval_matrix["sign_driver"] is False
    assert approval_matrix["activate_driver"] is False


def test_clean_regression_report_becomes_approval_ready_without_registry_mutation():
    _package, report = _clean_report()
    board = DriverBatchReviewBoard()

    batch = board.review_reports((report,), reviewer_id="admin-1", rationale="golden fixtures passed")

    assert batch.ok is True
    assert batch.status is BatchReviewStatus.COMPLETED
    assert batch.approved_count == 1
    assert batch.registry_approved_count == 0
    assert batch.held_count == 0
    assert batch.batch_hash.startswith("sha256:")
    assert batch.approved_driver_ids == ("SearchPolicyDrivers",)
    decision = batch.decisions[0]
    assert decision.status is ReviewDecisionStatus.APPROVAL_READY
    assert decision.approved is True
    assert decision.final_action is ReviewAction.APPROVE
    assert decision.risk_level == "low"
    assert decision.evidence_summary["case_count"] == 1
    assert decision.evidence_summary["failed_count"] == 0
    assert decision.registry_state_after is None
    assert decision.review_hash.startswith("sha256:")


def test_batch_review_hash_is_deterministic_for_same_reports_and_admin_decision():
    _package, report = _clean_report()
    board = DriverBatchReviewBoard()

    first = board.review_reports((report,), reviewer_id="admin-1", rationale="same", batch_id="batch-a")
    second = board.review_reports((report,), reviewer_id="admin-1", rationale="same", batch_id="batch-a")

    assert first.batch_hash == second.batch_hash
    assert first.decisions[0].review_hash == second.decisions[0].review_hash


def test_failed_regression_report_requested_for_approval_is_held_not_approved():
    report = _failed_report()

    batch = DriverBatchReviewBoard().review_reports((report,), requested_action=ReviewAction.APPROVE)

    assert batch.ok is True
    assert batch.approved_count == 0
    assert batch.held_count == 1
    decision = batch.decisions[0]
    assert decision.status is ReviewDecisionStatus.HELD
    assert decision.final_action is ReviewAction.HOLD
    assert decision.risk_level == "high"
    assert decision.faults[0].code == "review.evidence.regression_not_clean"


def test_reject_and_quarantine_actions_remain_per_driver_decisions():
    _package, clean = _clean_report()
    _extract_package, clean_extract = _clean_report(EXTRACT_DRIVER)

    batch = DriverBatchReviewBoard().review_reports(
        (clean, clean_extract),
        action_overrides={
            "SearchPolicyDrivers": "quarantine",
            "ExtractPolicyDrivers": ReviewAction.REJECT,
        },
        reviewer_id="admin-2",
        rationale="manual routing check",
    )

    assert batch.ok is True
    assert batch.quarantined_count == 1
    assert batch.rejected_count == 1
    assert batch.decisions[0].status is ReviewDecisionStatus.QUARANTINED
    assert batch.decisions[1].status is ReviewDecisionStatus.REJECTED
    assert batch.decisions[0].rationale == "manual routing check"


def test_registry_approval_requires_explicit_policy_and_apply_flag():
    package, report = _clean_report()
    registry = DriverRegistry()
    manifest = DriverManifest.from_mapping(
        {
            "driver_id": report.driver_id,
            "version": report.driver_version,
            "kind": "search",
            "description": "candidate from regression report",
            "safety": "bounded",
            "capabilities": ("registry.scan", "manifest.read", "trace.write"),
        }
    )
    registry.add_candidate(manifest, test_report_hash=report.report_hash)

    denied = DriverBatchReviewBoard().review_reports((report,), registry=registry, apply_registry=True)

    assert denied.ok is False
    assert denied.registry_rejected_count == 1
    assert registry.require("SearchPolicyDrivers").state is DriverState.CANDIDATE
    assert denied.decisions[0].faults[0].code == "review.policy.registry_approval_disabled"

    approved = DriverBatchReviewBoard(policy=BatchReviewPolicy(allow_registry_approval=True)).review_reports(
        (report,), registry=registry, apply_registry=True
    )

    assert approved.ok is True
    assert approved.registry_approved_count == 1
    assert approved.approved_count == 0
    assert approved.decisions[0].status is ReviewDecisionStatus.REGISTRY_APPROVED
    assert approved.decisions[0].registry_state_before == DriverState.CANDIDATE.value
    assert approved.decisions[0].registry_state_after == DriverState.APPROVED.value
    assert registry.require("SearchPolicyDrivers").state is DriverState.APPROVED
    assert not hasattr(DriverBatchReviewBoard(), "attach_signature")
    assert not hasattr(DriverBatchReviewBoard(), "activate")


def test_batch_review_rejects_duplicate_driver_entries_as_structured_report():
    _package, report = _clean_report()

    batch = DriverBatchReviewBoard().review_reports((report, report))

    assert batch.ok is False
    assert batch.status is BatchReviewStatus.INPUT_REJECTED
    assert batch.decisions == ()
    assert "duplicate driver review entries" in batch.reason


def test_expected_negative_runtime_evidence_is_not_approval_ready_by_default():
    package = compile_tddl(SEARCH_DRIVER)
    harness = DriverRegressionHarness()
    case = DriverFixtureCase(
        "expected-bad-fixtures",
        {"records": "not-a-list"},
        expected_ok=False,
        expected_status=RuntimeManagerStatus.INPUT_REJECTED,
        expected_fault_codes=("runtime.input_rejected",),
    )
    report = harness.run_package(package, (case,))

    batch = DriverBatchReviewBoard().review_reports((report,))

    assert report.ok is True
    assert batch.approved_count == 0
    assert batch.held_count == 1
    assert batch.decisions[0].faults[0].code == "review.evidence.runtime_not_clean"

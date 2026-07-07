import copy

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverFixtureCase,
    DriverRegressionHarness,
    DriverRegressionReport,
    DriverRuntimeManager,
    RegressionStatus,
    RuntimeManagerPolicy,
    RuntimeManagerStatus,
    VMStatus,
    compile_tddl,
    regression_harness_capability_matrix,
    runtime_fixture_hash,
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
    {
        "path": ".tds/drivers/telemetry",
        "manifest": {
            "kind": "driver",
            "driver_id": "TelemetryOnly",
            "version": 1,
            "capabilities": ["telemetry"],
            "safety": "bounded",
        },
        "semantic_score": 0.60,
    },
]

NO_MATCH_RECORDS = [
    {
        "path": ".tds/drivers/metrics",
        "manifest": {"kind": "metric", "driver_id": "MetricsOnly", "version": 1},
        "semantic_score": 0.91,
    }
]


def _passing_cases():
    return (
        DriverFixtureCase(
            "policy-hit",
            {"records": copy.deepcopy(RECORDS)},
            expected_ok=True,
            expected_status=RuntimeManagerStatus.EXECUTED,
            expected_recommendation="candidate_ready",
            expected_vm_status=VMStatus.HALTED,
            expected_emitted_count=1,
            expected_trace_complete=True,
            tags=("golden", "hit"),
        ),
        DriverFixtureCase(
            "policy-miss",
            {"records": copy.deepcopy(NO_MATCH_RECORDS)},
            expected_ok=True,
            expected_status="executed",
            expected_recommendation="candidate_ready",
            expected_vm_status="halted",
            expected_emitted_count=0,
            expected_trace_complete=True,
            tags=("golden", "miss"),
        ),
    )


def test_v314_version():
    assert __version__ == "3.1.23"


def test_regression_harness_capability_matrix_denies_trust_authority_and_storage_writes():
    matrix = regression_harness_capability_matrix()

    assert matrix["run_runtime_manager"] is True
    assert matrix["compare_fixture_expectations"] is True
    assert matrix["produce_regression_report"] is True
    assert matrix["record_golden_evidence_hashes"] is True
    assert matrix["approve_driver"] is False
    assert matrix["sign_driver"] is False
    assert matrix["activate_driver"] is False
    assert matrix["write_storage"] is False
    assert matrix["execute_python"] is False
    assert matrix["bypass_policy"] is False


def test_regression_harness_runs_multiple_fixture_cases_and_returns_batch_ready_report():
    package = compile_tddl(SEARCH_DRIVER)
    harness = DriverRegressionHarness()

    report = harness.run_package(package, _passing_cases())

    assert isinstance(report, DriverRegressionReport)
    assert report.ok is True
    assert report.status is RegressionStatus.PASSED
    assert report.recommendation == "batch_review_ready"
    assert report.driver_id == "SearchPolicyDrivers"
    assert report.package_hash == package.package_hash
    assert report.case_count == 2
    assert report.passed_count == 2
    assert report.failed_count == 0
    assert report.failed_cases == ()
    assert report.report_hash.startswith("sha256:")
    assert report.results[0].fixture_hash == runtime_fixture_hash({"records": RECORDS})
    assert report.results[0].evidence.ok is True
    assert report.results[1].evidence.metrics["vm_emitted_count"] == 0


def test_regression_report_hash_is_deterministic_for_same_package_and_fixtures():
    package = compile_tddl(SEARCH_DRIVER)
    harness = DriverRegressionHarness()

    first = harness.run_package(package, _passing_cases())
    second = harness.run_package(package, _passing_cases())

    assert first.ok is True and second.ok is True
    assert first.report_hash == second.report_hash
    assert first.results[0].evidence_hash == second.results[0].evidence_hash


def test_regression_harness_detects_expectation_mismatch_without_halting():
    package = compile_tddl(SEARCH_DRIVER)
    case = DriverFixtureCase(
        "wrong-count",
        {"records": copy.deepcopy(RECORDS)},
        expected_ok=True,
        expected_status=RuntimeManagerStatus.EXECUTED,
        expected_vm_status=VMStatus.HALTED,
        expected_emitted_count=999,
        expected_trace_complete=True,
    )

    report = DriverRegressionHarness().run_package(package, (case,))

    assert report.ok is False
    assert report.status is RegressionStatus.FAILED
    assert report.recommendation == "hold"
    assert report.failed_cases == ("wrong-count",)
    assert report.results[0].passed is False
    assert report.results[0].mismatches[0].field == "vm_emitted_count"
    assert report.results[0].mismatches[0].actual == 1


def test_regression_harness_can_lock_expected_evidence_hashes():
    package = compile_tddl(SEARCH_DRIVER)
    evidence = DriverRuntimeManager().execute_package(package, {"records": copy.deepcopy(RECORDS)})
    case = DriverFixtureCase(
        "golden-hash",
        {"records": copy.deepcopy(RECORDS)},
        expected_ok=True,
        expected_status=RuntimeManagerStatus.EXECUTED,
        expected_evidence_hash=evidence.evidence_hash,
    )

    report = DriverRegressionHarness().run_package(package, (case,))

    assert report.ok is True
    assert report.results[0].evidence_hash == evidence.evidence_hash


def test_regression_harness_preserves_runtime_manager_policy_faults_as_expected_results():
    package = compile_tddl(SEARCH_DRIVER)
    manager = DriverRuntimeManager(policy=RuntimeManagerPolicy(allowed_driver_classes=frozenset({"extract"})))
    harness = DriverRegressionHarness(runtime_manager=manager)
    case = DriverFixtureCase(
        "policy-reject",
        {"records": copy.deepcopy(RECORDS)},
        expected_ok=False,
        expected_status=RuntimeManagerStatus.POLICY_REJECTED,
        expected_fault_codes=("runtime.policy.driver_class",),
        expected_trace_complete=False,
    )

    report = harness.run_package(package, (case,))

    assert report.ok is True
    assert report.results[0].passed is True
    assert report.results[0].evidence.status is RuntimeManagerStatus.POLICY_REJECTED
    assert report.results[0].evidence.vm_result is None


def test_regression_harness_rejects_bad_case_shape_as_report_not_exception():
    package = compile_tddl(SEARCH_DRIVER)

    report = DriverRegressionHarness().run_package(package, ({"case_id": "bad", "fixtures": "not-a-mapping"},))

    assert report.ok is False
    assert report.status is RegressionStatus.INPUT_REJECTED
    assert report.reason.startswith("invalid regression fixture cases")
    assert report.results == ()

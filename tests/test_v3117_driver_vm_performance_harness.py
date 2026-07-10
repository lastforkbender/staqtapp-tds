import copy

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverVMPerformanceBackend,
    DriverVMPerformanceHarness,
    DriverVMPerformancePolicy,
    DriverVMPerformanceReport,
    DriverVMPerformanceStatus,
    DriverVMRuntime,
    compile_tddl,
    driver_vm_performance_capability_matrix,
    driver_vm_performance_enabled,
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
        "path": ".tds/drivers/noise",
        "manifest": {
            "kind": "driver",
            "driver_id": "NoiseDriver",
            "version": 1,
            "capabilities": ["noise"],
            "safety": "bounded",
        },
        "semantic_score": 0.20,
    },
]


def _native_runner_alias(package, snapshot, policy):
    vm = DriverVMRuntime(max_instructions=policy.max_instructions, max_cost=policy.max_cost)
    vm.load(package)
    return vm.execute(copy.deepcopy(snapshot))


def test_v3117_version():
    assert __version__ == "3.5.2"


def test_performance_harness_is_opt_in_and_not_a_hot_path_hook():
    assert driver_vm_performance_enabled({}) is False
    assert driver_vm_performance_enabled({"STAQTAPP_TDS_DRIVER_VM_PERF": "1"}) is True

    matrix = driver_vm_performance_capability_matrix()
    assert matrix["driver_vm_performance_harness"] is True
    assert matrix["opt_in_only"] is True
    assert matrix["auto_runs_in_driver_vm_execute"] is False
    assert matrix["auto_runs_in_runtime_manager"] is False
    assert matrix["normal_python_vm_hot_path_changed"] is False
    assert matrix["future_native_c_conversion_target"] is True
    assert matrix["approve_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["activate_driver"] is False
    assert matrix["write_storage"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["store_private_keys"] is False
    assert matrix["bypass_policy"] is False


def test_performance_harness_generates_python_and_runtime_manager_evidence():
    package = compile_tddl(SEARCH_DRIVER)
    policy = DriverVMPerformancePolicy(repetitions=2, warmup_runs=0, include_managed_runtime=True)
    report = DriverVMPerformanceHarness(policy=policy).run_package(package, {"records": RECORDS})

    assert isinstance(report, DriverVMPerformanceReport)
    assert report.ok is True
    assert report.status is DriverVMPerformanceStatus.PASSED
    assert report.driver_id == "SearchPolicyDrivers"
    assert report.driver_version == 1
    assert report.driver_class == "search"
    assert report.package_hash == package.package_hash
    assert report.snapshot_hash.startswith("sha256:")
    assert report.performance_hash.startswith("sha256:")
    assert len(report.runs) == 4

    python_summary = report.summary(DriverVMPerformanceBackend.PYTHON_VM)
    managed_summary = report.summary(DriverVMPerformanceBackend.MANAGED_PYTHON_VM)
    assert python_summary.run_count == 2
    assert managed_summary.run_count == 2
    assert python_summary.ok_count == 2
    assert managed_summary.ok_count == 2
    assert python_summary.deterministic is True
    assert managed_summary.deterministic is True
    assert python_summary.median_records_per_second > 0
    assert managed_summary.median_records_per_second > 0
    assert report.comparisons[0].parity_ok is True
    assert report.signal_payload()["capability_report"]["normal_python_vm_hot_path_changed"] is False


def test_performance_harness_can_accept_future_native_backend_parity_target():
    package = compile_tddl(SEARCH_DRIVER)
    policy = DriverVMPerformancePolicy(
        repetitions=2,
        warmup_runs=0,
        include_managed_runtime=False,
        native_backend_enabled=True,
    )
    report = DriverVMPerformanceHarness(policy=policy, native_runner=_native_runner_alias).run(package, {"records": RECORDS})

    assert report.ok is True
    assert report.summary(DriverVMPerformanceBackend.PYTHON_VM).deterministic is True
    assert report.summary(DriverVMPerformanceBackend.NATIVE_C_VM).deterministic is True
    assert report.comparisons[0].candidate_backend is DriverVMPerformanceBackend.NATIVE_C_VM
    assert report.comparisons[0].parity_ok is True
    assert report.capability_report["native_c_vm_backend_slot"] is True
    assert report.capability_report["native_runner_available"] is True
    assert report.capability_report["activate_driver"] is False


def test_performance_harness_native_requested_without_runner_is_warning_not_auto_execution():
    package = compile_tddl(SEARCH_DRIVER)
    policy = DriverVMPerformancePolicy(
        repetitions=1,
        warmup_runs=0,
        include_managed_runtime=False,
        native_backend_enabled=True,
    )
    report = DriverVMPerformanceHarness(policy=policy).run_package(package, {"records": RECORDS})

    assert report.ok is True
    assert report.warnings == ("native C VM backend was requested but no native_runner was provided",)
    assert len(report.runs) == 1
    assert report.runs[0].backend is DriverVMPerformanceBackend.PYTHON_VM

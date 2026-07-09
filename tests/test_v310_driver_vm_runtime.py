import pytest

from staqtapp_tds import __version__
from staqtapp_tds.drivers import DriverVMRuntime, DriverVMSkeleton, VMState, compile_tddl

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

EXTRACT_DRIVER = '''
driver ExtractTelemetrySummary v1

manifest:
  kind = "extract"
  description = "Extract telemetry summary fields"
  safety = "bounded"

requires:
  capability manifest.read
  capability trace.write

limits:
  max_scan = 1000
  max_depth = 0
  timeout_ms = 250

program:
  READ target="manifest"
  MATCH field="manifest.kind" eq="telemetry"
  EXTRACT from="manifest" fields=["driver_id", "version"]
  TRACE event="telemetry_summary_extracted"
  EMIT mode="list" limit=10
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
    {
        "path": ".tds/telemetry/summary",
        "manifest": {"kind": "telemetry", "driver_id": "TelemetrySummary", "version": 2},
    },
    {
        "path": "outside/not_tds",
        "manifest": {"kind": "driver", "driver_id": "Outside", "version": 1},
        "semantic_score": 1.0,
    },
]


def test_v310_version():
    assert __version__ == "3.1.26"


def test_runtime_executes_validated_search_driver_deterministically():
    package = compile_tddl(SEARCH_DRIVER)
    vm = DriverVMRuntime()
    loaded = vm.load(package)
    result = vm.execute({"records": RECORDS})

    assert loaded.driver_class == "search"
    assert result.ok is True
    assert result.state is VMState.EXECUTED
    assert result.trace == ("validate", "load", "SCAN", "READ", "MATCH", "MATCH", "EXTRACT", "SCORE", "TRACE", "EMIT", "HALT")
    assert len(result.emitted) == 1
    assert result.emitted[0]["driver_id"] == "PolicyRoutingA"
    assert result.emitted[0]["rank_score"] >= 0.75
    assert result.trace_events == ({"event": "policy_driver_candidate", "count": 1},)


def test_runtime_executes_extract_driver_without_scan_against_input_snapshot():
    package = compile_tddl(EXTRACT_DRIVER)
    vm = DriverVMRuntime()
    vm.load(package)
    result = vm.execute({"records": RECORDS})

    assert result.ok is True
    assert [item["driver_id"] for item in result.emitted] == ["TelemetrySummary"]
    assert result.emitted[0]["version"] == 2


def test_runtime_fails_closed_without_loaded_package():
    result = DriverVMRuntime().execute({"records": RECORDS})
    assert result.ok is False
    assert result.state is VMState.REJECTED


def test_runtime_fails_closed_on_bad_records_input():
    package = compile_tddl(SEARCH_DRIVER)
    vm = DriverVMRuntime()
    vm.load(package)
    result = vm.execute({"records": "not-a-record-list"})

    assert result.ok is False
    assert result.state is VMState.REJECTED
    assert "records" in result.reason


def test_runtime_cost_budget_is_enforced_during_execution():
    package = compile_tddl(SEARCH_DRIVER)
    vm = DriverVMRuntime(max_cost=30)
    vm.load(package)
    result = vm.execute({"records": RECORDS})
    assert result.ok is True
    assert result.cost_used <= 30

    strict_vm = DriverVMRuntime(max_cost=20)
    with pytest.raises(ValueError, match="instruction cost"):
        strict_vm.load(package)


def test_skeleton_remains_non_executing_for_contract_audit_mode():
    package = compile_tddl(SEARCH_DRIVER)
    vm = DriverVMSkeleton()
    vm.load(package)
    result = vm.execute({"records": RECORDS})

    assert result.ok is False
    assert result.state is VMState.EXECUTION_DISABLED

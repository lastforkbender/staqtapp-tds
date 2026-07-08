import copy
import importlib
import inspect

import pytest

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverVMContext,
    DriverVMResult,
    DriverVMRuntime,
    TDDLValidationError,
    VMFault,
    VMState,
    VMStatus,
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

REGEX_DRIVER = '''
driver RegexPolicySearch v1

manifest:
  kind = "search"
  description = "Regex-limited policy search"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read
  capability trace.write

limits:
  max_scan = 1000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=1000 depth=8
  READ target="manifest"
  MATCH field="manifest.driver_id" regex_limited="^Policy"
  EXTRACT from="manifest" fields=["driver_id", "version"]
  EMIT mode="list" limit=10
  HALT

evolution:
  deny external_io
  max_delta = 1
'''

RANGE_DRIVER = '''
driver RangePolicySearch v1

manifest:
  kind = "search"
  description = "Range policy search"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read
  capability trace.write

limits:
  max_scan = 1000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=1000 depth=8
  READ target="manifest"
  MATCH field="manifest.version" range=[2, 5]
  EXTRACT from="manifest" fields=["driver_id", "version"]
  EMIT mode="list" limit=10
  HALT

evolution:
  deny external_io
  max_delta = 1
'''

UNSUPPORTED_EXTRACT_ADAPTER_DRIVER = '''
driver AdapterExtract v1

manifest:
  kind = "extract"
  description = "Adapter extraction remains future work"
  safety = "bounded"

requires:
  capability manifest.read
  capability trace.write
  adapter extractor.future.v1

limits:
  max_scan = 1000
  max_depth = 8
  timeout_ms = 250

program:
  READ target="manifest"
  MATCH field="manifest.kind" eq="driver"
  EXTRACT using="extractor.future.v1" from="manifest" as="summary"
  EMIT mode="list" limit=10
  HALT

evolution:
  deny external_io
  max_delta = 1
'''

SCAN_KIND_DRIVER = '''
driver ScanKindFuture v1

manifest:
  kind = "search"
  description = "SCAN kind is validated syntax but not runtime-supported yet"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read
  capability trace.write

limits:
  max_scan = 1000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=1000 depth=8 kind="driver"
  READ target="manifest"
  MATCH field="manifest.kind" eq="driver"
  EXTRACT from="manifest" fields=["driver_id"]
  EMIT mode="list" limit=10
  HALT

evolution:
  deny external_io
  max_delta = 1
'''

NO_PREDICATE_DRIVER = '''
driver NoPredicate v1

manifest:
  kind = "search"
  description = "Invalid MATCH field without predicate"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read

limits:
  max_scan = 1000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=1000 depth=8
  MATCH field="manifest.kind"
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


def test_v311_version():
    assert __version__ == "3.1.25"


def test_successful_execution_returns_driver_vm_result_with_context():
    vm = DriverVMRuntime()
    vm.load(compile_tddl(SEARCH_DRIVER))
    result = vm.execute({"records": RECORDS})

    assert isinstance(result, DriverVMResult)
    assert result.ok is True
    assert result.status is VMStatus.HALTED
    assert result.state is VMState.EXECUTED
    assert result.reason == "driver bytecode halted successfully"
    assert result.driver_id == "SearchPolicyDrivers"
    assert result.package_hash
    assert result.context.driver_class == "search"
    assert result.context.records_seen == len(RECORDS)
    assert result.context.emitted_count == 1
    assert result.metrics["status"] == VMStatus.HALTED.value
    assert result.faults == ()


def test_unloaded_runtime_returns_not_loaded_without_raising():
    result = DriverVMRuntime().execute({"records": RECORDS})

    assert result.ok is False
    assert result.status is VMStatus.NOT_LOADED
    assert result.state is VMState.REJECTED
    assert result.faults == (VMFault("vm.not_loaded", "no validated bytecode package is loaded"),)


def test_bad_records_input_returns_input_rejected_without_raising():
    vm = DriverVMRuntime()
    vm.load(compile_tddl(SEARCH_DRIVER))

    result = vm.execute({"records": "not-a-record-list"})

    assert result.ok is False
    assert result.status is VMStatus.INPUT_REJECTED
    assert result.state is VMState.REJECTED
    assert result.faults[0].code == "vm.input.records"
    assert "records" in result.reason


def test_runtime_budget_exceeded_returns_structured_result_without_raising():
    vm = DriverVMRuntime()
    vm.load(compile_tddl(SEARCH_DRIVER))
    vm.max_cost = 4  # Simulate a tighter runtime manager budget after load.

    result = vm.execute({"records": RECORDS})

    assert result.ok is False
    assert result.status is VMStatus.BUDGET_EXCEEDED
    assert result.faults[0].code == "vm.budget_exceeded"
    assert result.faults[0].instruction in {"READ", "MATCH", "SCAN"}
    assert result.context.cost_used > result.context.max_cost


def test_unsupported_runtime_operand_faults_without_halting_host():
    vm = DriverVMRuntime()
    vm.load(compile_tddl(SCAN_KIND_DRIVER))

    result = vm.execute({"records": RECORDS})

    assert result.ok is False
    assert result.status is VMStatus.FAULTED
    assert result.faults[0].code == "vm.scan.unsupported_operand"
    assert result.faults[0].instruction == "SCAN"
    assert "kind" in result.reason


def test_unsupported_extract_adapter_faults_with_instruction_context():
    vm = DriverVMRuntime()
    vm.load(compile_tddl(UNSUPPORTED_EXTRACT_ADAPTER_DRIVER))

    result = vm.execute({"records": RECORDS})

    assert result.ok is False
    assert result.status is VMStatus.FAULTED
    assert result.faults[0].code == "vm.adapter.unsupported"
    assert result.faults[0].instruction == "EXTRACT"
    assert result.context.instruction == "EXTRACT"
    assert result.context.instruction_pointer is not None


def test_regex_limited_and_range_predicates_have_runtime_semantics():
    regex_vm = DriverVMRuntime()
    regex_vm.load(compile_tddl(REGEX_DRIVER))
    regex_result = regex_vm.execute({"records": RECORDS})
    assert regex_result.ok is True
    assert [item["driver_id"] for item in regex_result.emitted] == ["PolicyRoutingA"]

    range_vm = DriverVMRuntime()
    range_vm.load(compile_tddl(RANGE_DRIVER))
    range_result = range_vm.execute({"records": RECORDS})
    assert range_result.ok is True
    assert [item["driver_id"] for item in range_result.emitted] == ["PolicyRoutingA"]


def test_match_field_without_predicate_is_rejected_before_bytecode():
    with pytest.raises(TDDLValidationError, match="MATCH.field requires at least one predicate"):
        compile_tddl(NO_PREDICATE_DRIVER)


def test_runtime_does_not_mutate_caller_record_snapshots():
    records = copy.deepcopy(RECORDS)
    before = copy.deepcopy(records)
    vm = DriverVMRuntime()
    vm.load(compile_tddl(SEARCH_DRIVER))

    result = vm.execute({"records": records})

    assert result.ok is True
    assert records == before
    result.emitted[0]["capabilities"].append("mutated-output")
    assert records == before


def test_public_execute_expected_faults_do_not_raise():
    scenarios = []

    bad_input_vm = DriverVMRuntime()
    bad_input_vm.load(compile_tddl(SEARCH_DRIVER))
    scenarios.append((bad_input_vm, {"records": object()}))

    budget_vm = DriverVMRuntime()
    budget_vm.load(compile_tddl(SEARCH_DRIVER))
    budget_vm.max_cost = 1
    scenarios.append((budget_vm, {"records": RECORDS}))

    adapter_vm = DriverVMRuntime()
    adapter_vm.load(compile_tddl(UNSUPPORTED_EXTRACT_ADAPTER_DRIVER))
    scenarios.append((adapter_vm, {"records": RECORDS}))

    for vm, inputs in scenarios:
        result = vm.execute(inputs)
        assert isinstance(result, DriverVMResult)
        assert result.ok is False
        assert result.faults


def test_internal_handler_exception_is_contained_as_internal_error(monkeypatch):
    vm_module = importlib.import_module("staqtapp_tds.drivers.vm")

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic handler explosion")

    vm = DriverVMRuntime()
    vm.load(compile_tddl(SEARCH_DRIVER))
    monkeypatch.setattr(vm_module, "_op_scan", boom)

    result = vm.execute({"records": RECORDS})

    assert result.ok is False
    assert result.status is VMStatus.INTERNAL_ERROR
    assert result.faults[0].code == "vm.internal_error"
    assert "synthetic handler explosion" in result.reason


def test_driver_vm_runtime_does_not_import_storage_engine():
    vm_module = importlib.import_module("staqtapp_tds.drivers.vm")
    source = inspect.getsource(vm_module)

    forbidden = (
        "tds_filesystem",
        "tds_persistence",
        "_native_index",
        "EntryIndex",
        "TDSFileSystem",
    )
    assert all(token not in source for token in forbidden)

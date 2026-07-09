import json

import pytest

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    BytecodeInstruction,
    BytecodePackage,
    DriverVMSkeleton,
    TDDLValidationError,
    VMState,
    audit_vm_contract,
    compile_tddl,
    vm_contract_table,
)

VALID_SEARCH_DRIVER = '''
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
  MATCH using="predicate.semantic_manifest.v1" query="policy routing" threshold=0.82
  EXTRACT from="manifest" fields=["driver_id", "version", "path", "capabilities", "safety"]
  SCORE using="scorer.trace_rank.v1" weight="semantic" threshold=0.75
  TRACE event="policy_driver_candidate"
  EMIT mode="ranked" limit=25
  HALT

evolution:
  allow reorder MATCH SCORE
  allow replace SCORE from registry
  deny external_io
  max_delta = 2
'''

VALID_EXTRACT_DRIVER = '''
driver ExtractTelemetrySummary v1

manifest:
  kind = "extract"
  description = "Extract telemetry summary fields"
  safety = "bounded"

requires:
  capability manifest.read
  capability trace.write
  adapter extractor.telemetry_summary.v1

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


def test_v308_version():
    assert __version__ == "3.1.26"


def test_vm_contract_table_has_complete_metadata_for_each_opcode():
    table = vm_contract_table()
    assert set(table) == {"SCAN", "READ", "MATCH", "EXTRACT", "SCORE", "EMIT", "TRACE", "HALT"}
    for name, row in table.items():
        assert row["opcode"] > 0
        assert row["cost"] > 0
        assert row["deterministic"] is True
        assert row["allowed_driver_classes"]
        assert row["hex"].startswith("0x")


def test_search_driver_passes_vm_contract_audit_and_loads_skeleton():
    package = compile_tddl(VALID_SEARCH_DRIVER)
    audit_vm_contract(package)

    vm = DriverVMSkeleton()
    loaded = vm.load(package)

    assert vm.state is VMState.LOADED
    assert loaded.driver_id == "SearchPolicyDrivers"
    assert loaded.driver_class == "search"
    assert loaded.instruction_count == 9
    assert loaded.package_hash == package.package_hash
    assert loaded.cost_budget > 0


def test_extract_driver_class_cannot_use_scan():
    invalid = VALID_EXTRACT_DRIVER.replace('  READ target="manifest"', '  SCAN scope=".tds" recursive=false limit=10 depth=0\n  READ target="manifest"')
    package = compile_tddl(invalid)
    with pytest.raises(TDDLValidationError, match="SCAN is not allowed for extract"):
        audit_vm_contract(package)


def test_vm_contract_requires_instruction_capabilities():
    invalid = VALID_SEARCH_DRIVER.replace("  capability trace.write\n", "")
    package = compile_tddl(invalid)
    with pytest.raises(TDDLValidationError, match="TRACE requires capability trace.write"):
        audit_vm_contract(package)


def test_vm_skeleton_does_not_execute_bytecode():
    package = compile_tddl(VALID_SEARCH_DRIVER)
    vm = DriverVMSkeleton()
    vm.load(package)
    result = vm.execute({"query": "policy"})

    assert result.ok is False
    assert result.state is VMState.EXECUTION_DISABLED
    assert "disabled" in result.reason
    assert result.trace == ("validate", "load", "execution_disabled")


def test_vm_skeleton_rejects_tampered_package_before_load():
    package = compile_tddl(VALID_SEARCH_DRIVER)
    tampered = BytecodePackage(
        header=package.header,
        manifest=package.manifest,
        capabilities=package.capabilities,
        adapters=package.adapters,
        limits={**package.limits, "max_depth": 99},
        instructions=package.instructions,
        constants=package.constants,
        evolution=package.evolution,
        source_hash=package.source_hash,
        package_hash=package.package_hash,
    )
    vm = DriverVMSkeleton()
    with pytest.raises(TDDLValidationError, match="hash"):
        vm.load(tampered)
    assert vm.state is VMState.REJECTED


def test_malformed_unknown_opcode_is_rejected_by_vm_audit():
    package = compile_tddl(VALID_SEARCH_DRIVER)
    bad_instruction = BytecodeInstruction(opcode=0x7F, name="SCAN", operand_ref=package.instructions[0].operand_ref, line=package.instructions[0].line)
    tampered = BytecodePackage(
        header=package.header,
        manifest=package.manifest,
        capabilities=package.capabilities,
        adapters=package.adapters,
        limits=package.limits,
        instructions=(bad_instruction,) + package.instructions[1:],
        constants=package.constants,
        evolution=package.evolution,
        source_hash=package.source_hash,
        package_hash=package.package_hash,
    )
    with pytest.raises(TDDLValidationError, match="hash|opcode"):
        audit_vm_contract(tampered)


def test_vm_loader_instruction_limit_is_fail_closed():
    package = compile_tddl(VALID_SEARCH_DRIVER)
    vm = DriverVMSkeleton(max_instructions=3)
    with pytest.raises(ValueError, match="instruction count"):
        vm.load(package)
    assert vm.state is VMState.REJECTED

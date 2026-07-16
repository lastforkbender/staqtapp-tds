import pytest

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    BYTECODE_MAGIC,
    BYTECODE_VERSION,
    BytecodePackage,
    TDDLValidationError,
    compile_tddl,
    decompile_to_ir,
    opcode_table,
    parse_tddl,
    validate_bytecode_package,
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


def test_v307_version():
    assert __version__ == "3.5.3"


def test_opcode_table_is_stable_for_first_native_vm_mapping():
    table = opcode_table()
    assert table["SCAN"]["opcode"] == 0x01
    assert table["READ"]["opcode"] == 0x02
    assert table["MATCH"]["opcode"] == 0x03
    assert table["EXTRACT"]["opcode"] == 0x04
    assert table["SCORE"]["opcode"] == 0x05
    assert table["EMIT"]["opcode"] == 0x06
    assert table["TRACE"]["opcode"] == 0x07
    assert table["HALT"]["opcode"] == 0x08


def test_valid_tddl_compiles_to_non_executing_bytecode_package():
    package = compile_tddl(VALID_SEARCH_DRIVER)

    assert package.header["magic"] == BYTECODE_MAGIC
    assert package.header["bytecode_version"] == BYTECODE_VERSION
    assert package.header["driver_id"] == "SearchPolicyDrivers"
    assert package.instructions[0].name == "SCAN"
    assert package.instructions[0].opcode == 0x01
    assert package.instructions[-1].name == "HALT"
    assert package.verify_hash()
    validate_bytecode_package(package)


def test_bytecode_hash_is_deterministic_for_same_source():
    first = compile_tddl(VALID_SEARCH_DRIVER)
    second = compile_tddl(VALID_SEARCH_DRIVER)
    assert first.source_hash == second.source_hash
    assert first.package_hash == second.package_hash
    assert first.to_bytes() == second.to_bytes()


def test_bytecode_hash_changes_when_limits_change():
    first = compile_tddl(VALID_SEARCH_DRIVER)
    changed = compile_tddl(VALID_SEARCH_DRIVER.replace("max_scan = 5000", "max_scan = 4999").replace("limit=5000", "limit=4999", 1))
    assert first.package_hash != changed.package_hash


def test_bytecode_round_trips_to_readable_ir():
    program = parse_tddl(VALID_SEARCH_DRIVER)
    package = compile_tddl(program)
    restored = decompile_to_ir(package)

    assert restored.driver_id == program.driver_id
    assert restored.instruction_names == program.instruction_names
    assert restored.instructions[3].operands["using"] == "predicate.semantic_manifest.v1"
    assert restored.instructions[5].operands["threshold"] == 0.75


def test_bytecode_package_serializes_and_verifies_from_bytes():
    package = compile_tddl(VALID_SEARCH_DRIVER)
    restored = BytecodePackage.from_bytes(package.to_bytes())
    assert restored.package_hash == package.package_hash
    assert restored.verify_hash()


def test_unsafe_tddl_never_reaches_bytecode():
    source = VALID_SEARCH_DRIVER.replace('SCAN scope=".tds"', 'SCAN scope="/etc"', 1)
    with pytest.raises(TDDLValidationError, match="scope"):
        compile_tddl(source)


def test_unsupported_future_instruction_does_not_compile_to_v1_bytecode():
    source = VALID_SEARCH_DRIVER.replace('  SCORE using="scorer.trace_rank.v1" weight="semantic" threshold=0.75', '  MAP using="scorer.trace_rank.v1" from="manifest"')
    with pytest.raises(TDDLValidationError, match="not supported"):
        compile_tddl(source)


def test_tampered_package_fails_hash_validation():
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
    with pytest.raises(TDDLValidationError, match="hash"):
        validate_bytecode_package(tampered)

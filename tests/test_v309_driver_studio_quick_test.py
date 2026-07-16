import pytest

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverState,
    DriverStudioSession,
    StudioGate,
    TDDLValidationError,
    run_studio_quick_test,
    studio_instruction_reference,
)

VALID_STUDIO_DRIVER = '''
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


def test_v309_version():
    assert __version__ == "3.5.3"


def test_studio_instruction_reference_is_complete_for_minimal_editor():
    ref = studio_instruction_reference()
    for name in {"SCAN", "READ", "MATCH", "EXTRACT", "SCORE", "EMIT", "TRACE", "HALT"}:
        assert name in ref
        assert "allowed_operands" in ref[name]
    assert "scope" in ref["SCAN"]["required"]
    assert "target" in ref["READ"]["required"]


def test_driver_studio_quick_test_passes_all_gates_and_activates():
    report = run_studio_quick_test(VALID_STUDIO_DRIVER)

    assert report.ok is True
    assert report.driver_id == "SearchPolicyDrivers"
    assert report.driver_class == "search"
    assert report.package_hash
    assert report.registry_state is DriverState.ACTIVE
    assert report.passed_gates == (
        "learn",
        "syntax",
        "capabilities",
        "bytecode",
        "vm_audit",
        "vm_load",
        "registry_policy",
        "signing",
        "complete",
    )


def test_driver_studio_gates_cannot_be_skipped():
    session = DriverStudioSession()
    with pytest.raises(RuntimeError, match="cannot pass bytecode before learn"):
        session.pass_gate(StudioGate.BYTECODE)


def test_driver_studio_quick_test_rejects_unsafe_source_before_bytecode():
    unsafe = VALID_STUDIO_DRIVER.replace('SCAN scope=".tds"', 'SCAN scope="../outside"')
    with pytest.raises(TDDLValidationError, match="scope"):
        run_studio_quick_test(unsafe)


def test_driver_studio_quick_test_rejects_undeclared_adapter():
    undeclared = VALID_STUDIO_DRIVER.replace('  adapter scorer.trace_rank.v1\n', '')
    with pytest.raises(TDDLValidationError, match="declared"):
        run_studio_quick_test(undeclared)

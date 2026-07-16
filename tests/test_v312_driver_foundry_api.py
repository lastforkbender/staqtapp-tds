from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverFoundry,
    DriverFoundryPolicy,
    DriverFoundryResult,
    DriverRegistry,
    DriverState,
    FoundryStage,
    FoundryStatus,
    VMStatus,
    foundry_capability_matrix,
)

VALID_DRIVER = '''
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


def test_v312_version():
    assert __version__ == "3.5.3"


def test_foundry_capability_matrix_denies_trust_authority():
    matrix = foundry_capability_matrix()

    assert matrix["validate_driver"] is True
    assert matrix["compile_driver"] is True
    assert matrix["audit_driver"] is True
    assert matrix["test_driver"] is True
    assert matrix["submit_candidate"] is True
    assert matrix["approve_driver"] is False
    assert matrix["sign_driver"] is False
    assert matrix["activate_driver"] is False
    assert matrix["write_storage"] is False
    assert matrix["execute_python"] is False
    assert matrix["bypass_policy"] is False


def test_foundry_validates_compiles_audits_and_tests_driver():
    foundry = DriverFoundry()

    validated = foundry.validate_driver(VALID_DRIVER)
    assert validated.ok is True
    assert validated.status is FoundryStatus.VALIDATED
    assert validated.context.driver_id == "SearchPolicyDrivers"
    assert validated.context.instruction_count == 9
    assert validated.context.source_hash.startswith("sha256:")

    built = foundry.compile_driver(VALID_DRIVER)
    assert built.ok is True
    assert built.status is FoundryStatus.COMPILED
    assert built.package is not None
    assert built.context.package_hash == built.package.package_hash

    audited = foundry.audit_driver(built.package)
    assert audited.ok is True
    assert audited.status is FoundryStatus.AUDITED

    tested = foundry.test_driver(built.package, {"records": RECORDS})
    assert tested.ok is True
    assert tested.status is FoundryStatus.TESTED
    assert tested.vm_result is not None
    assert tested.vm_result.status is VMStatus.HALTED
    assert tested.context.vm_status == VMStatus.HALTED.value
    assert tested.metrics["vm_emitted_count"] == 1


def test_foundry_proposal_returns_runtime_faults_as_repair_feedback():
    foundry = DriverFoundry()

    result = foundry.propose_driver(SCAN_KIND_DRIVER, fixtures={"records": RECORDS})

    assert isinstance(result, DriverFoundryResult)
    assert result.ok is False
    assert result.stage is FoundryStage.PROPOSE
    assert result.status is FoundryStatus.TEST_FAILED
    assert result.vm_result is not None
    assert result.vm_result.status is VMStatus.FAULTED
    assert result.faults[0].code == "vm.scan.unsupported_operand"
    assert any("runtime-supported" in hint for hint in result.repair_hints)


def test_foundry_rejects_bad_source_without_raising():
    foundry = DriverFoundry()
    bad_source = VALID_DRIVER.replace('SCAN scope=".tds"', 'SCAN scope="../outside"')

    result = foundry.compile_driver(bad_source)

    assert result.ok is False
    assert result.status is FoundryStatus.SOURCE_REJECTED
    assert result.faults[0].code == "foundry.compile_rejected"
    assert any("SCAN scope" in hint for hint in result.repair_hints)


def test_foundry_candidate_submission_requires_successful_vm_result():
    foundry = DriverFoundry()
    registry = DriverRegistry()
    package = foundry.compile_driver(VALID_DRIVER).package
    assert package is not None

    result = foundry.submit_candidate(package, registry=registry)

    assert result.ok is False
    assert result.status is FoundryStatus.TEST_FAILED
    assert result.faults[0].code == "foundry.candidate.requires_successful_test"
    try:
        registry.require("SearchPolicyDrivers")
    except Exception as exc:
        assert "unknown driver" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("candidate was submitted without test evidence")


def test_foundry_can_submit_candidate_but_not_activate_or_sign():
    foundry = DriverFoundry()
    registry = DriverRegistry()
    package = foundry.compile_driver(VALID_DRIVER).package
    assert package is not None
    vm_result = foundry.test_driver(package, {"records": RECORDS}).vm_result
    assert vm_result is not None and vm_result.ok is True

    result = foundry.submit_candidate(package, registry=registry, vm_result=vm_result)

    assert result.ok is True
    assert result.status is FoundryStatus.CANDIDATE_SUBMITTED
    assert result.registry_state is DriverState.CANDIDATE
    assert registry.require("SearchPolicyDrivers").state is DriverState.CANDIDATE
    assert not hasattr(foundry, "approve_driver")
    assert not hasattr(foundry, "sign_driver")
    assert not hasattr(foundry, "activate_driver")


def test_foundry_policy_cannot_grant_signing_or_activation_authority():
    foundry = DriverFoundry(policy=DriverFoundryPolicy(allow_signing=True, allow_activation=True))
    registry = DriverRegistry()
    package = DriverFoundry().compile_driver(VALID_DRIVER).package
    assert package is not None
    vm_result = DriverFoundry().test_driver(package, {"records": RECORDS}).vm_result
    assert vm_result is not None and vm_result.ok is True

    result = foundry.submit_candidate(package, registry=registry, vm_result=vm_result)

    assert result.ok is False
    assert result.status is FoundryStatus.POLICY_REJECTED
    assert result.faults[0].code == "foundry.policy.invalid_authority"


def test_foundry_test_handles_bad_fixture_as_structured_result():
    foundry = DriverFoundry()
    package = foundry.compile_driver(VALID_DRIVER).package
    assert package is not None

    result = foundry.test_driver(package, {"records": "not-a-list"})

    assert result.ok is False
    assert result.status is FoundryStatus.TEST_FAILED
    assert result.vm_result is not None
    assert result.vm_result.status is VMStatus.INPUT_REJECTED
    assert result.faults[0].code == "vm.input.records"
    assert any("fixtures" in hint for hint in result.repair_hints)


def test_foundry_candidate_submission_can_be_policy_disabled():
    foundry = DriverFoundry(policy=DriverFoundryPolicy(allow_candidate_submission=False))
    registry = DriverRegistry()
    package = DriverFoundry().compile_driver(VALID_DRIVER).package
    assert package is not None
    vm_result = DriverFoundry().test_driver(package, {"records": RECORDS}).vm_result
    assert vm_result is not None

    result = foundry.submit_candidate(package, registry=registry, vm_result=vm_result)

    assert result.ok is False
    assert result.status is FoundryStatus.POLICY_REJECTED
    assert result.faults[0].code == "foundry.policy.candidate_disabled"

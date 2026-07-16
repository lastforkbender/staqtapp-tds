import copy
from dataclasses import replace

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    BytecodePackage,
    DriverExecutionEvidence,
    DriverManifest,
    DriverRegistry,
    DriverRuntimeManager,
    DriverState,
    RuntimeManagerPolicy,
    RuntimeManagerStatus,
    SignaturePolicy,
    VMStatus,
    compile_tddl,
    runtime_manager_capability_matrix,
    sign_payload,
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

DENIED_CAPABILITY_DRIVER = SEARCH_DRIVER.replace(
    "  capability trace.write\n",
    "  capability trace.write\n  capability storage.write\n",
)

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
]


def _manifest_from_package(package: BytecodePackage) -> DriverManifest:
    return DriverManifest.from_mapping(
        {
            "driver_id": package.header["driver_id"],
            "version": package.header["driver_version"],
            "kind": package.manifest["kind"],
            "description": package.manifest.get("description", ""),
            "safety": package.manifest.get("safety", "bounded"),
            "capabilities": package.capabilities,
            "adapters": package.adapters,
            "generation": 0,
        }
    )


def _active_registry_for(package: BytecodePackage) -> DriverRegistry:
    signature_policy = SignaturePolicy()
    signature_policy.approve_signer("admin", b"runtime-secret")
    registry = DriverRegistry(signature_policy=signature_policy)
    record = registry.add_candidate(_manifest_from_package(package), test_report_hash="evidence-hash")
    registry.approve(record.manifest.driver_id)
    signature = sign_payload(record.manifest.canonical_payload(), signer="admin", secret=b"runtime-secret")
    registry.attach_signature(record.manifest.driver_id, signature)
    registry.activate(record.manifest.driver_id)
    return registry


def test_v313_version():
    assert __version__ == "3.5.3"


def test_runtime_manager_capability_matrix_denies_trust_authority_and_storage_writes():
    matrix = runtime_manager_capability_matrix(RuntimeManagerPolicy(require_registry_active=True, require_signature_accept=True))

    assert matrix["validate_package"] is True
    assert matrix["audit_package"] is True
    assert matrix["execute_driver_vm"] is True
    assert matrix["produce_execution_evidence"] is True
    assert matrix["require_registry_active"] is True
    assert matrix["require_signature_accept"] is True
    assert matrix["write_storage"] is False
    assert matrix["approve_driver"] is False
    assert matrix["sign_driver"] is False
    assert matrix["activate_driver"] is False
    assert matrix["execute_python"] is False
    assert matrix["bypass_policy"] is False


def test_runtime_manager_executes_package_and_returns_approval_grade_evidence():
    package = compile_tddl(SEARCH_DRIVER)
    manager = DriverRuntimeManager()

    evidence = manager.execute_package(package, {"records": RECORDS})

    assert isinstance(evidence, DriverExecutionEvidence)
    assert evidence.ok is True
    assert evidence.status is RuntimeManagerStatus.EXECUTED
    assert evidence.recommendation == "candidate_ready"
    assert evidence.driver_id == "SearchPolicyDrivers"
    assert evidence.package_hash == package.package_hash
    assert evidence.source_hash == package.source_hash
    assert evidence.snapshot_hash.startswith("sha256:")
    assert evidence.evidence_hash.startswith("sha256:")
    assert evidence.session_id.startswith("tds-exec-")
    assert evidence.trace_complete is True
    assert evidence.deterministic is True
    assert evidence.vm_result is not None
    assert evidence.vm_result.status is VMStatus.HALTED
    assert evidence.policy_report["snapshot_preserved"] is True
    assert evidence.metrics["vm_emitted_count"] == 1


def test_runtime_manager_evidence_is_deterministic_for_same_package_and_snapshot():
    package = compile_tddl(SEARCH_DRIVER)
    manager = DriverRuntimeManager()

    first = manager.execute_package(package, {"records": RECORDS})
    second = manager.execute_package(package, {"records": copy.deepcopy(RECORDS)})

    assert first.ok is True and second.ok is True
    assert first.snapshot_hash == second.snapshot_hash
    assert first.session_id == second.session_id
    assert first.evidence_hash == second.evidence_hash


def test_runtime_manager_does_not_mutate_caller_snapshot():
    package = compile_tddl(SEARCH_DRIVER)
    fixtures = {"records": copy.deepcopy(RECORDS)}
    original = copy.deepcopy(fixtures)

    evidence = DriverRuntimeManager().execute_package(package, fixtures)

    assert evidence.ok is True
    assert fixtures == original
    assert evidence.policy_report["snapshot_preserved"] is True


def test_runtime_manager_rejects_tampered_package_without_raising():
    package = compile_tddl(SEARCH_DRIVER)
    tampered = replace(package, package_hash="sha256:not-the-real-package-hash")

    evidence = DriverRuntimeManager().execute_package(tampered, {"records": RECORDS})

    assert evidence.ok is False
    assert evidence.status is RuntimeManagerStatus.PACKAGE_REJECTED
    assert evidence.faults[0].code == "runtime.package_rejected"
    assert "hash" in evidence.reason.lower()
    assert evidence.recommendation == "reject"


def test_runtime_manager_rejects_denied_capability_before_execution():
    package = compile_tddl(DENIED_CAPABILITY_DRIVER)

    evidence = DriverRuntimeManager().execute_package(package, {"records": RECORDS})

    assert evidence.ok is False
    assert evidence.status is RuntimeManagerStatus.POLICY_REJECTED
    assert evidence.faults[0].code == "runtime.policy.denied_capability"
    assert "storage.write" in evidence.reason
    assert evidence.vm_result is None


def test_runtime_manager_rejects_driver_class_outside_policy():
    package = compile_tddl(EXTRACT_DRIVER)
    manager = DriverRuntimeManager(policy=RuntimeManagerPolicy(allowed_driver_classes=frozenset({"search"})))

    evidence = manager.execute_package(package, {"records": RECORDS})

    assert evidence.ok is False
    assert evidence.status is RuntimeManagerStatus.POLICY_REJECTED
    assert evidence.faults[0].code == "runtime.policy.driver_class"
    assert evidence.capability_report["driver_class"] == "extract"


def test_runtime_manager_registry_gate_rejects_non_active_candidate():
    package = compile_tddl(SEARCH_DRIVER)
    registry = DriverRegistry()
    registry.add_candidate(_manifest_from_package(package), test_report_hash="evidence-hash")
    manager = DriverRuntimeManager(policy=RuntimeManagerPolicy(require_registry_active=True))

    evidence = manager.execute_package(package, {"records": RECORDS}, registry=registry)

    assert evidence.ok is False
    assert evidence.status is RuntimeManagerStatus.REGISTRY_REJECTED
    assert evidence.registry_state == DriverState.CANDIDATE.value
    assert evidence.faults[0].code == "runtime.registry.not_active"


def test_runtime_manager_registry_and_signature_gate_accepts_active_signed_driver():
    package = compile_tddl(SEARCH_DRIVER)
    registry = _active_registry_for(package)
    manager = DriverRuntimeManager(policy=RuntimeManagerPolicy(require_registry_active=True, require_signature_accept=True))

    evidence = manager.execute_package(package, {"records": RECORDS}, registry=registry)

    assert evidence.ok is True
    assert evidence.status is RuntimeManagerStatus.EXECUTED
    assert evidence.registry_state == DriverState.ACTIVE.value
    assert evidence.signature_verdict == "accept"
    assert evidence.policy_report["require_registry_active"] is True
    assert evidence.policy_report["require_signature_accept"] is True


def test_runtime_manager_signature_gate_rejects_bad_active_signature():
    package = compile_tddl(SEARCH_DRIVER)
    registry = _active_registry_for(package)
    record = registry.require("SearchPolicyDrivers")
    record.signature = "tds-sig-v1:admin:bad"
    manager = DriverRuntimeManager(policy=RuntimeManagerPolicy(require_registry_active=True, require_signature_accept=True))

    evidence = manager.execute_package(package, {"records": RECORDS}, registry=registry)

    assert evidence.ok is False
    assert evidence.status is RuntimeManagerStatus.SIGNATURE_REJECTED
    assert evidence.signature_verdict == "bad_signature"
    assert evidence.faults[0].code == "runtime.signature.rejected"


def test_runtime_manager_bad_fixture_returns_input_rejected_evidence():
    package = compile_tddl(SEARCH_DRIVER)

    evidence = DriverRuntimeManager().execute_package(package, {"records": "not-a-sequence"})

    assert evidence.ok is False
    assert evidence.status is RuntimeManagerStatus.INPUT_REJECTED
    assert evidence.faults[0].code == "runtime.input_rejected"
    assert evidence.vm_result is None


def test_runtime_manager_preserves_vm_runtime_faults_as_evidence():
    source = SEARCH_DRIVER.replace('SCAN scope=".tds" recursive=true limit=5000 depth=8', 'SCAN scope=".tds" recursive=true limit=5000 depth=8 kind="driver"')
    package = compile_tddl(source)

    evidence = DriverRuntimeManager().execute_package(package, {"records": RECORDS})

    assert evidence.ok is False
    assert evidence.status is RuntimeManagerStatus.RUNTIME_FAULTED
    assert evidence.vm_result is not None
    assert evidence.vm_result.status is VMStatus.FAULTED
    assert evidence.faults[0].code == "vm.scan.unsupported_operand"
    assert evidence.recommendation == "hold"

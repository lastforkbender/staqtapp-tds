"""Non-GUI Driver Studio certification quick-test model.

v3.0.9 adds a Class A readiness layer for the future PyQt5 Driver Studio.
It does not render a UI and it does not execute drivers. Instead, it models the
same gated workflow the Studio must enforce: learn, validate, compile, audit,
load, and registry-sign only after each previous gate passes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from .audit import audit_vm_contract
from .bytecode import BytecodePackage, compile_tddl
from .manifest import DriverManifest
from .registry import DriverRegistry, DriverState
from .signature import SignaturePolicy, SignatureVerdict, sign_payload
from .tddl import TDDLValidationError, instruction_specs, parse_tddl
from .vm import DriverVMSkeleton, VMState


class StudioGate(str, Enum):
    """Ordered Driver Studio certification gates."""

    LEARN = "learn"
    SYNTAX = "syntax"
    CAPABILITIES = "capabilities"
    BYTECODE = "bytecode"
    VM_AUDIT = "vm_audit"
    VM_LOAD = "vm_load"
    REGISTRY_POLICY = "registry_policy"
    SIGNING = "signing"
    COMPLETE = "complete"


_STUDIO_GATE_ORDER: tuple[StudioGate, ...] = (
    StudioGate.LEARN,
    StudioGate.SYNTAX,
    StudioGate.CAPABILITIES,
    StudioGate.BYTECODE,
    StudioGate.VM_AUDIT,
    StudioGate.VM_LOAD,
    StudioGate.REGISTRY_POLICY,
    StudioGate.SIGNING,
    StudioGate.COMPLETE,
)


@dataclass(frozen=True, slots=True)
class StudioGateResult:
    gate: StudioGate
    passed: bool
    detail: str


@dataclass(slots=True)
class DriverStudioSession:
    """Minimal gated certification session for future Driver Studio UX tests."""

    completed: list[StudioGate] = field(default_factory=list)

    def pass_gate(self, gate: StudioGate) -> None:
        expected = _STUDIO_GATE_ORDER[len(self.completed)]
        if gate is not expected:
            raise RuntimeError(f"cannot pass {gate.value} before {expected.value}")
        self.completed.append(gate)

    @property
    def next_gate(self) -> StudioGate:
        if len(self.completed) >= len(_STUDIO_GATE_ORDER):
            return StudioGate.COMPLETE
        return _STUDIO_GATE_ORDER[len(self.completed)]


@dataclass(frozen=True, slots=True)
class DriverStudioQuickTestReport:
    """Immutable report emitted by the Class A Studio quick test."""

    ok: bool
    driver_id: str
    driver_class: str
    package_hash: str
    registry_state: DriverState
    gate_results: tuple[StudioGateResult, ...]

    @property
    def passed_gates(self) -> tuple[str, ...]:
        return tuple(result.gate.value for result in self.gate_results if result.passed)


def studio_instruction_reference() -> Mapping[str, Mapping[str, object]]:
    """Return compact instruction reference data for the future Learn panel."""

    reference: dict[str, Mapping[str, object]] = {}
    for name, spec in instruction_specs().items():
        reference[name] = {
            "required": tuple(sorted(spec.required)),
            "optional": tuple(sorted(spec.optional)),
            "allowed_operands": tuple(sorted(spec.allowed)),
            "allowed_values": {key: tuple(sorted(values)) for key, values in spec.allowed_values.items()},
        }
    return reference


def run_studio_quick_test(
    source: str,
    *,
    signer: str = "studio-admin",
    secret: bytes = b"local-driver-studio-secret",
) -> DriverStudioQuickTestReport:
    """Run the non-GUI Driver Studio Class A certification path.

    The path deliberately mirrors the future PyQt5 Studio workflow. Each gate
    must pass before the next is attempted. Any validation failure propagates so
    tests and the eventual UI can display the precise fail-closed reason.
    """

    session = DriverStudioSession()
    results: list[StudioGateResult] = []

    reference = studio_instruction_reference()
    if not reference:
        raise RuntimeError("instruction reference is empty")
    session.pass_gate(StudioGate.LEARN)
    results.append(StudioGateResult(StudioGate.LEARN, True, "instruction reference available"))

    program = parse_tddl(source)
    session.pass_gate(StudioGate.SYNTAX)
    results.append(StudioGateResult(StudioGate.SYNTAX, True, f"parsed {len(program.instructions)} instructions"))

    if not program.capabilities:
        raise TDDLValidationError("driver must declare capabilities before Studio progression")
    session.pass_gate(StudioGate.CAPABILITIES)
    results.append(StudioGateResult(StudioGate.CAPABILITIES, True, f"{len(program.capabilities)} capabilities declared"))

    package = compile_tddl(program)
    session.pass_gate(StudioGate.BYTECODE)
    results.append(StudioGateResult(StudioGate.BYTECODE, True, f"compiled package {package.package_hash[:12]}"))

    audit_vm_contract(package)
    session.pass_gate(StudioGate.VM_AUDIT)
    results.append(StudioGateResult(StudioGate.VM_AUDIT, True, "VM contract audit passed"))

    vm = DriverVMSkeleton()
    loaded = vm.load(package)
    if vm.state is not VMState.LOADED:
        raise RuntimeError("VM skeleton did not load validated package")
    session.pass_gate(StudioGate.VM_LOAD)
    results.append(StudioGateResult(StudioGate.VM_LOAD, True, f"loaded {loaded.instruction_count} instructions"))

    manifest = _manifest_from_package(package)
    policy = SignaturePolicy()
    policy.approve_signer(signer, secret)
    registry = DriverRegistry(signature_policy=policy)
    test_report_hash = _test_report_hash(package, results)
    registry.add_candidate(manifest, test_report_hash=test_report_hash)
    registry.approve(manifest.driver_id)
    session.pass_gate(StudioGate.REGISTRY_POLICY)
    results.append(StudioGateResult(StudioGate.REGISTRY_POLICY, True, "candidate approved with test report"))

    signature = sign_payload(manifest.canonical_payload(), signer=signer, secret=secret)
    if policy.evaluate(manifest.canonical_payload(), signature) is not SignatureVerdict.ACCEPT:
        raise RuntimeError("generated Studio signature was not accepted")
    registry.attach_signature(manifest.driver_id, signature)
    record = registry.activate(manifest.driver_id)
    session.pass_gate(StudioGate.SIGNING)
    results.append(StudioGateResult(StudioGate.SIGNING, True, "driver signed and activated"))

    session.pass_gate(StudioGate.COMPLETE)
    results.append(StudioGateResult(StudioGate.COMPLETE, True, "Studio quick test complete"))

    return DriverStudioQuickTestReport(
        ok=True,
        driver_id=manifest.driver_id,
        driver_class=manifest.kind,
        package_hash=package.package_hash,
        registry_state=record.state,
        gate_results=tuple(results),
    )


def _manifest_from_package(package: BytecodePackage) -> DriverManifest:
    return DriverManifest.from_mapping(
        {
            "driver_id": str(package.header["driver_id"]),
            "version": int(package.header["driver_version"]),
            "kind": str(package.manifest["kind"]),
            "description": str(package.manifest.get("description", "")),
            "safety": str(package.manifest.get("safety", "bounded")),
            "capabilities": tuple(package.capabilities),
            "adapters": tuple(package.adapters),
            "generation": 0,
        }
    )


def _test_report_hash(package: BytecodePackage, results: list[StudioGateResult]) -> str:
    h = hashlib.sha256()
    h.update(package.package_hash.encode("utf-8"))
    for result in results:
        h.update(result.gate.value.encode("utf-8"))
        h.update(b"\0")
        h.update(str(result.passed).encode("utf-8"))
        h.update(b"\0")
        h.update(result.detail.encode("utf-8"))
    return h.hexdigest()

"""AI-safe Driver Foundry API.

v3.1.2 adds a survivable API seam for AI-assisted driver generation. The
Foundry can validate, compile, audit, test, and submit registry *candidates*;
it cannot approve, sign, activate, or bypass policy. Expected failures are
returned as structured results so an AI agent, Runtime Manager, or Studio can
iterate rapidly without halting the host process or touching storage internals.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .audit import audit_vm_contract
from .bytecode import BytecodePackage, compile_tddl
from .manifest import DriverManifest
from .registry import DriverRegistry, DriverState
from .tddl import TDDLProgram, TDDLValidationError, parse_tddl
from .vm import DriverVMResult, DriverVMRuntime, VMStatus


class FoundryStage(str, Enum):
    """Driver Foundry pipeline stages exposed to AI/Studio callers."""

    PROPOSE = "propose"
    VALIDATE = "validate"
    COMPILE = "compile"
    AUDIT = "audit"
    TEST = "test"
    CANDIDATE = "candidate"


class FoundryStatus(str, Enum):
    """Non-halting status values for Driver Foundry operations."""

    ACCEPTED = "accepted"
    VALIDATED = "validated"
    COMPILED = "compiled"
    AUDITED = "audited"
    TESTED = "tested"
    CANDIDATE_SUBMITTED = "candidate_submitted"
    SOURCE_REJECTED = "source_rejected"
    PACKAGE_REJECTED = "package_rejected"
    TEST_FAILED = "test_failed"
    INPUT_REJECTED = "input_rejected"
    POLICY_REJECTED = "policy_rejected"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class FoundryFault:
    """Structured Foundry fault for repair loops and Studio display."""

    code: str
    message: str
    stage: FoundryStage
    severity: str = "error"
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class DriverFoundryContext:
    """Compact context attached to every Driver Foundry result."""

    stage: FoundryStage
    driver_id: str | None = None
    driver_version: int | None = None
    driver_class: str | None = None
    source_hash: str | None = None
    package_hash: str | None = None
    instruction_count: int = 0
    capability_count: int = 0
    adapter_count: int = 0
    registry_state: str | None = None
    vm_status: str | None = None


@dataclass(frozen=True, slots=True)
class DriverFoundryResult:
    """Result-first envelope for Driver Foundry API calls.

    This is intentionally broader than :class:`DriverVMResult`: it can carry
    source validation, compiled bytecode, audit evidence, a VM test result, and
    registry-candidate submission evidence without giving the caller authority
    to approve, sign, or activate a driver.
    """

    ok: bool
    stage: FoundryStage
    status: FoundryStatus
    reason: str
    context: DriverFoundryContext
    faults: tuple[FoundryFault, ...] = ()
    program: TDDLProgram | None = None
    package: BytecodePackage | None = None
    vm_result: DriverVMResult | None = None
    registry_state: DriverState | None = None
    metrics: Mapping[str, int | str | bool | None] = field(default_factory=dict)
    repair_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverFoundryPolicy:
    """Safe authority policy for AI-facing Driver Foundry calls."""

    allow_candidate_submission: bool = True
    allow_signing: bool = False
    allow_activation: bool = False
    require_test_success_for_candidate: bool = True
    max_cost: int = 100_000
    max_instructions: int = 1024


class DriverFoundry:
    """AI-safe build/test/candidate API for TDS drivers.

    The Foundry deliberately stops before trust authority. It can create a
    registry candidate with a deterministic test-report hash, but approval,
    signing, activation, retirement, and revocation remain Registry/Policy
    responsibilities outside this API.
    """

    def __init__(self, *, policy: DriverFoundryPolicy | None = None) -> None:
        self.policy = policy or DriverFoundryPolicy()

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the Foundry authority matrix for AI and Studio surfaces."""

        return {
            "validate_driver": True,
            "compile_driver": True,
            "audit_driver": True,
            "test_driver": True,
            "submit_candidate": self.policy.allow_candidate_submission,
            "approve_driver": False,
            "sign_driver": False,
            "activate_driver": False,
            "write_storage": False,
            "execute_python": False,
            "bypass_policy": False,
        }

    def propose_driver(self, source: str, *, fixtures: Mapping[str, Any] | None = None) -> DriverFoundryResult:
        """Run the AI proposal path: validate, compile, audit, and optionally test."""

        result = self.compile_driver(source)
        if not result.ok or result.package is None:
            return _with_stage(result, FoundryStage.PROPOSE)
        audit = self.audit_driver(result.package)
        if not audit.ok:
            return _with_stage(audit, FoundryStage.PROPOSE)
        if fixtures is None:
            return _result(
                ok=True,
                stage=FoundryStage.PROPOSE,
                status=FoundryStatus.ACCEPTED,
                reason="driver proposal compiled and audited; no fixtures supplied for runtime test",
                program=result.program,
                package=result.package,
                repair_hints=("Supply fixtures with records to exercise the proposal in DriverVMRuntime.",),
            )
        tested = self.test_driver(result.package, fixtures)
        return _with_stage(tested, FoundryStage.PROPOSE)

    def validate_driver(self, source: str) -> DriverFoundryResult:
        """Validate TDDL source without compiling or executing it."""

        try:
            program = parse_tddl(source)
            return _result(
                ok=True,
                stage=FoundryStage.VALIDATE,
                status=FoundryStatus.VALIDATED,
                reason="TDDL source validated",
                program=program,
                source_hash=_source_hash(source),
            )
        except TDDLValidationError as exc:
            return _fault_result(
                stage=FoundryStage.VALIDATE,
                status=FoundryStatus.SOURCE_REJECTED,
                code="foundry.source_rejected",
                message=str(exc),
                source_hash=_source_hash(source),
                hints=_hints_for_message(str(exc)),
            )
        except Exception as exc:
            return _fault_result(
                stage=FoundryStage.VALIDATE,
                status=FoundryStatus.INTERNAL_ERROR,
                code="foundry.internal_error",
                message=f"internal Foundry validation error: {exc}",
                source_hash=_source_hash(source),
                recoverable=False,
            )

    def compile_driver(self, source: str) -> DriverFoundryResult:
        """Compile TDDL source to a deterministic bytecode package."""

        try:
            program = parse_tddl(source)
            package = compile_tddl(program)
            return _result(
                ok=True,
                stage=FoundryStage.COMPILE,
                status=FoundryStatus.COMPILED,
                reason="TDDL source compiled to bytecode package",
                program=program,
                package=package,
                source_hash=_source_hash(source),
            )
        except TDDLValidationError as exc:
            return _fault_result(
                stage=FoundryStage.COMPILE,
                status=FoundryStatus.SOURCE_REJECTED,
                code="foundry.compile_rejected",
                message=str(exc),
                source_hash=_source_hash(source),
                hints=_hints_for_message(str(exc)),
            )
        except Exception as exc:
            return _fault_result(
                stage=FoundryStage.COMPILE,
                status=FoundryStatus.INTERNAL_ERROR,
                code="foundry.internal_error",
                message=f"internal Foundry compile error: {exc}",
                source_hash=_source_hash(source),
                recoverable=False,
            )

    def audit_driver(self, package: BytecodePackage) -> DriverFoundryResult:
        """Audit a compiled package against VM contract rules."""

        try:
            audit_vm_contract(package)
            return _result(
                ok=True,
                stage=FoundryStage.AUDIT,
                status=FoundryStatus.AUDITED,
                reason="bytecode package passed VM contract audit",
                package=package,
            )
        except (TDDLValidationError, ValueError) as exc:
            return _fault_result(
                stage=FoundryStage.AUDIT,
                status=FoundryStatus.PACKAGE_REJECTED,
                code="foundry.package_rejected",
                message=str(exc),
                package=package,
                hints=_hints_for_message(str(exc)),
            )
        except Exception as exc:
            return _fault_result(
                stage=FoundryStage.AUDIT,
                status=FoundryStatus.INTERNAL_ERROR,
                code="foundry.internal_error",
                message=f"internal Foundry audit error: {exc}",
                package=package,
                recoverable=False,
            )

    def test_driver(self, package: BytecodePackage, fixtures: Mapping[str, Any]) -> DriverFoundryResult:
        """Execute a package through DriverVMRuntime against safe snapshot fixtures."""

        try:
            vm = DriverVMRuntime(max_instructions=self.policy.max_instructions, max_cost=self.policy.max_cost)
            vm.load(package)
            vm_result = vm.execute(fixtures)
            status = FoundryStatus.TESTED if vm_result.ok else FoundryStatus.TEST_FAILED
            return _result(
                ok=vm_result.ok,
                stage=FoundryStage.TEST,
                status=status,
                reason="driver runtime test passed" if vm_result.ok else f"driver runtime test failed: {vm_result.reason}",
                package=package,
                vm_result=vm_result,
                faults=tuple(
                    FoundryFault(
                        code=fault.code,
                        message=fault.message,
                        stage=FoundryStage.TEST,
                        severity=fault.severity,
                        recoverable=fault.recoverable,
                    )
                    for fault in vm_result.faults
                ),
                repair_hints=_hints_for_vm_result(vm_result),
            )
        except (TDDLValidationError, ValueError) as exc:
            return _fault_result(
                stage=FoundryStage.TEST,
                status=FoundryStatus.PACKAGE_REJECTED,
                code="foundry.test_rejected",
                message=str(exc),
                package=package,
                hints=_hints_for_message(str(exc)),
            )
        except Exception as exc:
            return _fault_result(
                stage=FoundryStage.TEST,
                status=FoundryStatus.INTERNAL_ERROR,
                code="foundry.internal_error",
                message=f"internal Foundry test error: {exc}",
                package=package,
                recoverable=False,
            )

    def submit_candidate(
        self,
        package: BytecodePackage,
        *,
        registry: DriverRegistry,
        vm_result: DriverVMResult | None = None,
    ) -> DriverFoundryResult:
        """Submit an audited/tested package as a registry candidate only.

        This method never approves, signs, or activates. If policy requires a
        successful runtime test, ``vm_result`` must be a successful
        :class:`DriverVMResult` from ``test_driver``.
        """

        if not self.policy.allow_candidate_submission:
            return _fault_result(
                stage=FoundryStage.CANDIDATE,
                status=FoundryStatus.POLICY_REJECTED,
                code="foundry.policy.candidate_disabled",
                message="candidate submission is disabled by Foundry policy",
                package=package,
                vm_result=vm_result,
            )
        if self.policy.allow_signing or self.policy.allow_activation:
            return _fault_result(
                stage=FoundryStage.CANDIDATE,
                status=FoundryStatus.POLICY_REJECTED,
                code="foundry.policy.invalid_authority",
                message="DriverFoundry policy may not grant signing or activation authority",
                package=package,
                vm_result=vm_result,
                recoverable=False,
            )
        if self.policy.require_test_success_for_candidate and (vm_result is None or not vm_result.ok):
            return _fault_result(
                stage=FoundryStage.CANDIDATE,
                status=FoundryStatus.TEST_FAILED,
                code="foundry.candidate.requires_successful_test",
                message="candidate submission requires a successful DriverVMResult",
                package=package,
                vm_result=vm_result,
                hints=("Run test_driver(package, fixtures) and submit only when result.ok is True.",),
            )
        audit = self.audit_driver(package)
        if not audit.ok:
            return _with_stage(audit, FoundryStage.CANDIDATE)
        try:
            manifest = _manifest_from_package(package)
            report_hash = _test_report_hash(package, vm_result)
            record = registry.add_candidate(manifest, test_report_hash=report_hash)
            return _result(
                ok=True,
                stage=FoundryStage.CANDIDATE,
                status=FoundryStatus.CANDIDATE_SUBMITTED,
                reason="driver package submitted as registry candidate; approval/signing/activation remain external",
                package=package,
                vm_result=vm_result,
                registry_state=record.state,
            )
        except Exception as exc:
            return _fault_result(
                stage=FoundryStage.CANDIDATE,
                status=FoundryStatus.POLICY_REJECTED,
                code="foundry.registry_rejected",
                message=str(exc),
                package=package,
                vm_result=vm_result,
                hints=_hints_for_message(str(exc)),
            )


def foundry_capability_matrix(policy: DriverFoundryPolicy | None = None) -> Mapping[str, bool]:
    """Convenience function for displaying the AI-safe Foundry authority map."""

    return DriverFoundry(policy=policy).capability_matrix()


def _result(
    *,
    ok: bool,
    stage: FoundryStage,
    status: FoundryStatus,
    reason: str,
    program: TDDLProgram | None = None,
    package: BytecodePackage | None = None,
    vm_result: DriverVMResult | None = None,
    registry_state: DriverState | None = None,
    faults: tuple[FoundryFault, ...] = (),
    repair_hints: tuple[str, ...] = (),
    source_hash: str | None = None,
) -> DriverFoundryResult:
    context = _context(
        stage=stage,
        program=program,
        package=package,
        vm_result=vm_result,
        registry_state=registry_state,
        source_hash=source_hash,
    )
    metrics: dict[str, int | str | bool | None] = {
        "ok": ok,
        "stage": stage.value,
        "status": status.value,
        "fault_count": len(faults),
        "instruction_count": context.instruction_count,
        "capability_count": context.capability_count,
        "adapter_count": context.adapter_count,
        "registry_state": context.registry_state,
        "vm_status": context.vm_status,
    }
    if vm_result is not None:
        metrics.update(
            {
                "vm_cost_used": vm_result.cost_used,
                "vm_emitted_count": vm_result.context.emitted_count,
                "vm_records_seen": vm_result.context.records_seen,
            }
        )
    return DriverFoundryResult(
        ok=ok,
        stage=stage,
        status=status,
        reason=reason,
        context=context,
        faults=faults,
        program=program,
        package=package,
        vm_result=vm_result,
        registry_state=registry_state,
        metrics=metrics,
        repair_hints=repair_hints,
    )


def _fault_result(
    *,
    stage: FoundryStage,
    status: FoundryStatus,
    code: str,
    message: str,
    source_hash: str | None = None,
    package: BytecodePackage | None = None,
    vm_result: DriverVMResult | None = None,
    hints: Sequence[str] = (),
    recoverable: bool = True,
) -> DriverFoundryResult:
    fault = FoundryFault(code=code, message=message, stage=stage, recoverable=recoverable)
    return _result(
        ok=False,
        stage=stage,
        status=status,
        reason=message,
        package=package,
        vm_result=vm_result,
        faults=(fault,),
        repair_hints=tuple(hints),
        source_hash=source_hash,
    )


def _with_stage(result: DriverFoundryResult, stage: FoundryStage) -> DriverFoundryResult:
    faults = tuple(
        FoundryFault(
            code=fault.code,
            message=fault.message,
            stage=stage,
            severity=fault.severity,
            recoverable=fault.recoverable,
        )
        for fault in result.faults
    )
    return _result(
        ok=result.ok,
        stage=stage,
        status=result.status,
        reason=result.reason,
        program=result.program,
        package=result.package,
        vm_result=result.vm_result,
        registry_state=result.registry_state,
        faults=faults,
        repair_hints=result.repair_hints,
        source_hash=result.context.source_hash,
    )


def _context(
    *,
    stage: FoundryStage,
    program: TDDLProgram | None,
    package: BytecodePackage | None,
    vm_result: DriverVMResult | None,
    registry_state: DriverState | None,
    source_hash: str | None,
) -> DriverFoundryContext:
    driver_id: str | None = None
    driver_version: int | None = None
    driver_class: str | None = None
    instruction_count = 0
    capability_count = 0
    adapter_count = 0
    package_hash: str | None = None

    if program is not None:
        driver_id = program.driver_id
        driver_version = program.version
        driver_class = str(program.manifest.get("kind"))
        instruction_count = len(program.instructions)
        capability_count = len(program.capabilities)
        adapter_count = len(program.adapters)
    if package is not None:
        driver_id = str(package.header.get("driver_id"))
        driver_version = int(package.header.get("driver_version", 0))
        driver_class = str(package.manifest.get("kind"))
        instruction_count = len(package.instructions)
        capability_count = len(package.capabilities)
        adapter_count = len(package.adapters)
        package_hash = package.package_hash
    if vm_result is not None:
        driver_id = vm_result.driver_id or driver_id
        driver_version = vm_result.driver_version or driver_version
        driver_class = vm_result.context.driver_class or driver_class
        package_hash = vm_result.package_hash or package_hash

    return DriverFoundryContext(
        stage=stage,
        driver_id=driver_id,
        driver_version=driver_version,
        driver_class=driver_class,
        source_hash=source_hash,
        package_hash=package_hash,
        instruction_count=instruction_count,
        capability_count=capability_count,
        adapter_count=adapter_count,
        registry_state=registry_state.value if registry_state else None,
        vm_status=vm_result.status.value if vm_result else None,
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


def _source_hash(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _test_report_hash(package: BytecodePackage, vm_result: DriverVMResult | None) -> str:
    payload = {
        "package_hash": package.package_hash,
        "vm_ok": vm_result.ok if vm_result else None,
        "vm_status": vm_result.status.value if vm_result else None,
        "vm_reason": vm_result.reason if vm_result else None,
        "vm_metrics": dict(vm_result.metrics) if vm_result else {},
        "faults": [fault.code for fault in vm_result.faults] if vm_result else [],
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _hints_for_message(message: str) -> tuple[str, ...]:
    lowered = message.lower()
    hints: list[str] = []
    if "scope" in lowered:
        hints.append("Keep SCAN scope inside .tds or .tds/... and avoid path traversal.")
    if "capability" in lowered:
        hints.append("Declare required capabilities in the requires section before compiling.")
    if "adapter" in lowered:
        hints.append("Declare adapters explicitly and use only approved bounded adapter names.")
    if "halt" in lowered:
        hints.append("End every TDDL program with exactly one HALT instruction.")
    if "predicate" in lowered or "match" in lowered:
        hints.append("For MATCH field=..., provide a predicate such as eq, contains, exists, regex_limited, or range.")
    if not hints:
        hints.append("Review TDDL syntax, manifest kind, capabilities, limits, and instruction operands.")
    return tuple(hints)


def _hints_for_vm_result(vm_result: DriverVMResult) -> tuple[str, ...]:
    if vm_result.ok:
        return ()
    hints: list[str] = []
    if vm_result.status is VMStatus.INPUT_REJECTED:
        hints.append("Supply fixtures as {'records': [mapping, ...]} using in-memory snapshots only.")
    if vm_result.status is VMStatus.BUDGET_EXCEEDED:
        hints.append("Reduce scan limits, instruction count, or runtime cost before retesting.")
    for fault in vm_result.faults:
        if "unsupported" in fault.code:
            hints.append("Use only runtime-supported operands/adapters or keep the feature behind validation-only tests.")
        if "match" in fault.code:
            hints.append("Repair MATCH predicates so they are both valid and runtime-supported.")
    if not hints:
        hints.append("Inspect DriverVMResult.trace, faults, and context for the repair target.")
    return tuple(dict.fromkeys(hints))

"""Driver Runtime Manager and execution evidence hardening.

v3.1.3 introduces the approval-grade execution layer between DriverFoundry,
Registry/Policy, and DriverVMRuntime. The Runtime Manager does not execute
arbitrary Python, does not write storage, and does not hold storage handles. It
validates compiled bytecode packages, applies runtime policy gates, optionally
requires active signed registry trust, executes only against immutable in-memory
record snapshots, and returns deterministic execution evidence suitable for
future admin review and Driver Studio panels.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .audit import audit_vm_contract
from .bytecode import BytecodePackage, validate_bytecode_package
from .manifest import DriverManifest
from .registry import DriverRegistry, DriverState, RegistryError
from .signature import SignatureVerdict
from .tddl import TDDLValidationError
from .vm import DriverVMResult, DriverVMRuntime, VMStatus


class RuntimeManagerStatus(str, Enum):
    """Non-halting status values for managed Driver VM execution."""

    EXECUTED = "executed"
    PACKAGE_REJECTED = "package_rejected"
    POLICY_REJECTED = "policy_rejected"
    REGISTRY_REJECTED = "registry_rejected"
    SIGNATURE_REJECTED = "signature_rejected"
    INPUT_REJECTED = "input_rejected"
    RUNTIME_FAULTED = "runtime_faulted"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class RuntimeManagerFault:
    """Structured manager-level fault for approval and Studio surfaces."""

    code: str
    message: str
    severity: str = "error"
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class RuntimeManagerPolicy:
    """Policy gates enforced before DriverVMRuntime execution."""

    max_cost: int = 100_000
    max_instructions: int = 1024
    max_snapshot_records: int = 100_000
    allowed_driver_classes: frozenset[str] = frozenset({"search", "extract", "rank", "adapter", "policy"})
    allowed_capabilities: frozenset[str] | None = None
    denied_capabilities: frozenset[str] = frozenset({"storage.write", "python.exec", "policy.bypass", "external.io"})
    require_registry_active: bool = False
    require_signature_accept: bool = False
    require_trace_complete: bool = True


@dataclass(frozen=True, slots=True)
class DriverExecutionEvidence:
    """Approval-grade evidence bundle for one managed VM execution."""

    ok: bool
    status: RuntimeManagerStatus
    reason: str
    driver_id: str | None = None
    driver_version: int | None = None
    driver_class: str | None = None
    package_hash: str | None = None
    source_hash: str | None = None
    snapshot_hash: str | None = None
    evidence_hash: str | None = None
    session_id: str | None = None
    registry_state: str | None = None
    signature_verdict: str | None = None
    vm_result: DriverVMResult | None = None
    faults: tuple[RuntimeManagerFault, ...] = ()
    capability_report: Mapping[str, Any] = field(default_factory=dict)
    policy_report: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, int | str | bool | None] = field(default_factory=dict)
    trace_complete: bool = False
    deterministic: bool = True
    recommendation: str = "hold"


class DriverRuntimeManager:
    """Production-facing gate for Driver VM execution.

    This manager is intentionally separate from both the Native Storage Engine
    and the low-level DriverVMRuntime. It receives bytecode packages and caller-
    supplied snapshots, never storage handles, then returns structured evidence.
    """

    def __init__(self, *, policy: RuntimeManagerPolicy | None = None) -> None:
        self.policy = policy or RuntimeManagerPolicy()

    def execute_package(
        self,
        package: BytecodePackage,
        fixtures: Mapping[str, Any] | None,
        *,
        registry: DriverRegistry | None = None,
    ) -> DriverExecutionEvidence:
        """Validate, gate, execute, and return evidence without expected raises."""

        package_hash = getattr(package, "package_hash", None)
        source_hash = getattr(package, "source_hash", None)
        driver_id = _safe_header(package, "driver_id")
        driver_version = _safe_int(_safe_header(package, "driver_version"))
        driver_class = _safe_manifest(package, "kind")
        snapshot_hash: str | None = None
        session_id: str | None = None
        registry_state: str | None = None
        signature_verdict: str | None = None
        capability_report: Mapping[str, Any] = {}
        policy_report: Mapping[str, Any] = {}

        try:
            snapshot = _normalize_snapshot(fixtures or {}, max_records=self.policy.max_snapshot_records)
            snapshot_hash = _snapshot_hash(snapshot)
            session_id = _session_id(package_hash, snapshot_hash)

            package_gate = self._package_gate(package)
            if package_gate is not None:
                return self._evidence(
                    ok=False,
                    status=RuntimeManagerStatus.PACKAGE_REJECTED,
                    reason=package_gate.message,
                    package=package,
                    snapshot_hash=snapshot_hash,
                    session_id=session_id,
                    faults=(package_gate,),
                    recommendation="reject",
                )

            capability_report, capability_fault = self._capability_gate(package)
            if capability_fault is not None:
                return self._evidence(
                    ok=False,
                    status=RuntimeManagerStatus.POLICY_REJECTED,
                    reason=capability_fault.message,
                    package=package,
                    snapshot_hash=snapshot_hash,
                    session_id=session_id,
                    faults=(capability_fault,),
                    capability_report=capability_report,
                    recommendation="reject",
                )

            registry_state, signature_verdict, registry_fault = self._registry_gate(package, registry)
            if registry_fault is not None:
                status = (
                    RuntimeManagerStatus.SIGNATURE_REJECTED
                    if registry_fault.code.startswith("runtime.signature")
                    else RuntimeManagerStatus.REGISTRY_REJECTED
                )
                return self._evidence(
                    ok=False,
                    status=status,
                    reason=registry_fault.message,
                    package=package,
                    snapshot_hash=snapshot_hash,
                    session_id=session_id,
                    registry_state=registry_state,
                    signature_verdict=signature_verdict,
                    faults=(registry_fault,),
                    capability_report=capability_report,
                    recommendation="reject",
                )

            vm = DriverVMRuntime(max_instructions=self.policy.max_instructions, max_cost=self.policy.max_cost)
            vm.load(package)
            before = copy.deepcopy(snapshot)
            vm_result = vm.execute(snapshot)
            snapshot_preserved = before == snapshot
            trace_complete = _trace_complete(vm_result)
            policy_report = self._policy_report(
                registry_state=registry_state,
                signature_verdict=signature_verdict,
                trace_complete=trace_complete,
                snapshot_preserved=snapshot_preserved,
            )
            faults = tuple(
                RuntimeManagerFault(fault.code, fault.message, severity=fault.severity, recoverable=fault.recoverable)
                for fault in vm_result.faults
            )
            if not snapshot_preserved:
                faults += (
                    RuntimeManagerFault(
                        "runtime.snapshot_mutated",
                        "runtime snapshot changed during managed execution",
                        recoverable=False,
                    ),
                )
            if self.policy.require_trace_complete and vm_result.ok and not trace_complete:
                faults += (
                    RuntimeManagerFault(
                        "runtime.trace_incomplete",
                        "successful runtime execution did not produce a complete HALT trace",
                        recoverable=False,
                    ),
                )
            ok = vm_result.ok and snapshot_preserved and not any(not fault.recoverable for fault in faults)
            status = RuntimeManagerStatus.EXECUTED if ok else _status_for_vm_result(vm_result)
            recommendation = "candidate_ready" if ok else "hold"
            return self._evidence(
                ok=ok,
                status=status,
                reason="managed driver execution produced approval-grade evidence" if ok else vm_result.reason,
                package=package,
                snapshot_hash=snapshot_hash,
                session_id=session_id,
                registry_state=registry_state,
                signature_verdict=signature_verdict,
                vm_result=vm_result,
                faults=faults,
                capability_report=capability_report,
                policy_report=policy_report,
                trace_complete=trace_complete,
                recommendation=recommendation,
            )
        except _SnapshotError as exc:
            fault = RuntimeManagerFault("runtime.input_rejected", str(exc))
            return self._evidence(
                ok=False,
                status=RuntimeManagerStatus.INPUT_REJECTED,
                reason=str(exc),
                driver_id=driver_id,
                driver_version=driver_version,
                driver_class=driver_class,
                package_hash=package_hash,
                source_hash=source_hash,
                faults=(fault,),
                recommendation="hold",
            )
        except Exception as exc:  # Defensive manager boundary.
            fault = RuntimeManagerFault("runtime.internal_error", f"internal Runtime Manager error: {exc}", recoverable=False)
            return self._evidence(
                ok=False,
                status=RuntimeManagerStatus.INTERNAL_ERROR,
                reason=fault.message,
                driver_id=driver_id,
                driver_version=driver_version,
                driver_class=driver_class,
                package_hash=package_hash,
                source_hash=source_hash,
                snapshot_hash=snapshot_hash,
                session_id=session_id,
                registry_state=registry_state,
                signature_verdict=signature_verdict,
                faults=(fault,),
                recommendation="reject",
            )

    # Short alias for UI/service code.
    run = execute_package

    def _package_gate(self, package: BytecodePackage) -> RuntimeManagerFault | None:
        try:
            validate_bytecode_package(package)
            audit_vm_contract(package)
        except (TDDLValidationError, ValueError) as exc:
            return RuntimeManagerFault("runtime.package_rejected", str(exc))
        return None

    def _capability_gate(self, package: BytecodePackage) -> tuple[Mapping[str, Any], RuntimeManagerFault | None]:
        capabilities = tuple(str(item) for item in package.capabilities)
        driver_class = str(package.manifest.get("kind"))
        denied = tuple(sorted(cap for cap in capabilities if cap in self.policy.denied_capabilities))
        outside_allow = ()
        if self.policy.allowed_capabilities is not None:
            outside_allow = tuple(sorted(cap for cap in capabilities if cap not in self.policy.allowed_capabilities))
        class_allowed = driver_class in self.policy.allowed_driver_classes
        report: dict[str, Any] = {
            "driver_class": driver_class,
            "driver_class_allowed": class_allowed,
            "capabilities": capabilities,
            "denied_capabilities": denied,
            "outside_allowed_capabilities": outside_allow,
            "capability_count": len(capabilities),
        }
        if not class_allowed:
            return report, RuntimeManagerFault(
                "runtime.policy.driver_class",
                f"driver class is not allowed by runtime policy: {driver_class}",
            )
        if denied:
            return report, RuntimeManagerFault(
                "runtime.policy.denied_capability",
                f"driver declares denied capabilities: {list(denied)}",
            )
        if outside_allow:
            return report, RuntimeManagerFault(
                "runtime.policy.capability_not_allowed",
                f"driver declares capabilities outside runtime allow-list: {list(outside_allow)}",
            )
        return report, None

    def _registry_gate(
        self,
        package: BytecodePackage,
        registry: DriverRegistry | None,
    ) -> tuple[str | None, str | None, RuntimeManagerFault | None]:
        if not self.policy.require_registry_active and not self.policy.require_signature_accept:
            return None, None, None
        if registry is None:
            return None, None, RuntimeManagerFault(
                "runtime.registry.required",
                "runtime policy requires registry trust but no registry was supplied",
            )
        driver_id = str(package.header.get("driver_id"))
        try:
            record = registry.require(driver_id)
        except RegistryError as exc:
            return None, None, RuntimeManagerFault("runtime.registry.unknown_driver", str(exc))
        registry_state = record.state.value
        if record.manifest.version != int(package.header.get("driver_version", 0)):
            return registry_state, None, RuntimeManagerFault(
                "runtime.registry.version_mismatch",
                "registry manifest version does not match package header",
            )
        if record.manifest.kind != str(package.manifest.get("kind")):
            return registry_state, None, RuntimeManagerFault(
                "runtime.registry.kind_mismatch",
                "registry manifest kind does not match package manifest",
            )
        if self.policy.require_registry_active and record.state is not DriverState.ACTIVE:
            return registry_state, None, RuntimeManagerFault(
                "runtime.registry.not_active",
                f"runtime policy requires active driver state, found {record.state.value}",
            )
        signature_verdict = registry.signature_policy.evaluate(record.manifest.canonical_payload(), record.signature).value
        if self.policy.require_signature_accept and signature_verdict != SignatureVerdict.ACCEPT.value:
            return registry_state, signature_verdict, RuntimeManagerFault(
                "runtime.signature.rejected",
                f"runtime policy requires accepted signature, found {signature_verdict}",
            )
        return registry_state, signature_verdict, None

    def _policy_report(
        self,
        *,
        registry_state: str | None,
        signature_verdict: str | None,
        trace_complete: bool,
        snapshot_preserved: bool,
    ) -> Mapping[str, Any]:
        return {
            "max_cost": self.policy.max_cost,
            "max_instructions": self.policy.max_instructions,
            "max_snapshot_records": self.policy.max_snapshot_records,
            "require_registry_active": self.policy.require_registry_active,
            "require_signature_accept": self.policy.require_signature_accept,
            "registry_state": registry_state,
            "signature_verdict": signature_verdict,
            "trace_complete": trace_complete,
            "snapshot_preserved": snapshot_preserved,
        }

    def _evidence(
        self,
        *,
        ok: bool,
        status: RuntimeManagerStatus,
        reason: str,
        package: BytecodePackage | None = None,
        driver_id: str | None = None,
        driver_version: int | None = None,
        driver_class: str | None = None,
        package_hash: str | None = None,
        source_hash: str | None = None,
        snapshot_hash: str | None = None,
        session_id: str | None = None,
        registry_state: str | None = None,
        signature_verdict: str | None = None,
        vm_result: DriverVMResult | None = None,
        faults: tuple[RuntimeManagerFault, ...] = (),
        capability_report: Mapping[str, Any] | None = None,
        policy_report: Mapping[str, Any] | None = None,
        trace_complete: bool = False,
        recommendation: str = "hold",
    ) -> DriverExecutionEvidence:
        if package is not None:
            driver_id = str(package.header.get("driver_id"))
            driver_version = int(package.header.get("driver_version", 0))
            driver_class = str(package.manifest.get("kind"))
            package_hash = package.package_hash
            source_hash = package.source_hash
        capability_report = dict(capability_report or {})
        policy_report = dict(policy_report or {})
        metrics: dict[str, int | str | bool | None] = {
            "ok": ok,
            "status": status.value,
            "fault_count": len(faults),
            "trace_complete": trace_complete,
            "vm_status": vm_result.status.value if vm_result else None,
            "vm_cost_used": vm_result.cost_used if vm_result else 0,
            "vm_emitted_count": vm_result.context.emitted_count if vm_result else 0,
            "vm_records_seen": vm_result.context.records_seen if vm_result else 0,
        }
        evidence_hash = _evidence_hash(
            ok=ok,
            status=status,
            reason=reason,
            driver_id=driver_id,
            driver_version=driver_version,
            driver_class=driver_class,
            package_hash=package_hash,
            source_hash=source_hash,
            snapshot_hash=snapshot_hash,
            registry_state=registry_state,
            signature_verdict=signature_verdict,
            vm_result=vm_result,
            faults=faults,
            capability_report=capability_report,
            policy_report=policy_report,
            trace_complete=trace_complete,
            recommendation=recommendation,
        )
        return DriverExecutionEvidence(
            ok=ok,
            status=status,
            reason=reason,
            driver_id=driver_id,
            driver_version=driver_version,
            driver_class=driver_class,
            package_hash=package_hash,
            source_hash=source_hash,
            snapshot_hash=snapshot_hash,
            evidence_hash=evidence_hash,
            session_id=session_id or _session_id(package_hash, snapshot_hash),
            registry_state=registry_state,
            signature_verdict=signature_verdict,
            vm_result=vm_result,
            faults=faults,
            capability_report=capability_report,
            policy_report=policy_report,
            metrics=metrics,
            trace_complete=trace_complete,
            deterministic=True,
            recommendation=recommendation,
        )


class _SnapshotError(ValueError):
    pass


def runtime_manager_capability_matrix(policy: RuntimeManagerPolicy | None = None) -> Mapping[str, bool]:
    """Display the Runtime Manager authority map for Studio/Admin surfaces."""

    resolved = policy or RuntimeManagerPolicy()
    return {
        "validate_package": True,
        "audit_package": True,
        "execute_driver_vm": True,
        "produce_execution_evidence": True,
        "require_registry_active": resolved.require_registry_active,
        "require_signature_accept": resolved.require_signature_accept,
        "write_storage": False,
        "approve_driver": False,
        "sign_driver": False,
        "activate_driver": False,
        "execute_python": False,
        "bypass_policy": False,
    }


def _normalize_snapshot(fixtures: Mapping[str, Any], *, max_records: int) -> Mapping[str, Any]:
    if not isinstance(fixtures, Mapping):
        raise _SnapshotError("runtime fixtures must be a mapping")
    records = fixtures.get("records", ())
    if records is None:
        records = ()
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise _SnapshotError("runtime fixtures.records must be a sequence of mappings")
    if len(records) > max_records:
        raise _SnapshotError("runtime fixtures.records exceeds max_snapshot_records")
    normalized_records = []
    for item in records:
        if not isinstance(item, Mapping):
            raise _SnapshotError("runtime fixtures.records items must be mappings")
        normalized_records.append(copy.deepcopy(dict(item)))
    return {"records": normalized_records}


def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(_normalize_json(snapshot)).encode("utf-8")).hexdigest()


def _evidence_hash(**items: Any) -> str:
    vm_result = items.pop("vm_result")
    faults = items.pop("faults")
    payload = dict(items)
    payload["vm"] = None
    if vm_result is not None:
        payload["vm"] = {
            "ok": vm_result.ok,
            "status": vm_result.status.value,
            "reason": vm_result.reason,
            "trace": list(vm_result.trace),
            "metrics": dict(vm_result.metrics),
            "faults": [fault.code for fault in vm_result.faults],
        }
    payload["faults"] = [fault.code for fault in faults]
    return "sha256:" + hashlib.sha256(_canonical_json(_normalize_json(payload)).encode("utf-8")).hexdigest()


def _session_id(package_hash: str | None, snapshot_hash: str | None) -> str:
    material = f"{package_hash or ''}\0{snapshot_hash or ''}".encode("utf-8")
    return "tds-exec-" + hashlib.sha256(material).hexdigest()[:16]


def _trace_complete(vm_result: DriverVMResult) -> bool:
    return vm_result.ok and vm_result.status is VMStatus.HALTED and bool(vm_result.trace) and vm_result.trace[-1] == "HALT"


def _status_for_vm_result(vm_result: DriverVMResult) -> RuntimeManagerStatus:
    if vm_result.status is VMStatus.INPUT_REJECTED:
        return RuntimeManagerStatus.INPUT_REJECTED
    if vm_result.status in {VMStatus.REJECTED, VMStatus.NOT_LOADED, VMStatus.POLICY_REJECTED}:
        return RuntimeManagerStatus.POLICY_REJECTED
    if vm_result.status is VMStatus.INTERNAL_ERROR:
        return RuntimeManagerStatus.INTERNAL_ERROR
    return RuntimeManagerStatus.RUNTIME_FAULTED


def _normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_json(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _safe_header(package: BytecodePackage, key: str) -> str | None:
    try:
        return str(package.header.get(key))
    except Exception:
        return None


def _safe_manifest(package: BytecodePackage, key: str) -> str | None:
    try:
        return str(package.manifest.get(key))
    except Exception:
        return None


def _safe_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

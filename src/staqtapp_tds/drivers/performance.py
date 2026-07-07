"""Opt-in Driver VM performance evidence harness.

v3.1.17 introduces a controlled benchmark/evidence layer for the Python
Driver VM.  The harness is deliberately outside :class:`DriverVMRuntime` and
outside the Studio hot path: normal driver execution is unchanged unless a
caller explicitly constructs and runs ``DriverVMPerformanceHarness``.

The purpose is not to approve drivers or to mutate Registry trust.  The purpose
is to produce repeatable performance/parity evidence that can later become the
conversion target for an optional native C Driver VM backend returning the same
``DriverVMResult`` shape.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from .bytecode import BytecodePackage
from .runtime_manager import DriverRuntimeManager, RuntimeManagerPolicy
from .vm import DriverVMResult, DriverVMRuntime


class DriverVMPerformanceStatus(str, Enum):
    """Status for opt-in performance evidence generation."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DriverVMPerformanceBackend(str, Enum):
    """Known execution targets for performance evidence."""

    PYTHON_VM = "python_vm"
    MANAGED_PYTHON_VM = "managed_python_vm"
    NATIVE_C_VM = "native_c_vm"


@dataclass(frozen=True, slots=True)
class DriverVMPerformancePolicy:
    """Configuration for controlled VM performance evidence runs."""

    repetitions: int = 3
    warmup_runs: int = 1
    max_records: int = 10_000
    max_instructions: int = 1024
    max_cost: int = 100_000
    include_managed_runtime: bool = True
    collect_trace_hashes: bool = True
    native_backend_enabled: bool = False
    fail_on_parity_mismatch: bool = True

    def __post_init__(self) -> None:
        if self.repetitions < 1:
            raise ValueError("repetitions must be positive")
        if self.warmup_runs < 0:
            raise ValueError("warmup_runs must not be negative")
        if self.max_records < 1:
            raise ValueError("max_records must be positive")
        if self.max_instructions < 1:
            raise ValueError("max_instructions must be positive")
        if self.max_cost < 1:
            raise ValueError("max_cost must be positive")


@dataclass(frozen=True, slots=True)
class DriverVMPerformanceRun:
    """One timed VM/backend execution."""

    backend: DriverVMPerformanceBackend
    iteration: int
    elapsed_ns: int
    ok: bool
    status: str
    result_hash: str
    emitted_count: int
    records_seen: int
    cost_used: int
    trace_complete: bool
    reason: str = ""
    fault_count: int = 0
    metrics: Mapping[str, int | float | str | bool | None] = field(default_factory=dict)

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed_ns / 1_000_000.0

    @property
    def records_per_second(self) -> float:
        if self.elapsed_ns <= 0:
            return 0.0
        return self.records_seen / (self.elapsed_ns / 1_000_000_000.0)

    @property
    def emitted_per_second(self) -> float:
        if self.elapsed_ns <= 0:
            return 0.0
        return self.emitted_count / (self.elapsed_ns / 1_000_000_000.0)

    @property
    def cost_per_second(self) -> float:
        if self.elapsed_ns <= 0:
            return 0.0
        return self.cost_used / (self.elapsed_ns / 1_000_000_000.0)

    def as_row(self) -> Mapping[str, Any]:
        return {
            "backend": self.backend.value,
            "iteration": self.iteration,
            "elapsed_ns": self.elapsed_ns,
            "elapsed_ms": round(self.elapsed_ms, 6),
            "records_per_second": round(self.records_per_second, 3),
            "emitted_per_second": round(self.emitted_per_second, 3),
            "cost_per_second": round(self.cost_per_second, 3),
            "ok": self.ok,
            "status": self.status,
            "result_hash": self.result_hash,
            "emitted_count": self.emitted_count,
            "records_seen": self.records_seen,
            "cost_used": self.cost_used,
            "trace_complete": self.trace_complete,
            "fault_count": self.fault_count,
            "reason": self.reason,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class DriverVMPerformanceSummary:
    """Aggregate timing/cost summary for one backend."""

    backend: DriverVMPerformanceBackend
    run_count: int
    ok_count: int
    median_elapsed_ns: int
    min_elapsed_ns: int
    max_elapsed_ns: int
    median_records_per_second: float
    median_emitted_per_second: float
    median_cost_per_second: float
    result_hashes: tuple[str, ...]
    deterministic: bool

    def as_row(self) -> Mapping[str, Any]:
        return {
            "backend": self.backend.value,
            "run_count": self.run_count,
            "ok_count": self.ok_count,
            "median_elapsed_ns": self.median_elapsed_ns,
            "min_elapsed_ns": self.min_elapsed_ns,
            "max_elapsed_ns": self.max_elapsed_ns,
            "median_elapsed_ms": round(self.median_elapsed_ns / 1_000_000.0, 6),
            "median_records_per_second": round(self.median_records_per_second, 3),
            "median_emitted_per_second": round(self.median_emitted_per_second, 3),
            "median_cost_per_second": round(self.median_cost_per_second, 3),
            "result_hashes": self.result_hashes,
            "deterministic": self.deterministic,
        }


@dataclass(frozen=True, slots=True)
class DriverVMPerformanceComparison:
    """Parity/speed comparison between two backend summaries."""

    baseline_backend: DriverVMPerformanceBackend
    candidate_backend: DriverVMPerformanceBackend
    parity_ok: bool
    speedup_ratio: float
    baseline_median_elapsed_ns: int
    candidate_median_elapsed_ns: int
    reason: str

    def as_row(self) -> Mapping[str, Any]:
        return {
            "baseline_backend": self.baseline_backend.value,
            "candidate_backend": self.candidate_backend.value,
            "parity_ok": self.parity_ok,
            "speedup_ratio": round(self.speedup_ratio, 6),
            "baseline_median_elapsed_ns": self.baseline_median_elapsed_ns,
            "candidate_median_elapsed_ns": self.candidate_median_elapsed_ns,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DriverVMPerformanceReport:
    """Evidence report emitted by the opt-in performance harness."""

    ok: bool
    status: DriverVMPerformanceStatus
    reason: str
    driver_id: str | None
    driver_version: int | None
    driver_class: str | None
    package_hash: str | None
    snapshot_hash: str
    performance_hash: str
    policy: DriverVMPerformancePolicy
    runs: tuple[DriverVMPerformanceRun, ...]
    summaries: tuple[DriverVMPerformanceSummary, ...]
    comparisons: tuple[DriverVMPerformanceComparison, ...]
    capability_report: Mapping[str, bool]
    warnings: tuple[str, ...] = ()

    def summary(self, backend: DriverVMPerformanceBackend | str) -> DriverVMPerformanceSummary:
        wanted = backend if isinstance(backend, DriverVMPerformanceBackend) else DriverVMPerformanceBackend(str(backend))
        for item in self.summaries:
            if item.backend is wanted:
                return item
        raise KeyError(wanted.value)

    def signal_payload(self) -> Mapping[str, Any]:
        """Return compact JSON-friendly evidence for future Studio panels."""

        return {
            "ok": self.ok,
            "status": self.status.value,
            "reason": self.reason,
            "driver_id": self.driver_id,
            "driver_version": self.driver_version,
            "driver_class": self.driver_class,
            "package_hash": self.package_hash,
            "snapshot_hash": self.snapshot_hash,
            "performance_hash": self.performance_hash,
            "policy": {
                "repetitions": self.policy.repetitions,
                "warmup_runs": self.policy.warmup_runs,
                "max_records": self.policy.max_records,
                "max_instructions": self.policy.max_instructions,
                "max_cost": self.policy.max_cost,
                "include_managed_runtime": self.policy.include_managed_runtime,
                "native_backend_enabled": self.policy.native_backend_enabled,
                "fail_on_parity_mismatch": self.policy.fail_on_parity_mismatch,
            },
            "run_count": len(self.runs),
            "summaries": tuple(item.as_row() for item in self.summaries),
            "comparisons": tuple(item.as_row() for item in self.comparisons),
            "warnings": self.warnings,
            "capability_report": dict(self.capability_report),
        }


NativeBackendRunner = Callable[[BytecodePackage, Mapping[str, Any], DriverVMPerformancePolicy], DriverVMResult]


class DriverVMPerformanceHarness:
    """Explicit, off-hot-path performance/parity evidence generator.

    The harness performs controlled repeated executions.  It does not modify the
    driver package, Runtime Manager policy, Registry, storage, Studio state, or
    the VM hot loop.
    """

    def __init__(
        self,
        *,
        policy: DriverVMPerformancePolicy | None = None,
        runtime_manager_policy: RuntimeManagerPolicy | None = None,
        native_runner: NativeBackendRunner | None = None,
    ) -> None:
        self.policy = policy or DriverVMPerformancePolicy()
        self.runtime_manager_policy = runtime_manager_policy or RuntimeManagerPolicy(
            max_instructions=self.policy.max_instructions,
            max_cost=self.policy.max_cost,
            max_snapshot_records=self.policy.max_records,
        )
        self.native_runner = native_runner

    def capability_matrix(self) -> Mapping[str, bool]:
        return driver_vm_performance_capability_matrix(self.policy, native_runner_available=self.native_runner is not None)

    def run_package(self, package: BytecodePackage, fixtures: Mapping[str, Any] | None) -> DriverVMPerformanceReport:
        """Run opt-in performance evidence for one package and immutable snapshot."""

        snapshot = _normalize_snapshot(fixtures or {}, max_records=self.policy.max_records)
        snapshot_hash = _stable_hash(snapshot)
        warnings: list[str] = []
        runs: list[DriverVMPerformanceRun] = []

        for _ in range(self.policy.warmup_runs):
            _execute_python_vm(package, snapshot, self.policy)
            if self.policy.include_managed_runtime:
                _execute_managed_python_vm(package, snapshot, self.runtime_manager_policy)

        for iteration in range(self.policy.repetitions):
            runs.append(_timed_python_vm(package, snapshot, self.policy, iteration=iteration))
            if self.policy.include_managed_runtime:
                runs.append(_timed_managed_python_vm(package, snapshot, self.runtime_manager_policy, iteration=iteration))
            if self.policy.native_backend_enabled:
                if self.native_runner is None:
                    warnings.append("native C VM backend was requested but no native_runner was provided")
                else:
                    runs.append(_timed_native_vm(package, snapshot, self.policy, self.native_runner, iteration=iteration))

        summaries = tuple(_summarize(backend_runs) for backend_runs in _group_runs(runs).values() if backend_runs)
        comparisons = tuple(_compare_summaries(summaries))
        parity_failures = [item for item in comparisons if not item.parity_ok]
        deterministic_failures = [item for item in summaries if not item.deterministic]
        ok = not deterministic_failures and (not parity_failures or not self.policy.fail_on_parity_mismatch)
        status = DriverVMPerformanceStatus.PASSED if ok else DriverVMPerformanceStatus.FAILED
        if not ok:
            reason = "performance evidence found deterministic or parity mismatches"
        elif warnings:
            reason = "performance evidence generated with warnings"
        else:
            reason = "performance evidence generated successfully"

        report_without_hash = {
            "ok": ok,
            "status": status.value,
            "reason": reason,
            "driver_id": _package_header(package, "driver_id"),
            "driver_version": _safe_int(_package_header(package, "driver_version")),
            "driver_class": _package_manifest(package, "kind"),
            "package_hash": getattr(package, "package_hash", None),
            "snapshot_hash": snapshot_hash,
            "runs": [run.as_row() for run in runs],
            "summaries": [summary.as_row() for summary in summaries],
            "comparisons": [comparison.as_row() for comparison in comparisons],
            "warnings": warnings,
        }
        performance_hash = _stable_hash(report_without_hash)
        return DriverVMPerformanceReport(
            ok=ok,
            status=status,
            reason=reason,
            driver_id=_package_header(package, "driver_id"),
            driver_version=_safe_int(_package_header(package, "driver_version")),
            driver_class=_package_manifest(package, "kind"),
            package_hash=getattr(package, "package_hash", None),
            snapshot_hash=snapshot_hash,
            performance_hash=performance_hash,
            policy=self.policy,
            runs=tuple(runs),
            summaries=summaries,
            comparisons=comparisons,
            capability_report=self.capability_matrix(),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    # Short alias for service/admin tooling.
    run = run_package


def driver_vm_performance_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether environment-gated benchmark tooling is explicitly enabled.

    This helper is intentionally passive.  It does not auto-run the harness.
    """

    value = (env or os.environ).get("STAQTAPP_TDS_DRIVER_VM_PERF", "0")
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def driver_vm_performance_capability_matrix(
    policy: DriverVMPerformancePolicy | None = None,
    *,
    native_runner_available: bool = False,
) -> Mapping[str, bool]:
    """Expose harness boundaries for Admin/Studio documentation."""

    resolved = policy or DriverVMPerformancePolicy()
    return {
        "driver_vm_performance_harness": True,
        "opt_in_only": True,
        "auto_runs_in_driver_vm_execute": False,
        "auto_runs_in_runtime_manager": False,
        "normal_python_vm_hot_path_changed": False,
        "direct_python_vm_backend": True,
        "managed_python_vm_backend": resolved.include_managed_runtime,
        "native_c_vm_backend_slot": True,
        "native_c_vm_backend_enabled": resolved.native_backend_enabled,
        "native_runner_available": native_runner_available,
        "returns_performance_evidence": True,
        "returns_parity_evidence": True,
        "records_per_second_metric": True,
        "emitted_per_second_metric": True,
        "cost_per_second_metric": True,
        "runtime_manager_overhead_comparison": resolved.include_managed_runtime,
        "future_native_c_conversion_target": True,
        "approve_driver": False,
        "reject_driver": False,
        "quarantine_driver": False,
        "call_registry_approve": False,
        "sign_driver": False,
        "attach_signature": False,
        "activate_driver": False,
        "write_storage": False,
        "mutate_registry": False,
        "store_private_keys": False,
        "bypass_policy": False,
    }


def _execute_python_vm(package: BytecodePackage, snapshot: Mapping[str, Any], policy: DriverVMPerformancePolicy) -> DriverVMResult:
    vm = DriverVMRuntime(max_instructions=policy.max_instructions, max_cost=policy.max_cost)
    vm.load(package)
    return vm.execute(copy.deepcopy(snapshot))


def _execute_managed_python_vm(
    package: BytecodePackage,
    snapshot: Mapping[str, Any],
    runtime_policy: RuntimeManagerPolicy,
) -> DriverVMResult | None:
    manager = DriverRuntimeManager(policy=runtime_policy)
    evidence = manager.execute_package(package, copy.deepcopy(snapshot))
    return evidence.vm_result


def _timed_python_vm(
    package: BytecodePackage,
    snapshot: Mapping[str, Any],
    policy: DriverVMPerformancePolicy,
    *,
    iteration: int,
) -> DriverVMPerformanceRun:
    start = time.perf_counter_ns()
    result = _execute_python_vm(package, snapshot, policy)
    elapsed = max(1, time.perf_counter_ns() - start)
    return _run_from_vm_result(DriverVMPerformanceBackend.PYTHON_VM, iteration, elapsed, result)


def _timed_managed_python_vm(
    package: BytecodePackage,
    snapshot: Mapping[str, Any],
    runtime_policy: RuntimeManagerPolicy,
    *,
    iteration: int,
) -> DriverVMPerformanceRun:
    start = time.perf_counter_ns()
    manager = DriverRuntimeManager(policy=runtime_policy)
    evidence = manager.execute_package(package, copy.deepcopy(snapshot))
    elapsed = max(1, time.perf_counter_ns() - start)
    result = evidence.vm_result
    if result is None:
        return DriverVMPerformanceRun(
            backend=DriverVMPerformanceBackend.MANAGED_PYTHON_VM,
            iteration=iteration,
            elapsed_ns=elapsed,
            ok=False,
            status=evidence.status.value,
            result_hash=_stable_hash({"evidence_hash": evidence.evidence_hash, "status": evidence.status.value}),
            emitted_count=0,
            records_seen=0,
            cost_used=0,
            trace_complete=False,
            reason=evidence.reason,
            fault_count=len(evidence.faults),
            metrics=dict(evidence.metrics),
        )
    run = _run_from_vm_result(DriverVMPerformanceBackend.MANAGED_PYTHON_VM, iteration, elapsed, result)
    return DriverVMPerformanceRun(
        backend=run.backend,
        iteration=run.iteration,
        elapsed_ns=run.elapsed_ns,
        ok=evidence.ok and run.ok,
        status=evidence.status.value,
        result_hash=run.result_hash,
        emitted_count=run.emitted_count,
        records_seen=run.records_seen,
        cost_used=run.cost_used,
        trace_complete=evidence.trace_complete,
        reason=evidence.reason,
        fault_count=len(evidence.faults) + run.fault_count,
        metrics={**dict(run.metrics), **dict(evidence.metrics)},
    )


def _timed_native_vm(
    package: BytecodePackage,
    snapshot: Mapping[str, Any],
    policy: DriverVMPerformancePolicy,
    runner: NativeBackendRunner,
    *,
    iteration: int,
) -> DriverVMPerformanceRun:
    start = time.perf_counter_ns()
    result = runner(package, copy.deepcopy(snapshot), policy)
    elapsed = max(1, time.perf_counter_ns() - start)
    return _run_from_vm_result(DriverVMPerformanceBackend.NATIVE_C_VM, iteration, elapsed, result)


def _run_from_vm_result(
    backend: DriverVMPerformanceBackend,
    iteration: int,
    elapsed_ns: int,
    result: DriverVMResult,
) -> DriverVMPerformanceRun:
    return DriverVMPerformanceRun(
        backend=backend,
        iteration=iteration,
        elapsed_ns=elapsed_ns,
        ok=result.ok,
        status=result.status.value,
        result_hash=_result_hash(result),
        emitted_count=result.context.emitted_count,
        records_seen=result.context.records_seen,
        cost_used=result.cost_used,
        trace_complete=result.ok and bool(result.trace) and result.trace[-1] == "HALT",
        reason=result.reason,
        fault_count=len(result.faults),
        metrics=dict(result.metrics),
    )


def _result_hash(result: DriverVMResult) -> str:
    payload: dict[str, Any] = {
        "ok": result.ok,
        "status": result.status.value,
        "trace": list(result.trace),
        "emitted": list(result.emitted),
        "faults": [fault.code for fault in result.faults],
        "driver_id": result.driver_id,
        "driver_version": result.driver_version,
        "package_hash": result.package_hash,
    }
    return _stable_hash(payload)


def _group_runs(runs: Sequence[DriverVMPerformanceRun]) -> Mapping[DriverVMPerformanceBackend, tuple[DriverVMPerformanceRun, ...]]:
    grouped: dict[DriverVMPerformanceBackend, list[DriverVMPerformanceRun]] = {}
    for run in runs:
        grouped.setdefault(run.backend, []).append(run)
    return {backend: tuple(items) for backend, items in grouped.items()}


def _summarize(runs: Sequence[DriverVMPerformanceRun]) -> DriverVMPerformanceSummary:
    backend = runs[0].backend
    elapsed = [run.elapsed_ns for run in runs]
    result_hashes = tuple(dict.fromkeys(run.result_hash for run in runs))
    return DriverVMPerformanceSummary(
        backend=backend,
        run_count=len(runs),
        ok_count=sum(1 for run in runs if run.ok),
        median_elapsed_ns=int(statistics.median(elapsed)),
        min_elapsed_ns=min(elapsed),
        max_elapsed_ns=max(elapsed),
        median_records_per_second=float(statistics.median(run.records_per_second for run in runs)),
        median_emitted_per_second=float(statistics.median(run.emitted_per_second for run in runs)),
        median_cost_per_second=float(statistics.median(run.cost_per_second for run in runs)),
        result_hashes=result_hashes,
        deterministic=len(result_hashes) == 1,
    )


def _compare_summaries(summaries: Sequence[DriverVMPerformanceSummary]) -> list[DriverVMPerformanceComparison]:
    by_backend = {summary.backend: summary for summary in summaries}
    baseline = by_backend.get(DriverVMPerformanceBackend.PYTHON_VM)
    if baseline is None:
        return []
    comparisons: list[DriverVMPerformanceComparison] = []
    for backend in (DriverVMPerformanceBackend.MANAGED_PYTHON_VM, DriverVMPerformanceBackend.NATIVE_C_VM):
        candidate = by_backend.get(backend)
        if candidate is None:
            continue
        parity_ok = bool(set(candidate.result_hashes) & set(baseline.result_hashes))
        speedup = baseline.median_elapsed_ns / candidate.median_elapsed_ns if candidate.median_elapsed_ns else 0.0
        comparisons.append(
            DriverVMPerformanceComparison(
                baseline_backend=baseline.backend,
                candidate_backend=candidate.backend,
                parity_ok=parity_ok,
                speedup_ratio=speedup,
                baseline_median_elapsed_ns=baseline.median_elapsed_ns,
                candidate_median_elapsed_ns=candidate.median_elapsed_ns,
                reason="result parity maintained" if parity_ok else "result parity mismatch",
            )
        )
    return comparisons


def _normalize_snapshot(fixtures: Mapping[str, Any], *, max_records: int) -> Mapping[str, Any]:
    if not isinstance(fixtures, Mapping):
        raise TypeError("performance fixtures must be a mapping")
    records = fixtures.get("records", ())
    if records is None:
        records = ()
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise TypeError("performance fixtures.records must be a sequence of mappings")
    if len(records) > max_records:
        raise ValueError("performance fixtures.records exceeds policy.max_records")
    normalized: list[Mapping[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping):
            raise TypeError("performance fixtures.records items must be mappings")
        normalized.append(copy.deepcopy(dict(item)))
    return {"records": normalized}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_normalize_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_json(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _package_header(package: BytecodePackage, key: str) -> str | None:
    try:
        return str(package.header.get(key))
    except Exception:
        return None


def _package_manifest(package: BytecodePackage, key: str) -> str | None:
    try:
        return str(package.manifest.get(key))
    except Exception:
        return None


def _safe_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

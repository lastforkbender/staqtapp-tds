"""Driver VM fixture and regression harness.

v3.1.4 adds the deterministic harness that should exist before admin batch
review, native driver runtime expansion, or full Driver Studio. The harness runs
compiled bytecode packages through DriverRuntimeManager against named immutable
fixture cases, compares the resulting execution evidence to explicit
expectations, and returns a non-halting report suitable for future approval
panels.

The harness is not a trust authority. It cannot approve, sign, activate, write
storage, execute Python, or bypass Runtime Manager policy.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .bytecode import BytecodePackage
from .registry import DriverRegistry
from .runtime_manager import DriverExecutionEvidence, DriverRuntimeManager, RuntimeManagerStatus
from .vm import VMStatus


class RegressionStatus(str, Enum):
    """Top-level status for a regression harness run."""

    PASSED = "passed"
    FAILED = "failed"
    INPUT_REJECTED = "input_rejected"


@dataclass(frozen=True, slots=True)
class DriverFixtureCase:
    """One named fixture and its expected Runtime Manager evidence shape."""

    case_id: str
    fixtures: Mapping[str, Any]
    description: str = ""
    expected_ok: bool | None = None
    expected_status: RuntimeManagerStatus | str | None = None
    expected_recommendation: str | None = None
    expected_vm_status: VMStatus | str | None = None
    expected_emitted_count: int | None = None
    expected_trace_complete: bool | None = None
    expected_fault_codes: tuple[str, ...] = ()
    expected_evidence_hash: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegressionMismatch:
    """One deterministic expectation mismatch."""

    field: str
    expected: Any
    actual: Any


@dataclass(frozen=True, slots=True)
class DriverRegressionResult:
    """Harness result for one fixture case."""

    case_id: str
    passed: bool
    status: RuntimeManagerStatus
    reason: str
    fixture_hash: str
    evidence_hash: str | None
    evidence: DriverExecutionEvidence
    mismatches: tuple[RegressionMismatch, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverRegressionReport:
    """Deterministic report across all fixture cases for one package."""

    ok: bool
    status: RegressionStatus
    reason: str
    driver_id: str | None
    driver_version: int | None
    driver_class: str | None
    package_hash: str | None
    report_hash: str
    results: tuple[DriverRegressionResult, ...]
    passed_count: int = 0
    failed_count: int = 0
    case_count: int = 0
    recommendation: str = "hold"

    @property
    def failed_cases(self) -> tuple[str, ...]:
        return tuple(result.case_id for result in self.results if not result.passed)

    @property
    def passed_cases(self) -> tuple[str, ...]:
        return tuple(result.case_id for result in self.results if result.passed)


class DriverRegressionHarness:
    """Run approval-grade Runtime Manager evidence across fixture cases."""

    def __init__(self, *, runtime_manager: DriverRuntimeManager | None = None, max_cases: int = 256) -> None:
        if max_cases < 1:
            raise ValueError("max_cases must be positive")
        self.runtime_manager = runtime_manager or DriverRuntimeManager()
        self.max_cases = max_cases

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the harness authority map for Admin and Studio display."""

        return {
            "run_runtime_manager": True,
            "compare_fixture_expectations": True,
            "produce_regression_report": True,
            "record_golden_evidence_hashes": True,
            "approve_driver": False,
            "sign_driver": False,
            "activate_driver": False,
            "write_storage": False,
            "execute_python": False,
            "bypass_policy": False,
        }

    def run_package(
        self,
        package: BytecodePackage,
        cases: Sequence[DriverFixtureCase | Mapping[str, Any]],
        *,
        registry: DriverRegistry | None = None,
    ) -> DriverRegressionReport:
        """Run a package against named fixtures without raising for expected failures."""

        try:
            fixture_cases = tuple(_validate_case(_coerce_case(case)) for case in cases)
        except Exception as exc:
            return _input_rejected_report(package, f"invalid regression fixture cases: {exc}")
        if not fixture_cases:
            return _input_rejected_report(package, "at least one regression fixture case is required")
        if len(fixture_cases) > self.max_cases:
            return _input_rejected_report(package, "regression fixture case count exceeds max_cases")
        duplicate_ids = _duplicate_case_ids(fixture_cases)
        if duplicate_ids:
            return _input_rejected_report(package, f"duplicate regression fixture case ids: {list(duplicate_ids)}")

        results: list[DriverRegressionResult] = []
        for case in fixture_cases:
            evidence = self.runtime_manager.execute_package(package, case.fixtures, registry=registry)
            mismatches = _compare_case(case, evidence)
            results.append(
                DriverRegressionResult(
                    case_id=case.case_id,
                    passed=not mismatches,
                    status=evidence.status,
                    reason=evidence.reason,
                    fixture_hash=runtime_fixture_hash(case.fixtures),
                    evidence_hash=evidence.evidence_hash,
                    evidence=evidence,
                    mismatches=mismatches,
                    tags=tuple(case.tags),
                )
            )

        passed_count = sum(1 for result in results if result.passed)
        failed_count = len(results) - passed_count
        ok = failed_count == 0
        status = RegressionStatus.PASSED if ok else RegressionStatus.FAILED
        reason = "all driver regression fixture cases passed" if ok else "one or more driver regression fixture cases failed"
        recommendation = "batch_review_ready" if ok else "hold"
        return _report(
            ok=ok,
            status=status,
            reason=reason,
            package=package,
            results=tuple(results),
            passed_count=passed_count,
            failed_count=failed_count,
            recommendation=recommendation,
        )

    # Short alias for service/UI code.
    run = run_package


def regression_harness_capability_matrix() -> Mapping[str, bool]:
    """Convenience function for displaying the harness authority map."""

    return DriverRegressionHarness().capability_matrix()


def runtime_fixture_hash(fixtures: Mapping[str, Any]) -> str:
    """Hash fixtures using the same canonical JSON discipline as evidence."""

    return "sha256:" + hashlib.sha256(_canonical_json(_normalize_json(fixtures)).encode("utf-8")).hexdigest()


def _coerce_case(case: DriverFixtureCase | Mapping[str, Any]) -> DriverFixtureCase:
    if isinstance(case, DriverFixtureCase):
        return case
    if not isinstance(case, Mapping):
        raise TypeError("fixture case must be DriverFixtureCase or mapping")
    expected_status = case.get("expected_status")
    expected_vm_status = case.get("expected_vm_status")
    return DriverFixtureCase(
        case_id=str(case["case_id"]),
        fixtures=_mapping(case.get("fixtures", {}), name="fixtures"),
        description=str(case.get("description", "")),
        expected_ok=_optional_bool(case.get("expected_ok")),
        expected_status=expected_status if expected_status is None else _runtime_status_value(expected_status),
        expected_recommendation=None if case.get("expected_recommendation") is None else str(case.get("expected_recommendation")),
        expected_vm_status=expected_vm_status if expected_vm_status is None else _vm_status_value(expected_vm_status),
        expected_emitted_count=None if case.get("expected_emitted_count") is None else int(case.get("expected_emitted_count")),
        expected_trace_complete=_optional_bool(case.get("expected_trace_complete")),
        expected_fault_codes=tuple(str(item) for item in case.get("expected_fault_codes", ())),
        expected_evidence_hash=None if case.get("expected_evidence_hash") is None else str(case.get("expected_evidence_hash")),
        tags=tuple(str(item) for item in case.get("tags", ())),
    )


def _validate_case(case: DriverFixtureCase) -> DriverFixtureCase:
    if case.expected_status is not None:
        _runtime_status_value(case.expected_status)
    if case.expected_vm_status is not None:
        _vm_status_value(case.expected_vm_status)
    if case.expected_emitted_count is not None and case.expected_emitted_count < 0:
        raise ValueError("expected_emitted_count must be >= 0")
    return case


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise TypeError("optional expectation boolean fields must be bool or None")


def _duplicate_case_ids(cases: Sequence[DriverFixtureCase]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for case in cases:
        if not case.case_id:
            duplicates.append(case.case_id)
        elif case.case_id in seen:
            duplicates.append(case.case_id)
        seen.add(case.case_id)
    return tuple(duplicates)


def _compare_case(case: DriverFixtureCase, evidence: DriverExecutionEvidence) -> tuple[RegressionMismatch, ...]:
    mismatches: list[RegressionMismatch] = []
    if case.expected_ok is not None and evidence.ok is not case.expected_ok:
        mismatches.append(RegressionMismatch("ok", case.expected_ok, evidence.ok))
    if case.expected_status is not None:
        expected = _runtime_status_value(case.expected_status)
        actual = evidence.status.value
        if actual != expected:
            mismatches.append(RegressionMismatch("status", expected, actual))
    if case.expected_recommendation is not None and evidence.recommendation != case.expected_recommendation:
        mismatches.append(RegressionMismatch("recommendation", case.expected_recommendation, evidence.recommendation))
    if case.expected_vm_status is not None:
        expected = _vm_status_value(case.expected_vm_status)
        actual = evidence.vm_result.status.value if evidence.vm_result else None
        if actual != expected:
            mismatches.append(RegressionMismatch("vm_status", expected, actual))
    if case.expected_emitted_count is not None:
        actual = int(evidence.metrics.get("vm_emitted_count", 0))
        if actual != case.expected_emitted_count:
            mismatches.append(RegressionMismatch("vm_emitted_count", case.expected_emitted_count, actual))
    if case.expected_trace_complete is not None and evidence.trace_complete is not case.expected_trace_complete:
        mismatches.append(RegressionMismatch("trace_complete", case.expected_trace_complete, evidence.trace_complete))
    if case.expected_fault_codes:
        actual_codes = tuple(fault.code for fault in evidence.faults)
        if actual_codes != tuple(case.expected_fault_codes):
            mismatches.append(RegressionMismatch("fault_codes", tuple(case.expected_fault_codes), actual_codes))
    if case.expected_evidence_hash is not None and evidence.evidence_hash != case.expected_evidence_hash:
        mismatches.append(RegressionMismatch("evidence_hash", case.expected_evidence_hash, evidence.evidence_hash))
    return tuple(mismatches)


def _runtime_status_value(value: RuntimeManagerStatus | str) -> str:
    if isinstance(value, RuntimeManagerStatus):
        return value.value
    return RuntimeManagerStatus(str(value)).value


def _vm_status_value(value: VMStatus | str) -> str:
    if isinstance(value, VMStatus):
        return value.value
    return VMStatus(str(value)).value


def _input_rejected_report(package: BytecodePackage, reason: str) -> DriverRegressionReport:
    return _report(
        ok=False,
        status=RegressionStatus.INPUT_REJECTED,
        reason=reason,
        package=package,
        results=(),
        passed_count=0,
        failed_count=0,
        recommendation="hold",
    )


def _report(
    *,
    ok: bool,
    status: RegressionStatus,
    reason: str,
    package: BytecodePackage,
    results: tuple[DriverRegressionResult, ...],
    passed_count: int,
    failed_count: int,
    recommendation: str,
) -> DriverRegressionReport:
    driver_id = _safe_header(package, "driver_id")
    driver_version = _safe_int(_safe_header(package, "driver_version"))
    driver_class = _safe_manifest(package, "kind")
    package_hash = getattr(package, "package_hash", None)
    report_hash = _report_hash(
        ok=ok,
        status=status,
        reason=reason,
        driver_id=driver_id,
        driver_version=driver_version,
        driver_class=driver_class,
        package_hash=package_hash,
        results=results,
        passed_count=passed_count,
        failed_count=failed_count,
        recommendation=recommendation,
    )
    return DriverRegressionReport(
        ok=ok,
        status=status,
        reason=reason,
        driver_id=driver_id,
        driver_version=driver_version,
        driver_class=driver_class,
        package_hash=package_hash,
        report_hash=report_hash,
        results=results,
        passed_count=passed_count,
        failed_count=failed_count,
        case_count=len(results),
        recommendation=recommendation,
    )


def _report_hash(**items: Any) -> str:
    results = items.pop("results")
    payload = dict(items)
    payload["results"] = [
        {
            "case_id": result.case_id,
            "passed": result.passed,
            "status": result.status.value,
            "fixture_hash": result.fixture_hash,
            "evidence_hash": result.evidence_hash,
            "mismatches": [
                {"field": item.field, "expected": item.expected, "actual": item.actual} for item in result.mismatches
            ],
            "tags": list(result.tags),
        }
        for result in results
    ]
    return "sha256:" + hashlib.sha256(_canonical_json(_normalize_json(payload)).encode("utf-8")).hexdigest()


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

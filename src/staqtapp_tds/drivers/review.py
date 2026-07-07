"""Admin batch review layer for Driver Regression evidence.

v3.1.5 adds the careful approval-review seam that sits above the deterministic
fixture regression harness and below future Driver Studio controls. The review
layer consumes :class:`DriverRegressionReport` objects, produces one immutable
admin decision per driver, and can optionally ask the Registry to approve clean
candidates. It never signs, activates, executes bytecode, writes storage, or
bypasses Runtime Manager evidence gates.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .registry import DriverRegistry, DriverState, RegistryError
from .regression import DriverRegressionReport, RegressionStatus


class ReviewAction(str, Enum):
    """Admin-requested review action for one driver report."""

    APPROVE = "approve"
    HOLD = "hold"
    REJECT = "reject"
    QUARANTINE = "quarantine"


class ReviewDecisionStatus(str, Enum):
    """Per-driver batch review outcome."""

    APPROVAL_READY = "approval_ready"
    REGISTRY_APPROVED = "registry_approved"
    HELD = "held"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    INPUT_REJECTED = "input_rejected"
    REGISTRY_REJECTED = "registry_rejected"


class BatchReviewStatus(str, Enum):
    """Top-level status for an admin batch review run."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    INPUT_REJECTED = "input_rejected"


@dataclass(frozen=True, slots=True)
class ReviewFault:
    """Structured fault for Admin/Studio review surfaces."""

    code: str
    message: str
    severity: str = "error"
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class BatchReviewPolicy:
    """Authority and evidence policy for admin batch review.

    ``allow_registry_approval`` is disabled by default so GUI and service code
    can rehearse decisions without mutating Registry state. Even when enabled,
    the board can only call ``DriverRegistry.approve`` for clean candidates; it
    has no signing or activation authority.
    """

    max_items: int = 128
    require_clean_regression: bool = True
    require_batch_review_ready: bool = True
    require_runtime_execution_ok: bool = True
    require_driver_identity: bool = True
    require_registry_candidate: bool = False
    allow_registry_approval: bool = False
    allowed_reviewers: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class DriverReviewItem:
    """One report plus the admin's requested action and explanation."""

    report: DriverRegressionReport
    requested_action: ReviewAction | str = ReviewAction.APPROVE
    reviewer_id: str = "admin"
    rationale: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverReviewDecision:
    """Immutable per-driver decision generated from regression evidence."""

    driver_id: str | None
    driver_version: int | None
    requested_action: ReviewAction
    final_action: ReviewAction
    status: ReviewDecisionStatus
    ok: bool
    reason: str
    reviewer_id: str
    rationale: str
    report_hash: str | None
    package_hash: str | None
    regression_status: str | None
    risk_level: str
    evidence_summary: Mapping[str, Any] = field(default_factory=dict)
    registry_state_before: str | None = None
    registry_state_after: str | None = None
    review_hash: str = ""
    faults: tuple[ReviewFault, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.status in {ReviewDecisionStatus.APPROVAL_READY, ReviewDecisionStatus.REGISTRY_APPROVED}


@dataclass(frozen=True, slots=True)
class DriverBatchReviewReport:
    """Deterministic batch report for Admin and future Driver Studio."""

    ok: bool
    status: BatchReviewStatus
    reason: str
    batch_id: str
    batch_hash: str
    decisions: tuple[DriverReviewDecision, ...]
    approved_count: int = 0
    held_count: int = 0
    rejected_count: int = 0
    quarantined_count: int = 0
    registry_approved_count: int = 0
    input_rejected_count: int = 0
    registry_rejected_count: int = 0
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    @property
    def approved_driver_ids(self) -> tuple[str, ...]:
        return tuple(decision.driver_id for decision in self.decisions if decision.approved and decision.driver_id)

    @property
    def held_driver_ids(self) -> tuple[str, ...]:
        return tuple(decision.driver_id for decision in self.decisions if decision.status is ReviewDecisionStatus.HELD and decision.driver_id)


class DriverBatchReviewBoard:
    """Review deterministic regression reports without expanding trust authority."""

    def __init__(self, *, policy: BatchReviewPolicy | None = None) -> None:
        self.policy = policy or BatchReviewPolicy()
        if self.policy.max_items < 1:
            raise ValueError("max_items must be positive")

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the Admin review authority map for Studio display."""

        return {
            "consume_regression_reports": True,
            "create_batch_review_records": True,
            "create_per_driver_audit_decisions": True,
            "approve_clean_candidate_decision": True,
            "call_registry_approve": self.policy.allow_registry_approval,
            "sign_driver": False,
            "attach_signature": False,
            "activate_driver": False,
            "run_driver_vm": False,
            "write_storage": False,
            "execute_python": False,
            "bypass_policy": False,
        }

    def review_reports(
        self,
        reports: Sequence[DriverRegressionReport | DriverReviewItem | Mapping[str, Any]],
        *,
        reviewer_id: str = "admin",
        requested_action: ReviewAction | str = ReviewAction.APPROVE,
        rationale: str = "",
        action_overrides: Mapping[str, ReviewAction | str] | None = None,
        registry: DriverRegistry | None = None,
        apply_registry: bool = False,
        batch_id: str | None = None,
    ) -> DriverBatchReviewReport:
        """Review a batch of regression reports and return deterministic decisions.

        ``action_overrides`` may be keyed by ``driver_id`` or ``report_hash``.
        Registry approval is deliberately opt-in and requires both
        ``apply_registry=True`` and ``BatchReviewPolicy.allow_registry_approval``.
        """

        try:
            items = tuple(
                _coerce_item(
                    item,
                    reviewer_id=reviewer_id,
                    requested_action=requested_action,
                    rationale=rationale,
                    action_overrides=action_overrides or {},
                )
                for item in reports
            )
            self._validate_batch(items)
        except Exception as exc:
            return _input_rejected_batch(str(exc), capability_matrix=self.capability_matrix(), batch_id=batch_id)

        decisions = tuple(
            self._review_item(item, registry=registry, apply_registry=apply_registry) for item in items
        )
        return _batch_report(decisions, capability_matrix=self.capability_matrix(), batch_id=batch_id)

    # Short alias for UI/service code.
    review = review_reports

    def _validate_batch(self, items: Sequence[DriverReviewItem]) -> None:
        if not items:
            raise ValueError("at least one regression report is required")
        if len(items) > self.policy.max_items:
            raise ValueError("batch review item count exceeds max_items")
        reviewer_ids = {item.reviewer_id for item in items}
        if self.policy.allowed_reviewers is not None:
            denied = sorted(reviewer for reviewer in reviewer_ids if reviewer not in self.policy.allowed_reviewers)
            if denied:
                raise ValueError(f"reviewer is not allowed: {denied[0]}")
        seen: set[tuple[str | None, int | None]] = set()
        duplicates: list[str] = []
        for item in items:
            identity = (item.report.driver_id, item.report.driver_version)
            if identity in seen:
                duplicates.append(str(item.report.driver_id))
            seen.add(identity)
        if duplicates:
            raise ValueError(f"duplicate driver review entries: {duplicates}")

    def _review_item(
        self,
        item: DriverReviewItem,
        *,
        registry: DriverRegistry | None,
        apply_registry: bool,
    ) -> DriverReviewDecision:
        report = item.report
        requested = _action_value(item.requested_action)
        faults: list[ReviewFault] = []
        registry_state_before: str | None = None
        registry_state_after: str | None = None

        if self.policy.require_driver_identity and not report.driver_id:
            return _decision(
                report=report,
                requested=requested,
                final=ReviewAction.HOLD,
                status=ReviewDecisionStatus.INPUT_REJECTED,
                ok=False,
                reason="regression report is missing driver identity",
                reviewer_id=item.reviewer_id,
                rationale=item.rationale,
                faults=(ReviewFault("review.identity.missing", "regression report is missing driver identity"),),
                tags=item.tags,
            )

        if registry is not None and report.driver_id:
            try:
                registry_state_before = registry.require(report.driver_id).state.value
            except RegistryError as exc:
                if self.policy.require_registry_candidate or apply_registry:
                    return _decision(
                        report=report,
                        requested=requested,
                        final=ReviewAction.HOLD,
                        status=ReviewDecisionStatus.REGISTRY_REJECTED,
                        ok=False,
                        reason=str(exc),
                        reviewer_id=item.reviewer_id,
                        rationale=item.rationale,
                        registry_state_before=None,
                        faults=(ReviewFault("review.registry.unknown_driver", str(exc)),),
                        tags=item.tags,
                    )

        evidence_fault = _evidence_fault(report, self.policy)
        if evidence_fault is not None:
            if requested is ReviewAction.REJECT or report.status is RegressionStatus.INPUT_REJECTED:
                final = ReviewAction.REJECT
                status = ReviewDecisionStatus.REJECTED
                reason = evidence_fault.message
            elif requested is ReviewAction.QUARANTINE:
                final = ReviewAction.QUARANTINE
                status = ReviewDecisionStatus.QUARANTINED
                reason = evidence_fault.message
            else:
                final = ReviewAction.HOLD
                status = ReviewDecisionStatus.HELD
                reason = evidence_fault.message
            return _decision(
                report=report,
                requested=requested,
                final=final,
                status=status,
                ok=status is not ReviewDecisionStatus.REJECTED,
                reason=reason,
                reviewer_id=item.reviewer_id,
                rationale=item.rationale,
                registry_state_before=registry_state_before,
                registry_state_after=registry_state_before,
                faults=(evidence_fault,),
                tags=item.tags,
            )

        if requested is ReviewAction.HOLD:
            return _decision(
                report=report,
                requested=requested,
                final=ReviewAction.HOLD,
                status=ReviewDecisionStatus.HELD,
                ok=True,
                reason="clean regression report held for later admin decision",
                reviewer_id=item.reviewer_id,
                rationale=item.rationale,
                registry_state_before=registry_state_before,
                registry_state_after=registry_state_before,
                tags=item.tags,
            )
        if requested is ReviewAction.REJECT:
            return _decision(
                report=report,
                requested=requested,
                final=ReviewAction.REJECT,
                status=ReviewDecisionStatus.REJECTED,
                ok=True,
                reason="clean regression report intentionally rejected by admin review",
                reviewer_id=item.reviewer_id,
                rationale=item.rationale,
                registry_state_before=registry_state_before,
                registry_state_after=registry_state_before,
                tags=item.tags,
            )
        if requested is ReviewAction.QUARANTINE:
            return _decision(
                report=report,
                requested=requested,
                final=ReviewAction.QUARANTINE,
                status=ReviewDecisionStatus.QUARANTINED,
                ok=True,
                reason="clean regression report quarantined for additional fixture coverage",
                reviewer_id=item.reviewer_id,
                rationale=item.rationale,
                registry_state_before=registry_state_before,
                registry_state_after=registry_state_before,
                tags=item.tags,
            )

        if apply_registry:
            if not self.policy.allow_registry_approval:
                return _decision(
                    report=report,
                    requested=requested,
                    final=ReviewAction.APPROVE,
                    status=ReviewDecisionStatus.REGISTRY_REJECTED,
                    ok=False,
                    reason="registry approval is disabled by batch review policy",
                    reviewer_id=item.reviewer_id,
                    rationale=item.rationale,
                    registry_state_before=registry_state_before,
                    registry_state_after=registry_state_before,
                    faults=(ReviewFault("review.policy.registry_approval_disabled", "registry approval is disabled by batch review policy"),),
                    tags=item.tags,
                )
            if registry is None:
                return _decision(
                    report=report,
                    requested=requested,
                    final=ReviewAction.APPROVE,
                    status=ReviewDecisionStatus.REGISTRY_REJECTED,
                    ok=False,
                    reason="registry approval requested without registry",
                    reviewer_id=item.reviewer_id,
                    rationale=item.rationale,
                    faults=(ReviewFault("review.registry.missing", "registry approval requested without registry"),),
                    tags=item.tags,
                )
            try:
                record = registry.require(str(report.driver_id))
                registry_state_before = record.state.value
                if self.policy.require_registry_candidate and record.state is not DriverState.CANDIDATE:
                    raise RegistryError("only candidate drivers can be batch approved")
                record = registry.approve(str(report.driver_id))
                registry_state_after = record.state.value
                return _decision(
                    report=report,
                    requested=requested,
                    final=ReviewAction.APPROVE,
                    status=ReviewDecisionStatus.REGISTRY_APPROVED,
                    ok=True,
                    reason="clean regression report approved in registry",
                    reviewer_id=item.reviewer_id,
                    rationale=item.rationale,
                    registry_state_before=registry_state_before,
                    registry_state_after=registry_state_after,
                    tags=item.tags,
                )
            except Exception as exc:
                return _decision(
                    report=report,
                    requested=requested,
                    final=ReviewAction.APPROVE,
                    status=ReviewDecisionStatus.REGISTRY_REJECTED,
                    ok=False,
                    reason=str(exc),
                    reviewer_id=item.reviewer_id,
                    rationale=item.rationale,
                    registry_state_before=registry_state_before,
                    registry_state_after=registry_state_before,
                    faults=(ReviewFault("review.registry.approval_rejected", str(exc)),),
                    tags=item.tags,
                )

        return _decision(
            report=report,
            requested=requested,
            final=ReviewAction.APPROVE,
            status=ReviewDecisionStatus.APPROVAL_READY,
            ok=True,
            reason="clean regression report is approval-ready; registry signing and activation remain separate",
            reviewer_id=item.reviewer_id,
            rationale=item.rationale,
            registry_state_before=registry_state_before,
            registry_state_after=registry_state_before,
            tags=item.tags,
        )


def batch_review_capability_matrix(policy: BatchReviewPolicy | None = None) -> Mapping[str, bool]:
    """Convenience function for displaying Admin batch review authority."""

    return DriverBatchReviewBoard(policy=policy).capability_matrix()


def _coerce_item(
    item: DriverRegressionReport | DriverReviewItem | Mapping[str, Any],
    *,
    reviewer_id: str,
    requested_action: ReviewAction | str,
    rationale: str,
    action_overrides: Mapping[str, ReviewAction | str],
) -> DriverReviewItem:
    if isinstance(item, DriverReviewItem):
        override = _override_for(item.report, action_overrides)
        if override is None:
            return item
        return DriverReviewItem(
            report=item.report,
            requested_action=override,
            reviewer_id=item.reviewer_id,
            rationale=item.rationale,
            tags=item.tags,
        )
    if isinstance(item, DriverRegressionReport):
        override = _override_for(item, action_overrides) or requested_action
        return DriverReviewItem(
            report=item,
            requested_action=override,
            reviewer_id=reviewer_id,
            rationale=rationale,
        )
    if not isinstance(item, Mapping):
        raise TypeError("review item must be DriverRegressionReport, DriverReviewItem, or mapping")
    report = item.get("report")
    if not isinstance(report, DriverRegressionReport):
        raise TypeError("review item mapping requires a DriverRegressionReport under 'report'")
    override = _override_for(report, action_overrides)
    return DriverReviewItem(
        report=report,
        requested_action=override or item.get("requested_action", requested_action),
        reviewer_id=str(item.get("reviewer_id", reviewer_id)),
        rationale=str(item.get("rationale", rationale)),
        tags=tuple(str(tag) for tag in item.get("tags", ())),
    )


def _override_for(report: DriverRegressionReport, overrides: Mapping[str, ReviewAction | str]) -> ReviewAction | str | None:
    if report.driver_id and report.driver_id in overrides:
        return overrides[report.driver_id]
    if report.report_hash in overrides:
        return overrides[report.report_hash]
    return None


def _action_value(value: ReviewAction | str) -> ReviewAction:
    if isinstance(value, ReviewAction):
        return value
    return ReviewAction(str(value))


def _evidence_fault(report: DriverRegressionReport, policy: BatchReviewPolicy) -> ReviewFault | None:
    if policy.require_clean_regression and not report.ok:
        return ReviewFault(
            "review.evidence.regression_not_clean",
            "regression report is not clean enough for approval",
        )
    if report.status is RegressionStatus.INPUT_REJECTED:
        return ReviewFault(
            "review.evidence.input_rejected",
            "regression report input was rejected",
        )
    if policy.require_batch_review_ready and report.recommendation != "batch_review_ready":
        return ReviewFault(
            "review.evidence.not_batch_ready",
            "regression report is not marked batch_review_ready",
        )
    if report.failed_count:
        return ReviewFault(
            "review.evidence.failed_cases",
            "regression report contains failed fixture cases",
        )
    if policy.require_runtime_execution_ok:
        bad_runtime = [result.case_id for result in report.results if not result.evidence.ok]
        if bad_runtime:
            return ReviewFault(
                "review.evidence.runtime_not_clean",
                "regression report contains non-clean runtime evidence",
            )
    return None


def _decision(
    *,
    report: DriverRegressionReport,
    requested: ReviewAction,
    final: ReviewAction,
    status: ReviewDecisionStatus,
    ok: bool,
    reason: str,
    reviewer_id: str,
    rationale: str,
    registry_state_before: str | None = None,
    registry_state_after: str | None = None,
    faults: tuple[ReviewFault, ...] = (),
    tags: tuple[str, ...] = (),
) -> DriverReviewDecision:
    risk_level = _risk_level(report, status=status, faults=faults)
    evidence_summary = _evidence_summary(report)
    review_hash = _review_hash(
        driver_id=report.driver_id,
        driver_version=report.driver_version,
        requested_action=requested.value,
        final_action=final.value,
        status=status.value,
        ok=ok,
        reason=reason,
        reviewer_id=reviewer_id,
        rationale=rationale,
        report_hash=report.report_hash,
        package_hash=report.package_hash,
        regression_status=report.status.value,
        risk_level=risk_level,
        evidence_summary=evidence_summary,
        registry_state_before=registry_state_before,
        registry_state_after=registry_state_after,
        faults=[fault.code for fault in faults],
        tags=list(tags),
    )
    return DriverReviewDecision(
        driver_id=report.driver_id,
        driver_version=report.driver_version,
        requested_action=requested,
        final_action=final,
        status=status,
        ok=ok,
        reason=reason,
        reviewer_id=reviewer_id,
        rationale=rationale,
        report_hash=report.report_hash,
        package_hash=report.package_hash,
        regression_status=report.status.value,
        risk_level=risk_level,
        evidence_summary=evidence_summary,
        registry_state_before=registry_state_before,
        registry_state_after=registry_state_after,
        review_hash=review_hash,
        faults=faults,
        tags=tags,
    )


def _batch_report(
    decisions: tuple[DriverReviewDecision, ...],
    *,
    capability_matrix: Mapping[str, bool],
    batch_id: str | None,
) -> DriverBatchReviewReport:
    approved_count = sum(1 for item in decisions if item.status is ReviewDecisionStatus.APPROVAL_READY)
    registry_approved_count = sum(1 for item in decisions if item.status is ReviewDecisionStatus.REGISTRY_APPROVED)
    held_count = sum(1 for item in decisions if item.status is ReviewDecisionStatus.HELD)
    rejected_count = sum(1 for item in decisions if item.status is ReviewDecisionStatus.REJECTED)
    quarantined_count = sum(1 for item in decisions if item.status is ReviewDecisionStatus.QUARANTINED)
    input_rejected_count = sum(1 for item in decisions if item.status is ReviewDecisionStatus.INPUT_REJECTED)
    registry_rejected_count = sum(1 for item in decisions if item.status is ReviewDecisionStatus.REGISTRY_REJECTED)
    bad_count = input_rejected_count + registry_rejected_count
    status = BatchReviewStatus.COMPLETED if bad_count == 0 else BatchReviewStatus.PARTIAL
    reason = "batch review completed" if bad_count == 0 else "batch review completed with rejected inputs or registry failures"
    batch_hash = _batch_hash(decisions, batch_id=batch_id)
    resolved_batch_id = batch_id or "tds-review-" + batch_hash.split(":", 1)[1][:16]
    return DriverBatchReviewReport(
        ok=bad_count == 0,
        status=status,
        reason=reason,
        batch_id=resolved_batch_id,
        batch_hash=batch_hash,
        decisions=decisions,
        approved_count=approved_count,
        held_count=held_count,
        rejected_count=rejected_count,
        quarantined_count=quarantined_count,
        registry_approved_count=registry_approved_count,
        input_rejected_count=input_rejected_count,
        registry_rejected_count=registry_rejected_count,
        capability_matrix=capability_matrix,
    )


def _input_rejected_batch(
    reason: str,
    *,
    capability_matrix: Mapping[str, bool],
    batch_id: str | None,
) -> DriverBatchReviewReport:
    payload = {"status": BatchReviewStatus.INPUT_REJECTED.value, "reason": reason, "batch_id": batch_id or ""}
    batch_hash = "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return DriverBatchReviewReport(
        ok=False,
        status=BatchReviewStatus.INPUT_REJECTED,
        reason=f"invalid batch review input: {reason}",
        batch_id=batch_id or "tds-review-" + batch_hash.split(":", 1)[1][:16],
        batch_hash=batch_hash,
        decisions=(),
        input_rejected_count=1,
        capability_matrix=capability_matrix,
    )


def _risk_level(report: DriverRegressionReport, *, status: ReviewDecisionStatus, faults: tuple[ReviewFault, ...]) -> str:
    if status in {ReviewDecisionStatus.REJECTED, ReviewDecisionStatus.INPUT_REJECTED, ReviewDecisionStatus.REGISTRY_REJECTED}:
        return "high"
    if faults or not report.ok or report.failed_count:
        return "high"
    runtime_fault_codes = [fault for result in report.results for fault in result.evidence.faults]
    mismatch_count = sum(len(result.mismatches) for result in report.results)
    if runtime_fault_codes or mismatch_count or status is ReviewDecisionStatus.QUARANTINED:
        return "medium"
    return "low"


def _evidence_summary(report: DriverRegressionReport) -> Mapping[str, Any]:
    fault_codes: list[str] = []
    runtime_statuses: list[str] = []
    trace_complete_count = 0
    for result in report.results:
        runtime_statuses.append(result.status.value)
        if result.evidence.trace_complete:
            trace_complete_count += 1
        fault_codes.extend(fault.code for fault in result.evidence.faults)
    return {
        "case_count": report.case_count,
        "passed_count": report.passed_count,
        "failed_count": report.failed_count,
        "failed_cases": list(report.failed_cases),
        "recommendation": report.recommendation,
        "runtime_statuses": sorted(set(runtime_statuses)),
        "fault_codes": sorted(set(fault_codes)),
        "trace_complete_count": trace_complete_count,
    }


def _review_hash(**items: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(_normalize_json(items)).encode("utf-8")).hexdigest()


def _batch_hash(decisions: tuple[DriverReviewDecision, ...], *, batch_id: str | None) -> str:
    payload = {
        "batch_id": batch_id or "",
        "decisions": [
            {
                "driver_id": decision.driver_id,
                "driver_version": decision.driver_version,
                "status": decision.status.value,
                "review_hash": decision.review_hash,
            }
            for decision in decisions
        ],
    }
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

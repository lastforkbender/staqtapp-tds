"""Driver Studio admin review action submission layer.

v3.1.8 adds the first carefully bounded mutation-adjacent Studio seam. Studio
may collect admin intent and submit review actions to the existing review
authority, but it still cannot approve by itself, sign, activate, execute
bytecode, mutate the Registry directly, write storage, or carry private keys.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .evidence import DriverEvidenceBundle
from .registry import DriverRegistry
from .regression import DriverRegressionReport
from .review import DriverBatchReviewBoard, DriverBatchReviewReport, DriverReviewDecision, ReviewAction
from .studio import DriverStudioConsoleSnapshot, DriverStudioReadOnlyConsole


class StudioReviewSubmissionStatus(str, Enum):
    """Top-level result for Studio-submitted admin review actions."""

    SUBMITTED = "submitted"
    AUTHORITY_ACCEPTED = "authority_accepted"
    AUTHORITY_REJECTED = "authority_rejected"
    POLICY_REJECTED = "policy_rejected"
    INPUT_REJECTED = "input_rejected"


class StudioReviewActionStatus(str, Enum):
    """Per-driver status for a Studio action request."""

    RECORDED = "recorded"
    AUTHORITY_ACCEPTED = "authority_accepted"
    AUTHORITY_REJECTED = "authority_rejected"
    POLICY_REJECTED = "policy_rejected"
    INPUT_REJECTED = "input_rejected"


@dataclass(frozen=True, slots=True)
class StudioReviewSubmissionPolicy:
    """Input and routing policy for Driver Studio admin action submission.

    ``allow_registry_approval_request`` only allows Studio to ask the review
    authority to apply registry approval. It does not give Studio permission to
    call ``DriverRegistry.approve``. The review board policy and Registry remain
    the actual trust authorities.
    """

    max_actions: int = 64
    require_verified_evidence: bool = True
    require_driver_present: bool = True
    require_rationale_for_reject: bool = True
    require_rationale_for_quarantine: bool = True
    allow_registry_approval_request: bool = False
    allowed_reviewers: frozenset[str] | None = None
    allowed_actions: frozenset[ReviewAction] = field(
        default_factory=lambda: frozenset(
            (ReviewAction.APPROVE, ReviewAction.HOLD, ReviewAction.REJECT, ReviewAction.QUARANTINE)
        )
    )


@dataclass(frozen=True, slots=True)
class StudioReviewActionRequest:
    """One admin action captured by Studio for authority review."""

    driver_id: str
    requested_action: ReviewAction | str
    reviewer_id: str = "studio-admin"
    rationale: str = ""
    source_panel: str = "driver_queue"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StudioReviewActionEvent:
    """Deterministic action-submission event for Studio audit surfaces."""

    event_id: str
    event_type: str
    actor_id: str
    action: str
    driver_id: str | None
    timestamp: str
    reason: str
    evidence_bundle_hash: str | None = None
    source_review_hash: str | None = None
    submission_hash: str | None = None
    authority_batch_hash: str | None = None
    authority_status: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StudioReviewActionDecision:
    """Per-driver result after Studio records or routes an admin action."""

    driver_id: str | None
    requested_action: ReviewAction
    status: StudioReviewActionStatus
    ok: bool
    reason: str
    reviewer_id: str
    rationale: str
    evidence_bundle_hash: str | None
    source_review_hash: str | None = None
    authority_status: str | None = None
    authority_review_hash: str | None = None
    registry_state_before: str | None = None
    registry_state_after: str | None = None
    decision_hash: str = ""
    fault_code: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StudioReviewSubmissionReport:
    """Immutable report for Driver Studio admin action submission."""

    ok: bool
    status: StudioReviewSubmissionStatus
    reason: str
    submission_id: str
    submission_hash: str
    evidence_bundle_hash: str | None
    request_registry_approval: bool
    decisions: tuple[StudioReviewActionDecision, ...]
    audit_events: tuple[StudioReviewActionEvent, ...]
    authority_batch_hash: str | None = None
    authority_report: DriverBatchReviewReport | None = None
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    @property
    def accepted_driver_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.driver_id
            for decision in self.decisions
            if decision.driver_id and decision.status is StudioReviewActionStatus.AUTHORITY_ACCEPTED
        )

    def to_dict(self) -> Mapping[str, Any]:
        return _submission_report_map(self)

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


class DriverStudioAdminReviewActions:
    """Bounded Studio layer for submitting admin review actions.

    This object is intentionally not a trust authority. It validates the current
    read-only evidence console, records admin intent, and optionally routes the
    request to ``DriverBatchReviewBoard``. Registry state changes can occur only
    if the caller supplies a Registry, the Studio policy permits requesting that
    route, and the review board policy independently permits registry approval.
    """

    def __init__(
        self,
        *,
        policy: StudioReviewSubmissionPolicy | None = None,
        readonly_console: DriverStudioReadOnlyConsole | None = None,
    ) -> None:
        self.policy = policy or StudioReviewSubmissionPolicy()
        if self.policy.max_actions < 1:
            raise ValueError("max_actions must be positive")
        self.readonly_console = readonly_console or DriverStudioReadOnlyConsole()

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the Studio admin-action authority map."""

        return {
            "load_readonly_console_snapshot": True,
            "submit_review_actions": True,
            "create_action_audit_records": True,
            "route_to_batch_review_authority": True,
            "request_registry_approval_route": self.policy.allow_registry_approval_request,
            "approve_driver": False,
            "reject_driver": False,
            "quarantine_driver": False,
            "call_registry_approve": False,
            "sign_driver": False,
            "attach_signature": False,
            "activate_driver": False,
            "edit_tddl": False,
            "edit_bytecode": False,
            "run_driver_vm": False,
            "write_storage": False,
            "execute_python": False,
            "mutate_registry": False,
            "store_private_keys": False,
            "bypass_policy": False,
        }

    def submit_actions(
        self,
        console_or_bundle: DriverStudioConsoleSnapshot | DriverEvidenceBundle | Mapping[str, Any] | str,
        actions: Sequence[StudioReviewActionRequest | Mapping[str, Any]],
        *,
        regression_reports: Sequence[DriverRegressionReport] | Mapping[str, DriverRegressionReport] | None = None,
        review_board: DriverBatchReviewBoard | None = None,
        registry: DriverRegistry | None = None,
        request_registry_approval: bool = False,
        submitted_at: str = "undated",
        submission_id: str | None = None,
        authority_batch_id: str | None = None,
    ) -> StudioReviewSubmissionReport:
        """Validate, audit, and optionally route Studio review actions.

        If ``regression_reports`` is omitted, Studio records only the immutable
        action submission. If reports are supplied, the requests are routed to
        ``DriverBatchReviewBoard`` for authoritative review decisions.
        """

        matrix = self.capability_matrix()
        try:
            console = self._console(console_or_bundle)
            requests = tuple(_coerce_action_request(item) for item in actions)
            self._validate_requests(console, requests, request_registry_approval=request_registry_approval)
        except Exception as exc:
            return _input_rejected_submission(
                str(exc),
                capability_matrix=matrix,
                submitted_at=submitted_at,
                submission_id=submission_id,
                request_registry_approval=request_registry_approval,
            )

        evidence_bundle_hash = console.bundle_hash
        request_decisions = tuple(
            _recorded_decision(request, console=console, evidence_bundle_hash=evidence_bundle_hash)
            for request in requests
        )

        if request_registry_approval and not self.policy.allow_registry_approval_request:
            decisions = tuple(
                _replace_decision_status(
                    decision,
                    status=StudioReviewActionStatus.POLICY_REJECTED,
                    ok=False,
                    reason="registry approval route was requested but is disabled by Studio submission policy",
                    fault_code="studio.policy.registry_route_disabled",
                )
                for decision in request_decisions
            )
            return _submission_report(
                status=StudioReviewSubmissionStatus.POLICY_REJECTED,
                reason="Studio policy rejected registry approval routing request",
                decisions=decisions,
                capability_matrix=matrix,
                submitted_at=submitted_at,
                submission_id=submission_id,
                evidence_bundle_hash=evidence_bundle_hash,
                request_registry_approval=request_registry_approval,
            )

        reports = _report_sequence(regression_reports)
        if not reports:
            return _submission_report(
                status=StudioReviewSubmissionStatus.SUBMITTED,
                reason="Studio review actions recorded; no regression reports supplied for authority routing",
                decisions=request_decisions,
                capability_matrix=matrix,
                submitted_at=submitted_at,
                submission_id=submission_id,
                evidence_bundle_hash=evidence_bundle_hash,
                request_registry_approval=request_registry_approval,
            )

        try:
            selected_reports = _reports_for_requests(reports, requests)
            action_overrides = {request.driver_id: _review_action_value(request.requested_action) for request in requests}
            reviewer_id = requests[0].reviewer_id if requests else "studio-admin"
            rationale = requests[0].rationale if requests else ""
            board = review_board or DriverBatchReviewBoard()
            authority = board.review_reports(
                selected_reports,
                reviewer_id=reviewer_id,
                rationale=rationale,
                action_overrides=action_overrides,
                registry=registry,
                apply_registry=request_registry_approval,
                batch_id=authority_batch_id,
            )
        except Exception as exc:
            decisions = tuple(
                _replace_decision_status(
                    decision,
                    status=StudioReviewActionStatus.AUTHORITY_REJECTED,
                    ok=False,
                    reason=str(exc),
                    fault_code="studio.authority.routing_failed",
                )
                for decision in request_decisions
            )
            return _submission_report(
                status=StudioReviewSubmissionStatus.AUTHORITY_REJECTED,
                reason=f"review authority rejected Studio submission: {exc}",
                decisions=decisions,
                capability_matrix=matrix,
                submitted_at=submitted_at,
                submission_id=submission_id,
                evidence_bundle_hash=evidence_bundle_hash,
                request_registry_approval=request_registry_approval,
            )

        authority_by_driver = {str(decision.driver_id): decision for decision in authority.decisions if decision.driver_id}
        routed_decisions = tuple(
            _decision_from_authority(
                recorded,
                authority_by_driver.get(str(recorded.driver_id)),
                authority_batch_hash=authority.batch_hash,
            )
            for recorded in request_decisions
        )
        status = StudioReviewSubmissionStatus.AUTHORITY_ACCEPTED if authority.ok else StudioReviewSubmissionStatus.AUTHORITY_REJECTED
        reason = (
            "Studio review actions routed to batch review authority"
            if authority.ok
            else "Studio review actions reached authority but authority returned failures"
        )
        return _submission_report(
            status=status,
            reason=reason,
            decisions=routed_decisions,
            capability_matrix=matrix,
            submitted_at=submitted_at,
            submission_id=submission_id,
            evidence_bundle_hash=evidence_bundle_hash,
            request_registry_approval=request_registry_approval,
            authority_report=authority,
        )

    # Short aliases for service/UI code.
    submit = submit_actions
    route = submit_actions

    def _console(
        self,
        console_or_bundle: DriverStudioConsoleSnapshot | DriverEvidenceBundle | Mapping[str, Any] | str,
    ) -> DriverStudioConsoleSnapshot:
        if isinstance(console_or_bundle, DriverStudioConsoleSnapshot):
            return console_or_bundle
        return self.readonly_console.open_bundle(console_or_bundle)

    def _validate_requests(
        self,
        console: DriverStudioConsoleSnapshot,
        requests: Sequence[StudioReviewActionRequest],
        *,
        request_registry_approval: bool,
    ) -> None:
        if self.policy.require_verified_evidence and console.integrity_status != "verified":
            raise ValueError("Studio admin actions require a verified evidence bundle")
        if not requests:
            raise ValueError("at least one Studio review action is required")
        if len(requests) > self.policy.max_actions:
            raise ValueError("Studio review action count exceeds max_actions")
        reviewer_ids = {request.reviewer_id for request in requests}
        if self.policy.allowed_reviewers is not None:
            denied = sorted(reviewer for reviewer in reviewer_ids if reviewer not in self.policy.allowed_reviewers)
            if denied:
                raise ValueError(f"reviewer is not allowed: {denied[0]}")
        known_driver_ids = {item.driver_id for item in console.queue if item.driver_id}
        seen: set[str] = set()
        for request in requests:
            action = _review_action_value(request.requested_action)
            if action not in self.policy.allowed_actions:
                raise ValueError(f"Studio review action is not allowed: {action.value}")
            if not request.driver_id:
                raise ValueError("Studio review action requires a driver_id")
            if request.driver_id in seen:
                raise ValueError(f"duplicate Studio review action for driver: {request.driver_id}")
            seen.add(request.driver_id)
            if self.policy.require_driver_present and request.driver_id not in known_driver_ids:
                raise ValueError(f"driver is not present in current evidence console: {request.driver_id}")
            if action is ReviewAction.REJECT and self.policy.require_rationale_for_reject and not request.rationale.strip():
                raise ValueError("reject actions require a rationale")
            if action is ReviewAction.QUARANTINE and self.policy.require_rationale_for_quarantine and not request.rationale.strip():
                raise ValueError("quarantine actions require a rationale")
        if request_registry_approval and any(_review_action_value(request.requested_action) is not ReviewAction.APPROVE for request in requests):
            raise ValueError("registry approval routing can only be requested for approve actions")


def studio_admin_review_capability_matrix(
    policy: StudioReviewSubmissionPolicy | None = None,
) -> Mapping[str, bool]:
    """Convenience function for displaying Studio admin-action authority."""

    return DriverStudioAdminReviewActions(policy=policy).capability_matrix()


def _coerce_action_request(item: StudioReviewActionRequest | Mapping[str, Any]) -> StudioReviewActionRequest:
    if isinstance(item, StudioReviewActionRequest):
        return item
    if not isinstance(item, Mapping):
        raise TypeError("Studio review action must be StudioReviewActionRequest or mapping")
    return StudioReviewActionRequest(
        driver_id=str(item.get("driver_id", "")),
        requested_action=item.get("requested_action", ReviewAction.APPROVE),
        reviewer_id=str(item.get("reviewer_id", "studio-admin")),
        rationale=str(item.get("rationale", "")),
        source_panel=str(item.get("source_panel", "driver_queue")),
        tags=tuple(str(tag) for tag in item.get("tags", ())),
    )


def _review_action_value(value: ReviewAction | str) -> ReviewAction:
    if isinstance(value, ReviewAction):
        return value
    return ReviewAction(str(value))


def _record_for_driver(console: DriverStudioConsoleSnapshot, driver_id: str | None) -> Mapping[str, Any]:
    if driver_id is None:
        return {}
    for item in console.to_dict().get("queue", ()):  # queue has stable review_hash/regression hashes.
        if item.get("driver_id") == driver_id:
            return item
    return {}


def _recorded_decision(
    request: StudioReviewActionRequest,
    *,
    console: DriverStudioConsoleSnapshot,
    evidence_bundle_hash: str | None,
) -> StudioReviewActionDecision:
    action = _review_action_value(request.requested_action)
    record = _record_for_driver(console, request.driver_id)
    return _action_decision(
        driver_id=request.driver_id,
        requested_action=action,
        status=StudioReviewActionStatus.RECORDED,
        ok=True,
        reason="Studio review action recorded for authority routing",
        reviewer_id=request.reviewer_id,
        rationale=request.rationale,
        evidence_bundle_hash=evidence_bundle_hash,
        source_review_hash=_optional_str(record.get("review_hash")),
        registry_state_before=_optional_str(record.get("registry_state_before")),
        registry_state_after=_optional_str(record.get("registry_state_after")),
        tags=tuple(request.tags),
    )


def _replace_decision_status(
    decision: StudioReviewActionDecision,
    *,
    status: StudioReviewActionStatus,
    ok: bool,
    reason: str,
    fault_code: str | None = None,
    authority_status: str | None = None,
    authority_review_hash: str | None = None,
    registry_state_before: str | None = None,
    registry_state_after: str | None = None,
) -> StudioReviewActionDecision:
    return _action_decision(
        driver_id=decision.driver_id,
        requested_action=decision.requested_action,
        status=status,
        ok=ok,
        reason=reason,
        reviewer_id=decision.reviewer_id,
        rationale=decision.rationale,
        evidence_bundle_hash=decision.evidence_bundle_hash,
        source_review_hash=decision.source_review_hash,
        authority_status=authority_status,
        authority_review_hash=authority_review_hash,
        registry_state_before=registry_state_before if registry_state_before is not None else decision.registry_state_before,
        registry_state_after=registry_state_after if registry_state_after is not None else decision.registry_state_after,
        fault_code=fault_code,
        tags=decision.tags,
    )


def _decision_from_authority(
    recorded: StudioReviewActionDecision,
    authority: DriverReviewDecision | None,
    *,
    authority_batch_hash: str,
) -> StudioReviewActionDecision:
    if authority is None:
        return _replace_decision_status(
            recorded,
            status=StudioReviewActionStatus.AUTHORITY_REJECTED,
            ok=False,
            reason="review authority did not return a decision for this driver",
            fault_code="studio.authority.missing_decision",
        )
    status = StudioReviewActionStatus.AUTHORITY_ACCEPTED if authority.ok else StudioReviewActionStatus.AUTHORITY_REJECTED
    return _replace_decision_status(
        recorded,
        status=status,
        ok=authority.ok,
        reason=authority.reason,
        authority_status=authority.status.value,
        authority_review_hash=authority.review_hash,
        registry_state_before=authority.registry_state_before,
        registry_state_after=authority.registry_state_after,
        fault_code=None if authority.ok else (authority.faults[0].code if authority.faults else "studio.authority.rejected"),
    )


def _report_sequence(
    reports: Sequence[DriverRegressionReport] | Mapping[str, DriverRegressionReport] | None,
) -> tuple[DriverRegressionReport, ...]:
    if reports is None:
        return ()
    values = reports.values() if isinstance(reports, Mapping) else reports
    return tuple(values)


def _reports_for_requests(
    reports: Sequence[DriverRegressionReport],
    requests: Sequence[StudioReviewActionRequest],
) -> tuple[DriverRegressionReport, ...]:
    by_driver: dict[str, DriverRegressionReport] = {}
    for report in reports:
        if not isinstance(report, DriverRegressionReport):
            raise TypeError("regression_reports must contain DriverRegressionReport objects")
        if report.driver_id:
            by_driver[str(report.driver_id)] = report
    missing = [request.driver_id for request in requests if request.driver_id not in by_driver]
    if missing:
        raise ValueError(f"missing regression report for Studio action driver: {missing[0]}")
    return tuple(by_driver[request.driver_id] for request in requests)


def _action_decision(
    *,
    driver_id: str | None,
    requested_action: ReviewAction,
    status: StudioReviewActionStatus,
    ok: bool,
    reason: str,
    reviewer_id: str,
    rationale: str,
    evidence_bundle_hash: str | None,
    source_review_hash: str | None = None,
    authority_status: str | None = None,
    authority_review_hash: str | None = None,
    registry_state_before: str | None = None,
    registry_state_after: str | None = None,
    fault_code: str | None = None,
    tags: tuple[str, ...] = (),
) -> StudioReviewActionDecision:
    payload = {
        "driver_id": driver_id,
        "requested_action": requested_action.value,
        "status": status.value,
        "ok": ok,
        "reason": reason,
        "reviewer_id": reviewer_id,
        "rationale": rationale,
        "evidence_bundle_hash": evidence_bundle_hash,
        "source_review_hash": source_review_hash,
        "authority_status": authority_status,
        "authority_review_hash": authority_review_hash,
        "registry_state_before": registry_state_before,
        "registry_state_after": registry_state_after,
        "fault_code": fault_code,
        "tags": list(tags),
    }
    decision_hash = _hash_payload(payload)
    return StudioReviewActionDecision(
        driver_id=driver_id,
        requested_action=requested_action,
        status=status,
        ok=ok,
        reason=reason,
        reviewer_id=reviewer_id,
        rationale=rationale,
        evidence_bundle_hash=evidence_bundle_hash,
        source_review_hash=source_review_hash,
        authority_status=authority_status,
        authority_review_hash=authority_review_hash,
        registry_state_before=registry_state_before,
        registry_state_after=registry_state_after,
        decision_hash=decision_hash,
        fault_code=fault_code,
        tags=tags,
    )


def _submission_report(
    *,
    status: StudioReviewSubmissionStatus,
    reason: str,
    decisions: tuple[StudioReviewActionDecision, ...],
    capability_matrix: Mapping[str, bool],
    submitted_at: str,
    submission_id: str | None,
    evidence_bundle_hash: str | None,
    request_registry_approval: bool,
    authority_report: DriverBatchReviewReport | None = None,
) -> StudioReviewSubmissionReport:
    base = {
        "status": status.value,
        "reason": reason,
        "evidence_bundle_hash": evidence_bundle_hash,
        "request_registry_approval": request_registry_approval,
        "authority_batch_hash": None if authority_report is None else authority_report.batch_hash,
        "decisions": [_action_decision_map(decision) for decision in decisions],
    }
    submission_hash = _hash_payload(base)
    resolved_submission_id = submission_id or "tds-studio-action-" + submission_hash.split(":", 1)[1][:16]
    events = tuple(
        _action_event(
            decision,
            submitted_at=submitted_at,
            submission_hash=submission_hash,
            authority_batch_hash=None if authority_report is None else authority_report.batch_hash,
        )
        for decision in decisions
    )
    ok = status in {StudioReviewSubmissionStatus.SUBMITTED, StudioReviewSubmissionStatus.AUTHORITY_ACCEPTED} and all(
        decision.ok for decision in decisions
    )
    return StudioReviewSubmissionReport(
        ok=ok,
        status=status,
        reason=reason,
        submission_id=resolved_submission_id,
        submission_hash=submission_hash,
        evidence_bundle_hash=evidence_bundle_hash,
        request_registry_approval=request_registry_approval,
        decisions=decisions,
        audit_events=events,
        authority_batch_hash=None if authority_report is None else authority_report.batch_hash,
        authority_report=authority_report,
        capability_matrix=capability_matrix,
    )


def _input_rejected_submission(
    reason: str,
    *,
    capability_matrix: Mapping[str, bool],
    submitted_at: str,
    submission_id: str | None,
    request_registry_approval: bool,
) -> StudioReviewSubmissionReport:
    decision = _action_decision(
        driver_id=None,
        requested_action=ReviewAction.HOLD,
        status=StudioReviewActionStatus.INPUT_REJECTED,
        ok=False,
        reason=reason,
        reviewer_id="studio-admin",
        rationale="",
        evidence_bundle_hash=None,
        fault_code="studio.input_rejected",
    )
    return _submission_report(
        status=StudioReviewSubmissionStatus.INPUT_REJECTED,
        reason=f"invalid Studio review action input: {reason}",
        decisions=(decision,),
        capability_matrix=capability_matrix,
        submitted_at=submitted_at,
        submission_id=submission_id,
        evidence_bundle_hash=None,
        request_registry_approval=request_registry_approval,
    )


def _action_event(
    decision: StudioReviewActionDecision,
    *,
    submitted_at: str,
    submission_hash: str,
    authority_batch_hash: str | None,
) -> StudioReviewActionEvent:
    payload = {
        "event_type": "studio_review_action_submitted",
        "actor_id": decision.reviewer_id,
        "action": decision.requested_action.value,
        "driver_id": decision.driver_id,
        "timestamp": submitted_at,
        "reason": decision.reason,
        "evidence_bundle_hash": decision.evidence_bundle_hash,
        "source_review_hash": decision.source_review_hash,
        "submission_hash": submission_hash,
        "authority_batch_hash": authority_batch_hash,
        "authority_status": decision.authority_status,
        "decision_hash": decision.decision_hash,
        "fault_code": decision.fault_code,
    }
    return StudioReviewActionEvent(
        event_id="tds-studio-audit-" + _hash_payload(payload).split(":", 1)[1][:16],
        event_type="studio_review_action_submitted",
        actor_id=decision.reviewer_id,
        action=decision.requested_action.value,
        driver_id=decision.driver_id,
        timestamp=submitted_at,
        reason=decision.reason,
        evidence_bundle_hash=decision.evidence_bundle_hash,
        source_review_hash=decision.source_review_hash,
        submission_hash=submission_hash,
        authority_batch_hash=authority_batch_hash,
        authority_status=decision.authority_status,
        metadata={"decision_hash": decision.decision_hash, "fault_code": decision.fault_code},
    )


def _submission_report_map(report: StudioReviewSubmissionReport) -> Mapping[str, Any]:
    return {
        "ok": report.ok,
        "status": report.status.value,
        "reason": report.reason,
        "submission_id": report.submission_id,
        "submission_hash": report.submission_hash,
        "evidence_bundle_hash": report.evidence_bundle_hash,
        "request_registry_approval": report.request_registry_approval,
        "authority_batch_hash": report.authority_batch_hash,
        "decisions": [_action_decision_map(decision) for decision in report.decisions],
        "audit_events": [_action_event_map(event) for event in report.audit_events],
        "capability_matrix": dict(report.capability_matrix),
    }


def _action_decision_map(decision: StudioReviewActionDecision) -> Mapping[str, Any]:
    return {
        "driver_id": decision.driver_id,
        "requested_action": decision.requested_action.value,
        "status": decision.status.value,
        "ok": decision.ok,
        "reason": decision.reason,
        "reviewer_id": decision.reviewer_id,
        "rationale": decision.rationale,
        "evidence_bundle_hash": decision.evidence_bundle_hash,
        "source_review_hash": decision.source_review_hash,
        "authority_status": decision.authority_status,
        "authority_review_hash": decision.authority_review_hash,
        "registry_state_before": decision.registry_state_before,
        "registry_state_after": decision.registry_state_after,
        "decision_hash": decision.decision_hash,
        "fault_code": decision.fault_code,
        "tags": list(decision.tags),
    }


def _action_event_map(event: StudioReviewActionEvent) -> Mapping[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "actor_id": event.actor_id,
        "action": event.action,
        "driver_id": event.driver_id,
        "timestamp": event.timestamp,
        "reason": event.reason,
        "evidence_bundle_hash": event.evidence_bundle_hash,
        "source_review_hash": event.source_review_hash,
        "submission_hash": event.submission_hash,
        "authority_batch_hash": event.authority_batch_hash,
        "authority_status": event.authority_status,
        "metadata": dict(event.metadata),
    }


def _hash_payload(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(_normalize_json(value)).encode("utf-8")).hexdigest()


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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)

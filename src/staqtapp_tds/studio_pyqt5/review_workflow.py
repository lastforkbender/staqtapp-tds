"""Review Workflow Console models for the optional Driver Studio PyQt5 cockpit.

v3.1.14 turns the hydrated cockpit and live panel runtime into a richer review
workflow surface.  The console explains readiness, action eligibility, rationale
templates, and review history for human reviewers.  It is still a cockpit layer:
actual submissions are converted into ``StudioReviewActionRequest`` objects and
routed through the existing v3.1.8 action layer / Review Board path.  It never
approves, signs, activates, mutates Registry state, writes storage, executes
trusted drivers, stores private keys, or bypasses policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from staqtapp_tds.drivers.review import ReviewAction
from staqtapp_tds.drivers.studio import StudioPanelKind
from staqtapp_tds.drivers.studio_actions import StudioReviewActionRequest, StudioReviewSubmissionReport
from .bridge import StudioQtBridge
from .hydration import StudioHydratedCockpitState, StudioPanelCard, StudioTimelineItem
from .runtime import StudioLivePanelRuntime, StudioPanelRuntimeState


class StudioReviewWorkflowStatus(str, Enum):
    """Top-level readiness state for the review workflow console."""

    EMPTY = "empty"
    READY = "ready"
    ATTENTION_REQUIRED = "attention_required"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class StudioReviewRationaleTemplate:
    """Stable rationale template surfaced by the Review Workflow Console."""

    template_id: str
    label: str
    requested_action: ReviewAction
    body: str
    tags: tuple[str, ...] = ()
    requires_edit: bool = True
    severity: str = "info"

    def render(self, *, driver_id: str | None = None, reason: str | None = None) -> str:
        """Render a bounded human-editable rationale string."""

        text = self.body.replace("{driver_id}", driver_id or "selected driver")
        text = text.replace("{reason}", reason or "review evidence requires additional human judgment")
        return text

    def as_row(self) -> Mapping[str, Any]:
        return {
            "template_id": self.template_id,
            "label": self.label,
            "requested_action": self.requested_action.value,
            "tags": self.tags,
            "requires_edit": self.requires_edit,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class StudioReviewActionEligibility:
    """Qt-ready action metadata with explicit eligibility explanation."""

    action_id: str
    label: str
    requested_action: ReviewAction
    enabled: bool
    reason: str
    source_panel: StudioPanelKind = StudioPanelKind.RISK_CARD
    requires_rationale: bool = False
    rationale_template_id: str | None = None
    dangerous: bool = False
    authority: str = "review_intent_only"
    severity: str = "info"

    def as_button(self) -> Mapping[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "requested_action": self.requested_action.value,
            "enabled": self.enabled,
            "reason": self.reason,
            "source_panel": self.source_panel.value,
            "requires_rationale": self.requires_rationale,
            "rationale_template_id": self.rationale_template_id,
            "dangerous": self.dangerous,
            "authority": self.authority,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class StudioReviewWorkflowItem:
    """One driver row in the Review Workflow Console."""

    driver_id: str | None
    driver_version: int | None
    selected: bool
    decision_status: str
    risk_level: str
    final_action: str
    readiness_status: StudioReviewWorkflowStatus
    readiness_score: int
    recommended_action: ReviewAction
    actions: tuple[StudioReviewActionEligibility, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    registry_state_before: str | None = None
    registry_state_after: str | None = None
    package_hash: str | None = None
    regression_report_hash: str | None = None
    review_hash: str | None = None

    @property
    def approval_ready(self) -> bool:
        return self.decision_status in {"approval_ready", "registry_approved"}

    @property
    def needs_attention(self) -> bool:
        return self.readiness_status in {StudioReviewWorkflowStatus.ATTENTION_REQUIRED, StudioReviewWorkflowStatus.BLOCKED}

    def action(self, requested_action: ReviewAction | str) -> StudioReviewActionEligibility:
        wanted = requested_action if isinstance(requested_action, ReviewAction) else ReviewAction(str(requested_action))
        for action in self.actions:
            if action.requested_action is wanted:
                return action
        raise KeyError(wanted.value)

    def as_row(self) -> Mapping[str, Any]:
        return {
            "selected": self.selected,
            "driver_id": self.driver_id,
            "driver_version": self.driver_version,
            "decision_status": self.decision_status,
            "risk_level": self.risk_level,
            "final_action": self.final_action,
            "readiness_status": self.readiness_status.value,
            "readiness_score": self.readiness_score,
            "recommended_action": self.recommended_action.value,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "registry_state_before": self.registry_state_before,
            "registry_state_after": self.registry_state_after,
            "package_hash": self.package_hash,
            "regression_report_hash": self.regression_report_hash,
            "review_hash": self.review_hash,
            "actions": tuple(action.as_button() for action in self.actions),
        }


@dataclass(frozen=True, slots=True)
class StudioReviewHistoryEntry:
    """Review-relevant history item derived from audit/live event surfaces."""

    timestamp: str
    label: str
    severity: str
    actor_id: str
    driver_id: str | None
    action: str | None
    detail: str
    source_event_id: str

    def as_row(self) -> Mapping[str, Any]:
        return {
            "timestamp": self.timestamp,
            "label": self.label,
            "severity": self.severity,
            "actor_id": self.actor_id,
            "driver_id": self.driver_id,
            "action": self.action,
            "detail": self.detail,
            "source_event_id": self.source_event_id,
        }


@dataclass(frozen=True, slots=True)
class StudioReviewWorkflowConsoleState:
    """Complete Review Workflow Console view-model."""

    ok: bool
    status: StudioReviewWorkflowStatus
    reason: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None
    generation: int
    cursor: int
    items: tuple[StudioReviewWorkflowItem, ...]
    selected_item: StudioReviewWorkflowItem | None
    cards: tuple[StudioPanelCard, ...]
    templates: tuple[StudioReviewRationaleTemplate, ...]
    history: tuple[StudioReviewHistoryEntry, ...]
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    @property
    def attention_count(self) -> int:
        return sum(1 for item in self.items if item.needs_attention)

    @property
    def ready_count(self) -> int:
        return sum(1 for item in self.items if item.readiness_status is StudioReviewWorkflowStatus.READY)

    def item(self, driver_id: str) -> StudioReviewWorkflowItem:
        for item in self.items:
            if item.driver_id == driver_id:
                return item
        raise KeyError(driver_id)

    def template(self, template_id: str) -> StudioReviewRationaleTemplate:
        for template in self.templates:
            if template.template_id == template_id:
                return template
        raise KeyError(template_id)

    def action_for_selected(self, requested_action: ReviewAction | str) -> StudioReviewActionEligibility:
        if self.selected_item is None:
            raise RuntimeError("no selected driver is available for review action")
        return self.selected_item.action(requested_action)

    def signal_payload(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "reason": self.reason,
            "selected_driver_id": self.selected_driver_id,
            "bundle_id": self.bundle_id,
            "bundle_hash": self.bundle_hash,
            "console_hash": self.console_hash,
            "generation": self.generation,
            "cursor": self.cursor,
            "item_count": len(self.items),
            "ready_count": self.ready_count,
            "attention_count": self.attention_count,
            "selected_item": None if self.selected_item is None else self.selected_item.as_row(),
            "items": tuple(item.as_row() for item in self.items),
            "cards": tuple(_card_map(card) for card in self.cards),
            "templates": tuple(template.as_row() for template in self.templates),
            "history": tuple(entry.as_row() for entry in self.history),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioReviewWorkflowConsole:
    """Decision-support layer for Studio review workflows.

    The console may build a ``StudioReviewActionRequest`` for the selected
    driver and may delegate review-intent submission to the live panel runtime.
    It does not own the resulting authority decision.
    """

    def __init__(
        self,
        *,
        bridge: StudioQtBridge | None = None,
        runtime: StudioLivePanelRuntime | None = None,
    ) -> None:
        self.bridge = bridge or StudioQtBridge()
        self.runtime = runtime or self.bridge.live_panel_runtime()

    def capability_matrix(self) -> Mapping[str, bool]:
        matrix = dict(self.runtime.capability_matrix())
        matrix.update(
            {
                "review_workflow_console": True,
                "render_review_readiness": True,
                "render_action_eligibility": True,
                "render_rationale_templates": True,
                "render_review_history": True,
                "build_review_action_request": True,
                "submit_review_intent": True,
                "route_review_intent_to_studio_action_layer": True,
                "review_workflow_mutates_backend": False,
                "review_workflow_is_authority": False,
                "approve_driver": False,
                "reject_driver": False,
                "quarantine_driver": False,
                "call_registry_approve": False,
                "sign_driver": False,
                "attach_signature": False,
                "activate_driver": False,
                "run_driver_vm": False,
                "write_storage": False,
                "execute_python": False,
                "mutate_registry": False,
                "store_private_keys": False,
                "bypass_policy": False,
            }
        )
        return matrix

    def current_state(self, runtime_state: StudioPanelRuntimeState | None = None) -> StudioReviewWorkflowConsoleState:
        live_state = runtime_state.live_state if runtime_state is not None else self.runtime.event_bridge.current_state()
        return _workflow_state(
            live_state.hydrated,
            generation=live_state.generation,
            cursor=live_state.cursor,
            capability_matrix=self.capability_matrix(),
            live_events=live_state.events,
        )

    def build_request(
        self,
        driver_id: str,
        action: ReviewAction | str,
        *,
        reviewer_id: str = "studio-admin",
        rationale: str = "",
        source_panel: StudioPanelKind | str = StudioPanelKind.RISK_CARD,
        tags: Sequence[str] = (),
    ) -> StudioReviewActionRequest:
        return self.runtime.event_bridge.bridge.build_action_request(
            driver_id,
            action,
            reviewer_id=reviewer_id,
            rationale=rationale,
            source_panel=source_panel,
            tags=tags,
        )

    def build_selected_request(
        self,
        action: ReviewAction | str,
        *,
        reviewer_id: str = "studio-admin",
        rationale: str = "",
        template_id: str | None = None,
        tags: Sequence[str] = (),
    ) -> StudioReviewActionRequest:
        state = self.current_state()
        if state.selected_item is None or not state.selected_item.driver_id:
            raise RuntimeError("cannot build review request without a selected driver")
        requested = action if isinstance(action, ReviewAction) else ReviewAction(str(action))
        eligibility = state.selected_item.action(requested)
        if not eligibility.enabled:
            raise RuntimeError(f"selected review action is not eligible: {eligibility.reason}")
        resolved_rationale = rationale
        if not resolved_rationale and template_id:
            resolved_rationale = state.template(template_id).render(driver_id=state.selected_item.driver_id, reason=eligibility.reason)
        return self.build_request(
            state.selected_item.driver_id,
            requested,
            reviewer_id=reviewer_id,
            rationale=resolved_rationale,
            source_panel=eligibility.source_panel,
            tags=tuple(tags) or tuple(filter(None, ("review-workflow", template_id))),
        )

    def submit_selected_action(
        self,
        action: ReviewAction | str,
        *,
        reviewer_id: str = "studio-admin",
        rationale: str = "",
        template_id: str | None = None,
        submitted_at: str = "undated",
        tags: Sequence[str] = (),
    ) -> tuple[StudioReviewSubmissionReport, StudioPanelRuntimeState, StudioReviewWorkflowConsoleState]:
        request = self.build_selected_request(
            action,
            reviewer_id=reviewer_id,
            rationale=rationale,
            template_id=template_id,
            tags=tags,
        )
        report, runtime_state = self.runtime.submit_review_action(request, submitted_at=submitted_at)
        return report, runtime_state, self.current_state(runtime_state)

    def signal_payload(self) -> Mapping[str, Any]:
        return self.current_state().signal_payload()


_DEFAULT_TEMPLATES: tuple[StudioReviewRationaleTemplate, ...] = (
    StudioReviewRationaleTemplate(
        "approve.clean_evidence",
        "Approve: clean evidence",
        ReviewAction.APPROVE,
        "{driver_id} has verified evidence and clean fixture review; submit approval intent to the Review Board.",
        tags=("approval", "verified-evidence"),
        requires_edit=False,
        severity="success",
    ),
    StudioReviewRationaleTemplate(
        "hold.more_evidence",
        "Hold: needs more evidence",
        ReviewAction.HOLD,
        "Hold {driver_id}: {reason}.",
        tags=("hold", "more-evidence"),
        requires_edit=True,
        severity="warning",
    ),
    StudioReviewRationaleTemplate(
        "reject.policy_failure",
        "Reject: policy failure",
        ReviewAction.REJECT,
        "Reject {driver_id}: {reason}. Evidence should be corrected and resubmitted through Foundry.",
        tags=("reject", "policy"),
        requires_edit=True,
        severity="danger",
    ),
    StudioReviewRationaleTemplate(
        "quarantine.risk_or_integrity",
        "Quarantine: risk/integrity concern",
        ReviewAction.QUARANTINE,
        "Quarantine {driver_id}: {reason}. Keep this proposal isolated until a fresh evidence bundle is produced.",
        tags=("quarantine", "risk"),
        requires_edit=True,
        severity="danger",
    ),
)


def studio_review_rationale_templates() -> tuple[StudioReviewRationaleTemplate, ...]:
    """Return stable rationale templates for the Review Workflow Console."""

    return _DEFAULT_TEMPLATES


def studio_review_workflow_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying v3.1.14 workflow boundaries."""

    return StudioReviewWorkflowConsole().capability_matrix()


def _workflow_state(
    hydrated: StudioHydratedCockpitState,
    *,
    generation: int,
    cursor: int,
    capability_matrix: Mapping[str, bool],
    live_events: Sequence[Any] = (),
) -> StudioReviewWorkflowConsoleState:
    queue = hydrated.panel(StudioPanelKind.DRIVER_QUEUE)
    items = tuple(_workflow_item(row, hydrated=hydrated) for row in queue.rows)
    selected = _selected_item(items, hydrated.selected_driver_id)
    status = _workflow_status(hydrated, items)
    reason = _workflow_reason(hydrated, status, selected, items)
    cards = _workflow_cards(hydrated, items, selected, status)
    history = _review_history(hydrated, live_events=live_events)
    return StudioReviewWorkflowConsoleState(
        ok=hydrated.ok and bool(items) and status is not StudioReviewWorkflowStatus.BLOCKED,
        status=status,
        reason=reason,
        selected_driver_id=hydrated.selected_driver_id,
        bundle_id=hydrated.bundle_id,
        bundle_hash=hydrated.bundle_hash,
        console_hash=hydrated.console_hash,
        generation=generation,
        cursor=cursor,
        items=items,
        selected_item=selected,
        cards=cards,
        templates=studio_review_rationale_templates(),
        history=history,
        capability_matrix=capability_matrix,
    )


def _workflow_item(row: Mapping[str, Any], *, hydrated: StudioHydratedCockpitState) -> StudioReviewWorkflowItem:
    driver_id = _optional_text(row.get("driver_id"))
    decision_status = str(row.get("decision_status") or "unknown")
    risk_level = str(row.get("risk_level") or "unknown")
    final_action = str(row.get("final_action") or "unknown")
    selected = bool(row.get("selected"))
    readiness_status, score, blockers, warnings, recommended = _readiness(decision_status, risk_level, hydrated.ok, hydrated.status)
    actions = _eligibility_actions(
        driver_id=driver_id,
        selected=selected,
        decision_status=decision_status,
        risk_level=risk_level,
        evidence_ok=hydrated.ok,
        readiness_status=readiness_status,
        blockers=blockers,
    )
    return StudioReviewWorkflowItem(
        driver_id=driver_id,
        driver_version=_optional_int(row.get("driver_version")),
        selected=selected,
        decision_status=decision_status,
        risk_level=risk_level,
        final_action=final_action,
        readiness_status=readiness_status,
        readiness_score=score,
        recommended_action=recommended,
        actions=actions,
        blockers=blockers,
        warnings=warnings,
        registry_state_before=_optional_text(row.get("registry_state_before")),
        registry_state_after=_optional_text(row.get("registry_state_after")),
        package_hash=_optional_text(row.get("package_hash")),
        regression_report_hash=_optional_text(row.get("regression_report_hash")),
        review_hash=_optional_text(row.get("review_hash")),
    )


def _readiness(
    decision_status: str,
    risk_level: str,
    evidence_ok: bool,
    cockpit_status: str,
) -> tuple[StudioReviewWorkflowStatus, int, tuple[str, ...], tuple[str, ...], ReviewAction]:
    blockers: list[str] = []
    warnings: list[str] = []
    lowered_status = decision_status.lower()
    lowered_risk = risk_level.lower()
    if not evidence_ok:
        blockers.append(f"evidence cockpit is not verified-ready: {cockpit_status}")
        return StudioReviewWorkflowStatus.BLOCKED, 0, tuple(blockers), tuple(warnings), ReviewAction.HOLD
    if lowered_status in {"approval_ready", "registry_approved"}:
        if lowered_status == "registry_approved":
            warnings.append("Registry already shows approval; Studio should observe or hold, not duplicate authority.")
            return StudioReviewWorkflowStatus.READY, 88, tuple(blockers), tuple(warnings), ReviewAction.HOLD
        return StudioReviewWorkflowStatus.READY, 96, tuple(blockers), tuple(warnings), ReviewAction.APPROVE
    if lowered_status in {"held"}:
        warnings.append("driver is already held; reviewer may keep hold or reject with rationale")
        return StudioReviewWorkflowStatus.ATTENTION_REQUIRED, 62, tuple(blockers), tuple(warnings), ReviewAction.HOLD
    if lowered_status in {"quarantined"}:
        warnings.append("driver is already quarantined; require fresh evidence before approval")
        return StudioReviewWorkflowStatus.ATTENTION_REQUIRED, 38, tuple(blockers), tuple(warnings), ReviewAction.QUARANTINE
    if lowered_status in {"rejected", "registry_rejected", "input_rejected"}:
        blockers.append("driver is not approval eligible from this evidence bundle")
        return StudioReviewWorkflowStatus.BLOCKED, 18, tuple(blockers), tuple(warnings), ReviewAction.REJECT
    if lowered_risk in {"high", "critical"}:
        warnings.append("risk level requires human rationale before routing review intent")
        return StudioReviewWorkflowStatus.ATTENTION_REQUIRED, 45, tuple(blockers), tuple(warnings), ReviewAction.HOLD
    warnings.append("decision status is unknown; hold until evidence is clearer")
    return StudioReviewWorkflowStatus.ATTENTION_REQUIRED, 50, tuple(blockers), tuple(warnings), ReviewAction.HOLD


def _eligibility_actions(
    *,
    driver_id: str | None,
    selected: bool,
    decision_status: str,
    risk_level: str,
    evidence_ok: bool,
    readiness_status: StudioReviewWorkflowStatus,
    blockers: Sequence[str],
) -> tuple[StudioReviewActionEligibility, ...]:
    has_driver = bool(driver_id)
    base_enabled = bool(has_driver and selected and evidence_ok)
    approval_clean = decision_status == "approval_ready" and readiness_status is StudioReviewWorkflowStatus.READY
    common_blocker = "; ".join(blockers) if blockers else "requires selected verified evidence"
    approve_enabled = bool(base_enabled and approval_clean)
    hold_enabled = bool(has_driver and selected)
    reject_enabled = bool(base_enabled and decision_status not in {"approval_ready", "registry_approved"})
    quarantine_enabled = bool(base_enabled and (risk_level.lower() in {"high", "critical"} or decision_status in {"quarantined", "input_rejected", "registry_rejected"}))
    return (
        StudioReviewActionEligibility(
            action_id="review_workflow.request_approve",
            label="Request Approve",
            requested_action=ReviewAction.APPROVE,
            enabled=approve_enabled,
            reason="clean evidence may be submitted as approval intent; Registry authority remains external" if approve_enabled else common_blocker,
            rationale_template_id="approve.clean_evidence",
            severity="success" if approve_enabled else "muted",
        ),
        StudioReviewActionEligibility(
            action_id="review_workflow.request_hold",
            label="Request Hold",
            requested_action=ReviewAction.HOLD,
            enabled=hold_enabled,
            reason="hold intent can be submitted for the selected driver" if hold_enabled else "requires selected driver",
            rationale_template_id="hold.more_evidence",
            requires_rationale=False,
            severity="warning" if hold_enabled else "muted",
        ),
        StudioReviewActionEligibility(
            action_id="review_workflow.request_reject",
            label="Request Reject",
            requested_action=ReviewAction.REJECT,
            enabled=reject_enabled,
            reason="reject intent requires rationale and Review Board routing" if reject_enabled else common_blocker,
            rationale_template_id="reject.policy_failure",
            requires_rationale=True,
            dangerous=True,
            severity="danger" if reject_enabled else "muted",
        ),
        StudioReviewActionEligibility(
            action_id="review_workflow.request_quarantine",
            label="Request Quarantine",
            requested_action=ReviewAction.QUARANTINE,
            enabled=quarantine_enabled,
            reason="quarantine intent requires rationale and authority review" if quarantine_enabled else common_blocker,
            rationale_template_id="quarantine.risk_or_integrity",
            requires_rationale=True,
            dangerous=True,
            severity="danger" if quarantine_enabled else "muted",
        ),
    )


def _selected_item(items: Sequence[StudioReviewWorkflowItem], selected_driver_id: str | None) -> StudioReviewWorkflowItem | None:
    for item in items:
        if selected_driver_id and item.driver_id == selected_driver_id:
            return item
    for item in items:
        if item.selected:
            return item
    return items[0] if items else None


def _workflow_status(
    hydrated: StudioHydratedCockpitState,
    items: Sequence[StudioReviewWorkflowItem],
) -> StudioReviewWorkflowStatus:
    if not items:
        return StudioReviewWorkflowStatus.EMPTY
    if not hydrated.ok:
        return StudioReviewWorkflowStatus.BLOCKED
    if any(item.readiness_status is StudioReviewWorkflowStatus.BLOCKED for item in items):
        return StudioReviewWorkflowStatus.ATTENTION_REQUIRED
    if any(item.readiness_status is StudioReviewWorkflowStatus.ATTENTION_REQUIRED for item in items):
        return StudioReviewWorkflowStatus.ATTENTION_REQUIRED
    return StudioReviewWorkflowStatus.READY


def _workflow_reason(
    hydrated: StudioHydratedCockpitState,
    status: StudioReviewWorkflowStatus,
    selected: StudioReviewWorkflowItem | None,
    items: Sequence[StudioReviewWorkflowItem],
) -> str:
    if status is StudioReviewWorkflowStatus.EMPTY:
        return "no evidence queue loaded for review workflow"
    if status is StudioReviewWorkflowStatus.BLOCKED:
        return hydrated.reason
    if selected is None:
        return f"{len(items)} review items loaded; select a driver to build action intent"
    return f"selected {selected.driver_id}; recommended action is {selected.recommended_action.value}"


def _workflow_cards(
    hydrated: StudioHydratedCockpitState,
    items: Sequence[StudioReviewWorkflowItem],
    selected: StudioReviewWorkflowItem | None,
    status: StudioReviewWorkflowStatus,
) -> tuple[StudioPanelCard, ...]:
    ready = sum(1 for item in items if item.readiness_status is StudioReviewWorkflowStatus.READY)
    attention = sum(1 for item in items if item.needs_attention)
    cards = [
        StudioPanelCard(
            title="Review Readiness",
            subtitle=status.value.replace("_", " "),
            severity="success" if status is StudioReviewWorkflowStatus.READY else "warning" if status is StudioReviewWorkflowStatus.ATTENTION_REQUIRED else "muted" if status is StudioReviewWorkflowStatus.EMPTY else "danger",
            fields={
                "driver_count": len(items),
                "ready_count": ready,
                "attention_count": attention,
                "bundle_id": hydrated.bundle_id,
                "selected_driver_id": hydrated.selected_driver_id,
            },
            badges=("review-intent-only", "no-registry-mutation"),
        )
    ]
    if selected is not None:
        cards.append(
            StudioPanelCard(
                title=str(selected.driver_id),
                subtitle=f"{selected.decision_status}; recommended {selected.recommended_action.value}",
                severity="success" if selected.readiness_status is StudioReviewWorkflowStatus.READY else "warning" if selected.readiness_status is StudioReviewWorkflowStatus.ATTENTION_REQUIRED else "danger",
                fields={
                    "readiness_score": selected.readiness_score,
                    "risk_level": selected.risk_level,
                    "blockers": selected.blockers,
                    "warnings": selected.warnings,
                    "review_hash": selected.review_hash,
                },
                badges=(selected.readiness_status.value, selected.recommended_action.value),
            )
        )
    return tuple(cards)


def _review_history(
    hydrated: StudioHydratedCockpitState,
    *,
    live_events: Sequence[Any] = (),
) -> tuple[StudioReviewHistoryEntry, ...]:
    try:
        timeline = hydrated.panel(StudioPanelKind.EVENT_CONSOLE).timeline
    except Exception:
        timeline = ()
    entries: list[StudioReviewHistoryEntry] = []
    for item in timeline:
        action = _action_from_label(item.label)
        if action or any(token in item.label.lower() for token in ("review", "audit", "approve", "hold", "reject", "quarantine")):
            entries.append(
                StudioReviewHistoryEntry(
                    timestamp=item.timestamp,
                    label=item.label,
                    severity=item.severity,
                    actor_id=item.actor_id,
                    driver_id=item.driver_id,
                    action=action,
                    detail=item.detail,
                    source_event_id=item.source_event_id,
                )
            )
    for event in live_events:
        label = str(getattr(event, "kind", "live_event"))
        if hasattr(getattr(event, "kind", None), "value"):
            label = str(event.kind.value).replace("_", " ").title()
        action = None
        payload = getattr(event, "payload", {}) or {}
        if isinstance(payload, Mapping):
            raw_action = payload.get("action")
            action = None if raw_action is None else str(raw_action)
        entries.append(
            StudioReviewHistoryEntry(
                timestamp=str(getattr(event, "timestamp", "undated")),
                label=label,
                severity=str(getattr(event, "severity", "info")),
                actor_id=str(getattr(event, "source", "studio_live_bridge")),
                driver_id=_optional_text(getattr(event, "driver_id", None)),
                action=action or _action_from_label(label),
                detail=str(getattr(event, "message", "")),
                source_event_id=str(getattr(event, "event_id", "")),
            )
        )
    return tuple(entries)


def _action_from_label(label: str) -> str | None:
    lowered = label.lower()
    for action in ReviewAction:
        if action.value in lowered:
            return action.value
    return None


def _card_map(card: StudioPanelCard) -> Mapping[str, Any]:
    return {
        "title": card.title,
        "subtitle": card.subtitle,
        "severity": card.severity,
        "fields": dict(card.fields),
        "badges": card.badges,
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None

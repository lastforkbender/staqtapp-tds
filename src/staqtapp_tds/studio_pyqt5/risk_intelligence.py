"""Risk Intelligence Cards for the optional Driver Studio PyQt5 cockpit.

v3.1.16 upgrades the existing risk-card surface into an analysis layer that
cross-checks risk rows, lifecycle timeline evidence, fixture coverage, review
posture, registry observations, and live Studio events.  It is deliberately
non-authoritative: Risk Intelligence can explain, rank, and prepare review
context, but it never approves, rejects, quarantines, signs, activates, runs
trusted drivers, mutates Registry state, writes storage, stores private keys,
or bypasses Runtime Manager / Foundry / Review Board policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from staqtapp_tds.drivers.review import ReviewAction
from staqtapp_tds.drivers.studio import StudioPanelKind
from .hydration import StudioHydratedCockpitState, StudioPanelCard
from .runtime import StudioLivePanelRuntime, StudioPanelRuntimeState


class StudioRiskIntelligenceBand(str, Enum):
    """Stable risk-pressure bands used by the Driver Studio cockpit."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StudioRiskIntelligenceFactor:
    """One explainable risk factor derived from evidence, not authority."""

    factor_id: str
    label: str
    severity: str
    weight: int
    detail: str
    evidence_refs: tuple[str, ...] = ()
    recommended_admin_question: str = ""
    authority: str = "observe_only"

    def as_row(self) -> Mapping[str, Any]:
        return {
            "factor_id": self.factor_id,
            "label": self.label,
            "severity": self.severity,
            "weight": self.weight,
            "detail": self.detail,
            "evidence_refs": self.evidence_refs,
            "recommended_admin_question": self.recommended_admin_question,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioRiskIntelligenceCard:
    """Admin-facing risk card with timeline and review context."""

    driver_id: str | None
    risk_level: str
    decision_status: str
    pressure_score: int
    band: StudioRiskIntelligenceBand
    summary: str
    review_action_hint: ReviewAction
    readiness_label: str
    factors: tuple[StudioRiskIntelligenceFactor, ...]
    evidence_gap_count: int
    latest_lifecycle_stage: str | None
    timeline_event_count: int
    registry_observation_count: int
    blocked_authority: tuple[str, ...]
    fault_codes: tuple[str, ...] = ()
    authority: str = "observe_only"

    @property
    def attention_required(self) -> bool:
        return self.band in {StudioRiskIntelligenceBand.HIGH, StudioRiskIntelligenceBand.CRITICAL, StudioRiskIntelligenceBand.UNKNOWN} or self.evidence_gap_count > 0

    def as_card(self) -> Mapping[str, Any]:
        return {
            "driver_id": self.driver_id,
            "risk_level": self.risk_level,
            "decision_status": self.decision_status,
            "pressure_score": self.pressure_score,
            "band": self.band.value,
            "summary": self.summary,
            "review_action_hint": self.review_action_hint.value,
            "readiness_label": self.readiness_label,
            "factor_count": len(self.factors),
            "evidence_gap_count": self.evidence_gap_count,
            "latest_lifecycle_stage": self.latest_lifecycle_stage,
            "timeline_event_count": self.timeline_event_count,
            "registry_observation_count": self.registry_observation_count,
            "blocked_authority": self.blocked_authority,
            "fault_codes": self.fault_codes,
            "attention_required": self.attention_required,
            "authority": self.authority,
        }

    def signal_payload(self) -> Mapping[str, Any]:
        payload = dict(self.as_card())
        payload["factors"] = tuple(factor.as_row() for factor in self.factors)
        return payload


@dataclass(frozen=True, slots=True)
class StudioRiskIntelligenceState:
    """Complete v3.1.16 Risk Intelligence view-model."""

    ok: bool
    status: str
    reason: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None
    generation: int
    cursor: int
    cards: tuple[StudioRiskIntelligenceCard, ...]
    selected_card: StudioRiskIntelligenceCard | None
    aggregate_pressure_score: int
    attention_count: int
    evidence_gap_count: int
    panel_cards: tuple[StudioPanelCard, ...]
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    def card_for_driver(self, driver_id: str) -> StudioRiskIntelligenceCard:
        for card in self.cards:
            if card.driver_id == driver_id:
                return card
        raise KeyError(driver_id)

    def signal_payload(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "selected_driver_id": self.selected_driver_id,
            "bundle_id": self.bundle_id,
            "bundle_hash": self.bundle_hash,
            "console_hash": self.console_hash,
            "generation": self.generation,
            "cursor": self.cursor,
            "card_count": len(self.cards),
            "aggregate_pressure_score": self.aggregate_pressure_score,
            "attention_count": self.attention_count,
            "evidence_gap_count": self.evidence_gap_count,
            "selected_card": None if self.selected_card is None else self.selected_card.signal_payload(),
            "cards": tuple(card.signal_payload() for card in self.cards),
            "panel_cards": tuple(_panel_card_map(card) for card in self.panel_cards),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioRiskIntelligenceCards:
    """Evidence-facing risk analysis layer for Driver Studio.

    Risk Intelligence consumes already-hydrated Studio state and live events. It
    may recommend which *review intent* an admin should inspect next, but it has
    no method that performs the action or mutates trust state.
    """

    def __init__(self, *, runtime: StudioLivePanelRuntime | None = None) -> None:
        self.runtime = runtime or StudioLivePanelRuntime()

    def capability_matrix(self) -> Mapping[str, bool]:
        matrix = dict(self.runtime.capability_matrix())
        matrix.update(
            {
                "risk_intelligence_cards": True,
                "render_risk_pressure": True,
                "render_evidence_gap_factors": True,
                "render_timeline_risk_context": True,
                "render_fixture_risk_context": True,
                "render_review_action_hints": True,
                "risk_to_review_workflow_context": True,
                "risk_to_evidence_timeline_context": True,
                "risk_intelligence_mutates_backend": False,
                "risk_intelligence_is_authority": False,
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

    def current_state(self, runtime_state: StudioPanelRuntimeState | None = None) -> StudioRiskIntelligenceState:
        live_state = runtime_state.live_state if runtime_state is not None else self.runtime.event_bridge.current_state()
        return _risk_state(
            live_state.hydrated,
            generation=live_state.generation,
            cursor=live_state.cursor,
            capability_matrix=self.capability_matrix(),
            live_events=live_state.events,
        )

    def signal_payload(self) -> Mapping[str, Any]:
        return self.current_state().signal_payload()


def studio_risk_intelligence_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying v3.1.16 Risk Intelligence boundaries."""

    return StudioRiskIntelligenceCards().capability_matrix()


def _risk_state(
    hydrated: StudioHydratedCockpitState,
    *,
    generation: int,
    cursor: int,
    capability_matrix: Mapping[str, bool],
    live_events: Sequence[Any] = (),
) -> StudioRiskIntelligenceState:
    risk_panel = hydrated.panel(StudioPanelKind.RISK_CARD)
    timeline_panel = hydrated.panel(StudioPanelKind.EVIDENCE_TIMELINE)
    fixture_panel = hydrated.panel(StudioPanelKind.FIXTURE_REPLAY)
    registry_panel = hydrated.panel(StudioPanelKind.REGISTRY_STATE)

    timeline_rows = tuple(dict(row) for row in timeline_panel.rows)
    fixture_rows = tuple(dict(row) for row in fixture_panel.rows)
    registry_rows = tuple(dict(row) for row in registry_panel.rows)
    cards = tuple(
        _risk_card_from_row(
            row,
            selected_driver_id=hydrated.selected_driver_id,
            timeline_rows=timeline_rows,
            fixture_rows=fixture_rows,
            registry_rows=registry_rows,
            live_events=live_events,
        )
        for row in risk_panel.rows
    )
    selected = _selected_card(cards, hydrated.selected_driver_id)
    aggregate = int(round(sum(card.pressure_score for card in cards) / len(cards))) if cards else 0
    attention = sum(1 for card in cards if card.attention_required)
    gaps = sum(card.evidence_gap_count for card in cards)
    status = "ready" if cards else "empty"
    reason = risk_panel.summary if cards else "no risk intelligence source rows loaded"
    panel_cards = tuple(risk_panel.cards) + (
        StudioPanelCard(
            title="Risk Intelligence Summary",
            subtitle="Evidence-linked admin analysis; review hints remain intent-only.",
            severity=_aggregate_severity(cards),
            fields={
                "aggregate_pressure_score": aggregate,
                "attention_count": attention,
                "evidence_gap_count": gaps,
                "selected_driver_id": hydrated.selected_driver_id,
                "authority": "observe_only",
            },
            badges=("risk-intelligence", "timeline-linked", "observe-only"),
        ),
    )
    return StudioRiskIntelligenceState(
        ok=hydrated.ok and bool(cards),
        status=status,
        reason=reason,
        selected_driver_id=hydrated.selected_driver_id,
        bundle_id=hydrated.bundle_id,
        bundle_hash=hydrated.bundle_hash,
        console_hash=hydrated.console_hash,
        generation=generation,
        cursor=cursor,
        cards=cards,
        selected_card=selected,
        aggregate_pressure_score=aggregate,
        attention_count=attention,
        evidence_gap_count=gaps,
        panel_cards=panel_cards,
        capability_matrix=capability_matrix,
    )


def _risk_card_from_row(
    row: Mapping[str, Any],
    *,
    selected_driver_id: str | None,
    timeline_rows: Sequence[Mapping[str, Any]],
    fixture_rows: Sequence[Mapping[str, Any]],
    registry_rows: Sequence[Mapping[str, Any]],
    live_events: Sequence[Any],
) -> StudioRiskIntelligenceCard:
    driver_id = _optional_text(row.get("driver_id")) or selected_driver_id
    scoped_timeline = _rows_for_driver(timeline_rows, driver_id)
    scoped_fixtures = _rows_for_driver(fixture_rows, driver_id)
    scoped_registry = _rows_for_driver(registry_rows, driver_id)
    stages = tuple(str(item.get("stage")) for item in scoped_timeline if item.get("stage"))
    latest_stage = _latest_stage(stages)
    missing = _missing_core_stages(stages)
    registry_count = sum(1 for item in scoped_timeline if str(item.get("stage")) in _REGISTRY_STAGES)

    risk_level = str(row.get("risk_level") or "unknown")
    decision_status = str(row.get("decision_status") or "unknown")
    fault_codes = tuple(str(item) for item in row.get("fault_codes", ()) or ())
    blocked = tuple(str(item) for item in row.get("blocked_authority", ()) or ())
    reasons = tuple(str(item) for item in row.get("reasons", ()) or ())

    factors: list[StudioRiskIntelligenceFactor] = []
    risk_weight = _risk_level_weight(risk_level)
    factors.append(
        StudioRiskIntelligenceFactor(
            factor_id="risk.level",
            label="Declared risk level",
            severity=_weight_severity(risk_weight),
            weight=risk_weight,
            detail=f"Risk card reports {risk_level} risk.",
            evidence_refs=("risk_card",),
            recommended_admin_question="Does the declared risk level match the lifecycle evidence?",
        )
    )
    decision_weight = _decision_weight(decision_status)
    factors.append(
        StudioRiskIntelligenceFactor(
            factor_id="review.decision_status",
            label="Review posture",
            severity=_weight_severity(decision_weight),
            weight=decision_weight,
            detail=f"Decision status is {decision_status}.",
            evidence_refs=("risk_card", "review_workflow"),
            recommended_admin_question="Is the current review posture justified by evidence?",
        )
    )
    if fault_codes:
        factors.append(
            StudioRiskIntelligenceFactor(
                factor_id="review.fault_codes",
                label="Review faults present",
                severity="danger",
                weight=min(45, 15 + 10 * len(fault_codes)),
                detail="Fault codes: " + ", ".join(fault_codes),
                evidence_refs=("risk_card", "audit_trail"),
                recommended_admin_question="Which fault code blocks approval readiness?",
            )
        )
    for reason_index, reason in enumerate(reasons[:3], start=1):
        factors.append(
            StudioRiskIntelligenceFactor(
                factor_id=f"risk.reason.{reason_index}",
                label="Risk-card explanation",
                severity="info",
                weight=0,
                detail=reason,
                evidence_refs=("risk_card",),
            )
        )
    if missing:
        factors.append(
            StudioRiskIntelligenceFactor(
                factor_id="timeline.evidence_gaps",
                label="Timeline evidence gaps",
                severity="warning",
                weight=min(35, 8 * len(missing)),
                detail="Missing lifecycle stages: " + ", ".join(missing),
                evidence_refs=("evidence_timeline",),
                recommended_admin_question="Should review wait for a complete lifecycle spine?",
            )
        )
    fixture_factor = _fixture_factor(scoped_fixtures)
    if fixture_factor is not None:
        factors.append(fixture_factor)
    registry_factor = _registry_factor(scoped_registry, scoped_timeline)
    if registry_factor is not None:
        factors.append(registry_factor)
    submitted_count = _live_review_count(live_events, driver_id)
    if submitted_count:
        factors.append(
            StudioRiskIntelligenceFactor(
                factor_id="live.review_intent_submitted",
                label="Live review intent observed",
                severity="info",
                weight=0,
                detail=f"{submitted_count} review-intent event(s) observed in the live cockpit stream.",
                evidence_refs=("live_event_bridge", "review_workflow"),
                recommended_admin_question="Did the submitted rationale match the evidence state?",
                authority="review_intent_only",
            )
        )

    pressure = _clamp_score(sum(max(0, factor.weight) for factor in factors))
    band = _band_for_pressure(pressure, risk_level, decision_status)
    hint = _review_action_hint(decision_status, fault_codes, missing, band)
    readiness = _readiness_label(decision_status, missing, fault_codes, band)
    summary = _summary_for(driver_id, band, pressure, readiness)
    return StudioRiskIntelligenceCard(
        driver_id=driver_id,
        risk_level=risk_level,
        decision_status=decision_status,
        pressure_score=pressure,
        band=band,
        summary=summary,
        review_action_hint=hint,
        readiness_label=readiness,
        factors=tuple(factors),
        evidence_gap_count=len(missing),
        latest_lifecycle_stage=latest_stage,
        timeline_event_count=len(scoped_timeline),
        registry_observation_count=registry_count,
        blocked_authority=blocked,
        fault_codes=fault_codes,
    )


def _fixture_factor(rows: Sequence[Mapping[str, Any]]) -> StudioRiskIntelligenceFactor | None:
    if not rows:
        return StudioRiskIntelligenceFactor(
            factor_id="fixture.coverage_missing",
            label="Fixture coverage missing",
            severity="warning",
            weight=18,
            detail="No fixture replay rows are attached for the selected risk context.",
            evidence_refs=("fixture_replay",),
            recommended_admin_question="Should fixture replay be required before approval readiness?",
        )
    passed = sum(1 for row in rows if bool(row.get("passed")))
    if passed == len(rows):
        return StudioRiskIntelligenceFactor(
            factor_id="fixture.coverage_clean",
            label="Fixture replay clean",
            severity="success",
            weight=0,
            detail=f"{passed}/{len(rows)} fixture case(s) passed.",
            evidence_refs=("fixture_replay",),
        )
    return StudioRiskIntelligenceFactor(
        factor_id="fixture.failures_present",
        label="Fixture replay failures",
        severity="danger",
        weight=35,
        detail=f"{passed}/{len(rows)} fixture case(s) passed.",
        evidence_refs=("fixture_replay",),
        recommended_admin_question="Which failed fixture explains the risk posture?",
    )


def _registry_factor(registry_rows: Sequence[Mapping[str, Any]], timeline_rows: Sequence[Mapping[str, Any]]) -> StudioRiskIntelligenceFactor | None:
    registry_states = tuple(
        _optional_text(row.get("registry_state_after") or row.get("resulting_status") or row.get("registry_state"))
        for row in registry_rows
    )
    registry_states = tuple(state for state in registry_states if state)
    timeline_registry_states = tuple(_optional_text(row.get("registry_state")) for row in timeline_rows if row.get("registry_state"))
    if not registry_states and not timeline_registry_states:
        return StudioRiskIntelligenceFactor(
            factor_id="registry.observation_missing",
            label="Registry observation missing",
            severity="info",
            weight=6,
            detail="No Registry observation is attached yet; Studio remains observe-only.",
            evidence_refs=("registry_state", "evidence_timeline"),
            recommended_admin_question="Is this driver expected to have Registry visibility at this stage?",
        )
    unique = tuple(dict.fromkeys(registry_states + timeline_registry_states))
    return StudioRiskIntelligenceFactor(
        factor_id="registry.observed_state",
        label="Registry state observed",
        severity="info",
        weight=0,
        detail="Observed Registry state(s): " + ", ".join(unique),
        evidence_refs=("registry_state", "evidence_timeline"),
    )


def _rows_for_driver(rows: Sequence[Mapping[str, Any]], driver_id: str | None) -> tuple[Mapping[str, Any], ...]:
    if driver_id is None:
        return tuple(rows)
    scoped = tuple(row for row in rows if row.get("driver_id") in {None, driver_id})
    return scoped or tuple(rows)


_CORE_STAGES = ("proposal", "validated", "compiled", "fixture-tested", "evidence-ready", "review-submitted", "reviewed", "exported")
_REGISTRY_STAGES = {"registry-approval-requested", "approved", "signed", "active", "observed-active"}
_STAGE_ORDER = {
    "draft": 0,
    "proposal": 1,
    "validated": 2,
    "compiled": 3,
    "fixture-tested": 4,
    "evidence-ready": 5,
    "review-submitted": 6,
    "reviewed": 7,
    "registry-approval-requested": 8,
    "approved": 9,
    "signed": 10,
    "active": 11,
    "observed-active": 12,
    "exported": 13,
}


def _missing_core_stages(stages: Sequence[str]) -> tuple[str, ...]:
    present = set(stages)
    return tuple(stage for stage in _CORE_STAGES if stage not in present)


def _latest_stage(stages: Sequence[str]) -> str | None:
    if not stages:
        return None
    return max(stages, key=lambda stage: _STAGE_ORDER.get(stage, -1))


def _risk_level_weight(risk_level: str) -> int:
    return {
        "none": 0,
        "low": 5,
        "moderate": 20,
        "medium": 20,
        "elevated": 30,
        "high": 42,
        "critical": 60,
        "unknown": 22,
    }.get(str(risk_level).lower(), 22)


def _decision_weight(decision_status: str) -> int:
    return {
        "approval_ready": 0,
        "registry_approved": 0,
        "approved": 0,
        "held": 22,
        "hold": 22,
        "quarantined": 48,
        "rejected": 55,
        "registry_rejected": 55,
        "input_rejected": 55,
        "unknown": 28,
    }.get(str(decision_status).lower(), 28)


def _weight_severity(weight: int) -> str:
    if weight >= 45:
        return "danger"
    if weight >= 18:
        return "warning"
    if weight > 0:
        return "info"
    return "success"


def _clamp_score(score: int) -> int:
    return max(0, min(100, int(score)))


def _band_for_pressure(score: int, risk_level: str, decision_status: str) -> StudioRiskIntelligenceBand:
    lowered_risk = risk_level.lower()
    lowered_decision = decision_status.lower()
    if lowered_risk == "unknown" or lowered_decision == "unknown":
        return StudioRiskIntelligenceBand.UNKNOWN
    if score >= 75 or lowered_risk == "critical" or lowered_decision in {"rejected", "registry_rejected", "input_rejected"}:
        return StudioRiskIntelligenceBand.CRITICAL
    if score >= 45 or lowered_risk == "high" or lowered_decision == "quarantined":
        return StudioRiskIntelligenceBand.HIGH
    if score >= 18 or lowered_risk in {"moderate", "medium", "elevated"} or lowered_decision in {"held", "hold"}:
        return StudioRiskIntelligenceBand.MODERATE
    return StudioRiskIntelligenceBand.LOW


def _review_action_hint(
    decision_status: str,
    fault_codes: Sequence[str],
    missing_stages: Sequence[str],
    band: StudioRiskIntelligenceBand,
) -> ReviewAction:
    lowered = decision_status.lower()
    if fault_codes or lowered in {"rejected", "registry_rejected", "input_rejected"}:
        return ReviewAction.REJECT
    if lowered == "quarantined" or band is StudioRiskIntelligenceBand.CRITICAL:
        return ReviewAction.QUARANTINE
    if missing_stages or lowered in {"held", "hold", "unknown"} or band in {StudioRiskIntelligenceBand.MODERATE, StudioRiskIntelligenceBand.UNKNOWN}:
        return ReviewAction.HOLD
    return ReviewAction.APPROVE


def _readiness_label(
    decision_status: str,
    missing_stages: Sequence[str],
    fault_codes: Sequence[str],
    band: StudioRiskIntelligenceBand,
) -> str:
    if fault_codes:
        return "blocked_by_faults"
    if missing_stages:
        return "waiting_for_evidence"
    if decision_status.lower() in {"approval_ready", "registry_approved", "approved"} and band is StudioRiskIntelligenceBand.LOW:
        return "review_ready"
    if band in {StudioRiskIntelligenceBand.HIGH, StudioRiskIntelligenceBand.CRITICAL}:
        return "needs_admin_attention"
    return "review_with_caution"


def _summary_for(driver_id: str | None, band: StudioRiskIntelligenceBand, pressure: int, readiness: str) -> str:
    label = driver_id or "selected driver"
    return f"{label}: {band.value} pressure ({pressure}/100), {readiness.replace('_', ' ')}"


def _live_review_count(events: Sequence[Any], driver_id: str | None) -> int:
    count = 0
    for event in events:
        kind_value = str(getattr(getattr(event, "kind", None), "value", getattr(event, "kind", "")))
        if kind_value != "review_action_submitted":
            continue
        event_driver = _optional_text(getattr(event, "driver_id", None))
        if driver_id is None or event_driver in {None, driver_id}:
            count += 1
    return count


def _selected_card(cards: Sequence[StudioRiskIntelligenceCard], selected_driver_id: str | None) -> StudioRiskIntelligenceCard | None:
    if not cards:
        return None
    if selected_driver_id is None:
        return cards[0]
    for card in cards:
        if card.driver_id == selected_driver_id:
            return card
    return cards[0]


def _aggregate_severity(cards: Sequence[StudioRiskIntelligenceCard]) -> str:
    if not cards:
        return "muted"
    if any(card.band is StudioRiskIntelligenceBand.CRITICAL for card in cards):
        return "danger"
    if any(card.band in {StudioRiskIntelligenceBand.HIGH, StudioRiskIntelligenceBand.UNKNOWN} for card in cards):
        return "warning"
    if any(card.band is StudioRiskIntelligenceBand.MODERATE for card in cards):
        return "info"
    return "success"


def _panel_card_map(card: StudioPanelCard) -> Mapping[str, Any]:
    return {
        "title": card.title,
        "subtitle": card.subtitle,
        "severity": card.severity,
        "fields": dict(card.fields),
        "badges": tuple(card.badges),
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)

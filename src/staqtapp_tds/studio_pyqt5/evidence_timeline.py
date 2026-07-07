"""Evidence Timeline models for the optional Driver Studio PyQt5 cockpit.

v3.1.16 adds a chronological trust-history surface for Studio & Evidence.  The
Evidence Timeline makes proposal, validation, compile, fixture, evidence,
review, Registry observation, and export milestones visible and export-ready.
It is deliberately non-authoritative: it never approves, signs, activates,
executes drivers, mutates Registry trust state, writes storage, stores private
keys, or bypasses Runtime Manager / Foundry / Review Board policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from staqtapp_tds.drivers.studio import StudioPanelKind
from .hydration import StudioHydratedCockpitState, StudioPanelCard
from .runtime import StudioLivePanelRuntime, StudioPanelRuntimeState


class StudioDriverLifecycleStage(str, Enum):
    """Lifecycle stages rendered by the v3.1.16 Evidence Timeline."""

    DRAFT = "draft"
    PROPOSAL = "proposal"
    VALIDATED = "validated"
    COMPILED = "compiled"
    FIXTURE_TESTED = "fixture-tested"
    EVIDENCE_READY = "evidence-ready"
    REVIEW_SUBMITTED = "review-submitted"
    REVIEWED = "reviewed"
    REGISTRY_APPROVAL_REQUESTED = "registry-approval-requested"
    APPROVED = "approved"
    SIGNED = "signed"
    ACTIVE = "active"
    OBSERVED_ACTIVE = "observed-active"
    EXPORTED = "exported"


_STAGE_ORDER: Mapping[StudioDriverLifecycleStage, int] = {
    stage: index for index, stage in enumerate(StudioDriverLifecycleStage)
}


@dataclass(frozen=True, slots=True)
class StudioEvidenceTimelineItem:
    """One chronological lifecycle item surfaced by Driver Studio."""

    timestamp: str
    stage: StudioDriverLifecycleStage
    status: str
    severity: str
    driver_id: str | None
    label: str
    detail: str
    source_event_id: str | None = None
    actor_id: str = "studio-evidence"
    package_hash: str | None = None
    regression_report_hash: str | None = None
    evidence_hash: str | None = None
    review_hash: str | None = None
    registry_state: str | None = None
    export_hash: str | None = None
    authority: str = "observe_only"

    @property
    def registry_related(self) -> bool:
        return self.stage in {
            StudioDriverLifecycleStage.REGISTRY_APPROVAL_REQUESTED,
            StudioDriverLifecycleStage.APPROVED,
            StudioDriverLifecycleStage.SIGNED,
            StudioDriverLifecycleStage.ACTIVE,
            StudioDriverLifecycleStage.OBSERVED_ACTIVE,
        }

    def as_row(self) -> Mapping[str, Any]:
        return {
            "timestamp": self.timestamp,
            "stage": self.stage.value,
            "status": self.status,
            "severity": self.severity,
            "driver_id": self.driver_id,
            "label": self.label,
            "detail": self.detail,
            "source_event_id": self.source_event_id,
            "actor_id": self.actor_id,
            "package_hash": self.package_hash,
            "regression_report_hash": self.regression_report_hash,
            "evidence_hash": self.evidence_hash,
            "review_hash": self.review_hash,
            "registry_state": self.registry_state,
            "export_hash": self.export_hash,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioRegistryObservationItem:
    """Registry-related timeline item extracted for audit/export review."""

    timestamp: str
    driver_id: str | None
    registry_state: str | None
    stage: StudioDriverLifecycleStage
    source_event_id: str | None
    signature_status: str | None = None
    public_key_fingerprint: str | None = None
    authority: str = "observe_only"

    def as_row(self) -> Mapping[str, Any]:
        return {
            "timestamp": self.timestamp,
            "driver_id": self.driver_id,
            "registry_state": self.registry_state,
            "stage": self.stage.value,
            "source_event_id": self.source_event_id,
            "signature_status": self.signature_status,
            "public_key_fingerprint": self.public_key_fingerprint,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioEvidenceTimelineIntegrityCard:
    """Integrity/export readiness summary for the Evidence Timeline."""

    title: str
    severity: str
    item_count: int
    stage_count: int
    registry_observation_count: int
    export_ready: bool
    selected_driver_id: str | None
    bundle_hash: str | None
    missing_stages: tuple[StudioDriverLifecycleStage, ...] = ()
    authority: str = "observe_only"

    def as_card(self) -> Mapping[str, Any]:
        return {
            "title": self.title,
            "severity": self.severity,
            "item_count": self.item_count,
            "stage_count": self.stage_count,
            "registry_observation_count": self.registry_observation_count,
            "export_ready": self.export_ready,
            "selected_driver_id": self.selected_driver_id,
            "bundle_hash": self.bundle_hash,
            "missing_stages": tuple(stage.value for stage in self.missing_stages),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioEvidenceTimelineState:
    """Complete v3.1.16 Evidence Timeline view-model."""

    ok: bool
    status: str
    reason: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None
    generation: int
    cursor: int
    items: tuple[StudioEvidenceTimelineItem, ...]
    registry_observations: tuple[StudioRegistryObservationItem, ...]
    integrity_card: StudioEvidenceTimelineIntegrityCard
    cards: tuple[StudioPanelCard, ...]
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    @property
    def latest_stage(self) -> StudioDriverLifecycleStage | None:
        if not self.items:
            return None
        return max((item.stage for item in self.items), key=lambda stage: _STAGE_ORDER.get(stage, -1))

    @property
    def export_ready(self) -> bool:
        return self.integrity_card.export_ready

    @property
    def registry_observation_count(self) -> int:
        return len(self.registry_observations)

    def items_for_stage(self, stage: StudioDriverLifecycleStage | str) -> tuple[StudioEvidenceTimelineItem, ...]:
        wanted = stage if isinstance(stage, StudioDriverLifecycleStage) else StudioDriverLifecycleStage(str(stage))
        return tuple(item for item in self.items if item.stage is wanted)

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
            "item_count": len(self.items),
            "latest_stage": None if self.latest_stage is None else self.latest_stage.value,
            "registry_observation_count": len(self.registry_observations),
            "export_ready": self.export_ready,
            "items": tuple(item.as_row() for item in self.items),
            "registry_observations": tuple(item.as_row() for item in self.registry_observations),
            "integrity_card": self.integrity_card.as_card(),
            "cards": tuple(_card_map(card) for card in self.cards),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioEvidenceTimeline:
    """Chronological trust-history layer for Studio & Evidence.

    The timeline consumes hydrated Studio panels and live events.  It does not
    call Registry, Runtime Manager, Foundry, VM execution, storage, or signing
    authority.  Its output is GUI/export/audit preparation only.
    """

    def __init__(self, *, runtime: StudioLivePanelRuntime | None = None) -> None:
        self.runtime = runtime or StudioLivePanelRuntime()

    def capability_matrix(self) -> Mapping[str, bool]:
        matrix = dict(self.runtime.capability_matrix())
        matrix.update(
            {
                "evidence_timeline": True,
                "render_chronological_trust_history": True,
                "render_driver_lifecycle_stages": True,
                "render_registry_observations": True,
                "render_timeline_integrity_card": True,
                "prepare_export_audit_context": True,
                "timeline_to_review_workflow_context": True,
                "evidence_timeline_mutates_backend": False,
                "evidence_timeline_is_authority": False,
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

    def current_state(self, runtime_state: StudioPanelRuntimeState | None = None) -> StudioEvidenceTimelineState:
        live_state = runtime_state.live_state if runtime_state is not None else self.runtime.event_bridge.current_state()
        return _timeline_state(
            live_state.hydrated,
            generation=live_state.generation,
            cursor=live_state.cursor,
            capability_matrix=self.capability_matrix(),
            live_events=live_state.events,
        )

    def signal_payload(self) -> Mapping[str, Any]:
        return self.current_state().signal_payload()


def studio_evidence_timeline_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying v3.1.16 timeline boundaries."""

    return StudioEvidenceTimeline().capability_matrix()


def _timeline_state(
    hydrated: StudioHydratedCockpitState,
    *,
    generation: int,
    cursor: int,
    capability_matrix: Mapping[str, bool],
    live_events: Sequence[Any] = (),
) -> StudioEvidenceTimelineState:
    panel = hydrated.panel(StudioPanelKind.EVIDENCE_TIMELINE)
    items = tuple(sorted((_timeline_item(row) for row in panel.rows), key=_item_sort_key))
    items = _merge_live_review_items(items, live_events=live_events, selected_driver_id=hydrated.selected_driver_id)
    registry_observations = tuple(_registry_observation(item) for item in items if item.registry_related)
    missing = _missing_export_spine_stages(items)
    export_ready = bool(hydrated.bundle_hash and items and not missing)
    severity = "success" if export_ready else "warning" if items else "muted"
    integrity = StudioEvidenceTimelineIntegrityCard(
        title="Evidence Timeline Integrity",
        severity=severity,
        item_count=len(items),
        stage_count=len({item.stage for item in items}),
        registry_observation_count=len(registry_observations),
        export_ready=export_ready,
        selected_driver_id=hydrated.selected_driver_id,
        bundle_hash=hydrated.bundle_hash,
        missing_stages=missing,
    )
    cards = tuple(panel.cards) + (
        StudioPanelCard(
            title=integrity.title,
            subtitle="Chronological audit spine for future export packets.",
            severity=integrity.severity,
            fields=integrity.as_card(),
            badges=("timeline", "audit-spine", "observe-only"),
        ),
    )
    reason = panel.summary if items else "no evidence timeline loaded"
    return StudioEvidenceTimelineState(
        ok=hydrated.ok and bool(items),
        status=panel.status,
        reason=reason,
        selected_driver_id=hydrated.selected_driver_id,
        bundle_id=hydrated.bundle_id,
        bundle_hash=hydrated.bundle_hash,
        console_hash=hydrated.console_hash,
        generation=generation,
        cursor=cursor,
        items=items,
        registry_observations=registry_observations,
        integrity_card=integrity,
        cards=cards,
        capability_matrix=capability_matrix,
    )


def _timeline_item(row: Mapping[str, Any]) -> StudioEvidenceTimelineItem:
    return StudioEvidenceTimelineItem(
        timestamp=str(row.get("timestamp") or "undated"),
        stage=_stage_value(row.get("stage")),
        status=str(row.get("status") or "observed"),
        severity=str(row.get("severity") or "info"),
        driver_id=_optional_text(row.get("driver_id")),
        label=str(row.get("label") or row.get("stage") or "Timeline Item"),
        detail=str(row.get("detail") or row.get("reason") or ""),
        source_event_id=_optional_text(row.get("source_event_id") or row.get("event_id")),
        actor_id=str(row.get("actor_id") or "studio-evidence"),
        package_hash=_optional_text(row.get("package_hash")),
        regression_report_hash=_optional_text(row.get("regression_report_hash")),
        evidence_hash=_optional_text(row.get("evidence_hash") or row.get("runtime_evidence_hash")),
        review_hash=_optional_text(row.get("review_hash")),
        registry_state=_optional_text(row.get("registry_state") or row.get("resulting_status")),
        export_hash=_optional_text(row.get("export_hash") or row.get("evidence_bundle_hash")),
        authority=str(row.get("authority") or "observe_only"),
    )


def _merge_live_review_items(
    items: Sequence[StudioEvidenceTimelineItem],
    *,
    live_events: Sequence[Any],
    selected_driver_id: str | None,
) -> tuple[StudioEvidenceTimelineItem, ...]:
    merged = list(items)
    seen = {item.source_event_id for item in merged if item.source_event_id}
    for event in live_events:
        kind_value = str(getattr(getattr(event, "kind", None), "value", getattr(event, "kind", "live_event")))
        if kind_value != "review_action_submitted":
            continue
        event_id = str(getattr(event, "event_id", ""))
        if event_id in seen:
            continue
        payload = getattr(event, "payload", {}) or {}
        action = payload.get("action") if isinstance(payload, Mapping) else None
        merged.append(
            StudioEvidenceTimelineItem(
                timestamp=str(getattr(event, "timestamp", "undated")),
                stage=StudioDriverLifecycleStage.REVIEW_SUBMITTED,
                status="submitted",
                severity=str(getattr(event, "severity", "info")),
                driver_id=_optional_text(getattr(event, "driver_id", None)) or selected_driver_id,
                label="Review Intent Submitted",
                detail=f"Studio submitted {action or 'review'} intent through the action layer",
                source_event_id=event_id,
                actor_id=str(getattr(event, "source", "studio_action_layer")),
                authority="review_intent_only",
            )
        )
    return tuple(sorted(merged, key=_item_sort_key))


def _registry_observation(item: StudioEvidenceTimelineItem) -> StudioRegistryObservationItem:
    return StudioRegistryObservationItem(
        timestamp=item.timestamp,
        driver_id=item.driver_id,
        registry_state=item.registry_state or item.stage.value,
        stage=item.stage,
        source_event_id=item.source_event_id,
        signature_status="observed" if item.stage in {StudioDriverLifecycleStage.SIGNED, StudioDriverLifecycleStage.ACTIVE, StudioDriverLifecycleStage.OBSERVED_ACTIVE} else None,
    )


def _missing_export_spine_stages(items: Sequence[StudioEvidenceTimelineItem]) -> tuple[StudioDriverLifecycleStage, ...]:
    present = {item.stage for item in items}
    required = (
        StudioDriverLifecycleStage.PROPOSAL,
        StudioDriverLifecycleStage.VALIDATED,
        StudioDriverLifecycleStage.COMPILED,
        StudioDriverLifecycleStage.EVIDENCE_READY,
        StudioDriverLifecycleStage.REVIEW_SUBMITTED,
        StudioDriverLifecycleStage.REVIEWED,
        StudioDriverLifecycleStage.EXPORTED,
    )
    return tuple(stage for stage in required if stage not in present)


def _stage_value(value: Any) -> StudioDriverLifecycleStage:
    if isinstance(value, StudioDriverLifecycleStage):
        return value
    raw = str(value or "evidence-ready").replace("_", "-")
    aliases = {
        "fixture-tested": StudioDriverLifecycleStage.FIXTURE_TESTED,
        "fixture_tested": StudioDriverLifecycleStage.FIXTURE_TESTED,
        "evidence-ready": StudioDriverLifecycleStage.EVIDENCE_READY,
        "review-submitted": StudioDriverLifecycleStage.REVIEW_SUBMITTED,
        "registry-approval-requested": StudioDriverLifecycleStage.REGISTRY_APPROVAL_REQUESTED,
        "observed-active": StudioDriverLifecycleStage.OBSERVED_ACTIVE,
    }
    if raw in aliases:
        return aliases[raw]
    return StudioDriverLifecycleStage(raw)


def _item_sort_key(item: StudioEvidenceTimelineItem) -> tuple[str, int, str, str]:
    return (item.timestamp, _STAGE_ORDER.get(item.stage, 99), item.source_event_id or "", item.label)


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

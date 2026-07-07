"""Export / Audit Console models for the optional Driver Studio PyQt5 cockpit.

v3.1.20 adds a selected-driver administrative surface that prepares evidence
history for reviewable, hash-backed export packet previews.  The console joins
Evidence Timeline, Risk Intelligence, Review Workflow, Registry observation,
optional performance evidence, and existing bundle metadata into deterministic
manifest/checklist view models.

It is deliberately non-authoritative: it never approves, rejects, quarantines,
signs, activates, executes trusted drivers, mutates Registry state, writes
storage, stores private keys, or bypasses Runtime Manager / Foundry / Review
Board policy.  It packages and explains trust evidence only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from staqtapp_tds.version import __version__
from .evidence_timeline import StudioEvidenceTimelineState
from .hydration import StudioPanelCard
from .review_workflow import StudioReviewWorkflowConsoleState
from .risk_intelligence import StudioRiskIntelligenceState
from .runtime import StudioLivePanelRuntime, StudioPanelRuntimeState


class StudioExportAuditStatus(str, Enum):
    """Top-level Export / Audit Console readiness status."""

    EMPTY = "empty"
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class StudioExportAuditIntegrityItem:
    """One manifest/checklist integrity item for a future export packet."""

    item_id: str
    label: str
    status: str
    severity: str
    detail: str
    hash_value: str | None = None
    source: str = "studio_export_audit"
    required: bool = True
    authority: str = "prepare_only"

    @property
    def ready(self) -> bool:
        return self.status in {"ready", "verified", "attached", "observed", "optional"}

    def as_row(self) -> Mapping[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "status": self.status,
            "severity": self.severity,
            "detail": self.detail,
            "hash_value": self.hash_value,
            "source": self.source,
            "required": self.required,
            "ready": self.ready,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioExportAuditChecklist:
    """Stable checklist rendered beside the packet preview."""

    checklist_id: str
    title: str
    items: tuple[StudioExportAuditIntegrityItem, ...]
    authority: str = "prepare_only"

    @property
    def required_count(self) -> int:
        return sum(1 for item in self.items if item.required)

    @property
    def ready_count(self) -> int:
        return sum(1 for item in self.items if item.required and item.ready)

    @property
    def missing_items(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.items if item.required and not item.ready)

    @property
    def ready(self) -> bool:
        return self.ready_count == self.required_count and self.required_count > 0

    def as_card(self) -> Mapping[str, Any]:
        return {
            "checklist_id": self.checklist_id,
            "title": self.title,
            "required_count": self.required_count,
            "ready_count": self.ready_count,
            "missing_items": self.missing_items,
            "ready": self.ready,
            "authority": self.authority,
            "items": tuple(item.as_row() for item in self.items),
        }


@dataclass(frozen=True, slots=True)
class StudioExportAuditReadinessCard:
    """Compact readiness summary for the selected export/audit packet."""

    title: str
    severity: str
    export_ready: bool
    selected_driver_id: str | None
    bundle_hash: str | None
    manifest_hash: str | None
    packet_hash: str | None
    missing_items: tuple[str, ...]
    warning_count: int
    authority: str = "prepare_only"

    def as_card(self) -> Mapping[str, Any]:
        return {
            "title": self.title,
            "severity": self.severity,
            "export_ready": self.export_ready,
            "selected_driver_id": self.selected_driver_id,
            "bundle_hash": self.bundle_hash,
            "manifest_hash": self.manifest_hash,
            "packet_hash": self.packet_hash,
            "missing_items": self.missing_items,
            "warning_count": self.warning_count,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioExportAuditManifest:
    """Deterministic manifest preview for a future export/audit packet."""

    schema: str
    tds_version: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None
    proposal_source_hash: str | None
    package_hash: str | None
    regression_report_hash: str | None
    evidence_bundle_hash: str | None
    review_hash: str | None
    registry_observation_count: int
    audit_event_count: int
    timeline_event_count: int
    risk_factor_count: int
    review_history_count: int
    performance_evidence_hash: str | None = None
    manifest_hash: str | None = None
    authority: str = "prepare_only"

    def with_manifest_hash(self) -> "StudioExportAuditManifest":
        return replace(self, manifest_hash=_hash_payload(self.as_manifest(include_hash=False)))

    def as_manifest(self, *, include_hash: bool = True) -> Mapping[str, Any]:
        payload = {
            "schema": self.schema,
            "tds_version": self.tds_version,
            "selected_driver_id": self.selected_driver_id,
            "bundle_id": self.bundle_id,
            "bundle_hash": self.bundle_hash,
            "console_hash": self.console_hash,
            "proposal_source_hash": self.proposal_source_hash,
            "package_hash": self.package_hash,
            "regression_report_hash": self.regression_report_hash,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "review_hash": self.review_hash,
            "registry_observation_count": self.registry_observation_count,
            "audit_event_count": self.audit_event_count,
            "timeline_event_count": self.timeline_event_count,
            "risk_factor_count": self.risk_factor_count,
            "review_history_count": self.review_history_count,
            "performance_evidence_hash": self.performance_evidence_hash,
            "authority": self.authority,
        }
        if include_hash:
            payload["manifest_hash"] = self.manifest_hash
        return payload


@dataclass(frozen=True, slots=True)
class StudioExportAuditPacketPreview:
    """Reviewable packet preview assembled from visible Studio evidence."""

    ok: bool
    status: StudioExportAuditStatus
    reason: str
    manifest: StudioExportAuditManifest
    checklist: StudioExportAuditChecklist
    readiness_card: StudioExportAuditReadinessCard
    timeline_rows: tuple[Mapping[str, Any], ...]
    risk_notes: tuple[Mapping[str, Any], ...]
    review_history_rows: tuple[Mapping[str, Any], ...]
    registry_rows: tuple[Mapping[str, Any], ...]
    performance_attachment: Mapping[str, Any] | None = None
    packet_hash: str | None = None
    authority: str = "prepare_only"

    def as_payload(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "reason": self.reason,
            "manifest": self.manifest.as_manifest(),
            "checklist": self.checklist.as_card(),
            "readiness_card": self.readiness_card.as_card(),
            "timeline_rows": self.timeline_rows,
            "risk_notes": self.risk_notes,
            "review_history_rows": self.review_history_rows,
            "registry_rows": self.registry_rows,
            "performance_attachment": self.performance_attachment,
            "packet_hash": self.packet_hash,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioExportAuditConsoleState:
    """Complete v3.1.20 Export / Audit Console view-model."""

    ok: bool
    status: StudioExportAuditStatus
    reason: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    console_hash: str | None
    generation: int
    cursor: int
    preview: StudioExportAuditPacketPreview
    manifest: StudioExportAuditManifest
    checklist: StudioExportAuditChecklist
    readiness_card: StudioExportAuditReadinessCard
    integrity_items: tuple[StudioExportAuditIntegrityItem, ...]
    cards: tuple[StudioPanelCard, ...]
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

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
            "preview": self.preview.as_payload(),
            "manifest": self.manifest.as_manifest(),
            "checklist": self.checklist.as_card(),
            "readiness_card": self.readiness_card.as_card(),
            "integrity_items": tuple(item.as_row() for item in self.integrity_items),
            "cards": tuple(_card_map(card) for card in self.cards),
            "warnings": self.warnings,
            "metrics": dict(self.metrics),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioExportAuditConsole:
    """Prepare selected-driver export/audit packet previews.

    The console only reads the current live Studio state and joined evidence
    models.  It returns deterministic manifests, readiness cards, checklists,
    and hashes for review/export tooling to inspect later.
    """

    def __init__(self, *, runtime: StudioLivePanelRuntime | None = None) -> None:
        self.runtime = runtime or StudioLivePanelRuntime()

    def capability_matrix(self) -> Mapping[str, bool]:
        matrix = dict(self.runtime.capability_matrix())
        matrix.update(
            {
                "export_audit_console": True,
                "prepare_export_audit_packet_preview": True,
                "prepare_export_audit_manifest": True,
                "prepare_export_audit_checklist": True,
                "prepare_export_manifest_hash": True,
                "map_evidence_timeline_to_export": True,
                "map_risk_intelligence_to_export_notes": True,
                "map_review_workflow_to_export_history": True,
                "map_registry_observations_to_export": True,
                "attach_performance_evidence_when_explicit": True,
                "export_audit_console_is_authority": False,
                "export_audit_console_mutates_backend": False,
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

    def current_state(
        self,
        runtime_state: StudioPanelRuntimeState | None = None,
        *,
        performance_report: Any | Mapping[str, Any] | None = None,
    ) -> StudioExportAuditConsoleState:
        runtime_state = runtime_state or self.runtime.current_state(include_packets=False)
        timeline = self.runtime.evidence_timeline().current_state(runtime_state)
        risk = self.runtime.risk_intelligence_cards().current_state(runtime_state)
        review = self.runtime.review_workflow_console().current_state(runtime_state)
        return _export_audit_state(
            runtime_state,
            timeline=timeline,
            risk=risk,
            review=review,
            performance_report=performance_report,
            capability_matrix=self.capability_matrix(),
        )

    def packet_preview(
        self,
        runtime_state: StudioPanelRuntimeState | None = None,
        *,
        performance_report: Any | Mapping[str, Any] | None = None,
    ) -> StudioExportAuditPacketPreview:
        return self.current_state(runtime_state, performance_report=performance_report).preview

    def signal_payload(self) -> Mapping[str, Any]:
        return self.current_state().signal_payload()



def studio_export_audit_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying v3.1.20 export/audit boundaries."""

    return StudioExportAuditConsole().capability_matrix()



def _export_audit_state(
    runtime_state: StudioPanelRuntimeState,
    *,
    timeline: StudioEvidenceTimelineState,
    risk: StudioRiskIntelligenceState,
    review: StudioReviewWorkflowConsoleState,
    performance_report: Any | Mapping[str, Any] | None,
    capability_matrix: Mapping[str, bool],
) -> StudioExportAuditConsoleState:
    selected = timeline.selected_driver_id or risk.selected_driver_id or review.selected_driver_id
    selected_item = review.selected_item
    selected_card = risk.selected_card
    timeline_rows = tuple(item.as_row() for item in timeline.items if selected is None or item.driver_id in {None, selected})
    registry_rows = tuple(item.as_row() for item in timeline.registry_observations if selected is None or item.driver_id in {None, selected})
    review_history_rows = tuple(entry.as_row() for entry in review.history if selected is None or entry.driver_id in {None, selected})
    risk_notes = tuple(factor.as_row() for factor in selected_card.factors) if selected_card is not None else ()
    package_hash = _first_text(
        getattr(selected_item, "package_hash", None),
        *(row.get("package_hash") for row in timeline_rows),
    )
    regression_hash = _first_text(
        getattr(selected_item, "regression_report_hash", None),
        *(row.get("regression_report_hash") for row in timeline_rows),
    )
    review_hash = _first_text(
        getattr(selected_item, "review_hash", None),
        *(row.get("review_hash") for row in timeline_rows),
    )
    evidence_hash = _first_text(timeline.bundle_hash, *(row.get("evidence_hash") or row.get("export_hash") for row in timeline_rows))
    performance_attachment = _performance_payload(performance_report)
    performance_hash = _first_text(
        _mapping_get(performance_attachment, "performance_hash"),
        _mapping_get(performance_attachment, "snapshot_hash"),
    )
    manifest = StudioExportAuditManifest(
        schema="tds.driver.studio.export_audit.preview.v1",
        tds_version=__version__,
        selected_driver_id=selected,
        bundle_id=timeline.bundle_id,
        bundle_hash=timeline.bundle_hash,
        console_hash=timeline.console_hash,
        proposal_source_hash=_proposal_source_hash(runtime_state),
        package_hash=package_hash,
        regression_report_hash=regression_hash,
        evidence_bundle_hash=evidence_hash,
        review_hash=review_hash,
        registry_observation_count=len(registry_rows),
        audit_event_count=len(review_history_rows),
        timeline_event_count=len(timeline_rows),
        risk_factor_count=len(risk_notes),
        review_history_count=len(review_history_rows),
        performance_evidence_hash=performance_hash,
    ).with_manifest_hash()
    items = _integrity_items(
        selected_driver_id=selected,
        manifest=manifest,
        timeline=timeline,
        timeline_rows=timeline_rows,
        registry_rows=registry_rows,
        review_history_rows=review_history_rows,
        risk_notes=risk_notes,
        performance_hash=performance_hash,
    )
    checklist = StudioExportAuditChecklist(
        checklist_id="export_audit.selected_driver.v1",
        title="Selected Driver Export Checklist",
        items=items,
    )
    status = _status_from_checklist(timeline, checklist)
    warnings = _warnings(checklist, timeline=timeline, risk=risk, review=review)
    reason = _reason(status, checklist, timeline=timeline)
    packet_hash = _hash_payload(
        {
            "manifest": manifest.as_manifest(),
            "checklist": checklist.as_card(),
            "timeline_rows": timeline_rows,
            "risk_notes": risk_notes,
            "review_history_rows": review_history_rows,
            "registry_rows": registry_rows,
            "performance_attachment": performance_attachment,
        }
    )
    readiness = StudioExportAuditReadinessCard(
        title="Export / Audit Readiness",
        severity="success" if status is StudioExportAuditStatus.READY else "warning" if status is StudioExportAuditStatus.PARTIAL else "danger" if status is StudioExportAuditStatus.BLOCKED else "muted",
        export_ready=status is StudioExportAuditStatus.READY,
        selected_driver_id=selected,
        bundle_hash=timeline.bundle_hash,
        manifest_hash=manifest.manifest_hash,
        packet_hash=packet_hash,
        missing_items=checklist.missing_items,
        warning_count=len(warnings),
    )
    preview = StudioExportAuditPacketPreview(
        ok=status is StudioExportAuditStatus.READY,
        status=status,
        reason=reason,
        manifest=manifest,
        checklist=checklist,
        readiness_card=readiness,
        timeline_rows=timeline_rows,
        risk_notes=risk_notes,
        review_history_rows=review_history_rows,
        registry_rows=registry_rows,
        performance_attachment=performance_attachment,
        packet_hash=packet_hash,
    )
    cards = (
        StudioPanelCard(
            title=readiness.title,
            subtitle="Hash-backed packet preview; packaging only, no trust authority.",
            severity=readiness.severity,
            fields=readiness.as_card(),
            badges=("export-audit", "hash-backed", "prepare-only"),
        ),
        StudioPanelCard(
            title="Manifest Hash",
            subtitle=manifest.manifest_hash or "manifest unavailable",
            severity="success" if manifest.manifest_hash else "muted",
            fields=manifest.as_manifest(),
            badges=("manifest", "deterministic"),
        ),
    )
    metrics = {
        "timeline_event_count": len(timeline_rows),
        "registry_observation_count": len(registry_rows),
        "risk_factor_count": len(risk_notes),
        "review_history_count": len(review_history_rows),
        "required_ready_count": checklist.ready_count,
        "required_count": checklist.required_count,
        "has_performance_attachment": performance_attachment is not None,
        "authority": "prepare_only",
    }
    return StudioExportAuditConsoleState(
        ok=preview.ok,
        status=status,
        reason=reason,
        selected_driver_id=selected,
        bundle_id=timeline.bundle_id,
        bundle_hash=timeline.bundle_hash,
        console_hash=timeline.console_hash,
        generation=runtime_state.generation,
        cursor=runtime_state.cursor,
        preview=preview,
        manifest=manifest,
        checklist=checklist,
        readiness_card=readiness,
        integrity_items=items,
        cards=cards,
        warnings=warnings,
        metrics=metrics,
        capability_matrix=capability_matrix,
    )



def _integrity_items(
    *,
    selected_driver_id: str | None,
    manifest: StudioExportAuditManifest,
    timeline: StudioEvidenceTimelineState,
    timeline_rows: Sequence[Mapping[str, Any]],
    registry_rows: Sequence[Mapping[str, Any]],
    review_history_rows: Sequence[Mapping[str, Any]],
    risk_notes: Sequence[Mapping[str, Any]],
    performance_hash: str | None,
) -> tuple[StudioExportAuditIntegrityItem, ...]:
    return (
        _item("driver_identity", "Driver identity", selected_driver_id, "selected driver is bound to the packet preview"),
        _item("evidence_bundle_hash", "Evidence bundle hash", manifest.bundle_hash, "bundle hash is available for packet binding"),
        _item("compiled_bytecode_hash", "Compiled bytecode hash", manifest.package_hash, "compiled bytecode/package hash is available"),
        _item("fixture_replay_summary", "Fixture replay summary", manifest.regression_report_hash, "regression/fixture report hash is available"),
        _item("review_action_history", "Review action history", manifest.review_hash or review_history_rows, "review hash or review intent history is available"),
        _item("evidence_timeline", "Evidence timeline mapping", timeline_rows if timeline.export_ready else None, "timeline contains the export audit spine"),
        _item("risk_intelligence_notes", "Risk intelligence notes", risk_notes, "risk factors are available for reviewer context"),
        StudioExportAuditIntegrityItem(
            item_id="registry_observation",
            label="Registry observation rows",
            status="observed" if registry_rows else "optional",
            severity="success" if registry_rows else "info",
            detail="registry observation rows are mapped without mutation" if registry_rows else "no registry observation rows are present yet; approval/signing/activation may still be pending",
            required=False,
        ),
        _item("export_manifest_hash", "Export manifest hash", manifest.manifest_hash, "deterministic manifest hash prepared"),
        StudioExportAuditIntegrityItem(
            item_id="performance_evidence",
            label="Performance evidence attachment",
            status="attached" if performance_hash else "optional",
            severity="success" if performance_hash else "info",
            detail="explicit performance evidence hash attached" if performance_hash else "no performance evidence attached; this is optional for v3.1.20",
            hash_value=performance_hash,
            required=False,
        ),
    )



def _item(item_id: str, label: str, value: Any, detail: str) -> StudioExportAuditIntegrityItem:
    ready = bool(value)
    return StudioExportAuditIntegrityItem(
        item_id=item_id,
        label=label,
        status="ready" if ready else "missing",
        severity="success" if ready else "warning",
        detail=detail if ready else f"missing {label.lower()}",
        hash_value=value if isinstance(value, str) and value.startswith("sha256:") else None,
    )



def _status_from_checklist(timeline: StudioEvidenceTimelineState, checklist: StudioExportAuditChecklist) -> StudioExportAuditStatus:
    if not timeline.bundle_hash and not timeline.items:
        return StudioExportAuditStatus.EMPTY
    if not timeline.ok:
        return StudioExportAuditStatus.BLOCKED if not timeline.items else StudioExportAuditStatus.PARTIAL
    return StudioExportAuditStatus.READY if checklist.ready else StudioExportAuditStatus.PARTIAL



def _warnings(
    checklist: StudioExportAuditChecklist,
    *,
    timeline: StudioEvidenceTimelineState,
    risk: StudioRiskIntelligenceState,
    review: StudioReviewWorkflowConsoleState,
) -> tuple[str, ...]:
    warnings: list[str] = []
    warnings.extend(f"missing export item: {item}" for item in checklist.missing_items)
    if risk.selected_card is not None and risk.selected_card.attention_required:
        warnings.append("selected driver has risk intelligence attention markers")
    if review.selected_item is not None and review.selected_item.needs_attention:
        warnings.append("selected driver review workflow still needs attention")
    if timeline.integrity_card.missing_stages:
        warnings.append("timeline is missing lifecycle stages: " + ", ".join(stage.value for stage in timeline.integrity_card.missing_stages))
    return tuple(warnings)



def _reason(status: StudioExportAuditStatus, checklist: StudioExportAuditChecklist, *, timeline: StudioEvidenceTimelineState) -> str:
    if status is StudioExportAuditStatus.READY:
        return "export/audit packet preview is hash-backed and ready for external export tooling"
    if status is StudioExportAuditStatus.EMPTY:
        return "no selected driver evidence is loaded for export/audit preview"
    if status is StudioExportAuditStatus.BLOCKED:
        return "timeline/evidence state is blocked; export/audit preview cannot be ready"
    return "export/audit packet preview is partial; missing: " + ", ".join(checklist.missing_items or ("unknown",))



def _proposal_source_hash(runtime_state: StudioPanelRuntimeState) -> str | None:
    for event in reversed(runtime_state.live_state.events):
        payload = getattr(event, "payload", {}) or {}
        if isinstance(payload, Mapping) and payload.get("source_hash"):
            return str(payload.get("source_hash"))
    return None



def _performance_payload(report: Any | Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if report is None:
        return None
    if isinstance(report, Mapping):
        return dict(report)
    if hasattr(report, "signal_payload"):
        payload = report.signal_payload()
        if isinstance(payload, Mapping):
            return dict(payload)
    data: dict[str, Any] = {}
    for key in ("ok", "status", "reason", "driver_id", "package_hash", "snapshot_hash", "performance_hash"):
        if hasattr(report, key):
            value = getattr(report, key)
            data[key] = getattr(value, "value", value)
    return data or None



def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return None



def _mapping_get(mapping: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    return mapping.get(key)



def _hash_payload(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()



def _canonical_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)



def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "as_row"):
        return _jsonable(value.as_row())
    if hasattr(value, "as_card"):
        return _jsonable(value.as_card())
    return value



def _card_map(card: StudioPanelCard) -> Mapping[str, Any]:
    return {
        "title": card.title,
        "subtitle": card.subtitle,
        "severity": card.severity,
        "fields": dict(card.fields),
        "badges": card.badges,
    }

"""Export Integrity Workflow models for the optional Driver Studio PyQt5 cockpit.

v3.1.20 strengthens the v3.1.20 Export / Audit Console with a review-safe
integrity workflow.  It recomputes manifest and packet hashes, compares them
against optional expected hashes/manifests, turns packet checklist items into
progressive checkpoints, and emits a deterministic workflow hash for external
export tooling to inspect.

The workflow is deliberately non-authoritative: it does not approve, reject,
quarantine, sign, activate, execute trusted drivers, mutate Registry state,
write storage, store private keys, or bypass Runtime Manager / Foundry / Review
Board policy.  It verifies and explains export readiness only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .export_audit import StudioExportAuditConsole, StudioExportAuditPacketPreview
from .runtime import StudioLivePanelRuntime, StudioPanelRuntimeState


class StudioExportIntegrityWorkflowStatus(str, Enum):
    """Top-level v3.1.20 export-integrity workflow status."""

    EMPTY = "empty"
    VERIFIED = "verified"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    BLOCKED = "blocked"


class StudioExportIntegrityCheckpointStatus(str, Enum):
    """Status for one review-safe export-integrity checkpoint."""

    VERIFIED = "verified"
    MISSING = "missing"
    OPTIONAL = "optional"
    MISMATCH = "mismatch"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class StudioExportIntegrityCheckpoint:
    """One progressive checkpoint in the export-integrity workflow."""

    checkpoint_id: str
    label: str
    status: StudioExportIntegrityCheckpointStatus
    severity: str
    detail: str
    required: bool = True
    source_item_id: str | None = None
    expected_hash: str | None = None
    observed_hash: str | None = None
    authority: str = "verify_only"

    @property
    def ok(self) -> bool:
        if self.required:
            return self.status is StudioExportIntegrityCheckpointStatus.VERIFIED
        return self.status in {
            StudioExportIntegrityCheckpointStatus.VERIFIED,
            StudioExportIntegrityCheckpointStatus.OPTIONAL,
        }

    def as_row(self) -> Mapping[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "label": self.label,
            "status": self.status.value,
            "severity": self.severity,
            "detail": self.detail,
            "required": self.required,
            "ok": self.ok,
            "source_item_id": self.source_item_id,
            "expected_hash": self.expected_hash,
            "observed_hash": self.observed_hash,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioExportIntegrityManifestComparison:
    """Comparison between the current manifest and an expected manifest/hash."""

    ok: bool
    status: StudioExportIntegrityWorkflowStatus
    reason: str
    expected_manifest_hash: str | None
    observed_manifest_hash: str | None
    expected_packet_hash: str | None
    observed_packet_hash: str | None
    changed_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    authority: str = "compare_only"

    def as_payload(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "reason": self.reason,
            "expected_manifest_hash": self.expected_manifest_hash,
            "observed_manifest_hash": self.observed_manifest_hash,
            "expected_packet_hash": self.expected_packet_hash,
            "observed_packet_hash": self.observed_packet_hash,
            "changed_fields": self.changed_fields,
            "missing_fields": self.missing_fields,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioExportIntegrityReviewGate:
    """Review-safe readiness gate for handoff to export/review tooling."""

    ready_for_export_review: bool
    status: StudioExportIntegrityWorkflowStatus
    severity: str
    reason: str
    required_checkpoint_count: int
    verified_checkpoint_count: int
    blocking_checkpoint_ids: tuple[str, ...]
    authority: str = "intent_only"

    def as_card(self) -> Mapping[str, Any]:
        return {
            "ready_for_export_review": self.ready_for_export_review,
            "status": self.status.value,
            "severity": self.severity,
            "reason": self.reason,
            "required_checkpoint_count": self.required_checkpoint_count,
            "verified_checkpoint_count": self.verified_checkpoint_count,
            "blocking_checkpoint_ids": self.blocking_checkpoint_ids,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioExportIntegrityWorkflowState:
    """Complete v3.1.20 Export Integrity Workflow state."""

    ok: bool
    status: StudioExportIntegrityWorkflowStatus
    reason: str
    selected_driver_id: str | None
    bundle_id: str | None
    bundle_hash: str | None
    manifest_hash: str | None
    packet_hash: str | None
    workflow_hash: str | None
    generation: int
    cursor: int
    checkpoints: tuple[StudioExportIntegrityCheckpoint, ...]
    comparison: StudioExportIntegrityManifestComparison
    review_gate: StudioExportIntegrityReviewGate
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    @property
    def blocking_checkpoint_ids(self) -> tuple[str, ...]:
        return tuple(checkpoint.checkpoint_id for checkpoint in self.checkpoints if checkpoint.required and not checkpoint.ok)

    def signal_payload(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "reason": self.reason,
            "selected_driver_id": self.selected_driver_id,
            "bundle_id": self.bundle_id,
            "bundle_hash": self.bundle_hash,
            "manifest_hash": self.manifest_hash,
            "packet_hash": self.packet_hash,
            "workflow_hash": self.workflow_hash,
            "generation": self.generation,
            "cursor": self.cursor,
            "checkpoints": tuple(checkpoint.as_row() for checkpoint in self.checkpoints),
            "comparison": self.comparison.as_payload(),
            "review_gate": self.review_gate.as_card(),
            "warnings": self.warnings,
            "metrics": dict(self.metrics),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioExportIntegrityWorkflow:
    """Verify export/audit packet previews for review-safe handoff."""

    def __init__(self, *, runtime: StudioLivePanelRuntime | None = None) -> None:
        self.runtime = runtime or StudioLivePanelRuntime()
        self.export_audit_console = StudioExportAuditConsole(runtime=self.runtime)

    def capability_matrix(self) -> Mapping[str, bool]:
        matrix = dict(self.export_audit_console.capability_matrix())
        matrix.update(
            {
                "export_integrity_workflow": True,
                "recompute_export_manifest_hash": True,
                "recompute_export_packet_hash": True,
                "compare_export_manifest_hash": True,
                "compare_export_packet_hash": True,
                "compare_expected_manifest_fields": True,
                "progress_export_checkpoints": True,
                "prepare_review_safe_export_gate": True,
                "prepare_export_workflow_hash": True,
                "export_integrity_workflow_is_authority": False,
                "export_integrity_workflow_mutates_backend": False,
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
        expected_manifest: Mapping[str, Any] | None = None,
        expected_manifest_hash: str | None = None,
        expected_packet_hash: str | None = None,
    ) -> StudioExportIntegrityWorkflowState:
        runtime_state = runtime_state or self.runtime.current_state(include_packets=False)
        preview = self.export_audit_console.packet_preview(runtime_state, performance_report=performance_report)
        return _workflow_state(
            runtime_state,
            preview=preview,
            expected_manifest=expected_manifest,
            expected_manifest_hash=expected_manifest_hash,
            expected_packet_hash=expected_packet_hash,
            capability_matrix=self.capability_matrix(),
        )

    def signal_payload(self) -> Mapping[str, Any]:
        return self.current_state().signal_payload()



def studio_export_integrity_workflow_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for displaying v3.1.20 export-integrity boundaries."""

    return StudioExportIntegrityWorkflow().capability_matrix()



def _workflow_state(
    runtime_state: StudioPanelRuntimeState,
    *,
    preview: StudioExportAuditPacketPreview,
    expected_manifest: Mapping[str, Any] | None,
    expected_manifest_hash: str | None,
    expected_packet_hash: str | None,
    capability_matrix: Mapping[str, bool],
) -> StudioExportIntegrityWorkflowState:
    manifest_payload = preview.manifest.as_manifest(include_hash=False)
    observed_manifest_hash = _hash_payload(manifest_payload)
    observed_packet_hash = _packet_hash(preview)
    expected_manifest_for_hash = _manifest_without_hash(expected_manifest) if expected_manifest is not None else None
    manifest_hash_expected = expected_manifest_hash or (_hash_payload(expected_manifest_for_hash) if expected_manifest_for_hash is not None else None)
    comparison = _comparison(
        preview=preview,
        expected_manifest=expected_manifest,
        expected_manifest_hash=manifest_hash_expected,
        observed_manifest_hash=observed_manifest_hash,
        expected_packet_hash=expected_packet_hash,
        observed_packet_hash=observed_packet_hash,
    )
    checkpoints = _checkpoints(
        preview=preview,
        observed_manifest_hash=observed_manifest_hash,
        observed_packet_hash=observed_packet_hash,
        comparison=comparison,
    )
    required_count = sum(1 for checkpoint in checkpoints if checkpoint.required)
    verified_count = sum(1 for checkpoint in checkpoints if checkpoint.required and checkpoint.ok)
    blocking = tuple(checkpoint.checkpoint_id for checkpoint in checkpoints if checkpoint.required and not checkpoint.ok)
    status = _status(preview, comparison, checkpoints)
    reason = _reason(status, blocking=blocking, comparison=comparison, preview=preview)
    review_gate = StudioExportIntegrityReviewGate(
        ready_for_export_review=status is StudioExportIntegrityWorkflowStatus.VERIFIED,
        status=status,
        severity=_severity(status),
        reason=reason,
        required_checkpoint_count=required_count,
        verified_checkpoint_count=verified_count,
        blocking_checkpoint_ids=blocking,
    )
    warnings = _warnings(preview, comparison, checkpoints)
    workflow_hash = _hash_payload(
        {
            "schema": "tds.driver.studio.export_integrity.workflow.v1",
            "selected_driver_id": preview.manifest.selected_driver_id,
            "bundle_hash": preview.manifest.bundle_hash,
            "manifest_hash": observed_manifest_hash,
            "packet_hash": observed_packet_hash,
            "checkpoints": tuple(checkpoint.as_row() for checkpoint in checkpoints),
            "comparison": comparison.as_payload(),
            "review_gate": review_gate.as_card(),
            "authority": "verify_only",
        }
    )
    metrics = {
        "required_checkpoint_count": required_count,
        "verified_checkpoint_count": verified_count,
        "blocking_checkpoint_count": len(blocking),
        "manifest_hash_matches_preview": observed_manifest_hash == preview.manifest.manifest_hash,
        "packet_hash_matches_preview": observed_packet_hash == preview.packet_hash,
        "expected_manifest_compared": bool(expected_manifest or expected_manifest_hash),
        "expected_packet_compared": bool(expected_packet_hash),
        "ready_for_export_review": review_gate.ready_for_export_review,
        "authority": "verify_only",
    }
    return StudioExportIntegrityWorkflowState(
        ok=review_gate.ready_for_export_review,
        status=status,
        reason=reason,
        selected_driver_id=preview.manifest.selected_driver_id,
        bundle_id=preview.manifest.bundle_id,
        bundle_hash=preview.manifest.bundle_hash,
        manifest_hash=observed_manifest_hash,
        packet_hash=observed_packet_hash,
        workflow_hash=workflow_hash,
        generation=runtime_state.generation,
        cursor=runtime_state.cursor,
        checkpoints=checkpoints,
        comparison=comparison,
        review_gate=review_gate,
        warnings=warnings,
        metrics=metrics,
        capability_matrix=capability_matrix,
    )



def _checkpoints(
    *,
    preview: StudioExportAuditPacketPreview,
    observed_manifest_hash: str,
    observed_packet_hash: str,
    comparison: StudioExportIntegrityManifestComparison,
) -> tuple[StudioExportIntegrityCheckpoint, ...]:
    checkpoints: list[StudioExportIntegrityCheckpoint] = []
    for item in preview.checklist.items:
        if item.required:
            status = StudioExportIntegrityCheckpointStatus.VERIFIED if item.ready else StudioExportIntegrityCheckpointStatus.MISSING
        else:
            status = StudioExportIntegrityCheckpointStatus.VERIFIED if item.ready and item.status != "optional" else StudioExportIntegrityCheckpointStatus.OPTIONAL
        checkpoints.append(
            StudioExportIntegrityCheckpoint(
                checkpoint_id=f"checklist.{item.item_id}",
                label=item.label,
                status=status,
                severity="success" if status is StudioExportIntegrityCheckpointStatus.VERIFIED else "info" if status is StudioExportIntegrityCheckpointStatus.OPTIONAL else "warning",
                detail=item.detail,
                required=item.required,
                source_item_id=item.item_id,
                observed_hash=item.hash_value,
                authority="verify_only",
            )
        )
    checkpoints.append(
        _hash_checkpoint(
            checkpoint_id="hash.manifest_recompute",
            label="Manifest hash recompute",
            expected_hash=preview.manifest.manifest_hash,
            observed_hash=observed_manifest_hash,
            detail="recomputed manifest hash matches packet manifest hash",
        )
    )
    checkpoints.append(
        _hash_checkpoint(
            checkpoint_id="hash.packet_recompute",
            label="Packet hash recompute",
            expected_hash=preview.packet_hash,
            observed_hash=observed_packet_hash,
            detail="recomputed packet hash matches packet preview hash",
        )
    )
    if comparison.expected_manifest_hash:
        checkpoints.append(
            _hash_checkpoint(
                checkpoint_id="compare.expected_manifest_hash",
                label="Expected manifest hash comparison",
                expected_hash=comparison.expected_manifest_hash,
                observed_hash=observed_manifest_hash,
                detail="observed manifest hash matches expected manifest hash",
            )
        )
    if comparison.expected_packet_hash:
        checkpoints.append(
            _hash_checkpoint(
                checkpoint_id="compare.expected_packet_hash",
                label="Expected packet hash comparison",
                expected_hash=comparison.expected_packet_hash,
                observed_hash=observed_packet_hash,
                detail="observed packet hash matches expected packet hash",
            )
        )
    if comparison.changed_fields or comparison.missing_fields:
        checkpoints.append(
            StudioExportIntegrityCheckpoint(
                checkpoint_id="compare.expected_manifest_fields",
                label="Expected manifest field comparison",
                status=StudioExportIntegrityCheckpointStatus.MISMATCH,
                severity="danger",
                detail="expected manifest fields differ from observed manifest",
                required=True,
                authority="compare_only",
            )
        )
    elif comparison.expected_manifest_hash and comparison.ok:
        checkpoints.append(
            StudioExportIntegrityCheckpoint(
                checkpoint_id="compare.expected_manifest_fields",
                label="Expected manifest field comparison",
                status=StudioExportIntegrityCheckpointStatus.VERIFIED,
                severity="success",
                detail="expected manifest fields match observed manifest",
                required=False,
                authority="compare_only",
            )
        )
    checkpoints.append(
        StudioExportIntegrityCheckpoint(
            checkpoint_id="gate.review_safe_handoff",
            label="Review-safe export handoff",
            status=StudioExportIntegrityCheckpointStatus.VERIFIED if preview.ok and comparison.ok else StudioExportIntegrityCheckpointStatus.BLOCKED,
            severity="success" if preview.ok and comparison.ok else "danger",
            detail="packet is ready for external export/review tooling" if preview.ok and comparison.ok else "packet cannot be handed off until blocking items clear",
            required=True,
            authority="intent_only",
        )
    )
    return tuple(checkpoints)



def _hash_checkpoint(
    *,
    checkpoint_id: str,
    label: str,
    expected_hash: str | None,
    observed_hash: str | None,
    detail: str,
) -> StudioExportIntegrityCheckpoint:
    matched = bool(expected_hash and observed_hash and expected_hash == observed_hash)
    return StudioExportIntegrityCheckpoint(
        checkpoint_id=checkpoint_id,
        label=label,
        status=StudioExportIntegrityCheckpointStatus.VERIFIED if matched else StudioExportIntegrityCheckpointStatus.MISMATCH,
        severity="success" if matched else "danger",
        detail=detail if matched else "hash mismatch detected",
        expected_hash=expected_hash,
        observed_hash=observed_hash,
        required=True,
        authority="verify_only",
    )



def _comparison(
    *,
    preview: StudioExportAuditPacketPreview,
    expected_manifest: Mapping[str, Any] | None,
    expected_manifest_hash: str | None,
    observed_manifest_hash: str | None,
    expected_packet_hash: str | None,
    observed_packet_hash: str | None,
) -> StudioExportIntegrityManifestComparison:
    current_manifest = dict(preview.manifest.as_manifest(include_hash=False))
    expected_manifest_clean = _manifest_without_hash(expected_manifest) if expected_manifest is not None else None
    changed_fields: list[str] = []
    missing_fields: list[str] = []
    if expected_manifest_clean is not None:
        for key, expected_value in expected_manifest_clean.items():
            if key not in current_manifest:
                missing_fields.append(str(key))
            elif _jsonable(current_manifest.get(key)) != _jsonable(expected_value):
                changed_fields.append(str(key))
    manifest_ok = not expected_manifest_hash or expected_manifest_hash == observed_manifest_hash
    packet_ok = not expected_packet_hash or expected_packet_hash == observed_packet_hash
    fields_ok = not changed_fields and not missing_fields
    ok = bool(manifest_ok and packet_ok and fields_ok)
    if ok:
        reason = "manifest and packet integrity comparisons passed"
        status = StudioExportIntegrityWorkflowStatus.VERIFIED
    elif not fields_ok:
        reason = "expected manifest fields differ from observed manifest"
        status = StudioExportIntegrityWorkflowStatus.MISMATCH
    else:
        reason = "expected export hash comparison failed"
        status = StudioExportIntegrityWorkflowStatus.MISMATCH
    return StudioExportIntegrityManifestComparison(
        ok=ok,
        status=status,
        reason=reason,
        expected_manifest_hash=expected_manifest_hash,
        observed_manifest_hash=observed_manifest_hash,
        expected_packet_hash=expected_packet_hash,
        observed_packet_hash=observed_packet_hash,
        changed_fields=tuple(changed_fields),
        missing_fields=tuple(missing_fields),
    )



def _status(
    preview: StudioExportAuditPacketPreview,
    comparison: StudioExportIntegrityManifestComparison,
    checkpoints: Sequence[StudioExportIntegrityCheckpoint],
) -> StudioExportIntegrityWorkflowStatus:
    if preview.status.value == "empty":
        return StudioExportIntegrityWorkflowStatus.EMPTY
    if preview.status.value == "blocked":
        return StudioExportIntegrityWorkflowStatus.BLOCKED
    if not comparison.ok:
        return StudioExportIntegrityWorkflowStatus.MISMATCH
    if any(checkpoint.required and checkpoint.status is StudioExportIntegrityCheckpointStatus.MISMATCH for checkpoint in checkpoints):
        return StudioExportIntegrityWorkflowStatus.MISMATCH
    if any(checkpoint.required and checkpoint.status is StudioExportIntegrityCheckpointStatus.BLOCKED for checkpoint in checkpoints):
        return StudioExportIntegrityWorkflowStatus.BLOCKED
    if all(checkpoint.ok for checkpoint in checkpoints if checkpoint.required):
        return StudioExportIntegrityWorkflowStatus.VERIFIED
    return StudioExportIntegrityWorkflowStatus.PARTIAL



def _reason(
    status: StudioExportIntegrityWorkflowStatus,
    *,
    blocking: Sequence[str],
    comparison: StudioExportIntegrityManifestComparison,
    preview: StudioExportAuditPacketPreview,
) -> str:
    if status is StudioExportIntegrityWorkflowStatus.VERIFIED:
        return "export integrity workflow verified manifest, packet, checklist, and review-safe handoff"
    if status is StudioExportIntegrityWorkflowStatus.EMPTY:
        return "no selected driver export/audit packet is loaded"
    if status is StudioExportIntegrityWorkflowStatus.MISMATCH:
        return comparison.reason
    if status is StudioExportIntegrityWorkflowStatus.BLOCKED:
        return "export integrity workflow is blocked by evidence state or review-safe handoff"
    return "export integrity workflow is partial; blocking: " + ", ".join(blocking or preview.checklist.missing_items or ("unknown",))



def _warnings(
    preview: StudioExportAuditPacketPreview,
    comparison: StudioExportIntegrityManifestComparison,
    checkpoints: Sequence[StudioExportIntegrityCheckpoint],
) -> tuple[str, ...]:
    warnings: list[str] = []
    warnings.extend(preview.readiness_card.missing_items)
    if not comparison.ok:
        warnings.append(comparison.reason)
    for checkpoint in checkpoints:
        if checkpoint.required and not checkpoint.ok:
            warnings.append(f"blocking checkpoint: {checkpoint.checkpoint_id}")
    return tuple(dict.fromkeys(warnings))



def _severity(status: StudioExportIntegrityWorkflowStatus) -> str:
    if status is StudioExportIntegrityWorkflowStatus.VERIFIED:
        return "success"
    if status is StudioExportIntegrityWorkflowStatus.EMPTY:
        return "muted"
    if status in {StudioExportIntegrityWorkflowStatus.MISMATCH, StudioExportIntegrityWorkflowStatus.BLOCKED}:
        return "danger"
    return "warning"



def _manifest_without_hash(manifest: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if manifest is None:
        return None
    return {str(key): value for key, value in manifest.items() if str(key) != "manifest_hash"}


def _packet_hash(preview: StudioExportAuditPacketPreview) -> str:
    return _hash_payload(
        {
            "manifest": preview.manifest.as_manifest(),
            "checklist": preview.checklist.as_card(),
            "timeline_rows": preview.timeline_rows,
            "risk_notes": preview.risk_notes,
            "review_history_rows": preview.review_history_rows,
            "registry_rows": preview.registry_rows,
            "performance_attachment": preview.performance_attachment,
        }
    )



def _hash_payload(payload: Any) -> str:
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

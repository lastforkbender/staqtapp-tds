"""Evidence bundle and audit trail export for Driver Studio surfaces.

v3.1.6 adds a read-only export layer above fixture regression and admin batch
review. The exporter freezes the driver trust chain into deterministic,
Studio-ready packets: review decisions, fixture evidence summaries, audit events,
component hashes, and capability boundaries. It does not approve, sign, activate,
execute bytecode, mutate the Registry, write storage, or carry private keys.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from staqtapp_tds.version import __version__

from .regression import DriverRegressionReport
from .review import DriverBatchReviewReport, DriverReviewDecision


class EvidenceExportFormat(str, Enum):
    """Supported read-only export formats."""

    JSON = "json"


class EvidenceIntegrityStatus(str, Enum):
    """Integrity status for deterministic evidence bundles."""

    VERIFIED = "verified"
    INCOMPLETE = "incomplete"
    MISMATCHED = "mismatched"


class AuditTrailStatus(str, Enum):
    """Completeness status for exported audit trails."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"


class EvidenceBundleStatus(str, Enum):
    """Top-level bundle export outcome."""

    READY = "ready"
    PARTIAL = "partial"
    INPUT_REJECTED = "input_rejected"


class DriverAuditEventType(str, Enum):
    """Read-only event types used by the Driver Studio audit timeline."""

    REGRESSION_ATTACHED = "regression_attached"
    ADMIN_REVIEWED = "admin_reviewed"
    REGISTRY_STATE_OBSERVED = "registry_state_observed"
    EXPORT_CREATED = "export_created"
    EXPORT_VERIFIED = "export_verified"


@dataclass(frozen=True, slots=True)
class DriverAuditEvent:
    """One immutable audit event for chain-of-custody displays.

    ``timestamp`` is caller supplied. The exporter uses a stable default so test
    and CI packets remain deterministic; production callers can pass an explicit
    UTC timestamp from their own clock boundary.
    """

    event_id: str
    event_type: DriverAuditEventType
    driver_id: str | None = None
    driver_version: int | None = None
    actor_id: str = "tds-system"
    actor_role: str = "system"
    action: str | None = None
    reason: str = ""
    timestamp: str = "undated"
    previous_status: str | None = None
    resulting_status: str | None = None
    regression_report_hash: str | None = None
    runtime_evidence_hash: str | None = None
    review_hash: str | None = None
    batch_hash: str | None = None
    evidence_bundle_hash: str | None = None
    policy_hash: str | None = None
    public_key_fingerprint: str | None = None
    signature_status: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DriverAuditTrail:
    """Read-only audit trail plus deterministic trail hash."""

    status: AuditTrailStatus
    trail_hash: str
    events: tuple[DriverAuditEvent, ...]


@dataclass(frozen=True, slots=True)
class DriverEvidenceRecord:
    """Studio-ready evidence summary for one reviewed driver."""

    driver_id: str | None
    driver_version: int | None
    package_hash: str | None
    regression_report_hash: str | None
    review_hash: str | None
    decision_status: str
    requested_action: str
    final_action: str
    reviewer_id: str
    rationale: str
    reason: str
    risk_level: str
    registry_state_before: str | None = None
    registry_state_after: str | None = None
    evidence_summary: Mapping[str, Any] = field(default_factory=dict)
    fixture_results: tuple[Mapping[str, Any], ...] = ()
    faults: tuple[Mapping[str, Any], ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceBundleManifest:
    """Deterministic manifest describing an exported evidence bundle."""

    schema: str
    tds_version: str
    export_format: EvidenceExportFormat
    created_by: str
    created_at: str
    batch_id: str
    batch_hash: str
    driver_count: int
    audit_event_count: int
    component_hashes: Mapping[str, str | None] = field(default_factory=dict)
    private_keys_included: bool = False
    mutable_authority: bool = False
    storage_payload_included: bool = False


@dataclass(frozen=True, slots=True)
class DriverEvidenceBundle:
    """Frozen read-only packet for audit export and Driver Studio panels."""

    ok: bool
    status: EvidenceBundleStatus
    reason: str
    bundle_id: str
    bundle_hash: str
    integrity_status: EvidenceIntegrityStatus
    manifest: EvidenceBundleManifest
    audit_trail: DriverAuditTrail
    records: tuple[DriverEvidenceRecord, ...]
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Mapping[str, Any]:
        """Return a canonical JSON-compatible mapping."""

        return _bundle_payload(self, include_bundle_hash=True)

    def to_json(self) -> str:
        """Return a deterministic JSON export string."""

        return _canonical_json(self.to_dict())


class EvidenceBundleExporter:
    """Create and verify read-only driver evidence bundles.

    The exporter is intentionally below Studio and outside Registry authority. It
    may collect hashes and public signature metadata, but it never owns signing
    keys or performs signing/activation.
    """

    def __init__(self, *, export_format: EvidenceExportFormat | str = EvidenceExportFormat.JSON) -> None:
        self.export_format = _export_format_value(export_format)

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the export-layer authority boundary for GUI display."""

        return {
            "consume_batch_review_reports": True,
            "consume_regression_reports": True,
            "create_evidence_bundle": True,
            "create_audit_trail": True,
            "export_json": self.export_format is EvidenceExportFormat.JSON,
            "verify_export_integrity": True,
            "record_public_signature_metadata": True,
            "include_private_keys": False,
            "approve_driver": False,
            "call_registry_approve": False,
            "sign_driver": False,
            "attach_signature": False,
            "activate_driver": False,
            "run_driver_vm": False,
            "write_storage": False,
            "execute_python": False,
            "mutate_registry": False,
            "bypass_policy": False,
        }

    def export_batch_review(
        self,
        batch_report: DriverBatchReviewReport,
        *,
        regression_reports: Sequence[DriverRegressionReport] | Mapping[str, DriverRegressionReport] | None = None,
        created_by: str = "tds-admin",
        created_at: str = "undated",
        actor_role: str = "admin",
        policy_snapshot: Mapping[str, Any] | None = None,
        public_signature_metadata: Mapping[str, Mapping[str, Any]] | None = None,
        bundle_id: str | None = None,
    ) -> DriverEvidenceBundle:
        """Freeze one batch review report into a deterministic evidence packet.

        ``regression_reports`` is optional. When supplied, fixture replay details
        are included as read-only summaries; when omitted, the bundle still
        contains each review decision and its evidence summary.
        """

        report_index = _index_reports(regression_reports)
        public_signature_metadata = dict(public_signature_metadata or {})
        policy_hash = _hash_optional(policy_snapshot)
        records = tuple(_record_from_decision(decision, report_index.get(decision.report_hash)) for decision in batch_report.decisions)
        base_events = tuple(
            event
            for decision in batch_report.decisions
            for event in _events_for_decision(
                decision,
                batch_report=batch_report,
                report=report_index.get(decision.report_hash),
                created_by=created_by,
                created_at=created_at,
                actor_role=actor_role,
                policy_hash=policy_hash,
                signature_metadata=public_signature_metadata.get(str(decision.driver_id), {}),
            )
        )
        trail_without_export = _audit_trail(base_events)
        component_hashes = {
            "batch_hash": batch_report.batch_hash,
            "audit_trail_hash": trail_without_export.trail_hash,
            "policy_hash": policy_hash,
            "records_hash": _hash_payload([_record_map(record) for record in records]),
            "regression_corpus_hash": _hash_optional(
                [report.report_hash for report in report_index.values()] if report_index else None
            ),
        }
        manifest_without_export = EvidenceBundleManifest(
            schema="tds.driver.evidence.bundle.v1",
            tds_version=__version__,
            export_format=self.export_format,
            created_by=created_by,
            created_at=created_at,
            batch_id=batch_report.batch_id,
            batch_hash=batch_report.batch_hash,
            driver_count=len(records),
            audit_event_count=len(base_events) + 1,
            component_hashes=component_hashes,
        )
        status = _bundle_status(batch_report)
        reason = "evidence bundle exported" if status is EvidenceBundleStatus.READY else batch_report.reason
        preliminary = DriverEvidenceBundle(
            ok=batch_report.ok and len(records) > 0,
            status=status,
            reason=reason,
            bundle_id=bundle_id or "",
            bundle_hash="",
            integrity_status=EvidenceIntegrityStatus.INCOMPLETE,
            manifest=manifest_without_export,
            audit_trail=trail_without_export,
            records=records,
            capability_matrix=self.capability_matrix(),
        )
        preliminary_hash = _bundle_hash(preliminary)
        resolved_bundle_id = bundle_id or "tds-evidence-" + preliminary_hash.split(":", 1)[1][:16]
        export_event = _event(
            DriverAuditEventType.EXPORT_CREATED,
            actor_id=created_by,
            actor_role="exporter",
            action="export_created",
            reason="read-only evidence bundle created",
            timestamp=created_at,
            batch_hash=batch_report.batch_hash,
            evidence_bundle_hash=None,
            policy_hash=policy_hash,
            metadata={
                "bundle_id": resolved_bundle_id,
                "export_format": self.export_format.value,
                "pre_export_content_hash": preliminary_hash,
            },
        )
        audit_trail = _audit_trail(base_events + (export_event,))
        manifest = replace(manifest_without_export, audit_event_count=len(audit_trail.events), component_hashes={**component_hashes, "audit_trail_hash": audit_trail.trail_hash})
        bundle = DriverEvidenceBundle(
            ok=batch_report.ok and len(records) > 0,
            status=status,
            reason=reason,
            bundle_id=resolved_bundle_id,
            bundle_hash="",
            integrity_status=EvidenceIntegrityStatus.INCOMPLETE,
            manifest=manifest,
            audit_trail=audit_trail,
            records=records,
            capability_matrix=self.capability_matrix(),
        )
        final_hash = _bundle_hash(bundle)
        return replace(bundle, bundle_hash=final_hash, integrity_status=EvidenceIntegrityStatus.VERIFIED)

    def verify_bundle(self, bundle: DriverEvidenceBundle | Mapping[str, Any] | str) -> EvidenceIntegrityStatus:
        """Verify a bundle by recomputing its deterministic bundle hash."""

        if isinstance(bundle, DriverEvidenceBundle):
            if not bundle.records or not bundle.audit_trail.events:
                return EvidenceIntegrityStatus.INCOMPLETE
            return EvidenceIntegrityStatus.VERIFIED if _bundle_hash(bundle) == bundle.bundle_hash else EvidenceIntegrityStatus.MISMATCHED
        if isinstance(bundle, str):
            try:
                bundle = json.loads(bundle)
            except Exception:
                return EvidenceIntegrityStatus.MISMATCHED
        if not isinstance(bundle, Mapping):
            return EvidenceIntegrityStatus.MISMATCHED
        expected = bundle.get("bundle_hash")
        if not expected:
            return EvidenceIntegrityStatus.INCOMPLETE
        payload = dict(bundle)
        payload["bundle_hash"] = ""
        payload["integrity_status"] = EvidenceIntegrityStatus.INCOMPLETE.value
        actual = _hash_payload(payload)
        return EvidenceIntegrityStatus.VERIFIED if actual == expected else EvidenceIntegrityStatus.MISMATCHED

    # Short alias for UI/service code.
    export = export_batch_review
    verify = verify_bundle


def evidence_export_capability_matrix(export_format: EvidenceExportFormat | str = EvidenceExportFormat.JSON) -> Mapping[str, bool]:
    """Convenience function for displaying evidence-export authority."""

    return EvidenceBundleExporter(export_format=export_format).capability_matrix()


def _record_from_decision(decision: DriverReviewDecision, report: DriverRegressionReport | None) -> DriverEvidenceRecord:
    return DriverEvidenceRecord(
        driver_id=decision.driver_id,
        driver_version=decision.driver_version,
        package_hash=decision.package_hash,
        regression_report_hash=decision.report_hash,
        review_hash=decision.review_hash,
        decision_status=decision.status.value,
        requested_action=decision.requested_action.value,
        final_action=decision.final_action.value,
        reviewer_id=decision.reviewer_id,
        rationale=decision.rationale,
        reason=decision.reason,
        risk_level=decision.risk_level,
        registry_state_before=decision.registry_state_before,
        registry_state_after=decision.registry_state_after,
        evidence_summary=dict(decision.evidence_summary),
        fixture_results=_fixture_results(report),
        faults=tuple(_fault_map(fault) for fault in decision.faults),
        tags=tuple(decision.tags),
    )


def _fixture_results(report: DriverRegressionReport | None) -> tuple[Mapping[str, Any], ...]:
    if report is None:
        return ()
    return tuple(
        {
            "case_id": result.case_id,
            "passed": result.passed,
            "status": result.status.value,
            "fixture_hash": result.fixture_hash,
            "evidence_hash": result.evidence_hash,
            "mismatches": [
                {"field": mismatch.field, "expected": mismatch.expected, "actual": mismatch.actual}
                for mismatch in result.mismatches
            ],
            "runtime": {
                "ok": result.evidence.ok,
                "status": result.evidence.status.value,
                "reason": result.evidence.reason,
                "recommendation": result.evidence.recommendation,
                "trace_complete": result.evidence.trace_complete,
                "fault_codes": [fault.code for fault in result.evidence.faults],
                "metrics": dict(result.evidence.metrics),
                "snapshot_hash": result.evidence.snapshot_hash,
                "session_id": result.evidence.session_id,
            },
            "tags": list(result.tags),
        }
        for result in report.results
    )


def _events_for_decision(
    decision: DriverReviewDecision,
    *,
    batch_report: DriverBatchReviewReport,
    report: DriverRegressionReport | None,
    created_by: str,
    created_at: str,
    actor_role: str,
    policy_hash: str | None,
    signature_metadata: Mapping[str, Any],
) -> tuple[DriverAuditEvent, ...]:
    latest_evidence_hash = _latest_evidence_hash(report)
    events: list[DriverAuditEvent] = []
    if report is not None:
        events.append(
            _event(
                DriverAuditEventType.REGRESSION_ATTACHED,
                driver_id=decision.driver_id,
                driver_version=decision.driver_version,
                actor_id="regression-harness",
                actor_role="system",
                action="regression_attached",
                reason=report.reason,
                timestamp=created_at,
                regression_report_hash=report.report_hash,
                runtime_evidence_hash=latest_evidence_hash,
                batch_hash=batch_report.batch_hash,
                policy_hash=policy_hash,
                metadata={
                    "regression_status": report.status.value,
                    "case_count": report.case_count,
                    "passed_count": report.passed_count,
                    "failed_count": report.failed_count,
                },
            )
        )
    events.append(
        _event(
            DriverAuditEventType.ADMIN_REVIEWED,
            driver_id=decision.driver_id,
            driver_version=decision.driver_version,
            actor_id=decision.reviewer_id or created_by,
            actor_role=actor_role,
            action=decision.final_action.value,
            reason=decision.reason,
            timestamp=created_at,
            previous_status=decision.registry_state_before,
            resulting_status=decision.status.value,
            regression_report_hash=decision.report_hash,
            runtime_evidence_hash=latest_evidence_hash,
            review_hash=decision.review_hash,
            batch_hash=batch_report.batch_hash,
            policy_hash=policy_hash,
            metadata={
                "requested_action": decision.requested_action.value,
                "risk_level": decision.risk_level,
                "rationale": decision.rationale,
                "fault_codes": [fault.code for fault in decision.faults],
            },
        )
    )
    if decision.registry_state_before is not None or decision.registry_state_after is not None or signature_metadata:
        events.append(
            _event(
                DriverAuditEventType.REGISTRY_STATE_OBSERVED,
                driver_id=decision.driver_id,
                driver_version=decision.driver_version,
                actor_id="registry",
                actor_role="authority-observer",
                action="registry_state_observed",
                reason="registry state recorded for evidence export",
                timestamp=created_at,
                previous_status=decision.registry_state_before,
                resulting_status=decision.registry_state_after,
                regression_report_hash=decision.report_hash,
                runtime_evidence_hash=latest_evidence_hash,
                review_hash=decision.review_hash,
                batch_hash=batch_report.batch_hash,
                policy_hash=policy_hash,
                public_key_fingerprint=_optional_str(signature_metadata.get("public_key_fingerprint")),
                signature_status=_optional_str(signature_metadata.get("signature_status")),
                metadata={key: value for key, value in signature_metadata.items() if key not in {"private_key", "secret", "token"}},
            )
        )
    return tuple(events)


def _event(event_type: DriverAuditEventType, **items: Any) -> DriverAuditEvent:
    payload = {"event_type": event_type.value, **items}
    event_id = "tds-audit-" + _hash_payload(payload).split(":", 1)[1][:16]
    return DriverAuditEvent(event_id=event_id, event_type=event_type, **items)


def _audit_trail(events: Sequence[DriverAuditEvent]) -> DriverAuditTrail:
    if not events:
        status = AuditTrailStatus.EMPTY
    elif any(event.regression_report_hash is None and event.event_type is DriverAuditEventType.REGRESSION_ATTACHED for event in events):
        status = AuditTrailStatus.PARTIAL
    else:
        status = AuditTrailStatus.COMPLETE
    event_maps = [_event_map(event) for event in events]
    return DriverAuditTrail(status=status, trail_hash=_hash_payload(event_maps), events=tuple(events))


def _index_reports(
    reports: Sequence[DriverRegressionReport] | Mapping[str, DriverRegressionReport] | None,
) -> Mapping[str, DriverRegressionReport]:
    if reports is None:
        return {}
    if isinstance(reports, Mapping):
        values = reports.values()
    else:
        values = reports
    indexed: dict[str, DriverRegressionReport] = {}
    for report in values:
        if not isinstance(report, DriverRegressionReport):
            raise TypeError("regression_reports must contain DriverRegressionReport objects")
        indexed[str(report.report_hash)] = report
    return indexed


def _bundle_status(batch_report: DriverBatchReviewReport) -> EvidenceBundleStatus:
    if not batch_report.decisions:
        return EvidenceBundleStatus.INPUT_REJECTED
    if not batch_report.ok:
        return EvidenceBundleStatus.PARTIAL
    return EvidenceBundleStatus.READY


def _bundle_hash(bundle: DriverEvidenceBundle) -> str:
    return _hash_payload(_bundle_payload(bundle, include_bundle_hash=False))


def _bundle_payload(bundle: DriverEvidenceBundle, *, include_bundle_hash: bool) -> Mapping[str, Any]:
    return {
        "ok": bundle.ok,
        "status": bundle.status.value,
        "reason": bundle.reason,
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash if include_bundle_hash else "",
        "integrity_status": bundle.integrity_status.value if include_bundle_hash else EvidenceIntegrityStatus.INCOMPLETE.value,
        "manifest": _manifest_map(bundle.manifest),
        "audit_trail": _trail_map(bundle.audit_trail),
        "records": [_record_map(record) for record in bundle.records],
        "capability_matrix": dict(bundle.capability_matrix),
    }


def _manifest_map(manifest: EvidenceBundleManifest) -> Mapping[str, Any]:
    return {
        "schema": manifest.schema,
        "tds_version": manifest.tds_version,
        "export_format": manifest.export_format.value,
        "created_by": manifest.created_by,
        "created_at": manifest.created_at,
        "batch_id": manifest.batch_id,
        "batch_hash": manifest.batch_hash,
        "driver_count": manifest.driver_count,
        "audit_event_count": manifest.audit_event_count,
        "component_hashes": dict(manifest.component_hashes),
        "private_keys_included": manifest.private_keys_included,
        "mutable_authority": manifest.mutable_authority,
        "storage_payload_included": manifest.storage_payload_included,
    }


def _trail_map(trail: DriverAuditTrail) -> Mapping[str, Any]:
    return {
        "status": trail.status.value,
        "trail_hash": trail.trail_hash,
        "events": [_event_map(event) for event in trail.events],
    }


def _event_map(event: DriverAuditEvent) -> Mapping[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "driver_id": event.driver_id,
        "driver_version": event.driver_version,
        "actor_id": event.actor_id,
        "actor_role": event.actor_role,
        "action": event.action,
        "reason": event.reason,
        "timestamp": event.timestamp,
        "previous_status": event.previous_status,
        "resulting_status": event.resulting_status,
        "regression_report_hash": event.regression_report_hash,
        "runtime_evidence_hash": event.runtime_evidence_hash,
        "review_hash": event.review_hash,
        "batch_hash": event.batch_hash,
        "evidence_bundle_hash": event.evidence_bundle_hash,
        "policy_hash": event.policy_hash,
        "public_key_fingerprint": event.public_key_fingerprint,
        "signature_status": event.signature_status,
        "metadata": dict(event.metadata),
    }


def _record_map(record: DriverEvidenceRecord) -> Mapping[str, Any]:
    return {
        "driver_id": record.driver_id,
        "driver_version": record.driver_version,
        "package_hash": record.package_hash,
        "regression_report_hash": record.regression_report_hash,
        "review_hash": record.review_hash,
        "decision_status": record.decision_status,
        "requested_action": record.requested_action,
        "final_action": record.final_action,
        "reviewer_id": record.reviewer_id,
        "rationale": record.rationale,
        "reason": record.reason,
        "risk_level": record.risk_level,
        "registry_state_before": record.registry_state_before,
        "registry_state_after": record.registry_state_after,
        "evidence_summary": dict(record.evidence_summary),
        "fixture_results": [dict(item) for item in record.fixture_results],
        "faults": [dict(item) for item in record.faults],
        "tags": list(record.tags),
    }


def _fault_map(fault: Any) -> Mapping[str, Any]:
    return {
        "code": getattr(fault, "code", None),
        "message": getattr(fault, "message", ""),
        "severity": getattr(fault, "severity", "error"),
        "recoverable": getattr(fault, "recoverable", True),
    }


def _latest_evidence_hash(report: DriverRegressionReport | None) -> str | None:
    if report is None or not report.results:
        return None
    return report.results[-1].evidence_hash


def _hash_optional(value: Any) -> str | None:
    if value is None:
        return None
    return _hash_payload(value)


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


def _export_format_value(value: EvidenceExportFormat | str) -> EvidenceExportFormat:
    if isinstance(value, EvidenceExportFormat):
        return value
    return EvidenceExportFormat(str(value))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)

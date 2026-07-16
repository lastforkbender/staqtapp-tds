import copy
import json

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    AuditTrailStatus,
    BatchReviewPolicy,
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverManifest,
    DriverRegressionHarness,
    DriverRegistry,
    DriverState,
    EvidenceBundleExporter,
    EvidenceBundleStatus,
    EvidenceIntegrityStatus,
    ReviewAction,
    RuntimeManagerStatus,
    VMStatus,
    compile_tddl,
    evidence_export_capability_matrix,
)

SEARCH_DRIVER = '''
driver SearchPolicyDrivers v1

manifest:
  kind = "search"
  description = "Find policy-related driver manifests"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read
  capability trace.write
  adapter predicate.semantic_manifest.v1
  adapter scorer.trace_rank.v1

limits:
  max_scan = 5000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=5000 depth=8
  READ target="manifest"
  MATCH field="manifest.kind" eq="driver"
  MATCH using="predicate.semantic_manifest.v1" query="policy routing" threshold=0.80
  EXTRACT from="manifest" fields=["driver_id", "version", "capabilities", "safety"]
  SCORE using="scorer.trace_rank.v1" weight="semantic" threshold=0.75
  TRACE event="policy_driver_candidate"
  EMIT mode="ranked" limit=2
  HALT

evolution:
  deny external_io
  max_delta = 1
'''

EXTRACT_DRIVER = SEARCH_DRIVER.replace("SearchPolicyDrivers", "ExtractPolicyDrivers").replace('kind = "search"', 'kind = "extract"')

RECORDS = [
    {
        "path": ".tds/drivers/policy_routing",
        "manifest": {
            "kind": "driver",
            "driver_id": "PolicyRoutingA",
            "version": 3,
            "capabilities": ["policy", "routing", "search"],
            "safety": "bounded",
        },
        "semantic_score": 0.93,
    },
]


def _clean_report(source=SEARCH_DRIVER):
    package = compile_tddl(source)
    case = DriverFixtureCase(
        "policy-hit",
        {"records": copy.deepcopy(RECORDS)},
        expected_ok=True,
        expected_status=RuntimeManagerStatus.EXECUTED,
        expected_recommendation="candidate_ready",
        expected_vm_status=VMStatus.HALTED,
        expected_emitted_count=1,
        expected_trace_complete=True,
        tags=("golden",),
    )
    return package, DriverRegressionHarness().run_package(package, (case,))


def _approval_ready_batch(report):
    return DriverBatchReviewBoard().review_reports(
        (report,),
        reviewer_id="admin-1",
        rationale="fixture evidence reviewed",
        batch_id="batch-v316-a",
    )


def test_v316_version():
    assert __version__ == "3.5.3.post1"


def test_evidence_export_capability_matrix_is_read_only_and_key_safe():
    matrix = evidence_export_capability_matrix()

    assert matrix["consume_batch_review_reports"] is True
    assert matrix["consume_regression_reports"] is True
    assert matrix["create_evidence_bundle"] is True
    assert matrix["create_audit_trail"] is True
    assert matrix["export_json"] is True
    assert matrix["verify_export_integrity"] is True
    assert matrix["record_public_signature_metadata"] is True
    assert matrix["include_private_keys"] is False
    assert matrix["approve_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False
    assert matrix["execute_python"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["bypass_policy"] is False


def test_exporter_freezes_batch_review_decision_and_fixture_replay_summary():
    _package, report = _clean_report()
    batch = _approval_ready_batch(report)

    bundle = EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-05T20:00:00Z",
        policy_snapshot={"mode": "strict"},
    )

    assert bundle.ok is True
    assert bundle.status is EvidenceBundleStatus.READY
    assert bundle.integrity_status is EvidenceIntegrityStatus.VERIFIED
    assert bundle.bundle_hash.startswith("sha256:")
    assert bundle.bundle_id.startswith("tds-evidence-")
    assert bundle.manifest.schema == "tds.driver.evidence.bundle.v1"
    assert bundle.manifest.tds_version == "3.5.3.post1"
    assert bundle.manifest.private_keys_included is False
    assert bundle.manifest.mutable_authority is False
    assert bundle.audit_trail.status is AuditTrailStatus.COMPLETE
    assert bundle.records[0].driver_id == "SearchPolicyDrivers"
    assert bundle.records[0].decision_status == "approval_ready"
    assert bundle.records[0].risk_level == "low"
    assert bundle.records[0].fixture_results[0]["case_id"] == "policy-hit"
    assert bundle.records[0].fixture_results[0]["runtime"]["status"] == "executed"
    assert bundle.records[0].fixture_results[0]["runtime"]["trace_complete"] is True


def test_evidence_bundle_json_export_is_deterministic_and_verifiable():
    _package, report = _clean_report()
    batch = _approval_ready_batch(report)
    exporter = EvidenceBundleExporter()

    first = exporter.export_batch_review(batch, regression_reports=(report,), created_by="admin-1", created_at="fixed")
    second = exporter.export_batch_review(batch, regression_reports=(report,), created_by="admin-1", created_at="fixed")

    assert first.bundle_hash == second.bundle_hash
    assert first.to_json() == second.to_json()
    assert exporter.verify_bundle(first) is EvidenceIntegrityStatus.VERIFIED
    assert exporter.verify_bundle(first.to_json()) is EvidenceIntegrityStatus.VERIFIED


def test_tampered_bundle_mapping_is_reported_as_mismatched():
    _package, report = _clean_report()
    batch = _approval_ready_batch(report)
    exporter = EvidenceBundleExporter()
    bundle = exporter.export_batch_review(batch, regression_reports=(report,), created_by="admin-1", created_at="fixed")
    payload = json.loads(bundle.to_json())

    payload["records"][0]["risk_level"] = "low-but-tampered"

    assert exporter.verify_bundle(payload) is EvidenceIntegrityStatus.MISMATCHED


def test_export_without_regression_reports_still_preserves_review_chain_but_no_fixture_details():
    _package, report = _clean_report()
    batch = _approval_ready_batch(report)

    bundle = EvidenceBundleExporter().export_batch_review(batch, created_by="admin-1", created_at="fixed")

    assert bundle.ok is True
    assert bundle.records[0].regression_report_hash == report.report_hash
    assert bundle.records[0].fixture_results == ()
    event_types = tuple(event.event_type.value for event in bundle.audit_trail.events)
    assert "admin_reviewed" in event_types
    assert "export_created" in event_types


def test_registry_approval_export_records_observed_registry_state_without_signing_power():
    package, report = _clean_report()
    registry = DriverRegistry()
    manifest = DriverManifest.from_mapping(
        {
            "driver_id": report.driver_id,
            "version": report.driver_version,
            "kind": "search",
            "description": "candidate from regression report",
            "safety": "bounded",
            "capabilities": ("registry.scan", "manifest.read", "trace.write"),
        }
    )
    registry.add_candidate(manifest, test_report_hash=report.report_hash)
    batch = DriverBatchReviewBoard(policy=BatchReviewPolicy(allow_registry_approval=True)).review_reports(
        (report,), registry=registry, apply_registry=True, batch_id="batch-registry"
    )

    bundle = EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="fixed",
        public_signature_metadata={
            "SearchPolicyDrivers": {
                "public_key_fingerprint": "SHA256:ABC123",
                "signature_status": "not_signed",
                "private_key": "must-not-export",
                "token": "must-not-export",
            }
        },
    )

    assert registry.require(package.header["driver_id"]).state is DriverState.APPROVED
    assert bundle.records[0].registry_state_before == DriverState.CANDIDATE.value
    assert bundle.records[0].registry_state_after == DriverState.APPROVED.value
    registry_events = [event for event in bundle.audit_trail.events if event.event_type.value == "registry_state_observed"]
    assert len(registry_events) == 1
    assert registry_events[0].public_key_fingerprint == "SHA256:ABC123"
    assert registry_events[0].signature_status == "not_signed"
    assert "private_key" not in registry_events[0].metadata
    assert "token" not in registry_events[0].metadata
    assert bundle.capability_matrix["sign_driver"] is False
    assert not hasattr(EvidenceBundleExporter(), "attach_signature")
    assert not hasattr(EvidenceBundleExporter(), "activate")


def test_partial_batch_review_exports_as_partial_read_only_packet():
    package, report = _clean_report()
    registry = DriverRegistry()
    # apply_registry=True without an allow policy creates a registry-rejected decision.
    batch = DriverBatchReviewBoard().review_reports((report,), registry=registry, apply_registry=True, batch_id="batch-partial")

    bundle = EvidenceBundleExporter().export_batch_review(batch, regression_reports=(report,), created_by="admin-1", created_at="fixed")

    assert batch.ok is False
    assert bundle.ok is False
    assert bundle.status is EvidenceBundleStatus.PARTIAL
    assert bundle.records[0].decision_status == "registry_rejected"
    assert bundle.records[0].faults[0]["code"] == "review.registry.unknown_driver"
    assert package.package_hash == bundle.records[0].package_hash


def test_input_rejected_empty_batch_exports_incomplete_integrity_material():
    batch = DriverBatchReviewBoard().review_reports(())

    bundle = EvidenceBundleExporter().export_batch_review(batch, created_by="admin-1", created_at="fixed")

    assert bundle.ok is False
    assert bundle.status is EvidenceBundleStatus.INPUT_REJECTED
    assert bundle.records == ()
    assert bundle.audit_trail.status is AuditTrailStatus.COMPLETE
    assert EvidenceBundleExporter().verify_bundle(bundle) is EvidenceIntegrityStatus.INCOMPLETE


def test_multi_driver_export_keeps_one_record_per_review_decision():
    _package, search_report = _clean_report()
    _extract_package, extract_report = _clean_report(EXTRACT_DRIVER)
    batch = DriverBatchReviewBoard().review_reports(
        (search_report, extract_report),
        action_overrides={"SearchPolicyDrivers": ReviewAction.QUARANTINE, "ExtractPolicyDrivers": ReviewAction.HOLD},
        reviewer_id="admin-2",
        rationale="needs another visual fixture pass",
        batch_id="batch-multi",
    )

    bundle = EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(search_report, extract_report),
        created_by="admin-2",
        created_at="fixed",
    )

    assert len(bundle.records) == 2
    assert tuple(record.driver_id for record in bundle.records) == ("SearchPolicyDrivers", "ExtractPolicyDrivers")
    assert tuple(record.final_action for record in bundle.records) == ("quarantine", "hold")
    assert bundle.records[0].fixture_results[0]["evidence_hash"].startswith("sha256:")
    assert bundle.manifest.driver_count == 2
    assert bundle.manifest.component_hashes["records_hash"].startswith("sha256:")

import copy
import json

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    BatchReviewPolicy,
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverManifest,
    DriverRegistry,
    DriverRegressionHarness,
    DriverStudioReadOnlyConsole,
    EvidenceBundleExporter,
    RuntimeManagerStatus,
    StudioConsoleStatus,
    StudioPanelKind,
    StudioPanelStatus,
    VMStatus,
    compile_tddl,
    studio_readonly_capability_matrix,
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


def _bundle(report, *, registry_approved=False):
    registry = None
    if registry_approved:
        registry = DriverRegistry()
        registry.add_candidate(
            DriverManifest.from_mapping(
                {
                    "driver_id": report.driver_id,
                    "version": report.driver_version,
                    "kind": "search",
                    "description": "candidate from regression report",
                    "safety": "bounded",
                    "capabilities": ("registry.scan", "manifest.read", "trace.write"),
                }
            ),
            test_report_hash=report.report_hash,
        )
        batch = DriverBatchReviewBoard(policy=BatchReviewPolicy(allow_registry_approval=True)).review_reports(
            (report,), registry=registry, apply_registry=True, batch_id="batch-v317-registry"
        )
    else:
        batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v317")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-05T21:00:00Z",
        public_signature_metadata={str(report.driver_id): {"public_key_fingerprint": "SHA256:V317", "signature_status": "not_signed"}},
    )


def test_v317_version():
    assert __version__ == "3.1.25"


def test_studio_readonly_capability_matrix_denies_mutating_authority():
    matrix = studio_readonly_capability_matrix()

    assert matrix["load_evidence_bundle"] is True
    assert matrix["render_driver_queue"] is True
    assert matrix["render_evidence_bundle"] is True
    assert matrix["render_audit_trail"] is True
    assert matrix["render_fixture_replay"] is True
    assert matrix["render_risk_cards"] is True
    assert matrix["render_registry_state"] is True
    assert matrix["verify_export_integrity"] is True
    assert matrix["record_public_signature_metadata"] is True
    assert matrix["include_private_keys"] is False
    assert matrix["approve_driver"] is False
    assert matrix["reject_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["edit_tddl"] is False
    assert matrix["edit_bytecode"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False
    assert matrix["execute_python"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["bypass_policy"] is False


def test_readonly_console_builds_browser_like_panel_snapshots_from_bundle():
    _package, report = _clean_report()
    bundle = _bundle(report)

    snapshot = DriverStudioReadOnlyConsole().open_bundle(bundle)

    assert snapshot.ok is True
    assert snapshot.status is StudioConsoleStatus.READY
    assert snapshot.integrity_status == "verified"
    assert snapshot.selected_driver_id == "SearchPolicyDrivers"
    assert snapshot.console_hash.startswith("sha256:")
    assert len(snapshot.panels) == len(tuple(StudioPanelKind))
    assert {panel.kind for panel in snapshot.panels} == {
        StudioPanelKind.DRIVER_QUEUE,
        StudioPanelKind.EVIDENCE_BUNDLE,
        StudioPanelKind.AUDIT_TRAIL,
        StudioPanelKind.EVIDENCE_TIMELINE,
        StudioPanelKind.FIXTURE_REPLAY,
        StudioPanelKind.RISK_CARD,
        StudioPanelKind.REGISTRY_STATE,
        StudioPanelKind.EXPORT_INTEGRITY,
        StudioPanelKind.EXPORT_AUDIT_CONSOLE,
        StudioPanelKind.MANUAL_DRIVER_BUILDER,
        StudioPanelKind.EVENT_CONSOLE,
    }
    assert snapshot.panel(StudioPanelKind.DRIVER_QUEUE).metrics["driver_count"] == 1
    assert snapshot.panel("fixture_replay").metrics["passed_count"] == 1
    assert snapshot.panel(StudioPanelKind.RISK_CARD).rows[0]["decision_status"] == "approval_ready"
    assert "sign_driver" in snapshot.risk_cards[0].blocked_authority
    assert snapshot.panel(StudioPanelKind.EXPORT_INTEGRITY).status is StudioPanelStatus.READY


def test_readonly_console_hash_and_json_are_deterministic_for_same_bundle():
    _package, report = _clean_report()
    bundle = _bundle(report)
    console = DriverStudioReadOnlyConsole()

    first = console.open_bundle(bundle)
    second = console.open_bundle(bundle.to_json())

    assert first.console_hash == second.console_hash
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["bundle_hash"] == bundle.bundle_hash


def test_readonly_console_reports_tampered_bundle_without_gaining_approval_power():
    _package, report = _clean_report()
    bundle = _bundle(report)
    payload = json.loads(bundle.to_json())
    payload["records"][0]["risk_level"] = "tampered"

    snapshot = DriverStudioReadOnlyConsole().open_bundle(payload)

    assert snapshot.ok is False
    assert snapshot.status is StudioConsoleStatus.INTEGRITY_MISMATCH
    assert snapshot.panel(StudioPanelKind.EXPORT_INTEGRITY).status is StudioPanelStatus.INTEGRITY_MISMATCH
    assert snapshot.panel(StudioPanelKind.EXPORT_INTEGRITY).warnings == ("bundle hash did not verify",)
    assert snapshot.capability_matrix["approve_driver"] is False
    assert snapshot.capability_matrix["sign_driver"] is False
    assert not hasattr(DriverStudioReadOnlyConsole(), "approve")
    assert not hasattr(DriverStudioReadOnlyConsole(), "sign")
    assert not hasattr(DriverStudioReadOnlyConsole(), "activate")
    assert not hasattr(DriverStudioReadOnlyConsole(), "execute")


def test_readonly_console_selected_driver_filters_fixture_and_risk_panels():
    _package_a, report_a = _clean_report(SEARCH_DRIVER)
    _package_b, report_b = _clean_report(EXTRACT_DRIVER)
    batch = DriverBatchReviewBoard().review_reports((report_a, report_b), reviewer_id="admin-1", batch_id="batch-v317-multi")
    bundle = EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report_a, report_b),
        created_by="admin-1",
        created_at="fixed",
    )

    snapshot = DriverStudioReadOnlyConsole().open_bundle(bundle, selected_driver_id="ExtractPolicyDrivers")

    assert snapshot.selected_driver_id == "ExtractPolicyDrivers"
    assert len(snapshot.queue) == 2
    assert [item.selected for item in snapshot.queue] == [False, True]
    assert snapshot.panel(StudioPanelKind.FIXTURE_REPLAY).metrics["fixture_count"] == 1
    assert snapshot.panel(StudioPanelKind.FIXTURE_REPLAY).rows[0]["driver_id"] == "ExtractPolicyDrivers"
    assert snapshot.panel(StudioPanelKind.RISK_CARD).rows[0]["driver_id"] == "ExtractPolicyDrivers"

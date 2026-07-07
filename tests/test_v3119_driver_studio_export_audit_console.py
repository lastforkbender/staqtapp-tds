import copy

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverBatchReviewBoard,
    DriverFixtureCase,
    DriverRegressionHarness,
    EvidenceBundleExporter,
    ReviewAction,
    RuntimeManagerStatus,
    StudioPanelKind,
    VMStatus,
    compile_tddl,
)
from staqtapp_tds.studio_pyqt5 import (
    StudioExportAuditConsole,
    StudioExportAuditConsoleState,
    StudioExportAuditIntegrityItem,
    StudioExportAuditManifest,
    StudioExportAuditPacketPreview,
    StudioExportAuditStatus,
    StudioQtBridge,
    studio_export_audit_capability_matrix,
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


def _bundle(*, action=ReviewAction.APPROVE):
    package = compile_tddl(SEARCH_DRIVER)
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
    report = DriverRegressionHarness().run_package(package, (case,))
    batch = DriverBatchReviewBoard().review_reports(
        (report,),
        reviewer_id="admin-1",
        requested_action=action,
        rationale="export audit console test path",
        batch_id="batch-v3119",
    )
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-07T08:00:00Z",
    )


def test_v3119_version():
    assert __version__ == "3.1.20"


def test_export_audit_capability_matrix_is_prepare_only():
    matrix = studio_export_audit_capability_matrix()

    assert matrix["export_audit_console"] is True
    assert matrix["prepare_export_audit_packet_preview"] is True
    assert matrix["prepare_export_audit_manifest"] is True
    assert matrix["prepare_export_manifest_hash"] is True
    assert matrix["map_evidence_timeline_to_export"] is True
    assert matrix["map_risk_intelligence_to_export_notes"] is True
    assert matrix["map_review_workflow_to_export_history"] is True
    assert matrix["map_registry_observations_to_export"] is True
    assert matrix["attach_performance_evidence_when_explicit"] is True
    assert matrix["export_audit_console_is_authority"] is False
    assert matrix["export_audit_console_mutates_backend"] is False
    assert matrix["approve_driver"] is False
    assert matrix["reject_driver"] is False
    assert matrix["quarantine_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["store_private_keys"] is False
    assert matrix["bypass_policy"] is False

    console = StudioExportAuditConsole()
    assert not hasattr(console, "approve")
    assert not hasattr(console, "sign")
    assert not hasattr(console, "activate")


def test_export_audit_console_joins_timeline_risk_review_registry_and_hashes():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    runtime.mark_all_dirty(reason="initial export audit paint")

    state = runtime.export_audit_console().current_state()

    assert isinstance(state, StudioExportAuditConsoleState)
    assert state.ok is True
    assert state.status is StudioExportAuditStatus.READY
    assert state.selected_driver_id == "SearchPolicyDrivers"
    assert isinstance(state.manifest, StudioExportAuditManifest)
    assert state.manifest.manifest_hash.startswith("sha256:")
    assert state.manifest.package_hash
    assert state.manifest.regression_report_hash
    assert state.manifest.review_hash
    assert state.manifest.evidence_bundle_hash == state.bundle_hash
    assert state.manifest.registry_observation_count >= 0
    assert state.manifest.timeline_event_count >= 8
    assert state.manifest.risk_factor_count >= 4
    assert state.manifest.review_history_count >= 1
    assert state.preview.packet_hash.startswith("sha256:")
    assert isinstance(state.preview, StudioExportAuditPacketPreview)
    assert state.preview.ok is True
    assert state.checklist.ready is True
    assert all(isinstance(item, StudioExportAuditIntegrityItem) for item in state.integrity_items)
    assert state.readiness_card.export_ready is True
    assert state.signal_payload()["capability_matrix"]["mutate_registry"] is False


def test_export_audit_cockpit_panel_and_refresh_contract_are_gui_ready():
    bridge = StudioQtBridge()
    shell = bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    panel = shell.panel(StudioPanelKind.EXPORT_AUDIT_CONSOLE)
    hydrated = bridge.hydrate_panel(StudioPanelKind.EXPORT_AUDIT_CONSOLE)
    runtime = bridge.live_panel_runtime(max_events=16)
    runtime_state = runtime.mark_all_dirty(reason="paint export audit")

    assert panel.title == "Export / Audit Console"
    assert panel.primary_surface == "audit_packet_preview"
    assert panel.rows[0]["readiness_status"] == "packet_ready"
    assert hydrated.cards[0].badges == ("packet-ready", "hash-backed", "prepare-only")
    assert any(packet.kind is StudioPanelKind.EXPORT_AUDIT_CONSOLE for packet in runtime_state.refresh_packets)
    assert bridge.capability_matrix()["create_export_audit_console"] is True
    assert runtime.capability_matrix()["create_export_audit_console"] is True


def test_export_audit_accepts_explicit_optional_performance_evidence():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    console = bridge.export_audit_console(max_events=16)
    perf = {
        "ok": True,
        "driver_id": "SearchPolicyDrivers",
        "snapshot_hash": "sha256:" + "1" * 64,
        "performance_hash": "sha256:" + "2" * 64,
    }

    state = console.current_state(performance_report=perf)

    assert state.ok is True
    assert state.manifest.performance_evidence_hash == perf["performance_hash"]
    assert state.preview.performance_attachment["performance_hash"] == perf["performance_hash"]
    item = [item for item in state.integrity_items if item.item_id == "performance_evidence"][0]
    assert item.required is False
    assert item.status == "attached"
    assert state.metrics["has_performance_attachment"] is True

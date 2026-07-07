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
    StudioCockpitHydrator,
    StudioHydratedCockpitState,
    StudioPanelActionDescriptor,
    StudioQtBridge,
    manual_builder_form_schema,
    studio_cockpit_hydration_capability_matrix,
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


def _bundle():
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
    batch = DriverBatchReviewBoard().review_reports((report,), reviewer_id="admin-1", batch_id="batch-v3111")
    return EvidenceBundleExporter().export_batch_review(
        batch,
        regression_reports=(report,),
        created_by="admin-1",
        created_at="2026-07-06T05:00:00Z",
    )


def test_v3111_version():
    assert __version__ == "3.1.23"


def test_hydration_capability_matrix_is_gui_power_not_trust_authority():
    matrix = studio_cockpit_hydration_capability_matrix()

    assert matrix["hydrate_panel_view_models"] is True
    assert matrix["render_table_columns"] is True
    assert matrix["render_card_surfaces"] is True
    assert matrix["render_timeline_stream"] is True
    assert matrix["render_review_action_descriptors"] is True
    assert matrix["render_manual_builder_form_schema"] is True
    assert matrix["approve_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["store_private_keys"] is False
    assert matrix["bypass_policy"] is False

    hydrator = StudioCockpitHydrator()
    assert not hasattr(hydrator, "approve")
    assert not hasattr(hydrator, "sign")
    assert not hasattr(hydrator, "activate")


def test_hydrated_empty_shell_has_all_panel_models_and_builder_schema():
    bridge = StudioQtBridge()
    hydrated = bridge.hydrated_shell_state()

    assert isinstance(hydrated, StudioHydratedCockpitState)
    assert hydrated.status == "empty"
    assert hydrated.severity == "muted"
    assert len(hydrated.panels) == len(tuple(StudioPanelKind))

    queue = hydrated.panel(StudioPanelKind.DRIVER_QUEUE)
    assert queue.columns[0].key == "selected"
    assert queue.actions
    assert all(action.enabled is False for action in queue.actions)

    builder = hydrated.panel(StudioPanelKind.MANUAL_DRIVER_BUILDER)
    assert builder.read_only is False
    assert builder.primary_surface == "proposal_workbench"
    assert len(builder.form_fields) >= 12
    assert any(field.name == "scan_scope" and field.default == ".tds" for field in builder.form_fields)
    assert builder.cards[0].fields["registry_authority"] is False


def test_hydrated_bundle_exposes_tables_cards_timelines_and_safe_actions():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    hydrated = bridge.hydrated_shell_state()

    assert hydrated.ok is True
    assert hydrated.status == "ready"
    assert hydrated.severity == "success"
    assert hydrated.selected_driver_id == "SearchPolicyDrivers"
    assert hydrated.metrics["panel_count"] == len(tuple(StudioPanelKind))
    assert hydrated.capability_matrix["hydrate_panel_view_models"] is True
    assert hydrated.capability_matrix["approve_driver"] is False
    assert hydrated.capability_matrix["activate_driver"] is False

    queue = hydrated.panel("driver_queue")
    assert [column.key for column in queue.columns][:3] == ["selected", "driver_id", "driver_version"]
    assert queue.rows[0]["driver_id"] == "SearchPolicyDrivers"
    assert any(action.requested_action == ReviewAction.APPROVE.value and action.enabled for action in queue.actions)
    assert all(isinstance(action, StudioPanelActionDescriptor) for action in queue.actions)
    assert all("Registry" in action.reason or "Review Board" in action.reason or "Studio" in action.reason for action in queue.actions)

    risk = hydrated.panel(StudioPanelKind.RISK_CARD)
    assert risk.cards
    assert risk.cards[0].title == "SearchPolicyDrivers"
    assert "blocked_authority" in risk.cards[0].fields
    assert "activate_driver" in risk.cards[0].fields["blocked_authority"]

    event_console = hydrated.panel(StudioPanelKind.EVENT_CONSOLE)
    assert event_console.dock_area == "bottom"
    assert event_console.timeline
    assert hydrated.event_stream == event_console.timeline
    assert all(item.timestamp for item in event_console.timeline)

    integrity = bridge.hydrate_panel(StudioPanelKind.EXPORT_INTEGRITY)
    assert integrity.cards[0].severity == "success"
    assert integrity.cards[0].badges == ("verified",)


def test_manual_builder_form_schema_is_stable_and_bounded():
    fields = manual_builder_form_schema()
    by_name = {field.name: field for field in fields}

    assert by_name["driver_id"].required is True
    assert by_name["kind"].options == ("search", "extract", "rank", "adapter", "policy")
    assert by_name["safety"].options == ("bounded", "restricted", "experimental")
    assert by_name["scan_limit"].minimum == 1
    assert by_name["scan_limit"].maximum == 100000
    assert by_name["semantic_threshold"].minimum == 0.0
    assert by_name["semantic_threshold"].maximum == 1.0
    assert by_name["emit_mode"].options == ("ranked", "list", "first", "proposal")

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverStudioManualProposalBuilder,
    FoundryStatus,
    StudioManualDriverTask,
    StudioManualProposalStatus,
    StudioPanelKind,
    VMStatus,
    parse_tddl,
    studio_manual_builder_capability_matrix,
)
from staqtapp_tds.studio_pyqt5 import StudioQtBridge


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


def _task() -> StudioManualDriverTask:
    return StudioManualDriverTask(
        driver_id="ManualPolicyDriver",
        description="Manual cockpit proposal for policy-routing manifests",
        semantic_query="policy routing",
        emit_limit=2,
        tags=("manual", "studio"),
    )


def test_v3110_version():
    assert __version__ == "3.1.25"


def test_manual_builder_capability_matrix_has_proposal_power_not_trust_authority():
    matrix = studio_manual_builder_capability_matrix()

    assert matrix["render_manual_builder"] is True
    assert matrix["accept_human_task_fields"] is True
    assert matrix["generate_tddl_source"] is True
    assert matrix["route_to_foundry"] is True
    assert matrix["validate_driver"] is True
    assert matrix["compile_driver"] is True
    assert matrix["audit_driver"] is True
    assert matrix["test_driver_with_fixtures"] is True
    assert matrix["submit_candidate"] is False
    assert matrix["approve_driver"] is False
    assert matrix["call_registry_approve"] is False
    assert matrix["sign_driver"] is False
    assert matrix["attach_signature"] is False
    assert matrix["activate_driver"] is False
    assert matrix["write_storage"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["store_private_keys"] is False
    assert matrix["bypass_policy"] is False

    builder = DriverStudioManualProposalBuilder()
    assert not hasattr(builder, "approve")
    assert not hasattr(builder, "sign")
    assert not hasattr(builder, "activate")
    assert not hasattr(builder, "submit_candidate")


def test_manual_builder_preview_generates_deterministic_valid_tddl_source():
    builder = DriverStudioManualProposalBuilder()

    first = builder.preview_task(_task())
    second = builder.preview_task(_task())

    assert first.ok is True
    assert first.status is StudioManualProposalStatus.PREVIEWED
    assert first.source_hash == second.source_hash
    assert "driver ManualPolicyDriver v1" in first.source
    assert "SCAN scope=\".tds\"" in first.source
    assert "HALT" in first.source
    assert first.metrics["instruction_count"] == 9
    assert first.metrics["capability_count"] == 3
    assert any("proposal only" in warning for warning in first.warnings)

    program = parse_tddl(first.source)
    assert program.driver_id == "ManualPolicyDriver"
    assert program.manifest["kind"] == "search"
    assert program.instruction_names[-1] == "HALT"


def test_manual_builder_routes_proposals_through_foundry_with_fixtures():
    builder = DriverStudioManualProposalBuilder()

    report = builder.propose_task(_task(), fixtures={"records": RECORDS})

    assert report.ok is True
    assert report.status is StudioManualProposalStatus.PROPOSED
    assert report.foundry_result is not None
    assert report.foundry_result.status is FoundryStatus.TESTED
    assert report.foundry_result.vm_result is not None
    assert report.foundry_result.vm_result.status is VMStatus.HALTED
    assert report.metrics["foundry_stage"] == "propose"
    assert report.metrics["vm_status"] == "halted"
    assert report.capability_matrix["submit_candidate"] is False
    assert report.capability_matrix["activate_driver"] is False


def test_manual_builder_rejects_unsafe_task_before_foundry():
    builder = DriverStudioManualProposalBuilder()
    bad = StudioManualDriverTask(
        driver_id="UnsafeManualDriver",
        description="Unsafe scope should fail closed",
        scan_scope="../outside",
    )

    preview = builder.preview_task(bad)
    report = builder.propose_task(bad, fixtures={"records": RECORDS})

    assert preview.ok is False
    assert preview.status is StudioManualProposalStatus.INPUT_REJECTED
    assert "scan_scope" in preview.reason
    assert report.ok is False
    assert report.foundry_result is None
    assert report.capability_matrix["bypass_policy"] is False


def test_pyqt_bridge_hydrates_manual_builder_panel_and_routes_task_to_builder():
    bridge = StudioQtBridge()
    empty_state = bridge.shell_state()

    assert empty_state.panel(StudioPanelKind.MANUAL_DRIVER_BUILDER).primary_surface == "proposal_workbench"
    assert empty_state.panel(StudioPanelKind.MANUAL_DRIVER_BUILDER).read_only is False
    assert bridge.capability_matrix()["route_manual_driver_proposals_to_foundry"] is True
    assert bridge.capability_matrix()["submit_candidate"] is False

    preview = bridge.preview_manual_driver_task(_task())
    report = bridge.propose_manual_driver_task(_task(), fixtures={"records": RECORDS})

    assert preview.ok is True
    assert preview.source_hash == report.source_hash
    assert report.ok is True
    assert report.foundry_result is not None
    assert report.foundry_result.context.driver_id == "ManualPolicyDriver"

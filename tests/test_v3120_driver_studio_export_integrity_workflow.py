from staqtapp_tds import __version__
from staqtapp_tds.drivers import StudioPanelKind
from staqtapp_tds.studio_pyqt5 import (
    StudioExportIntegrityCheckpoint,
    StudioExportIntegrityCheckpointStatus,
    StudioExportIntegrityManifestComparison,
    StudioExportIntegrityReviewGate,
    StudioExportIntegrityWorkflow,
    StudioExportIntegrityWorkflowState,
    StudioExportIntegrityWorkflowStatus,
    StudioQtBridge,
    studio_export_integrity_workflow_capability_matrix,
)

from test_v3119_driver_studio_export_audit_console import _bundle


def _runtime():
    bridge = StudioQtBridge()
    bridge.load_bundle(_bundle(), selected_driver_id="SearchPolicyDrivers")
    runtime = bridge.live_panel_runtime(max_events=16)
    runtime.mark_all_dirty(reason="export integrity workflow paint")
    return bridge, runtime


def test_v3120_version():
    assert __version__ == "3.5.3.post1"


def test_export_integrity_workflow_capability_matrix_is_verify_only():
    matrix = studio_export_integrity_workflow_capability_matrix()

    assert matrix["export_integrity_workflow"] is True
    assert matrix["recompute_export_manifest_hash"] is True
    assert matrix["recompute_export_packet_hash"] is True
    assert matrix["compare_export_manifest_hash"] is True
    assert matrix["compare_export_packet_hash"] is True
    assert matrix["compare_expected_manifest_fields"] is True
    assert matrix["progress_export_checkpoints"] is True
    assert matrix["prepare_review_safe_export_gate"] is True
    assert matrix["prepare_export_workflow_hash"] is True
    assert matrix["export_integrity_workflow_is_authority"] is False
    assert matrix["export_integrity_workflow_mutates_backend"] is False
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

    workflow = StudioExportIntegrityWorkflow()
    assert not hasattr(workflow, "approve")
    assert not hasattr(workflow, "sign")
    assert not hasattr(workflow, "activate")


def test_export_integrity_workflow_verifies_packet_preview_hashes_and_checkpoints():
    _bridge, runtime = _runtime()
    state = runtime.export_integrity_workflow().current_state()

    assert isinstance(state, StudioExportIntegrityWorkflowState)
    assert state.ok is True
    assert state.status is StudioExportIntegrityWorkflowStatus.VERIFIED
    assert state.selected_driver_id == "SearchPolicyDrivers"
    assert state.manifest_hash.startswith("sha256:")
    assert state.packet_hash.startswith("sha256:")
    assert state.workflow_hash.startswith("sha256:")
    assert state.comparison.observed_manifest_hash == state.manifest_hash
    assert state.comparison.observed_packet_hash == state.packet_hash
    assert isinstance(state.comparison, StudioExportIntegrityManifestComparison)
    assert isinstance(state.review_gate, StudioExportIntegrityReviewGate)
    assert state.review_gate.ready_for_export_review is True
    assert state.review_gate.authority == "intent_only"
    assert state.blocking_checkpoint_ids == ()
    assert all(isinstance(checkpoint, StudioExportIntegrityCheckpoint) for checkpoint in state.checkpoints)

    rows = {checkpoint.checkpoint_id: checkpoint for checkpoint in state.checkpoints}
    assert rows["hash.manifest_recompute"].status is StudioExportIntegrityCheckpointStatus.VERIFIED
    assert rows["hash.packet_recompute"].status is StudioExportIntegrityCheckpointStatus.VERIFIED
    assert rows["gate.review_safe_handoff"].status is StudioExportIntegrityCheckpointStatus.VERIFIED
    assert state.signal_payload()["capability_matrix"]["mutate_registry"] is False


def test_export_integrity_workflow_accepts_expected_manifest_and_packet_hashes():
    _bridge, runtime = _runtime()
    console = runtime.export_audit_console()
    preview = console.packet_preview()
    state = runtime.export_integrity_workflow().current_state(
        expected_manifest=preview.manifest.as_manifest(include_hash=False),
        expected_manifest_hash=preview.manifest.manifest_hash,
        expected_packet_hash=preview.packet_hash,
    )

    assert state.ok is True
    assert state.status is StudioExportIntegrityWorkflowStatus.VERIFIED
    assert state.comparison.ok is True
    assert state.comparison.expected_manifest_hash == preview.manifest.manifest_hash
    assert state.comparison.expected_packet_hash == preview.packet_hash
    ids = {checkpoint.checkpoint_id for checkpoint in state.checkpoints}
    assert "compare.expected_manifest_hash" in ids
    assert "compare.expected_packet_hash" in ids
    assert state.metrics["expected_manifest_compared"] is True
    assert state.metrics["expected_packet_compared"] is True


def test_export_integrity_workflow_blocks_on_expected_hash_mismatch_without_mutation():
    _bridge, runtime = _runtime()
    bad_hash = "sha256:" + "0" * 64
    state = runtime.export_integrity_workflow().current_state(expected_packet_hash=bad_hash)

    assert state.ok is False
    assert state.status is StudioExportIntegrityWorkflowStatus.MISMATCH
    assert state.review_gate.ready_for_export_review is False
    assert "compare.expected_packet_hash" in state.blocking_checkpoint_ids
    assert state.comparison.expected_packet_hash == bad_hash
    assert state.comparison.observed_packet_hash != bad_hash
    assert state.capability_matrix["mutate_registry"] is False
    assert state.capability_matrix["sign_driver"] is False


def test_export_integrity_workflow_bridge_runtime_and_panel_contracts_are_gui_ready():
    bridge, runtime = _runtime()
    bridge_workflow = bridge.export_integrity_workflow(max_events=16)
    runtime_workflow = runtime.export_integrity_workflow()
    hydrated = bridge.hydrate_panel(StudioPanelKind.EXPORT_INTEGRITY)

    assert isinstance(bridge_workflow.current_state(), StudioExportIntegrityWorkflowState)
    assert isinstance(runtime_workflow.current_state(), StudioExportIntegrityWorkflowState)
    assert bridge.capability_matrix()["create_export_integrity_workflow"] is True
    assert runtime.capability_matrix()["create_export_integrity_workflow"] is True
    assert runtime.capability_matrix()["verify_export_packet_integrity"] is True
    assert hydrated.kind is StudioPanelKind.EXPORT_INTEGRITY
    assert hydrated.cards[0].badges == ("verified",)

from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_interpole_timeline_ring_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_interpole_determinant_vector_report_key,
    csv_interpole_timeline_ring_report_key,
    csv_interpole_timeline_ring_summary,
    import_csv_bytes,
    load_csv_interpole_timeline_ring_report,
    prepare_csv_interpole_timeline_ring,
    validate_csv_interpole_timeline_ring,
)


def _interpole_ring_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b"id,name,score\n1,Ada,99\n2,Grace,98\n",
    *,
    include_scan_artifacts: bool = False,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="interpole_ring.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, include_scan_artifacts=include_scan_artifacts)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    timeline = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    determinants = commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    assert revalidation.ok is True
    assert timeline.ok is True
    assert determinants.ok is True
    return manifest, determinants


def test_version_344_csv_interpole_timeline_ring_mirror():
    assert __version__ == "3.5.3"


def test_csv_interpole_timeline_ring_prepare_builds_no_write_mirror_feedback():
    fs = TDSFileSystem("root")
    manifest, determinants = _interpole_ring_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)
    summary = csv_interpole_timeline_ring_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "ring_ready"
    assert report.mode == "timeline_ring_prepare"
    assert report.source_vector_fingerprint == determinants.vector_fingerprint
    assert report.ring.source_vector_fingerprint == determinants.vector_fingerprint
    assert report.ring.node_count == 6
    assert report.ring.stable_node_count >= 5
    assert report.ring.blocked_node_count == 0
    assert report.ring.drifted_node_count == 0
    assert report.mirror_delta.previous_vector_fingerprint == determinants.vector_fingerprint
    assert report.mirror_delta.current_vector_fingerprint == determinants.vector_fingerprint
    assert report.mirror_delta.inverse_check_passed is True
    assert report.mirror_delta.delta_magnitude == 0.0
    assert "stable_progression" in report.discrete_feedback
    assert "ir_ready" in report.discrete_feedback
    assert report.tds_artifact_writes == 0
    assert report.native_storage_writes is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.determinant_vectoring is True
    assert report.timeline_ring_materialized is True
    assert report.invertible_mirror_feedback is True
    assert report.formal_ir_committed is False
    assert summary["node_count"] == report.node_count
    assert summary["discrete_feedback"] == list(report.discrete_feedback)
    assert after_keys == before_keys


def test_csv_interpole_timeline_ring_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_ring_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)
    loaded = load_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)
    validation = validate_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert committed.status == "ring_committed"
    assert committed.mode == "timeline_ring_commit"
    assert committed.tds_artifact_writes == 1
    assert loaded.report_key == csv_interpole_timeline_ring_report_key(manifest.csv_id)
    assert loaded.ring_fingerprint == committed.ring_fingerprint
    assert loaded.mirror_fingerprint == committed.mirror_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_interpole_timeline_ring_requires_persisted_determinant_vector():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="missing_determinants.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)

    report = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.node_count == 0
    assert any("interpole_determinant_vector_report_unreadable" in error for error in report.errors)
    assert report.native_storage_writes is False
    assert report.formal_ir_committed is False


def test_csv_interpole_timeline_ring_detects_source_drift_before_ring_ready():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_ring_ready_csv(fs, b"a,b\n1,2\n")
    fs.root.write_text(artifact_keys(manifest.csv_id)["raw"], "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "drifted"
    assert report.determinant_validation_status == "drifted"
    assert "drift_confirmed" in report.discrete_feedback
    assert "ir_blocked" in report.discrete_feedback
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False


def test_csv_interpole_timeline_ring_validation_detects_later_ring_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_ring_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)
    key = csv_interpole_timeline_ring_report_key(manifest.csv_id)
    stored = fs.root.read_value(key)
    stored["ring"]["ring_fingerprint"] = "0" * 64
    stored["ring_fingerprint"] = "0" * 64
    fs.root.write_json(key, stored, overwrite=True, provenance="DERIVED")

    validation = validate_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert "interpole_timeline_ring_fingerprint_drift" in validation.errors
    assert validation.native_storage_writes is False


def test_csv_interpole_timeline_ring_is_deterministic():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_ring_ready_csv(fs, b"a,b,c\n1,2,3\n4,5,6\n")

    first = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)
    second = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert first.ok is True
    assert second.ok is True
    assert first.ring_fingerprint == second.ring_fingerprint
    assert first.mirror_fingerprint == second.mirror_fingerprint
    assert [(node.stage_name, node.node_fingerprint, node.feedback_hint) for node in first.ring.nodes] == [
        (node.stage_name, node.node_fingerprint, node.feedback_hint) for node in second.ring.nodes
    ]


def test_csv_interpole_timeline_ring_nodes_are_evidence_neutral():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_ring_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert report.ok is True
    for node in report.ring.nodes:
        assert node.ok is True
        assert node.source_signature_sha256
        assert node.signal_count > 0
        assert 0.0 <= node.magnitude_average <= 1.0
        assert 0.0 <= node.confidence_average <= 1.0
        assert 0.0 <= node.drift_pressure <= 1.0
        assert node.semantic_conclusion is False
        assert node.schema_inference is False
        assert node.type_inference is False
        assert node.entity_inference is False
        assert node.ir_candidate is False
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False


def test_csv_interpole_timeline_ring_mirror_detects_vector_signature_drift():
    fs = TDSFileSystem("root")
    manifest, determinants = _interpole_ring_ready_csv(fs, b"a,b\n1,2\n")
    key = csv_interpole_determinant_vector_report_key(manifest.csv_id)
    stored = fs.root.read_value(key)
    stored["vector"]["vector_fingerprint"] = "f" * 64
    stored["vector_fingerprint"] = "f" * 64
    fs.root.write_json(key, stored, overwrite=True, provenance="DERIVED")

    report = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert determinants.ok is True
    assert report.ok is False
    assert report.status == "drifted"
    assert report.mirror_delta.previous_vector_fingerprint == "f" * 64
    assert report.mirror_delta.current_vector_fingerprint != "f" * 64
    assert "drift_confirmed" in report.discrete_feedback
    assert "ir_blocked" in report.discrete_feedback
    assert any("interpole_determinant_vector_fingerprint_drift" in error for error in report.errors)


def test_csv_interpole_timeline_ring_preserves_optional_scan_boundary():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_ring_ready_csv(fs, b"a,b\n1,2\n", include_scan_artifacts=True)

    report = prepare_csv_interpole_timeline_ring(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.timeline_ring_materialized is True
    assert report.invertible_mirror_feedback is True
    assert report.native_storage_writes is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False

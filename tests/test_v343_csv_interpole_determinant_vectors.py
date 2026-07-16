from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_interpole_determinant_vector_report_key,
    csv_interpole_determinant_vector_summary,
    import_csv_bytes,
    load_csv_interpole_determinant_vector_report,
    prepare_csv_interpole_determinant_vector,
    validate_csv_interpole_determinant_vector,
)


def _interpole_vector_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b"id,name,score\n1,Ada,99\n2,Grace,98\n",
    *,
    include_scan_artifacts: bool = False,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="interpole_vector.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, include_scan_artifacts=include_scan_artifacts)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    timeline = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    assert revalidation.ok is True
    assert timeline.ok is True
    return manifest, timeline


def test_version_343_csv_interpole_determinant_vectors():
    assert __version__ == "3.5.3"


def test_csv_interpole_determinant_prepare_builds_no_write_vector():
    fs = TDSFileSystem("root")
    manifest, timeline = _interpole_vector_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)
    summary = csv_interpole_determinant_vector_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "determinants_ready"
    assert report.mode == "determinant_prepare"
    assert report.source_timeline_fingerprint == timeline.timeline_fingerprint
    assert report.vector.source_timeline_fingerprint == timeline.timeline_fingerprint
    assert report.signal_count >= 12
    assert report.vector.active_signal_count == report.signal_count
    assert report.vector.negative_signal_count == 0
    assert report.vector.wrapped_stage_count == 6
    assert report.vector.stage_order == (
        "evidence_baseline",
        "structure_baseline",
        "canonical_export_baseline",
        "native_storage_commit_baseline",
        "native_revalidation_baseline",
        "ir_readiness_baseline",
    )
    assert report.vector.stability_score > 0.75
    assert report.vector.ir_readiness_score == 1.0
    assert report.tds_artifact_writes == 0
    assert report.native_storage_writes is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.determinant_vectoring is True
    assert report.timeline_ring_materialized is False
    assert report.invertible_mirror_feedback is False
    assert report.formal_ir_committed is False
    assert summary["signal_count"] == report.signal_count
    assert summary["semantic_conclusions"] is False
    assert after_keys == before_keys


def test_csv_interpole_determinant_report_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_vector_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    loaded = load_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    validation = validate_csv_interpole_determinant_vector(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert committed.status == "determinants_committed"
    assert committed.mode == "determinant_commit"
    assert committed.tds_artifact_writes == 1
    assert loaded.report_key == csv_interpole_determinant_vector_report_key(manifest.csv_id)
    assert loaded.vector_fingerprint == committed.vector_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_interpole_determinant_requires_persisted_timeline():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="missing_timeline.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)

    report = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.signal_count == 0
    assert any("interpole_timeline_report_unreadable" in error for error in report.errors)
    assert report.native_storage_writes is False
    assert report.formal_ir_committed is False


def test_csv_interpole_determinant_detects_source_drift_before_vector_ready():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_vector_ready_csv(fs, b"a,b\n1,2\n")
    fs.root.write_text(artifact_keys(manifest.csv_id)["raw"], "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "drifted"
    assert report.timeline_validation_status == "drifted"
    assert any("native_revalidation" in error for error in report.errors)
    assert any(signal.signal_name == "drift_absence_pressure" and signal.magnitude < 1.0 for signal in report.vector.signals)
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False


def test_csv_interpole_determinant_validation_detects_later_vector_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_vector_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    key = csv_interpole_determinant_vector_report_key(manifest.csv_id)
    stored = fs.root.read_value(key)
    stored["vector"]["vector_fingerprint"] = "0" * 64
    stored["vector_fingerprint"] = "0" * 64
    fs.root.write_json(key, stored, overwrite=True, provenance="DERIVED")

    validation = validate_csv_interpole_determinant_vector(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert "interpole_determinant_vector_fingerprint_drift" in validation.errors
    assert validation.native_storage_writes is False


def test_csv_interpole_determinant_vector_is_deterministic():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_vector_ready_csv(fs, b"a,b,c\n1,2,3\n4,5,6\n")

    first = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)
    second = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)

    assert first.ok is True
    assert second.ok is True
    assert first.vector_fingerprint == second.vector_fingerprint
    assert [(signal.signal_name, signal.magnitude, signal.direction) for signal in first.vector.signals] == [
        (signal.signal_name, signal.magnitude, signal.direction) for signal in second.vector.signals
    ]


def test_csv_interpole_determinant_signals_are_evidence_neutral():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_vector_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.vector.composite_signature_sha256 == report.vector.vector_fingerprint
    for signal in report.vector.signals:
        assert signal.ok is True
        assert signal.source_signature_sha256
        assert 0.0 <= signal.magnitude <= 1.0
        assert 0.0 <= signal.confidence <= 1.0
        assert signal.semantic_conclusion is False
        assert signal.schema_inference is False
        assert signal.type_inference is False
        assert signal.entity_inference is False
        assert signal.ir_candidate is False
    assert any(signal.signal_name == "semantic_neutrality_lock" and signal.magnitude == 1.0 for signal in report.vector.signals)


def test_csv_interpole_determinant_preserves_optional_scan_boundary():
    fs = TDSFileSystem("root")
    manifest, _ = _interpole_vector_ready_csv(fs, b"a,b\n1,2\n", include_scan_artifacts=True)

    report = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)
    optional_signal = next(signal for signal in report.vector.signals if signal.signal_name == "optional_scan_skip_pressure")

    assert report.ok is True
    assert optional_signal.metrics["skipped_optional_count"] == 3
    assert optional_signal.direction == "neutral"
    assert report.timeline_ring_materialized is False
    assert report.invertible_mirror_feedback is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False


def test_csv_interpole_determinant_stage_wrapping_links_back_to_timeline_signatures():
    fs = TDSFileSystem("root")
    manifest, timeline = _interpole_vector_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_interpole_determinant_vector(fs.root, manifest.csv_id)
    timeline_signature_by_stage = {stage.stage_name: stage.signature.signature_sha256 for stage in timeline.timeline.stages}

    assert report.ok is True
    assert set(signal.source_stage_name for signal in report.vector.signals) == set(timeline_signature_by_stage)
    for signal in report.vector.signals:
        assert signal.source_signature_sha256 == timeline_signature_by_stage[signal.source_stage_name]

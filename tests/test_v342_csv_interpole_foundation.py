from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_interpole_timeline_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_interpole_timeline_report_key,
    csv_interpole_timeline_summary,
    import_csv_bytes,
    load_csv_interpole_timeline_report,
    prepare_csv_interpole_timeline,
    validate_csv_interpole_timeline,
)


def _interpole_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b"id,name\n1,Ada\n2,Grace\n",
    *,
    include_scan_artifacts: bool = False,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="interpole.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, include_scan_artifacts=include_scan_artifacts)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    assert revalidation.ok is True
    return manifest, native_commit, revalidation


def test_version_342_csv_interpole_foundation():
    assert __version__ == "3.5.3"


def test_csv_interpole_prepare_builds_no_write_foundation_timeline():
    fs = TDSFileSystem("root")
    manifest, _, revalidation = _interpole_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_interpole_timeline(fs.root, manifest.csv_id)
    summary = csv_interpole_timeline_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "interpole_ready"
    assert report.mode == "timeline_prepare"
    assert report.stage_count == 6
    assert report.ready_stage_count == 6
    assert report.timeline.stage_count == 6
    assert [stage.stage_name for stage in report.timeline.stages] == [
        "evidence_baseline",
        "structure_baseline",
        "canonical_export_baseline",
        "native_storage_commit_baseline",
        "native_revalidation_baseline",
        "ir_readiness_baseline",
    ]
    assert report.source_revalidation_fingerprint == revalidation.revalidation_fingerprint
    assert report.tds_artifact_writes == 0
    assert report.native_storage_writes is False
    assert report.native_c_engine_changed is False
    assert report.native_csv_kernel_used is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.determinant_vectoring is False
    assert report.timeline_ring_materialized is False
    assert report.invertible_mirror_feedback is False
    assert report.formal_ir_committed is False
    assert summary["stage_count"] == 6
    assert summary["semantic_conclusions"] is False
    assert after_keys == before_keys


def test_csv_interpole_report_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _, _ = _interpole_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    loaded = load_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    validation = validate_csv_interpole_timeline(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert committed.status == "timeline_committed"
    assert committed.mode == "timeline_commit"
    assert committed.tds_artifact_writes == 1
    assert loaded.report_key == csv_interpole_timeline_report_key(manifest.csv_id)
    assert loaded.timeline_fingerprint == committed.timeline_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_interpole_requires_persisted_native_revalidation_guard():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="missing_revalidation.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)

    report = prepare_csv_interpole_timeline(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.stage_count == 0
    assert any("native_storage_revalidation_report_unreadable" in error for error in report.errors)
    assert report.native_storage_writes is False
    assert report.formal_ir_committed is False


def test_csv_interpole_detects_source_drift_before_ir_readiness():
    fs = TDSFileSystem("root")
    manifest, _, _ = _interpole_ready_csv(fs, b"a,b\n1,2\n")
    fs.root.write_text(artifact_keys(manifest.csv_id)["raw"], "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = prepare_csv_interpole_timeline(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "drifted"
    assert report.native_revalidation_status == "drifted"
    assert any("native_revalidation" in error for error in report.errors)
    assert any(stage.stage_name == "native_revalidation_baseline" and stage.status == "drifted" for stage in report.timeline.stages)
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False


def test_csv_interpole_validation_detects_later_storage_drift():
    fs = TDSFileSystem("root")
    manifest, native_commit, _ = _interpole_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    raw_entry = next(entry for entry in native_commit.entries if entry.artifact_name == "raw")
    fs.root.write_text(raw_entry.storage_entry_key, "a,b\n9,9\n", overwrite=True, provenance="REAL")

    validation = validate_csv_interpole_timeline(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert any("interpole_timeline_fingerprint_drift" == error for error in validation.errors)
    assert any("native_revalidation" in error for error in validation.errors)
    assert validation.native_storage_writes is False


def test_csv_interpole_timeline_fingerprint_is_deterministic():
    fs = TDSFileSystem("root")
    manifest, _, _ = _interpole_ready_csv(fs, b"a,b\n1,2\n")

    first = prepare_csv_interpole_timeline(fs.root, manifest.csv_id)
    second = prepare_csv_interpole_timeline(fs.root, manifest.csv_id)

    assert first.ok is True
    assert second.ok is True
    assert first.timeline_fingerprint == second.timeline_fingerprint
    assert [stage.signature.signature_sha256 for stage in first.timeline.stages] == [
        stage.signature.signature_sha256 for stage in second.timeline.stages
    ]


def test_csv_interpole_preserves_optional_scan_skip_readiness():
    fs = TDSFileSystem("root")
    manifest, _, _ = _interpole_ready_csv(fs, b"a,b\n1,2\n", include_scan_artifacts=True)

    report = prepare_csv_interpole_timeline(fs.root, manifest.csv_id)
    revalidation_stage = next(stage for stage in report.timeline.stages if stage.stage_name == "native_revalidation_baseline")

    assert report.ok is True
    assert revalidation_stage.signature.metrics["skipped_optional_count"] == 3
    assert report.stage_count == 6
    assert report.timeline_ring_materialized is False
    assert report.invertible_mirror_feedback is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False


def test_csv_interpole_stage_signatures_are_evidence_neutral():
    fs = TDSFileSystem("root")
    manifest, _, _ = _interpole_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_interpole_timeline(fs.root, manifest.csv_id)

    assert report.ok is True
    for stage in report.timeline.stages:
        assert stage.ok is True
        assert stage.signature.signature_sha256
        assert stage.signature.semantic_conclusion is False
        assert stage.signature.determinant_vector is False
        assert stage.signature.ir_candidate is False
    ir_stage = next(stage for stage in report.timeline.stages if stage.stage_name == "ir_readiness_baseline")
    assert ir_stage.signature.metrics["ready_for_future_determinants"] is True
    assert ir_stage.signature.metrics["formal_ir_committed"] is False

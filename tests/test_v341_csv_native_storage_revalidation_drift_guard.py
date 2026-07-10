from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_native_storage_revalidation_report_key,
    csv_native_storage_revalidation_summary,
    csv_storage_adapter_replay_report_key,
    import_csv_bytes,
    load_csv_native_storage_revalidation_report,
    prepare_csv_native_storage_revalidation,
    validate_csv_native_storage_revalidation,
)


def _native_ready_csv(fs: TDSFileSystem, payload: bytes = b"id,name\n1,Ada\n2,Grace\n", *, include_scan_artifacts: bool = False):
    manifest = import_csv_bytes(fs.root, payload, source_name="native_revalidation.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, include_scan_artifacts=include_scan_artifacts)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    return manifest, native_commit


def test_version_341_csv_native_storage_revalidation_drift_guard():
    assert __version__ == "3.5.2"


def test_csv_native_storage_revalidation_clean_snapshot_has_no_storage_writes():
    fs = TDSFileSystem("root")
    manifest, native_commit = _native_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_native_storage_revalidation(fs.root, manifest.csv_id)
    summary = csv_native_storage_revalidation_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "revalidated"
    assert report.mode == "revalidation"
    assert report.entry_count == native_commit.entry_count == 6
    assert report.verified_count == 6
    assert report.source_drift_count == 0
    assert report.storage_drift_count == 0
    assert report.proof_drift_count == 0
    assert report.native_storage_writes is False
    assert report.native_c_engine_changed is False
    assert report.native_csv_kernel_used is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert summary["verified_count"] == 6
    assert after_keys == before_keys


def test_csv_native_storage_revalidation_report_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _ = _native_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    loaded = load_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    validation = validate_csv_native_storage_revalidation(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert committed.mode == "revalidation_commit"
    assert committed.tds_artifact_writes == 1
    assert committed.native_storage_writes is False
    assert loaded.report_key == csv_native_storage_revalidation_report_key(manifest.csv_id)
    assert loaded.revalidation_fingerprint == committed.revalidation_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_native_storage_revalidation_detects_source_artifact_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _native_ready_csv(fs, b"a,b\n1,2\n")
    fs.root.write_text(artifact_keys(manifest.csv_id)["raw"], "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = prepare_csv_native_storage_revalidation(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "drifted"
    assert report.source_drift_count >= 1
    assert any(entry.artifact_name == "raw" and entry.status == "source_drift" for entry in report.entries)
    assert any("source_drift" in error for error in report.errors)
    assert report.native_storage_writes is False


def test_csv_native_storage_revalidation_detects_storage_payload_drift():
    fs = TDSFileSystem("root")
    manifest, native_commit = _native_ready_csv(fs, b"a,b\n1,2\n")
    raw_entry = next(entry for entry in native_commit.entries if entry.artifact_name == "raw")
    fs.root.write_text(raw_entry.storage_entry_key, "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = prepare_csv_native_storage_revalidation(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "drifted"
    assert report.storage_drift_count == 1
    assert any(entry.artifact_name == "raw" and entry.status == "storage_drift" for entry in report.entries)
    assert any("storage_drift" in error for error in report.errors)


def test_csv_native_storage_revalidation_detects_replay_proof_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _native_ready_csv(fs, b"a,b\n1,2\n")
    replay_key = csv_storage_adapter_replay_report_key(manifest.csv_id)
    replay_payload = dict(fs.root.read_value(replay_key))
    replay_payload["transaction_id"] = "csv-replay-proof-drift"
    fs.root.write_json(replay_key, replay_payload, overwrite=True, provenance="DERIVED")

    report = prepare_csv_native_storage_revalidation(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "drifted"
    assert report.proof_drift_count >= 1
    assert any(entry.status == "proof_drift" for entry in report.entries if entry.status != "skipped_optional")
    assert any("replay_validation" in error for error in report.errors)


def test_csv_native_storage_revalidation_preserves_optional_scan_skips():
    fs = TDSFileSystem("root")
    manifest, _ = _native_ready_csv(fs, b"a,b\n1,2\n", include_scan_artifacts=True)

    report = prepare_csv_native_storage_revalidation(fs.root, manifest.csv_id)
    skipped = {entry.artifact_name for entry in report.entries if entry.status == "skipped_optional"}

    assert report.ok is True
    assert report.entry_count == 9
    assert report.verified_count == 6
    assert report.skipped_optional_count == 3
    assert skipped == {"scan_profile", "row_anchor_profile", "scan_materialization_report"}
    assert report.per_row_writes is False
    assert report.per_cell_writes is False


def test_csv_native_storage_revalidation_validation_detects_later_drift():
    fs = TDSFileSystem("root")
    manifest, native_commit = _native_ready_csv(fs, b"a,b\n1,2\n")
    committed_revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    raw_entry = next(entry for entry in native_commit.entries if entry.artifact_name == "raw")
    fs.root.write_text(raw_entry.storage_entry_key, "a,b\n9,9\n", overwrite=True, provenance="REAL")

    validation = validate_csv_native_storage_revalidation(fs.root, manifest.csv_id)

    assert committed_revalidation.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert validation.storage_drift_count == 1
    assert any("revalidation_fingerprint_drift" == error for error in validation.errors)


def test_csv_native_storage_revalidation_requires_native_storage_commit_report():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="no_native_commit.csv")

    report = prepare_csv_native_storage_revalidation(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.entry_count == 0
    assert any("native_storage_commit_report_unreadable" in error for error in report.errors)
    assert report.native_storage_writes is False

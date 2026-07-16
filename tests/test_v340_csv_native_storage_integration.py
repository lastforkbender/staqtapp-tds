from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_native_storage_artifacts,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_native_storage_commit_report_key,
    csv_native_storage_commit_summary,
    import_csv_bytes,
    load_csv_native_storage_commit_report,
    validate_csv_native_storage_commit,
)


def _ready_csv(fs: TDSFileSystem, payload: bytes = b"id,name\n1,Ada\n2,Grace\n"):
    manifest = import_csv_bytes(fs.root, payload, source_name="native_storage.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    return manifest


def test_version_340_csv_native_storage_integration():
    assert __version__ == "3.5.3"


def test_csv_native_storage_commit_requires_persisted_replay_proof():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,name\n1,Ada\n", source_name="no_native_replay.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)

    report = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.mode == "invalid"
    assert report.entry_count == 0
    assert report.native_storage_writes is False
    assert any("replay_report_unreadable" in error for error in report.errors)


def test_csv_native_storage_commit_writes_fixed_artifact_set_only():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    validation = validate_csv_native_storage_commit(fs.root, manifest.csv_id)
    summary = csv_native_storage_commit_summary(report)
    after_keys = set(fs.root._entries.keys())
    added_keys = after_keys - before_keys

    assert report.ok is True
    assert report.status == "native_storage_committed"
    assert report.mode == "native_storage_commit"
    assert report.entry_count == 6
    assert report.committed_count == 6
    assert report.native_storage_entry_writes == 6
    assert report.tds_artifact_writes == 7
    assert report.native_storage_writes is True
    assert report.native_c_engine_changed is False
    assert report.native_csv_kernel_used is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert summary["storage_payload_commits"] == 6
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"
    assert {entry.artifact_name for entry in report.entries} == {
        "raw",
        "dialect",
        "row_offsets",
        "content_hashes",
        "manifest",
        "import_report",
    }
    assert len(added_keys) == 7
    assert csv_native_storage_commit_report_key(manifest.csv_id) in added_keys
    assert all(
        entry.storage_entry_key in added_keys
        for entry in report.entries
        if entry.status == "committed"
    )


def test_csv_native_storage_commit_preserves_payload_hashes_and_kinds():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs, b"a,b\n1,2\n")

    report = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    by_name = {entry.artifact_name: entry for entry in report.entries}
    raw_storage_value = fs.root.read_value(by_name["raw"].storage_entry_key)
    raw_metadata = fs.root.entry_metadata(by_name["raw"].storage_entry_key)
    manifest_metadata = fs.root.entry_metadata(by_name["manifest"].storage_entry_key)

    assert report.ok is True
    assert by_name["raw"].payload_sha256 == manifest.raw_sha256
    assert by_name["raw"].storage_payload_sha256 == manifest.raw_sha256
    assert raw_storage_value == "a,b\n1,2\n"
    assert raw_metadata["payload_kind"] == "TEXT_UTF8"
    assert manifest_metadata["payload_kind"] == "JSON_UTF8"


def test_csv_native_storage_commit_is_idempotent_when_payloads_already_present():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs, b"a,b\n1,2\n")
    first = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    before_count = len(fs.root._entries)

    second = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id, overwrite=True)
    after_count = len(fs.root._entries)

    assert first.ok is True
    assert second.ok is True
    assert second.committed_count == 6
    assert second.native_storage_entry_writes == 6
    assert after_count == before_count


def test_csv_native_storage_validation_detects_storage_payload_drift():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    raw_entry = next(entry for entry in committed.entries if entry.artifact_name == "raw")
    fs.root.write_text(raw_entry.storage_entry_key, "a,b\n9,9\n", overwrite=True, provenance="REAL")

    validation = validate_csv_native_storage_commit(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert any("storage_payload_hash_drift:raw" == error for error in validation.errors)


def test_csv_native_storage_commit_rejects_source_drift_before_writes():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs, b"a,b\n1,2\n")
    before_count = len(fs.root._entries)
    fs.root.write_text(artifact_keys(manifest.csv_id)["raw"], "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    after_count = len(fs.root._entries)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.entry_count == 0
    assert report.native_storage_writes is False
    assert after_count == before_count
    assert any("payload_hash_drift:raw" in error for error in report.errors)


def test_csv_native_storage_commit_skips_optional_scan_artifacts_without_row_writes():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="native_optional.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, include_scan_artifacts=True)
    commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)

    report = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    skipped = {entry.artifact_name for entry in report.entries if entry.status == "skipped_optional"}

    assert report.ok is True
    assert report.entry_count == 9
    assert report.committed_count == 6
    assert report.skipped_optional_count == 3
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert skipped == {"scan_profile", "row_anchor_profile", "scan_materialization_report"}


def test_csv_native_storage_commit_report_can_be_loaded():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    loaded = load_csv_native_storage_commit_report(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert loaded.status == "native_storage_committed"
    assert loaded.report_key == csv_native_storage_commit_report_key(manifest.csv_id)
    assert loaded.committed_count == committed.committed_count
    assert loaded.transaction_id == committed.transaction_id

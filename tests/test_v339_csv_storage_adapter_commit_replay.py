from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_storage_adapter_replay_report_key,
    csv_storage_adapter_replay_summary,
    import_csv_bytes,
    load_csv_storage_adapter_replay_report,
    prepare_csv_storage_adapter_replay,
    validate_csv_storage_adapter_replay,
)


def test_version_339_csv_storage_adapter_commit_replay():
    assert __version__ == "3.5.3.post1"


def test_csv_storage_adapter_replay_requires_binding_contract():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,name\n1,Ada\n", source_name="no_replay_commit.csv")

    report = prepare_csv_storage_adapter_replay(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.mode == "invalid"
    assert report.step_count == 0
    assert any("commit_report_unreadable" in error for error in report.errors)


def test_csv_storage_adapter_replay_simulates_core_commit_sequence_without_writes():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,note\n1,alpha\n2,beta\n", source_name="replay.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    before_count = len(fs.root._entries)

    report = prepare_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    validation = validate_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    summary = csv_storage_adapter_replay_summary(report)
    after_count = len(fs.root._entries)

    assert committed.ok is True
    assert report.ok is True
    assert report.status == "simulated"
    assert report.mode == "commit_simulation"
    assert report.binding_validation_status == "ready"
    assert report.binding_count == 6
    assert report.staged_count == 6
    assert report.committed_count == 6
    assert report.simulated_payload_commits == 6
    assert report.failed_hash_check_count == 0
    assert report.failed_binding_validation_count == 0
    assert report.native_storage_writes is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.semantic_reasoning is False
    assert validation.ok is True
    assert validation.mode == "validation"
    assert summary["ok"] is True
    assert summary["simulated_payload_commits"] == 6
    assert after_count == before_count


def test_csv_storage_adapter_replay_preserves_deterministic_ordering():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="ordered_replay.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)

    first = prepare_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    second = prepare_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    commit_steps = [step for step in first.replay_steps if step.operation == "commit_payload"]

    assert first.replay_fingerprint == second.replay_fingerprint
    assert first.transaction_id == second.transaction_id
    assert [step.artifact_name for step in commit_steps] == [
        "raw",
        "dialect",
        "row_offsets",
        "content_hashes",
        "manifest",
        "import_report",
    ]
    assert [step.step_index for step in first.replay_steps] == list(range(1, first.step_count + 1))


def test_csv_storage_adapter_replay_skips_optional_scan_artifacts_without_failure():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="optional_replay.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, include_scan_artifacts=True)

    report = prepare_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    skipped = [step for step in report.replay_steps if step.status == "skipped_optional"]

    assert committed.ok is True
    assert report.ok is True
    assert report.status == "simulated"
    assert report.binding_count == 9
    assert report.committed_count == 6
    assert report.skipped_optional_count == 3
    assert {step.artifact_name for step in skipped} == {
        "scan_profile",
        "row_anchor_profile",
        "scan_materialization_report",
    }
    assert report.failed_hash_check_count == 0
    assert report.failed_binding_validation_count == 0


def test_csv_storage_adapter_replay_detects_hash_drift_before_simulated_commit():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="drift_replay.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    fs.root.write_text(artifact_keys(manifest.csv_id)["raw"], "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = prepare_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    failed = [step for step in report.replay_steps if step.status == "failed_hash_check"]

    assert committed.ok is True
    assert report.ok is False
    assert report.status == "invalid"
    assert report.failed_hash_check_count == 1
    assert failed[0].artifact_name == "raw"
    assert failed[0].operation == "verify_payload_hash"
    assert any("failed_hash_check" in error for error in report.errors)
    assert report.native_storage_writes is False


def test_csv_storage_adapter_replay_detects_missing_required_binding():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="missing_replay.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    fs.root.delete_entry(artifact_keys(manifest.csv_id)["row_offsets"])

    report = prepare_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    failed = [step for step in report.replay_steps if step.status == "failed_binding_validation"]

    assert committed.ok is True
    assert report.ok is False
    assert report.status == "invalid"
    assert report.failed_binding_validation_count >= 1
    assert any(step.artifact_name == "row_offsets" for step in failed)
    assert any("failed_binding_validation" in error for error in report.errors)


def test_csv_storage_adapter_replay_report_can_be_persisted_and_validated():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="persisted_replay.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    before_count = len(fs.root._entries)

    committed = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    loaded = load_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    validation = validate_csv_storage_adapter_replay(fs.root, manifest.csv_id)
    after_count = len(fs.root._entries)

    assert committed.ok is True
    assert committed.status == "replay_committed"
    assert committed.mode == "replay_report_commit"
    assert committed.report_key == csv_storage_adapter_replay_report_key(manifest.csv_id)
    assert committed.tds_artifact_writes == 1
    assert loaded.replay_fingerprint == committed.replay_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"
    assert after_count == before_count + 1


def test_csv_storage_adapter_replay_validation_detects_persisted_replay_drift():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="persisted_replay_drift.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    committed = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)

    altered = committed.to_dict()
    altered["replay_fingerprint"] = "0" * 64
    fs.root.write_json(csv_storage_adapter_replay_report_key(manifest.csv_id), altered, overwrite=True, provenance="DERIVED")

    validation = validate_csv_storage_adapter_replay(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert "replay_fingerprint_drift" in validation.errors

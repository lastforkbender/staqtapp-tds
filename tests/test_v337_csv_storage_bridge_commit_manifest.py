from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_storage_bridge_manifest,
    csv_storage_bridge_commit_report_key,
    csv_storage_bridge_commit_summary,
    import_csv_bytes,
    load_csv_storage_bridge_commit_report,
    materialize_csv_scan_artifacts,
    prepare_csv_storage_bridge_commit,
    validate_csv_storage_bridge_commit,
)


def test_version_337_csv_storage_bridge_commit_manifest():
    assert __version__ == "3.5.3"


def test_csv_storage_bridge_prepare_is_dry_run_and_writes_nothing():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,note\n1,alpha\n2,beta\n", source_name="dry_run.csv")

    prepared = prepare_csv_storage_bridge_commit(fs.root, manifest.csv_id)
    summary = csv_storage_bridge_commit_summary(prepared)

    assert prepared.ok is True
    assert prepared.status == "ready"
    assert prepared.mode == "dry_run"
    assert prepared.entry_count == 6
    assert prepared.committed_count == 0
    assert len(prepared.payload_hashes) == 6
    assert prepared.payload_hashes["raw"] == manifest.raw_sha256
    assert prepared.per_row_writes is False
    assert prepared.per_cell_writes is False
    assert prepared.native_storage_hot_path_touched is False
    assert prepared.semantic_reasoning is False
    assert summary["ok"] is True
    assert summary["mode"] == "dry_run"
    try:
        fs.root.read_value(csv_storage_bridge_commit_report_key(manifest.csv_id))
    except KeyError:
        pass
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("dry-run prepare unexpectedly wrote a commit report")


def test_csv_storage_bridge_commit_persists_derived_manifest_and_validates():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,note\n1,alpha\n2,beta\n", source_name="commit.csv")

    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    loaded = load_csv_storage_bridge_commit_report(fs.root, manifest.csv_id)
    validation = validate_csv_storage_bridge_commit(fs.root, manifest.csv_id)
    metadata = fs.root.entry_metadata(csv_storage_bridge_commit_report_key(manifest.csv_id))

    assert committed.ok is True
    assert committed.status == "committed"
    assert committed.mode == "manifest_commit"
    assert committed.committed_count == 6
    assert loaded.status == "committed"
    assert loaded.payload_hashes == committed.payload_hashes
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"
    assert metadata["payload_kind"] == "JSON_UTF8"
    assert metadata["provenance"]["provenance"] == "DERIVED"


def test_csv_storage_bridge_commit_can_require_scan_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b'a,b\n1,"two\nlines"\n2,ok\n', source_name="scan_commit.csv")
    materialized = materialize_csv_scan_artifacts(fs.root, manifest.csv_id, include_row_anchors=True, chunk_size=4)

    committed = commit_csv_storage_bridge_manifest(
        fs.root,
        manifest.csv_id,
        require_scan_artifacts=True,
        chunk_size=4,
    )
    validation = validate_csv_storage_bridge_commit(fs.root, manifest.csv_id, chunk_size=4)

    assert materialized.ok is True
    assert committed.ok is True
    assert committed.entry_count == 9
    assert committed.optional_count == 3
    assert committed.scan_validation_status == "valid"
    assert set(committed.payload_hashes) == {
        "raw",
        "dialect",
        "row_offsets",
        "content_hashes",
        "manifest",
        "import_report",
        "scan_profile",
        "row_anchor_profile",
        "scan_materialization_report",
    }
    assert validation.ok is True
    assert validation.status == "valid"


def test_csv_storage_bridge_commit_fails_closed_when_core_preflight_is_invalid():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="invalid_commit.csv")
    fs.root.delete_entry(artifact_keys(manifest.csv_id)["row_offsets"])

    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)

    assert committed.ok is False
    assert committed.status == "invalid"
    assert committed.preflight_status in {"partial", "invalid"}
    assert any("row_offsets" in error for error in committed.errors)
    try:
        fs.root.read_value(csv_storage_bridge_commit_report_key(manifest.csv_id))
    except KeyError:
        pass
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("invalid preflight unexpectedly wrote a commit report")


def test_csv_storage_bridge_commit_rejects_duplicate_report_without_overwrite():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="duplicate_commit.csv")

    first = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    second = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    third = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, overwrite=True)

    assert first.ok is True
    assert second.ok is False
    assert second.status == "invalid"
    assert any("commit_report_write_failed" in error for error in second.errors)
    assert third.ok is True
    assert third.status == "committed"


def test_csv_storage_bridge_commit_validation_detects_report_hash_drift():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="drift_commit.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)

    altered = committed.to_dict()
    altered["payload_hashes"]["raw"] = "0" * 64
    fs.root.write_json(csv_storage_bridge_commit_report_key(manifest.csv_id), altered, overwrite=True, provenance="DERIVED")

    validation = validate_csv_storage_bridge_commit(fs.root, manifest.csv_id)

    assert validation.ok is False
    assert validation.drifted is True
    assert validation.status == "drifted"
    assert "payload_hash_drift:raw" in validation.errors

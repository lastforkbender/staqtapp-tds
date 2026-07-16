from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_storage_bridge_manifest,
    csv_storage_adapter_binding_summary,
    csv_storage_bridge_commit_report_key,
    import_csv_bytes,
    prepare_csv_storage_adapter_binding,
    validate_csv_storage_adapter_binding,
)


def test_version_338_csv_storage_adapter_binding_contract():
    assert __version__ == "3.5.3.post1"


def test_csv_storage_adapter_binding_requires_committed_bridge_manifest():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,name\n1,Ada\n", source_name="no_commit.csv")

    report = prepare_csv_storage_adapter_binding(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.mode == "invalid"
    assert report.binding_count == 0
    assert any(error.startswith("commit_report_unreadable:") for error in report.errors)


def test_csv_storage_adapter_binding_dry_run_resolves_core_bindings_without_writes():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,note\n1,alpha\n2,beta\n", source_name="binding.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    before_count = len(fs.root._entries)  # dry-run guard: no new TDS entry should be created

    report = prepare_csv_storage_adapter_binding(fs.root, manifest.csv_id)
    validation = validate_csv_storage_adapter_binding(fs.root, manifest.csv_id)
    summary = csv_storage_adapter_binding_summary(report)
    after_count = len(fs.root._entries)
    raw_binding = next(binding for binding in report.bindings if binding.artifact_name == "raw")

    assert committed.ok is True
    assert report.ok is True
    assert report.status == "ready"
    assert report.mode == "dry_run"
    assert report.binding_count == 6
    assert report.ready_count == 6
    assert report.bindable_count == 6
    assert report.optional_missing_count == 0
    assert raw_binding.status == "ready"
    assert raw_binding.artifact_key == artifact_keys(manifest.csv_id)["raw"]
    assert raw_binding.storage_entry_key == f"csv_storage::{manifest.csv_id}::raw"
    assert raw_binding.stored_payload_sha256 == manifest.raw_sha256
    assert raw_binding.current_payload_sha256 == manifest.raw_sha256
    assert validation.ok is True
    assert validation.mode == "validation"
    assert summary["ok"] is True
    assert summary["bindable_count"] == 6
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.semantic_reasoning is False
    assert after_count == before_count


def test_csv_storage_adapter_binding_keeps_missing_optional_scan_artifacts_nonfatal():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="optional_scan_binding.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id, include_scan_artifacts=True)

    report = prepare_csv_storage_adapter_binding(fs.root, manifest.csv_id)
    optional_statuses = {
        binding.artifact_name: binding.status
        for binding in report.bindings
        if binding.artifact_name in {"scan_profile", "row_anchor_profile", "scan_materialization_report"}
    }

    assert committed.ok is True
    assert report.ok is True
    assert report.status == "ready"
    assert report.binding_count == 9
    assert report.ready_count == 6
    assert report.optional_missing_count == 3
    assert report.missing_count == 0
    assert report.drifted_count == 0
    assert report.rejected_count == 0
    assert set(optional_statuses.values()) == {"optional_missing"}
    assert any("optional_missing" in warning for warning in report.warnings)


def test_csv_storage_adapter_binding_detects_payload_hash_drift_before_native_commit():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="hash_drift_binding.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    fs.root.write_text(artifact_keys(manifest.csv_id)["raw"], "a,b\n9,9\n", overwrite=True, provenance="REAL")

    report = prepare_csv_storage_adapter_binding(fs.root, manifest.csv_id)
    raw_binding = next(binding for binding in report.bindings if binding.artifact_name == "raw")

    assert committed.ok is True
    assert report.ok is False
    assert report.status == "invalid"
    assert report.drifted_count >= 1
    assert raw_binding.status == "drifted"
    assert raw_binding.error == "payload_hash_drift"
    assert raw_binding.stored_payload_sha256 == manifest.raw_sha256
    assert raw_binding.current_payload_sha256 != manifest.raw_sha256
    assert any("binding:raw:drifted:payload_hash_drift" in error for error in report.errors)
    assert report.native_storage_hot_path_touched is False


def test_csv_storage_adapter_binding_detects_missing_committed_artifact():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="missing_binding.csv")
    committed = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    fs.root.delete_entry(artifact_keys(manifest.csv_id)["row_offsets"])

    report = prepare_csv_storage_adapter_binding(fs.root, manifest.csv_id)
    row_offsets = next(binding for binding in report.bindings if binding.artifact_name == "row_offsets")

    assert committed.ok is True
    assert report.ok is False
    assert report.status == "invalid"
    assert report.missing_count >= 1
    assert row_offsets.status == "missing"
    assert row_offsets.required is True
    assert "missing_or_unreadable" in row_offsets.error
    assert any("binding:row_offsets:missing" in error for error in report.errors)


def test_csv_storage_adapter_binding_rejects_noncommitted_source_report():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="noncommitted_binding.csv")
    prepared = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    altered = prepared.to_dict()
    altered["status"] = "ready"
    fs.root.write_json(csv_storage_bridge_commit_report_key(manifest.csv_id), altered, overwrite=True, provenance="DERIVED")

    report = prepare_csv_storage_adapter_binding(fs.root, manifest.csv_id)

    assert prepared.ok is True
    assert report.ok is False
    assert report.status == "invalid"
    assert any(error == "stored_report_not_committed:ready" for error in report.errors)
    assert report.ready_count == 6

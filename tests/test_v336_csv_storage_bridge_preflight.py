from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    csv_storage_bridge_plan,
    csv_storage_bridge_preflight_summary,
    import_csv_bytes,
    materialize_csv_scan_artifacts,
    validate_csv_storage_bridge_preflight,
)


def test_version_336_csv_storage_bridge_preflight():
    assert __version__ == "3.5.3"


def test_csv_storage_bridge_plan_is_six_core_artifacts_by_default():
    plan = csv_storage_bridge_plan("dataset_01")

    assert len(plan) == 6
    assert [entry.artifact_name for entry in plan] == [
        "raw",
        "dialect",
        "row_offsets",
        "content_hashes",
        "manifest",
        "import_report",
    ]
    assert plan[0].expected_payload_kind == "TEXT_UTF8"
    assert plan[0].expected_provenance == "REAL"
    assert all(entry.required for entry in plan)
    assert all(entry.expected_payload_kind == "JSON_UTF8" for entry in plan[1:])
    assert all(entry.expected_provenance == "DERIVED" for entry in plan[1:])


def test_csv_storage_bridge_preflight_ready_for_core_import_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,note\n1,alpha\n2,beta\n", source_name="bridge.csv")

    report = validate_csv_storage_bridge_preflight(fs.root, manifest.csv_id)
    summary = csv_storage_bridge_preflight_summary(report)

    assert report.ok is True
    assert report.status == "ready"
    assert report.entry_count == 6
    assert report.required_count == 6
    assert report.present_required_count == 6
    assert report.optional_count == 0
    assert report.artifact_validation_status == "valid"
    assert report.security_status == "valid"
    assert report.scan_validation_status == "not_required"
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.semantic_reasoning is False
    assert summary["ok"] is True
    assert summary["entry_count"] == 6
    raw_entry = next(entry for entry in report.entries if entry.artifact_name == "raw")
    assert raw_entry.payload_kind == "TEXT_UTF8"
    assert raw_entry.payload_sha256 == manifest.raw_sha256
    assert all(entry.ok for entry in report.entries)


def test_csv_storage_bridge_preflight_can_include_optional_scan_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b'a,b\n1,"two\nlines"\n2,ok\n', source_name="bridge_scan.csv")
    materialized = materialize_csv_scan_artifacts(fs.root, manifest.csv_id, include_row_anchors=True, chunk_size=4)

    report = validate_csv_storage_bridge_preflight(
        fs.root,
        manifest.csv_id,
        include_scan_artifacts=True,
        require_scan_artifacts=True,
        chunk_size=4,
    )

    assert materialized.ok is True
    assert report.ok is True
    assert report.status == "ready"
    assert report.entry_count == 9
    assert report.optional_count == 3
    assert report.present_optional_count == 3
    assert report.scan_validation_status == "valid"
    assert not report.missing_optional_artifacts
    assert {entry.artifact_name for entry in report.entries if not entry.required} == {
        "scan_profile",
        "row_anchor_profile",
        "scan_materialization_report",
    }


def test_csv_storage_bridge_preflight_warns_for_missing_optional_scan_artifacts_when_not_required():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="no_scan.csv")

    report = validate_csv_storage_bridge_preflight(fs.root, manifest.csv_id, include_scan_artifacts=True)

    assert report.ok is True
    assert report.status == "ready"
    assert report.optional_count == 3
    assert report.present_optional_count == 0
    assert set(report.missing_optional_artifacts) == {
        "scan_profile",
        "row_anchor_profile",
        "scan_materialization_report",
    }
    assert any(warning.startswith("optional_bridge_entry:scan_profile:") for warning in report.warnings)


def test_csv_storage_bridge_preflight_fails_when_required_scan_artifacts_missing():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="require_scan.csv")

    report = validate_csv_storage_bridge_preflight(fs.root, manifest.csv_id, require_scan_artifacts=True)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.scan_validation_status == "invalid"
    assert set(report.missing_optional_artifacts) == {
        "scan_profile",
        "row_anchor_profile",
        "scan_materialization_report",
    }
    assert any(error.startswith("scan_validation_unreadable:") for error in report.errors)
    assert any(error.startswith("bridge_entry:scan_profile:") for error in report.errors)


def test_csv_storage_bridge_preflight_fails_closed_for_partial_core_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="partial_bridge.csv")
    fs.root.delete_entry(artifact_keys(manifest.csv_id)["row_offsets"])

    report = validate_csv_storage_bridge_preflight(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status in {"partial", "invalid"}
    assert "row_offsets" in report.missing_required_artifacts
    assert any("row_offsets" in error for error in report.errors)

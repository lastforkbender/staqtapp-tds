from __future__ import annotations

import pytest

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    csv_scan_artifact_keys,
    import_csv_bytes,
    is_safe_csv_id,
    materialize_csv_scan_artifacts,
    safe_csv_id,
    validate_csv_artifact_key,
    validate_csv_artifact_security,
    validate_csv_artifacts,
    validate_csv_id,
    validate_materialized_csv_scan_artifacts,
)


def test_version_334_csv_artifact_security_envelope():
    assert __version__ == "3.5.3"


def test_csv_id_validation_accepts_bounded_artifact_safe_ids():
    csv_id = "dataset-01.alpha_beta"

    assert is_safe_csv_id(csv_id) is True
    assert validate_csv_id(csv_id) == csv_id
    assert artifact_keys(csv_id)["raw"] == "csv__dataset-01.alpha_beta__raw.csv"
    assert csv_scan_artifact_keys(csv_id)["scan_profile"] == "csv__dataset-01.alpha_beta__scan_profile.json"


def test_csv_id_validation_rejects_path_control_and_empty_ids():
    unsafe_ids = [
        "",
        "../escape",
        "nested/name",
        "nested\\name",
        ".hidden",
        "-dash-start",
        "bad\nline",
        "a" * 129,
    ]

    for csv_id in unsafe_ids:
        assert is_safe_csv_id(csv_id) is False
        with pytest.raises(ValueError):
            validate_csv_id(csv_id)
        with pytest.raises(ValueError):
            artifact_keys(csv_id)


def test_safe_csv_id_bounds_long_source_names_without_losing_hash_suffix():
    raw = b"a,b\n1,2\n"
    csv_id = safe_csv_id("x" * 300 + ".csv", raw)

    assert is_safe_csv_id(csv_id) is True
    assert len(csv_id) <= 128
    assert csv_id.endswith("_" + safe_csv_id("short.csv", raw).split("_")[-1])


def test_csv_import_rejects_unsafe_custom_csv_id_before_writes():
    fs = TDSFileSystem("root")

    with pytest.raises(ValueError):
        import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="evil.csv", csv_id="../evil")

    assert validate_csv_artifacts(fs.root, "../evil").ok is False
    assert validate_csv_artifacts(fs.root, "../evil").errors[0].startswith("csv_id_unsafe")


def test_csv_artifact_key_validation_contains_keys_in_csv_namespace():
    csv_id = "safe_123"
    key = artifact_keys(csv_id)["manifest"]

    assert validate_csv_artifact_key(key, csv_id) == key
    with pytest.raises(ValueError):
        validate_csv_artifact_key("csv__other__manifest.json", csv_id)
    with pytest.raises(ValueError):
        validate_csv_artifact_key("csv__safe_123__/escape.json", csv_id)


def test_csv_artifact_security_envelope_validates_core_and_scan_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,note\n1,ok\n2,done\n", source_name="secure.csv")
    materialized = materialize_csv_scan_artifacts(fs.root, manifest.csv_id, include_row_anchors=True, chunk_size=2)

    core_report = validate_csv_artifact_security(fs.root, manifest.csv_id)
    scan_report = validate_csv_artifact_security(fs.root, manifest.csv_id, include_scan_artifacts=True)

    assert materialized.ok is True
    assert core_report.ok is True
    assert core_report.id_safe is True
    assert core_report.core_keyset_verified is True
    assert core_report.scan_keyset_verified is True
    assert core_report.per_row_writes is False
    assert core_report.per_cell_writes is False
    assert core_report.native_storage_hot_path_touched is False
    assert core_report.semantic_reasoning is False
    assert scan_report.ok is True
    assert scan_report.scan_keyset_verified is True
    assert set(scan_report.checked_artifacts) == {
        "manifest",
        "scan_profile",
        "row_anchor_profile",
        "scan_materialization_report",
    }


def test_csv_artifact_security_envelope_fails_closed_on_manifest_key_tampering():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="key-drift.csv")
    manifest_doc = fs.root.read_value(manifest.artifact_keys["manifest"])
    manifest_doc["artifact_keys"] = dict(manifest_doc["artifact_keys"])
    manifest_doc["artifact_keys"]["raw"] = "csv__../escape__raw.csv"
    fs.root.write_json(manifest.artifact_keys["manifest"], manifest_doc, overwrite=True, provenance="DERIVED")

    report = validate_csv_artifact_security(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.core_keyset_verified is False
    assert "core_keyset_mismatch" in report.errors
    assert any(error.startswith("core_raw_unsafe_key") for error in report.errors)


def test_csv_scan_materialization_invalid_id_returns_invalid_report_without_writes():
    fs = TDSFileSystem("root")

    report = materialize_csv_scan_artifacts(fs.root, "../bad", include_row_anchors=True)
    validation = validate_materialized_csv_scan_artifacts(fs.root, "../bad")

    assert report.ok is False
    assert report.write_count == 0
    assert report.errors[0].startswith("csv_id_unsafe")
    assert validation.ok is False
    assert validation.errors[0].startswith("csv_id_unsafe")

from __future__ import annotations

from staqtapp_tds import TDSDirectory, TDSFileSystem, __version__
from staqtapp_tds.csv_layer import import_csv_bytes, load_csv_artifact, validate_csv_artifacts


def test_version_322_csv_artifact_validation_pass():
    assert __version__ == "3.5.3.post1"


def test_csv_artifact_validation_accepts_clean_import():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,name\n1,Ada\n2,Grace\n", source_name="people.csv")

    report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.status == "valid"
    assert report.error_count == 0
    assert report.raw_sha256_verified is True
    assert report.row_offsets_verified is True
    assert report.dialect_verified is True
    assert report.manifest_consistent is True
    assert report.original_preserved is True
    assert report.derived_artifacts_only is True
    assert report.native_storage_hot_path_touched is False
    assert report.per_cell_writes is False
    assert set(report.checked_artifacts) == {"manifest", "raw", "dialect", "row_offsets", "content_hashes", "import_report"}
    assert report.to_dict()["ok"] is True


def test_csv_artifact_validation_detects_raw_artifact_tampering():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,name\n1,Ada\n", source_name="people.csv")

    fs.root.write_text(manifest.artifact_keys["raw"], "id,name\n1,Eve\n", overwrite=True, provenance="REAL")
    report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.raw_sha256_verified is False
    assert "raw_sha256_mismatch" in report.errors
    assert "row_offsets_source_actual_hash_mismatch" in report.errors


def test_csv_artifact_validation_detects_row_offset_artifact_drift():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"id,note\n1,flat\n2,done\n", source_name="offsets.csv")
    row_offsets = load_csv_artifact(fs.root, manifest.csv_id, "row_offsets")
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(manifest.artifact_keys["row_offsets"], row_offsets, overwrite=True, provenance="DERIVED")

    report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.row_offsets_verified is False
    assert "row_offsets_recompute_mismatch" in report.errors


def test_csv_artifact_validation_detects_shape_contract_regression():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="shape.csv")
    import_report = load_csv_artifact(fs.root, manifest.csv_id, "import_report")
    import_report["artifact_write_count"] = 5000
    import_report["per_cell_writes"] = True
    fs.root.write_json(manifest.artifact_keys["import_report"], import_report, overwrite=True, provenance="DERIVED")

    report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.per_cell_writes is True
    assert "import_report_artifact_write_count_mismatch" in report.errors
    assert "import_report_declares_per_cell_writes" in report.errors


def test_csv_artifact_validation_missing_manifest_fails_closed():
    directory = TDSDirectory("root")
    report = validate_csv_artifacts(directory, "missing")

    assert report.ok is False
    assert report.status == "invalid"
    assert report.error_count == 1
    assert report.errors[0].startswith("manifest_unreadable")

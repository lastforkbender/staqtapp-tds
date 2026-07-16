from __future__ import annotations

from staqtapp_tds import TDSDirectory, TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    csv_scan_artifact_keys,
    import_csv_bytes,
    load_csv_artifact,
    load_csv_row_anchor_profile,
    load_csv_scan_materialization_report,
    load_csv_scan_profile,
    materialize_csv_scan_artifacts,
    scan_csv_bytes,
    scan_csv_row_anchors,
    validate_materialized_csv_scan_artifacts,
)


class CountingDirectory(TDSDirectory):
    def __init__(self, name: str):
        super().__init__(name)
        self.text_writes = 0
        self.json_writes = 0

    def write_text(self, *args, **kwargs):
        self.text_writes += 1
        return super().write_text(*args, **kwargs)

    def write_json(self, *args, **kwargs):
        self.json_writes += 1
        return super().write_json(*args, **kwargs)


def test_version_333_csv_scan_artifact_materialization():
    assert __version__ == "3.5.3"


def test_csv_scan_artifacts_materialize_as_optional_derived_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(
        fs.root,
        b'id,note\r\n1,"two\nlines"\r\n2,"quote "" kept"\r\n',
        source_name="scan_materialized.csv",
    )

    report = materialize_csv_scan_artifacts(fs.root, manifest.csv_id, include_row_anchors=True, chunk_size=4)
    keys = csv_scan_artifact_keys(manifest.csv_id)

    assert report.ok is True
    assert report.status == "materialized"
    assert report.write_count == 3
    assert report.wrote_scan_profile is True
    assert report.wrote_row_anchor_profile is True
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.semantic_reasoning is False
    assert fs.root.read_value(keys["scan_profile"])["row_count"] == manifest.row_count
    assert fs.root.read_value(keys["row_anchor_profile"])["row_count"] == manifest.row_count
    assert fs.root.read_value(keys["scan_materialization_report"])["ok"] is True

    loaded_scan = load_csv_scan_profile(fs.root, manifest.csv_id)
    loaded_anchors = load_csv_row_anchor_profile(fs.root, manifest.csv_id)
    raw = fs.root.read_value(manifest.artifact_keys["raw"]).encode(manifest.encoding)

    assert loaded_scan.to_dict() == scan_csv_bytes(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=4).to_dict()
    assert loaded_anchors.to_dict() == scan_csv_row_anchors(raw, manifest.dialect, encoding=manifest.encoding, chunk_size=4).to_dict()
    assert load_csv_scan_materialization_report(fs.root, manifest.csv_id).to_dict() == report.to_dict()


def test_csv_scan_materialization_does_not_change_core_import_write_shape():
    directory = CountingDirectory("root")
    rows = ["c1,c2,c3"] + [f"{i},{i + 1},{i + 2}" for i in range(100)]
    manifest = import_csv_bytes(directory, ("\n".join(rows) + "\n").encode("utf-8"), source_name="shape.csv")
    import_report = load_csv_artifact(directory, manifest.csv_id, "import_report")

    assert directory.text_writes == 1
    assert directory.json_writes == 5
    assert import_report["artifact_write_count"] == 6
    assert import_report["derived_artifact_count"] == 5
    assert import_report["per_cell_writes"] is False

    materialized = materialize_csv_scan_artifacts(directory, manifest.csv_id, include_row_anchors=True, chunk_size=8)

    assert materialized.ok is True
    assert directory.text_writes == 1
    assert directory.json_writes == 8
    assert materialized.write_count == 3
    assert load_csv_artifact(directory, manifest.csv_id, "import_report")["artifact_write_count"] == 6


def test_csv_scan_materialization_can_store_scan_profile_without_row_anchors():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="scan_only.csv")

    report = materialize_csv_scan_artifacts(fs.root, manifest.csv_id, include_row_anchors=False, chunk_size=2)
    validation = validate_materialized_csv_scan_artifacts(
        fs.root,
        manifest.csv_id,
        require_row_anchors=False,
        chunk_size=2,
    )

    assert report.ok is True
    assert report.write_count == 2
    assert report.wrote_scan_profile is True
    assert report.wrote_row_anchor_profile is False
    assert report.row_anchor_hash_count == 0
    assert validation.ok is True
    assert validation.scan_profile_match is True
    assert validation.row_anchor_profile_match is True


def test_csv_materialized_scan_validation_fails_closed_on_raw_drift():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n3,4\n", source_name="drift.csv")
    materialize_csv_scan_artifacts(fs.root, manifest.csv_id, include_row_anchors=True, chunk_size=3)

    fs.root.write_text(manifest.artifact_keys["raw"], "a,b\n1,2\n3,4\n5,6\n", overwrite=True, provenance="REAL")

    report = validate_materialized_csv_scan_artifacts(fs.root, manifest.csv_id, require_row_anchors=True, chunk_size=3)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.scan_profile_match is False
    assert report.row_anchor_profile_match is False
    assert "materialized_scan_profile_raw_sha256_mismatch" in report.errors
    assert "materialized_row_anchor_raw_sha256_mismatch" in report.errors


def test_csv_scan_materialization_fails_closed_before_writing_when_core_artifacts_drift():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n3,4\n", source_name="offset_drift.csv")
    row_offsets = load_csv_artifact(fs.root, manifest.csv_id, "row_offsets")
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(manifest.artifact_keys["row_offsets"], row_offsets, overwrite=True, provenance="DERIVED")

    report = materialize_csv_scan_artifacts(fs.root, manifest.csv_id, include_row_anchors=True, chunk_size=2)
    keys = csv_scan_artifact_keys(manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert report.write_count == 0
    assert report.wrote_scan_profile is False
    assert "scan_row_offsets_mismatch" in report.errors
    try:
        fs.root.read_value(keys["scan_profile"])
    except KeyError:
        pass
    else:
        raise AssertionError("scan profile should not be written when core artifacts drift")

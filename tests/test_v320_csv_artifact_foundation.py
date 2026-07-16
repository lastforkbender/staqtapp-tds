from __future__ import annotations

from pathlib import Path

from staqtapp_tds import TDSFileSystem, TDSPersistence, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    build_row_offset_map,
    detect_csv_dialect,
    export_canonical_csv,
    export_original_csv,
    import_csv_bytes,
    import_csv_file,
    load_csv_artifact,
    load_csv_manifest,
    logical_record_offsets,
    prove_original_roundtrip,
)


def test_version_320_csv_foundation():
    assert __version__ == "3.5.3.post1"


def test_csv_import_preserves_original_and_writes_derived_artifacts():
    fs = TDSFileSystem("root")
    csv_text = "id,name\n1,Ada\n2,Grace\n"

    manifest = import_csv_bytes(fs.root, csv_text.encode("utf-8"), source_name="people.csv")

    assert manifest.csv_id.startswith("people_")
    assert manifest.row_count == 3
    assert manifest.column_count == 2
    assert manifest.original_preserved is True
    assert manifest.derived_artifacts_only is True
    assert manifest.native_storage_hot_path_touched is False
    keys = artifact_keys(manifest.csv_id)
    assert export_original_csv(fs.root, manifest.csv_id) == csv_text
    assert fs.root.read_value(keys["manifest"])["raw_sha256"] == manifest.raw_sha256
    assert fs.root.read_value(keys["dialect"])["delimiter"] == ","
    assert fs.root.read_value(keys["row_offsets"])["row_count"] == 3
    assert fs.root.read_value(keys["content_hashes"])["raw_sha256"] == manifest.raw_sha256
    assert fs.root.read_value(keys["import_report"])["status"] == "imported"


def test_csv_import_persists_through_tds_storage_without_native_engine_changes(tmp_path: Path):
    fs = TDSFileSystem("root")
    source = tmp_path / "inventory.csv"
    source.write_text("sku,qty\nA-1,7\nB-2,9\n", encoding="utf-8")
    manifest = import_csv_file(fs.root, source)

    persist = TDSPersistence(tmp_path / "mount")
    persist.flush(fs, parallel_nodes=False)
    loaded = persist.load_node(tmp_path / "mount" / "root.tds")

    loaded_manifest = load_csv_manifest(loaded, manifest.csv_id)
    assert loaded_manifest.raw_sha256 == manifest.raw_sha256
    exported = export_original_csv(loaded, manifest.csv_id)
    assert exported.encode(loaded_manifest.encoding) == source.read_bytes()
    proof = prove_original_roundtrip(loaded, manifest.csv_id)
    assert proof.byte_equivalent is True
    assert loaded.read_value(manifest.artifact_keys["roundtrip_report"])["byte_equivalent"] is True


def test_csv_logical_row_offsets_respect_quoted_newline():
    text = 'id,note\n1,"hello\nworld"\n2,"done"\n'
    dialect = detect_csv_dialect(text)
    offsets = logical_record_offsets(text, dialect)
    row_map = build_row_offset_map(text, dialect)

    assert len(offsets) == 3
    assert row_map.row_count == 3
    assert offsets[0] == 0
    second_row = text.encode("utf-8")[offsets[1]:].decode("utf-8")
    assert second_row.startswith('1,"hello')


def test_csv_canonical_export_is_deterministic_and_source_remains_unchanged():
    fs = TDSFileSystem("root")
    source = 'id;name\r\n1;"Ada"\r\n2;"Grace"\r\n'
    manifest = import_csv_bytes(fs.root, source.encode("utf-8"), source_name="semi.csv")

    canonical_a = export_canonical_csv(fs.root, manifest.csv_id)
    canonical_b = export_canonical_csv(fs.root, manifest.csv_id)

    assert canonical_a == canonical_b
    assert canonical_a == "id;name\n1;Ada\n2;Grace\n"
    assert export_original_csv(fs.root, manifest.csv_id) == source


def test_csv_artifact_loader_and_manifest_roundtrip():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n3,4\n", source_name="tiny.csv")

    dialect = load_csv_artifact(fs.root, manifest.csv_id, "dialect")
    loaded = load_csv_manifest(fs.root, manifest.csv_id)

    assert dialect["delimiter"] == ","
    assert loaded.to_dict() == manifest.to_dict()


def test_csv_import_duplicate_without_overwrite_fails_cleanly():
    fs = TDSFileSystem("root")
    payload = b"a,b\n1,2\n"
    manifest = import_csv_bytes(fs.root, payload, source_name="dupe.csv", csv_id="dupe")

    try:
        import_csv_bytes(fs.root, payload, source_name="dupe.csv", csv_id="dupe", overwrite=False)
    except RuntimeError as exc:
        assert "CSV artifact write failed" in str(exc)
    else:
        raise AssertionError("duplicate CSV import should fail without overwrite=True")

    overwritten = import_csv_bytes(fs.root, payload, source_name="dupe.csv", csv_id="dupe", overwrite=True)
    assert overwritten.csv_id == manifest.csv_id

from __future__ import annotations

import hashlib

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    import_csv_bytes,
    load_csv_artifact,
    scan_csv_bytes,
    scan_csv_row_anchors,
    scan_csv_text_row_anchors,
    validate_csv_row_anchors,
)
from staqtapp_tds.csv_layer.dialect import detect_csv_dialect


def test_version_332_csv_row_anchor_scan_pass():
    assert __version__ == "3.5.3.post1"


def test_csv_row_anchor_profile_hashes_exact_logical_record_bytes():
    raw = b'id,note\r\n1,"line\none"\r\n2,"quote "" kept"\r\n3,last'
    dialect = detect_csv_dialect(raw.decode("utf-8"))
    scan = scan_csv_bytes(raw, dialect, chunk_size=5)

    anchors = scan_csv_row_anchors(raw, dialect, chunk_size=5)

    expected_hashes = []
    expected_spans = []
    for idx, start in enumerate(scan.row_offsets):
        end = scan.row_offsets[idx + 1] if idx + 1 < len(scan.row_offsets) else len(raw)
        expected_spans.append(end - start)
        expected_hashes.append(hashlib.sha256(raw[start:end]).hexdigest())

    assert anchors.row_offsets == scan.row_offsets
    assert anchors.row_spans == tuple(expected_spans)
    assert anchors.row_anchor_hashes == tuple(expected_hashes)
    assert anchors.row_count == scan.row_count == 4
    assert anchors.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert anchors.digest_algorithm == "sha256"
    assert anchors.native_storage_hot_path_touched is False
    assert anchors.semantic_reasoning is False
    assert anchors.to_dict()["row_anchor_hashes"] == list(anchors.row_anchor_hashes)


def test_csv_row_anchor_hashes_are_stable_for_buffers_and_chunk_boundaries():
    raw = b'a,b\n1,"two\nlines"\n2,done\n3,"quote "" kept"\n'
    dialect = detect_csv_dialect(raw.decode("utf-8"))
    expected = scan_csv_row_anchors(raw, dialect, chunk_size=None)

    for payload in (bytearray(raw), memoryview(raw)):
        for chunk_size in (1, 2, 7, 64):
            anchors = scan_csv_row_anchors(payload, dialect, chunk_size=chunk_size)
            assert anchors.row_offsets == expected.row_offsets
            assert anchors.row_spans == expected.row_spans
            assert anchors.row_anchor_hashes == expected.row_anchor_hashes
            assert anchors.raw_sha256 == expected.raw_sha256
            assert anchors.chunk_count >= 1


def test_csv_text_row_anchor_helper_delegates_to_byte_reference():
    text = 'id,name\n1,Åsa\n2,東京\n'
    dialect = detect_csv_dialect(text)

    from_text = scan_csv_text_row_anchors(text, dialect, chunk_size=3)
    from_bytes = scan_csv_row_anchors(text.encode("utf-8"), dialect, chunk_size=3)

    assert from_text.to_dict() == from_bytes.to_dict()


def test_csv_row_anchor_validation_is_read_only_and_matches_durable_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(
        fs.root,
        b'id,note\n1,"chunk\nboundary"\n2,"quote "" kept"\n',
        source_name="row_anchor.csv",
    )

    report = validate_csv_row_anchors(fs.root, manifest.csv_id, chunk_size=3)

    assert report.ok is True
    assert report.status == "valid"
    assert report.raw_sha256_verified is True
    assert report.row_offsets_match is True
    assert report.row_count_match is True
    assert report.anchor_row_count == manifest.row_count
    assert report.artifact_row_count == manifest.row_count
    assert report.checked_artifacts == ("manifest", "raw", "row_offsets")
    assert report.native_storage_hot_path_touched is False
    assert report.semantic_reasoning is False
    assert report.to_dict()["ok"] is True


def test_csv_row_anchor_validation_fails_closed_on_row_offset_drift():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n3,4\n", source_name="row_anchor_drift.csv")
    row_offsets = load_csv_artifact(fs.root, manifest.csv_id, "row_offsets")
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(manifest.artifact_keys["row_offsets"], row_offsets, overwrite=True, provenance="DERIVED")

    report = validate_csv_row_anchors(fs.root, manifest.csv_id, chunk_size=2)

    assert report.ok is False
    assert report.status == "invalid"
    assert "anchor_row_offsets_mismatch" in report.errors

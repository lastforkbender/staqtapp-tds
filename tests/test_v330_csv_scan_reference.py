from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    import_csv_bytes,
    logical_record_offsets_bytes,
    scan_csv_bytes,
    scan_csv_text,
    validate_csv_artifacts,
    validate_csv_scan_profile,
)
from staqtapp_tds.csv_layer.dialect import detect_csv_dialect


def test_version_330_csv_scan_reference_foundation():
    assert __version__ == "3.5.3.post1"


def test_csv_scan_profile_matches_row_offset_reference_across_chunk_boundaries():
    cases = [
        b"a,b\n1,2\n3,4\n",
        b"a,b\r\n1,2\n3,4\r5,6\n",
        b'id,note\n1,"hello\nworld"\n2,"quote "" kept"\n',
        b'id,note\r\n1,"crlf\r\ninside"\r\n2,done\r\n',
        b"id\tnote\n1\talpha\n2\tbeta\n",
        "id,name\n1,Åsa\n2,東京\n".encode("utf-8"),
        b'id,note\n1,"unterminated\n2,still quoted\n',
    ]
    chunk_sizes = [None, 1, 2, 3, 5, 8, 13, 64]

    for raw in cases:
        text = raw.decode("utf-8")
        dialect = detect_csv_dialect(text)
        expected_offsets = logical_record_offsets_bytes(raw, dialect)
        for chunk_size in chunk_sizes:
            profile = scan_csv_bytes(raw, dialect, chunk_size=chunk_size)
            assert profile.row_offsets == expected_offsets, (raw, chunk_size, profile.to_dict())
            assert profile.row_count == len(expected_offsets)
            assert profile.raw_sha256
            assert profile.native_storage_hot_path_touched is False
            assert profile.semantic_reasoning is False


def test_csv_scan_profile_reports_mechanical_newline_and_quote_metrics_only():
    raw = b'id,note\r\n1,"line one\nline two"\r\n2,"quote "" kept"\r\n3,last'
    dialect = detect_csv_dialect(raw.decode("utf-8"))
    profile = scan_csv_bytes(raw, dialect, chunk_size=4)

    assert profile.row_count == 4
    assert profile.newline_crlf_count == 3
    assert profile.newline_lf_count == 0
    assert profile.newline_cr_count == 0
    assert profile.quoted_newline_count == 1
    assert profile.escaped_quote_count == 1
    assert profile.delimiter_count == 4
    assert profile.terminal_newline is False
    assert profile.ended_in_open_quote is False
    assert profile.chunk_size == 4
    assert profile.chunk_count > 1
    assert profile.to_dict()["row_offsets"] == list(profile.row_offsets)


def test_csv_scan_text_delegates_to_same_byte_reference():
    text = 'a,b\n1,"two\nlines"\n2,done\n'
    dialect = detect_csv_dialect(text)

    from_text = scan_csv_text(text, dialect, chunk_size=2)
    from_bytes = scan_csv_bytes(text.encode("utf-8"), dialect, chunk_size=2)

    assert from_text.to_dict() == from_bytes.to_dict()


def test_csv_scan_parity_report_validates_against_durable_artifacts_without_writes():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(
        fs.root,
        b'id,note\n1,"chunk\nboundary"\n2,"quote "" kept"\n',
        source_name="scan_parity.csv",
    )

    report = validate_csv_scan_profile(fs.root, manifest.csv_id, chunk_size=3)
    artifact_report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.status == "valid"
    assert report.raw_sha256_verified is True
    assert report.row_offsets_match is True
    assert report.row_count_match is True
    assert report.scan_row_count == manifest.row_count
    assert report.artifact_row_count == manifest.row_count
    assert report.checked_artifacts == ("manifest", "raw", "row_offsets")
    assert report.native_storage_hot_path_touched is False
    assert report.semantic_reasoning is False
    assert report.to_dict()["ok"] is True
    assert artifact_report.ok is True


def test_csv_scan_parity_report_fails_closed_on_row_offset_drift():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n3,4\n", source_name="scan_drift.csv")
    row_offsets = fs.root.read_value(manifest.artifact_keys["row_offsets"])
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(manifest.artifact_keys["row_offsets"], row_offsets, overwrite=True, provenance="DERIVED")

    report = validate_csv_scan_profile(fs.root, manifest.csv_id, chunk_size=2)

    assert report.ok is False
    assert report.status == "invalid"
    assert "scan_row_offsets_mismatch" in report.errors

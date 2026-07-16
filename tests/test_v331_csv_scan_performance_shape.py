from __future__ import annotations

import mmap

import pytest

from staqtapp_tds import __version__
from staqtapp_tds.csv_layer import (
    logical_record_offsets_bytes,
    pack_csv_row_offsets,
    scan_csv_bytes,
    unpack_csv_row_offsets,
)
from staqtapp_tds.csv_layer.dialect import detect_csv_dialect


def test_version_331_csv_scan_performance_shape_pass():
    assert __version__ == "3.5.3"


def test_csv_scan_accepts_buffer_inputs_with_same_profile(tmp_path):
    raw = b'id,note\n1,"line\none"\n2,"quote "" kept"\n'
    dialect = detect_csv_dialect(raw.decode("utf-8"))
    expected = scan_csv_bytes(raw, dialect, chunk_size=3)

    bytearray_profile = scan_csv_bytes(bytearray(raw), dialect, chunk_size=3)
    memoryview_profile = scan_csv_bytes(memoryview(raw), dialect, chunk_size=3)

    path = tmp_path / "scan-buffer.csv"
    path.write_bytes(raw)
    with path.open("rb") as handle:
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            mmap_profile = scan_csv_bytes(mapped, dialect, chunk_size=3)

    assert bytearray_profile.to_dict() == expected.to_dict()
    assert memoryview_profile.to_dict() == expected.to_dict()
    assert mmap_profile.to_dict() == expected.to_dict()
    assert logical_record_offsets_bytes(memoryview(raw), dialect) == expected.row_offsets


def test_csv_scan_tracks_max_record_span_without_intermediate_span_artifact():
    raw = b"a,b\n123,456\nx,y"
    dialect = detect_csv_dialect(raw.decode("utf-8"))

    profile = scan_csv_bytes(raw, dialect)

    assert profile.row_offsets == (0, 4, 12)
    assert profile.max_record_span == 8
    assert profile.terminal_newline is False


def test_csv_row_offsets_can_round_trip_through_packed_uint64_shape():
    offsets = (0, 4, 12, 2**40)

    payload = pack_csv_row_offsets(offsets)

    assert isinstance(payload, bytes)
    assert len(payload) == 8 * len(offsets)
    assert unpack_csv_row_offsets(payload) == offsets
    assert unpack_csv_row_offsets(memoryview(bytearray(payload))) == offsets


def test_csv_packed_row_offsets_fail_closed_on_invalid_shape():
    with pytest.raises(ValueError, match="non-negative"):
        pack_csv_row_offsets((0, -1))

    with pytest.raises(ValueError, match="8-byte aligned"):
        unpack_csv_row_offsets(b"abc")

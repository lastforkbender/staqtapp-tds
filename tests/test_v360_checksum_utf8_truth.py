from __future__ import annotations

import threading

import pytest

from staqtapp_tds import FmtID, TDSFileSystem
from staqtapp_tds.native.checksums import (
    CRC32_IEEE_V1,
    FNV1A32_LEGACY_V1,
    checksum32,
    checksum32_many,
    checksum32_python,
    manifest_checksum32_algorithm,
)
from staqtapp_tds.native.manager import get_native_manager
from staqtapp_tds.native.utf8 import (
    UTF8_CHUNK_CONTRACT,
    utf8_chunk_bounds,
    utf8_chunk_bounds_python,
)


def test_registered_checksum_known_vectors_and_batch_parity() -> None:
    assert checksum32_python(b"123456789", algorithm=CRC32_IEEE_V1) == 0xCBF43926
    assert checksum32_python(b"hello", algorithm=FNV1A32_LEGACY_V1) == 0x4F9F2CAB

    payloads = [b"", b"alpha", "βγ".encode("utf-8"), bytes(range(256))]
    for algorithm in (CRC32_IEEE_V1, FNV1A32_LEGACY_V1):
        expected = [checksum32_python(item, algorithm=algorithm) for item in payloads]
        actual, backend = checksum32_many(payloads, algorithm=algorithm)
        assert actual == expected
        assert backend in {"native", "python"}
        for payload, value in zip(payloads, expected):
            scalar, scalar_backend = checksum32(payload, algorithm=algorithm)
            assert scalar == value
            assert scalar_backend in {"native", "python"}


def test_new_chunk_manifest_binds_checksum_and_utf8_contract() -> None:
    fs = TDSFileSystem("truth")
    text = "alpha β 😀 𝄞" * 40
    result = fs.root.write_text_chunked("evidence", text, chunk_size=7)
    assert result.ok

    manifest = fs.root.read_value("evidence")
    assert manifest["chunk_checksum_algorithm"] == CRC32_IEEE_V1
    assert manifest["chunk_boundary_contract"] == UTF8_CHUNK_CONTRACT
    assert manifest["chunk_checksum_backend"] in {"native", "python"}
    assert manifest["chunk_boundary_backend"] in {"native", "python"}
    assert fs.root.read_text("evidence") == text


def test_historical_native_manifest_infers_legacy_fnv_and_remains_readable() -> None:
    fs = TDSFileSystem("legacy")
    text = "legacy β evidence"
    assert fs.root.write_text_chunked("doc", text, chunk_size=6).ok
    manifest = dict(fs.root.read_value("doc"))
    raw_parts = [
        str(fs.root.read_value(chunk_name)).encode("utf-8")
        for chunk_name in manifest["chunks"]
    ]
    legacy_values, _backend = checksum32_many(
        raw_parts,
        algorithm=FNV1A32_LEGACY_V1,
    )
    manifest.pop("chunk_checksum_algorithm", None)
    manifest.pop("chunk_boundary_contract", None)
    manifest.pop("chunk_boundary_backend", None)
    manifest["chunk_checksum_backend"] = "native"
    manifest["chunk_checksums32"] = legacy_values
    fs.root._write_entry("doc", manifest, fmt_id=FmtID.JSON_UTF8, compress=False)

    assert manifest_checksum32_algorithm(manifest) == FNV1A32_LEGACY_V1
    assert fs.root.read_text("doc") == text


@pytest.mark.parametrize(
    "payload",
    (
        b"\xc0\x80",
        b"\xed\xa0\x80",
        b"\xf0\x9f\x92",
        b"\xf4\x90\x80\x80",
        b"\x80",
    ),
)
def test_invalid_utf8_fails_closed_in_python_and_selected_backend(payload: bytes) -> None:
    with pytest.raises(UnicodeDecodeError):
        utf8_chunk_bounds_python(payload, 2)
    with pytest.raises(UnicodeDecodeError):
        utf8_chunk_bounds(payload, 2)


def test_utf8_boundaries_match_reference_across_real_split_sizes() -> None:
    data = ("a😀bé𝄞日本語" * 19).encode("utf-8")
    for chunk_size in range(1, 17):
        expected = utf8_chunk_bounds_python(data, chunk_size)
        actual, backend = utf8_chunk_bounds(data, chunk_size)
        assert actual == expected
        assert backend in {"native", "python"}
        start = 0
        for end in actual:
            chunk = data[start:end]
            chunk.decode("utf-8")
            if len(chunk) > chunk_size:
                assert len(chunk.decode("utf-8")) == 1
                assert len(chunk) <= 4
            start = end
        assert start == len(data)


def test_mutable_buffer_calls_observe_only_complete_snapshots() -> None:
    left = bytearray(("aβ😀" * 128).encode("utf-8"))
    original = bytes(left)
    right = ("zγ𝄞" * 128).encode("utf-8")
    assert len(left) == len(right)
    allowed_crc = {
        checksum32_python(original, algorithm=CRC32_IEEE_V1),
        checksum32_python(right, algorithm=CRC32_IEEE_V1),
    }
    allowed_bounds = {
        tuple(utf8_chunk_bounds_python(original, 13)),
        tuple(utf8_chunk_bounds_python(right, 13)),
    }
    stop = threading.Event()

    def mutate() -> None:
        while not stop.is_set():
            left[:] = right
            left[:] = original

    worker = threading.Thread(target=mutate)
    worker.start()
    try:
        for _ in range(100):
            checksum, _backend = checksum32(left, algorithm=CRC32_IEEE_V1)
            assert checksum in allowed_crc
            bounds, _backend = utf8_chunk_bounds(left, 13)
            assert tuple(bounds) in allowed_bounds
    finally:
        stop.set()
        worker.join(timeout=5)
    assert not worker.is_alive()


def test_native_capability_report_binds_algorithm_and_boundary_contract() -> None:
    module, report = get_native_manager().inspect_module("staqtapp_tds._native_index")
    if module is None:
        pytest.skip("native extension is not active")
    assert report.compatible
    assert report.capabilities["has_checksum32_for_algorithm"] is True
    assert report.capabilities["has_checksum32_many_for_algorithm"] is True
    assert set(report.capabilities["checksum_algorithms"]) == {
        CRC32_IEEE_V1,
        FNV1A32_LEGACY_V1,
    }
    assert report.capabilities["utf8_chunk_contract"] == UTF8_CHUNK_CONTRACT

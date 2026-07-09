import shutil
import struct
import zlib

import pytest

from staqtapp_tds.result import TDSResultCode
from staqtapp_tds.tds_filesystem import CompressorRegistry, TDSFileSystem
from staqtapp_tds.tds_persistence import (
    FILE_HDR_FMT,
    FILE_HDR_SIZE,
    TDSPersistence,
    TDSPersistenceIntegrityError,
    TDSReader,
)


def _baseline_file(tmp_path):
    fs = TDSFileSystem()
    fs.root.write_text("alpha", "hello")
    fs.root.write_json("beta", {"x": 1})
    TDSPersistence(tmp_path).flush(fs, parallel_nodes=False)
    return tmp_path / "tds_root.tds"


def _rewrite_header(raw: bytearray, *, slot_count=None, index_offset=None) -> bytearray:
    magic, ver, old_count, old_idx, data_off, ts, _crc = struct.unpack(FILE_HDR_FMT, raw[:FILE_HDR_SIZE])
    new_count = old_count if slot_count is None else slot_count
    new_idx = old_idx if index_offset is None else index_offset
    zero_crc = struct.pack(FILE_HDR_FMT, magic, ver, new_count, new_idx, data_off, ts, 0)
    raw[:FILE_HDR_SIZE] = struct.pack(
        FILE_HDR_FMT, magic, ver, new_count, new_idx, data_off, ts, zlib.crc32(zero_crc) & 0xFFFFFFFF
    )
    return raw


@pytest.mark.parametrize("tail_bytes", [1, 8])
def test_slot_index_truncation_fails_closed(tmp_path, tail_bytes):
    tds_path = _baseline_file(tmp_path)
    corrupt = tmp_path / f"truncated_{tail_bytes}.tds"
    corrupt.write_bytes(tds_path.read_bytes()[:-tail_bytes])

    with pytest.raises(TDSPersistenceIntegrityError) as exc:
        TDSReader(corrupt)
    assert exc.value.code == TDSResultCode.PERSIST_INDEX_CORRUPT


def test_slot_count_overstatement_fails_closed(tmp_path):
    tds_path = _baseline_file(tmp_path)
    raw = bytearray(tds_path.read_bytes())
    _magic, _ver, slot_count, _idx, _data, _ts, _crc = struct.unpack(FILE_HDR_FMT, raw[:FILE_HDR_SIZE])
    corrupt = tmp_path / "slot_count_plus_one.tds"
    corrupt.write_bytes(_rewrite_header(raw, slot_count=slot_count + 1))

    with pytest.raises(TDSPersistenceIntegrityError) as exc:
        TDSReader(corrupt)
    assert exc.value.code == TDSResultCode.PERSIST_INDEX_CORRUPT


def test_index_offset_past_eof_fails_closed(tmp_path):
    tds_path = _baseline_file(tmp_path)
    raw = bytearray(tds_path.read_bytes())
    corrupt = tmp_path / "index_past_eof.tds"
    corrupt.write_bytes(_rewrite_header(raw, index_offset=len(raw) + 128))

    with pytest.raises(TDSPersistenceIntegrityError) as exc:
        TDSReader(corrupt)
    assert exc.value.code == TDSResultCode.PERSIST_INDEX_CORRUPT


def test_payload_hash_mismatch_returns_typed_integrity_result(tmp_path):
    tds_path = _baseline_file(tmp_path)
    with TDSReader(tds_path) as reader:
        rec = reader._idx.lookup("/tds_root/alpha")
        assert rec is not None
        abs_off = int(reader._hdr["data_offset"]) + rec.offset

    raw = bytearray(tds_path.read_bytes())
    assert raw[abs_off : abs_off + 5] == b"hello"
    raw[abs_off] = ord("j")
    corrupt = tmp_path / "payload_hash_mismatch.tds"
    corrupt.write_bytes(raw)
    shutil.copyfile(tds_path.with_suffix(".tds.meta"), corrupt.with_suffix(".tds.meta"))

    result = TDSReader(corrupt).read_result("/tds_root/alpha")
    assert not result.ok
    assert result.code == TDSResultCode.PERSIST_PAYLOAD_HASH_MISMATCH.value
    assert result.meta["expected_hash"] != result.meta["actual_hash"]


def test_compressed_payload_uses_persisted_codec_not_process_default(tmp_path):
    try:
        CompressorRegistry.register("revz_test", lambda d: zlib.compress(d)[::-1], lambda d: zlib.decompress(d[::-1]))
    except Exception:
        pass
    old_default = CompressorRegistry._default
    try:
        CompressorRegistry.set_default("revz_test")
        fs = TDSFileSystem()
        fs.root.write_text("big", "x" * 2048, compress=True, codec="revz_test")
        TDSPersistence(tmp_path).flush(fs, parallel_nodes=False)
        CompressorRegistry.set_default("zlib")

        result = TDSReader(tmp_path / "tds_root.tds").read_result("/tds_root/big")
        assert result.ok
        assert result.value == "x" * 2048
    finally:
        CompressorRegistry.set_default(old_default)


def test_json_write_freezes_mutable_value_before_flush(tmp_path):
    fs = TDSFileSystem()
    payload = {"items": [1]}
    fs.root.write_json("m", payload)
    payload["items"].append(2)

    TDSPersistence(tmp_path).flush(fs, parallel_nodes=False)
    result = TDSReader(tmp_path / "tds_root.tds").read_result("/tds_root/m")
    assert result.ok
    assert result.value == {"items": [1]}

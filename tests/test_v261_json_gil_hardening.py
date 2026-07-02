from pathlib import Path

import pytest

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.tds_json import dumps_canonical, dumps_pretty, loads_fast, loads_manifest, loads_snapshot


def test_v261_version():
    assert __version__ == "2.6.1"


def test_central_json_round_trip_and_strict_loaders():
    raw, dump_backend = dumps_canonical({"b": 2, "a": [1, True, None]})
    assert isinstance(raw, bytes)
    value, load_backend = loads_fast(raw)
    assert value == {"a": [1, True, None], "b": 2}
    assert dump_backend in {"orjson", "stdlib"}
    assert load_backend in {"simdjson", "stdlib"}
    pretty, _ = dumps_pretty({"x": 1})
    assert pretty.endswith("\n")
    manifest, _ = loads_manifest(b'{"tds_manifest_version":1}')
    assert manifest["tds_manifest_version"] == 1
    snapshot, _ = loads_snapshot(b'{"schema_version":1}')
    assert snapshot["schema_version"] == 1


def test_chunked_text_has_checksum_manifest_and_detects_corruption():
    fs = TDSFileSystem()
    text = "alphaβγ" * 200
    result = fs.root.write_text_chunked("doc", text, chunk_size=17)
    assert result.ok
    manifest = fs.root.read("doc")
    assert manifest["chunk_checksums32"]
    assert manifest["chunk_checksum_backend"] in {"native", "python"}
    assert fs.root.read_text("doc") == text

    first_chunk = manifest["chunks"][0]
    fs.root.write(first_chunk, "corrupted", fmt_id=fs.root._entries.get(first_chunk).fmt_id)
    with pytest.raises(ValueError):
        fs.root.read_text("doc")


def test_native_checksum32_many_if_available_matches_scalar():
    try:
        from staqtapp_tds import _native_index
    except Exception:
        pytest.skip("native extension unavailable")
    if not hasattr(_native_index, "checksum32_many"):
        pytest.skip("native checksum32_many unavailable")
    payloads = [b"alpha", b"beta", "γ".encode("utf-8")]
    assert list(_native_index.checksum32_many(payloads)) == [_native_index.checksum32(p) for p in payloads]


def test_json_telemetry_counters_on_snapshot():
    fs = TDSFileSystem()
    fs.root.write_json("payload", {"k": "v"})
    snap = fs.root.telemetry_manager.snapshot(force=True)
    perf = snap["performance"]
    assert perf["json_serialize_calls"] >= 1
    assert "avg_json_serialize_ms" in perf

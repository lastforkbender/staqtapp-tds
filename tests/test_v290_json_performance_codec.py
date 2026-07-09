from staqtapp_tds import __version__
from staqtapp_tds.tds_json import (
    backend_probe,
    codec_stats,
    dumps_canonical,
    dumps_status,
    loads_fast,
    preferred_dumps_backend,
    preferred_loads_backend,
    reset_codec_stats,
)


def test_v290_version():
    assert __version__ == "3.1.26"


def test_v290_json_backends_are_selected_without_hot_path_import_probe():
    info = backend_probe()
    assert info.loads_backend == preferred_loads_backend()
    assert info.dumps_backend == preferred_dumps_backend()
    assert info.loads_backend in {"simdjson", "stdlib"}
    assert info.dumps_backend in {"orjson", "stdlib"}


def test_v290_json_codec_stats_and_compact_status_payload():
    reset_codec_stats()
    payload = {"z": [1, 2, 3], "a": {"nested": True}}
    raw, dump_backend = dumps_canonical(payload)
    assert raw.startswith(b'{"')
    parsed, load_backend = loads_fast(raw)
    assert parsed == payload
    status_raw, status_backend, elapsed_ns = dumps_status({"status": "ok", "values": [payload]})
    assert isinstance(status_raw, bytes)
    assert b"\n" not in status_raw
    assert elapsed_ns >= 0
    assert dump_backend in {"orjson", "stdlib"}
    assert status_backend in {"orjson", "stdlib"}
    assert load_backend in {"simdjson", "stdlib"}
    stats = codec_stats()
    assert stats.loads_calls >= 1
    assert stats.dumps_calls >= 2
    assert stats.avg_dump_ns >= 0
    assert stats.to_dict()["loads_backend"] in {"simdjson", "stdlib"}

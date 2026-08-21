from concurrent.futures import ThreadPoolExecutor

import staqtapp_tds.tds_json as tds_json
from staqtapp_tds import RuntimeConfig, TDSFileSystem
from staqtapp_tds.backends.native_index import NativeEntryIndexBackend
from staqtapp_tds.telemetry import TelemetryManager


def test_json_hot_stats_are_exact_without_dataclass_materialization(monkeypatch) -> None:
    tds_json.reset_codec_stats()

    def reject_asdict(_value):
        raise AssertionError("JSON hot-path stats must not materialize a dataclass")

    monkeypatch.setattr(tds_json, "asdict", reject_asdict)
    workers = 4
    calls_per_worker = 100

    def round_trip(_worker: int) -> None:
        for index in range(calls_per_worker):
            raw, _backend = tds_json.dumps_canonical({"index": index})
            value, _backend = tds_json.loads_fast(raw)
            assert value == {"index": index}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(round_trip, range(workers)))

    stats = tds_json.codec_stats()
    expected = workers * calls_per_worker
    assert stats.dumps_calls == expected
    assert stats.loads_calls == expected
    assert stats.orjson_writes + stats.stdlib_writes == expected
    assert stats.simdjson_reads + stats.stdlib_reads == expected
    assert stats.dump_ns > 0
    assert stats.parse_ns > 0

    tds_json.reset_codec_stats()
    reset = tds_json.codec_stats()
    assert reset == tds_json.JsonCodecStats()


def test_native_telemetry_shapes_both_views_from_one_stats_scan() -> None:
    calls = 0

    class FakeNativeIndex:
        def stats(self):
            nonlocal calls
            calls += 1
            return {
                "backend": "native-c-swiss-entryindex",
                "size": 7,
                "capacity": 32,
                "tombstones": 2,
                "load_factor": 7 / 32,
                "max_probe": 3,
                "avg_probe": 1.25,
                "next_handle": 9,
                "namespace_id": 11,
                "index_epoch": 4,
                "native_stats_calls": calls,
                "python_native_transitions": 13,
                "gil_released_stats_scan": True,
            }

    backend = object.__new__(NativeEntryIndexBackend)
    backend._index = FakeNativeIndex()
    entry_stats, execution_stats = backend.telemetry_stats()

    assert calls == 1
    assert entry_stats.size == 7
    assert entry_stats.max_probe == 3
    assert execution_stats["namespace_id"] == 11
    assert execution_stats["native_stats_calls"] == 1
    assert execution_stats["python_native_transitions"] == 13


def test_filesystem_index_telemetry_uses_one_walk_and_normal_skips_it(monkeypatch) -> None:
    monkeypatch.setenv("STAQTAPP_TDS_INDEX_BACKEND", "python")
    config = RuntimeConfig.default().next_generation(telemetry_level="engineering")
    fs = TDSFileSystem("telemetry_root", runtime_config=config)
    fs.root.mkdir("a")
    fs.root.mkdir("b").mkdir("nested")

    original_walk = fs._walk_directories
    directories = list(original_walk())
    walk_calls = 0
    index_calls = 0

    def counted_walk():
        nonlocal walk_calls
        walk_calls += 1
        yield from original_walk()

    fs._walk_directories = counted_walk
    for directory in directories:
        original_stats = directory._entry_index.telemetry_stats

        def counted_stats(original_stats=original_stats):
            nonlocal index_calls
            index_calls += 1
            return original_stats()

        directory._entry_index.telemetry_stats = counted_stats

    combined = fs._index_stats_snapshot()
    assert walk_calls == 1
    assert index_calls == len(directories)
    assert combined["swiss"]["directory_count"] == len(directories)
    assert combined["radix"]["routers"] == len(directories)

    walk_calls = 0
    index_calls = 0
    engineering = fs.telemetry_manager.snapshot(force=True)
    assert walk_calls == 2  # one combined index walk plus the existing storage walk
    assert index_calls == len(directories)
    assert set(engineering["indexes"]) == {"swiss", "radix"}
    assert set(engineering["indexes"]["swiss"]) == {
        "entries",
        "directory_count",
        "backends",
        "max_probe",
        "average_probe",
        "gil_released_stats_scan",
    }

    fs.telemetry_manager.set_level("normal")
    walk_calls = 0
    index_calls = 0
    normal = fs.telemetry_manager.snapshot(force=True)
    assert walk_calls == 1
    assert index_calls == 0
    assert normal["indexes"] == {}
    assert normal["storage"]["directories"] == len(directories)


def test_combined_index_sampler_preserves_custom_indexes_name_and_fault_keys() -> None:
    manager = TelemetryManager(level="engineering")
    manager.register_index_sampler(lambda: {"swiss": {"size": 1}, "radix": {"nodes": 2}})
    manager.register_sampler("indexes", lambda: {"custom": "preserved"})

    snapshot = manager.snapshot(force=True)

    assert snapshot["indexes"]["swiss"] == {"size": 1}
    assert snapshot["indexes"]["radix"] == {"nodes": 2}
    assert snapshot["indexes"]["indexes"] == {"custom": "preserved"}

    def failed_indexes():
        raise RuntimeError("combined observation failed")

    manager.register_index_sampler(failed_indexes)
    failed = manager.snapshot(force=True)
    assert failed["components"]["sampler:swiss"]["status"] == "degraded"
    assert failed["components"]["sampler:radix"]["status"] == "degraded"
    assert "sampler:indexes" not in failed["components"]

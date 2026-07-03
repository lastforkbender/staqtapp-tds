import sys

from staqtapp_tds import __version__, EntryIndex, TraceRecord, TraceSetManifest, AggregationRecord
from staqtapp_tds.metadata import EntryDescriptor, ChunkDescriptor, NamespaceDescriptor, ExecutionCounters, RuntimeSnapshot
from staqtapp_tds.telemetry import TelemetryManager


def test_version_centralized_v242():
    assert __version__ == "2.7.8"


def test_metadata_records_are_slotted_and_immutable():
    records = [
        EntryDescriptor("entry-1", key="alpha"),
        ChunkDescriptor("chunk-1", entry_id="entry-1"),
        NamespaceDescriptor("root", path="/"),
        RuntimeSnapshot(schema_version=1),
        TraceRecord(run_id="run-1", trace_id="trace-1", rank_method="external-verifier"),
        TraceSetManifest(run_id="run-1", set_id="set-1", trace_ids=("trace-1",)),
        AggregationRecord(run_id="run-1", aggregation_id="agg-1", output_entry="out", derived_from=("trace-1",)),
    ]
    for rec in records:
        assert not hasattr(rec, "__dict__")
        try:
            rec.extra = "not allowed"  # type: ignore[attr-defined]
        except Exception:
            pass
        else:
            raise AssertionError("slotted metadata accepted dynamic attributes")


def test_native_batch_put_and_pop_many_when_available():
    try:
        idx = EntryIndex(backend="native")
    except RuntimeError:
        return
    handles = idx.put_many([("a", 1), ("b", 2), ("c", 3)])
    assert len(handles) == 3
    assert idx.get_handles(["a", "b", "c", "missing"])[-1] == -1
    assert idx.pop_many(["a", "missing", "c"]) == [1, None, 3]
    stats = idx.native_execution_stats()
    assert stats["gil_released_put_many"] is True
    assert stats["gil_released_pop_many"] is True
    assert stats["native_batch_put_calls"] >= 1
    assert stats["native_batch_pop_calls"] >= 1


def test_native_checksum_and_utf8_chunk_bounds_when_available():
    try:
        from staqtapp_tds import _native_index
    except Exception:
        return
    payload = "alpha βeta gamma".encode("utf-8")
    assert _native_index.checksum32(payload) == _native_index.checksum32(payload)
    bounds = _native_index.utf8_chunk_bounds(payload, 7)
    assert bounds[-1] == len(payload)
    for b in bounds:
        payload[:b].decode("utf-8")


def test_execution_counters_include_pool_reuse_fields():
    tm = TelemetryManager(snapshot_interval_seconds=0.25)
    tm.merge_native_execution_stats({"pool_reuse_count": 3, "pool_allocator_calls": 7, "native_batch_put_calls": 2})
    snap = tm.snapshot(force=True)
    perf = snap["performance"]
    assert perf["pool_reuse_count"] == 3
    assert perf["pool_allocator_calls"] == 7
    assert perf["native_batch_ops"] >= 2
    assert ExecutionCounters(native_backend_ops=8, python_backend_ops=2).native_percent() == 80.0

from staqtapp_tds import __version__
from staqtapp_tds.pressure import calculate_pressure_snapshot
from staqtapp_tds.telemetry import TelemetryManager


def test_v272_version():
    assert __version__ == "3.5.3"


def test_pressure_engine_exposes_component_scores_without_hot_path_state():
    snap = calculate_pressure_snapshot(
        {"chunk_pending": 4, "telemetry_dropped": 2, "errors": 1},
        native_counters={
            "ring_capacity": 100,
            "ring_occupancy": 80,
            "events_dropped": 3,
            "event_ring_wraparounds": 1,
            "lock_transitions": 9000,
            "memory_transitions": 4000,
            "slot_transitions": 2000,
            "index_transitions": 3000,
        },
        performance={
            "reads_per_sec": 4000,
            "writes_per_sec": 2200,
            "lookups_per_sec": 5000,
            "avg_lookup_ms": 3.0,
            "avg_write_ms": 5.0,
            "python_native_transitions_per_sec": 6000,
            "native_batch_ops_per_sec": 3000,
            "pool_allocator_calls": 5000,
            "pool_reuse_percent": 40,
        },
        storage={"chunk_pending": 4, "chunk_quarantined": 1, "telemetry_dropped": 2, "errors": 1},
        indexes={"swiss": {"average_probe": 3.5, "max_probe": 8, "load_factor": 0.91}},
        snapshot_lag=3,
    ).to_dict()
    assert snap["schema_version"] == 1
    assert snap["score"] > 0
    assert snap["ring_buffer_pressure"] >= 75
    assert snap["lock_pressure"] > 0
    assert snap["memory_pressure"] > 0
    assert snap["bridge_pressure"] > 0
    assert snap["dominant_component"] in snap["components"]
    assert snap["causes"]


def test_telemetry_snapshot_includes_v272_pressure_fields():
    tm = TelemetryManager(snapshot_interval_seconds=0.0, level="engineering")
    tm.record_execution(native_ops=10, python_ops=2, transitions=15, batch_ops=3, gil_released_ns=1000)
    tm.record_chunk_transition("pending", 2)
    snap = tm.snapshot()
    pressure = snap["pressure"]
    assert "components" in pressure
    assert "engine_pressure" in pressure
    assert "ring_buffer_pressure" in pressure
    assert "bridge_pressure" in pressure
    assert "dominant_component" in pressure

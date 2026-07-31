from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from staqtapp_tds.diagnostics import (
    DiagnosticEvent,
    native_diag_emit,
    native_diag_reset,
    native_diag_set_sampling,
    native_diag_snapshot,
    native_diagnostics_available,
)
from staqtapp_tds.native.manager import NativeEngineManager


def require_native():
    if not native_diagnostics_available():
        pytest.skip("native diagnostics extension not built")


def test_v360_diagnostic_protocol_and_default_sampling_are_declared():
    require_native()
    from staqtapp_tds import _native_index

    assert _native_index.TDS_NATIVE_DIAG_PROTOCOL == (
        "c11-atomic-slot-seqlock-mpsc-v1"
    )
    assert _native_index.TDS_NATIVE_DIAG_SAMPLING == (
        "burst=64;period=1024;manual=all"
    )
    assert hasattr(_native_index, "diag_set_sampling")

    module, report = NativeEngineManager().inspect_module(
        "staqtapp_tds._native_index"
    )
    assert module is _native_index
    assert report.compatible is True
    assert report.capabilities["diag_protocol"] == (
        "c11-atomic-slot-seqlock-mpsc-v1"
    )
    assert report.capabilities["diag_sampling"] == (
        "burst=64;period=1024;manual=all"
    )


def test_v360_automatic_events_are_sampled_but_mechanical_counters_are_exact():
    require_native()
    from staqtapp_tds import _native_index

    native_diag_reset()
    assert native_diag_set_sampling(interval=16, burst=4) is True
    index = _native_index.NativeHandleIndex(capacity=16)
    handle = index.put("sampled-key")
    for _ in range(200):
        assert index.get_handle("sampled-key") == handle

    snapshot = native_diag_snapshot(event_limit=4096)
    counters = snapshot.counters
    assert counters["native_lookup_calls"] == 200
    assert counters["index_transitions"] >= 200
    assert counters["automatic_event_attempts"] > counters["events_emitted"]
    assert counters["events_sampled_out"] > 0
    assert counters["sampling_interval"] == 16
    assert counters["sampling_burst"] == 4
    assert counters["event_attempts"] == (
        counters["automatic_event_attempts"]
        + counters["manual_event_attempts"]
    )


def test_v360_manual_events_are_never_sampled():
    require_native()

    native_diag_reset()
    assert native_diag_set_sampling(interval=1_000_000, burst=0) is True
    for value in range(32):
        assert native_diag_emit(
            DiagnosticEvent.NATIVE_OPERATION,
            value,
            value + 1,
        ) is True

    snapshot = native_diag_snapshot(event_limit=64)
    manual = [
        event
        for event in snapshot.recent_events
        if event["code"] == int(DiagnosticEvent.NATIVE_OPERATION)
    ]
    assert len(manual) == 32
    assert snapshot.counters["manual_event_attempts"] == 32
    assert snapshot.counters["events_sampled_out"] == 0


def test_v360_concurrent_gil_free_publishers_produce_stable_complete_events():
    require_native()
    from staqtapp_tds import _native_index

    index = _native_index.NativeHandleIndex(capacity=512)
    keys = [f"key-{value:04d}" for value in range(256)]
    handles = index.put_many(keys)
    native_diag_reset()
    assert native_diag_set_sampling(interval=1, burst=0) is True

    def worker(offset: int) -> None:
        for round_number in range(16):
            for position in range(offset, len(keys), 8):
                expected = handles[position]
                assert index.get_handle(keys[position]) == expected
                if round_number % 4 == 0:
                    assert index.get_handle("absent-key") == -1

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, offset) for offset in range(8)]
        for future in futures:
            future.result()

    snapshot = native_diag_snapshot(event_limit=4096)
    sequences = [int(event["seq"]) for event in snapshot.recent_events]
    assert sequences == sorted(set(sequences))
    assert snapshot.counters["events_emitted"] > 0
    assert snapshot.counters["active_event_writers"] == 0
    for event in snapshot.recent_events:
        assert set(event).issuperset(
            {
                "seq",
                "timestamp_ns",
                "code",
                "flags",
                "subsystem",
                "object_id",
                "value_a",
                "value_b",
            }
        )
        assert int(event["seq"]) > 0
        assert int(event["timestamp_ns"]) > 0


def test_v360_reset_is_safe_while_gil_free_publishers_are_active():
    require_native()
    from staqtapp_tds import _native_index

    index = _native_index.NativeHandleIndex(capacity=256)
    keys = [f"reset-key-{value:04d}" for value in range(128)]
    handles = index.put_many(keys)
    native_diag_reset()
    assert native_diag_set_sampling(interval=1, burst=0) is True
    started = threading.Event()

    def worker(offset: int) -> None:
        started.set()
        for _ in range(48):
            for position in range(offset, len(keys), 4):
                assert index.get_handle(keys[position]) == handles[position]

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, offset) for offset in range(4)]
        assert started.wait(timeout=5.0)
        for _ in range(8):
            native_diag_reset()
        for future in futures:
            future.result()

    snapshot = native_diag_snapshot(event_limit=256)
    sequences = [int(event["seq"]) for event in snapshot.recent_events]
    assert sequences == sorted(set(sequences))
    assert snapshot.counters["reset_requests"] >= 1
    assert snapshot.counters["active_event_writers"] == 0
    assert snapshot.counters["resetting"] == 0


def test_v360_default_sampling_bounds_hot_path_event_volume():
    require_native()
    from staqtapp_tds import _native_index

    index = _native_index.NativeHandleIndex(capacity=16)
    handle = index.put("default-sampling")
    native_diag_reset()
    assert native_diag_set_sampling(interval=1024, burst=64) is True
    for _ in range(10_000):
        assert index.get_handle("default-sampling") == handle

    counters = native_diag_snapshot(event_limit=0).counters
    assert counters["native_lookup_calls"] == 10_000
    assert counters["events_sampled_out"] > 9_000
    assert counters["events_emitted"] < 100

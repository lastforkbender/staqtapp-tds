from __future__ import annotations

import pytest

from staqtapp_tds.diagnostics import (
    DiagnosticEvent,
    NativeDiagnosticSnapshot,
    native_diag_emit,
    native_diag_mark_degraded,
    native_diag_reset,
    native_diag_set_enabled,
    native_diag_snapshot,
    native_diagnostics_available,
)
from staqtapp_tds.telemetry import TelemetryManager


def require_native():
    if not native_diagnostics_available():
        pytest.skip("native diagnostics extension not built")


def test_native_diagnostic_snapshot_shape_and_counters():
    require_native()
    native_diag_reset()
    from staqtapp_tds import _native_index

    idx = _native_index.NativeHandleIndex()
    assert idx.put("alpha") > 0
    assert idx.get_handle("alpha") > 0
    assert _native_index.checksum32_many([b"a", b"bc"]) == [_native_index.checksum32(b"a"), _native_index.checksum32(b"bc")]

    snap = native_diag_snapshot(event_limit=8)
    assert isinstance(snap, NativeDiagnosticSnapshot)
    assert snap.enabled is True
    assert snap.subsystem == "native_diagnostics"
    assert snap.counters["gil_released_calls"] >= 4
    assert snap.counters["python_native_transitions"] >= 4
    assert snap.counters["native_put_calls"] >= 1
    assert snap.counters["native_lookup_calls"] >= 1
    assert snap.counters["native_checksum_batch_calls"] >= 1
    assert snap.sequence >= 1
    assert len(snap.recent_events) <= 8


def test_native_diagnostics_enable_and_degraded_state_do_not_break_storage():
    require_native()
    native_diag_reset()
    from staqtapp_tds import _native_index

    idx = _native_index.NativeHandleIndex()
    native_diag_set_enabled(False)
    handle = idx.put("disabled-path")
    assert idx.get_handle("disabled-path") == handle
    disabled = native_diag_snapshot()
    assert disabled.enabled is False

    native_diag_set_enabled(True)
    native_diag_mark_degraded(True)
    assert idx.put("still-working") > 0
    degraded = native_diag_snapshot()
    assert degraded.degraded is True
    assert degraded.counters.get("degraded_count", 0) >= 1
    native_diag_mark_degraded(False)


def test_native_diagnostic_event_ring_is_bounded_and_loss_tolerant():
    require_native()
    native_diag_reset()
    initial = native_diag_snapshot(event_limit=0)
    capacity = int(initial.counters.get("ring_capacity", 1024)) or 1024
    for i in range(capacity + 128):
        assert native_diag_emit(DiagnosticEvent.NATIVE_OPERATION, i, i + 1) is True
    snap = native_diag_snapshot(event_limit=capacity)
    assert len(snap.recent_events) == capacity
    assert snap.counters["events_emitted"] >= capacity + 128
    assert snap.counters["events_dropped"] > 0
    assert snap.counters["event_ring_wraparounds"] > 0


def test_telemetry_snapshot_includes_native_diagnostics_without_sampler_failure():
    require_native()
    native_diag_reset()
    from staqtapp_tds import _native_index

    _native_index.checksum32(b"telemetry")
    manager = TelemetryManager(snapshot_interval_seconds=0.25)
    snap = manager.snapshot(force=True)
    assert "native_diagnostics" in snap
    nd = snap["native_diagnostics"]
    assert nd["subsystem"] == "native_diagnostics"
    assert "native_diagnostics" in snap["components"]
    assert snap["components"]["native_diagnostics"]["status"] in {"enabled", "degraded", "disabled"}

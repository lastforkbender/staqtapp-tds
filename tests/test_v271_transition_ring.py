from __future__ import annotations

import pytest

from staqtapp_tds.diagnostics import DiagnosticEvent, native_diag_emit, native_diag_reset, native_diag_snapshot, native_diagnostics_available


def require_native():
    if not native_diagnostics_available():
        pytest.skip("native diagnostics extension not built")


def test_v271_transition_events_are_named_and_grouped():
    require_native()
    native_diag_reset()
    from staqtapp_tds import _native_index

    idx = _native_index.NativeHandleIndex(capacity=4)
    h = idx.put("alpha")
    assert idx.get_handle("alpha") == h
    assert idx.get_handle("missing") == -1
    assert idx.pop("alpha") == h

    snap = native_diag_snapshot(event_limit=64)
    names = {event.get("event_name") for event in snap.recent_events}
    subsystems = {event.get("subsystem_name") for event in snap.recent_events}
    assert "slot_allocated" in names
    assert "slot_written" in names
    assert "slot_visible" in names
    assert "slot_deleted" in names
    assert "index_lookup_hit" in names
    assert "index_lookup_miss" in names
    assert "slot_lifecycle" in subsystems
    assert "index_engine" in subsystems
    assert snap.counters["slot_transitions"] >= 4
    assert snap.counters["index_transitions"] >= 2
    assert snap.counters["ring_capacity"] >= 1024


def test_v271_manual_transition_emit_uses_taxonomy():
    require_native()
    native_diag_reset()
    assert native_diag_emit(DiagnosticEvent.SLOT_UPDATED, 7, 9) is True
    snap = native_diag_snapshot(event_limit=4)
    assert snap.recent_events[-1]["event_name"] == "slot_updated"
    assert snap.counters["slot_transitions"] >= 1

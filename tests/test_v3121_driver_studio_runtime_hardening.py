import json

from staqtapp_tds import __version__
from staqtapp_tds.studio_pyqt5 import (
    StudioLiveEventKind,
    StudioLivePanelRuntime,
    StudioManualBuilderRuntimeStatus,
    StudioManualBuilderUIRuntime,
    StudioQtBridge,
    studio_live_event_bridge_capability_matrix,
    studio_live_panel_runtime_capability_matrix,
    studio_manual_builder_ui_runtime_capability_matrix,
)


class OddValue:
    def __str__(self):
        return "odd-value"


def test_v3121_version():
    assert __version__ == "3.1.26"


def test_live_event_bridge_accounts_for_bounded_stream_drops_without_mutation():
    runtime = StudioLivePanelRuntime(max_events=2)

    runtime.event_bridge.refresh(reason="paint-1", timestamp="t1")
    runtime.event_bridge.refresh(reason="paint-2", timestamp="t2")
    runtime.event_bridge.refresh(reason="paint-3", timestamp="t3")

    state = runtime.current_state(include_packets=True)
    payload = state.signal_payload()

    assert state.cursor == 3
    assert state.consumed_cursor == 0
    assert state.event_retention_gap is True
    assert state.dropped_event_count == 1
    assert state.runtime_warnings == (
        "live event retention gap detected; older events were dropped before runtime consumption",
    )
    assert [event.event_id for event in state.events] == ["live-000002", "live-000003"]
    assert all(event.kind is StudioLiveEventKind.SNAPSHOT_REFRESH for event in state.events)
    assert payload["event_retention_gap"] is True
    assert payload["dropped_event_count"] == 1
    assert payload["runtime_warnings"] == state.runtime_warnings
    assert payload["capability_matrix"]["detect_event_retention_gap"] is True
    assert payload["capability_matrix"]["mutate_registry"] is False


def test_live_event_retention_gap_clears_after_runtime_consumes_current_cursor():
    runtime = StudioLivePanelRuntime(max_events=2)
    for idx in range(4):
        runtime.event_bridge.refresh(reason=f"paint-{idx}", timestamp=f"t{idx}")

    gap_state = runtime.current_state(include_packets=True)
    consumed = runtime.consume(include_packets=True)
    quiet = runtime.current_state(include_packets=True)

    assert gap_state.event_retention_gap is True
    assert consumed.event_retention_gap is True
    assert runtime.consumed_cursor == 4
    assert quiet.events == ()
    assert quiet.dirty_marks == ()
    assert quiet.refresh_packets == ()
    assert quiet.event_retention_gap is False
    assert quiet.dropped_event_count == 2
    assert quiet.runtime_warnings == ()


def test_live_bridge_signal_payload_exposes_retention_floor_and_drop_accounting():
    runtime = StudioLivePanelRuntime(max_events=2)
    for idx in range(3):
        runtime.event_bridge.refresh(reason=f"refresh-{idx}")

    live_state = runtime.event_bridge.current_state()
    payload = live_state.signal_payload()

    assert live_state.retained_cursor_floor == 2
    assert live_state.dropped_event_count == 1
    assert live_state.event_retention_gap is True
    assert live_state.has_retention_gap_since(0) is True
    assert live_state.has_retention_gap_since(2) is False
    assert payload["retained_cursor_floor"] == 2
    assert payload["dropped_event_count"] == 1
    assert payload["event_retention_gap"] is True


def test_manual_builder_runtime_signal_payload_is_json_safe_for_unusual_form_values():
    runtime = StudioManualBuilderUIRuntime()
    payload = dict(runtime.default_form_payload())
    payload.update(
        {
            "driver_id": "JsonSafeDriver",
            "extra_object": OddValue(),
            "extra_mapping": {"nested": OddValue()},
            "extra_set": {"beta", "alpha"},
        }
    )

    state = runtime.preview_form_payload(payload)
    signal = state.signal_payload()

    assert state.status is StudioManualBuilderRuntimeStatus.PREVIEW_READY
    assert signal["form_payload"]["extra_object"] == "odd-value"
    assert signal["form_payload"]["extra_mapping"] == {"nested": "odd-value"}
    assert signal["form_payload"]["extra_set"] == ("alpha", "beta")
    assert signal["capability_matrix"]["signal_payload_json_safe"] is True
    json.dumps(signal)


def test_manual_builder_runtime_rejected_state_payload_remains_json_safe():
    runtime = StudioManualBuilderUIRuntime()
    payload = dict(runtime.default_form_payload())
    payload.update({"driver_id": "bad driver id", "extra_object": OddValue()})

    state = runtime.preview_form_payload(payload)
    signal = state.signal_payload()

    assert state.ok is False
    assert state.status is StudioManualBuilderRuntimeStatus.INPUT_REJECTED
    assert signal["form_payload"]["extra_object"] == "odd-value"
    assert signal["capability_matrix"]["approve_driver"] is False
    json.dumps(signal)


def test_runtime_hardening_capability_matrices_preserve_studio_boundaries():
    bridge_matrix = studio_live_event_bridge_capability_matrix()
    runtime_matrix = studio_live_panel_runtime_capability_matrix()
    manual_matrix = studio_manual_builder_ui_runtime_capability_matrix()

    assert bridge_matrix["detect_event_retention_gap"] is True
    assert bridge_matrix["event_stream_drop_accounting"] is True
    assert runtime_matrix["detect_event_retention_gap"] is True
    assert runtime_matrix["runtime_warning_payloads"] is True
    assert manual_matrix["signal_payload_json_safe"] is True

    for matrix in (bridge_matrix, runtime_matrix, manual_matrix):
        assert matrix["approve_driver"] is False
        assert matrix["sign_driver"] is False
        assert matrix["activate_driver"] is False
        assert matrix["mutate_registry"] is False
        assert matrix["store_private_keys"] is False
        assert matrix["bypass_policy"] is False


def test_bridge_runtime_factory_and_manual_builder_factory_remain_compatible():
    bridge = StudioQtBridge()
    runtime = bridge.live_panel_runtime(max_events=4)
    manual_runtime = bridge.manual_builder_ui_runtime()

    assert isinstance(runtime, StudioLivePanelRuntime)
    assert isinstance(manual_runtime, StudioManualBuilderUIRuntime)
    assert runtime.capability_matrix()["live_runtime_mutates_backend"] is False
    assert manual_runtime.capability_matrix()["auto_runs_foundry"] is False

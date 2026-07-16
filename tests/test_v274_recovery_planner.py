from __future__ import annotations

from staqtapp_tds import __version__
from staqtapp_tds.recovery import build_recovery_plan
from staqtapp_tds.telemetry import TelemetryManager
from staqtapp_tds.admin.panel import AdminPanelServer, render_dashboard_html


def test_v274_version():
    assert __version__ == "3.5.3"


def test_recovery_planner_generates_advisory_actions_from_pressure_snapshot():
    plan = build_recovery_plan(
        {
            "score": 72,
            "dominant_component": "diagnostic_ring",
            "ring_buffer_pressure": 86,
            "bridge_pressure": 64,
            "lock_pressure": 47,
        },
        native_diagnostics={"counters": {"ring_occupancy": 3900, "ring_capacity": 4096, "events_dropped": 4, "lock_transitions": 2200}},
        performance={"python_native_transitions_per_sec": 1800, "pool_reuse_percent": 81},
        storage={"telemetry_dropped": 2},
    ).to_dict()
    assert plan["schema_version"] == 1
    assert plan["status"] in {"advisory", "critical"}
    assert plan["action_count"] >= 2
    assert plan["automatic_actions"] == 0
    assert plan["actions"][0]["automatic"] is False
    assert any(a["code"] == "REC_DIAG_RING_RELIEF" for a in plan["actions"])
    assert plan["guardrails"]


def test_telemetry_snapshot_includes_recovery_planner_output():
    tm = TelemetryManager(snapshot_interval_seconds=0.0, level="engineering")
    tm.record_execution(native_ops=25, python_ops=5, transitions=60, batch_ops=10, gil_released_ns=1000)
    tm.record_chunk_transition("pending", 3)
    snap = tm.snapshot()
    recovery = snap["recovery"]
    assert recovery["schema_version"] == 1
    assert "actions" in recovery
    assert recovery["automatic_actions"] == 0
    assert recovery["guardrails"]


def test_dashboard_renders_recovery_planner_console_components():
    html = render_dashboard_html(version="2.8.1")
    assert "recovery-planner-page" in html
    assert "recovery-actions" in html
    assert "recovery-guardrails" in html
    panel = AdminPanelServer()
    js_asset = panel._static_asset("/static/js/dashboard.js")
    assert js_asset is not None
    js, ctype = js_asset
    assert ctype == "application/javascript"
    assert b"renderRecoveryPlanner" in js
    assert b"recovery-actions" in js

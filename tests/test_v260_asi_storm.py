from staqtapp_tds import __version__, TDSFileSystem, TelemetryManager, PressureMode, VFSState, estimate_pressure
from staqtapp_tds.admin.panel import render_dashboard_html


def test_version_v260():
    assert __version__ == "2.8.0"


def test_pressure_model_modes_and_vfs_state():
    low = estimate_pressure({})
    assert low.mode is PressureMode.NORMAL
    assert low.vfs_state is VFSState.ACTIVE
    high = estimate_pressure({"chunk_pending": 30, "telemetry_dropped": 15, "python_native_transitions": 1800, "errors": 5, "chunk_quarantined": 2})
    assert high.score >= 60
    assert high.mode in {PressureMode.HIGH_PRESSURE, PressureMode.CRITICAL_PRESSURE, PressureMode.PROTECTIVE_READ_ONLY}


def test_telemetry_snapshot_contains_pressure_and_chunk_lifecycle():
    tm = TelemetryManager(snapshot_interval_seconds=0.25)
    tm.record_chunk_transition("pending", 3)
    tm.record_chunk_transition("sealed", 3)
    tm.record_chunk_transition("verified", 3)
    tm.record_chunk_transition("indexed", 2)
    tm.record_chunk_transition("exposed", 2)
    snap = tm.snapshot(force=True)
    assert "pressure" in snap
    assert snap["pressure"]["chunk_pending_count"] == 3
    assert snap["storage"]["chunk_verified"] == 3
    assert snap["storage"]["chunk_indexed"] == 2


def test_chunked_text_records_lifecycle_and_round_trips():
    fs = TDSFileSystem()
    text = "hello 🌍 " * 200
    result = fs.root.write_text_chunked("story", text, chunk_size=17, overwrite=True)
    assert result.ok
    assert fs.root.read_text("story") == text
    snap = fs.telemetry_manager.snapshot(force=True)
    assert snap["storage"]["chunk_sealed"] >= result.meta["chunks"]
    assert snap["storage"]["chunk_exposed"] >= result.meta["chunks"]


def test_dashboard_contains_pressure_panel_and_custom_svg_assets():
    html = render_dashboard_html(version="2.6.1")
    assert "ASI Pressure" in html
    assert "/static/icons/pressure.svg" in html
    assert "/static/icons/storm.svg" in html
    assert "🟢" not in html and "🟡" not in html and "🔴" not in html

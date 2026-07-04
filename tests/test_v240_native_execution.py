from staqtapp_tds import EntryIndex, TelemetryManager, TDSFileSystem
from staqtapp_tds.admin.panel import render_dashboard_html


def test_execution_mode_telemetry_snapshot_fields():
    tm = TelemetryManager(snapshot_interval_seconds=0.25)
    tm.record_execution(native_ops=10, python_ops=2, transitions=4, batch_ops=1, gil_released_ns=1000)
    snap = tm.snapshot(force=True)
    perf = snap["performance"]
    assert perf["native_execution_percent"] > perf["python_execution_percent"]
    assert perf["gil_released_percent"] >= 0
    assert perf["python_native_transitions"] == 4
    assert perf["native_batch_ops"] == 1


def test_native_entry_index_reports_execution_stats_when_available():
    try:
        idx = EntryIndex(backend="native")
    except RuntimeError:
        return
    idx.put("alpha", object())
    idx.get_handle("alpha")
    idx.get_handles(["alpha", "missing"])
    assert "alpha" in idx
    stats = idx.native_execution_stats()
    assert stats["gil_released_put"] is True
    assert stats["gil_released_get_handle"] is True
    assert stats["gil_released_get_handles"] is True
    assert stats["native_put_calls"] >= 1
    assert stats["python_native_transitions"] >= 3


def test_filesystem_dashboard_snapshot_contains_execution_percentages():
    fs = TDSFileSystem("root", telemetry_manager=TelemetryManager(snapshot_interval_seconds=0.25))
    fs.root.write("alpha", "payload")
    assert fs.root.read_value("alpha") == "payload"
    snap = fs.telemetry_manager.snapshot(force=True)
    perf = snap["performance"]
    assert "native_execution_percent" in perf
    assert "python_execution_percent" in perf
    assert "python_native_transitions_per_sec" in perf


def test_professional_dashboard_has_execution_mode_fields():
    html = render_dashboard_html(version="2.5.0", refresh_seconds=2)
    assert "Native Execution" in html
    assert "Python↔Native" in html
    assert "native-exec-pct" in html

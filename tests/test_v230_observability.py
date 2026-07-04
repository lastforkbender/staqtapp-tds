from __future__ import annotations

import threading

from staqtapp_tds import TDSFileSystem, TelemetryManager, RuntimeConfig, ConfigRegistry
from staqtapp_tds.admin import AdminControl, LocalAuthProvider
from staqtapp_tds.admin.panel import AdminPanelServer, HTML


def test_observation_snapshot_counts_reads_writes_and_behavior():
    fs = TDSFileSystem(telemetry_manager=TelemetryManager(snapshot_interval_seconds=0.25))
    fs.root.write("a", "alpha")
    fs.root.write("b", "beta")
    assert fs.root.read("a") == "alpha"
    snap = fs.observation_snapshot(force=True)
    assert snap["schema_version"] == 1
    assert snap["performance"]["write_count"] >= 2
    assert snap["performance"]["read_count"] >= 1
    assert snap["storage"]["entries"] >= 2
    assert snap["indexes"]["swiss"]["entries"] >= 2
    assert snap["indexes"]["radix"]["routers"] >= 1
    assert snap["behavior"]["workload_mode"] in {"read-heavy", "write-heavy", "balanced", "idle"}


def test_admin_status_can_include_observation_source_without_dashboard_scanning_directly():
    registry = ConfigRegistry(RuntimeConfig.default(config_id="rc-001", generation=1))
    fs = TDSFileSystem(config_registry=registry)
    fs.root.write_text_chunked("doc", "hello 🌍" * 100, chunk_size=32)
    control = AdminControl(registry=registry, auth=LocalAuthProvider("s"), observation_source=fs)
    status = control.status()
    assert status["active"]["config_id"] == "rc-001"
    assert status["observation"]["storage"]["chunks_created"] > 0
    assert "performance" in status["observation"]


def test_panel_exposes_v23_observability_ui_tokens():
    assert "Telemetry Cache" in HTML
    assert "Reads/sec" in HTML
    assert "Writes/sec" in HTML
    assert "WORKLOAD" in HTML
    assert "Compression" in HTML


def test_telemetry_manager_threaded_updates_are_consistent_enough():
    tm = TelemetryManager(snapshot_interval_seconds=0.25)

    def worker():
        for _ in range(100):
            tm.record_read(1000, hit=True, backend="native")
            tm.record_write(2000, raw_size=100, stored_size=50, backend="native")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = tm.snapshot(force=True)
    assert snap["performance"]["read_count"] == 400
    assert snap["performance"]["write_count"] == 400
    assert snap["behavior"]["compression_ratio"] == 2.0
    assert snap["performance"]["native_backend_ops"] == 800


def test_admin_panel_status_snapshot_includes_observation_when_source_present():
    fs = TDSFileSystem()
    fs.root.write("x", 1)
    panel = AdminPanelServer(control=AdminControl(registry=fs.config_registry, observation_source=fs))
    snap = panel._status_snapshot()
    assert "observation" in snap
    assert snap["observation"]["performance"]["write_count"] >= 1

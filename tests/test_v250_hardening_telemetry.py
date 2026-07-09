import time

from staqtapp_tds import (
    __version__,
    TDSFileSystem,
    TelemetryLevel,
    TelemetryManager,
    TelemetryPublisherThread,
    verify,
)
from staqtapp_tds.config import RuntimeConfig


def test_version_v251():
    assert __version__ == "3.1.26"


def test_telemetry_levels_gate_engineering_samplers():
    tm = TelemetryManager(snapshot_interval_seconds=0.25, level=TelemetryLevel.MINIMAL)
    called = {"swiss": 0}

    def swiss():
        called["swiss"] += 1
        return {"entries": 1}

    tm.register_sampler("swiss", swiss)
    snap = tm.snapshot(force=True)
    assert snap["health"]["telemetry_level"] == "minimal"
    assert snap["indexes"] == {}
    assert called["swiss"] == 0

    tm.set_level("engineering")
    snap = tm.snapshot(force=True)
    assert "swiss" in snap["indexes"]
    assert called["swiss"] == 1


def test_telemetry_publisher_thread_creates_one_way_snapshot():
    tm = TelemetryManager(snapshot_interval_seconds=0.25, level="normal")
    tm.record_read(1000, backend="python")
    publisher = TelemetryPublisherThread(tm, interval_seconds=0.05).start()
    try:
        time.sleep(0.12)
        snap = tm.latest_snapshot()
        assert snap["health"]["publisher_updates"] >= 1
        assert snap["performance"]["reads_per_sec"] >= 0
        assert snap["system_health"] in {"HEALTHY", "ATTENTION", "STALE", "DISABLED"}
    finally:
        publisher.stop()


def test_health_verifier_reports_clean_in_memory_store():
    fs = TDSFileSystem("health_root")
    fs.root.write("alpha", b"payload")
    report = verify(fs)
    data = report.to_dict()
    assert data["status"] == "healthy"
    assert data["score"] == 100
    assert {c["name"] for c in data["checks"]} >= {"telemetry_snapshot", "runtime_config", "directory_walk", "index_consistency"}


def test_runtime_config_telemetry_level_validation():
    cfg = RuntimeConfig.default().next_generation(telemetry_level="engineering")
    assert cfg.to_dict()["telemetry_level"] == "engineering"
    try:
        RuntimeConfig.default().next_generation(telemetry_level="loud")
    except ValueError as exc:
        assert "telemetry_level" in str(exc)
    else:
        raise AssertionError("invalid telemetry level accepted")


def test_local_admin_default_secret_refuses_nonlocal_bind():
    from staqtapp_tds.admin import AdminControl, LocalAuthProvider
    from staqtapp_tds.admin.panel import AdminPanelServer

    control = AdminControl(auth=LocalAuthProvider())
    AdminPanelServer(control=control, host="127.0.0.1")
    try:
        AdminPanelServer(control=control, host="0.0.0.0")
    except ValueError as exc:
        assert "local-dev-admin-secret" in str(exc)
    else:
        raise AssertionError("default admin secret allowed non-local bind")


def test_execution_timeline_is_snapshot_cached():
    tm = TelemetryManager(snapshot_interval_seconds=0.25, level="engineering")
    tm.record_execution(native_ops=3, python_ops=1, transitions=2, gil_released_ns=100)
    snap = tm.snapshot(force=True)
    timeline = snap["performance"]["execution_timeline"]
    assert timeline
    assert timeline[-1]["native_execution_percent"] >= 70
    assert snap["performance"]["gil_released_ops_per_sec"] >= 0

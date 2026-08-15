from __future__ import annotations

import json
import multiprocessing
import os
import select
import signal
import time
from pathlib import Path

import pytest

from staqtapp_tds import TDSFileSystem, TelemetryManager, TelemetryPublisherThread
from staqtapp_tds import admin as admin_package
from staqtapp_tds.admin import app
from staqtapp_tds.admin import console
from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.admin.panel import AdminPanelServer
from staqtapp_tds.admin.workspace import (
    MAX_WORKSPACE_SNAPSHOT_BYTES,
    WORKSPACE_SCHEMA,
    WORKSPACE_SCHEMA_VERSION,
    WORKSPACE_SNAPSHOT_FILENAME,
    WorkspaceMountError,
    WorkspaceSnapshotError,
    WorkspaceTelemetryPublisher,
    WorkspaceTelemetrySource,
    WorkspaceUnavailableError,
    attach_workspace_telemetry,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _publish_from_child(mount_path: str) -> None:
    WorkspaceTelemetryPublisher(mount_path).publish(
        {"performance": {"producer_pid": os.getpid()}}
    )


def test_manual_publisher_is_side_effect_free_until_publish_and_is_canonical(tmp_path: Path):
    mount = tmp_path / "workspace"
    manager = TelemetryManager(snapshot_interval_seconds=0.25)
    publisher = attach_workspace_telemetry(manager, mount)

    assert not mount.exists()
    assert not publisher.running

    # A workspace exporter is a post-publication sink.  It must not assemble a
    # manager snapshot from the caller/browser path when no producer has run.
    assert manager.published_snapshot() is None
    with pytest.raises(WorkspaceUnavailableError, match="no published snapshot"):
        publisher.publish()
    assert not mount.exists()

    manager.publish_snapshot({"performance": {"read_count": 0}})
    envelope = publisher.publish()
    raw = (mount / WORKSPACE_SNAPSHOT_FILENAME).read_bytes()
    assert raw == _canonical(json.loads(raw.decode("ascii")))
    assert envelope["owner"] == {
        "pid": os.getpid(),
        "schema": WORKSPACE_SCHEMA,
        "started_at_ns": envelope["owner"]["started_at_ns"],
        "start_identity": envelope["owner"]["start_identity"],
        "version": WORKSPACE_SCHEMA_VERSION,
    }
    assert len(envelope["owner"]["start_identity"]) == 32
    assert envelope["sequence"] == 1


def test_publisher_attaches_to_telemetry_manager_and_tds_filesystem(tmp_path: Path):
    manager = TelemetryManager(snapshot_interval_seconds=0.25)
    manager.record_read(10, hit=True, backend="python")
    manager.publish_snapshot(manager.snapshot(force=True))
    manager_mount = tmp_path / "manager"
    attach_workspace_telemetry(manager, manager_mount).publish()
    manager_snapshot = WorkspaceTelemetrySource(manager_mount).read_snapshot()
    assert manager_snapshot["performance"]["read_count"] == 1

    filesystem = TDSFileSystem(telemetry_manager=manager)
    filesystem.root.write("alpha", b"payload")
    manager.publish_snapshot(manager.snapshot(force=True))
    filesystem_mount = tmp_path / "filesystem"
    attach_workspace_telemetry(filesystem, filesystem_mount).publish()
    filesystem_snapshot = WorkspaceTelemetrySource(filesystem_mount).read_snapshot()
    assert filesystem_snapshot["performance"]["write_count"] >= 1


def test_snapshot_round_trips_between_real_processes(tmp_path: Path):
    mount = tmp_path / "cross-process"
    process = multiprocessing.get_context("spawn").Process(
        target=_publish_from_child,
        args=(str(mount),),
    )
    process.start()
    process.join(timeout=10.0)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2.0)
        raise AssertionError("workspace producer child did not exit")
    assert process.exitcode == 0

    envelope = WorkspaceTelemetrySource(mount).read_envelope()
    assert envelope["owner"]["pid"] == process.pid
    assert envelope["owner"]["pid"] != os.getpid()
    assert envelope["snapshot"]["performance"]["producer_pid"] == process.pid


def test_explicit_publisher_thread_advances_live_manager_snapshot(tmp_path: Path):
    manager = TelemetryManager(snapshot_interval_seconds=0.25)
    mount = tmp_path / "live"
    publisher = WorkspaceTelemetryPublisher(mount, manager).start(interval_seconds=0.25)
    source = WorkspaceTelemetrySource(mount)
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            state = source.admin_status_snapshot()
            if state["workspace_mount"]["state"] == "ready":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("initial workspace snapshot was not published")

        manager.record_read(20, hit=True, backend="python")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            snapshot = source.read_snapshot()
            if snapshot["performance"]["read_count"] >= 1:
                break
            time.sleep(0.03)
        else:
            raise AssertionError("workspace publisher repeated a frozen manager snapshot")
    finally:
        publisher.stop()
    assert not publisher.running


def test_admin_control_reports_ready_stale_and_unavailable_without_throwing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    missing = WorkspaceTelemetrySource(tmp_path / "missing")
    missing_status = AdminControl(observation_source=missing).status()
    assert missing_status["workspace_mount"]["state"] == "unavailable"
    assert missing_status["observation"]["system_health"] == "UNAVAILABLE"

    mount = tmp_path / "mounted"
    envelope = WorkspaceTelemetryPublisher(mount).publish(
        {"health": {"state": "healthy"}, "performance": {"read_count": 3}}
    )
    source = WorkspaceTelemetrySource(mount, stale_after_seconds=1.0)
    ready = AdminControl(observation_source=source).status()
    assert ready["workspace_mount"]["state"] == "ready"

    from staqtapp_tds.admin import workspace

    monkeypatch.setattr(
        workspace.time,
        "time_ns",
        lambda: int(envelope["published_at_ns"]) + 2_000_000_000,
    )
    stale = AdminControl(observation_source=source).status()
    assert stale["workspace_mount"]["state"] == "stale"
    assert stale["observation"]["system_health"] == "STALE"
    assert stale["observation"]["health"]["snapshot_age_seconds"] == 2.0


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b'{"owner": {}}',
        b'{"snapshot":{},"owner":{},"sequence":1,"published_at_ns":1}',
    ],
)
def test_malformed_and_noncanonical_snapshots_are_explicitly_invalid(
    tmp_path: Path, payload: bytes
):
    mount = tmp_path / "invalid"
    mount.mkdir()
    (mount / WORKSPACE_SNAPSHOT_FILENAME).write_bytes(payload)
    source = WorkspaceTelemetrySource(mount)

    status = AdminControl(observation_source=source).status()
    assert status["workspace_mount"]["state"] == "invalid"
    assert status["observation"]["system_health"] == "INVALID"
    with pytest.raises(WorkspaceSnapshotError):
        source.read_envelope()


def test_oversized_and_nonregular_snapshots_are_rejected(tmp_path: Path):
    oversized = tmp_path / "oversized"
    oversized.mkdir()
    (oversized / WORKSPACE_SNAPSHOT_FILENAME).write_bytes(
        b"{" + b" " * MAX_WORKSPACE_SNAPSHOT_BYTES + b"}"
    )
    assert (
        AdminControl(observation_source=WorkspaceTelemetrySource(oversized))
        .status()["workspace_mount"]["state"]
        == "invalid"
    )

    nonregular = tmp_path / "nonregular"
    nonregular.mkdir()
    (nonregular / WORKSPACE_SNAPSHOT_FILENAME).mkdir()
    assert (
        AdminControl(observation_source=WorkspaceTelemetrySource(nonregular))
        .status()["workspace_mount"]["state"]
        == "invalid"
    )


def test_mount_rejects_traversal_and_symlinked_snapshot(tmp_path: Path):
    with pytest.raises(WorkspaceMountError, match="traversal"):
        WorkspaceTelemetrySource(tmp_path / "safe" / ".." / "escaped")

    mount = tmp_path / "mount"
    mount.mkdir()
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    try:
        (mount / WORKSPACE_SNAPSHOT_FILENAME).symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")
    source = WorkspaceTelemetrySource(mount)
    assert AdminControl(observation_source=source).status()["workspace_mount"]["state"] == "invalid"
    with pytest.raises(WorkspaceSnapshotError, match="symlink|reparse"):
        source.read_envelope()


def test_mount_rejects_symlinked_intermediate_parent(tmp_path: Path):
    real_parent = tmp_path / "real"
    real_mount = real_parent / "mount"
    real_mount.mkdir(parents=True)
    WorkspaceTelemetryPublisher(real_mount).publish({"performance": {}})
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    source = WorkspaceTelemetrySource(linked_parent / "mount")
    status = AdminControl(observation_source=source).status()
    assert status["workspace_mount"]["state"] == "invalid"
    assert "symlink or reparse" in str(status["workspace_mount"]["error"])
    with pytest.raises(WorkspaceMountError, match="symlink|reparse"):
        WorkspaceTelemetryPublisher(linked_parent / "new-mount").publish({})


def test_atomic_publication_fsyncs_file_and_uses_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from staqtapp_tds.admin import workspace

    fsync_calls: list[int] = []
    replace_calls: list[tuple[object, object]] = []
    real_fsync = workspace.os.fsync
    real_replace = workspace.os.replace

    def checked_fsync(fd: int):
        fsync_calls.append(fd)
        return real_fsync(fd)

    def checked_replace(source: object, destination: object):
        replace_calls.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(workspace.os, "fsync", checked_fsync)
    monkeypatch.setattr(workspace.os, "replace", checked_replace)
    mount = tmp_path / "atomic"
    WorkspaceTelemetryPublisher(mount).publish({"performance": {"reads": 1}})

    assert fsync_calls
    assert len(replace_calls) == 1
    assert Path(replace_calls[0][1]) == mount / WORKSPACE_SNAPSHOT_FILENAME
    assert not list(mount.glob("*.tmp"))


def test_atomic_replace_between_lstat_and_open_never_reports_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A reader may safely finish with either immutable file generation."""

    from staqtapp_tds.admin import workspace

    mount = tmp_path / "replace-race"
    publisher = WorkspaceTelemetryPublisher(mount)
    publisher.publish({"performance": {"generation": "before"}})
    source = WorkspaceTelemetrySource(mount)
    real_open = workspace.os.open
    replaced = False

    def replace_before_open(path: object, flags: int, *args: object):
        nonlocal replaced
        if not replaced and Path(path) == publisher.snapshot_path:
            replaced = True
            publisher.publish({"performance": {"generation": "after"}})
        return real_open(path, flags, *args)

    monkeypatch.setattr(workspace.os, "open", replace_before_open)
    status = AdminControl(observation_source=source).status()

    assert replaced
    assert status["workspace_mount"]["state"] == "ready"
    assert status["observation"]["performance"]["generation"] == "after"
    assert status["workspace_mount"]["sequence"] == 2


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_workspace_and_telemetry_timing_values_are_rejected(
    tmp_path: Path, invalid: float
):
    manager = TelemetryManager(snapshot_interval_seconds=0.25)
    workspace_publisher = WorkspaceTelemetryPublisher(
        tmp_path / "nonfinite",
        lambda: {"performance": {}},
    )

    with pytest.raises(ValueError, match="finite"):
        workspace_publisher.start(interval_seconds=invalid)
    with pytest.raises(ValueError, match="finite"):
        WorkspaceTelemetrySource(tmp_path / "nonfinite", stale_after_seconds=invalid)
    with pytest.raises(ValueError, match="finite"):
        workspace_publisher.stop(timeout=invalid)
    with pytest.raises(ValueError, match="finite"):
        TelemetryPublisherThread(manager, interval_seconds=invalid)

    telemetry_publisher = TelemetryPublisherThread(manager, interval_seconds=0.25)
    with pytest.raises(ValueError, match="finite"):
        telemetry_publisher.stop(timeout=invalid)


@pytest.mark.parametrize("invalid_version", [True, 1.0])
def test_owner_version_requires_an_exact_integer(
    tmp_path: Path, invalid_version: object
):
    mount = tmp_path / "owner-version"
    envelope = WorkspaceTelemetryPublisher(mount).publish({"performance": {}})
    envelope["owner"]["version"] = invalid_version
    (mount / WORKSPACE_SNAPSHOT_FILENAME).write_bytes(_canonical(envelope))
    source = WorkspaceTelemetrySource(mount)

    assert AdminControl(observation_source=source).status()["workspace_mount"]["state"] == "invalid"
    with pytest.raises(WorkspaceSnapshotError, match="schema/version"):
        source.read_envelope()


def test_manager_has_one_snapshot_publisher_and_workspace_can_attach_as_sink(tmp_path: Path):
    manager = TelemetryManager(snapshot_interval_seconds=0.25)
    manager.record_read(17, hit=True, backend="python")
    mount = tmp_path / "single-publisher"
    workspace_publisher = WorkspaceTelemetryPublisher(mount, manager)
    workspace_sink = workspace_publisher.publish
    primary = TelemetryPublisherThread(manager, interval_seconds=0.25).start()
    competing = TelemetryPublisherThread(manager, interval_seconds=0.25)
    try:
        with pytest.raises(RuntimeError, match="already active"):
            competing.start()
        with pytest.raises(RuntimeError, match="already active"):
            workspace_publisher.start(interval_seconds=0.25)

        primary.add_sink(workspace_sink)
        source = WorkspaceTelemetrySource(mount)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            status = AdminControl(observation_source=source).status()
            if (
                status["workspace_mount"]["state"] == "ready"
                and status["observation"]["performance"].get("read_count", 0) >= 1
            ):
                break
            time.sleep(0.02)
        else:
            raise AssertionError("workspace sink did not receive the manager publication")
    finally:
        primary.remove_sink(workspace_sink)
        primary.stop()

    # A failed ownership claim does not poison the one-shot object, and the
    # active owner's stop releases the manager for a successor.
    competing.start()
    competing.stop()


def test_snapshot_sinks_are_nested_copy_isolated_and_bound_methods_are_removable():
    manager = TelemetryManager(snapshot_interval_seconds=0.25)
    manager.record_read(11, hit=True, backend="python")
    observed: list[int] = []

    class MutatingSink:
        def receive(self, snapshot: dict[str, object]) -> None:
            performance = snapshot["performance"]
            assert isinstance(performance, dict)
            performance["read_count"] = 987654

    mutating = MutatingSink()

    def observe(snapshot: dict[str, object]) -> None:
        performance = snapshot["performance"]
        assert isinstance(performance, dict)
        observed.append(int(performance["read_count"]))

    publisher = TelemetryPublisherThread(manager, interval_seconds=0.25)
    publisher.add_sink(mutating.receive)
    publisher.add_sink(mutating.receive)
    assert len(publisher._sinks) == 1
    publisher.add_sink(observe).start()
    try:
        deadline = time.monotonic() + 3.0
        while not observed and time.monotonic() < deadline:
            time.sleep(0.02)
        assert observed and observed[0] == 1
        assert manager.latest_snapshot()["performance"]["read_count"] == 1
    finally:
        publisher.stop()

    publisher.remove_sink(mutating.receive)
    assert all(
        not publisher._same_sink(sink, mutating.receive)
        for sink in publisher._sinks
    )


def test_duck_typed_snapshot_source_keeps_generic_workspace_polling_path(tmp_path: Path):
    class SnapshotSource:
        def snapshot(self) -> dict[str, object]:
            return {"performance": {"read_count": 4}}

        def publish_snapshot(self, _snapshot: dict[str, object]) -> None:
            return None

        def published_snapshot(self) -> dict[str, object]:
            return self.snapshot()

    mount = tmp_path / "duck-source"
    publisher = WorkspaceTelemetryPublisher(mount, SnapshotSource()).start(
        interval_seconds=0.25
    )
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            status = AdminControl(
                observation_source=WorkspaceTelemetrySource(mount)
            ).status()
            if status["workspace_mount"]["state"] == "ready":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("generic workspace source did not publish")
        assert status["observation"]["performance"]["read_count"] == 4
    finally:
        publisher.stop()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
@pytest.mark.filterwarnings(
    r"ignore:This process .* is multi-threaded, use of fork\(\) may lead to deadlocks.*:DeprecationWarning"
)
def test_publisher_resets_inherited_locked_state_before_child_publish(tmp_path: Path):
    mount = tmp_path / "fork-reset"
    publisher = WorkspaceTelemetryPublisher(mount)
    publisher.publish({"performance": {"generation": "parent"}})
    read_fd, write_fd = os.pipe()
    publisher._publish_lock.acquire()
    child_pid = os.fork()
    if child_pid == 0:  # pragma: no cover - assertions run in the parent
        os.close(read_fd)
        exit_code = 0
        try:
            envelope = publisher.publish({"performance": {"generation": "child"}})
            message = f"ok:{envelope['owner']['pid']}:{envelope['sequence']}".encode("ascii")
        except BaseException as exc:
            exit_code = 1
            message = f"error:{type(exc).__name__}:{exc}".encode("utf-8", "replace")
        try:
            os.write(write_fd, message)
        finally:
            os.close(write_fd)
            os._exit(exit_code)

    os.close(write_fd)
    timed_out = False
    message = b""
    try:
        readable, _, _ = select.select([read_fd], [], [], 3.0)
        if readable:
            message = os.read(read_fd, 4096)
        else:
            timed_out = True
    finally:
        publisher._publish_lock.release()
        os.close(read_fd)
        if timed_out:
            os.kill(child_pid, signal.SIGKILL)
        _, child_status = os.waitpid(child_pid, 0)

    assert not timed_out, "fork child deadlocked on an inherited publisher lock"
    assert os.WIFEXITED(child_status) and os.WEXITSTATUS(child_status) == 0
    assert message == f"ok:{child_pid}:1".encode("ascii")
    envelope = WorkspaceTelemetrySource(mount).read_envelope()
    assert envelope["owner"]["pid"] == child_pid
    assert envelope["sequence"] == 1
    assert envelope["snapshot"]["performance"]["generation"] == "child"


def test_cli_workspace_mount_attaches_read_only_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, object] = {}

    class FakePanel:
        def __init__(self, control: AdminControl, host: str, port: int):
            captured["control"] = control
            self.host = host
            self.port = port
            self.csrf_token = "test"

        def make_handler(self):
            return object

    class FakeServer:
        server_port = 8765

        def __init__(self, *_args: object):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            captured["closed"] = True

    monkeypatch.setattr(app, "AdminPanelServer", FakePanel)
    monkeypatch.setattr(app, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(app.webbrowser, "open", lambda _url: pytest.fail("browser opened"))
    mount = tmp_path / "cli-mount"
    assert app.main(["--workspace-mount", str(mount), "--no-browser"]) == 0
    control = captured["control"]
    assert isinstance(control, AdminControl)
    assert isinstance(control.observation_source, WorkspaceTelemetrySource)
    assert control.status()["workspace_mount"]["state"] == "unavailable"
    assert captured["closed"] is True


def test_admin_console_serve_panel_accepts_workspace_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, object] = {}

    class FakePanel:
        def __init__(self, control: AdminControl, host: str, port: int):
            captured["control"] = control
            captured["host"] = host
            captured["port"] = port

        def serve_forever(self):
            captured["served"] = True

    monkeypatch.setattr(console, "AdminPanelServer", FakePanel)
    mount = tmp_path / "console-mount"
    assert (
        console.main(
            [
                "serve-panel",
                "--host",
                "127.0.0.1",
                "--port",
                "9876",
                "--workspace-mount",
                str(mount),
            ]
        )
        is None
    )
    control = captured["control"]
    assert isinstance(control, AdminControl)
    assert isinstance(control.observation_source, WorkspaceTelemetrySource)
    assert captured == {
        "control": control,
        "host": "127.0.0.1",
        "port": 9876,
        "served": True,
    }


def test_workspace_api_is_public_from_admin_package():
    assert admin_package.WorkspaceTelemetryPublisher is WorkspaceTelemetryPublisher
    assert admin_package.WorkspaceTelemetrySource is WorkspaceTelemetrySource
    assert admin_package.attach_workspace_telemetry is attach_workspace_telemetry


def test_panel_preserves_localhost_safety_and_surfaces_invalid_health(tmp_path: Path):
    mount = tmp_path / "bad-panel"
    mount.mkdir()
    (mount / WORKSPACE_SNAPSHOT_FILENAME).write_bytes(b"bad")
    panel = AdminPanelServer(control=AdminControl(observation_source=WorkspaceTelemetrySource(mount)))
    assert panel._status_snapshot()["system_health"] == "INVALID"

    with pytest.raises(ValueError):
        AdminPanelServer(
            control=AdminControl(observation_source=WorkspaceTelemetrySource(mount)),
            host="0.0.0.0",
        )


def test_no_source_admin_status_contract_is_unchanged():
    status = AdminControl().status()
    assert "workspace_mount" not in status
    assert "observation" not in status

"""Observer-only, cross-process telemetry snapshots for the local Browser.

The workspace mount is deliberately a very small file boundary.  A TDS process
may publish an already assembled telemetry snapshot into a user-selected local
directory; the Browser process reads only that immutable JSON file.  The reader
never imports, opens, or walks the publisher's TDS objects.

Publishing is opt-in.  Constructing a :class:`WorkspaceTelemetryPublisher` does
not start a thread or touch the filesystem.  Pass an explicit snapshot to
:meth:`publish`, export an already-published manager snapshot, or use the
explicit :meth:`start`/:meth:`stop` lifecycle when a cadence is wanted.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import stat
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from staqtapp_tds.telemetry import TelemetryManager, TelemetryPublisherThread


WORKSPACE_SCHEMA = "staqtapp-tds.workspace-telemetry"
WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_SNAPSHOT_FILENAME = "telemetry.snapshot.json"
MAX_WORKSPACE_SNAPSHOT_BYTES = 1 << 20
DEFAULT_STALE_AFTER_SECONDS = 10.0
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 100_000
_OWNER_FIELDS = {
    "pid",
    "schema",
    "started_at_ns",
    "start_identity",
    "version",
}
_ENVELOPE_FIELDS = {"owner", "published_at_ns", "sequence", "snapshot"}


class WorkspaceMountError(ValueError):
    """Base error for an unsafe or invalid workspace telemetry mount."""


class WorkspaceUnavailableError(WorkspaceMountError):
    """The mount or its snapshot does not exist yet."""


class WorkspaceSnapshotError(WorkspaceMountError):
    """A workspace snapshot failed its bounded integrity checks."""


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise WorkspaceSnapshotError("snapshot is not canonical JSON data") from exc


def _normalize_json_value(value: object, *, depth: int = 0) -> object:
    """Normalize producer data before its byte-exact canonical encoding.

    Native diagnostics currently use integer event codes as mapping keys.  JSON
    object keys are strings, so normalization must happen before the first sort;
    otherwise a read/re-encode can order ``"10"`` differently from integer
    ``10`` and correctly classify our own output as noncanonical.
    """

    if depth > _MAX_JSON_DEPTH:
        raise WorkspaceSnapshotError("workspace telemetry snapshot nesting is too deep")
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise WorkspaceSnapshotError("workspace telemetry snapshot contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, nested in value.items():
            if type(key) not in {str, int}:
                raise WorkspaceSnapshotError("workspace telemetry object keys must be text or integers")
            text_key = str(key)
            if text_key in normalized:
                raise WorkspaceSnapshotError("workspace telemetry object keys collide after JSON normalization")
            normalized[text_key] = _normalize_json_value(nested, depth=depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item, depth=depth + 1) for item in value]
    if hasattr(value, "to_dict"):
        return _normalize_json_value(value.to_dict(), depth=depth)
    # NumPy scalar values expose item(); accept them only when they reduce to a
    # distinct JSON scalar, without importing NumPy into the admin boundary.
    if hasattr(value, "item"):
        scalar = value.item()
        if scalar is not value:
            return _normalize_json_value(scalar, depth=depth)
    raise WorkspaceSnapshotError(
        f"workspace telemetry snapshot contains unsupported {type(value).__name__} data"
    )


def _coerce_mount_path(value: str | os.PathLike[str]) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise WorkspaceMountError("workspace mount path must be non-empty local text")
    candidate = Path(raw)
    if ".." in candidate.parts:
        raise WorkspaceMountError("workspace mount path traversal is not allowed")
    # abspath normalizes without resolving symlinks.  Symlinks/reparse points
    # are rejected separately instead of silently changing the user's target.
    return Path(os.path.abspath(candidate))


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse
    )


def _require_safe_path_components(
    path: Path,
    *,
    allow_missing_leaf: bool = False,
    unavailable: bool = False,
) -> None:
    """Reject links/reparse points in every component of an absolute path."""

    if not path.is_absolute():
        raise AssertionError("workspace path validation requires an absolute path")
    anchor = Path(path.anchor)
    try:
        anchor_metadata = anchor.lstat()
    except OSError as exc:
        error = WorkspaceUnavailableError if unavailable else WorkspaceMountError
        raise error(f"workspace path anchor is unavailable: {anchor}") from exc
    if _is_link_or_reparse(anchor_metadata) or not stat.S_ISDIR(anchor_metadata.st_mode):
        raise WorkspaceMountError("workspace path anchor must be a real non-link directory")
    current = anchor
    relative_parts = path.parts[1:] if path.anchor else path.parts
    for index, part in enumerate(relative_parts):
        current = current / part
        leaf = index == len(relative_parts) - 1
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            if allow_missing_leaf and leaf:
                return
            error = WorkspaceUnavailableError if unavailable else WorkspaceMountError
            raise error(f"workspace path component is unavailable: {current}") from exc
        except OSError as exc:
            raise WorkspaceMountError(
                f"workspace path component cannot be inspected: {current}"
            ) from exc
        if _is_link_or_reparse(metadata):
            raise WorkspaceMountError(
                f"workspace path component cannot be a symlink or reparse point: {current}"
            )
        if not leaf and not stat.S_ISDIR(metadata.st_mode):
            raise WorkspaceMountError(
                f"workspace parent component must be a real directory: {current}"
            )


def _require_real_directory(path: Path, *, unavailable: bool = False) -> None:
    _require_safe_path_components(path, unavailable=unavailable)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        error = WorkspaceUnavailableError if unavailable else WorkspaceMountError
        raise error(f"workspace mount directory is unavailable: {path}") from exc
    except OSError as exc:
        raise WorkspaceMountError(f"workspace mount directory cannot be inspected: {path}") from exc
    if _is_link_or_reparse(metadata):
        raise WorkspaceMountError("workspace mount directory cannot be a symlink or reparse point")
    if not stat.S_ISDIR(metadata.st_mode):
        raise WorkspaceMountError("workspace mount path must be a real directory")


def _prepare_publish_directory(path: Path) -> None:
    _require_safe_path_components(path, allow_missing_leaf=True)
    try:
        _require_real_directory(path)
        return
    except WorkspaceMountError:
        if path.exists() or path.is_symlink():
            raise

    parent = path.parent
    _require_real_directory(parent)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise WorkspaceMountError(f"workspace mount directory cannot be created: {path}") from exc
    _require_real_directory(path)
    _fsync_directory(parent)


def _snapshot_path(mount_path: Path) -> Path:
    return mount_path / WORKSPACE_SNAPSHOT_FILENAME


def _open_bounded_regular(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    # Prevent a swapped FIFO/device from blocking between lstat and open.
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)

    for _attempt in range(4):
        try:
            before = path.lstat()
        except FileNotFoundError as exc:
            raise WorkspaceUnavailableError("workspace telemetry snapshot is unavailable") from exc
        except OSError as exc:
            raise WorkspaceSnapshotError("workspace telemetry snapshot cannot be inspected") from exc
        if _is_link_or_reparse(before):
            raise WorkspaceSnapshotError("workspace telemetry snapshot cannot be a symlink or reparse point")
        if not stat.S_ISREG(before.st_mode):
            raise WorkspaceSnapshotError("workspace telemetry snapshot must be a regular file")

        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise WorkspaceSnapshotError("workspace telemetry snapshot cannot be opened safely") from exc
        try:
            opened = os.fstat(fd)
            before_identity = (before.st_dev, before.st_ino)
            opened_identity = (opened.st_dev, opened.st_ino)
            if stat.S_ISREG(opened.st_mode) and before_identity == opened_identity:
                # If atomic replacement happens after open, this descriptor is
                # still a complete immutable old snapshot and remains safe.
                return fd
        except BaseException:
            os.close(fd)
            raise
        os.close(fd)

    raise WorkspaceSnapshotError("workspace telemetry snapshot changed repeatedly during safe open")


def _read_bounded_regular(path: Path, max_bytes: int) -> bytes:
    fd = _open_bounded_regular(path)
    try:
        opened = os.fstat(fd)
        if opened.st_size > max_bytes:
            raise WorkspaceSnapshotError("workspace telemetry snapshot exceeds its byte bound")
        parts: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 64 << 10))
            if not chunk:
                break
            parts.append(chunk)
            remaining -= len(chunk)
        data = b"".join(parts)
        if len(data) > max_bytes:
            raise WorkspaceSnapshotError("workspace telemetry snapshot exceeds its byte bound")
        return data
    finally:
        os.close(fd)


def _validate_json_bounds(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise WorkspaceSnapshotError("workspace telemetry snapshot has too many JSON nodes")
        if depth > _MAX_JSON_DEPTH:
            raise WorkspaceSnapshotError("workspace telemetry snapshot nesting is too deep")
        if isinstance(item, dict):
            pending.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            pending.extend((nested, depth + 1) for nested in item)


def _load_canonical_envelope(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise WorkspaceSnapshotError("workspace telemetry snapshot is malformed JSON") from exc
    _validate_json_bounds(value)
    if _canonical_json_bytes(value) != data:
        raise WorkspaceSnapshotError("workspace telemetry snapshot is noncanonical JSON")
    if not isinstance(value, dict) or set(value) != _ENVELOPE_FIELDS:
        raise WorkspaceSnapshotError("workspace telemetry snapshot envelope is not canonical")

    owner = value.get("owner")
    snapshot = value.get("snapshot")
    if not isinstance(owner, dict) or set(owner) != _OWNER_FIELDS:
        raise WorkspaceSnapshotError("workspace telemetry owner metadata is not canonical")
    owner_version = owner.get("version")
    if (
        owner.get("schema") != WORKSPACE_SCHEMA
        or type(owner_version) is not int
        or owner_version != WORKSPACE_SCHEMA_VERSION
    ):
        raise WorkspaceSnapshotError("workspace telemetry schema/version is unsupported")
    for field in ("pid", "started_at_ns"):
        field_value = owner.get(field)
        if type(field_value) is not int or field_value <= 0:
            raise WorkspaceSnapshotError(f"workspace telemetry owner {field} is invalid")
    identity = owner.get("start_identity")
    if (
        not isinstance(identity, str)
        or len(identity) != 32
        or any(char not in "0123456789abcdef" for char in identity)
    ):
        raise WorkspaceSnapshotError("workspace telemetry owner start identity is invalid")
    for field in ("published_at_ns", "sequence"):
        field_value = value.get(field)
        if type(field_value) is not int or field_value <= 0:
            raise WorkspaceSnapshotError(f"workspace telemetry {field} is invalid")
    if owner["started_at_ns"] > value["published_at_ns"]:
        raise WorkspaceSnapshotError("workspace telemetry owner start is after publication")
    if not isinstance(snapshot, dict):
        raise WorkspaceSnapshotError("workspace telemetry payload must be a JSON object")
    return value


def _assert_replace_target_safe(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise WorkspaceSnapshotError("workspace telemetry target cannot be inspected") from exc
    if _is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise WorkspaceSnapshotError("workspace telemetry target must be a regular non-link file")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError:
        # Directory fsync is unavailable on some Windows/filesystem pairs.  The
        # data file itself is still fsynced before the atomic replace.
        return
    try:
        try:
            os.fsync(fd)
        except OSError:
            return
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    _assert_replace_target_safe(path)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(8)}.tmp"
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd: int | None = None
    try:
        fd = os.open(temporary, flags, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise WorkspaceSnapshotError("workspace telemetry temporary is not a regular file")
        view = memoryview(data)
        written = 0
        while written < len(view):
            count = os.write(fd, view[written:])
            if count <= 0:
                raise WorkspaceSnapshotError("workspace telemetry write did not make progress")
            written += count
        os.fsync(fd)
        os.close(fd)
        fd = None
        _assert_replace_target_safe(path)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except WorkspaceMountError:
        raise
    except OSError as exc:
        raise WorkspaceMountError("workspace telemetry snapshot cannot be published atomically") from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _snapshot_from_source(source: object) -> dict[str, Any]:
    # TDSFileSystem owns a TelemetryManager. Export only its already-published
    # immutable value: workspace file I/O must never invoke engine samplers.
    manager = getattr(source, "telemetry_manager", None)
    selected = manager if manager is not None else source
    if hasattr(selected, "published_snapshot"):
        value = selected.published_snapshot()
        if value is None:
            raise WorkspaceUnavailableError(
                "telemetry manager has no published snapshot; start its publisher or the workspace publisher"
            )
    elif hasattr(selected, "latest_snapshot"):
        value = selected.latest_snapshot()
    elif hasattr(selected, "observation_snapshot"):
        value = selected.observation_snapshot()
    elif hasattr(selected, "snapshot"):
        value = selected.snapshot()
    elif callable(selected):
        value = selected()
    else:
        raise TypeError("workspace publisher source does not expose a telemetry snapshot API")
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise TypeError("workspace publisher source must return a mapping snapshot")
    return dict(value)


class WorkspaceTelemetryPublisher:
    """Explicit publisher for a TelemetryManager or TDSFileSystem snapshot."""

    def __init__(
        self,
        mount_path: str | os.PathLike[str],
        source: object | None = None,
        *,
        max_snapshot_bytes: int = MAX_WORKSPACE_SNAPSHOT_BYTES,
    ) -> None:
        self.mount_path = _coerce_mount_path(mount_path)
        self.source = source
        self.max_snapshot_bytes = int(max_snapshot_bytes)
        if not 1 <= self.max_snapshot_bytes <= MAX_WORKSPACE_SNAPSHOT_BYTES:
            raise ValueError(
                f"max_snapshot_bytes must be within 1..{MAX_WORKSPACE_SNAPSHOT_BYTES}"
            )
        self._owner_pid = os.getpid()
        self._started_at_ns = time.time_ns()
        self._start_identity = secrets.token_hex(16)
        self._sequence = 0
        self._publish_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._manager_publisher: TelemetryPublisherThread | None = None
        self._sink_callback = self._publish_from_snapshot
        self.last_error: str | None = None

    @property
    def snapshot_path(self) -> Path:
        return _snapshot_path(self.mount_path)

    @property
    def running(self) -> bool:
        return bool(
            (self._thread is not None and self._thread.is_alive())
            or (
                self._manager_publisher is not None
                and self._manager_publisher.running
            )
        )

    @property
    def owner(self) -> dict[str, object]:
        self._reset_after_fork_if_needed()
        return {
            "schema": WORKSPACE_SCHEMA,
            "version": WORKSPACE_SCHEMA_VERSION,
            "pid": self._owner_pid,
            "started_at_ns": self._started_at_ns,
            "start_identity": self._start_identity,
        }

    def _reset_after_fork_if_needed(self) -> None:
        pid = os.getpid()
        if pid != self._owner_pid:
            # Locks and thread objects inherited from a multithreaded parent may
            # remain permanently owned in the child. Replace them before any
            # lock acquisition; attached TDS/manager objects should themselves
            # be constructed after a multithreaded fork.
            self._publish_lock = threading.Lock()
            self._lifecycle_lock = threading.Lock()
            self._stop_event = threading.Event()
            self._thread = None
            self._manager_publisher = None
            self._owner_pid = pid
            self._started_at_ns = time.time_ns()
            self._start_identity = secrets.token_hex(16)
            self._sequence = 0
            self.last_error = None

    def publish(self, snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Publish one atomic snapshot and return the canonical envelope."""

        self._reset_after_fork_if_needed()
        with self._publish_lock:
            if snapshot is None:
                if self.source is None:
                    raise TypeError("publish requires a snapshot or an attached telemetry source")
                payload = _snapshot_from_source(self.source)
            else:
                payload = dict(snapshot)
            normalized = _normalize_json_value(payload)
            if not isinstance(normalized, dict):
                raise WorkspaceSnapshotError("workspace telemetry payload must be a JSON object")
            payload = normalized
            _validate_json_bounds(payload)
            self._sequence += 1
            envelope: dict[str, Any] = {
                "owner": self.owner,
                "published_at_ns": max(time.time_ns(), self._started_at_ns),
                "sequence": self._sequence,
                "snapshot": payload,
            }
            data = _canonical_json_bytes(envelope)
            if len(data) > self.max_snapshot_bytes:
                self._sequence -= 1
                raise WorkspaceSnapshotError("workspace telemetry snapshot exceeds its byte bound")
            _prepare_publish_directory(self.mount_path)
            _atomic_write(self.snapshot_path, data)
            self.last_error = None
            return envelope

    def start(self, *, interval_seconds: float = 2.0) -> "WorkspaceTelemetryPublisher":
        """Start an explicit background publication lifecycle.

        No thread exists before this method is called.  Publication happens
        immediately on the worker, then at the requested cadence until stop().
        """

        interval = float(interval_seconds)
        if not math.isfinite(interval) or interval < 0.25:
            raise ValueError("workspace publish interval must be finite and at least 0.25 seconds")
        if self.source is None:
            raise TypeError("a telemetry source is required for background publication")
        self._reset_after_fork_if_needed()
        with self._lifecycle_lock:
            if self.running:
                return self
            manager = getattr(self.source, "telemetry_manager", None)
            selected = manager if manager is not None else self.source
            if isinstance(selected, TelemetryManager):
                publisher = TelemetryPublisherThread(
                    selected,
                    interval_seconds=interval,
                    name="staqtapp-tds-workspace-telemetry",
                    sinks=(self._sink_callback,),
                )
                publisher.start()
                self._manager_publisher = publisher
                self._thread = None
            else:
                self._stop_event = threading.Event()
                self._thread = threading.Thread(
                    target=self._run,
                    args=(interval,),
                    name="staqtapp-tds-workspace-telemetry",
                    daemon=True,
                )
                self._thread.start()
        return self

    def stop(self, timeout: float | None = 2.0) -> None:
        if timeout is not None:
            timeout = float(timeout)
            if not math.isfinite(timeout) or timeout < 0:
                raise ValueError("workspace publisher stop timeout must be finite and non-negative")
        self._reset_after_fork_if_needed()
        with self._lifecycle_lock:
            thread = self._thread
            manager_publisher = self._manager_publisher
            self._stop_event.set()
        if manager_publisher is not None:
            manager_publisher.stop(timeout=timeout)
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def _publish_from_snapshot(self, snapshot: dict[str, object]) -> None:
        try:
            self.publish(snapshot)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise

    def _run(self, interval_seconds: float) -> None:
        while not self._stop_event.is_set():
            try:
                self.publish()
            except Exception as exc:  # keep observer failure outside TDS control flow
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._stop_event.wait(interval_seconds)

    def __enter__(self) -> "WorkspaceTelemetryPublisher":
        # Context management controls cleanup only; it does not implicitly
        # choose a cadence or start a background thread.
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def attach_workspace_telemetry(
    source: object,
    mount_path: str | os.PathLike[str],
    *,
    max_snapshot_bytes: int = MAX_WORKSPACE_SNAPSHOT_BYTES,
) -> WorkspaceTelemetryPublisher:
    """Attach an explicit publisher to a TelemetryManager or TDSFileSystem.

    Attachment has no side effects. Callers choose an explicit
    ``start()``/``stop()`` lifecycle, pass a snapshot to manual ``publish()``,
    or export an already-published manager snapshot.
    """

    return WorkspaceTelemetryPublisher(
        mount_path,
        source,
        max_snapshot_bytes=max_snapshot_bytes,
    )


class WorkspaceTelemetrySource:
    """Read-only Browser source backed solely by the bounded snapshot file."""

    def __init__(
        self,
        mount_path: str | os.PathLike[str],
        *,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        max_snapshot_bytes: int = MAX_WORKSPACE_SNAPSHOT_BYTES,
    ) -> None:
        self.mount_path = _coerce_mount_path(mount_path)
        self.stale_after_seconds = float(stale_after_seconds)
        self.max_snapshot_bytes = int(max_snapshot_bytes)
        if not math.isfinite(self.stale_after_seconds) or self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be finite and positive")
        if not 1 <= self.max_snapshot_bytes <= MAX_WORKSPACE_SNAPSHOT_BYTES:
            raise ValueError(
                f"max_snapshot_bytes must be within 1..{MAX_WORKSPACE_SNAPSHOT_BYTES}"
            )
        self._last_mount_status = self._status("unavailable", "snapshot not read yet")

    @property
    def snapshot_path(self) -> Path:
        return _snapshot_path(self.mount_path)

    def _status(self, state: str, error: str | None = None, **fields: object) -> dict[str, object]:
        status: dict[str, object] = {
            "available": state in {"ready", "stale"},
            "error": error,
            "observer_only": True,
            "path": str(self.mount_path),
            "snapshot_file": WORKSPACE_SNAPSHOT_FILENAME,
            "stale": state == "stale",
            "stale_after_seconds": self.stale_after_seconds,
            "state": state,
        }
        status.update(fields)
        return status

    def read_envelope(self) -> dict[str, Any]:
        """Read and strictly validate one canonical snapshot envelope."""

        _require_real_directory(self.mount_path, unavailable=True)
        data = _read_bounded_regular(self.snapshot_path, self.max_snapshot_bytes)
        return _load_canonical_envelope(data)

    def read_snapshot(self) -> dict[str, Any]:
        """Return the validated producer payload, raising on invalid input."""

        return dict(self.read_envelope()["snapshot"])

    def _unavailable_observation(self, status: Mapping[str, object]) -> dict[str, Any]:
        state = str(status.get("state", "unavailable"))
        return {
            "behavior": {},
            "components": {},
            "created_at": 0.0,
            "health": {
                "score": 0,
                "snapshot_age_seconds": None,
                "state": state,
            },
            "indexes": {},
            "performance": {},
            "recommendations": [],
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "storage": {},
            "system_health": state.upper(),
            "uptime_seconds": 0.0,
            "workspace_mount": dict(status),
        }

    def admin_status_snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a non-throwing AdminControl observation + mount state."""

        try:
            envelope = self.read_envelope()
            now_ns = time.time_ns()
            published_at_ns = int(envelope["published_at_ns"])
            if published_at_ns > now_ns + 5_000_000_000:
                raise WorkspaceSnapshotError("workspace telemetry publication time is in the future")
            age_seconds = max(0.0, (now_ns - published_at_ns) / 1_000_000_000.0)
            state = "stale" if age_seconds > self.stale_after_seconds else "ready"
            status = self._status(
                state,
                age_seconds=round(age_seconds, 3),
                owner=dict(envelope["owner"]),
                published_at_ns=published_at_ns,
                sequence=int(envelope["sequence"]),
            )
            observation = dict(envelope["snapshot"])
            observation["workspace_mount"] = dict(status)
            if state == "stale":
                health = observation.get("health")
                health_data = dict(health) if isinstance(health, Mapping) else {}
                health_data.update(
                    state="stale",
                    snapshot_age_seconds=round(age_seconds, 3),
                )
                observation["health"] = health_data
                observation["system_health"] = "STALE"
        except WorkspaceUnavailableError as exc:
            status = self._status("unavailable", str(exc))
            observation = self._unavailable_observation(status)
        except (OSError, WorkspaceMountError) as exc:
            status = self._status("invalid", str(exc))
            observation = self._unavailable_observation(status)
        self._last_mount_status = dict(status)
        return {"observation": observation, "workspace_mount": dict(status)}

    def observation_snapshot(self) -> dict[str, Any]:
        """AdminControl-compatible, non-throwing observation method."""

        return self.admin_status_snapshot()["observation"]

    def workspace_status(self) -> dict[str, object]:
        """Return the state captured by the most recent observation read."""

        return dict(self._last_mount_status)


__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "MAX_WORKSPACE_SNAPSHOT_BYTES",
    "WORKSPACE_SCHEMA",
    "WORKSPACE_SCHEMA_VERSION",
    "WORKSPACE_SNAPSHOT_FILENAME",
    "WorkspaceMountError",
    "WorkspaceSnapshotError",
    "WorkspaceTelemetryPublisher",
    "WorkspaceTelemetrySource",
    "WorkspaceUnavailableError",
    "attach_workspace_telemetry",
]

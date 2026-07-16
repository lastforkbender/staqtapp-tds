from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from staqtapp_tds import GuaranteedStorageBridge, GuaranteedStorageError, TDSFileSystem


PRE_PUBLISH = (
    "materialize_temp_created",
    "materialize_before_file",
    "materialize_file_before_fsync",
    "materialize_file_after_fsync",
    "materialize_after_file",
    "materialize_before_directory_fsync",
    "materialize_after_directory_fsync",
    "materialize_before_publish",
)
POST_PUBLISH = (
    "materialize_after_publish",
    "materialize_parent_synced",
)


def _fs() -> TDSFileSystem:
    fs = TDSFileSystem("root")
    d = fs.root.mkdir("models")
    d.write("one", b"a" * 8192)
    d.write("two", {"epoch": 9})
    return fs


def _prepare(root: Path) -> None:
    GuaranteedStorageBridge(root).commit_filesystem(_fs(), parallel_nodes=False)


def _crash_materialize(root: Path, destination: Path, checkpoint: str) -> subprocess.CompletedProcess[str]:
    script = r'''
import os, sys
from staqtapp_tds import GuaranteedStorageBridge
root, destination, checkpoint = sys.argv[1:4]
def crash(name):
    if name == checkpoint:
        os._exit(77)
GuaranteedStorageBridge(root, fault_hook=crash).materialize_current(destination)
'''
    return subprocess.run(
        [sys.executable, "-c", script, str(root), str(destination), checkpoint],
        text=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=30,
    )


@pytest.mark.parametrize("checkpoint", PRE_PUBLISH)
def test_subprocess_crash_before_publication_never_publishes_destination(tmp_path: Path, checkpoint: str):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    _prepare(root)
    result = _crash_materialize(root, destination, checkpoint)
    assert result.returncode == 77, (checkpoint, result.stdout, result.stderr)
    assert not destination.exists()
    # Crash evidence may remain only under a private materialising name.
    leftovers = list(tmp_path.glob(".restored.materializing-*"))
    assert all(path.is_dir() for path in leftovers)


@pytest.mark.parametrize("checkpoint", POST_PUBLISH)
def test_subprocess_crash_after_publication_leaves_complete_destination(tmp_path: Path, checkpoint: str):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    result = _crash_materialize(root, destination, checkpoint)
    assert result.returncode == 77, (checkpoint, result.stdout, result.stderr)
    assert destination.is_dir()
    # A fresh reader invocation must see the same complete inventory.
    files = sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file())
    assert files
    assert not list(tmp_path.glob(".restored.materializing-*"))


def test_exception_before_publish_removes_private_temp(tmp_path: Path):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    def fail(name: str) -> None:
        if name == "materialize_after_file":
            raise RuntimeError("injected")
    bridge._fault_hook = fail
    with pytest.raises(RuntimeError, match="injected"):
        bridge.materialize_current(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".restored.materializing-*"))


def test_zero_progress_write_never_publishes(tmp_path: Path, monkeypatch):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    monkeypatch.setattr(os, "write", lambda fd, data: 0)
    with pytest.raises(GuaranteedStorageError, match="no progress"):
        bridge.materialize_current(destination)
    assert not destination.exists()


def test_short_writes_are_retried_and_exact(tmp_path: Path, monkeypatch):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    original = os.write
    calls = 0
    regular_fds: set[int] = set()
    original_open = os.open
    def tracked_open(path, flags, mode=0o777):
        fd = original_open(path, flags, mode)
        if flags & os.O_WRONLY:
            regular_fds.add(fd)
        return fd
    def short(fd, data):
        nonlocal calls
        if fd in regular_fds:
            calls += 1
            return original(fd, data[: max(1, len(data) // 3)])
        return original(fd, data)
    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "write", short)
    report = bridge.materialize_current_report(destination)
    assert report.published is True
    assert report.files_materialized > 0
    assert report.bytes_materialized > 0
    assert calls > report.files_materialized


def _rewrite_image(bridge: GuaranteedStorageBridge, records: list[tuple[str, bytes]]) -> None:
    generation = bridge.store.verify(bridge.store.current_generation())
    payload = bytearray(b"TDSIMG1\n")
    for name, data in records:
        raw = name.encode("utf-8")
        payload += struct.pack(">IQ", len(raw), len(data)) + raw + data + hashlib.sha256(data).digest()
    payload += struct.pack(">IQ", 0, 0)
    data_path = generation.path / bridge.store.DATA_NAME
    data_path.write_bytes(payload)
    meta_path = generation.path / bridge.store.META_NAME
    meta = json.loads(meta_path.read_text())
    meta["data_size"] = len(payload)
    meta["data_sha256"] = hashlib.sha256(payload).hexdigest()
    meta_path.write_text(json.dumps(meta, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("records,match", [
    ([("a.txt", b"1"), ("a.txt", b"2")], "duplicate"),
    ([("é.txt", b"1"), ("e\u0301.txt", b"2")], "Unicode-normalization"),
    ([("A.txt", b"1"), ("a.txt", b"2")], "case-folding"),
])
def test_path_collisions_fail_closed(tmp_path: Path, records, match):
    bridge = GuaranteedStorageBridge(tmp_path / "store")
    bridge.store.commit(b"placeholder")
    _rewrite_image(bridge, records)
    with pytest.raises(GuaranteedStorageError, match=match):
        bridge.materialize_current(tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_unexpected_file_in_private_tree_prevents_publication(tmp_path: Path):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    injected = False
    def inject(name: str) -> None:
        nonlocal injected
        if name == "materialize_before_directory_fsync" and not injected:
            private = next(tmp_path.glob(".restored.materializing-*"))
            (private / "unexpected.bin").write_bytes(b"not in manifest")
            injected = True
    bridge._fault_hook = inject
    with pytest.raises(GuaranteedStorageError, match="unexpected"):
        bridge.materialize_current(destination)
    assert not destination.exists()


def test_destination_appearing_during_materialization_is_not_overwritten(tmp_path: Path):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    def race(name: str) -> None:
        if name == "materialize_after_directory_fsync":
            destination.mkdir()
            (destination / "owner.txt").write_text("external")
    bridge._fault_hook = race
    with pytest.raises(GuaranteedStorageError, match="appeared"):
        bridge.materialize_current(destination)
    assert (destination / "owner.txt").read_text() == "external"


def test_permission_failure_never_publishes(tmp_path: Path, monkeypatch):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    original_open = os.open
    def denied(path, flags, mode=0o777, *, dir_fd=None):
        if flags & os.O_WRONLY and flags & os.O_EXCL and ".materializing-" in str(path):
            raise PermissionError("injected permission denial")
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(PermissionError, match="injected"):
        bridge.materialize_current(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".restored.materializing-*"))


def test_repeated_materializations_are_byte_deterministic(tmp_path: Path):
    root = tmp_path / "store"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    first = bridge.materialize_current(tmp_path / "first")
    second = bridge.materialize_current(tmp_path / "second")
    first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
    assert first_files == second_files


def test_symlink_in_private_tree_prevents_publication(tmp_path: Path):
    root = tmp_path / "store"
    destination = tmp_path / "restored"
    bridge = GuaranteedStorageBridge(root)
    bridge.commit_filesystem(_fs(), parallel_nodes=False)
    def inject(name: str) -> None:
        if name == "materialize_after_directory_fsync":
            private = next(tmp_path.glob(".restored.materializing-*"))
            os.symlink("outside", private / "unexpected-link")
    bridge._fault_hook = inject
    with pytest.raises(GuaranteedStorageError, match="unexpected"):
        bridge.materialize_current(destination)
    assert not destination.exists()

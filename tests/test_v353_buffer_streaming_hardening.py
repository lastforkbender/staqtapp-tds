from __future__ import annotations

from array import array
import hashlib
import os

import pytest

from staqtapp_tds import BufferContractError, BufferPolicy, GenerationError, ImmutableGenerationStore


def test_bytes_and_readonly_contiguous_views_use_stable_path(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    payload = b"stable-buffer" * 257
    first = store.commit(payload)
    assert first.data_sha256 == hashlib.sha256(payload).hexdigest()

    view = memoryview(payload)
    try:
        second = store.commit(view)
    finally:
        view.release()
    assert second.data_size == len(payload)
    assert store.read_current() == payload


def test_mutable_buffer_rejected_by_default_before_promotion(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    original = store.commit(b"old")
    with pytest.raises(BufferContractError, match="mutable"):
        store.commit(bytearray(b"new"))
    assert store.current_generation() == original.generation_id
    assert store.read_current() == b"old"


def test_mutable_buffer_snapshot_is_immutable_commit_input(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    payload = bytearray(b"snapshot-me")
    info = store.commit(payload, buffer_policy=BufferPolicy.SNAPSHOT)
    payload[:] = b"changed-now"
    assert store.read_current() == b"snapshot-me"
    assert info.data_sha256 == hashlib.sha256(b"snapshot-me").hexdigest()


def test_non_contiguous_view_rejected_or_explicitly_snapshotted(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    source = memoryview(b"abcdefgh")[::2]
    try:
        with pytest.raises(BufferContractError, match="non-contiguous"):
            store.commit(source)
        store.commit(source, buffer_policy="snapshot")
    finally:
        source.release()
    assert store.read_current() == b"aceg"


def test_multibyte_readonly_buffer_is_written_as_raw_bytes(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    raw = array("I", [1, 2, 0xAABBCCDD]).tobytes()
    view = memoryview(raw).cast("I")
    try:
        info = store.commit(view)
    finally:
        view.release()
    assert info.data_size == len(raw)
    assert store.read_current() == raw


def test_short_writes_are_retried_and_hash_exact_written_bytes(tmp_path, monkeypatch):
    store = ImmutableGenerationStore(tmp_path)
    payload = b"partial-write" * 1000
    real_write = os.write

    def short_write(fd: int, data):
        return real_write(fd, data[: max(1, min(len(data), 37))])

    monkeypatch.setattr(os, "write", short_write)
    info = store.commit(payload)
    assert info.data_size == len(payload)
    assert info.data_sha256 == hashlib.sha256(payload).hexdigest()
    assert store.read_current() == payload


def test_zero_progress_write_fails_without_promoting_current(tmp_path, monkeypatch):
    store = ImmutableGenerationStore(tmp_path)
    original = store.commit(b"old")
    real_write = os.write
    calls = 0

    def no_progress(fd: int, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 0
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", no_progress)
    with pytest.raises(GenerationError, match="no forward progress"):
        store.commit(b"new")
    monkeypatch.setattr(os, "write", real_write)
    assert store.current_generation() == original.generation_id
    assert store.read_current() == b"old"


def test_memoryview_released_after_success_allows_exporter_resize(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    payload = bytearray(b"mutable")
    store.commit(payload, buffer_policy="snapshot")
    payload.extend(b"-resized")
    assert payload == bytearray(b"mutable-resized")


def test_unknown_buffer_policy_fails_closed(tmp_path):
    with pytest.raises(BufferContractError, match="unsupported buffer policy"):
        ImmutableGenerationStore(tmp_path).commit(b"x", buffer_policy="unsafe_magic")

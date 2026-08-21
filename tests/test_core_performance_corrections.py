from __future__ import annotations

import threading
import zlib
from concurrent.futures import ThreadPoolExecutor

import pytest

import staqtapp_tds.tds_persistence as persistence_module
from staqtapp_tds.tds_filesystem import CompressorRegistry, TDSFileSystem
from staqtapp_tds.tds_persistence import (
    FILE_HDR_SIZE,
    TDSPersistence,
    TDSPersistenceIntegrityError,
    TDSReader,
)
from staqtapp_tds.telemetry import TelemetryManager


INT64_MAX = (1 << 63) - 1


def require_native():
    try:
        from staqtapp_tds import _native_index
    except Exception:
        pytest.skip("native index extension not built")
    return _native_index


def test_native_automatic_allocator_preserves_high_water_across_delete_resize_and_restore() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)

    assert [index.put(f"first-{i}".encode()) for i in range(12)] == list(range(1, 13))
    assert index.pop(b"first-3") == 4
    assert index.put(b"after-delete") == 13

    before_resize = index.stats()
    assert before_resize["capacity"] >= 16
    for i in range(32):
        index.put(f"resize-{i}".encode())
    after_resize = index.stats()
    assert after_resize["capacity"] > before_resize["capacity"]
    assert index.put(b"after-resize") == 46

    # A reopened/restored index rebuilds the high-water mark through the
    # existing explicit-handle lane; the next automatic handle follows it.
    restored = native.NativeHandleIndex(capacity=16)
    assert restored.put(b"restored-low", 4) == 4
    assert restored.put(b"restored-high", 46) == 46
    assert restored.put(b"restored-auto") == 47
    with pytest.raises(ValueError, match="already assigned"):
        restored.put(b"restored-duplicate", 46)
    with pytest.raises(ValueError, match="monotonic high-water"):
        restored.put(b"restored-reuse", 12)


def test_native_automatic_allocator_is_unique_under_concurrent_insertion() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)
    workers = 8
    per_worker = 250
    barrier = threading.Barrier(workers)

    def insert(worker: int) -> list[int]:
        barrier.wait()
        return [
            int(index.put(f"worker-{worker}-{item}".encode()))
            for item in range(per_worker)
        ]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        handles = [
            handle
            for batch in pool.map(insert, range(workers))
            for handle in batch
        ]

    expected_count = workers * per_worker
    assert len(handles) == expected_count
    assert len(set(handles)) == expected_count
    assert sorted(handles) == list(range(1, expected_count + 1))
    assert index.stats()["next_handle"] == expected_count + 1


def test_native_allocator_exhaustion_remains_sticky_after_delete() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)

    assert index.put(b"last", INT64_MAX) == INT64_MAX
    assert index.pop(b"last") == INT64_MAX
    assert index.stats()["next_handle"] == 0
    with pytest.raises(OverflowError, match="allocator exhausted"):
        index.put(b"no-reuse")


def test_native_backend_does_not_multiply_python_shards_into_empty_capacity() -> None:
    require_native()
    from staqtapp_tds.backends.native_index import NativeEntryIndexBackend

    backend = NativeEntryIndexBackend(shards=64)
    assert backend.stats().capacity == 1024
    with pytest.raises(ValueError, match="shards must be positive"):
        NativeEntryIndexBackend(shards=0)


class _CountingRLock:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.acquisitions = 0

    def __enter__(self):
        self.acquisitions += 1
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.release()


def test_telemetry_operation_updates_use_one_lock_and_preserve_exact_values() -> None:
    manager = TelemetryManager()
    lock = _CountingRLock()
    manager._lock = lock

    manager.record_read(17, hit=False, backend="native-c-swiss")
    assert lock.acquisitions == 1
    assert manager._counters["reads"] == 1
    assert manager._counters["lookups"] == 1
    assert manager._counters["lookup_misses"] == 1
    assert manager._counters["native_backend_ops"] == 1
    assert manager._counters["gil_released_ops"] == 1
    assert manager._timers_ns["read_ns"] == 17
    assert manager._timers_ns["lookup_ns"] == 17
    assert manager._timer_counts["read_ns"] == 1
    assert manager._timer_counts["lookup_ns"] == 1

    lock.acquisitions = 0
    manager.record_write(-5, raw_size=-2, stored_size=9, backend="python-sharded")
    assert lock.acquisitions == 1
    assert manager._counters["writes"] == 1
    assert manager._counters["bytes_raw"] == 0
    assert manager._counters["bytes_stored"] == 9
    assert manager._counters["python_backend_ops"] == 1
    assert manager._timers_ns["write_ns"] == 0
    assert manager._timer_counts["write_ns"] == 1

    lock.acquisitions = 0
    manager.record_json(parse_ns=11, serialize_ns=13, backend="orjson")
    assert lock.acquisitions == 1
    assert manager._counters["json_parse_ns"] == 11
    assert manager._counters["json_serialize_ns"] == 13
    assert manager._counters["json_parse_calls"] == 1
    assert manager._counters["json_serialize_calls"] == 1
    assert manager._counters["json_orjson_writes"] == 1


def test_reader_indexes_sidecar_metadata_once(tmp_path) -> None:
    fs = TDSFileSystem()
    fs.root.write_text("alpha", "payload")
    TDSPersistence(tmp_path).flush(fs, parallel_nodes=False)

    with TDSReader(tmp_path / "tds_root.tds") as reader:
        slot_key = "/tds_root/alpha"
        expected = reader._entry_meta["alpha"]
        assert reader._meta_by_slot[slot_key] is expected
        assert reader._meta_for_slot(slot_key) is expected

        class _NoScanDict(dict):
            def items(self):
                raise AssertionError("per-read sidecar scan")

        reader._entry_meta = _NoScanDict(reader._entry_meta)
        assert reader._meta_for_slot(slot_key) is expected
        assert reader.read(slot_key) == "payload"


def test_reader_reload_binds_index_metadata_and_backing_to_one_snapshot(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    persistence = TDSPersistence(tmp_path)
    first = TDSFileSystem()
    first.root.write_text("alpha", "alpha")
    persistence.flush(first, parallel_nodes=False)
    path = tmp_path / "tds_root.tds"
    reader = TDSReader(path)

    second = TDSFileSystem()
    second.root.write_text("alpha", "bravo")
    persistence.flush(second, parallel_nodes=False)
    with TDSReader(path) as fresh:
        record = fresh._idx.lookup("/tds_root/alpha")
        assert record is not None
        payload_offset = int(fresh._hdr["data_offset"]) + int(record.offset)
    with path.open("r+b") as handle:
        handle.seek(payload_offset)
        handle.write(b"c")

    reload_entered = threading.Event()
    release_reload = threading.Event()
    lookup_called = threading.Event()
    original_load_sidecar = TDSReader._load_sidecar
    original_lookup = persistence_module.SlotIndex.lookup

    def paused_load_sidecar(candidate) -> None:
        if candidate is not reader:
            reload_entered.set()
            if not release_reload.wait(5):
                raise AssertionError("reload coordination timed out")
        original_load_sidecar(candidate)

    def tracked_lookup(self, name):
        lookup_called.set()
        return original_lookup(self, name)

    monkeypatch.setattr(TDSReader, "_load_sidecar", paused_load_sidecar)
    monkeypatch.setattr(persistence_module.SlotIndex, "lookup", tracked_lookup)
    reload_errors: list[BaseException] = []

    def reload_reader() -> None:
        try:
            reader.reload()
        except BaseException as exc:  # pragma: no cover - surfaced below
            reload_errors.append(exc)

    reload_thread = threading.Thread(target=reload_reader)
    reload_thread.start()
    assert reload_entered.wait(5)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(reader.read, "/tds_root/alpha")
            assert lookup_called.wait(0.1) is False
            release_reload.set()
            result = pending.result(timeout=5)
    finally:
        release_reload.set()
        reload_thread.join(timeout=5)
        reader.close()

    assert not reload_thread.is_alive()
    assert reload_errors == []
    assert result.ok is False
    assert result.code == "PERSIST_PAYLOAD_HASH_MISMATCH"


def test_reader_reload_failure_preserves_previous_valid_snapshot(tmp_path) -> None:
    persistence = TDSPersistence(tmp_path)
    fs = TDSFileSystem()
    fs.root.write_text("alpha", "original")
    persistence.flush(fs, parallel_nodes=False)
    path = tmp_path / "tds_root.tds"

    with TDSReader(path) as reader:
        meta_path = path.with_suffix(".tds.meta")
        meta_path.write_bytes(b"{malformed")

        with pytest.raises(TDSPersistenceIntegrityError):
            reader.reload()

        assert reader.read("/tds_root/alpha") == "original"
        assert reader.keys() == ["/tds_root/alpha"]


def test_read_many_binds_every_entry_to_one_reload_epoch(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persistence = TDSPersistence(tmp_path)
    first = TDSFileSystem()
    first.root.write_text("alpha", "old-alpha")
    first.root.write_text("beta", "old-beta")
    persistence.flush(first, parallel_nodes=False)
    path = tmp_path / "tds_root.tds"
    reader = TDSReader(path)

    second = TDSFileSystem()
    second.root.write_text("alpha", "new-alpha")
    second.root.write_text("beta", "new-beta")
    persistence.flush(second, parallel_nodes=False)

    first_bound = threading.Event()
    reload_started = threading.Event()
    reload_done = threading.Event()
    original_snapshot = reader._snapshot_read_input
    original_read_snapshot = reader._read_snapshot
    snapshot_count = 0

    def coordinated_snapshot(name, *, codec=None, content_hash=None):
        nonlocal snapshot_count
        snapshot = original_snapshot(
            name,
            codec=codec,
            content_hash=content_hash,
        )
        snapshot_count += 1
        if snapshot_count == 1:
            first_bound.set()
            assert reload_started.wait(5)
        return snapshot

    def decode_after_reload(snapshot):
        assert reload_done.wait(5)
        return original_read_snapshot(snapshot)

    monkeypatch.setattr(reader, "_snapshot_read_input", coordinated_snapshot)
    monkeypatch.setattr(reader, "_read_snapshot", decode_after_reload)

    batch_values: list[dict[str, object]] = []
    batch_errors: list[BaseException] = []

    def run_batch() -> None:
        try:
            batch_values.append(
                reader.read_many(["/tds_root/alpha", "/tds_root/beta"])
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            batch_errors.append(exc)

    def run_reload() -> None:
        reload_started.set()
        try:
            reader.reload()
        finally:
            reload_done.set()

    batch_thread = threading.Thread(target=run_batch)
    reload_thread = threading.Thread(target=run_reload)
    batch_thread.start()
    assert first_bound.wait(5)
    reload_thread.start()
    batch_thread.join(timeout=10)
    reload_thread.join(timeout=10)
    try:
        assert not batch_thread.is_alive()
        assert not reload_thread.is_alive()
        assert batch_errors == []
        assert batch_values == [
            {
                "/tds_root/alpha": "old-alpha",
                "/tds_root/beta": "old-beta",
            }
        ]
        assert reader.read("/tds_root/alpha") == "new-alpha"
        assert reader.read("/tds_root/beta") == "new-beta"
    finally:
        reader.close()


def test_compressed_persistence_read_decompresses_payload_once(tmp_path) -> None:
    calls = {"decompress": 0}

    def decompress(data: bytes) -> bytes:
        calls["decompress"] += 1
        return zlib.decompress(data)

    CompressorRegistry.register("counting-zlib", zlib.compress, decompress)
    fs = TDSFileSystem()
    fs.root.write_text(
        "compressed",
        "payload-" * 1024,
        compress=True,
        codec="counting-zlib",
    )
    TDSPersistence(tmp_path).flush(fs, parallel_nodes=False)
    calls["decompress"] = 0

    with TDSReader(tmp_path / "tds_root.tds") as reader:
        assert reader.read("/tds_root/compressed") == "payload-" * 1024
    assert calls["decompress"] == 1


def test_writer_streams_header_payloads_and_index_without_full_file_copy(tmp_path, monkeypatch) -> None:
    fs = TDSFileSystem()
    fs.root.write_text("alpha", "a" * 64)
    fs.root.write_text("beta", "b" * 96)

    chunk_batches: list[list[bytes]] = []
    original_write_chunks = persistence_module._write_chunks_buffered

    def recording_write_chunks(fd: int, chunks, **kwargs) -> None:
        materialized = [bytes(chunk) for chunk in chunks]
        chunk_batches.append(materialized)
        original_write_chunks(fd, materialized, **kwargs)

    monkeypatch.setattr(
        persistence_module,
        "_write_chunks_buffered",
        recording_write_chunks,
    )
    TDSPersistence(tmp_path).flush(fs, parallel_nodes=False)

    # One bounded stream receives header, each immutable payload view, and the
    # index. The helper's fixed buffer prevents full-file materialization while
    # avoiding one operating-system write per small slot.
    assert len(chunk_batches) == 1
    chunks = chunk_batches[0]
    assert len(chunks[0]) == FILE_HDR_SIZE
    assert chunks[1] == b"a" * 64
    assert chunks[2] == b"b" * 96
    assert chunks[3]
    assert (tmp_path / "tds_root.tds").read_bytes() == b"".join(chunks)

    with TDSReader(tmp_path / "tds_root.tds") as reader:
        assert reader.read("/tds_root/alpha") == "a" * 64
        assert reader.read("/tds_root/beta") == "b" * 96


def test_bounded_writer_handles_partial_progress_and_retains_fd_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PartialStream:
        def __init__(self):
            self.data = bytearray()
            self.flushed = False
            self.closed = False

        def write(self, data):
            count = min(3, len(data))
            self.data.extend(data[:count])
            return count

        def flush(self):
            self.flushed = True

        def close(self):
            self.closed = True

    stream = PartialStream()

    def fake_fdopen(fd, mode, *, buffering, closefd):
        assert fd == 123
        assert mode == "wb"
        assert buffering == 7
        assert closefd is False
        return stream

    monkeypatch.setattr(persistence_module.os, "fdopen", fake_fdopen)
    persistence_module._write_chunks_buffered(
        123,
        (b"abcde", b"fghij"),
        buffer_size=7,
    )

    assert bytes(stream.data) == b"abcdefghij"
    assert stream.flushed is True
    assert stream.closed is True


def test_bounded_writer_fails_on_zero_progress_and_closes_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ZeroProgressStream:
        closed = False

        def write(self, _data):
            return 0

        def flush(self):
            raise AssertionError("flush must not follow zero write progress")

        def close(self):
            self.closed = True

    stream = ZeroProgressStream()
    monkeypatch.setattr(
        persistence_module.os,
        "fdopen",
        lambda *_args, **_kwargs: stream,
    )

    with pytest.raises(TDSPersistenceIntegrityError) as error:
        persistence_module._write_chunks_buffered(123, (b"payload",))

    assert error.value.code == "PERSIST_WRITE_ERROR"
    assert stream.closed is True


def test_persistence_write_failure_removes_shadow_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filesystem = TDSFileSystem()
    filesystem.root.write_text("alpha", "payload")

    def failed_write(*_args, **_kwargs):
        raise OSError("injected buffered write failure")

    monkeypatch.setattr(persistence_module, "_write_chunks_buffered", failed_write)
    with pytest.raises(OSError, match="injected"):
        TDSPersistence(tmp_path).flush(filesystem, parallel_nodes=False)

    assert not (tmp_path / "tds_root.tds~").exists()

from __future__ import annotations

import sys
import threading

import pytest


native_csv = pytest.importorskip("staqtapp_tds._csv_scan_kernel")


def _scan(raw: object, *, chunk_size: int = 3) -> dict[str, object]:
    return native_csv.scan_bytes(
        raw,
        delimiter=ord(","),
        quote=ord('"'),
        escape=-1,
        doublequote=1,
        chunk_size=chunk_size,
    )


def _offsets(raw: object, *, chunk_size: int = 3) -> dict[str, object]:
    return native_csv.row_offsets(
        raw,
        quote=ord('"'),
        escape=-1,
        doublequote=1,
        chunk_size=chunk_size,
    )


def test_native_csv_declares_immutable_input_ownership() -> None:
    assert native_csv.CSV_NATIVE_SCAN_KERNEL_ABI == "tds.csv.scan.kernel.prototype.v1"
    assert native_csv.CSV_NATIVE_SCAN_KERNEL_BACKEND == "native.c.csv_scan.prototype"
    assert (
        native_csv.CSV_NATIVE_SCAN_INPUT_OWNERSHIP
        == "bytes-zero-copy;other-contiguous-buffers-snapshot"
    )


def test_scan_and_row_offsets_match_for_supported_buffer_exporters() -> None:
    raw = b'id,name\r\n1,"Ada\nLovelace"\r\n2,Grace\r3,Hopper\n'
    expected_scan = _scan(raw, chunk_size=7)
    expected_offsets = _offsets(raw, chunk_size=7)

    mutable = bytearray(raw)
    cases = (
        mutable,
        memoryview(raw),
        memoryview(mutable),
        memoryview(mutable).toreadonly(),
    )
    for payload in cases:
        assert _scan(payload, chunk_size=7) == expected_scan
        assert _offsets(payload, chunk_size=7) == expected_offsets


def test_mutable_exporter_is_released_after_snapshot_scan() -> None:
    payload = bytearray(b"a,b\n1,2\n")
    assert _scan(payload)["row_count"] == 2
    payload.extend(b"3,4\n")
    assert payload.endswith(b"3,4\n")


def test_non_contiguous_buffer_is_rejected_before_gil_free_work() -> None:
    payload = memoryview(b"abcdef")[::2]
    with pytest.raises((BufferError, TypeError)):
        _scan(payload)
    with pytest.raises((BufferError, TypeError)):
        _offsets(payload)


def test_token_and_chunk_bounds_fail_before_native_scan() -> None:
    with pytest.raises(ValueError):
        native_csv.scan_bytes(b"a,b", ord(","), ord('"'), -2, 1, 0)
    with pytest.raises(ValueError):
        native_csv.row_offsets(b"a,b", ord('"'), -2, 1, 0)
    with pytest.raises(ValueError):
        native_csv.scan_bytes(b"a,b", ord(","), ord('"'), -1, 1, -1)


def test_mutable_buffer_changes_after_snapshot_do_not_change_scan_result() -> None:
    # The mutator is made runnable immediately before the C call. A long Python
    # switch interval prevents it from running until the native scanner releases
    # the GIL. The scanner must therefore continue from its pre-release snapshot,
    # not from the concurrently changed bytearray.
    repeats = 1_000_000
    original = b"a,b," * repeats
    replacement = b"a;b;" * repeats
    payload = bytearray(original)
    expected = _scan(original, chunk_size=8191)
    start = threading.Event()

    def mutate() -> None:
        start.wait()
        payload[:] = replacement

    thread = threading.Thread(target=mutate, name="csv-buffer-mutator")
    previous_interval = sys.getswitchinterval()
    try:
        sys.setswitchinterval(60.0)
        thread.start()
        start.set()
        observed = _scan(payload, chunk_size=8191)
    finally:
        sys.setswitchinterval(previous_interval)
        thread.join(timeout=10.0)

    assert not thread.is_alive()
    assert payload == replacement
    assert observed == expected
    assert observed["delimiter_count"] == repeats * 2
    assert observed["row_count"] == 1

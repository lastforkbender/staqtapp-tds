from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from struct import pack, unpack_from

import pytest

from staqtapp_tds.backends.native_index import (
    NativeEntryIndexBackend,
    NativeFrozenHandleView,
)
from staqtapp_tds.native.manager import NativeEngineManager


FROZEN_CONTRACT = "immutable-rehash-copy;lock-free-read-v1"
PACKED_CONTRACT = (
    "keys-bytes;offsets-le64;handles-le-i64;caller-owned-output-v1"
)
MAX_KEYS = 65_536


def require_native():
    try:
        from staqtapp_tds import _native_index
    except Exception:
        pytest.skip("native index extension not built")
    return _native_index


def pack_keys(keys: list[bytes]) -> tuple[bytes, bytes]:
    blob = b"".join(keys)
    offsets = [0]
    total = 0
    for key in keys:
        total += len(key)
        offsets.append(total)
    return blob, b"".join(pack("<Q", value) for value in offsets)


def decode_handles(output: bytes | bytearray | memoryview) -> list[int]:
    view = memoryview(output).cast("B")
    return [
        unpack_from("<q", view, offset)[0]
        for offset in range(0, len(view), 8)
    ]


def test_v360_frozen_and_packed_contracts_are_declared_and_admitted() -> None:
    native = require_native()

    assert native.TDS_NATIVE_FROZEN_INDEX_CONTRACT == FROZEN_CONTRACT
    assert native.TDS_NATIVE_PACKED_LOOKUP_CONTRACT == PACKED_CONTRACT
    assert native.TDS_NATIVE_PACKED_LOOKUP_MAX_KEYS == MAX_KEYS
    capabilities = set(native.TDS_NATIVE_CAPABILITIES.split(","))
    assert {"frozen_index_v1", "packed_lookup_v1"} <= capabilities

    module, report = NativeEngineManager().inspect_module(
        "staqtapp_tds._native_index"
    )
    assert module is native
    assert report.compatible is True
    assert report.capabilities["has_frozen_index"] is True
    assert report.capabilities["frozen_index_contract"] == FROZEN_CONTRACT
    assert report.capabilities["has_packed_lookup"] is True
    assert report.capabilities["packed_lookup_contract"] == PACKED_CONTRACT
    assert report.capabilities["packed_lookup_max_keys"] == MAX_KEYS


def test_v360_frozen_type_is_created_only_from_a_mutable_snapshot() -> None:
    native = require_native()

    with pytest.raises(TypeError):
        native.NativeFrozenHandleIndex()

    source = native.NativeHandleIndex(capacity=16)
    frozen = source.freeze()
    assert type(frozen) is native.NativeFrozenHandleIndex
    assert not hasattr(frozen, "put")
    assert not hasattr(frozen, "pop")


def test_v360_freeze_rehashes_only_live_entries_and_preserves_handles() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=32)
    expected: dict[bytes, int] = {}

    for value in range(20):
        key = f"key-{value:02d}".encode("ascii")
        expected[key] = int(source.put(key))
    for value in (1, 4, 7, 10, 13, 16):
        key = f"key-{value:02d}".encode("ascii")
        assert source.pop(key) == expected.pop(key)

    source_stats = source.stats()
    assert source_stats["tombstones"] > 0
    frozen = source.freeze()
    identity = frozen.identity()
    stats = frozen.stats()

    assert identity["snapshot_id"] > 0
    assert identity["source_namespace_id"] == source.identity()[0]
    assert identity["source_index_epoch"] == source.identity()[1]
    assert identity["size"] == len(expected)
    assert identity["frozen_index_contract"] == FROZEN_CONTRACT
    assert identity["packed_lookup_contract"] == PACKED_CONTRACT
    assert stats["size"] == len(expected)
    assert stats["key_bytes"] == sum(len(key) for key in expected)
    assert 16 <= stats["capacity"] <= source_stats["capacity"]
    assert stats["capacity"] >= max(16, 2 * len(expected))

    for key, handle in expected.items():
        assert frozen.get_handle(key) == handle
        assert frozen.contains(key) is True
    assert frozen.get_handle(b"missing") == -1
    assert frozen.contains(b"missing") is False
    with pytest.raises(TypeError, match="exact immutable bytes"):
        frozen.get_handle(bytearray(b"key-00"))
    with pytest.raises(TypeError, match="exact immutable bytes"):
        frozen.contains(memoryview(bytearray(b"key-00")))


def test_v360_frozen_snapshot_is_independent_of_later_source_mutation() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=16)
    original = {b"alpha": source.put(b"alpha"), b"beta": source.put(b"beta")}
    frozen = source.freeze()
    frozen_identity = frozen.identity()

    assert source.pop(b"alpha") == original[b"alpha"]
    replacement = source.put(b"alpha")
    assert replacement > original[b"alpha"]
    for value in range(32):
        source.put(f"grow-{value}".encode("ascii"))

    assert source.identity()[1] > frozen_identity["source_index_epoch"]
    assert source.get_handle(b"alpha") == replacement
    assert frozen.get_handle(b"alpha") == original[b"alpha"]
    assert frozen.get_handle(b"beta") == original[b"beta"]
    assert frozen.get_handle(b"grow-31") == -1

    second = source.freeze()
    assert second.identity()["snapshot_id"] > frozen_identity["snapshot_id"]
    assert second.get_handle(b"alpha") == replacement


def test_v360_freeze_compacts_sparse_mutable_capacity() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=4096)
    for value in range(20):
        source.put(f"small-{value:02d}".encode("ascii"))

    frozen = source.freeze()
    source_capacity = source.stats()["capacity"]
    frozen_capacity = frozen.stats()["capacity"]
    assert frozen_capacity < source_capacity
    assert frozen_capacity >= 2 * int(frozen.size())
    assert frozen_capacity & (frozen_capacity - 1) == 0


def test_v360_packed_lookup_writes_canonical_signed_little_endian_results() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=16)
    alpha = source.put(b"alpha")
    beta = source.put(b"beta")
    frozen = source.freeze()

    keys, offsets = pack_keys([b"alpha", b"missing", b"beta"])
    output = bytearray(24)
    assert frozen.lookup_packed(keys, offsets, output) == 3
    assert decode_handles(output) == [alpha, -1, beta]
    assert output[8:16] == b"\xff" * 8

    stats = frozen.stats()
    assert stats["request_path_lock"] == "none"
    assert stats["shared_hot_path_state_writes"] == 0
    assert stats["general_heap_allocations_per_lookup"] == 0
    assert stats["caller_owned_output"] is True


def test_v360_packed_lookup_validates_every_offset_before_output_mutation() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=16)
    source.put(b"abc")
    frozen = source.freeze()
    sentinel = bytes([0xA5]) * 16

    cases = (
        b"",  # no initial offset
        pack("<Q", 1),  # first offset is not zero
        pack("<QQQ", 0, 3, 2),  # nonmonotonic
        pack("<QQQ", 0, 0, 3),  # empty key span
        pack("<QQ", 0, 4),  # beyond key bytes
        pack("<QQ", 0, 2),  # final offset does not cover key bytes
        b"\x00" * 9,  # not an integral uint64 vector
    )
    for offsets in cases:
        output = bytearray(sentinel)
        with pytest.raises(ValueError):
            frozen.lookup_packed(b"abc", offsets, output)
        assert bytes(output) == sentinel


def test_v360_packed_lookup_requires_exact_immutable_inputs_and_exact_output() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=16)
    source.put(b"a")
    frozen = source.freeze()
    keys, offsets = pack_keys([b"a"])

    with pytest.raises(TypeError, match="exact immutable bytes"):
        frozen.lookup_packed(bytearray(keys), offsets, bytearray(8))
    with pytest.raises(TypeError, match="exact immutable bytes"):
        frozen.lookup_packed(keys, bytearray(offsets), bytearray(8))
    with pytest.raises((BufferError, TypeError)):
        frozen.lookup_packed(keys, offsets, bytes(8))
    with pytest.raises(ValueError, match="key count times eight"):
        frozen.lookup_packed(keys, offsets, bytearray(7))

    wide_output = memoryview(bytearray(8)).cast("Q")
    with pytest.raises(TypeError, match="one-dimensional byte buffer"):
        frozen.lookup_packed(keys, offsets, wide_output)


def test_v360_packed_lookup_has_canonical_empty_and_bounded_maximum_cases() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=16)
    frozen = source.freeze()

    assert frozen.lookup_packed(b"", pack("<Q", 0), bytearray()) == 0

    max_blob = b"x" * MAX_KEYS
    offsets = b"".join(pack("<Q", value) for value in range(MAX_KEYS + 1))
    output = bytearray(MAX_KEYS * 8)
    assert frozen.lookup_packed(max_blob, offsets, output) == MAX_KEYS
    assert output == b"\xff" * len(output)

    one_over = b"\x00" * ((MAX_KEYS + 2) * 8)
    with pytest.raises(ValueError, match="key limit exceeded"):
        frozen.lookup_packed(b"", one_over, bytearray())


def test_v360_frozen_packed_reads_are_safe_for_concurrent_independent_outputs() -> None:
    native = require_native()
    source = native.NativeHandleIndex(capacity=2048)
    keys = [f"key-{value:04d}".encode("ascii") for value in range(1024)]
    expected = [int(source.put(key)) for key in keys]
    blob, offsets = pack_keys(keys)
    frozen = source.freeze()

    def worker() -> tuple[int, ...]:
        output = bytearray(len(keys) * 8)
        for _ in range(40):
            assert frozen.lookup_packed(blob, offsets, output) == len(keys)
        return tuple(decode_handles(output))

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: worker(), range(4)))
    assert results == [tuple(expected)] * 4

    stats = frozen.stats()
    assert stats["shared_hot_path_state_writes"] == 0
    assert stats["request_path_lock"] == "none"


def test_v360_python_backend_exposes_handle_only_frozen_view() -> None:
    require_native()
    backend = NativeEntryIndexBackend(shards=1)
    alpha = backend.put("alpha", {"value": 1})
    beta = backend.put("beta", {"value": 2})

    frozen = backend.freeze_handles()
    assert isinstance(frozen, NativeFrozenHandleView)
    assert len(frozen) == 2
    assert frozen.get_handle("alpha") == alpha
    assert frozen.get_handle(b"beta") == beta
    assert frozen.contains("missing") is False
    assert "source_namespace_id" in frozen.identity()

    blob, offsets = pack_keys([b"beta", b"missing", b"alpha"])
    output = bytearray(24)
    assert frozen.lookup_packed(blob, offsets, output) == 3
    assert decode_handles(output) == [beta, -1, alpha]

    backend.pop("alpha")
    assert backend.get_handle("alpha") == -1
    assert frozen.get_handle("alpha") == alpha

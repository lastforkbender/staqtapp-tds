from __future__ import annotations

import pytest

from staqtapp_tds.backends.native_index import NativeEntryIndexBackend
from staqtapp_tds.native.manager import NativeEngineManager


CONTRACT = "namespace-epoch-slot-generation-handle-v1"
INT64_MAX = (1 << 63) - 1


def require_native():
    try:
        from staqtapp_tds import _native_index
    except Exception:
        pytest.skip("native index extension not built")
    return _native_index


def test_v360_handle_reference_contract_is_declared_and_admitted() -> None:
    native = require_native()

    assert native.TDS_NATIVE_HANDLE_REF_CONTRACT == CONTRACT
    assert "handle_refs_v1" in native.TDS_NATIVE_CAPABILITIES.split(",")
    module, report = NativeEngineManager().inspect_module(
        "staqtapp_tds._native_index"
    )
    assert module is native
    assert report.compatible is True
    assert report.capabilities["has_handle_refs"] is True
    assert report.capabilities["handle_ref_contract"] == CONTRACT


def test_v360_index_identities_are_positive_unique_and_stable() -> None:
    native = require_native()

    first = native.NativeHandleIndex(capacity=16)
    second = native.NativeHandleIndex(capacity=16)
    first_identity = first.identity()
    second_identity = second.identity()
    assert first_identity[0] > 0
    assert first_identity[1] == 1
    assert second_identity[0] > 0
    assert second_identity[1] == 1
    assert first_identity != second_identity
    assert first.identity() == first_identity
    assert second.identity() == second_identity
    assert first.stats()["namespace_id"] == first_identity[0]
    assert first.stats()["index_epoch"] == first_identity[1]
    assert first.stats()["handle_ref_contract"] == CONTRACT

    with pytest.raises(TypeError):
        native.NativeHandleIndex(capacity=16, namespace_id=123)


def test_v360_explicit_handles_obey_collision_and_monotonic_high_water() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)

    assert index.put(b"alpha", 10) == 10
    assert index.put(b"alpha") == 10
    assert index.put(b"alpha", 10) == 10
    with pytest.raises(ValueError, match="existing key handle is immutable"):
        index.put(b"alpha", 11)
    with pytest.raises(ValueError, match="already assigned"):
        index.put(b"beta", 10)

    assert index.pop(b"alpha") == 10
    with pytest.raises(ValueError, match="monotonic high-water"):
        index.put(b"beta", 10)
    assert index.put(b"beta") == 11
    assert index.stats()["next_handle"] == 12

    with pytest.raises(ValueError, match="zero or positive"):
        index.put(b"negative", -1)


def test_v360_handle_allocator_exhaustion_is_deterministic() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)

    assert index.put(b"last", INT64_MAX) == INT64_MAX
    assert index.stats()["next_handle"] == 0
    assert index.put(b"last") == INT64_MAX
    with pytest.raises(OverflowError, match="allocator exhausted"):
        index.put(b"after-last")
    with pytest.raises(OverflowError, match="allocator exhausted"):
        index.put(b"after-last-explicit", INT64_MAX)


def test_v360_handle_references_reject_forgery_cross_index_and_reuse() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)
    other = native.NativeHandleIndex(capacity=16)

    handle = index.put(b"key")
    ref = index.get_handle_ref(b"key")
    assert ref is not None
    namespace_id, epoch, slot, generation, referenced_handle = ref
    assert (namespace_id, epoch) == index.identity()
    assert referenced_handle == handle
    assert generation > 0
    assert index.resolve_handle_ref(*ref) == handle
    assert other.resolve_handle_ref(*ref) == -1

    forged = (
        (namespace_id + 1, epoch, slot, generation, handle),
        (namespace_id, epoch + 1, slot, generation, handle),
        (namespace_id, epoch, slot + 1_000_000, generation, handle),
        (namespace_id, epoch, slot, generation + 1, handle),
        (namespace_id, epoch, slot, generation, handle + 1),
    )
    for candidate in forged:
        assert index.resolve_handle_ref(*candidate) == -1

    assert index.pop(b"key") == handle
    assert index.resolve_handle_ref(*ref) == -1
    new_handle = index.put(b"key")
    new_ref = index.get_handle_ref(b"key")
    assert new_ref is not None
    assert new_handle > handle
    assert new_ref[2] == slot
    assert new_ref[3] == generation + 1
    assert index.resolve_handle_ref(*new_ref) == new_handle
    assert index.resolve_handle_ref(*ref) == -1


def test_v360_resize_advances_epoch_and_invalidates_old_slot_coordinates() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)

    root_handle = index.put(b"root")
    for value in range(11):
        index.put(f"pre-{value}".encode("ascii"))
    root_ref = index.get_handle_ref(b"root")
    assert root_ref is not None
    before = index.identity()

    # Existing-key insertion is idempotent and must not force a resize merely
    # because the table is over its next-new-key threshold.
    assert index.put(b"root") == root_handle
    assert index.identity() == before
    assert index.resolve_handle_ref(*root_ref) == root_handle

    index.put(b"resize-trigger")
    after = index.identity()
    assert after[0] == before[0]
    assert after[1] == before[1] + 1
    assert index.resolve_handle_ref(*root_ref) == -1
    refreshed = index.get_handle_ref(b"root")
    assert refreshed is not None
    assert refreshed[1] == after[1]
    assert index.resolve_handle_ref(*refreshed) == root_handle


def test_v360_native_index_reinitialization_is_rejected() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)
    with pytest.raises(RuntimeError, match="already initialized"):
        index.__init__(capacity=32)



def test_v360_empty_batches_and_capacity_overflow_fail_deterministically() -> None:
    native = require_native()
    index = native.NativeHandleIndex(capacity=16)
    assert index.put_many([]) == []
    assert index.get_handles([]) == []
    assert index.pop_many([]) == []

    with pytest.raises(OverflowError, match="capacity exceeds addressable bounds"):
        native.NativeHandleIndex(capacity=(1 << 63) - 1)

def test_v360_python_native_backend_exposes_validated_handle_references() -> None:
    require_native()
    backend = NativeEntryIndexBackend(shards=1)

    handle = backend.put("alpha", {"value": 1})
    ref = backend.get_handle_ref("alpha")
    assert ref is not None
    assert backend.resolve_handle_ref(ref) == handle
    assert backend.get_handle_ref("missing") is None
    assert backend.identity() == ref[:2]

    stats = backend.native_execution_stats()
    assert stats["namespace_id"] == ref[0]
    assert stats["index_epoch"] == ref[1]
    assert stats["handle_ref_contract"] == CONTRACT

    backend.pop("alpha")
    assert backend.resolve_handle_ref(ref) == -1
    with pytest.raises(ValueError, match="five integers"):
        backend.resolve_handle_ref((1, 2, 3))  # type: ignore[arg-type]

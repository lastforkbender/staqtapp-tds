import pytest


def _native_index_type():
    _native_index = pytest.importorskip("staqtapp_tds._native_index")
    return _native_index.NativeHandleIndex


def test_tiny_key_pool_reuses_full_capacity_block_across_key_sizes() -> None:
    native_index_type = _native_index_type()
    index = native_index_type(capacity=16)

    smallest_key = b"a"
    boundary_key = b"b" * 128

    first_handle = index.put(smallest_key)
    allocated = index.stats()
    assert allocated["pool_block_size"] == 128
    assert allocated["pool_allocator_calls"] == 1
    assert allocated["pool_reuse_count"] == 0

    assert index.pop(smallest_key) == first_handle
    released = index.stats()
    assert released["pool_frees"] == 1

    second_handle = index.put(boundary_key)
    reused = index.stats()
    assert second_handle > first_handle
    assert index.get_handle(boundary_key) == second_handle
    assert reused["pool_allocator_calls"] == 1
    assert reused["pool_reuse_count"] == 1

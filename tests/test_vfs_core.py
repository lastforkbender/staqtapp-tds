import numpy as np
from staqtapp_tds import TDSFileSystem, FmtID, HybridRegistry, REGISTRY_DTYPE, SharedMemoryArena, EntryIndex


def test_registry_structured_records():
    r = HybridRegistry(capacity=2)
    r.put('a', 1)
    r.put('b', 2)
    assert r.get('a') == 1
    r.put('c', 3)
    assert len(r) == 2
    assert r.records.dtype == REGISTRY_DTYPE


def test_arena_offset_handles():
    arena = SharedMemoryArena(1024)
    h = arena.allocate(b'payload')
    assert isinstance(h, int)
    assert arena.read(h) == b'payload'


def test_entry_index_handles_and_compat_get():
    fs = TDSFileSystem('root')
    d = fs.root.mkdir('idx')
    e = d.write_entry('alpha', {'v': 1})
    handle = d._entries.get_handle('alpha')
    assert isinstance(handle, int) and handle > 0
    assert d._entries.get('alpha') is e
    assert d.read_value('alpha') == {'v': 1}
    d.delete('alpha')
    assert d._entries.get('alpha') is None


def test_directory_numpy_roundtrip():
    fs = TDSFileSystem('root')
    d = fs.root.mkdir('vectors')
    arr = np.arange(16, dtype=np.float32).reshape(4, 4)
    d.write('x', arr, fmt_id=FmtID.NUMPY_MATRIX)
    out = d.read_value('x')
    assert np.array_equal(out, arr)


def test_entry_index_backend_facade_stats():
    idx = EntryIndex(shards=8, backend='python')
    assert idx.backend_name == 'python-sharded'
    class Obj: pass
    obj = Obj()
    h = idx.put('k', obj)
    assert h > 0
    assert idx.get_handle('k') == h
    assert idx.get_by_handle(h) is obj
    assert idx.stats().size == 1


def test_arena_stats_and_view():
    arena = SharedMemoryArena(128)
    h = arena.allocate(memoryview(b'abc'))
    assert arena.view(h).tobytes() == b'abc'
    st = arena.stats()
    assert st.allocations == 1
    assert st.used > 0

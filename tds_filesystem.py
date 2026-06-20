"""
Updated 6-20-26, several critical & minor issues fixed

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
>>> Staqtapp-TDS v1.1.188 / tds_filesystem.py
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////



Staqtapp-TDS / Temporal Directory System
VFS for ASI large scale computation
Extension: .tds



---- Architecture ----
  
  > Compressed binary directory headers
  > Numba-JIT hot paths for parsing/math
  > Probability-weighted LRU registry with concurrent pool hooks
  > Loop cache for overwrite-cycle variables
  > Matrix symbol switching with recursive array joins
  > Parallel sub-directory I/O via guaranteed concurrency extension
"""

from __future__ import annotations
import asyncio
import math
import os
import pickle
import struct
import time
import threading
import uuid
import zlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

try:
    from numba import njit, prange
    NUMBA_AVAILABLE = True
except ImportError:
    def njit(*args, **kwargs):
        def decorator(fn): return fn
        return decorator if args and callable(args[0]) else decorator
    prange = range
    NUMBA_AVAILABLE = False

# ////////////////////////////////////////////////////////////////////////////////
# § 1  HEADER ENCODING
# ////////////////////////////////////////////////////////////////////////////////

TDS_MAGIC = b'\x54\x44\x53\x01'
HEADER_FMT = '>4sQQHHIII'
HEADER_SIZE = struct.calcsize(HEADER_FMT) # 36 bytes

class FmtID(IntFlag):
    RAW_BINARY = 0x00
    NUMPY_MATRIX = 0x01
    PICKLE_OBJ = 0x02
    SYMBOL_TABLE = 0x04
    LOOP_CACHE = 0x08
    COMPRESSED = 0x80


class DirFlags(IntEnum):
    NONE = 0x0000
    READONLY = 0x0001
    ENCRYPTED = 0x0002
    PARALLEL_IO = 0x0004
    LOOP_PINNED = 0x0008
    RECURSIVE = 0x0010
    PROB_SORT = 0x0020

def encode_header(ts_create: int, ts_mod: int, flags: int, fmt_id: int, subdir_count: int, entry_count: int) -> bytes:
    payload = struct.pack(HEADER_FMT, TDS_MAGIC, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, 0)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    return struct.pack(HEADER_FMT, TDS_MAGIC, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, crc)

def decode_header(raw: bytes) -> dict:
    if len(raw) < HEADER_SIZE:
        raise ValueError("Buffer too small for TDS header")
    magic, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, crc = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    if magic != TDS_MAGIC:
        raise ValueError(f"Invalid TDS magic: {magic!r}")
    repacked = struct.pack(HEADER_FMT, magic, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, 0)
    expected = zlib.crc32(repacked) & 0xFFFFFFFF
    if crc != expected:
        raise ValueError("TDS header checksum mismatch")
    return {'ts_create': ts_create, 'ts_mod': ts_mod, 'flags': flags, 'fmt_id': fmt_id, 'subdir_count': subdir_count, 'entry_count': entry_count, 'crc': crc}

# ////////////////////////////////////////////////////////////////////////////////
# § 2  NUMBA-JIT KERNELS
# ////////////////////////////////////////////////////////////////////////////////

@njit(cache=True)
def _compute_subdir_offsets(entry_sizes: np.ndarray) -> np.ndarray:
    n = entry_sizes.shape[0]
    offsets = np.empty(n + 1, dtype=np.int64)
    offsets[0] = 0
    for i in range(n): offsets[i + 1] = offsets[i] + entry_sizes[i]
    return offsets

@njit(cache=True)
def _probability_decay(access_counts: np.ndarray, last_access_times: np.ndarray, now: float, decay_lambda: float) -> np.ndarray:
    n = access_counts.shape[0]
    scores = np.empty(n, dtype=np.float64)
    for i in prange(n):
        dt = now - last_access_times[i]
        scores[i] = access_counts[i] * math.exp(-decay_lambda * dt)
    return scores

@njit(cache=True)
def _matrix_symbol_swap(matrix: np.ndarray, old_val: np.float64, new_val: np.float64) -> np.ndarray:
    rows, cols = matrix.shape
    for i in prange(rows):
        for j in range(cols):
            if matrix[i, j] == old_val: matrix[i, j] = new_val
    return matrix

# Sequential implementation used directly by recursive_join()
def _join_segments(segments: List[np.ndarray]) -> np.ndarray:
    if not segments:
        return np.array([], dtype=np.float64)
    return np.concatenate(segments)

# ////////////////////////////////////////////////////////////////////////////////
# § 3  PROBABILITY LRU REGISTRY
# ////////////////////////////////////////////////////////////////////////////////

class HybridRegistry:
    def __init__(self, capacity: int = 4096, decay_lambda: float = 1e-4):
        self._cap = capacity
        self._lam = decay_lambda
        self._lock = threading.RLock()
        self._store: Dict[str, list] = {}
        self._order: OrderedDict = OrderedDict()

    def _rebuild_score_arrays(self) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        keys = list(self._store.keys())
        counts = np.array([self._store[k][0] for k in keys], dtype=np.float64)
        times = np.array([self._store[k][1] for k in keys], dtype=np.float64)
        return counts, times, keys

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            now = time.monotonic()
            if key in self._store:
                self._store[key][0] += 1; self._store[key][1] = now
                self._store[key][2] = value; self._order.move_to_end(key)
            else:
                if len(self._store) >= self._cap:
                    evict_key, _ = self._order.popitem(last=False)
                    del self._store[evict_key]
                self._store[key] = [1, now, value]
                self._order[key] = True

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                return None
            entry = self._store[key]; entry[0] += 1; entry[1] = time.monotonic()
            self._order.move_to_end(key)
            return entry[2]

    def remove(self, key: str) -> None:
        with self._lock:
            if key in self._store:
                del self._store[key]; self._order.pop(key, None)

    def sorted_keys(self) -> List[str]:
        with self._lock:
            if not self._store:
                return []
            counts, times, keys = self._rebuild_score_arrays()
            scores  = _probability_decay(counts, times, time.monotonic(), self._lam)
            indices = np.argsort(-scores)
            return [keys[i] for i in indices]

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

# ////////////////////////////////////////////////////////////////////////////////
# § 4  LOOP CACHE
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class LoopCacheSlot:
    name: str
    cycle: int
    _write_cnt: int = 0
    current: Any = None

    def write(self, value: Any) -> bool:
        self._write_cnt += 1
        if self._write_cnt % self.cycle == 0:
            self.current = value
            return True
        return False

    def read(self) -> Any:
        return self.current

class LoopCacheManager:
    def __init__(self):
        self._slots: Dict[str, LoopCacheSlot] = {}
        self._lock = threading.Lock()

    def register(self, name: str, cycle: int = 1) -> LoopCacheSlot:
        with self._lock:
            slot = LoopCacheSlot(name=name, cycle=cycle); self._slots[name] = slot
            return slot

    def write(self, name: str, value: Any) -> bool:
        with self._lock:
            return self._slots[name].write(value)

    def read(self, name: str) -> Any:
        with self._lock:
            return self._slots[name].read()

    def batch_flush_numpy(self, name: str, arr: np.ndarray, axis: int = 0) -> Optional[np.ndarray]:
        with self._lock:
            slot = self._slots[name]
            if slot.current is None: slot.current = arr
            else: slot.current = np.concatenate([slot.current, arr], axis=axis)
            slot._write_cnt += 1
            if slot._write_cnt % slot.cycle == 0:
                result = slot.current; slot.current = None
                return result
            return None

# ////////////////////////////////////////////////////////////////////////////////
# § 5  CONCURRENCY POOL
# ////////////////////////////////////////////////////////////////////////////////

class ConcurrencyPool:
    _global_instance: Optional['ConcurrencyPool'] = None
    _init_lock = threading.Lock()

    def __init__(self, max_threads: int = 64, max_procs: int = 8):
        self._thread_pool = ThreadPoolExecutor(max_workers=max_threads, thread_name_prefix='tds_t')
        self._proc_pool = ProcessPoolExecutor(max_workers=max_procs)
        self._event_loop:  Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._event_loop is None:
            self._event_loop  = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(target=self._event_loop.run_forever, daemon=True)
            self._loop_thread.start()
        return self._event_loop

    @classmethod
    def acquire(cls) -> 'ConcurrencyPool':
        if cls._global_instance is None:
            with cls._init_lock:
                if cls._global_instance is None: cls._global_instance = cls()
        return cls._global_instance

    def submit_thread(self, fn, *args, **kwargs):
        return self._thread_pool.submit(fn, *args, **kwargs)

    def submit_process(self, fn, *args):
        return self._proc_pool.submit(fn, *args)

    async def gather_async(self, *coros):
        return await asyncio.gather(*coros)

    def run_async(self, coro):
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    def map_parallel(self, fn, items: list, use_processes: bool = False):
        if use_processes:
            raise ValueError(
                "use_processes=True requires a picklable top-level function. "
                "Pass a module-level callable or use the thread pool instead.")
        return list(self._thread_pool.map(fn, items))

    def shutdown(self):
        self._thread_pool.shutdown(wait=True)
        self._proc_pool.shutdown(wait=True)
        if self._event_loop is not None: self._event_loop.call_soon_threadsafe(self._event_loop.stop)

# ////////////////////////////////////////////////////////////////////////////////
# § 6  SYMBOL TABLE
# ////////////////////////////////////////////////////////////////////////////////

class SymbolTable:
    def __init__(self):
        self._sym_to_id: Dict[str, int] = {}
        self._id_to_sym: Dict[int, str] = {}
        self._counter = 0

    def intern(self, symbol: str) -> int:
        if symbol not in self._sym_to_id:
            self._sym_to_id[symbol] = self._counter
            self._id_to_sym[self._counter] = symbol
            self._counter += 1
        return self._sym_to_id[symbol]

    def swap(self, old_sym: str, new_sym: str, matrix: np.ndarray) -> np.ndarray:
        old_id = float(self.intern(old_sym))
        new_id = float(self.intern(new_sym))
        return _matrix_symbol_swap(matrix.astype(np.float64), old_id, new_id)

    def decode_matrix(self, matrix: np.ndarray) -> list:
        return [[self._id_to_sym.get(int(v), '?') for v in row] for row in matrix]

# ////////////////////////////////////////////////////////////////////////////////
# § 7  TDS ENTRY
# ////////////////////////////////////////////////////////////////////////////////

def _serialize_payload(data: Any, fmt_id: FmtID) -> bytes:
    base = fmt_id & ~FmtID.COMPRESSED
    if base == FmtID.NUMPY_MATRIX and isinstance(data, np.ndarray):
        import io
        buf = io.BytesIO()
        np.save(buf, data, allow_pickle=False)
        raw = buf.getvalue()
    else: raw = pickle.dumps(data, protocol=5)
    if fmt_id & FmtID.COMPRESSED: raw = zlib.compress(raw, level=6)
    return raw

def _deserialize_payload(raw: bytes, fmt_id: FmtID) -> Any:
    if fmt_id & FmtID.COMPRESSED: raw = zlib.decompress(raw)
    base = fmt_id & ~FmtID.COMPRESSED
    if base == FmtID.NUMPY_MATRIX:
        import io
        return np.load(io.BytesIO(raw), allow_pickle=False)
    try:
        return pickle.loads(raw)
    except Exception:
        return raw

@dataclass
class TDSEntry:
    name: str
    fmt_id: FmtID
    data: Any
    ts_written: int = field(default_factory=lambda: int(time.time_ns()))
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def serialise(self) -> bytes:
        raw = _serialize_payload(self.data, self.fmt_id)
        return struct.pack('>I', len(raw)) + raw

    @classmethod
    def deserialise(cls, name: str, fmt_id: FmtID, buf: bytes, ts_written: int = 0, entry_id: str = '') -> 'TDSEntry':
        length = struct.unpack('>I', buf[:4])[0]
        raw = buf[4: 4 + length]
        data = _deserialize_payload(raw, fmt_id)
        e = cls(name=name, fmt_id=fmt_id, data=data)
        if ts_written: e.ts_written = ts_written
        if entry_id: e.entry_id = entry_id
        return e

# ////////////////////////////////////////////////////////////////////////////////
# § 8  TDS DIRECTORY NODE
# ////////////////////////////////////////////////////////////////////////////////

class TDSDirectory:
    def __init__(self, name: str, fmt_id: FmtID = FmtID.RAW_BINARY, flags: int = DirFlags.NONE, parent: Optional['TDSDirectory'] = None):
        self.name = name
        self.fmt_id = fmt_id
        self.flags = flags
        self.parent = parent
        self.dir_id  = uuid.uuid4().hex
        self._ts_create = int(time.time_ns())
        self._ts_mod  = self._ts_create
        self._entries:  Dict[str, TDSEntry] = {}
        self._children: Dict[str, 'TDSDirectory'] = {}
        self._lock = threading.RLock()
        self._pool = ConcurrencyPool.acquire()
        self._registry = HybridRegistry(capacity=2048)
        self.loop_cache = LoopCacheManager()
        self.symbols = SymbolTable()

    def header_bytes(self) -> bytes:
        with self._lock:
            return encode_header(
                ts_create = self._ts_create,
                ts_mod = self._ts_mod,
                flags = self.flags,
                fmt_id = int(self.fmt_id),
                subdir_count= len(self._children),
                entry_count = len(self._entries))

    def write(self, name: str, value: Any, fmt_id: FmtID = FmtID.PICKLE_OBJ, compress: bool = False) -> 'TDSEntry':
        if compress: fmt_id = FmtID(fmt_id | FmtID.COMPRESSED)
        entry = TDSEntry(name=name, fmt_id=fmt_id, data=value)
        with self._lock:
            self._entries[name] = entry; self._ts_mod = int(time.time_ns())
        self._registry.put(name, entry)
        return entry

    def read(self, name: str) -> Any:
        with self._lock:
            cached = self._registry.get(name)
            if cached is not None:
                return cached.data
            entry = self._entries.get(name)
            if entry is None:
                raise KeyError(f"No entry '{name}' in {self.name!r}")
            self._registry.put(name, entry)
            return entry.data

    def delete(self, name: str) -> None:
        with self._lock:
            self._entries.pop(name, None); self._ts_mod = int(time.time_ns())
        self._registry.remove(name)

    def mkdir(self, name: str, **kwargs) -> 'TDSDirectory':
        child = TDSDirectory(name=name, parent=self, **kwargs)
        with self._lock:
            self._children[name] = child; self._ts_mod = int(time.time_ns())
        return child

    def cd(self, name: str) -> 'TDSDirectory':
        with self._lock:
            child = self._children.get(name)
        if child is None:
            raise KeyError(f"Sub-directory '{name}' not found in {self.name!r}")
        return child

    def ls(self, sort_by_prob: bool = True) -> List[str]:
        with self._lock:
            child_names = ['[dir] ' + n for n in self._children.keys()]
            entry_names = list(self._entries.keys())
        if sort_by_prob and (self.flags & DirFlags.PROB_SORT):
            entry_names = self._registry.sorted_keys()
        return child_names + entry_names

    def parallel_read_all(self) -> Dict[str, Any]:
        with self._lock:
            keys = list(self._entries.keys())

        def _read_one(k):
            return (k, self.read(k))

        results = self._pool.map_parallel(_read_one, keys)
        return dict(results)

    def recursive_join(self, dtype=np.float64, max_depth: int = 8) -> np.ndarray:
        segments: List[np.ndarray] = []

        def _collect(node: 'TDSDirectory', depth: int):
            if depth >= max_depth:
                return
            with node._lock:
                for entry in node._entries.values():
                    if isinstance(entry.data, np.ndarray):
                        segments.append(entry.data.astype(dtype).ravel())
                children = list(node._children.values())
            for child in children: _collect(child, depth + 1)
        _collect(self, 0)
        return _join_segments(segments)

    def build_offset_index(self) -> np.ndarray:
        with self._lock:
            entries = list(self._entries.values())
        sizes = np.array([len(e.serialise()) for e in entries], dtype=np.int64)
        return _compute_subdir_offsets(sizes)

    def to_bytes(self) -> bytes:
        header = self.header_bytes(); payloads = []
        with self._lock:
            for entry in self._entries.values():
                name_enc = entry.name.encode(); edata = entry.serialise()
                payloads.append(struct.pack('>H', len(name_enc)) + name_enc + edata)
        body = b''.join(payloads); body = zlib.compress(body, level=3)
        return header + struct.pack('>I', len(body)) + body

    def path(self) -> str:
        parts = []
        node: Optional['TDSDirectory'] = self
        while node is not None:
            parts.append(node.name); node = node.parent
        return '/' + '/'.join(reversed(parts))

    def __repr__(self) -> str:
        return (f"<TDSDirectory '{self.path()}' "
                f"entries={len(self._entries)} "
                f"subdirs={len(self._children)} "
                f"fmt={self.fmt_id.name}>")

# ////////////////////////////////////////////////////////////////////////////////
# § 9  TDS FILE SYSTEM
# ////////////////////////////////////////////////////////////////////////////////

class TDSFileSystem:
    """
    ---- Usage ----
        fs  = TDSFileSystem("asi_root")
        db  = fs.root.mkdir("databases", flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
        mem = fs.root.mkdir("working_mem", flags=DirFlags.LOOP_PINNED)
        db.write("embedding_matrix", np.random.randn(1024, 1024),
                 fmt_id=FmtID.NUMPY_MATRIX, compress=True)
        mem.loop_cache.register("gradient_buf", cycle=32)
        for step in range(100):
            g = np.random.randn(256)
            mem.loop_cache.write("gradient_buf", g)
    """
    VERSION = (1, 1, 188)

    def __init__(self, name: str = "tds_root"):
        self.root = TDSDirectory(name = name, fmt_id = FmtID.RAW_BINARY, flags = DirFlags.PARALLEL_IO | DirFlags.PROB_SORT | DirFlags.RECURSIVE)
        self._pool = ConcurrencyPool.acquire()

    def resolve(self, path: str) -> TDSDirectory:
        parts = [p for p in path.strip('/').split('/') if p]
        node  = self.root
        for part in parts:
            node = node.cd(part)
        return node

    def makedirs(self, path: str, **kwargs) -> TDSDirectory:
        parts = [p for p in path.strip('/').split('/') if p]
        node  = self.root
        for part in parts:
            try:
                node = node.cd(part)
            except KeyError:
                node = node.mkdir(part, **kwargs)
        return node

    def parallel_batch_write(self, writes: List[Tuple[str, str, Any]]) -> None:
        def _do_write(args):
            path, name, value = args
            self.resolve(path).write(name, value)
        self._pool.map_parallel(_do_write, writes)

    def snapshot_headers(self) -> Dict[str, dict]:
        result: Dict[str, dict] = {}

        def _walk(node: TDSDirectory):
            result[node.path()] = decode_header(node.header_bytes())
            with node._lock:
                children = list(node._children.values())
            for child in children: _walk(child)
        _walk(self.root)
        return result

    def __repr__(self) -> str:
        snap = self.snapshot_headers()
        total_entries = sum(v['entry_count'] for v in snap.values())
        return (f"<TDSFileSystem v{'.'.join(map(str, self.VERSION))} "
                f"dirs={len(snap)} total_entries={total_entries}>")

# ////////////////////////////////////////////////////////////////////////////////
# § 10  DEMO
# ////////////////////////////////////////////////////////////////////////////////

def demo():
    import time
    print(">> Initialising TDS VFS...")
    fs = TDSFileSystem("asi_root")

    vec_db = fs.makedirs("databases/vectors", fmt_id=FmtID.NUMPY_MATRIX, flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
    sym_db = fs.makedirs("databases/symbols", fmt_id=FmtID.SYMBOL_TABLE, flags=DirFlags.RECURSIVE)
    wm   = fs.makedirs("working_memory", flags=DirFlags.LOOP_PINNED)
    logs = fs.makedirs("logs/audit",     flags=DirFlags.NONE)
    print(">> Writing compressed numpy matrices...")
    for i in range(4):
        mat = np.random.randn(128, 128).astype(np.float32)
        vec_db.write(f"embed_{i:04d}", mat, fmt_id=FmtID.NUMPY_MATRIX, compress=True)
    print(">> Symbol table: intern + matrix swap...")
    token_mat = np.zeros((6, 6))
    sym_db.symbols.intern("NULL")
    sym_db.symbols.intern("START")
    sym_db.symbols.intern("END")
    sym_db.write("token_template", token_mat, fmt_id=FmtID.SYMBOL_TABLE)
    swapped = sym_db.symbols.swap("NULL", "START", token_mat.copy())
    sym_db.write("token_v1", swapped, fmt_id=FmtID.SYMBOL_TABLE)
    print(f"   decoded[0]: {sym_db.symbols.decode_matrix(swapped[:2])}")
    print(">> Loop cache: pinned gradient buffer (cycle=8)...")
    wm.loop_cache.register("grad_buf", cycle=8)
    cycles_triggered = 0
    for step in range(32):
        g = np.random.randn(64).astype(np.float32) * 0.01
        if wm.loop_cache.write("grad_buf", g): cycles_triggered += 1
    print(f"   Overwrite cycles triggered: {cycles_triggered}")
    print(">> Parallel batch write across logs...")
    batch = [("logs/audit", f"event_{i:06d}", {"ts": time.time_ns(), "msg": f"op_{i}"}) for i in range(16)]
    fs.parallel_batch_write(batch)
    print(">> Building Numba offset index for vec_db...")
    offsets = vec_db.build_offset_index()
    print(f"   Entry offsets (first 5): {offsets[:5].tolist()}")
    print(">> Reading back (primes prob-registry)...")
    _ = vec_db.read("embed_0000")
    _ = vec_db.read("embed_0000")
    _ = vec_db.read("embed_0001")
    print(f"   Prob-sorted ls: {vec_db.ls(sort_by_prob=True)[:5]}")
    print(">> Recursive array join across databases/...")
    db_root = fs.resolve("databases")
    joined  = db_root.recursive_join(dtype=np.float32)
    print(f"   Joined array shape: {joined.shape}  dtype: {joined.dtype}")
    print(">> delete() + registry eviction test...")
    vec_db.write("temp_entry", np.zeros(4), fmt_id=FmtID.NUMPY_MATRIX)
    _ = vec_db.read("temp_entry")      # populates registry
    vec_db.delete("temp_entry")
    try:
        vec_db.read("temp_entry")
        print("   ERROR: stale read after delete!")
    except KeyError:
        print("   OK: KeyError raised after delete (registry correctly evicted)")
    print(">> Header snapshot...")
    snap = fs.snapshot_headers()
    for path, hdr in snap.items():
        print(f"   {path:40s}  entries={hdr['entry_count']:4d}  "
              f"subdirs={hdr['subdir_count']}  crc=0x{hdr['crc']:08X}")
    print(f"\n{fs}")
    print(">> TDS demo complete.")


if __name__ == '__main__':
    demo()


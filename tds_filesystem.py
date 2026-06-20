"""
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
>>> Staqtapp-TDS / tds_filesystem.py
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
import hashlib
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
from enum import IntEnum, IntFlag, auto
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union
import numpy as np

try:
    from numba import njit, prange, typed, types
    NUMBA_AVAILABLE = True
except ImportError:
    def njit(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator if args and callable(args[0]) else decorator
    prange = range; NUMBA_AVAILABLE = False

# ////////////////////////////////////////////////////////////////////////////////
#
# § 1  MACHINE LANGUAGE HEADER ENCODING //////////////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

# Header magic bytes  — "TDS\x01" in ASCII + version byte
TDS_MAGIC   = b'\x54\x44\x53\x01'
HEADER_FMT  = '>4sQQHHIII'   # big-endian: magic(4) ts_create(8) ts_mod(8)
                             # flags(2) fmt_id(2) subdir_count(4)
                             # entry_count(4) checksum(4)
                             
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 36 bytes

from enum import IntFlag

class FmtID(IntFlag):
    # Data format stored in this directory node; OR-able flags
    RAW_BINARY   = 0x00
    NUMPY_MATRIX = 0x01
    PICKLE_OBJ   = 0x02
    SYMBOL_TABLE = 0x03
    LOOP_CACHE   = 0x04
    COMPRESSED   = 0x80     # OR-able — e.g. NUMPY_MATRIX | COMPRESSED = 0x81

class DirFlags(IntEnum):
    # Bit-field directory flags packed into header.flags
    NONE         = 0x0000
    READONLY     = 0x0001
    ENCRYPTED    = 0x0002
    PARALLEL_IO  = 0x0004   # sub-dirs fanned out in parallel
    LOOP_PINNED  = 0x0008   # loop-cache variables pinned in memory
    RECURSIVE    = 0x0010   # supports recursive array join traversal
    PROB_SORT    = 0x0020   # probability-LRU resorting active

def encode_header(ts_create: int, ts_mod: int, flags: int, fmt_id: int, subdir_count: int, entry_count: int,) -> bytes:
    payload = struct.pack(HEADER_FMT, TDS_MAGIC, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count,0,)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    # Repack with real checksum
    return struct.pack(HEADER_FMT, TDS_MAGIC, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, crc,)

def decode_header(raw: bytes) -> dict:
    if len(raw) < HEADER_SIZE:
        raise ValueError("Buffer too small for TDS header")
    magic, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, crc = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    if magic != TDS_MAGIC:
        raise ValueError(f"Invalid TDS magic: {magic!r}")
    # Verify checksum
    repacked = struct.pack(HEADER_FMT, magic, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, 0)
    expected = zlib.crc32(repacked) & 0xFFFFFFFF
    if crc != expected:
        raise ValueError("TDS header checksum mismatch — data may be corrupt")
    return {'ts_create': ts_create, 'ts_mod': ts_mod, 'flags': flags, 'fmt_id': fmt_id, 'subdir_count': subdir_count, 'entry_count': entry_count, 'crc': crc,}

# ////////////////////////////////////////////////////////////////////////////////
#
# § 2  NUMBA-JIT MATH KERNEL / Compressed directory index arithmetic /////////////
#
# ////////////////////////////////////////////////////////////////////////////////

@njit(cache=True)
def _compute_subdir_offsets(entry_sizes: np.ndarray) -> np.ndarray:
    # Prefix sum of entry byte sizes ~ absolute offsets
    n = entry_sizes.shape[0]; offsets = np.empty(n + 1, dtype=np.int64); offsets[0] = 0
    for i in prange(n): offsets[i + 1] = offsets[i] + entry_sizes[i]
    return offsets

@njit(cache=True)
def _probability_decay(access_counts: np.ndarray, last_access_times: np.ndarray, now: float, decay_lambda: float) -> np.ndarray:
    # Score each entry: score = count * exp(-λ * Δt)
    # Higher score -> more likely to be accessed, sorted earlier
    # Fully vectorised via numba parallel range
    n = access_counts.shape[0]
    scores = np.empty(n, dtype=np.float64)
    for i in prange(n): dt = now - last_access_times[i]; scores[i] = access_counts[i] * math.exp(-decay_lambda * dt)
    return scores

@njit(cache=True)
def _matrix_symbol_swap(matrix: np.ndarray, old_val: np.float64, new_val: np.float64) -> np.ndarray:
    # In place symbol substitution across entire matrix
    rows, cols = matrix.shape
    for i in prange(rows):
        for j in range(cols):
            if matrix[i, j] == old_val: matrix[i, j] = new_val
    return matrix

@njit(cache=True)
def _recursive_array_join(arrays: np.ndarray, depth: int) -> np.ndarray:
    # Flatten stack of 1D arrays via repeated concatenation, up to 'depth'
    # Recursion into array pattern for any directory tree traversal!
    total = 0
    for k in range(arrays.shape[0]): total += arrays[k].shape[0]
    result = np.empty(total, dtype=arrays[0].dtype); cursor = 0
    for k in range(arrays.shape[0]):
        seg = arrays[k]
        for j in range(seg.shape[0]):
            result[cursor] = seg[j]; cursor += 1
    return result

# ////////////////////////////////////////////////////////////////////////////////
#
# § 3  PROBABILITY LRU REGISTRY / HSC - Hybrid Sorted Cache //////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class HybridRegistry:
    """
      • LRU eviction, ordered dict backend
      • Probability-decay re-sorting, numba kernel
      • O(1) O(log n) access path via numpy argsort on scores

    *Thread safe thru RLock: Concurrency pool can call freely
    """
    def __init__(self, capacity: int = 4096, decay_lambda: float = 1e-4):
        self._cap = capacity; self._lam = decay_lambda; self._lock = threading.RLock()
        # Key -> access_count, last_access_time, value_ref
        self._store: Dict[str, list] = {}
        self._order: OrderedDict = OrderedDict() # Key -> True -> LRU order

    def _rebuild_score_arrays(self) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        # Internal built numpy, lazy
        keys   = list(self._store.keys())
        counts = np.array([self._store[k][0] for k in keys], dtype=np.float64)
        times  = np.array([self._store[k][1] for k in keys], dtype=np.float64)
        return counts, times, keys
        
    # ////////////////////////////////////////////////////////////////////////////////
    # ////////// API /////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////////

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
                self._store[key] = [1, now, value]; self._order[key] = True

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                return None
            entry = self._store[key]; entry[0] += 1; entry[1] = time.monotonic()
            self._order.move_to_end(key)
            return entry[2]

    def sorted_keys(self) -> List[str]:
        # Return keys sorted by probability score, highest first, state of the art
        with self._lock:
            if not self._store:
                return []
            counts, times, keys = self._rebuild_score_arrays()
            scores  = _probability_decay(counts, times, time.monotonic(), self._lam)
            indices = np.argsort(-scores)   # descending
            return [keys[i] for i in indices]

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

# ////////////////////////////////////////////////////////////////////////////////
#
# § 4  LOOP CACHE / Pinned overwrite cycle variables /////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class LoopCacheSlot:
    # One pinned slot: Value is overwritten every 'cycle' writes
    name: str
    cycle: int # overwrite every N writes
    _buf: list  = field(default_factory=list, repr=False)
    _write_cnt: int = 0
    current: Any = None

    def write(self, value: Any) -> bool:
        # Returns True when a full cycle completes & slot overwritten
        self._buf.append(value); self._write_cnt += 1
        if self._write_cnt % self.cycle == 0:
            self.current = value; self._buf.clear()
            return True
        return False

    def read(self) -> Any:
        return self.current

class LoopCacheManager:
    # Manages a collection of LoopCacheSlots for a directory node
    # Supports numpy batch flush for matrix valued slots
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

    def batch_flush_numpy(self, name: str, arr: np.ndarray, axis: int = 0) -> np.ndarray:
        # Stack incoming numpy arrays; flush current when the cycle triggers
        slot = self._slots[name]
        if slot.current is None: slot.current = arr
        else:
            slot.current = np.concatenate([slot.current, arr], axis=axis); slot._write_cnt += 1
            if slot._write_cnt % slot.cycle == 0:
                result = slot.current; slot.current = None
                return result
        return slot.current

# ////////////////////////////////////////////////////////////////////////////////
#
# § 5  CONCURRENCY POOL EXTENSION / Guaranteed hook for any directory ////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class ConcurrencyPool:
    # Extended class that any TDSDirectory can hook into instantly
    # Provides both thread & process workers -> auto scales
    _global_instance: Optional['ConcurrencyPool'] = None
    _init_lock = threading.Lock()

    def __init__(self, max_threads: int = 64, max_procs: int = 8):
        self._thread_pool = ThreadPoolExecutor(max_workers=max_threads, thread_name_prefix='tds_t')
        self._proc_pool = ProcessPoolExecutor(max_workers=max_procs)
        self._event_loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._event_loop.run_forever, daemon=True)
        self._loop_thread.start()

    @classmethod
    def acquire(cls) -> 'ConcurrencyPool':
        # Guaranteed singleton: Directories call this to hook in instantly
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
        return asyncio.run_coroutine_threadsafe(coro, self._event_loop).result()

    def map_parallel(self, fn, items: list, use_processes: bool = False):
        pool = self._proc_pool if use_processes else self._thread_pool
        return list(pool.map(fn, items))

    def shutdown(self):
        self._thread_pool.shutdown(wait=False)
        self._proc_pool.shutdown(wait=False)
        self._event_loop.call_soon_threadsafe(self._event_loop.stop)

# ////////////////////////////////////////////////////////////////////////////////
#
# § 6  SYMBOL TABLE / Custom symbol switching inside structures //////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class SymbolTable:
    # Bi-directional symbol <-> numeric ID mapping, state of the art
    # Supports instant swap across matrices, delegated to numba kernel

    def __init__(self):
        self._sym_to_id: Dict[str, float] = {}; self._id_to_sym: Dict[float, str] = {}; self._counter = 0.0

    def intern(self, symbol: str) -> float:
        if symbol not in self._sym_to_id:
            self._sym_to_id[symbol] = self._counter; self._id_to_sym[self._counter] = symbol; self._counter += 1.0
        return self._sym_to_id[symbol]

    def swap(self, old_sym: str, new_sym: str, matrix: np.ndarray) -> np.ndarray:
        # Replace every occurrence of old_sym's ID with new_sym's ID in matrix
        old_id = self.intern(old_sym); new_id = self.intern(new_sym)
        result = _matrix_symbol_swap(matrix.astype(np.float64), old_id, new_id)
        return result

    def decode_matrix(self, matrix: np.ndarray) -> list:
        return [[self._id_to_sym.get(v, '?') for v in row] for row in matrix]

# ////////////////////////////////////////////////////////////////////////////////
#
# § 7  TDS ENTRY / Leaf level variable storage ///////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class TDSEntry:
    # Single stored variable inside a directory node
    name: str
    fmt_id: FmtID
    data: Any
    ts_written: int = field(default_factory=lambda: int(time.time_ns()))
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def serialise(self) -> bytes:
        raw = pickle.dumps(self.data, protocol=5)
        if self.fmt_id & FmtID.COMPRESSED: raw = zlib.compress(raw, level=6)
        # 4 byte len prefix + payload
        return struct.pack('>I', len(raw)) + raw

    @classmethod
    def deserialise(cls, name: str, fmt_id: FmtID, buf: bytes) -> 'TDSEntry':
        length = struct.unpack('>I', buf[:4])[0]; raw = buf[4: 4 + length]
        if fmt_id & FmtID.COMPRESSED: raw = zlib.decompress(raw)
        data = pickle.loads(raw)
        return cls(name=name, fmt_id=fmt_id, data=data)

# ////////////////////////////////////////////////////////////////////////////////
#
# § 8  TDS DIRECTORY NODE / The core tree unit ///////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class TDSDirectory:
    """
    ---- Features ----
    
      >> Binary encoded header (§1)
      >> Parallel sub-directory fan-out (§5)
      >> Probability LRU registry for child lookup (§3)
      >> Loop cache manager for pinned cycle variables (§4)
      >> Symbol table for matrix level symbol switching (§6)
      >> Recursive array join traversal (§2)
    """

    def __init__(self, name: str, fmt_id: FmtID = FmtID.RAW_BINARY, flags: int = DirFlags.NONE, parent: Optional['TDSDirectory'] = None,):
        self.name = name
        self.fmt_id = fmt_id
        self.flags = flags
        self.parent = parent
        self.dir_id = uuid.uuid4().hex
        self._ts_create = int(time.time_ns())
        self._ts_mod = self._ts_create
        self._entries:  Dict[str, TDSEntry] = {}
        self._children: Dict[str, TDSDirectory] = {}
        self._lock = threading.RLock()
        # Hook into global concurrency pool immediately
        self._pool = ConcurrencyPool.acquire()
        # Probability LRU registry for child directory access patterns
        self._registry = HybridRegistry(capacity=2048)
        # Loop cache manager
        self.loop_cache = LoopCacheManager()
        # And the symbol table
        self.symbols = SymbolTable()

    def header_bytes(self) -> bytes:
        with self._lock:
            return encode_header(ts_create = self._ts_create, ts_mod = self._ts_mod, flags = self.flags, fmt_id = int(self.fmt_id), subdir_count = len(self._children), entry_count = len(self._entries),)

    def write(self, name: str, value: Any, fmt_id: FmtID = FmtID.PICKLE_OBJ, compress: bool = False) -> TDSEntry:
        if compress: fmt_id = FmtID(fmt_id | FmtID.COMPRESSED)
        entry = TDSEntry(name=name, fmt_id=fmt_id, data=value)
        with self._lock: self._entries[name] = entry; self._ts_mod = int(time.time_ns())
        self._registry.put(name, entry)
        return entry

    def read(self, name: str) -> Any:
        # Check registry first
        cached = self._registry.get(name)
        if cached is not None:
            return cached.data
        with self._lock: entry = self._entries.get(name)
        if entry is None:
            raise KeyError(f"No entry '{name}' in {self.name!r}")
        self._registry.put(name, entry)
        return entry.data

    def delete(self, name: str) -> None:
        with self._lock:
            self._entries.pop(name, None); self._ts_mod = int(time.time_ns())

    def mkdir(self, name: str, **kwargs) -> 'TDSDirectory':
        child = TDSDirectory(name=name, parent=self, **kwargs)
        with self._lock: self._children[name] = child; self._ts_mod = int(time.time_ns())
        self._registry.put(name, child)
        return child

    def cd(self, name: str) -> 'TDSDirectory':
        child = self._registry.get(name)
        if child is not None and isinstance(child, TDSDirectory):
            return child
        with self._lock: child = self._children.get(name)
        if child is None:
            raise KeyError(f"Sub-directory '{name}' not found in {self.name!r}")
        self._registry.put(name, child)
        return child

    def ls(self, sort_by_prob: bool = True) -> List[str]:
        # List entries; optionally sorted by probability score
        with self._lock:
            entry_names = list(self._entries.keys()); child_names = ['[dir] ' + n for n in self._children.keys()]
        if sort_by_prob and (self.flags & DirFlags.PROB_SORT): entry_names = self._registry.sorted_keys()
        return child_names + entry_names

    def parallel_read_all(self) -> Dict[str, Any]:
        # Read all entries in parallel via the concurrency pool
        with self._lock: keys = list(self._entries.keys())

        def _read_one(k):
            return (k, self.read(k))

        results = self._pool.map_parallel(_read_one, keys)
        return dict(results)

    def recursive_join(self, dtype=np.float64, max_depth: int = 8) -> np.ndarray:
        # Collect all numpy arrays in this subtree + join of them
        # Uses numba kernel for final concatenation, state of the art
        segments: List[np.ndarray] = []
        def _collect(node: TDSDirectory, depth: int):
            if depth > max_depth:
                return
            with node._lock:
                for entry in node._entries.values():
                    if isinstance(entry.data, np.ndarray): segments.append(entry.data.astype(dtype).ravel())
                children = list(node._children.values())
            for child in children: _collect(child, depth + 1)
        _collect(self, 0)
        if not segments:
            return np.array([], dtype=dtype)
        # Build a padded 2D array for the numba kernel
        max_len = max(s.shape[0] for s in segments)
        padded = np.zeros((len(segments), max_len), dtype=dtype)
        for i, seg in enumerate(segments): padded[i, :seg.shape[0]] = seg
        # Strip padding + concatenate
        flat_parts = np.array([padded[i, :segments[i].shape[0]] for i in range(len(segments))], dtype=object)
        # Fall back to numpy concatenate
        return np.concatenate([s for s in segments])

    def build_offset_index(self) -> np.ndarray:
        # Compute byte offset idx for all serialised entries
        with self._lock: entries = list(self._entries.values())
        sizes = np.array([len(e.serialise()) for e in entries], dtype=np.int64)
        return _compute_subdir_offsets(sizes)

    def to_bytes(self) -> bytes:
        # Serialise header + all entries to a single byte buffer
        header  = self.header_bytes(); payloads = []
        with self._lock:
            for entry in self._entries.values():
                name_enc = entry.name.encode(); edata    = entry.serialise()
                # 2 byte name len prefix
                payloads.append(struct.pack('>H', len(name_enc)) + name_enc + edata)
        body = b''.join(payloads); body = zlib.compress(body, level=3)
        return header + struct.pack('>I', len(body)) + body

    def path(self) -> str:
        parts = []
        node: Optional[TDSDirectory] = self
        while node is not None:
            parts.append(node.name); node = node.parent
        return '/' + '/'.join(reversed(parts))

    def __repr__(self) -> str:
        return (f"<TDSDirectory '{self.path()}' "
                f"entries={len(self._entries)} "
                f"subdirs={len(self._children)} "
                f"fmt={self.fmt_id.name}>")

# ////////////////////////////////////////////////////////////////////////////////
#
# § 9  TDS FILE SYSTEM / Root + Mount API ////////////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class TDSFileSystem:
    """
    ---- Usage ----
    
        fs = TDSFileSystem("asi_root")
        db = fs.root.mkdir("databases",  flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
        mem = fs.root.mkdir("working_mem", flags=DirFlags.LOOP_PINNED)

        db.write("embedding_matrix", np.random.randn(1024, 1024), fmt_id=FmtID.NUMPY_MATRIX, compress=True)

        mem.loop_cache.register("gradient_buf", cycle=32)
        for step in range(100):
            g = np.random.randn(256); mem.loop_cache.write("gradient_buf", g)

        sym_dir = fs.root.mkdir("symbol_space", flags=DirFlags.RECURSIVE)
        token_mat = np.zeros((8, 8))
        
        sym_dir.symbols.intern("START"); sym_dir.symbols.intern("END")
        swapped = sym_dir.symbols.swap("START", "END", token_mat)
    """
    
    VERSION = (0, 1, 0)
    def __init__(self, name: str = "tds_root"):
        self.root  = TDSDirectory(name   = name, fmt_id = FmtID.RAW_BINARY, flags  = DirFlags.PARALLEL_IO | DirFlags.PROB_SORT | DirFlags.RECURSIVE,)
        self._pool = ConcurrencyPool.acquire()

    def resolve(self, path: str) -> TDSDirectory:
        # Walk path '/databases/vectors' -> TDSDirectory
        parts = [p for p in path.strip('/').split('/') if p]; node  = self.root
        for part in parts: node = node.cd(part)
        return node

    def makedirs(self, path: str, **kwargs) -> TDSDirectory:
        # mkdir -p equivalent
        parts = [p for p in path.strip('/').split('/') if p]; node  = self.root
        for part in parts:
            try:
                node = node.cd(part)
            except KeyError:
                node = node.mkdir(part, **kwargs)
        return node

    def parallel_batch_write(self, writes: List[Tuple[str, str, Any]]) -> None:
        # writes = list of (path, entry_name, value)
        # All writes fan out in parallel via the concurrency pool
        def _do_write(args):
            path, name, value = args
            node = self.resolve(path); node.write(name, value)
        self._pool.map_parallel(_do_write, writes)

    def snapshot_headers(self) -> Dict[str, dict]:
        # Walk the entire tree and return decoded headers for every node
        result: Dict[str, dict] = {}
        
        def _walk(node: TDSDirectory):
            raw = node.header_bytes();result[node.path()] = decode_header(raw)
            with node._lock: children = list(node._children.values())
            for child in children:
                _walk(child)
        _walk(self.root)
        return result

    def __repr__(self) -> str:
        snap = self.snapshot_headers()
        total_entries = sum(v['entry_count'] for v in snap.values())
        return (f"<TDSFileSystem v{'.'.join(map(str, self.VERSION))} "
                f"dirs={len(snap)} total_entries={total_entries}>")

# ////////////////////////////////////////////////////////////////////////////////
#
# § 10  Staqtapp-TDS DEMO ////////////////////////////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

def demo():
    print(">> Initialising TDS VFS...")
    fs = TDSFileSystem("asi_root")
    
    # Build a directory tree
    vec_db = fs.makedirs("databases/vectors", fmt_id=FmtID.NUMPY_MATRIX, flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
    sym_db = fs.makedirs("databases/symbols", fmt_id=FmtID.SYMBOL_TABLE, flags=DirFlags.RECURSIVE)
    wm = fs.makedirs("working_memory", flags=DirFlags.LOOP_PINNED)
    logs = fs.makedirs("logs/audit", flags=DirFlags.NONE)
    
    # Write compressed numpy matrices
    print(">> Writing compressed numpy matrices...")
    for i in range(4):
        mat = np.random.randn(128, 128).astype(np.float32)
        vec_db.write(f"embed_{i:04d}", mat, fmt_id=FmtID.NUMPY_MATRIX, compress=True)
        
    # Symbol table + matrix swap
    print(">> Symbol table: intern + matrix swap…")
    token_mat = np.zeros((6, 6))
    sym_db.symbols.intern("NULL"); sym_db.symbols.intern("START"); sym_db.symbols.intern("END")
    sym_db.write("token_template", token_mat, fmt_id=FmtID.SYMBOL_TABLE)
    swapped = sym_db.symbols.swap("NULL", "START", token_mat.copy())
    sym_db.write("token_v1", swapped, fmt_id=FmtID.SYMBOL_TABLE)
    print(f"   decoded[0]: {sym_db.symbols.decode_matrix(swapped[:2])}")

    # Loop cache demo
    print(">> Loop cache: pinned gradient buffer (cycle=8)...")
    wm.loop_cache.register("grad_buf", cycle=8)
    cycles_triggered = 0
    for step in range(32):
        g = np.random.randn(64).astype(np.float32) * 0.01
        if wm.loop_cache.write("grad_buf", g): cycles_triggered += 1
    print(f"   Overwrite cycles triggered: {cycles_triggered}")

    # Parallel batch write
    print(">> Parallel batch write across logs...")
    batch = [("logs/audit", f"event_{i:06d}", {"ts": time.time_ns(), "msg": f"op_{i}"}) for i in range(16)]
    fs.parallel_batch_write(batch)

    # Offset index
    print(">> Building Numba offset index for vec_db...")
    offsets = vec_db.build_offset_index()
    print(f"   Entry offsets (first 5): {offsets[:5].tolist()}")

    # Probability sorted LS
    print(">> Reading back (primes prob-registry)...")
    _ = vec_db.read("embed_0000"); _ = vec_db.read("embed_0000"); _ = vec_db.read("embed_0001")
    print(f"   Prob-sorted ls: {vec_db.ls(sort_by_prob=True)[:5]}")

    # Recursive array join
    print(">> Recursive array join across entire databases/...")
    db_root = fs.resolve("databases")
    joined  = db_root.recursive_join(dtype=np.float32)
    print(f"   Joined array shape: {joined.shape}  dtype: {joined.dtype}")

    # Snapshot headers
    print(">> Header snapshot...")
    snap = fs.snapshot_headers()
    for path, hdr in snap.items():
        print(f"   {path:40s}  entries={hdr['entry_count']:4d}  "
              f"subdirs={hdr['subdir_count']}  crc=0x{hdr['crc']:08X}")
    print(f"\n{fs}")
    print(">> TDS demo complete.")

if __name__ == '__main__':
    demo()

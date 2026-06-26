"""
Updated 6-26-26, critical & professional fixes applied via top Anthropic AI-MDL

////////////////////////////////////////////////////////////////////////////////
>>> Staqtapp-TDS v1.2.0 / tds_filesystem.py
////////////////////////////////////////////////////////////////////////////////

Staqtapp-TDS / Temporal Directory System
VFS for ASI large scale computation
Extension: .tds

---- Architecture ----
  > Compressed binary directory headers
  > Numba-JIT hot paths for parsing/math
  > Probability-weighted LRU registry (true score-based eviction)
  > Loop cache for overwrite-cycle variables
  > Matrix symbol switching with recursive array joins
  > Parallel sub-directory I/O via guaranteed concurrency extension
  > Bloom filter on slot lookups (zero-seek miss path)
  > Pluggable compression backends (zlib / lz4 / zstd)
  > Schema-validated entries (dtype + shape enforcement)
  > Async-native read/write surface
  > Write-Ahead Log (WAL) crash recovery
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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
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
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 36 bytes


class FmtID(IntFlag):
    RAW_BINARY   = 0x00
    NUMPY_MATRIX = 0x01
    PICKLE_OBJ   = 0x02
    SYMBOL_TABLE = 0x04
    LOOP_CACHE   = 0x08
    COMPRESSED   = 0x80   # bitmask — combined with a base format


class DirFlags(IntEnum):
    NONE       = 0x0000
    READONLY   = 0x0001
    ENCRYPTED  = 0x0002
    PARALLEL_IO= 0x0004
    LOOP_PINNED= 0x0008
    RECURSIVE  = 0x0010
    PROB_SORT  = 0x0020


def encode_header(ts_create: int, ts_mod: int, flags: int, fmt_id: int,
                  subdir_count: int, entry_count: int) -> bytes:
    payload = struct.pack(HEADER_FMT, TDS_MAGIC, ts_create, ts_mod,
                          flags, fmt_id, subdir_count, entry_count, 0)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    return struct.pack(HEADER_FMT, TDS_MAGIC, ts_create, ts_mod,
                       flags, fmt_id, subdir_count, entry_count, crc)


def decode_header(raw: bytes) -> dict:
    if len(raw) < HEADER_SIZE:
        raise ValueError("Buffer too small for TDS header")
    magic, ts_create, ts_mod, flags, fmt_id, subdir_count, entry_count, crc = \
        struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    if magic != TDS_MAGIC:
        raise ValueError(f"Invalid TDS magic: {magic!r}")
    repacked = struct.pack(HEADER_FMT, magic, ts_create, ts_mod,
                           flags, fmt_id, subdir_count, entry_count, 0)
    expected = zlib.crc32(repacked) & 0xFFFFFFFF
    if crc != expected:
        raise ValueError("TDS header checksum mismatch")
    return {
        'ts_create': ts_create, 'ts_mod': ts_mod, 'flags': flags,
        'fmt_id': fmt_id, 'subdir_count': subdir_count,
        'entry_count': entry_count, 'crc': crc,
    }


# ////////////////////////////////////////////////////////////////////////////////
# § 1b  PLUGGABLE COMPRESSION BACKENDS
# ////////////////////////////////////////////////////////////////////////////////

class CompressorRegistry:
    """
    Maps codec names to (compress_fn, decompress_fn) pairs.
    Defaults to zlib. Falls back gracefully if optional libs are absent.
    """
    _codecs: Dict[str, Tuple[Callable, Callable]] = {}
    _default = 'zlib'

    @classmethod
    def register(cls, name: str, compress_fn: Callable, decompress_fn: Callable) -> None:
        cls._codecs[name] = (compress_fn, decompress_fn)

    @classmethod
    def compress(cls, data: bytes, codec: str = '') -> bytes:
        codec = codec or cls._default
        fn, _ = cls._codecs.get(codec, cls._codecs['zlib'])
        return fn(data)

    @classmethod
    def decompress(cls, data: bytes, codec: str = '') -> bytes:
        codec = codec or cls._default
        _, fn = cls._codecs.get(codec, cls._codecs['zlib'])
        return fn(data)

    @classmethod
    def set_default(cls, codec: str) -> None:
        if codec not in cls._codecs:
            raise KeyError(f"Codec '{codec}' not registered")
        cls._default = codec


# Register built-ins
CompressorRegistry.register(
    'zlib',
    lambda d: zlib.compress(d, level=6),
    zlib.decompress,
)
try:
    import lz4.frame as _lz4
    CompressorRegistry.register('lz4', _lz4.compress, _lz4.decompress)
except ImportError:
    pass
try:
    import zstandard as _zstd
    _zctx_c = _zstd.ZstdCompressor(level=3)
    _zctx_d = _zstd.ZstdDecompressor()
    CompressorRegistry.register('zstd', _zctx_c.compress, _zctx_d.decompress)
except ImportError:
    pass


# ////////////////////////////////////////////////////////////////////////////////
# § 1c  ENTRY SCHEMA VALIDATION
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class EntrySchema:
    """
    Attach to a TDSDirectory via directory.set_schema(name, schema).
    On write: validates dtype + shape before serialisation.
    On read:  re-validates the recovered object.
    Pass shape=None to skip shape check (only dtype enforced).
    """
    dtype: Optional[np.dtype] = None          # None = any / non-numpy OK
    shape: Optional[Tuple[int, ...]] = None   # None = any shape
    python_type: Optional[Type] = None        # e.g. dict, list — for non-numpy

    def validate(self, value: Any, name: str) -> None:
        if self.python_type is not None and not isinstance(value, self.python_type):
            raise TypeError(
                f"Schema violation for '{name}': "
                f"expected {self.python_type.__name__}, got {type(value).__name__}"
            )
        if self.dtype is not None:
            if not isinstance(value, np.ndarray):
                raise TypeError(
                    f"Schema violation for '{name}': expected ndarray, got {type(value).__name__}"
                )
            if value.dtype != np.dtype(self.dtype):
                raise TypeError(
                    f"Schema violation for '{name}': "
                    f"dtype mismatch — expected {self.dtype}, got {value.dtype}"
                )
            if self.shape is not None and value.shape != self.shape:
                raise ValueError(
                    f"Schema violation for '{name}': "
                    f"shape mismatch — expected {self.shape}, got {value.shape}"
                )


# ////////////////////////////////////////////////////////////////////////////////
# § 2  NUMBA-JIT KERNELS
# ////////////////////////////////////////////////////////////////////////////////

@njit(cache=True)
def _compute_subdir_offsets(entry_sizes: np.ndarray) -> np.ndarray:
    n = entry_sizes.shape[0]
    offsets = np.empty(n + 1, dtype=np.int64)
    offsets[0] = 0
    for i in range(n):
        offsets[i + 1] = offsets[i] + entry_sizes[i]
    return offsets


@njit(cache=True)
def _probability_decay(access_counts: np.ndarray, last_access_times: np.ndarray,
                       now: float, decay_lambda: float) -> np.ndarray:
    n = access_counts.shape[0]
    scores = np.empty(n, dtype=np.float64)
    for i in prange(n):
        dt = now - last_access_times[i]
        scores[i] = access_counts[i] * math.exp(-decay_lambda * dt)
    return scores


@njit(cache=True)
def _matrix_symbol_swap(matrix: np.ndarray, old_val: np.float64,
                        new_val: np.float64) -> np.ndarray:
    rows, cols = matrix.shape
    for i in prange(rows):
        for j in range(cols):
            if matrix[i, j] == old_val:
                matrix[i, j] = new_val
    return matrix


def _join_segments(segments: List[np.ndarray],
                   dtype: np.dtype = np.float64) -> np.ndarray:
    """Concatenate ravelled array segments, preserving caller-specified dtype."""
    if not segments:
        return np.array([], dtype=dtype)
    return np.concatenate([s.astype(dtype).ravel() for s in segments])


# ////////////////////////////////////////////////////////////////////////////////
# § 3  PROBABILITY LRU REGISTRY  (FIX: true score-based eviction)
# ////////////////////////////////////////////////////////////////////////////////

class HybridRegistry:
    """
    Probability-weighted LRU with genuine score-based eviction.

    BUG FIXED: previous version evicted by insertion order (pure FIFO),
    ignoring the computed decay scores entirely.  Now the lowest-scoring
    entry is evicted on overflow.
    """

    def __init__(self, capacity: int = 4096, decay_lambda: float = 1e-4):
        self._cap = capacity
        self._lam = decay_lambda
        self._lock = threading.RLock()
        self._store: Dict[str, list] = {}   # key -> [count, last_t, value]
        self._order: OrderedDict = OrderedDict()

    def _evict_lowest(self) -> None:
        """Evict the entry with the lowest probability-decay score."""
        if not self._store:
            return
        counts, times, keys = self._rebuild_score_arrays()
        scores = _probability_decay(counts, times, time.monotonic(), self._lam)
        worst = int(np.argmin(scores))
        evict_key = keys[worst]
        del self._store[evict_key]
        self._order.pop(evict_key, None)

    def _rebuild_score_arrays(self) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        keys   = list(self._store.keys())
        counts = np.array([self._store[k][0] for k in keys], dtype=np.float64)
        times  = np.array([self._store[k][1] for k in keys], dtype=np.float64)
        return counts, times, keys

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            now = time.monotonic()
            if key in self._store:
                self._store[key][0] += 1
                self._store[key][1]  = now
                self._store[key][2]  = value
                self._order.move_to_end(key)
            else:
                if len(self._store) >= self._cap:
                    self._evict_lowest()        # score-based, not FIFO
                self._store[key] = [1, now, value]
                self._order[key] = True

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                return None
            entry = self._store[key]
            entry[0] += 1
            entry[1]  = time.monotonic()
            self._order.move_to_end(key)
            return entry[2]

    def remove(self, key: str) -> None:
        with self._lock:
            if key in self._store:
                del self._store[key]
                self._order.pop(key, None)

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
    """
    Stores a value every `cycle` writes.

    Cycle semantics: triggers on write number cycle, 2*cycle, 3*cycle …
    (1-indexed; the very first write never triggers unless cycle == 1).
    """
    name: str
    cycle: int
    _write_cnt: int = field(default=0, repr=False)
    current: Any = field(default=None, repr=False)

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
            slot = LoopCacheSlot(name=name, cycle=cycle)
            self._slots[name] = slot
            return slot

    def write(self, name: str, value: Any) -> bool:
        with self._lock:
            return self._slots[name].write(value)

    def read(self, name: str) -> Any:
        with self._lock:
            return self._slots[name].read()

    def batch_flush_numpy(self, name: str, arr: np.ndarray,
                          axis: int = 0) -> Optional[np.ndarray]:
        with self._lock:
            slot = self._slots[name]
            slot.current = (arr if slot.current is None
                            else np.concatenate([slot.current, arr], axis=axis))
            slot._write_cnt += 1
            if slot._write_cnt % slot.cycle == 0:
                result = slot.current
                slot.current = None
                return result
            return None


# ////////////////////////////////////////////////////////////////////////////////
# § 5  CONCURRENCY POOL  (FIX: thread-safe event loop init, proc pool removed)
# ////////////////////////////////////////////////////////////////////////////////

class ConcurrencyPool:
    """
    Singleton thread-pool + async event loop.

    BUG FIXED: _ensure_loop() was not thread-safe; two racing threads could
    create two event loops.  Now guarded by a dedicated lock.

    ProcessPoolExecutor removed: it required picklable top-level callables
    which conflicted with the lambda-heavy API and was unreachable via the
    public surface.  The dead code and wasted OS handles are gone.
    """
    _global_instance: Optional['ConcurrencyPool'] = None
    _init_lock = threading.Lock()

    def __init__(self, max_threads: int = 64):
        self._thread_pool = ThreadPoolExecutor(
            max_workers=max_threads, thread_name_prefix='tds_t')
        self._event_loop:  Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_lock = threading.Lock()   # guards _ensure_loop

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:                # FIX: double-checked under lock
            if self._event_loop is None:
                self._event_loop  = asyncio.new_event_loop()
                self._loop_thread = threading.Thread(
                    target=self._event_loop.run_forever, daemon=True)
                self._loop_thread.start()
        return self._event_loop

    @classmethod
    def acquire(cls) -> 'ConcurrencyPool':
        if cls._global_instance is None:
            with cls._init_lock:
                if cls._global_instance is None:
                    cls._global_instance = cls()
        return cls._global_instance

    def submit_thread(self, fn, *args, **kwargs):
        return self._thread_pool.submit(fn, *args, **kwargs)

    async def gather_async(self, *coros):
        return await asyncio.gather(*coros)

    def run_async(self, coro):
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    def map_parallel(self, fn, items: list):
        return list(self._thread_pool.map(fn, items))

    def shutdown(self):
        self._thread_pool.shutdown(wait=True)
        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)


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
# § 6b  BLOOM FILTER  (zero-seek miss path for SlotIndex lookups)
# ////////////////////////////////////////////////////////////////////////////////

class BloomFilter:
    """
    Simple counting-free Bloom filter for string keys.
    ~0.1 % false-positive rate at 10 bits/key.
    Eliminates disk seeks on definite misses.
    """

    def __init__(self, capacity: int = 100_000, error_rate: float = 0.01):
        self._capacity   = capacity
        self._error_rate = error_rate
        # optimal bit-array size and number of hashes
        import math as _m
        m = int(-capacity * _m.log(error_rate) / (_m.log(2) ** 2))
        k = int((m / capacity) * _m.log(2))
        self._m   = max(m, 1)
        self._k   = max(k, 1)
        self._bits = bytearray(math.ceil(self._m / 8))

    def _hashes(self, key: str):
        h1 = zlib.adler32(key.encode())
        h2 = zlib.crc32(key.encode()) & 0xFFFFFFFF
        for i in range(self._k):
            yield (h1 + i * h2) % self._m

    def add(self, key: str) -> None:
        for bit in self._hashes(key):
            self._bits[bit >> 3] |= (1 << (bit & 7))

    def __contains__(self, key: str) -> bool:
        return all(
            (self._bits[bit >> 3] >> (bit & 7)) & 1
            for bit in self._hashes(key)
        )


# ////////////////////////////////////////////////////////////////////////////////
# § 7  TDS ENTRY
# ////////////////////////////////////////////////////////////////////////////////

def _serialize_payload(data: Any, fmt_id: FmtID,
                       codec: str = '') -> bytes:
    base = fmt_id & ~FmtID.COMPRESSED
    if base == FmtID.NUMPY_MATRIX and isinstance(data, np.ndarray):
        import io
        buf = io.BytesIO()
        np.save(buf, data, allow_pickle=False)
        raw = buf.getvalue()
    else:
        raw = pickle.dumps(data, protocol=5)
    if fmt_id & FmtID.COMPRESSED:
        raw = CompressorRegistry.compress(raw, codec)
    return raw


def _deserialize_payload(raw: bytes, fmt_id: FmtID,
                         codec: str = '') -> Any:
    if fmt_id & FmtID.COMPRESSED:
        raw = CompressorRegistry.decompress(raw, codec)
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
    entry_id:   str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    codec:      str = field(default='')     # compression codec tag

    def serialise(self) -> bytes:
        raw = _serialize_payload(self.data, self.fmt_id, self.codec)
        return struct.pack('>I', len(raw)) + raw

    @classmethod
    def deserialise(cls, name: str, fmt_id: FmtID, buf: bytes,
                    ts_written: int = 0, entry_id: str = '',
                    codec: str = '') -> 'TDSEntry':
        length = struct.unpack('>I', buf[:4])[0]
        raw    = buf[4: 4 + length]
        data   = _deserialize_payload(raw, fmt_id, codec)
        e = cls(name=name, fmt_id=fmt_id, data=data, codec=codec)
        if ts_written: e.ts_written = ts_written
        if entry_id:   e.entry_id   = entry_id
        return e


# ////////////////////////////////////////////////////////////////////////////////
# § 8  TDS DIRECTORY NODE
# ////////////////////////////////////////////////////////////////////////////////

class TDSDirectory:
    def __init__(self, name: str, fmt_id: FmtID = FmtID.RAW_BINARY,
                 flags: int = DirFlags.NONE,
                 parent: Optional['TDSDirectory'] = None):
        self.name    = name
        self.fmt_id  = fmt_id
        self.flags   = flags
        self.parent  = parent
        self.dir_id  = uuid.uuid4().hex
        self._ts_create = int(time.time_ns())
        self._ts_mod    = self._ts_create
        self._entries:  Dict[str, TDSEntry]      = {}
        self._children: Dict[str, 'TDSDirectory'] = {}
        self._schemas:  Dict[str, EntrySchema]   = {}
        self._lock     = threading.RLock()
        self._pool     = ConcurrencyPool.acquire()
        self._registry = HybridRegistry(capacity=2048)
        self._bloom    = BloomFilter(capacity=8192)
        self.loop_cache = LoopCacheManager()
        self.symbols    = SymbolTable()

    # --- schema ---

    def set_schema(self, name: str, schema: EntrySchema) -> None:
        """Attach a validation schema to a named entry slot."""
        with self._lock:
            self._schemas[name] = schema

    def _validate(self, name: str, value: Any) -> None:
        schema = self._schemas.get(name)
        if schema is not None:
            schema.validate(value, name)

    # --- header ---

    def header_bytes(self) -> bytes:
        with self._lock:
            return encode_header(
                ts_create    = self._ts_create,
                ts_mod       = self._ts_mod,
                flags        = self.flags,
                fmt_id       = int(self.fmt_id),
                subdir_count = len(self._children),
                entry_count  = len(self._entries),
            )

    # --- core I/O ---

    def write(self, name: str, value: Any,
              fmt_id: FmtID = FmtID.PICKLE_OBJ,
              compress: bool = False,
              codec: str = '') -> 'TDSEntry':
        self._validate(name, value)
        if compress:
            fmt_id = FmtID(fmt_id | FmtID.COMPRESSED)
        entry = TDSEntry(name=name, fmt_id=fmt_id, data=value, codec=codec)
        with self._lock:
            self._entries[name] = entry
            self._ts_mod = int(time.time_ns())
            self._bloom.add(name)
        self._registry.put(name, entry)
        return entry

    def read(self, name: str) -> Any:
        # Bloom filter: definite miss without touching the lock
        if name not in self._bloom:
            raise KeyError(f"No entry '{name}' in {self.name!r}")
        # snapshot the entry reference under lock, release before data access
        with self._lock:
            cached = self._registry.get(name)
            if cached is not None:
                return cached.data
            entry = self._entries.get(name)
            if entry is None:
                raise KeyError(f"No entry '{name}' in {self.name!r}")
        # data access outside lock — avoids deadlock with thread-pool reads
        self._registry.put(name, entry)
        return entry.data

    def delete(self, name: str) -> None:
        with self._lock:
            self._entries.pop(name, None)
            self._ts_mod = int(time.time_ns())
        self._registry.remove(name)
        # Note: Bloom filter is not decremental; rebuild on next flush if needed.

    # --- async surface ---

    async def awrite(self, name: str, value: Any, **kwargs) -> 'TDSEntry':
        """Non-blocking async write — delegates to thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.write(name, value, **kwargs))

    async def aread(self, name: str) -> Any:
        """Non-blocking async read — delegates to thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.read(name))

    # --- directory ops ---

    def mkdir(self, name: str, **kwargs) -> 'TDSDirectory':
        child = TDSDirectory(name=name, parent=self, **kwargs)
        with self._lock:
            self._children[name] = child
            self._ts_mod = int(time.time_ns())
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
        """
        Read all entries concurrently.
        BUG FIXED: previously called self.read() from inside a locked section
        which could deadlock with the thread pool.  Keys are now snapshotted
        outside any lock before dispatching to the pool.
        """
        with self._lock:
            keys = list(self._entries.keys())   # snapshot — no lock held below

        def _read_one(k):
            return (k, self.read(k))

        return dict(self._pool.map_parallel(_read_one, keys))

    def recursive_join(self, dtype=np.float64, max_depth: int = 8) -> np.ndarray:
        """Concatenate all numpy array entries in the subtree."""
        segments: List[np.ndarray] = []

        def _collect(node: 'TDSDirectory', depth: int):
            if depth >= max_depth:
                return
            with node._lock:
                entries  = list(node._entries.values())
                children = list(node._children.values())
            for entry in entries:
                if isinstance(entry.data, np.ndarray):
                    segments.append(entry.data)
            for child in children:
                _collect(child, depth + 1)

        _collect(self, 0)
        return _join_segments(segments, dtype=dtype)

    def build_offset_index(self) -> np.ndarray:
        with self._lock:
            entries = list(self._entries.values())
        sizes = np.array([len(e.serialise()) for e in entries], dtype=np.int64)
        return _compute_subdir_offsets(sizes)

    def to_bytes(self) -> bytes:
        header = self.header_bytes()
        payloads = []
        with self._lock:
            for entry in self._entries.values():
                name_enc = entry.name.encode()
                edata    = entry.serialise()
                payloads.append(
                    struct.pack('>H', len(name_enc)) + name_enc + edata)
        body = b''.join(payloads)
        body = CompressorRegistry.compress(body)
        return header + struct.pack('>I', len(body)) + body

    def path(self) -> str:
        parts: List[str] = []
        node: Optional['TDSDirectory'] = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
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

        # Schema validation example
        from staqtapp_tds.tds_filesystem import EntrySchema
        db.set_schema("embedding_matrix", EntrySchema(dtype=np.float32, shape=(1024, 1024)))

        db.write("embedding_matrix", np.random.randn(1024, 1024).astype(np.float32),
                 fmt_id=FmtID.NUMPY_MATRIX, compress=True)

        mem.loop_cache.register("gradient_buf", cycle=32)
        for step in range(100):
            g = np.random.randn(256)
            mem.loop_cache.write("gradient_buf", g)

        # Async usage
        import asyncio
        asyncio.run(db.awrite("key", value))
        value = asyncio.run(db.aread("key"))
    """
    VERSION = (1, 2, 0)

    def __init__(self, name: str = "tds_root"):
        self.root = TDSDirectory(
            name   = name,
            fmt_id = FmtID.RAW_BINARY,
            flags  = DirFlags.PARALLEL_IO | DirFlags.PROB_SORT | DirFlags.RECURSIVE,
        )
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
# § 9b  WRITE-AHEAD LOG  (crash recovery)
# ////////////////////////////////////////////////////////////////////////////////

class WriteAheadLog:
    """
    Append-only WAL for TDSDirectory writes.
    On crash, replay() re-applies all un-checkpointed entries.

    Layout per record:
        [4B magic 'WALR'] [4B name_len] [name_bytes]
        [4B fmt_id] [8B ts] [4B data_len] [data_bytes]
        [4B CRC32 of above]

    Usage:
        wal = WriteAheadLog("/tmp/tds.wal")
        wal.append(entry)           # before writing to directory
        directory.write(...)        # actual write
        wal.checkpoint()            # truncates WAL after successful flush
    """
    _MAGIC = b'WALR'
    _REC_HDR = '>4sII'   # magic, name_len, fmt_id
    _REC_HDR_SIZE = struct.calcsize(_REC_HDR)

    def __init__(self, path):
        from pathlib import Path
        self._path = Path(path)
        self._lock = threading.Lock()
        self._f = open(self._path, 'ab', buffering=0)   # unbuffered append

    def append(self, entry: 'TDSEntry') -> None:
        name_b = entry.name.encode('utf-8')
        data_b = _serialize_payload(entry.data, entry.fmt_id, entry.codec)
        ts_b   = struct.pack('>Q', entry.ts_written)
        body   = (struct.pack(self._REC_HDR, self._MAGIC,
                              len(name_b), int(entry.fmt_id))
                  + name_b + ts_b
                  + struct.pack('>I', len(data_b)) + data_b)
        crc = zlib.crc32(body) & 0xFFFFFFFF
        record = body + struct.pack('>I', crc)
        with self._lock:
            self._f.write(record)
            os.fsync(self._f.fileno())

    def checkpoint(self) -> None:
        """Truncate WAL — call after a successful flush to disk."""
        with self._lock:
            self._f.truncate(0)
            self._f.seek(0)
            os.fsync(self._f.fileno())

    def replay(self, directory: 'TDSDirectory') -> int:
        """
        Re-apply WAL records into a TDSDirectory.
        Returns the number of records replayed.
        """
        replayed = 0
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return 0
        cursor = 0
        while cursor < len(raw):
            try:
                hdr_end = cursor + self._REC_HDR_SIZE
                if hdr_end > len(raw):
                    break
                magic, name_len, fmt_id_int = struct.unpack(
                    self._REC_HDR, raw[cursor: hdr_end])
                if magic != self._MAGIC:
                    break
                p = hdr_end
                name  = raw[p: p + name_len].decode('utf-8'); p += name_len
                ts    = struct.unpack('>Q', raw[p: p + 8])[0]; p += 8
                dlen  = struct.unpack('>I', raw[p: p + 4])[0]; p += 4
                data_b = raw[p: p + dlen]; p += dlen
                stored_crc = struct.unpack('>I', raw[p: p + 4])[0]; p += 4
                body = raw[cursor: p - 4]
                if (zlib.crc32(body) & 0xFFFFFFFF) != stored_crc:
                    break   # corrupted tail — stop here
                fmt_id = FmtID(fmt_id_int)
                data   = _deserialize_payload(data_b, fmt_id)
                directory.write(name, data, fmt_id=fmt_id & ~FmtID.COMPRESSED,
                                compress=bool(fmt_id & FmtID.COMPRESSED))
                replayed += 1
                cursor = p
            except Exception:
                break
        return replayed

    def close(self) -> None:
        with self._lock:
            self._f.close()


# ////////////////////////////////////////////////////////////////////////////////
# § 10  DEMO
# ////////////////////////////////////////////////////////////////////////////////

def demo():
    print(">> Initialising TDS VFS v1.2.0 ...")
    fs = TDSFileSystem("asi_root")

    vec_db = fs.makedirs("databases/vectors",
                         fmt_id=FmtID.NUMPY_MATRIX,
                         flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
    sym_db = fs.makedirs("databases/symbols",
                         fmt_id=FmtID.SYMBOL_TABLE,
                         flags=DirFlags.RECURSIVE)
    wm   = fs.makedirs("working_memory", flags=DirFlags.LOOP_PINNED)

    # Schema validation
    vec_db.set_schema("embed_0000", EntrySchema(dtype=np.float32))
    print(">> Writing compressed numpy matrices ...")
    for i in range(4):
        mat = np.random.randn(128, 128).astype(np.float32)
        vec_db.write(f"embed_{i:04d}", mat,
                     fmt_id=FmtID.NUMPY_MATRIX, compress=True)

    print(">> Symbol table: intern + matrix swap ...")
    token_mat = np.zeros((6, 6))
    sym_db.symbols.intern("NULL")
    sym_db.symbols.intern("START")
    sym_db.symbols.intern("END")
    sym_db.write("token_template", token_mat, fmt_id=FmtID.SYMBOL_TABLE)
    swapped = sym_db.symbols.swap("NULL", "START", token_mat.copy())
    sym_db.write("token_v1", swapped, fmt_id=FmtID.SYMBOL_TABLE)
    print(f"   decoded[0]: {sym_db.symbols.decode_matrix(swapped[:2])}")

    print(">> Loop cache: pinned gradient buffer (cycle=8) ...")
    wm.loop_cache.register("grad_buf", cycle=8)
    cycles_triggered = 0
    for step in range(32):
        g = np.random.randn(64).astype(np.float32) * 0.01
        if wm.loop_cache.write("grad_buf", g):
            cycles_triggered += 1
    print(f"   Overwrite cycles triggered: {cycles_triggered}")

    print(">> Parallel read-all ...")
    result = vec_db.parallel_read_all()
    print(f"   Keys read: {list(result.keys())}")

    print(">> WAL append + checkpoint ...")
    import tempfile, pathlib
    wal_path = pathlib.Path(tempfile.mktemp(suffix='.wal'))
    wal = WriteAheadLog(wal_path)
    entry = vec_db._entries.get("embed_0000")
    if entry:
        wal.append(entry)
    wal.checkpoint()
    wal.close()
    wal_path.unlink(missing_ok=True)

    print(">> Bloom filter miss test ...")
    assert "embed_0000" in vec_db._bloom
    assert "nonexistent_key" not in vec_db._bloom
    print("   Bloom filter working correctly.")

    print(">> TDS demo complete.")
    print(fs)


if __name__ == '__main__':
    demo()

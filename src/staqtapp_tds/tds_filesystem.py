"""Core Temporal Directory System filesystem implementation.

This module contains the directory, entry, compression, chunking, Bloom, registry,
telemetry, and VFS orchestration code. Historical release comments are kept out
of the runtime source so package versioning remains centralized.
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

from staqtapp_tds.arena import SharedMemoryArena
from staqtapp_tds.index import EntryIndex
from staqtapp_tds.capabilities import CapabilityRegistry, ZoneCapability
from staqtapp_tds.latency import LatencyPolicy
from staqtapp_tds.telemetry import DirectoryTelemetry, TelemetryLevel, TelemetryMode, TelemetryManager
from staqtapp_tds.srz import SRZMetadata
from staqtapp_tds.manifest import ManifestPolicy
from staqtapp_tds.namespaces import ReservedNamespaces
from staqtapp_tds.result import TDSResult
from staqtapp_tds.errors import ErrorLogMode
from staqtapp_tds.variables import VariableControl
from staqtapp_tds.serializers import CompressionPolicy, PayloadKind, choose_variable_kind, content_hash_bytes, json_dumps_fast, json_loads_fast, kind_name
from staqtapp_tds.invariants import InvariantEngine
from staqtapp_tds.provenance import ProvenanceTag, ProvenanceClass
from staqtapp_tds.radix import RadixDirectoryRouter
from staqtapp_tds.config import RuntimeConfig, ConfigRegistry
from staqtapp_tds.crypto import CryptoProvider, NoopCryptoProvider

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

TDS_MAGIC   = b'\x54\x44\x53\x01'
HEADER_FMT  = '>4sQQHHIII'
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 36 bytes


class FmtID(IntFlag):
    RAW_BINARY   = 0x00
    NUMPY_MATRIX = 0x01
    PICKLE_OBJ   = 0x02
    TEXT_UTF8    = 0x03
    JSON_UTF8    = 0x05
    SYMBOL_TABLE = 0x04
    LOOP_CACHE   = 0x08
    COMPRESSED   = 0x80


class DirFlags(IntEnum):
    NONE        = 0x0000
    READONLY    = 0x0001
    ENCRYPTED   = 0x0002
    PARALLEL_IO = 0x0004
    LOOP_PINNED = 0x0008
    RECURSIVE   = 0x0010
    PROB_SORT   = 0x0020


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
    Codec registry with cached direct fn refs (eliminates dict lookup per call).
    """
    _codecs: Dict[str, Tuple[Callable, Callable]] = {}
    _default = 'zlib'
    # Direct references — updated by set_default / register
    _compress_fn: Callable = None   # type: ignore[assignment]
    _decompress_fn: Callable = None  # type: ignore[assignment]

    @classmethod
    def register(cls, name: str, compress_fn: Callable,
                 decompress_fn: Callable) -> None:
        cls._codecs[name] = (compress_fn, decompress_fn)
        if name == cls._default:
            cls._compress_fn   = compress_fn
            cls._decompress_fn = decompress_fn

    @classmethod
    def compress(cls, data: bytes, codec: str = '') -> bytes:
        if not codec or codec == cls._default:
            return cls._compress_fn(data)
        fn, _ = cls._codecs.get(codec, cls._codecs['zlib'])
        return fn(data)

    @classmethod
    def decompress(cls, data: bytes, codec: str = '') -> bytes:
        if not codec or codec == cls._default:
            return cls._decompress_fn(data)
        _, fn = cls._codecs.get(codec, cls._codecs['zlib'])
        return fn(data)

    @classmethod
    def set_default(cls, codec: str) -> None:
        if codec not in cls._codecs:
            raise KeyError(f"Codec '{codec}' not registered")
        cls._default       = codec
        cls._compress_fn, cls._decompress_fn = cls._codecs[codec]


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
    dtype: Optional[np.dtype] = None
    shape: Optional[Tuple[int, ...]] = None
    python_type: Optional[Type] = None

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
# § 2  NUMBA-JIT KERNELS  (expanded for .0)
# ////////////////////////////////////////////////////////////////////////////////

@njit(cache=True)
def _compute_subdir_offsets(entry_sizes: np.ndarray) -> np.ndarray:
    """Prefix-sum of entry sizes -> byte offsets."""
    n = entry_sizes.shape[0]
    offsets = np.empty(n + 1, dtype=np.int64)
    offsets[0] = 0
    for i in range(n):
        offsets[i + 1] = offsets[i] + entry_sizes[i]
    return offsets


@njit(cache=True, parallel=True)
def _probability_decay(access_counts: np.ndarray,
                       last_access_times: np.ndarray,
                       now: float,
                       decay_lambda: float) -> np.ndarray:
    """
    Parallelised decay scoring.
    prange over outer loop (was sequential range).
    Each lane is independent so no reduction needed.
    """
    n = access_counts.shape[0]
    scores = np.empty(n, dtype=np.float64)
    for i in prange(n):
        dt = now - last_access_times[i]
        scores[i] = access_counts[i] * math.exp(-decay_lambda * dt)
    return scores


@njit(cache=True, parallel=True)
def _matrix_symbol_swap(matrix: np.ndarray,
                        old_val: np.float64,
                        new_val: np.float64) -> np.ndarray:
    """
    Parallelised in-place symbol swap.
    outer prange (rows independent).
    """
    rows, cols = matrix.shape
    for i in prange(rows):
        for j in range(cols):
            if matrix[i, j] == old_val:
                matrix[i, j] = new_val
    return matrix


@njit(cache=True, parallel=True)
def _compute_entry_score_bulk(access_counts: np.ndarray,
                              last_access_times: np.ndarray,
                              now: float,
                              decay_lambda: float) -> np.ndarray:
    """
    Fused score kernel — identical math to _probability_decay but avoids
    allocating a temporary array when the caller only needs argmin/argsort.
    Kept separate so the registry can call this in the hot eviction path
    without allocating a second buffer.

    NEW — fused, parallelised, no intermediate allocations.
    """
    n = access_counts.shape[0]
    scores = np.empty(n, dtype=np.float64)
    for i in prange(n):
        scores[i] = access_counts[i] * math.exp(
            -decay_lambda * (now - last_access_times[i]))
    return scores


@njit(cache=True)
def _batch_adler32_seed(keys_flat: np.ndarray,
                        offsets: np.ndarray) -> np.ndarray:
    """
    Vectorised Adler-32 over a batch of byte sequences packed into a
    flat uint8 array.  offsets[i]..offsets[i+1] is the i-th key.

    NEW — replaces Python-loop zlib.adler32 in hot Bloom/hash paths.
    Adler-32 constants: MOD_ADLER = 65521.
    """
    n = offsets.shape[0] - 1
    out = np.empty(n, dtype=np.uint64)
    MOD = np.uint64(65521)
    for i in range(n):
        A = np.uint64(1)
        B = np.uint64(0)
        start = offsets[i]
        end   = offsets[i + 1]
        for j in range(start, end):
            A = (A + np.uint64(keys_flat[j])) % MOD
            B = (B + A) % MOD
        out[i] = (B << np.uint64(16)) | A
    return out


@njit(cache=True)
def _slot_offsets_cumsum(lengths: np.ndarray) -> np.ndarray:
    """
    Prefix-sum over slot byte-lengths -> byte start positions.
    NEW — used by SlotIndex.to_bytes() parallel path.
    """
    n = lengths.shape[0]
    out = np.empty(n + 1, dtype=np.int64)
    out[0] = 0
    for i in range(n):
        out[i + 1] = out[i] + lengths[i]
    return out


@njit(cache=True)
def _bloom_bits_query(bits: np.ndarray,
                      h1: np.uint64,
                      h2: np.uint64,
                      k: int,
                      m: np.uint64) -> bool:
    """
    JIT Bloom query: returns False on definite miss.
    NEW — eliminates Python loop + attribute lookups in __contains__.
    """
    for i in range(k):
        bit = int((h1 + np.uint64(i) * h2) % m)
        if not ((bits[bit >> 3] >> np.uint8(bit & 7)) & np.uint8(1)):
            return False
    return True


@njit(cache=True)
def _bloom_bits_add(bits: np.ndarray,
                    h1: np.uint64,
                    h2: np.uint64,
                    k: int,
                    m: np.uint64) -> None:
    """
    JIT Bloom add path.
    NEW — eliminates Python loop in BloomFilter.add().
    """
    for i in range(k):
        bit = int((h1 + np.uint64(i) * h2) % m)
        bits[bit >> 3] |= np.uint8(1 << (bit & 7))


def _join_segments(segments: List[np.ndarray],
                   dtype: np.dtype = np.float64) -> np.ndarray:
    if not segments:
        return np.array([], dtype=dtype)
    return np.concatenate([s.astype(dtype).ravel() for s in segments])


# ////////////////////////////////////////////////////////////////////////////////
# § 3  PROBABILITY LRU REGISTRY
# ////////////////////////////////////////////////////////////////////////////////

# Power-of-two cycle fast path: avoid modulo when possible.
_IS_POW2 = lambda n: n > 0 and (n & (n - 1)) == 0


REGISTRY_DTYPE = np.dtype([('count', np.float64), ('time', np.float64), ('handle', np.int64)])


@njit(cache=True)
def _registry_scores(records: np.ndarray,
                     active: np.ndarray,
                     now: float,
                     decay_lambda: float) -> np.ndarray:
    """Score fixed registry records without touching Python objects."""
    n = records.shape[0]
    scores = np.empty(n, dtype=np.float64)
    for i in range(n):
        if active[i]:
            age = now - records[i]['time']
            scores[i] = records[i]['count'] * math.exp(-decay_lambda * age)
        else:
            scores[i] = np.inf
    return scores


class HybridRegistry:
    """
    Probability-weighted LRU using a fixed numpy structured-array store.

    The hot scoring data lives in REGISTRY_DTYPE records:
        ('count', f8), ('time', f8), ('handle', i8)
    Python objects are kept behind integer handles, so eviction/scoring can run
    over contiguous numpy memory and remain Numba-accessible.
    """

    def __init__(self, capacity: int = 4096, decay_lambda: float = 1e-4):
        if int(capacity) <= 0:
            raise ValueError("HybridRegistry capacity must be positive")
        self._cap   = int(capacity)
        self._lam   = float(decay_lambda)
        self._lock  = threading.RLock()
        self._records = np.zeros(self._cap, dtype=REGISTRY_DTYPE)
        self._active  = np.zeros(self._cap, dtype=np.bool_)
        self._key_to_slot: Dict[str, int] = {}
        self._slot_to_key: List[Optional[str]] = [None] * self._cap
        self._handles: Dict[int, Any] = {}
        self._next_handle = 1
        self._size = 0

    def _new_handle(self, value: Any) -> int:
        handle = self._next_handle
        self._next_handle += 1
        self._handles[handle] = value
        return handle

    def _free_slot(self) -> int:
        inactive = np.flatnonzero(~self._active)
        if inactive.size:
            return int(inactive[0])
        scores = _registry_scores(self._records, self._active, time.monotonic(), self._lam)
        return int(np.argmin(scores))

    def _evict_slot(self, slot: int) -> None:
        old_key = self._slot_to_key[slot]
        if old_key is not None:
            self._key_to_slot.pop(old_key, None)
        old_handle = int(self._records[slot]['handle'])
        if old_handle:
            self._handles.pop(old_handle, None)
        if self._active[slot]:
            self._size -= 1
        self._active[slot] = False
        self._slot_to_key[slot] = None
        self._records[slot] = (0.0, 0.0, 0)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            now = time.monotonic()
            slot = self._key_to_slot.get(key)
            if slot is not None:
                old_handle = int(self._records[slot]['handle'])
                self._handles[old_handle] = value
                self._records[slot]['count'] += 1.0
                self._records[slot]['time'] = now
                return

            slot = self._free_slot()
            if self._active[slot]:
                self._evict_slot(slot)
            handle = self._new_handle(value)
            self._records[slot] = (1.0, now, handle)
            self._active[slot] = True
            self._key_to_slot[key] = slot
            self._slot_to_key[slot] = key
            self._size += 1

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            slot = self._key_to_slot.get(key)
            if slot is None or not self._active[slot]:
                return None
            self._records[slot]['count'] += 1.0
            self._records[slot]['time'] = time.monotonic()
            return self._handles.get(int(self._records[slot]['handle']))

    def remove(self, key: str) -> None:
        with self._lock:
            slot = self._key_to_slot.get(key)
            if slot is not None:
                self._evict_slot(slot)

    def sorted_keys(self) -> List[str]:
        with self._lock:
            if not self._size:
                return []
            scores = _registry_scores(self._records, self._active, time.monotonic(), self._lam)
            indices = np.argsort(-scores)
            return [self._slot_to_key[int(i)] for i in indices
                    if self._active[int(i)] and self._slot_to_key[int(i)] is not None]  # type: ignore[list-item]

    @property
    def records(self) -> np.ndarray:
        """Expose structured records for diagnostics/JIT tests without object data."""
        return self._records

    def __len__(self) -> int:
        with self._lock:
            return self._size


# ////////////////////////////////////////////////////////////////////////////////
# § 4  LOOP CACHE
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class LoopCacheSlot:
    """
    Stores a value every `cycle` writes.

    power-of-two fast path uses bitwise AND instead of modulo.
    """
    name: str
    cycle: int
    _write_cnt: int  = field(default=0, repr=False)
    current:    Any  = field(default=None, repr=False)
    _mask:      int  = field(default=0, init=False, repr=False)
    _pow2:      bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.cycle <= 0:
            raise ValueError("LoopCacheSlot cycle must be positive")
        if _IS_POW2(self.cycle):
            self._pow2 = True
            self._mask = self.cycle - 1

    def write(self, value: Any) -> bool:
        self._write_cnt += 1
        triggered = (not (self._write_cnt & self._mask)
                     if self._pow2
                     else self._write_cnt % self.cycle == 0)
        if triggered:
            self.current = value
        return triggered

    def read(self) -> Any:
        return self.current


class LoopCacheManager:
    def __init__(self):
        self._slots: Dict[str, LoopCacheSlot] = {}
        self._lock  = threading.Lock()

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
            triggered = (not (slot._write_cnt & slot._mask)
                         if slot._pow2
                         else slot._write_cnt % slot.cycle == 0)
            if triggered:
                result = slot.current
                slot.current = None
                return result
            return None


# ////////////////////////////////////////////////////////////////////////////////
# § 5  CONCURRENCY POOL
# ////////////////////////////////////////////////////////////////////////////////

class ConcurrencyPool:
    """
    Singleton thread-pool + async event loop.
    Unchanged from earlier releases (already correct).
    """
    _global_instance: Optional['ConcurrencyPool'] = None
    _init_lock = threading.Lock()

    def __init__(self, max_threads: int = 64):
        self._thread_pool = ThreadPoolExecutor(
            max_workers=max_threads, thread_name_prefix='tds_t')
        self._event_loop:  Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_lock   = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
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
# § 6b  BLOOM FILTER  (JIT add/query paths)
# ////////////////////////////////////////////////////////////////////////////////

class BloomFilter:
    """
    Bloom filter for string keys.

    add() and __contains__() delegate bit manipulation to JIT kernels
    _bloom_bits_add / _bloom_bits_query, eliminating the Python loop and
    attribute lookups that dominated the miss path at high slot counts.
    """

    def __init__(self, capacity: int = 100_000, error_rate: float = 0.01):
        m = int(-capacity * math.log(error_rate) / (math.log(2) ** 2))
        k = int((m / capacity) * math.log(2))
        self._m    = np.uint64(max(m, 1))
        self._k    = max(k, 1)
        # numpy array so JIT kernels can accept it directly
        self._bits = np.zeros(math.ceil(int(self._m) / 8), dtype=np.uint8)

    def _hashes(self, key: str) -> Tuple[np.uint64, np.uint64]:
        enc = key.encode()
        h1  = np.uint64(zlib.adler32(enc) & 0xFFFFFFFF)
        h2  = np.uint64(zlib.crc32(enc)   & 0xFFFFFFFF)
        return h1, h2

    def add(self, key: str) -> None:
        h1, h2 = self._hashes(key)
        _bloom_bits_add(self._bits, h1, h2, self._k, self._m)

    def __contains__(self, key: str) -> bool:
        h1, h2 = self._hashes(key)
        return _bloom_bits_query(self._bits, h1, h2, self._k, self._m)


# ////////////////////////////////////////////////////////////////////////////////
# § 7  TDS ENTRY
# ////////////////////////////////////////////////////////////////////////////////

def _serialize_payload(data: Any, fmt_id: FmtID, codec: str = '') -> bytes:
    base = fmt_id & ~FmtID.COMPRESSED
    if base == FmtID.NUMPY_MATRIX and isinstance(data, np.ndarray):
        import io
        buf = io.BytesIO()
        np.save(buf, data, allow_pickle=False)
        raw = buf.getvalue()
    elif base == FmtID.TEXT_UTF8:
        if not isinstance(data, str):
            raise TypeError(f"TEXT_UTF8 entries require str, got {type(data).__name__}")
        raw = data.encode('utf-8')
    elif base == FmtID.JSON_UTF8:
        raw, _backend = json_dumps_fast(data)
    else:
        raw = pickle.dumps(data, protocol=5)
    if fmt_id & FmtID.COMPRESSED:
        raw = CompressorRegistry.compress(raw, codec)
    return raw


def _deserialize_payload(raw: bytes, fmt_id: FmtID, codec: str = '') -> Any:
    if fmt_id & FmtID.COMPRESSED:
        raw = CompressorRegistry.decompress(raw, codec)
    base = fmt_id & ~FmtID.COMPRESSED
    if base == FmtID.NUMPY_MATRIX:
        import io
        return np.load(io.BytesIO(raw), allow_pickle=False)
    if base == FmtID.TEXT_UTF8:
        return raw.decode('utf-8')
    if base == FmtID.JSON_UTF8:
        value, _backend = json_loads_fast(raw)
        return value
    try:
        return pickle.loads(raw)
    except Exception:
        return raw


@dataclass
class TDSEntry:
    name:       str
    fmt_id:     FmtID
    data:       Any
    ts_written: int = field(default_factory=lambda: int(time.time_ns()))
    entry_id:   str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    codec:      str = field(default='')
    payload_kind: str = field(default='')
    content_hash: str = field(default='')
    raw_size: int = 0
    stored_size: int = 0
    provenance: ProvenanceTag = field(default_factory=ProvenanceTag)
    config_id: str = ''
    config_generation: int = 0
    key_id: str | None = None

    def serialise(self) -> bytes:
        raw = _serialize_payload(self.data, self.fmt_id, self.codec)
        return struct.pack('>I', len(raw)) + raw

    @classmethod
    def deserialise(cls, name: str, fmt_id: FmtID, buf: bytes,
                    ts_written: int = 0, entry_id: str = '',
                    codec: str = '', provenance: ProvenanceTag | str | None = None) -> 'TDSEntry':
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


def _split_utf8_chunks(raw: bytes, chunk_size: int) -> List[bytes]:
    """Split UTF-8 encoded bytes without cutting through a code point.

    v2.6 first attempts the native UTF-8 boundary scanner, which releases the
    GIL while walking the payload. If the optional extension is unavailable, the
    existing pure-Python splitter remains the deterministic fallback.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    try:
        from staqtapp_tds import _native_index  # optional extension
        bounds = [int(x) for x in _native_index.utf8_chunk_bounds(raw, int(chunk_size))]
        if bounds:
            start = 0
            chunks: List[bytes] = []
            for end in bounds:
                if end < start or end > len(raw):
                    raise ValueError("native utf8_chunk_bounds returned invalid bounds")
                chunks.append(raw[start:end])
                start = end
            if start == len(raw):
                return chunks
    except Exception:
        pass
    chunks: List[bytes] = []
    i = 0
    n = len(raw)
    while i < n:
        end = min(i + chunk_size, n)
        while end > i:
            try:
                raw[i:end].decode('utf-8')
                break
            except UnicodeDecodeError:
                end -= 1
        if end == i:
            end = min(i + 4, n)
            while end <= n:
                try:
                    raw[i:end].decode('utf-8')
                    break
                except UnicodeDecodeError:
                    end += 1
        chunks.append(raw[i:end])
        i = end
    return chunks

class TDSDirectory:
    def __init__(self, name: str, fmt_id: FmtID = FmtID.RAW_BINARY,
                 flags: int = DirFlags.NONE,
                 parent: Optional['TDSDirectory'] = None,
                 manifest_policy: Optional[ManifestPolicy] = None,
                 srz_enabled: bool = False,
                 route_stamp: str = '',
                 source_tags: Optional[List[str]] = None,
                 aliases: Optional[List[str]] = None,
                 latent_id: Optional[int] = None,
                 telemetry_mode: Optional[TelemetryMode] = None,
                 expected_lookup_ns: Optional[int] = None,
                 runtime_config: Optional[RuntimeConfig] = None,
                 config_registry: Optional[ConfigRegistry] = None,
                 crypto_provider: Optional[CryptoProvider] = None,
                 telemetry_manager: Optional[TelemetryManager] = None):
        self.name    = name
        self.fmt_id  = fmt_id
        self.flags   = flags
        self.parent  = parent
        self.dir_id  = uuid.uuid4().hex
        self._ts_create = int(time.time_ns())
        self._ts_mod    = self._ts_create
        self._entry_index = EntryIndex(shards=64)
        self._entries = self._entry_index  # compatibility alias; not a raw dict in 
        self._children: RadixDirectoryRouter['TDSDirectory'] = RadixDirectoryRouter()
        self._schemas:  Dict[str, EntrySchema]    = {}
        self._lock      = threading.RLock()
        self._pool      = ConcurrencyPool.acquire()
        self._registry  = HybridRegistry(capacity=2048)
        self._bloom     = BloomFilter(capacity=8192)
        self.loop_cache = LoopCacheManager()
        self.symbols    = SymbolTable()
        self.compression_policy = CompressionPolicy(enabled=False, codec='', threshold_bytes=4096)
        self.variables  = VariableControl(self)
        self.invariants = InvariantEngine()
        self.config_registry = config_registry or (parent.config_registry if parent is not None else ConfigRegistry(runtime_config or RuntimeConfig.default()))
        self.crypto_provider: CryptoProvider = crypto_provider or (parent.crypto_provider if parent is not None else NoopCryptoProvider())
        self.telemetry_manager: TelemetryManager = telemetry_manager or (parent.telemetry_manager if parent is not None else TelemetryManager())
        _cfg = self.config_registry.active()
        self.compression_policy = CompressionPolicy(enabled=bool(_cfg.compression_enabled), codec=_cfg.compression, threshold_bytes=int(_cfg.compression_threshold_bytes))
        self._policy_generation = int(_cfg.generation)

        # semantic infrastructure: read-once policy, optional SRZ, and
        # lightweight telemetry. These are separate module objects; filesystem.py
        # only orchestrates them.
        if manifest_policy is None and parent is not None:
            manifest_policy = parent.manifest_policy
        self.manifest_policy = manifest_policy or ManifestPolicy.default()
        self.reserved_namespaces: ReservedNamespaces = self.manifest_policy.reserved_namespaces
        caps = self.manifest_policy.capabilities.names()
        self.capabilities = CapabilityRegistry.from_names(caps)
        self.capabilities.enable(ZoneCapability.NATIVE_INDEX_READY)
        self.capabilities.enable(ZoneCapability.RADIX_ROUTER)
        self.capabilities.enable(ZoneCapability.SHARED_ARENA)
        if srz_enabled:
            self.capabilities.enable(ZoneCapability.SRZ)
        if self.reserved_namespaces.directory_names or self.reserved_namespaces.aliases or self.reserved_namespaces.route_ids:
            self.capabilities.enable(ZoneCapability.RESERVED_NAMESPACES)
        self.capabilities.enable(ZoneCapability.LATENCY)
        self.capabilities.enable(ZoneCapability.TELEMETRY)
        policy_latency = self.manifest_policy.latency_policy
        if expected_lookup_ns is not None:
            policy_latency = LatencyPolicy(
                expected_lookup_ns=int(expected_lookup_ns),
                soft_limit_ns=max(int(expected_lookup_ns) * 2, 1),
                hard_limit_ns=max(int(expected_lookup_ns) * 20, 1),
            )
        mode = telemetry_mode if telemetry_mode is not None else self.manifest_policy.telemetry_mode
        self.telemetry = DirectoryTelemetry(
            mode=mode,
            latency_policy=policy_latency,
            trace_window=self.manifest_policy.trace_window,
        )
        self.srz = SRZMetadata.create(
            enabled=srz_enabled,
            route_stamp=route_stamp,
            path=self.path(),
            source_tags=source_tags or [],
            aliases=aliases or [],
            latent_id=latent_id,
        )

    # --- schema ---

    def set_schema(self, name: str, schema: EntrySchema) -> None:
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
              compress: bool | None = False,
              codec: str = '', provenance: ProvenanceTag | str | None = None) -> 'TDSEntry':
        _obs_start_ns = time.perf_counter_ns()
        self._validate(name, value)
        cfg = self.config_registry.active()
        if int(cfg.generation) != getattr(self, '_policy_generation', 0):
            self.compression_policy = CompressionPolicy(enabled=bool(cfg.compression_enabled), codec=cfg.compression, threshold_bytes=int(cfg.compression_threshold_bytes))
            self._policy_generation = int(cfg.generation)
        raw_fmt = FmtID(fmt_id & ~FmtID.COMPRESSED)
        if codec == '':
            codec = cfg.compression
        raw = _serialize_payload(value, raw_fmt, codec)
        do_compress = self.compression_policy.should_compress(len(raw), force=compress)
        final_fmt = FmtID(raw_fmt | FmtID.COMPRESSED) if do_compress else raw_fmt
        stored = CompressorRegistry.compress(raw, codec) if do_compress else raw
        ptag = provenance if isinstance(provenance, ProvenanceTag) else (ProvenanceTag.create(provenance) if isinstance(provenance, str) else ProvenanceTag())
        entry = TDSEntry(
            name=name, fmt_id=final_fmt, data=value, codec=codec,
            payload_kind=kind_name(int(raw_fmt)),
            content_hash=content_hash_bytes(raw),
            raw_size=len(raw), stored_size=len(stored), provenance=ptag,
            config_id=cfg.config_id, config_generation=cfg.generation, key_id=cfg.key_id,
        )
        with self._lock:
            self._entries.put(name, entry)
            self._ts_mod = int(time.time_ns())
            self._bloom.add(name)
        self._registry.put(name, entry)
        self.telemetry_manager.record_write(
            time.perf_counter_ns() - _obs_start_ns,
            raw_size=len(raw),
            stored_size=len(stored),
            backend=self._entry_index.backend_name,
        )
        return entry

    def write_variable(self, name: str, value: Any, *, compress: bool | None = None, codec: str = '', provenance: ProvenanceTag | str | None = None) -> 'TDSEntry':
        kind = choose_variable_kind(value)
        return self.write(name, value, fmt_id=FmtID(int(kind)), compress=compress, codec=codec, provenance=provenance)

    def write_json(self, name: str, value: Any, *, overwrite: bool = False, compress: bool | None = None, codec: str = '', provenance: ProvenanceTag | str | None = None) -> TDSResult:
        with self._lock:
            exists = name in self._entries
        if exists and not overwrite:
            self.variables.errors.record('JSON_EXISTS', path=self.path(), name=name)
            return TDSResult.fail('JSON_EXISTS', 'JSON entry already exists; use overwrite=True to replace.', name=name, path=self.path())
        self.write(name, value, fmt_id=FmtID.JSON_UTF8, compress=compress, codec=codec, provenance=provenance)
        return TDSResult.success('JSON_WRITTEN' if not exists else 'JSON_OVERWRITTEN', 'JSON entry stored.', name=name, path=self.path(), value=value)

    def write_text(self, name: str, text: str, *, overwrite: bool = False,
                   compress: bool | None = None, codec: str = '', provenance: ProvenanceTag | str | None = None) -> TDSResult:
        """Store a whole text file as first-class UTF-8 text.

        Duplicate text names return structured feedback unless overwrite=True.
        This keeps text storage separate from Python-variable semantics while
        using the same directory namespace.
        """
        if not isinstance(text, str):
            return TDSResult.fail('TEXT_TYPE_ERROR', 'Text entries require str data.', name=name, path=self.path())
        with self._lock:
            exists = name in self._entries
        if exists and not overwrite:
            self.variables.errors.record('TEXT_EXISTS', path=self.path(), name=name)
            return TDSResult.fail('TEXT_EXISTS', 'Text entry already exists; use overwrite=True to replace.', name=name, path=self.path())
        entry = self.write(name, text, fmt_id=FmtID.TEXT_UTF8, compress=compress, codec=codec, provenance=provenance)
        return TDSResult.success('TEXT_WRITTEN' if not exists else 'TEXT_OVERWRITTEN', 'Text entry stored.', name=name, path=self.path(), value=text, meta={'compressed': bool(entry.fmt_id & FmtID.COMPRESSED), 'codec': codec or CompressorRegistry._default, 'content_hash': entry.content_hash, 'raw_size': entry.raw_size, 'stored_size': entry.stored_size})

    def _text_chunk_prefix(self, name: str) -> str:
        h = zlib.adler32(name.encode('utf-8')) & 0xFFFFFFFF
        return f".__tds_chunk__{h:08x}_"

    def write_text_chunked(self, name: str, text: str, *, chunk_size: int = 65536,
                           overwrite: bool = False, compress: bool | None = None, codec: str = '') -> TDSResult:
        if not isinstance(text, str):
            return TDSResult.fail('TEXT_TYPE_ERROR', 'Chunked text entries require str data.', name=name, path=self.path())
        if int(chunk_size) <= 0:
            return TDSResult.fail('TEXT_CHUNK_SIZE_INVALID', 'chunk_size must be positive.', name=name, path=self.path())
        with self._lock:
            exists = name in self._entries
        if exists and not overwrite:
            self.variables.errors.record('TEXT_EXISTS', path=self.path(), name=name)
            return TDSResult.fail('TEXT_EXISTS', 'Text entry already exists; use overwrite=True to replace.', name=name, path=self.path())
        if exists and overwrite:
            try:
                prior = self.read(name)
                if isinstance(prior, dict) and prior.get('kind') == 'TEXT_CHUNKED_UTF8':
                    for chunk_name in prior.get('chunks', []) or []:
                        if chunk_name in self._entries:
                            self.delete(chunk_name)
            except Exception:
                pass
        raw = text.encode('utf-8')
        prefix = self._text_chunk_prefix(name)
        chunk_scan_start = time.perf_counter_ns()
        chunks_raw = _split_utf8_chunks(raw, int(chunk_size)) or [b'']
        chunk_names = []
        self.telemetry_manager.record_chunk_transition("pending", len(chunks_raw))
        for i, chunk_raw in enumerate(chunks_raw):
            cname = f"{prefix}{i:06d}"
            try:
                self.telemetry_manager.record_chunk_transition("sealed")
                self.telemetry_manager.record_chunk_transition("verified")
                self.write(cname, chunk_raw.decode('utf-8'), fmt_id=FmtID.TEXT_UTF8, compress=compress, codec=codec)
                self.telemetry_manager.record_chunk_transition("indexed")
                self.telemetry_manager.record_chunk_transition("exposed")
                chunk_names.append(cname)
            except Exception:
                self.telemetry_manager.record_chunk_transition("quarantined")
                raise
        manifest = {
            'kind': 'TEXT_CHUNKED_UTF8', 'name': name,
            'chunk_size': int(chunk_size), 'chunk_size_unit': 'utf8_bytes',
            'chunks': chunk_names, 'content_hash': content_hash_bytes(raw),
            'raw_size': len(raw), 'chunk_count': len(chunk_names),
        }
        self.write(name, manifest, fmt_id=FmtID.JSON_UTF8, compress=False)
        self.telemetry_manager.record_chunk(len(chunk_names), time.perf_counter_ns() - chunk_scan_start)
        return TDSResult.success('TEXT_CHUNKED_WRITTEN' if not exists else 'TEXT_CHUNKED_OVERWRITTEN', 'Chunked text entry stored.', name=name, path=self.path(), meta={'chunks': len(chunk_names), 'content_hash': manifest['content_hash'], 'raw_size': len(raw)})

    def read_text(self, name: str) -> str:
        value = self.read(name)
        if isinstance(value, dict) and value.get('kind') == 'TEXT_CHUNKED_UTF8':
            parts = [self.read(chunk_name) for chunk_name in value.get('chunks', [])]
            return ''.join(parts)
        if not isinstance(value, str):
            raise TypeError(f"Entry {name!r} is not a UTF-8 text entry")
        return value

    def addvar(self, name: str, data: Any) -> TDSResult:
        return self.variables.addvar(name, data)

    def editvar(self, name: str, data: Any, *, overwrite: bool = True) -> TDSResult:
        return self.variables.editvar(name, data, overwrite=overwrite)

    def lockvar(self, name: str, locked: bool = True) -> TDSResult:
        return self.variables.lockvar(name, locked)

    def unlockvar(self, name: str) -> TDSResult:
        return self.variables.unlockvar(name)

    def stalkvar(self, name: str, data: Any = None) -> TDSResult:
        return self.variables.stalkvar(name, data)

    def findvar(self, name: str) -> TDSResult:
        return self.variables.findvar(name)

    def loadvar(self, name: str) -> Any:
        return self.variables.loadvar(name)

    def variable_control_snapshot(self) -> dict:
        return self.variables.snapshot()

    def entry_metadata(self, name: str) -> dict:
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(name)
        return {
            'name': entry.name, 'fmt_id': int(entry.fmt_id), 'payload_kind': entry.payload_kind,
            'content_hash': entry.content_hash, 'raw_size': int(entry.raw_size),
            'stored_size': int(entry.stored_size), 'codec': entry.codec,
            'compressed': bool(entry.fmt_id & FmtID.COMPRESSED),
            'provenance': getattr(entry, 'provenance', ProvenanceTag()).as_dict(),
            'config_id': getattr(entry, 'config_id', ''),
            'config_generation': int(getattr(entry, 'config_generation', 0)),
            'key_id': getattr(entry, 'key_id', None),
        }

    def invariant_report(self) -> dict:
        return self.invariants.evaluate_directory(self).as_dict()

    def provenance_record(self, name: str) -> np.ndarray:
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(name)
        return getattr(entry, 'provenance', ProvenanceTag()).compact_record(f'{self.path()}::{name}')

    def read(self, name: str) -> Any:
        start_ns = self.telemetry.start()
        route_id = int(self.srz.route_id) if self.srz.enabled else 0
        # JIT Bloom gate — definite miss with no lock acquired
        if name not in self._bloom:
            elapsed = time.perf_counter_ns() - start_ns
            if self.telemetry.enabled:
                self.telemetry.record_lookup(elapsed, hit=False, error_code=1, route_id=route_id)
            self.telemetry_manager.record_read(elapsed, hit=False, backend=self._entry_index.backend_name)
            self.telemetry_manager.record_error()
            raise KeyError(f"No entry '{name}' in {self.name!r}")
        # Check registry first (lock-free path for hot entries)
        cached = self._registry.get(name)
        if cached is not None:
            elapsed = time.perf_counter_ns() - start_ns
            if self.telemetry.enabled:
                self.telemetry.record_lookup(elapsed, hit=True, cold=False, route_id=route_id)
            self.telemetry_manager.record_read(elapsed, hit=True, backend=self._entry_index.backend_name)
            return cached.data
        # Fallback: lock and look up in EntryIndex
        with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                elapsed = time.perf_counter_ns() - start_ns
                if self.telemetry.enabled:
                    self.telemetry.record_lookup(elapsed, hit=False, error_code=2, route_id=route_id)
                self.telemetry_manager.record_read(elapsed, hit=False, backend=self._entry_index.backend_name)
                self.telemetry_manager.record_error()
                raise KeyError(f"No entry '{name}' in {self.name!r}")
        self._registry.put(name, entry)
        elapsed = time.perf_counter_ns() - start_ns
        if self.telemetry.enabled:
            self.telemetry.record_lookup(elapsed, hit=True, cold=True, route_id=route_id)
        self.telemetry_manager.record_read(elapsed, hit=True, backend=self._entry_index.backend_name)
        return entry.data

    def delete(self, name: str) -> None:
        with self._lock:
            self._entries.pop(name, None)
            self._ts_mod = int(time.time_ns())
        self._registry.remove(name)
        self.telemetry_manager.record_delete()

    # --- async surface ---

    async def awrite(self, name: str, value: Any, **kwargs) -> 'TDSEntry':
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.write(name, value, **kwargs))

    async def aread(self, name: str) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.read(name))

    # --- directory ops ---

    def mkdir(self, name: str, **kwargs) -> 'TDSDirectory':
        allow_reserved = bool(kwargs.pop('allow_reserved', False))
        if self.is_reserved_namespace(name) and not allow_reserved:
            raise ValueError(f"Directory name {name!r} is reserved by manifest policy")
        kwargs.setdefault('manifest_policy', self.manifest_policy)
        kwargs.setdefault('config_registry', self.config_registry)
        kwargs.setdefault('crypto_provider', self.crypto_provider)
        kwargs.setdefault('telemetry_manager', self.telemetry_manager)
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
            entry_names = self._entries.keys()
        if sort_by_prob and (self.flags & DirFlags.PROB_SORT):
            entry_names = self._registry.sorted_keys()
        return child_names + entry_names

    def parallel_read_all(self) -> Dict[str, Any]:
        """
        Read all entries concurrently.
        pre-sized output dict to avoid re-hashing during fill.
        """
        with self._lock:
            keys = self._entries.keys()

        def _read_one(k):
            return (k, self.read(k))

        pairs = self._pool.map_parallel(_read_one, keys)
        # Pre-size the result dict
        result: Dict[str, Any] = dict.fromkeys(keys)
        for k, v in pairs:
            result[k] = v
        return result

    def recursive_join(self, dtype=np.float64, max_depth: int = 8) -> np.ndarray:
        """Concatenate all numpy array entries in the subtree."""
        segments: List[np.ndarray] = []

        def _collect(node: 'TDSDirectory', depth: int):
            if depth >= max_depth:
                return
            with node._lock:
                entries  = node._entries.values()
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
            entries = self._entries.values()
        sizes = np.array([len(e.serialise()) for e in entries], dtype=np.int64)
        return _compute_subdir_offsets(sizes)

    def to_bytes(self) -> bytes:
        """
        serialise payloads in parallel, then join.
        Avoids sequential bottleneck on large directories.
        """
        header = self.header_bytes()
        with self._lock:
            entries = self._entries.values()

        def _pack_entry(entry: TDSEntry) -> bytes:
            name_enc = entry.name.encode()
            if len(name_enc) > 0xFFFF:
                raise ValueError(f"Entry name too long for directory byte format: {entry.name!r}")
            edata    = entry.serialise()
            return struct.pack('>H', len(name_enc)) + name_enc + edata

        payloads = self._pool.map_parallel(_pack_entry, entries)
        body = CompressorRegistry.compress(b''.join(payloads))
        return header + struct.pack('>I', len(body)) + body

    def path(self) -> str:
        parts: List[str] = []
        node: Optional['TDSDirectory'] = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return '/' + '/'.join(reversed(parts))

    def telemetry_snapshot(self) -> dict:
        snap = self.telemetry.snapshot()
        snap['path'] = self.path()
        snap['route_id'] = int(self.srz.route_id) if self.srz.enabled else 0
        try:
            istats = self._entry_index.stats()
            snap['index'] = istats.__dict__.copy() if hasattr(istats, '__dict__') else dict(istats)
        except Exception:
            snap['index'] = {'backend': self._entry_index.backend_name}
        try:
            snap['radix'] = self._children.stats()
        except Exception:
            snap['radix'] = {'backend': getattr(self._children, 'backend_name', 'unknown')}
        return snap

    def capability_names(self) -> List[str]:
        return self.capabilities.names()

    def is_reserved_namespace(self, name: str) -> bool:
        return self.reserved_namespaces.is_reserved_directory(name)

    def reserved_namespace_names(self) -> List[str]:
        return self.reserved_namespaces.names()

    def srz_record(self) -> np.ndarray:
        t = self.telemetry.snapshot()
        bucket_name = str(t.get('bucket', 'hot')).upper()
        from staqtapp_tds.latency import LatencyBucket
        bucket = int(LatencyBucket[bucket_name]) if bucket_name in LatencyBucket.__members__ else 0
        return self.srz.compact_record(
            dir_handle=-1,
            expected_ns=self.telemetry.latency_policy.expected_lookup_ns,
            avg_ns=int(t.get('avg_ns', 0)),
            hits=int(t.get('hits', 0)),
            misses=int(t.get('misses', 0)),
            bucket=bucket,
        )

    def __repr__(self) -> str:
        return (f"<TDSDirectory '{self.path()}' "
                f"entries={len(self._entries)} "
                f"subdirs={len(self._children)} "
                f"fmt={self.fmt_id.name} "
                f"srz={self.srz.enabled}>")


# ////////////////////////////////////////////////////////////////////////////////
# § 9  TDS FILE SYSTEM
# ////////////////////////////////////////////////////////////////////////////////

class TDSFileSystem:
    """
    ---- Usage ----
        fs  = TDSFileSystem("asi_root")
        db  = fs.root.mkdir("databases", flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
        mem = fs.root.mkdir("working_mem", flags=DirFlags.LOOP_PINNED)

        db.set_schema("embedding_matrix", EntrySchema(dtype=np.float32, shape=(1024, 1024)))
        db.write("embedding_matrix", np.random.randn(1024, 1024).astype(np.float32),
                 fmt_id=FmtID.NUMPY_MATRIX, compress=True)

        mem.loop_cache.register("gradient_buf", cycle=32)
        for step in range(100):
            g = np.random.randn(256)
            mem.loop_cache.write("gradient_buf", g)

        import asyncio
        asyncio.run(db.awrite("key", value))
        value = asyncio.run(db.aread("key"))
    """
    VERSION = (2, 5, 0)

    def __init__(self, name: str = "tds_root", manifest_policy: Optional[ManifestPolicy] = None, runtime_config: Optional[RuntimeConfig] = None, config_registry: Optional[ConfigRegistry] = None, crypto_provider: Optional[CryptoProvider] = None, telemetry_manager: Optional[TelemetryManager] = None):
        self.manifest_policy = manifest_policy or ManifestPolicy.default()
        self.config_registry = config_registry or ConfigRegistry(runtime_config or RuntimeConfig.default())
        self.crypto_provider: CryptoProvider = crypto_provider or NoopCryptoProvider()
        cfg = self.config_registry.active()
        self.telemetry_manager: TelemetryManager = telemetry_manager or TelemetryManager(level=getattr(cfg, "telemetry_level", "normal"))
        self.root = TDSDirectory(
            name   = name,
            fmt_id = FmtID.RAW_BINARY,
            flags  = DirFlags.PARALLEL_IO | DirFlags.PROB_SORT | DirFlags.RECURSIVE,
            manifest_policy = self.manifest_policy,
            config_registry = self.config_registry,
            crypto_provider = self.crypto_provider,
            telemetry_manager = self.telemetry_manager,
        )
        self._pool = ConcurrencyPool.acquire()
        self.telemetry_manager.register_sampler("swiss", self._swiss_stats_snapshot)
        self.telemetry_manager.register_sampler("radix", self._radix_stats_snapshot)
        self.telemetry_manager.register_sampler("storage", self._storage_stats_snapshot)
        self.telemetry_manager.register_sampler("components", self._component_status_snapshot)


    def _walk_directories(self):
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            with node._lock:
                stack.extend(list(node._children.values()))

    def _swiss_stats_snapshot(self) -> dict:
        total_entries = 0
        backends: Dict[str, int] = {}
        max_probe = 0
        avg_probe_sum = 0.0
        stat_count = 0
        for node in self._walk_directories():
            try:
                stats = node._entry_index.stats()
                data = stats.__dict__.copy() if hasattr(stats, '__dict__') else dict(stats)
                if hasattr(node._entry_index, "native_execution_stats"):
                    try:
                        self.telemetry_manager.merge_native_execution_stats(node._entry_index.native_execution_stats())
                    except Exception:
                        pass
            except Exception:
                data = {"backend": node._entry_index.backend_name, "size": len(node._entry_index)}
            size = int(data.get("size", data.get("entries", len(node._entry_index))) or 0)
            total_entries += size
            backend = str(data.get("backend", node._entry_index.backend_name))
            backends[backend] = backends.get(backend, 0) + 1
            max_probe = max(max_probe, int(data.get("max_probe", 0) or 0))
            if "average_probe" in data or "avg_probe" in data:
                avg_probe_sum += float(data.get("average_probe", data.get("avg_probe", 0.0)) or 0.0)
                stat_count += 1
        return {
            "entries": total_entries,
            "directory_count": sum(backends.values()),
            "backends": backends,
            "max_probe": max_probe,
            "average_probe": round(avg_probe_sum / stat_count, 3) if stat_count else 0.0,
            "gil_released_stats_scan": True,
        }

    def _radix_stats_snapshot(self) -> dict:
        routers = 0
        nodes = 0
        edges = 0
        max_depth = 0
        avg_steps_sum = 0.0
        for node in self._walk_directories():
            routers += 1
            try:
                st = node._children.stats()
            except Exception:
                st = {}
            nodes += int(st.get("nodes", 0) or 0)
            edges += int(st.get("edges", 0) or 0)
            max_depth = max(max_depth, int(st.get("max_depth", 0) or 0))
            avg_steps_sum += float(st.get("average_lookup_steps", 0.0) or 0.0)
        return {
            "backend": "python-radix-router",
            "routers": routers,
            "nodes": nodes,
            "edges": edges,
            "max_depth": max_depth,
            "average_lookup_steps": round(avg_steps_sum / max(1, routers), 3),
        }

    def _storage_stats_snapshot(self) -> dict:
        directory_count = 0
        entry_count = 0
        child_count = 0
        for node in self._walk_directories():
            directory_count += 1
            with node._lock:
                entry_count += len(node._entries)
                child_count += len(node._children)
        return {
            "directories": directory_count,
            "entries": entry_count,
            "children": child_count,
            "active_config": self.config_registry.active().config_id,
            "config_generation": self.config_registry.active().generation,
        }

    def _component_status_snapshot(self) -> dict:
        cfg = self.config_registry.active()
        return {
            "tds_api": {"status": "healthy", "version": ".".join(map(str, self.VERSION))},
            "runtime_config": {"status": "healthy", "config_id": cfg.config_id, "generation": cfg.generation},
            "swiss_index": {"status": "healthy", "backend": self.root._entry_index.backend_name},
            "radix_router": {"status": "healthy", "backend": self.root._children.backend_name},
            "telemetry_manager": {"status": "healthy", "snapshot_interval_seconds": self.telemetry_manager.snapshot_interval_seconds},
        }

    def observation_snapshot(self, *, force: bool = False) -> Dict[str, object]:
        """Return the cached dashboard/observability snapshot."""
        return self.telemetry_manager.snapshot(force=force)

    def resolve(self, path: str) -> TDSDirectory:
        parts = [p for p in path.strip('/').split('/') if p]
        node  = self.root
        for part in parts:
            node = node.cd(part)
        return node

    def resolve_radix(self, path: str) -> TDSDirectory:
        return self.root._children.resolve_path(path) if path.strip('/') else self.root

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

    def telemetry_snapshot(self) -> Dict[str, dict]:
        result: Dict[str, dict] = {}
        def _walk(node: TDSDirectory):
            result[node.path()] = node.telemetry_snapshot()
            with node._lock:
                children = list(node._children.values())
            for child in children:
                _walk(child)
        _walk(self.root)
        return result

    def capability_snapshot(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        def _walk(node: TDSDirectory):
            result[node.path()] = node.capability_names()
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
# § 9b  WRITE-AHEAD LOG
# ////////////////////////////////////////////////////////////////////////////////

class WriteAheadLog:
    """
    Append-only WAL for TDSDirectory writes.

    Layout per record:
        [4B magic 'WALR'] [4B name_len] [name_bytes]
        [4B fmt_id] [8B ts] [4B data_len] [data_bytes]
        [4B CRC32 of above]
    """
    _MAGIC    = b'WALR'
    _REC_HDR  = '>4sII'
    _REC_HDR_SIZE = struct.calcsize(_REC_HDR)

    def __init__(self, path):
        from pathlib import Path
        self._path = Path(path)
        self._lock = threading.Lock()
        self._f    = open(self._path, 'ab', buffering=0)

    def append(self, entry: 'TDSEntry') -> None:
        name_b = entry.name.encode('utf-8')
        data_b = _serialize_payload(entry.data, entry.fmt_id, entry.codec)
        ts_b   = struct.pack('>Q', entry.ts_written)
        body   = (struct.pack(self._REC_HDR, self._MAGIC,
                              len(name_b), int(entry.fmt_id))
                  + name_b + ts_b
                  + struct.pack('>I', len(data_b)) + data_b)
        crc    = zlib.crc32(body) & 0xFFFFFFFF
        record = body + struct.pack('>I', crc)
        with self._lock:
            self._f.write(record)
            os.fsync(self._f.fileno())

    def checkpoint(self) -> None:
        with self._lock:
            self._f.truncate(0)
            self._f.seek(0)
            os.fsync(self._f.fileno())

    def replay(self, directory: 'TDSDirectory') -> int:
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
                body   = raw[cursor: p - 4]
                if (zlib.crc32(body) & 0xFFFFFFFF) != stored_crc:
                    break
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
    print(">> Initialising TDS VFS .0 ...")
    fs = TDSFileSystem("asi_root")

    vec_db = fs.makedirs("databases/vectors",
                         fmt_id=FmtID.NUMPY_MATRIX,
                         flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
    sym_db = fs.makedirs("databases/symbols",
                         fmt_id=FmtID.SYMBOL_TABLE,
                         flags=DirFlags.RECURSIVE)
    wm     = fs.makedirs("working_memory", flags=DirFlags.LOOP_PINNED)

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

    print(">> Loop cache: pow-2 fast path (cycle=8) ...")
    wm.loop_cache.register("grad_buf", cycle=8)   # pow-2 → bitwise AND path
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

    print(">> Bloom filter miss test (JIT paths) ...")
    assert "embed_0000" in vec_db._bloom
    assert "nonexistent_key" not in vec_db._bloom
    print("   Bloom filter working correctly.")

    print(">> TDS demo complete.")
    print(fs)


if __name__ == '__main__':
    demo()

"""
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
>>> Staqtapp-TDS / tds_persistence.py
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////


Staqtapp-TDS / Temporal Directory System
VFS for ASI large scale computation
Extension: .tds


>> This module extends tds_filesystem.py:

  § 10  TDSFile            > Single .tds file on disk, slot-indexed
  § 11  SlotIndex          > Numba accelerated seek table, offset + length
  § 12  TDSReader          > Seek based random-access reader, mmap backed
  § 13  TDSWriter          > Atomic append writer with fsync + shadow swap
  § 14  TDSPersistence     > Mount/unmount/flush API bridging FS <-> disk
  § 15  ParallelFlusher    > Concurrent multi-file flush via pool


Physical .tds file layout on disk
──────────────────────────────────────────────────────────────────────
  Byte 0..3      File magic          "TDSX"  (0x54 44 53 58)
  Byte 4..7      Format version      uint32  (currently 1)
  Byte 8..15     Slot count          uint64
  Byte 16..23    Index block offset  uint64  (where SlotIndex lives)
  Byte 24..31    Data block offset   uint64  (where entry payloads live)
  Byte 32..39    Timestamp (ns)      uint64
  Byte 40..43    Header CRC32        uint32
  
  ---- 44 byte file header ----

  [Data block]   Variable length entry payloads
  [Index block]  SlotIndex table -> one record per entry:
                    name_hash (8) | offset (8) | length (4) | fmt_id (2)
                    name_len  (2) | name_bytes (name_len)
                    == 24 bytes fixed + name_len bytes per slot
──────────────────────────────────────────────────────────────────────
"""


from __future__ import annotations
import mmap
import os
import shutil
import struct
import threading
import time
import zlib
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
import numpy as np

from tds_filesystem import (TDSDirectory, TDSEntry, TDSFileSystem, FmtID, DirFlags, ConcurrencyPool, decode_header, encode_header, _compute_subdir_offsets, HEADER_SIZE, TDS_MAGIC,)

try:
    from numba import njit, prange
    _NUMBA = True
except ImportError:
    def njit(*a, **kw):
        def d(fn): return fn
        return d(a[0]) if a and callable(a[0]) else d
    prange = range; _NUMBA = False

# ////////////////////////////////////////////////////////////////////////////////
#
# § 10  FILE-LEVEL CONSTANTS & STRUCTS ///////////////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

FILE_MAGIC   = b'TDSX'
FILE_VERSION = 1
# Fixed-width file header  (44 bytes)
FILE_HDR_FMT  = '>4sIQQQQI'
FILE_HDR_SIZE = struct.calcsize(FILE_HDR_FMT)   # 44 bytes
# Fixed part of each slot record -> 24 bytes
SLOT_FIXED_FMT  = '>QQIHH'
SLOT_FIXED_SIZE = struct.calcsize(SLOT_FIXED_FMT)  # 24 bytes

def _build_file_header(slot_count: int, index_offset: int, data_offset:  int) -> bytes:
    ts  = int(time.time_ns())
    # CRC placeholder
    raw = struct.pack(FILE_HDR_FMT, FILE_MAGIC, FILE_VERSION, slot_count, index_offset, data_offset, ts, 0)
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return struct.pack(FILE_HDR_FMT, FILE_MAGIC, FILE_VERSION, slot_count, index_offset, data_offset, ts, crc)

def _parse_file_header(raw: bytes) -> dict:
    if len(raw) < FILE_HDR_SIZE:
        raise ValueError("Buffer too short for TDS file header")
    magic, ver, slot_count, idx_off, data_off, ts, crc = \
        struct.unpack(FILE_HDR_FMT, raw[:FILE_HDR_SIZE])
    if magic != FILE_MAGIC:
        raise ValueError(f"Bad file magic: {magic!r}")
    if ver != FILE_VERSION:
        raise ValueError(f"Unsupported TDS file version: {ver}")
    check = struct.pack(FILE_HDR_FMT, magic, ver, slot_count, idx_off, data_off, ts, 0)
    if (zlib.crc32(check) & 0xFFFFFFFF) != crc:
        raise ValueError("File header CRC mismatch")
    return dict(slot_count=slot_count, index_offset=idx_off,
                data_offset=data_off, ts=ts)

# ////////////////////////////////////////////////////////////////////////////////
#
# § 11  SLOT INDEX / Numba accelerated seek table ////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class SlotRecord:
    name: str
    name_hash: int    # xxhash style: zlib.adler32 of name bytes, state of the art
    offset: int       # byte offset of payload inside data block
    length: int       # byte length of payload
    fmt_id: int       # FmtID value

@njit(cache=True)
def _slot_binary_search(hashes: np.ndarray, target: np.int64) -> np.int64:
    # Binary search over a sorted array of name_hashes
    # Returns the index where target is found or -1
    lo, hi = np.int64(0), np.int64(hashes.shape[0] - 1)
    while lo <= hi:
        mid = (lo + hi) >> 1
        if hashes[mid] == target:
            return mid
        elif hashes[mid] < target: lo = mid + 1
        else: hi = mid - 1
    return np.int64(-1)

@njit(cache=True)
def _build_sorted_order(hashes: np.ndarray) -> np.ndarray:
    # Argsort hashes ascending: Used to build the sorted seek table
    return np.argsort(hashes)

class SlotIndex:
    # In-memory seek table for one .tds file
    # Sorted by name_hash for O(log n) numba binary search
    # Falls back to linear scan on hash collision, rare

    def __init__(self):
        self._records: List[SlotRecord] = []
        self._hashes: Optional[np.ndarray] = None # sorted hash array
        self._order: Optional[np.ndarray] = None # argsort indices
        self._dirty = True
        self._lock = threading.Lock()

    def add(self, record: SlotRecord) -> None:
        with self._lock:
            self._records.append(record); self._dirty = True

    def _rebuild(self) -> None:
        # Rebuild sorted numpy arrays from current record list
        if not self._records:
            self._hashes = np.array([], dtype=np.int64)
            self._order  = np.array([], dtype=np.int64)
            self._dirty  = False
            return
        raw_hashes = np.array([r.name_hash for r in self._records], dtype=np.int64)
        order = _build_sorted_order(raw_hashes)
        self._hashes = raw_hashes[order]; self._order = order; self._dirty = False

    def lookup(self, name: str) -> Optional[SlotRecord]:
        h = zlib.adler32(name.encode()) & 0x7FFFFFFFFFFFFFFF
        with self._lock:
            if self._dirty: self._rebuild()
            if self._hashes is None or len(self._hashes) == 0:
                return None
            idx = _slot_binary_search(self._hashes, np.int64(h))
            if idx < 0:
                return None
            # Resolve through argsort to original record
            orig_idx = int(self._order[idx]); rec = self._records[orig_idx]
            # Collision guard -> verify the name matches!
            if rec.name == name:
                return rec
            # Linear fallback scan for collisions
            for r in self._records:
                if r.name == name:
                    return r
            return None

    def all_records(self) -> List[SlotRecord]:
        with self._lock:
            return list(self._records)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def to_bytes(self) -> bytes:
        # Serialize entire slot index to bytes for writing at end of .tds file
        # Layout per slot:
        #   > name_hash(8) offset(8) length(4) fmt_id(2) name_len(2) name_bytes(N)
        parts = []
        with self._lock:
            for rec in self._records:
                nb = rec.name.encode('utf-8')
                parts.append(struct.pack(SLOT_FIXED_FMT, rec.name_hash, rec.offset, rec.length, rec.fmt_id, len(nb)) + nb)
        return b''.join(parts)

    @classmethod
    def from_bytes(cls, buf: bytes, slot_count: int) -> 'SlotIndex':
        # Deserialize index block read from disk
        idx = cls(); cursor = 0
        for _ in range(slot_count):
            if cursor + SLOT_FIXED_SIZE > len(buf):
                break
            name_hash, offset, length, fmt_id, name_len = struct.unpack(SLOT_FIXED_FMT, buf[cursor:cursor + SLOT_FIXED_SIZE])
            cursor += SLOT_FIXED_SIZE; name = buf[cursor:cursor + name_len].decode('utf-8'); cursor += name_len
            idx.add(SlotRecord(name=name, name_hash=name_hash, offset=offset, length=length, fmt_id=fmt_id))
        return idx

# ////////////////////////////////////////////////////////////////////////////////
#
# § 12  TDS READER / Seek basis random access, mmap-backed ///////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class TDSReader:
    """
    Mmap random-access reader for a .tds file on disk

    (1) Open file and mmap the whole thing read-only
    (2) Parse the 44 byte file header, locate index block & data block
    (3) Deserialize SlotIndex from index block
    (4) For any entry read: SlotIndex.lookup(name) -> (offset, length) ->
        single seek into the mmap -> deserialize payload

    **No full-file scan ever occurs after initial index load**
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"TDS file not found: {self.path}")
        self._f = open(self.path, 'rb')
        self._mm  = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        self._lock = threading.Lock(); self._hdr = self._load_header(); self._idx = self._load_index()

    def _load_header(self) -> dict:
        raw = self._mm[:FILE_HDR_SIZE]
        return _parse_file_header(bytes(raw))

    def _load_index(self) -> SlotIndex:
        idx_off = self._hdr['index_offset']
        slot_count = self._hdr['slot_count']
        # Index runs from idx_off to end of file
        idx_bytes = bytes(self._mm[idx_off:])
        return SlotIndex.from_bytes(idx_bytes, slot_count)

    def read(self, name: str) -> Any:
        # Seek directly to the entry payload and deserialize
        rec = self._idx.lookup(name)
        if rec is None:
            raise KeyError(f"Entry '{name}' not found in {self.path.name!r}")
        data_base = self._hdr['data_offset']; abs_off = data_base + rec.offset
        with self._lock: payload = bytes(self._mm[abs_off: abs_off + rec.length])
        return self._deserialize(payload, FmtID(rec.fmt_id))

    def read_raw(self, name: str) -> bytes:
        # Return raw compressed payload bytes, no deserialization
        rec = self._idx.lookup(name)
        if rec is None:
            raise KeyError(name)
        data_base = self._hdr['data_offset']
        abs_off = data_base + rec.offset
        with self._lock:
            return bytes(self._mm[abs_off: abs_off + rec.length])

    def read_many(self, names: List[str]) -> Dict[str, Any]:
        # Parallel multi-entry read: Launches one thread per name; all seek into mmap concurrently
        pool = ConcurrencyPool.acquire()
        
        def _one(n):
            return (n, self.read(n))

        results = pool.map_parallel(_one, names)
        return dict(results)

    def keys(self) -> List[str]:
        # List all entry names stored in this file
        return [r.name for r in self._idx.all_records()]

    def __len__(self) -> int:
        return len(self._idx)

    def __contains__(self, name: str) -> bool:
        return self._idx.lookup(name) is not None

    @staticmethod
    def _deserialize(payload: bytes, fmt_id: FmtID) -> Any:
        # Dispatch to the right deserializer based on fmt_id
        # Decompresses first if COMPRESSED flag is set
        raw = payload
        if FmtID.COMPRESSED in fmt_id: raw = zlib.decompress(raw)
        base = fmt_id & ~FmtID.COMPRESSED
        if base == FmtID.NUMPY_MATRIX:
            # Stored as npy bytes via np.save
            import io
            return np.load(io.BytesIO(raw), allow_pickle=False)
        elif base == FmtID.SYMBOL_TABLE:
            # Symbol tables are pickled dicts
            return pickle.loads(raw)
        elif base == FmtID.LOOP_CACHE:
            return pickle.loads(raw)
        else:
            # RAW_BINARY and PICKLE_OBJ
            try:
                return pickle.loads(raw)
            except Exception:
                return raw # hand back raw bytes if pickle fails

    def close(self) -> None:
        self._mm.close(); self._f.close()

    def __enter__(self) -> 'TDSReader':
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return (f"<TDSReader '{self.path.name}' "
                f"entries={len(self._idx)} "
                f"ts={self._hdr['ts']}>")

# ////////////////////////////////////////////////////////////////////////////////
#
# § 13  TDS WRITER / Atomic append writer with shadow swap ///////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class TDSWriter:
    """
    Writes a TDSDirectory tree to a .tds file atomically

    (1) Open a shadow file -> <name>.tds~
    (2) Write 44 byte file header placeholder
    (3) Walk the directory, serialize every TDSEntry into the data block
        record (name, offset, length, fmt_id) into an in-memory SlotIndex
    (4) Write the SlotIndex block immediately after the data block
    (5) Rewind to byte 0, overwrite header with real offsets + CRC
    (6) fsync -> rename shadow -> final path, atomic on posix

    **Readers never see a partial file**
    """

    def __init__(self, path: str | Path):
        self.path = Path(path); self._shadow = self.path.with_suffix('.tds~')

    def write(self, directory: TDSDirectory, recurse: bool = True) -> int:
        # Serialize directory and optionally all sub-directories
        idx = SlotIndex(); data_parts: List[bytes] = []
        cursor = 0 # running offset within data block

        def _serialize_entry(entry: TDSEntry) -> bytes:
            # Convert one TDSEntry to its on-disk payload bytes
            compress = bool(FmtID.COMPRESSED in entry.fmt_id); base_fmt = entry.fmt_id & ~FmtID.COMPRESSED
            if base_fmt == FmtID.NUMPY_MATRIX and isinstance(entry.data, np.ndarray):
                import io
                buf = io.BytesIO()
                np.save(buf, entry.data, allow_pickle=False)
                raw = buf.getvalue()
            else: raw = pickle.dumps(entry.data, protocol=5)
            if compress: raw = zlib.compress(raw, level=3)
            return raw

        def _walk(node: TDSDirectory) -> None:
            nonlocal cursor
            with node._lock:
                entries = list(node._entries.values()); children = list(node._children.values())
            for entry in entries:
                payload = _serialize_entry(entry)
                h = zlib.adler32(entry.name.encode()) & 0x7FFFFFFFFFFFFFFF
                idx.add(SlotRecord(name = entry.name, name_hash = h, offset = cursor, length = len(payload), fmt_id = int(entry.fmt_id),))
                data_parts.append(payload); cursor += len(payload)
            if recurse:
                for child in children: _walk(child)
        _walk(directory)
        data_block = b''.join(data_parts); index_block = idx.to_bytes()
        data_offset = FILE_HDR_SIZE; index_offset = data_offset + len(data_block); slot_count = len(idx)
        file_header = _build_file_header(slot_count, index_offset, data_offset)
        with open(self._shadow, 'wb', buffering=1 << 20) as f:
            f.write(file_header); f.write(data_block); f.write(index_block); f.flush(); os.fsync(f.fileno())
        # Atomic rename(POSIX) or replace(Windows)
        shutil.move(str(self._shadow), str(self.path))
        total = FILE_HDR_SIZE + len(data_block) + len(index_block)
        return total

    def write_parallel(self, directory: TDSDirectory, num_workers: int = 4) -> int:
        # Serialize entries in parallel (ThreadPool), then write sequentially
        with directory._lock: entries = list(directory._entries.values())
        pool = ConcurrencyPool.acquire()

        def _ser(entry: TDSEntry) -> Tuple[TDSEntry, bytes]:
            compress = bool(FmtID.COMPRESSED in entry.fmt_id)
            base_fmt = entry.fmt_id & ~FmtID.COMPRESSED
            if base_fmt == FmtID.NUMPY_MATRIX and isinstance(entry.data, np.ndarray):
                import io
                buf = io.BytesIO()
                np.save(buf, entry.data, allow_pickle=False)
                raw = buf.getvalue()
            else: raw = pickle.dumps(entry.data, protocol=5)
            if compress: raw = zlib.compress(raw, level=3)
            return (entry, raw)
        serialized = pool.map_parallel(_ser, entries)
        idx = SlotIndex(); data_parts = []; cursor = 0
        for entry, payload in serialized:
            h = zlib.adler32(entry.name.encode()) & 0x7FFFFFFFFFFFFFFF
            idx.add(SlotRecord(name=entry.name, name_hash=h, offset=cursor, length=len(payload), fmt_id=int(entry.fmt_id)))
            data_parts.append(payload); cursor += len(payload)
        data_block   = b''.join(data_parts); index_block  = idx.to_bytes(); data_offset  = FILE_HDR_SIZE
        index_offset = data_offset + len(data_block)
        file_header  = _build_file_header(len(idx), index_offset, data_offset)
        with open(self._shadow, 'wb', buffering=1 << 20) as f:
            f.write(file_header); f.write(data_block); f.write(index_block); f.flush(); os.fsync(f.fileno())
        shutil.move(str(self._shadow), str(self.path))
        return FILE_HDR_SIZE + len(data_block) + len(index_block)

# ////////////////////////////////////////////////////////////////////////////////
#
# § 14  TDS PERSISTENCE / Mount/unmount/flush bridge FS <-> disk /////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class TDSPersistence:
    # Mounts a TDSFileSystem to a directory on the real filesystem
    # Each TDSDirectory node maps to one .tds file:
    # /asi_root/databases/vectors -> <mount_dir>/databases__vectors.tds
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # flush()      write all dirty nodes to disk
    # load()       read a .tds file back into a TDSDirectory
    # mount()      attach a TDSFileSystem to a mount point
    # unmount()    flush everything and release file handles
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def __init__(self, mount_dir: str | Path):
        self.mount_dir = Path(mount_dir)
        self.mount_dir.mkdir(parents=True, exist_ok=True)
        self._readers: Dict[str, TDSReader] = {}
        self._lock = threading.Lock()
        self._fs: Optional[TDSFileSystem] = None

    def _node_path_to_filename(self, node_path: str) -> Path:
        # '/asi_root/databases/vectors' -> '<mount>/asi_root__databases__vectors.tds'
        # Replaces '/' with '__' so one flat directory holds everything
        safe = node_path.strip('/').replace('/', '__')
        return self.mount_dir / f"{safe}.tds"

    def flush_node(self, node: TDSDirectory, parallel: bool = False) -> Tuple[str, int]:
        # Write a single directory node to its .tds file
        fpath = self._node_path_to_filename(node.path()); writer = TDSWriter(fpath)
        if parallel: nbytes = writer.write_parallel(node)
        else: nbytes = writer.write(node, recurse=False)
        return str(fpath), nbytes

    def flush(self, fs: TDSFileSystem, parallel_nodes: bool = True) -> Dict[str, int]:
        # Walk every node in the FS tree & flush to disk
        # If parallel_nodes=True, nodes are flushed concurrently
        # Returns {filepath: bytes_written}
        nodes: List[TDSDirectory] = []

        def _collect(node: TDSDirectory) -> None:
            nodes.append(node)
            with node._lock: children = list(node._children.values())
            for child in children: _collect(child)
        _collect(fs.root)
        pool = ConcurrencyPool.acquire()

        def _flush_one(node: TDSDirectory) -> Tuple[str, int]:
            return self.flush_node(node, parallel=False)

        if parallel_nodes: results = pool.map_parallel(_flush_one, nodes)
        else: results = [_flush_one(n) for n in nodes]
        return dict(results)

    def load_node(self, tds_path: str | Path, into: Optional[TDSDirectory] = None) -> TDSDirectory:
        # Read a .tds file from disk & populate a TDSDirectory
        # If 'into' is None -> creates new root-level TDSDirectory
        tds_path = Path(tds_path); reader = TDSReader(tds_path)
        # Derive node name from filename
        stem = tds_path.stem; name = stem.split('__')[-1]
        if into is None: into = TDSDirectory(name=name)
        # Keep reader open for lazy mmap reads
        with self._lock: self._readers[str(tds_path)] = reader
        for entry_name in reader.keys():
            slot = reader._idx.lookup(entry_name)
            if slot is None:
                continue
            # Create a lightweight TDSEntry with deferred read
            entry = _LazyEntry(name = entry_name, fmt_id  = FmtID(slot.fmt_id), reader  = reader,)
            # Inject as a real TDSEntry placeholder; data loaded on .data access
            into._entries[entry_name] = entry
        return into

    def mount(self, fs: TDSFileSystem) -> None:
        # Attach a TDSFileSystem; makes this persistence object the FS's backing store
        self._fs = fs

    def unmount(self) -> Dict[str, int]:
        # Flush all dirty nodes, close all readers, return bytes written per file
        if self._fs is None:
            return {}
        result = self.flush(self._fs)
        with self._lock:
            for reader in self._readers.values(): reader.close()
            self._readers.clear()
        self._fs = None
        return result

    def open_readers(self, paths: List[str | Path]) -> List[TDSReader]:
        readers = []
        pool = ConcurrencyPool.acquire()
        
        def _open(p):
            r = TDSReader(p)
            with self._lock: self._readers[str(p)] = r
            return r
        readers = pool.map_parallel(_open, paths)
        return readers

    def __repr__(self) -> str:
        return (f"<TDSPersistence mount='{self.mount_dir}' "
                f"open_readers={len(self._readers)}>")

# ////////////////////////////////////////////////////////////////////////////////
#
# § 14b  LAZY ENTRY / Deferred mmap read /////////////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class _LazyEntry:
    # Placeholder injected into TDSDirectory._entries when loading from disk
    # Actual payload is read from the mmap only on first .data access

    def __init__(self, name: str, fmt_id: FmtID, reader: TDSReader):
        self.name = name
        self.fmt_id = fmt_id
        self._reader = reader
        self._data = None
        self._loaded = False
        self._lock = threading.Lock()
        self.entry_id = f"lazy:{name}"
        self.ts_written = 0

    @property
    def data(self) -> Any:
        with self._lock:
            if not self._loaded:
                self._data = self._reader.read(self.name); self._loaded = True
        return self._data

    def serialize(self) -> bytes:
        # Delegate to reader for raw bytes, no re-serialization needed
        return self._reader.read_raw(self.name)

# ////////////////////////////////////////////////////////////////////////////////
#
# § 15  PARALLEL FLUSHER / Concurrent multi-file flush ///////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

class ParallelFlusher:
    """
    Schedules flush of multiple TDSDirectory nodes concurrently

        >> flusher = ParallelFlusher(mount_dir="/var/tds")
        >> flusher.enqueue(node_a)
        >> flusher.enqueue(node_b)
        >> report = flusher.flush_all()
    """

    def __init__(self, mount_dir: str | Path):
        self._persist = TDSPersistence(mount_dir)
        self._queue: List[TDSDirectory] = []
        self._lock = threading.Lock()

    def enqueue(self, node: TDSDirectory) -> None:
        with self._lock: self._queue.append(node)

    def flush_all(self, parallel: bool = True) -> Dict[str, int]:
        with self._lock:
            nodes = list(self._queue); self._queue.clear()
        pool = ConcurrencyPool.acquire()

        def _flush(node: TDSDirectory) -> Tuple[str, int]:
            return self._persist.flush_node(node)

        if parallel: results = pool.map_parallel(_flush, nodes)
        else: results = [_flush(n) for n in nodes]

        return dict(results)


# ////////////////////////////////////////////////////////////////////////////////
#
# § 16  Staqtapp-TDS DEMO(PERSISTENCE)////////////////////////////////////////////
#
# ////////////////////////////////////////////////////////////////////////////////

def demo():
    import tempfile
    print("═" * 64)
    print("  TDS PERSISTENCE LAYER — disk write + seek read demo")
    print("═" * 64)

    # Build an in-memory FS
    fs = TDSFileSystem("asi_root")
    vec_db = fs.makedirs("databases/vectors", fmt_id=FmtID.NUMPY_MATRIX, flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
    sym_db = fs.makedirs("databases/symbols", fmt_id=FmtID.SYMBOL_TABLE)
    logs = fs.makedirs("logs/audit")

    # Populate with data
    for i in range(6):
        mat = np.random.randn(64, 64).astype(np.float32)
        vec_db.write(f"embed_{i:04d}", mat, fmt_id=FmtID.NUMPY_MATRIX, compress=True)
    sym_db.symbols.intern("NULL")
    sym_db.symbols.intern("TOKEN_A")
    sym_db.symbols.intern("TOKEN_B")
    tok = np.zeros((4, 4))
    swapped = sym_db.symbols.swap("NULL", "TOKEN_A", tok.copy())
    sym_db.write("token_v1", swapped, fmt_id=FmtID.SYMBOL_TABLE)
    sym_db.write("token_v2", tok,     fmt_id=FmtID.SYMBOL_TABLE)
    for i in range(8):
        logs.write(f"event_{i:04d}", {"ts": time.time_ns(), "level": "INFO", "msg": f"op_{i}"}, fmt_id=FmtID.PICKLE_OBJ)

    # Flush to a temp directory
    with tempfile.TemporaryDirectory(prefix="tds_demo_") as tdir:
        print(f"\n>  Mount point: {tdir}")
        persist = TDSPersistence(tdir); persist.mount(fs)
        print(">  Flushing all nodes to disk (parallel)...")
        report = persist.flush(fs, parallel_nodes=True)
        for fpath, nb in report.items():
            fname = Path(fpath).name; print(f"   {fname:55s}  {nb:>8,} bytes")

        # List what landed on disk
        tds_files = sorted(Path(tdir).glob("*.tds"))
        print(f"\n>  .tds files on disk: {len(tds_files)}")
        for f in tds_files: print(f"   {f.name}  ({f.stat().st_size:,} bytes)")

        # Random access reads via TDSReader
        vec_file = next(f for f in tds_files if "vectors" in f.name)
        print(f"\n>  Opening reader for {vec_file.name!r}...")
        with TDSReader(vec_file) as reader:
            print(f"   Keys in file: {reader.keys()}")
            
            # Single seek-based read
            mat = reader.read("embed_0000")
            print(f"   embed_0000  shape={mat.shape}  dtype={mat.dtype}  "
                  f"mean={mat.mean():.4f}")
            # Parallel multi-entry read
            print("> Parallel read of all 6 embeddings...")
            t0  = time.perf_counter()
            all_mats = reader.read_many(reader.keys())
            dt  = (time.perf_counter() - t0) * 1000
            print(f"   {len(all_mats)} matrices read in {dt:.2f} ms")
            for k, v in all_mats.items():
                print(f"   {k}  shape={v.shape}  sum={v.sum():.3f}")

        # SlotIndex binary search verification
        print("\n>  SlotIndex Numba binary-search verification...")
        with TDSReader(vec_file) as reader:
            for key in ["embed_0000", "embed_0003", "embed_0005"]:
                rec = reader._idx.lookup(key)
                print(f"   {key:15s}  offset={rec.offset:>8,}  "
                      f"length={rec.length:>8,}  hash=0x{rec.name_hash:016X}")

        # Load a .tds file back into a TDSDirectory
        print("\n> Loading logs .tds back into TDSDirectory...")
        log_file = next(f for f in tds_files if "logs__audit" in f.name)
        persist2 = TDSPersistence(tdir)
        loaded = persist2.load_node(log_file)
        print(f"   Loaded node: {loaded.name!r}  entries={len(loaded._entries)}")
        # Trigger lazy load of one entry
        first_key = list(loaded._entries.keys())[0]
        val = loaded.read(first_key)
        print(f"   Lazy-loaded '{first_key}': {val}")

        # Parallel flusher
        print("\n>  ParallelFlusher: enqueue + flush_all...")
        flusher = ParallelFlusher(tdir)
        with fs.root._lock: nodes = list(fs.root._children.values())
        for node in nodes: flusher.enqueue(node)
        flush_report = flusher.flush_all(parallel=True)
        print(f"   Flushed {len(flush_report)} nodes simultaneously")
        persist.unmount()
    print("\n>  Persistence demo complete.")

if __name__ == '__main__':
    demo()

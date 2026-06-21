"""
Updated 6-20-26, several critical & minor issues fixed

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
>>> Staqtapp-TDS 1.1.188 / tds_persistence.py
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
import json
import mmap
import os
import shutil
import struct
import threading
import time
import zlib
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from staqtapp_tds.tds_filesystem import (TDSDirectory, TDSEntry, TDSFileSystem, FmtID, DirFlags, ConcurrencyPool, decode_header, encode_header, _compute_subdir_offsets, _serialize_payload, _deserialize_payload, HEADER_SIZE, TDS_MAGIC,)

try:
    from numba import njit, prange
    _NUMBA = True
except ImportError:
    def njit(*a, **kw):
        def d(fn): return fn
        return d(a[0]) if a and callable(a[0]) else d
    prange = range; _NUMBA = False

# ////////////////////////////////////////////////////////////////////////////////
# § 10  FILE-LEVEL CONSTANTS
# ////////////////////////////////////////////////////////////////////////////////

FILE_MAGIC = b'TDSX'
FILE_VERSION = 1
FILE_HDR_FMT = '>4sIQQQQI'
FILE_HDR_SIZE = struct.calcsize(FILE_HDR_FMT) # 44 bytes
SLOT_FIXED_FMT = '>QQIHH'
SLOT_FIXED_SIZE = struct.calcsize(SLOT_FIXED_FMT) # 24 bytes

def _build_file_header(slot_count: int, index_offset: int, data_offset: int) -> bytes:
    ts  = int(time.time_ns())
    raw = struct.pack(FILE_HDR_FMT, FILE_MAGIC, FILE_VERSION, slot_count, index_offset, data_offset, ts, 0)
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return struct.pack(FILE_HDR_FMT, FILE_MAGIC, FILE_VERSION, slot_count, index_offset, data_offset, ts, crc)

def _parse_file_header(raw: bytes) -> dict:
    if len(raw) < FILE_HDR_SIZE:
        raise ValueError("Buffer too short for TDS file header")
    magic, ver, slot_count, idx_off, data_off, ts, crc = struct.unpack(FILE_HDR_FMT, raw[:FILE_HDR_SIZE])
    if magic != FILE_MAGIC:
        raise ValueError(f"Bad file magic: {magic!r}")
    if ver != FILE_VERSION:
        raise ValueError(f"Unsupported TDS file version: {ver}")
    check = struct.pack(FILE_HDR_FMT, magic, ver, slot_count, idx_off, data_off, ts, 0)
    if (zlib.crc32(check) & 0xFFFFFFFF) != crc:
        raise ValueError("File header CRC mismatch")
    return dict(slot_count=slot_count, index_offset=idx_off, data_offset=data_off, ts=ts)

# ////////////////////////////////////////////////////////////////////////////////
# § 11  SLOT INDEX
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class SlotRecord:
    name: str
    name_hash: int
    offset: int
    length: int
    fmt_id: int

@njit(cache=True)
def _slot_binary_search(hashes: np.ndarray, target: np.int64) -> np.int64:
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
    return np.argsort(hashes)

class SlotIndex:

    def __init__(self):
        self._records: List[SlotRecord] = []
        self._hashes: Optional[np.ndarray] = None
        self._order: Optional[np.ndarray] = None
        self._dirty = True
        self._lock = threading.Lock()

    def add(self, record: SlotRecord) -> None:
        with self._lock:
            self._records.append(record); self._dirty = True

    def _rebuild(self) -> None:
        if not self._records:
            self._hashes = np.array([], dtype=np.int64)
            self._order = np.array([], dtype=np.int64)
            self._dirty = False
            return
        raw_hashes = np.array([r.name_hash for r in self._records], dtype=np.int64)
        order = _build_sorted_order(raw_hashes)
        self._hashes = raw_hashes[order]
        self._order = order; self._dirty = False

    def lookup(self, name: str) -> Optional[SlotRecord]:
        h = zlib.adler32(name.encode()) & 0x7FFFFFFFFFFFFFFF
        with self._lock:
            if self._dirty: self._rebuild()
            if self._hashes is None or len(self._hashes) == 0:
                return None
            idx = _slot_binary_search(self._hashes, np.int64(h))
            if idx >= 0:
                orig_idx = int(self._order[idx]); rec = self._records[orig_idx]
                if rec.name == name:
                    return rec
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
        parts = []
        with self._lock:
            for rec in self._records:
                nb = rec.name.encode('utf-8')
                parts.append(struct.pack(SLOT_FIXED_FMT, rec.name_hash, rec.offset, rec.length, rec.fmt_id, len(nb)) + nb)
        return b''.join(parts)

    @classmethod
    def from_bytes(cls, buf: bytes, slot_count: int) -> 'SlotIndex':
        idx = cls(); cursor = 0
        for _ in range(slot_count):
            if cursor + SLOT_FIXED_SIZE > len(buf):
                break
            name_hash, offset, length, fmt_id, name_len = struct.unpack(SLOT_FIXED_FMT, buf[cursor: cursor + SLOT_FIXED_SIZE])
            cursor += SLOT_FIXED_SIZE
            name = buf[cursor: cursor + name_len].decode('utf-8')
            cursor += name_len
            idx.add(SlotRecord(name=name, name_hash=name_hash, offset=offset, length=length, fmt_id=fmt_id))
        return idx

# ////////////////////////////////////////////////////////////////////////////////
# § 12  TDS READER
# ////////////////////////////////////////////////////////////////////////////////

class TDSReader:
    """
    Mmap random access reader for a .tds file
    
    (1) Parse 44-byte file header -> locate index + data blocks
    (2) Deserialize SlotIndex from index block
    (3) read(name): SlotIndex.lookup -> single seek into mmap -> deserialize
    
    **No full-file scan after initial index load**
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"TDS file not found: {self.path}")
        self._f = open(self.path, 'rb')
        self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        self._lock = threading.Lock(); self._hdr = self._load_header(); self._idx = self._load_index()

    def _load_header(self) -> dict:
        return _parse_file_header(bytes(self._mm[:FILE_HDR_SIZE]))

    def _load_index(self) -> SlotIndex:
        idx_off = self._hdr['index_offset']
        slot_count = self._hdr['slot_count']
        idx_bytes = bytes(self._mm[idx_off:])
        return SlotIndex.from_bytes(idx_bytes, slot_count)

    def read(self, name: str) -> Any:
        rec = self._idx.lookup(name)
        if rec is None:
            raise KeyError(f"Entry '{name}' not found in {self.path.name!r}")
        data_base = self._hdr['data_offset']; abs_off = data_base + rec.offset
        with self._lock: payload = bytes(self._mm[abs_off: abs_off + rec.length])
        return _deserialize_payload(payload, FmtID(rec.fmt_id))

    def read_raw(self, name: str) -> bytes:
        rec = self._idx.lookup(name)
        if rec is None:
            raise KeyError(name)
        data_base = self._hdr['data_offset']; abs_off = data_base + rec.offset
        with self._lock:
            return bytes(self._mm[abs_off: abs_off + rec.length])

    def read_many(self, names: List[str]) -> Dict[str, Any]:
        pool = ConcurrencyPool.acquire()

        def _one(n):
            return (n, self.read(n))

        return dict(pool.map_parallel(_one, names))

    def keys(self) -> List[str]:
        return [r.name for r in self._idx.all_records()]

    def __len__(self) -> int:
        return len(self._idx)

    def __contains__(self, name: str) -> bool:
        return self._idx.lookup(name) is not None

    def close(self) -> None:
        self._mm.close(); self._f.close()

    def __enter__(self) -> 'TDSReader':
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return (f"<TDSReader '{self.path.name}' "
                f"entries={len(self._idx)} ts={self._hdr['ts']}>")

# ////////////////////////////////////////////////////////////////////////////////
# § 13  TDS WRITER
# ////////////////////////////////////////////////////////////////////////////////

class TDSWriter:
    """
    Atomic writer: shadow file -> fsync -> rename

    FIXED - Slot keys are prefixed with the directory path so entries
            from different subdirectories with the same name don't collide
        
    FIXED - Directory metadata (flags, fmt_id, dir_id, ts_create) is
            written to a JSON sidecar (<name>.tds.meta)
        
    FIXED - Shadow file is deleted on exception (no leftover .tds~)
    
    FIXED - Uses _serialize_payload (unified path matching TDSReader)
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._shadow = self.path.with_suffix('.tds~')
        self._meta = self.path.with_suffix('.tds.meta')

    @staticmethod
    def _serialize_entry(entry: TDSEntry) -> bytes:
        # FIXED - Delegates to unified _serialize_payload
        return _serialize_payload(entry.data, entry.fmt_id)

    @staticmethod
    def _slot_key(node_path: str, entry_name: str) -> str:
        # FIXED - Prefix with node path so same-named entries in different
        return f"{node_path}/{entry_name}"

    def write(self, directory: TDSDirectory, recurse: bool = True) -> int:
        idx = SlotIndex()
        data_parts: List[bytes] = []
        cursor = 0

        def _walk(node: TDSDirectory) -> None:
            nonlocal cursor
            with node._lock:
                entries = list(node._entries.values()); children = list(node._children.values())
            for entry in entries:
                payload = self._serialize_entry(entry)
                slot_key = self._slot_key(node.path(), entry.name)
                h = zlib.adler32(slot_key.encode()) & 0x7FFFFFFFFFFFFFFF
                idx.add(SlotRecord(name=slot_key, name_hash=h, offset=cursor, length=len(payload), fmt_id=int(entry.fmt_id)))
                data_parts.append(payload); cursor += len(payload)
            if recurse:
                for child in children: _walk(child)
        _walk(directory)
        return self._finalise(idx, data_parts, directory)

    def write_parallel(self, directory: TDSDirectory) -> int:
        with directory._lock:
            entries = list(directory._entries.values())
        pool = ConcurrencyPool.acquire()

        def _ser(entry: TDSEntry) -> Tuple[TDSEntry, bytes]:
            return (entry, self._serialize_entry(entry))

        serialized = pool.map_parallel(_ser, entries)
        idx = SlotIndex(); data_parts: List[bytes] = []; cursor = 0
        for entry, payload in serialized:
            slot_key = self._slot_key(directory.path(), entry.name)
            h = zlib.adler32(slot_key.encode()) & 0x7FFFFFFFFFFFFFFF
            idx.add(SlotRecord(name=slot_key, name_hash=h, offset=cursor, length=len(payload), fmt_id=int(entry.fmt_id)))
            data_parts.append(payload); cursor += len(payload)
        return self._finalise(idx, data_parts, directory)

    def _finalise(self, idx: SlotIndex, data_parts: List[bytes], directory: TDSDirectory) -> int:
        data_block = b''.join(data_parts); index_block = idx.to_bytes()
        data_offset = FILE_HDR_SIZE; index_offset = data_offset + len(data_block)
        file_header = _build_file_header(len(idx), index_offset, data_offset)

        # FIXED - Clean up shadow file if anything goes wrong mid-write
        try:
            with open(self._shadow, 'wb', buffering=1 << 20) as f:
                f.write(file_header); f.write(data_block); f.write(index_block); f.flush()
                os.fsync(f.fileno())
            shutil.move(str(self._shadow), str(self.path))
        except Exception:
            try:
                self._shadow.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        # FIXED - Persist directory metadata in a JSON sidecar
        meta = {'flags': directory.flags, 'fmt_id': int(directory.fmt_id), 'dir_id': directory.dir_id, 'ts_create': directory._ts_create,}
        self._meta.write_text(json.dumps(meta))
        return FILE_HDR_SIZE + len(data_block) + len(index_block)

# ////////////////////////////////////////////////////////////////////////////////
# § 14  TDS PERSISTENCE
# ////////////////////////////////////////////////////////////////////////////////

class TDSPersistence:
    """
    Mounts a TDSFileSystem to a real directory
    Each TDSDirectory node -> one .tds file + one .tds.meta sidecar
    '/asi_root/databases/vectors' -> '<mount>/asi_root__databases__vectors.tds'

    FIXED - Readers are tracked and closed by close_reader() / unmount()
    """

    def __init__(self, mount_dir: str | Path):
        self.mount_dir = Path(mount_dir)
        self.mount_dir.mkdir(parents=True, exist_ok=True)
        self._readers: Dict[str, TDSReader] = {}
        self._lock = threading.Lock()
        self._fs: Optional[TDSFileSystem] = None

    def _node_path_to_filename(self, node_path: str) -> Path:
        safe = node_path.strip('/').replace('/', '__')
        return self.mount_dir / f"{safe}.tds"

    def flush_node(self, node: TDSDirectory, parallel: bool = False) -> Tuple[str, int]:
        fpath = self._node_path_to_filename(node.path()); writer = TDSWriter(fpath)
        nbytes = writer.write_parallel(node) if parallel else writer.write(node, recurse=False)
        return str(fpath), nbytes

    def flush(self, fs: TDSFileSystem, parallel_nodes: bool = True) -> Dict[str, int]:
        nodes: List[TDSDirectory] = []

        def _collect(node: TDSDirectory) -> None:
            nodes.append(node)
            with node._lock: children = list(node._children.values())
            for child in children: _collect(child)
        _collect(fs.root)
        pool = ConcurrencyPool.acquire()

        def _flush_one(node: TDSDirectory) -> Tuple[str, int]:
            return self.flush_node(node, parallel=False)

        results = pool.map_parallel(_flush_one, nodes) if parallel_nodes else [_flush_one(n) for n in nodes]
        return dict(results)

    def load_node(self, tds_path: str | Path, into: Optional[TDSDirectory] = None) -> TDSDirectory:
        """Read a .tds file from disk and populate a TDSDirectory
        FIXED - Restores flags/fmt_id/dir_id/ts_create from .tds.meta sidecar
        FIXED - Reader is tracked; call close_reader() when done
        """
        
        tds_path = Path(tds_path)
        reader = TDSReader(tds_path)
        stem = tds_path.stem
        name = stem.split('__')[-1]

        # FIXED - Restore metadata from sidecar if present
        meta_path = tds_path.with_suffix('.tds.meta')
        flags = DirFlags.NONE
        fmt_id = FmtID.RAW_BINARY
        dir_id = None
        ts_create = None
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                flags = meta.get('flags', int(DirFlags.NONE))
                fmt_id = FmtID(meta.get('fmt_id', int(FmtID.RAW_BINARY)))
                dir_id = meta.get('dir_id')
                ts_create = meta.get('ts_create')
            except Exception:
                pass

        if into is None: into = TDSDirectory(name=name, fmt_id=fmt_id, flags=flags)
        if dir_id: into.dir_id = dir_id
        if ts_create: into._ts_create = ts_create
        with self._lock: self._readers[str(tds_path)] = reader
        for entry_name in reader.keys():
            slot = reader._idx.lookup(entry_name)
            if slot is None:
                continue
            # FIXED - _LazyEntry now inherits TDSEntry properly
            entry = _LazyEntry(name = entry_name, fmt_id = FmtID(slot.fmt_id), reader = reader)
            into._entries[entry_name] = entry
        return into

    def close_reader(self, tds_path: str | Path) -> None:
        key = str(tds_path)
        with self._lock: reader = self._readers.pop(key, None)
        if reader is not None: reader.close()

    def mount(self, fs: TDSFileSystem) -> None:
        self._fs = fs

    def unmount(self) -> Dict[str, int]:
        if self._fs is None:
            return {}
        result = self.flush(self._fs)
        with self._lock:
            for reader in self._readers.values():
                reader.close()
            self._readers.clear()
        self._fs = None
        return result

    def open_readers(self, paths: List[str | Path]) -> List[TDSReader]:
        pool = ConcurrencyPool.acquire()

        def _open(p):
            r = TDSReader(p)
            with self._lock: self._readers[str(p)] = r
            return r

        return pool.map_parallel(_open, paths)

    def __repr__(self) -> str:
        return (f"<TDSPersistence mount='{self.mount_dir}' "
                f"open_readers={len(self._readers)}>")

# ////////////////////////////////////////////////////////////////////////////////
# § 14b  LAZY ENTRY
# ////////////////////////////////////////////////////////////////////////////////

class _LazyEntry(TDSEntry):
    """
    Deferred load entry injected into TDSDirectory._entries when loading from disk
    FIXED - Now a proper TDSEntry subclass so serialise() and isinstance
            checks will work correctly
    """

    def __init__(self, name: str, fmt_id: FmtID, reader: TDSReader):
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'fmt_id', fmt_id)
        object.__setattr__(self, 'data', None) # populated on first access
        object.__setattr__(self, 'ts_written', 0)
        object.__setattr__(self, 'entry_id', f"lazy:{name}")
        object.__setattr__(self, '_reader', reader)
        object.__setattr__(self, '_loaded', False)
        object.__setattr__(self, '_lazy_lock', threading.Lock())

    # Intercept .data to trigger the lazy load
    def __getattribute__(self, item: str) -> Any:
        if item == 'data':
            lock = object.__getattribute__(self, '_lazy_lock')
            with lock:
                if not object.__getattribute__(self, '_loaded'):
                    reader = object.__getattribute__(self, '_reader')
                    name   = object.__getattribute__(self, 'name')
                    object.__setattr__(self, 'data', reader.read(name))
                    object.__setattr__(self, '_loaded', True)
            return object.__getattribute__(self, 'data')
        return object.__getattribute__(self, item)

    def serialise(self) -> bytes:
        # FIXED - Consistent spelling; delegates to reader for raw bytes
        reader = object.__getattribute__(self, '_reader')
        name = object.__getattribute__(self, 'name')
        raw = reader.read_raw(name)
        return struct.pack('>I', len(raw)) + raw

# ////////////////////////////////////////////////////////////////////////////////
# § 15  PARALLEL FLUSHER
# ////////////////////////////////////////////////////////////////////////////////

class ParallelFlusher:
    """
    Schedules concurrent flush of multiple TDSDirectory nodes

        flusher = ParallelFlusher(mount_dir="/var/tds")
        flusher.enqueue(node_a)
        flusher.enqueue(node_b)
        report = flusher.flush_all()
    """

    def __init__(self, mount_dir: str | Path):
        self._persist = TDSPersistence(mount_dir)
        self._queue:  List[TDSDirectory] = []
        self._lock = threading.Lock()

    def enqueue(self, node: TDSDirectory) -> None:
        with self._lock: self._queue.append(node)

    def flush_all(self, parallel: bool = True) -> Dict[str, int]:
        with self._lock:
            nodes = list(self._queue); self._queue.clear()
        pool = ConcurrencyPool.acquire()

        def _flush(node: TDSDirectory) -> Tuple[str, int]:
            return self._persist.flush_node(node)

        results = pool.map_parallel(_flush, nodes) if parallel \
                  else [_flush(n) for n in nodes]
        return dict(results)

# ////////////////////////////////////////////////////////////////////////////////
# § 16  DEMO
# ////////////////////////////////////////////////////////////////////////////////

def demo():
    import tempfile
    print("═" * 64)
    print("  TDS PERSISTENCE — disk write + seek read demo")
    print("═" * 64)
    fs     = TDSFileSystem("asi_root")
    vec_db = fs.makedirs("databases/vectors", fmt_id=FmtID.NUMPY_MATRIX, flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)
    sym_db = fs.makedirs("databases/symbols", fmt_id=FmtID.SYMBOL_TABLE)
    logs   = fs.makedirs("logs/audit")
    for i in range(6):
        mat = np.random.randn(64, 64).astype(np.float32)
        vec_db.write(f"embed_{i:04d}", mat, fmt_id=FmtID.NUMPY_MATRIX, compress=True)
    sym_db.symbols.intern("NULL")
    sym_db.symbols.intern("TOKEN_A")
    sym_db.symbols.intern("TOKEN_B")
    tok = np.zeros((4, 4))
    swapped = sym_db.symbols.swap("NULL", "TOKEN_A", tok.copy())
    sym_db.write("token_v1", swapped, fmt_id=FmtID.SYMBOL_TABLE)
    sym_db.write("token_v2", tok, fmt_id=FmtID.SYMBOL_TABLE)
    for i in range(8):
        logs.write(f"event_{i:04d}", {"ts": time.time_ns(), "level": "INFO", "msg": f"op_{i}"}, fmt_id=FmtID.PICKLE_OBJ)
    with tempfile.TemporaryDirectory(prefix="tds_demo_") as tdir:
        print(f"\n>  Mount point: {tdir}")
        persist = TDSPersistence(tdir)
        persist.mount(fs)
        print(">  Flushing all nodes (parallel)...")
        report = persist.flush(fs, parallel_nodes=True)
        for fpath, nb in report.items():
            fname = Path(fpath).name
            print(f"   {fname:55s}  {nb:>8,} bytes")
        tds_files = sorted(Path(tdir).glob("*.tds"))
        print(f"\n>  .tds files on disk: {len(tds_files)}")
        for f in tds_files: print(f"   {f.name}  ({f.stat().st_size:,} bytes)")
        # Verify metadata sidecar round-trip
        meta_files = sorted(Path(tdir).glob("*.tds.meta"))
        print(f"\n>  Metadata sidecars: {len(meta_files)}")
        for mf in meta_files: print(f"   {mf.name}: {mf.read_text()}")
        # Random-access reads
        vec_file = next(f for f in tds_files if "vectors" in f.name)
        print(f"\n>  Opening reader for {vec_file.name!r}...")
        with TDSReader(vec_file) as reader:
            print(f"   Keys: {reader.keys()}")
            # Keys are path-prefixed (Bug5 fix); read using full slot key
            first_key = reader.keys()[0]
            mat = reader.read(first_key)
            print(f"   {first_key}  shape={mat.shape}  mean={mat.mean():.4f}")
            print(">  Parallel read of all embeddings...")
            t0       = time.perf_counter()
            all_mats = reader.read_many(reader.keys())
            dt       = (time.perf_counter() - t0) * 1000
            print(f"   {len(all_mats)} matrices read in {dt:.2f} ms")
        # SlotIndex lookup verification
        print("\n>  SlotIndex binary-search check...")
        with TDSReader(vec_file) as reader:
            for key in reader.keys()[:3]:
                rec = reader._idx.lookup(key)
                print(f"   {key[:40]:40s}  off={rec.offset:>8,}  "
                      f"len={rec.length:>6,}  hash=0x{rec.name_hash:016X}")
        # Lazy-load from disk
        print("\n>  Loading logs .tds back into TDSDirectory...")
        log_file = next(f for f in tds_files if "logs__audit" in f.name)
        persist2 = TDSPersistence(tdir)
        loaded   = persist2.load_node(log_file)
        print(f"   Node: {loaded.name!r}  flags={loaded.flags}"
              f"  entries={len(loaded._entries)}")
        first_key = list(loaded._entries.keys())[0]
        val = loaded.read(first_key)
        print(f"   Lazy-loaded '{first_key}': {val}")
        persist2.close_reader(log_file)   # FIX Bug29: explicit close
        # ParallelFlusher
        print("\n>  ParallelFlusher enqueue + flush_all...")
        flusher = ParallelFlusher(tdir)
        with fs.root._lock: nodes = list(fs.root._children.values())
        for node in nodes: flusher.enqueue(node)
        flush_report = flusher.flush_all(parallel=True)
        print(f"   Flushed {len(flush_report)} nodes")
        persist.unmount()
    print("\n>  Persistence demo complete.")

if __name__ == '__main__':
    demo()


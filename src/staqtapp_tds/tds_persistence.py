"""TDS persistence, slot index, reader, writer, and parallel flush support.

Persistence is content-neutral and records compact metadata for entries while
leaving higher-level workflow semantics to optional modules.
"""

from __future__ import annotations
import mmap
import base64
import os
import shutil
import struct
import threading
import time
import zlib
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from staqtapp_tds._binary_io import open_binary_fd
from staqtapp_tds.tds_filesystem import (
    TDSDirectory, TDSEntry, TDSFileSystem, FmtID, DirFlags, ConcurrencyPool,
    decode_header, encode_header, _compute_subdir_offsets,
    _serialize_payload, _deserialize_payload, HEADER_SIZE, TDS_MAGIC,
    CompressorRegistry,
)
from staqtapp_tds.manifest import ManifestPolicy, load_manifest, write_default_manifest
from staqtapp_tds.tds_json import dumps_canonical, loads_strict
from staqtapp_tds.result import TDSResult, TDSResultCode
from staqtapp_tds.telemetry import TelemetryMode
from staqtapp_tds.serializers import content_hash_bytes

try:
    from numba import njit, prange
    _NUMBA = True
except ImportError:
    def njit(*a, **kw):
        def d(fn): return fn
        return d(a[0]) if a and callable(a[0]) else d
    prange = range
    _NUMBA = False

# ////////////////////////////////////////////////////////////////////////////////
# § 10  FILE-LEVEL CONSTANTS
# ////////////////////////////////////////////////////////////////////////////////

FILE_MAGIC       = b'TDSX'
FILE_VERSION     = 2
FILE_HDR_FMT     = '>4sIQQQQI'
FILE_HDR_SIZE    = struct.calcsize(FILE_HDR_FMT)    # 44 bytes
SLOT_FIXED_FMT   = '>QQIHH'
SLOT_FIXED_SIZE  = struct.calcsize(SLOT_FIXED_FMT)  # 24 bytes
_DETACH_READER_SNAPSHOTS = os.name == 'nt'


class TDSPersistenceIntegrityError(ValueError):
    """Typed fail-closed persistence-integrity error.

    Constructor/open paths still raise, preserving the existing hard-failure
    contract for corrupt files, while read_result() can surface the stable
    TDSResultCode carried here.
    """

    def __init__(self, code: TDSResultCode | str, message: str, **meta: Any):
        super().__init__(message)
        self.code = code
        self.meta = dict(meta)


def _raise_integrity(code: TDSResultCode | str, message: str, **meta: Any) -> None:
    raise TDSPersistenceIntegrityError(code, message, **meta)


def _write_all(fd: int, data: bytes | bytearray | memoryview) -> None:
    view = memoryview(data)
    total = len(view)
    written = 0
    while written < total:
        n = os.write(fd, view[written:])
        if n <= 0:
            _raise_integrity(TDSResultCode.PERSIST_WRITE_ERROR, "Short write while emitting TDS persistence file", written=written, expected=total)
        written += n


def _fsync_parent_dir(path: Path) -> None:
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        # Parent directory fsync is best-effort on platforms that do not permit it.
        pass


def _build_file_header(slot_count: int, index_offset: int,
                       data_offset: int) -> bytes:
    ts  = int(time.time_ns())
    raw = struct.pack(FILE_HDR_FMT, FILE_MAGIC, FILE_VERSION,
                      slot_count, index_offset, data_offset, ts, 0)
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return struct.pack(FILE_HDR_FMT, FILE_MAGIC, FILE_VERSION,
                       slot_count, index_offset, data_offset, ts, crc)


def _parse_file_header(raw: bytes) -> dict:
    if len(raw) < FILE_HDR_SIZE:
        raise ValueError("Buffer too short for TDS file header")
    magic, ver, slot_count, idx_off, data_off, ts, crc = \
        struct.unpack(FILE_HDR_FMT, raw[:FILE_HDR_SIZE])
    if magic != FILE_MAGIC:
        raise ValueError(f"Bad file magic: {magic!r}")
    if ver not in (1, FILE_VERSION):
        raise ValueError(f"Unsupported TDS file version: {ver}")
    check = struct.pack(FILE_HDR_FMT, magic, ver, slot_count,
                        idx_off, data_off, ts, 0)
    if (zlib.crc32(check) & 0xFFFFFFFF) != crc:
        raise ValueError("File header CRC mismatch")
    return dict(version=ver, slot_count=slot_count, index_offset=idx_off,
                data_offset=data_off, ts=ts)


# ////////////////////////////////////////////////////////////////////////////////
# § 10b  NUMBA KERNELS FOR PERSISTENCE
# ////////////////////////////////////////////////////////////////////////////////

@njit(cache=True)
def _pack_slot_fixed_batch(name_hashes: np.ndarray,
                           offsets:     np.ndarray,
                           lengths:     np.ndarray,
                           fmt_ids:     np.ndarray,
                           name_lens:   np.ndarray,
                           out:         np.ndarray) -> None:
    """
    JIT-pack the 24-byte fixed header for every SlotRecord into `out`.
    out must be pre-allocated: shape (n * SLOT_FIXED_SIZE,), dtype uint8.

    Field layout per slot (big-endian):
        name_hash  8B  uint64
        offset     8B  uint64
        length     4B  uint32
        fmt_id     2B  uint16
        name_len   2B  uint16

    NEW — eliminates per-slot struct.pack() Python call in to_bytes().
    """
    n = name_hashes.shape[0]
    for i in range(n):
        base = i * 24   # SLOT_FIXED_SIZE
        # name_hash  (8 bytes, big-endian uint64)
        h = name_hashes[i]
        out[base + 0] = (h >> np.uint64(56)) & np.uint64(0xFF)
        out[base + 1] = (h >> np.uint64(48)) & np.uint64(0xFF)
        out[base + 2] = (h >> np.uint64(40)) & np.uint64(0xFF)
        out[base + 3] = (h >> np.uint64(32)) & np.uint64(0xFF)
        out[base + 4] = (h >> np.uint64(24)) & np.uint64(0xFF)
        out[base + 5] = (h >> np.uint64(16)) & np.uint64(0xFF)
        out[base + 6] = (h >> np.uint64(8))  & np.uint64(0xFF)
        out[base + 7] =  h                   & np.uint64(0xFF)
        # offset  (8 bytes)
        o = offsets[i]
        out[base + 8]  = (o >> np.uint64(56)) & np.uint64(0xFF)
        out[base + 9]  = (o >> np.uint64(48)) & np.uint64(0xFF)
        out[base + 10] = (o >> np.uint64(40)) & np.uint64(0xFF)
        out[base + 11] = (o >> np.uint64(32)) & np.uint64(0xFF)
        out[base + 12] = (o >> np.uint64(24)) & np.uint64(0xFF)
        out[base + 13] = (o >> np.uint64(16)) & np.uint64(0xFF)
        out[base + 14] = (o >> np.uint64(8))  & np.uint64(0xFF)
        out[base + 15] =  o                   & np.uint64(0xFF)
        # length  (4 bytes)
        l_ = lengths[i]
        out[base + 16] = (l_ >> np.uint32(24)) & np.uint32(0xFF)
        out[base + 17] = (l_ >> np.uint32(16)) & np.uint32(0xFF)
        out[base + 18] = (l_ >> np.uint32(8))  & np.uint32(0xFF)
        out[base + 19] =  l_                   & np.uint32(0xFF)
        # fmt_id  (2 bytes)
        f = fmt_ids[i]
        out[base + 20] = (f >> np.uint16(8)) & np.uint16(0xFF)
        out[base + 21] =  f                  & np.uint16(0xFF)
        # name_len  (2 bytes)
        nl = name_lens[i]
        out[base + 22] = (nl >> np.uint16(8)) & np.uint16(0xFF)
        out[base + 23] =  nl                  & np.uint16(0xFF)


# ////////////////////////////////////////////////////////////////////////////////
# § 11  SLOT INDEX
# ////////////////////////////////////////////////////////////////////////////////

@dataclass
class SlotRecord:
    name:      str
    name_hash: int
    offset:    int
    length:    int
    fmt_id:    int


@dataclass(frozen=True)
class SnapshotSlot:
    slot_key: str
    short_name: str
    payload: bytes
    fmt_id: int
    payload_kind: str = ''
    content_hash: str = ''
    raw_size: int = 0
    stored_size: int = 0
    codec: str = ''


class SlotIndex:
    """
    O(1) slot lookup via dict primary path.

    to_bytes() uses _pack_slot_fixed_batch (JIT) for the 24-byte fixed
    header portion of every record; name bytes appended in Python.
    from_bytes() uses a memoryview to avoid redundant copies.
    """

    def __init__(self):
        self._records:  List[SlotRecord]       = []
        self._by_name:  Dict[str, SlotRecord]  = {}
        self._lock      = threading.Lock()

    def add(self, record: SlotRecord) -> None:
        with self._lock:
            self._records.append(record)
            self._by_name[record.name] = record


    def lookup(self, name: str) -> Optional[SlotRecord]:
        with self._lock:
            return self._by_name.get(name)

    def all_records(self) -> List[SlotRecord]:
        with self._lock:
            return list(self._records)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def to_bytes(self) -> bytes:
        """
        JIT kernel fills fixed 24-byte headers in one pass;
        Python only appends variable-length name bytes.
        """
        with self._lock:
            records = list(self._records)

        n = len(records)
        if n == 0:
            return b''

        name_bytes = [r.name.encode('utf-8') for r in records]
        for r, nb in zip(records, name_bytes):
            if len(nb) > 0xFFFF:
                raise ValueError(f"Slot name too long for TDS v1 slot: {r.name!r}")
            if r.length > 0xFFFFFFFF:
                raise ValueError(f"Slot payload too large for TDS v1 slot: {r.name!r}")
            if r.offset > 0xFFFFFFFFFFFFFFFF:
                raise ValueError(f"Slot offset too large for TDS v1 slot: {r.name!r}")
            if r.fmt_id > 0xFFFF:
                raise ValueError(f"Slot fmt_id out of range for TDS v1 slot: {r.name!r}")

        # Build numpy arrays for JIT kernel
        name_hashes = np.array([r.name_hash for r in records], dtype=np.uint64)
        offsets_arr = np.array([r.offset    for r in records], dtype=np.uint64)
        lengths_arr = np.array([r.length    for r in records], dtype=np.uint32)
        fmt_ids_arr = np.array([r.fmt_id    for r in records], dtype=np.uint16)
        name_lens   = np.array([len(nb) for nb in name_bytes], dtype=np.uint16)

        # JIT-fill fixed headers
        fixed_buf = np.zeros(n * SLOT_FIXED_SIZE, dtype=np.uint8)
        _pack_slot_fixed_batch(name_hashes, offsets_arr, lengths_arr,
                               fmt_ids_arr, name_lens, fixed_buf)

        # Interleave fixed headers with name bytes
        parts: List[bytes] = []
        fb    = fixed_buf.tobytes()
        for i, nb in enumerate(name_bytes):
            base = i * SLOT_FIXED_SIZE
            parts.append(fb[base: base + SLOT_FIXED_SIZE])
            parts.append(nb)
        return b''.join(parts)

    @classmethod
    def from_bytes(cls, buf: bytes, slot_count: int) -> 'SlotIndex':
        """Parse a v1 slot index with fail-closed structural validation.

        Older builds silently stopped when a fixed record was missing and sliced
        whatever name bytes were available.  That let truncated indexes expose
        malformed keys.  The hardening contract is exact: every declared slot
        must parse, every variable name byte must exist, the name_hash must
        match the key, names must be unique, and no trailing bytes are accepted.
        """
        idx = cls()
        mv = memoryview(buf)
        cursor = 0
        seen: set[str] = set()
        for record_no in range(int(slot_count)):
            if cursor + SLOT_FIXED_SIZE > len(mv):
                _raise_integrity(
                    TDSResultCode.PERSIST_INDEX_CORRUPT,
                    "Incomplete fixed slot header in TDS index",
                    record_no=record_no, cursor=cursor, available=len(mv),
                    expected_slot_count=int(slot_count), parsed_count=len(idx),
                )
            name_hash, offset, length, fmt_id, name_len = struct.unpack_from(
                SLOT_FIXED_FMT, mv, cursor)
            cursor += SLOT_FIXED_SIZE
            if cursor + int(name_len) > len(mv):
                _raise_integrity(
                    TDSResultCode.PERSIST_INDEX_CORRUPT,
                    "Incomplete variable slot-name bytes in TDS index",
                    record_no=record_no, cursor=cursor, name_len=int(name_len), available=len(mv),
                )
            raw_name = bytes(mv[cursor: cursor + int(name_len)])
            cursor += int(name_len)
            try:
                name = raw_name.decode('utf-8')
            except UnicodeDecodeError as exc:
                _raise_integrity(
                    TDSResultCode.PERSIST_INDEX_CORRUPT,
                    "Slot name is not valid UTF-8",
                    record_no=record_no, exception_type=type(exc).__name__, exception_message=str(exc),
                )
            expected_hash = zlib.adler32(raw_name) & 0x7FFFFFFFFFFFFFFF
            if int(name_hash) != int(expected_hash):
                _raise_integrity(
                    TDSResultCode.PERSIST_INDEX_CORRUPT,
                    "Slot name_hash mismatch",
                    record_no=record_no, name=name, stored_hash=int(name_hash), expected_hash=int(expected_hash),
                )
            if name in seen:
                _raise_integrity(
                    TDSResultCode.PERSIST_INDEX_CORRUPT,
                    "Duplicate slot name in TDS index",
                    record_no=record_no, name=name,
                )
            seen.add(name)
            idx.add(SlotRecord(name=name, name_hash=int(name_hash),
                               offset=int(offset), length=int(length), fmt_id=int(fmt_id)))
        if cursor != len(mv):
            _raise_integrity(
                TDSResultCode.PERSIST_INDEX_CORRUPT,
                "Trailing bytes after declared TDS slot index",
                parsed_count=len(idx), trailing_bytes=len(mv) - cursor,
            )
        if len(idx) != int(slot_count):
            _raise_integrity(
                TDSResultCode.PERSIST_INDEX_CORRUPT,
                "Parsed slot count does not match file header",
                parsed_count=len(idx), expected_slot_count=int(slot_count),
            )
        return idx


# ////////////////////////////////////////////////////////////////////////////////
# § 12  TDS READER
# ////////////////////////////////////////////////////////////////////////////////

class TDSReader:
    """
    Random-access reader for a .tds file.

    POSIX readers retain the file-backed mmap fast path. Windows readers detach
    an immutable byte snapshot and close the source file before validation so
    an atomic writer can replace the path while the existing snapshot remains
    usable. _load_index() slices either backing without an extra full-file copy.
    """

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"TDS file not found: {self.path}")
        self._lock  = threading.Lock()
        self._f:  Any = None
        self._mm: Any = None
        self._hdr: dict = {}
        self._idx: SlotIndex = SlotIndex()
        self._file_size = 0
        self._sidecar_meta: dict[str, Any] = {}
        self._entry_meta: dict[str, dict[str, Any]] = {}
        self._open()

    def _open(self) -> None:
        try:
            self._f = open(self.path, 'rb')
            self._file_size = os.fstat(self._f.fileno()).st_size
            if self._file_size < FILE_HDR_SIZE:
                _raise_integrity(
                    TDSResultCode.PERSIST_HEADER_CORRUPT,
                    "TDS file is smaller than the fixed file header",
                    file_size=self._file_size, header_size=FILE_HDR_SIZE,
                )
            if _DETACH_READER_SNAPSHOTS:
                snapshot = self._f.read()
                self._f.close()
                self._f = None
                if len(snapshot) != self._file_size:
                    _raise_integrity(
                        TDSResultCode.PERSIST_READ_ERROR,
                        "TDS file changed while detaching the reader snapshot",
                        expected=self._file_size, actual=len(snapshot),
                    )
                self._mm = snapshot
            else:
                self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                self._hdr = _parse_file_header(bytes(self._mm[:FILE_HDR_SIZE]))
            except TDSPersistenceIntegrityError:
                raise
            except Exception as exc:
                _raise_integrity(
                    TDSResultCode.PERSIST_HEADER_CORRUPT,
                    str(exc), exception_type=type(exc).__name__, exception_message=str(exc),
                )
            self._validate_file_geometry()
            self._idx = self._load_index()
            self._validate_slot_geometry()
            self._load_sidecar()
        except Exception:
            self._release_backing()
            raise

    def _release_backing(self) -> None:
        backing = self._mm
        handle = self._f
        self._mm = None
        self._f = None
        try:
            close_backing = getattr(backing, 'close', None)
            if close_backing is not None:
                close_backing()
        finally:
            if handle is not None:
                handle.close()

    def _validate_file_geometry(self) -> None:
        data_off = int(self._hdr['data_offset'])
        idx_off = int(self._hdr['index_offset'])
        slot_count = int(self._hdr['slot_count'])
        if data_off < FILE_HDR_SIZE:
            _raise_integrity(
                TDSResultCode.PERSIST_HEADER_CORRUPT,
                "TDS data_offset points inside the file header",
                data_offset=data_off, header_size=FILE_HDR_SIZE,
            )
        if idx_off < data_off:
            _raise_integrity(
                TDSResultCode.PERSIST_INDEX_CORRUPT,
                "TDS index_offset precedes data_offset",
                data_offset=data_off, index_offset=idx_off,
            )
        if idx_off > self._file_size:
            _raise_integrity(
                TDSResultCode.PERSIST_INDEX_CORRUPT,
                "TDS index_offset points past EOF",
                index_offset=idx_off, file_size=self._file_size,
            )
        if slot_count < 0:
            _raise_integrity(TDSResultCode.PERSIST_INDEX_CORRUPT, "TDS slot_count is negative", slot_count=slot_count)

    def _load_index(self) -> SlotIndex:
        idx_off = int(self._hdr['index_offset'])
        slot_count = int(self._hdr['slot_count'])
        idx_bytes = bytes(self._mm[idx_off:self._file_size])
        return SlotIndex.from_bytes(idx_bytes, slot_count)

    def _validate_slot_geometry(self) -> None:
        data_off = int(self._hdr['data_offset'])
        data_len = int(self._hdr['index_offset']) - data_off
        for rec in self._idx.all_records():
            if rec.offset < 0 or rec.length < 0:
                _raise_integrity(
                    TDSResultCode.PERSIST_SLOT_BOUNDS_ERROR,
                    "Negative slot offset or length", name=rec.name, offset=rec.offset, length=rec.length,
                )
            if rec.offset > data_len or rec.offset + rec.length > data_len:
                _raise_integrity(
                    TDSResultCode.PERSIST_SLOT_BOUNDS_ERROR,
                    "Slot payload range extends outside data block",
                    name=rec.name, offset=rec.offset, length=rec.length, data_len=data_len,
                )

    def _load_sidecar(self) -> None:
        meta_path = self.path.with_suffix('.tds.meta')
        self._sidecar_meta = {}
        self._entry_meta = {}
        if not meta_path.exists():
            if int(self._hdr.get('version', 1)) >= 2:
                _raise_integrity(TDSResultCode.PERSIST_SIDECAR_CORRUPT, 'Required TDS v2 integrity sidecar is missing', meta_path=str(meta_path))
            return
        try:
            meta, _json_backend = loads_strict(meta_path.read_bytes(), expected_type=dict)
        except Exception as exc:
            _raise_integrity(
                TDSResultCode.PERSIST_SIDECAR_CORRUPT,
                "TDS sidecar metadata could not be parsed",
                meta_path=str(meta_path), exception_type=type(exc).__name__, exception_message=str(exc),
            )
        if not isinstance(meta, dict):
            _raise_integrity(TDSResultCode.PERSIST_SIDECAR_CORRUPT, "TDS sidecar root is not an object", meta_path=str(meta_path))
        # New hardening fields are enforced when present and ignored for older sidecars.
        meta_ts = meta.get('tds_header_ts')
        if meta_ts is not None and int(meta_ts) != int(self._hdr.get('ts', 0)):
            _raise_integrity(
                TDSResultCode.PERSIST_SNAPSHOT_EPOCH_MISMATCH,
                "TDS data file and sidecar metadata describe different snapshots",
                file_ts=int(self._hdr.get('ts', 0)), meta_ts=int(meta_ts), meta_path=str(meta_path),
            )
        meta_size = meta.get('tds_file_size')
        if meta_size is not None and int(meta_size) != int(self._file_size):
            _raise_integrity(
                TDSResultCode.PERSIST_SNAPSHOT_EPOCH_MISMATCH,
                "TDS data file size and sidecar metadata size disagree",
                file_size=int(self._file_size), meta_file_size=int(meta_size), meta_path=str(meta_path),
            )
        entries = meta.get('entries', {}) or {}
        if not isinstance(entries, dict):
            _raise_integrity(TDSResultCode.PERSIST_SIDECAR_CORRUPT, "TDS sidecar entries field is not an object", meta_path=str(meta_path))
        self._sidecar_meta = meta
        self._entry_meta = {str(k): dict(v) for k, v in entries.items() if isinstance(v, dict)}

    def reload(self) -> None:
        with self._lock:
            self._release_backing()
            self._open()

    def _short_name(self, slot_key: str) -> str:
        return slot_key.rsplit('/', 1)[-1]

    def _meta_for_slot(self, slot_key: str) -> dict[str, Any]:
        for name, meta in self._entry_meta.items():
            if str(meta.get('slot_key', '')) == slot_key:
                return meta
        return self._entry_meta.get(self._short_name(slot_key), {})

    def _stored_payload(self, rec: SlotRecord) -> bytes:
        data_base = int(self._hdr['data_offset'])
        abs_off = data_base + int(rec.offset)
        abs_end = abs_off + int(rec.length)
        if abs_off < data_base or abs_end > int(self._hdr['index_offset']) or abs_end > self._file_size:
            _raise_integrity(
                TDSResultCode.PERSIST_SLOT_BOUNDS_ERROR,
                "Slot payload range failed read-time bounds validation",
                name=rec.name, abs_off=abs_off, abs_end=abs_end, index_offset=int(self._hdr['index_offset']), file_size=self._file_size,
            )
        with self._lock:
            payload = bytes(self._mm[abs_off:abs_end])
        if len(payload) != int(rec.length):
            _raise_integrity(
                TDSResultCode.PERSIST_SLOT_BOUNDS_ERROR,
                "Short payload read from memory map",
                name=rec.name, expected=int(rec.length), actual=len(payload),
            )
        return payload

    def _plain_payload_for_hash(self, stored: bytes, fmt_id: FmtID, codec: str) -> bytes | TDSResult:
        if fmt_id & FmtID.COMPRESSED:
            try:
                return CompressorRegistry.decompress(stored, codec)
            except Exception as exc:
                return TDSResult.fail(
                    TDSResultCode.PERSIST_CODEC_UNAVAILABLE,
                    "Compressed payload could not be decoded with its persisted codec.",
                    path=str(self.path),
                    meta={
                        'fmt_id': int(fmt_id),
                        'codec': codec or '',
                        'stored_size': len(stored),
                        'exception_type': type(exc).__name__,
                        'exception_message': str(exc),
                    },
                )
        return stored

    def _validate_payload_hash(self, slot_key: str, plain_raw: bytes, expected_hash: str) -> Optional[TDSResult]:
        if not expected_hash:
            return None
        actual_hash = content_hash_bytes(plain_raw)
        if actual_hash != expected_hash:
            return TDSResult.fail(
                TDSResultCode.PERSIST_PAYLOAD_HASH_MISMATCH,
                "Persisted payload content_hash mismatch; data not returned.",
                name=slot_key,
                path=str(self.path),
                meta={'expected_hash': expected_hash, 'actual_hash': actual_hash, 'raw_size': len(plain_raw)},
            )
        return None

    def read(self, name: str, *, codec: str | None = None, content_hash: str | None = None) -> Any:
        rec = self._idx.lookup(name)
        if rec is None:
            raise KeyError(f"Entry '{name}' not found in {self.path.name!r}")
        meta = self._meta_for_slot(name)
        effective_codec = str(codec if codec is not None else meta.get('codec', '') or '')
        expected_hash = str(content_hash if content_hash is not None else meta.get('content_hash', '') or '')
        stored = self._stored_payload(rec)
        plain_raw = self._plain_payload_for_hash(stored, FmtID(rec.fmt_id), effective_codec)
        if isinstance(plain_raw, TDSResult):
            return plain_raw
        hash_failure = self._validate_payload_hash(name, plain_raw, expected_hash)
        if hash_failure is not None:
            return hash_failure
        return _deserialize_payload(stored, FmtID(rec.fmt_id), effective_codec)

    def read_raw(self, name: str) -> bytes:
        rec = self._idx.lookup(name)
        if rec is None:
            raise KeyError(name)
        return self._stored_payload(rec)

    def read_result(self, name: str) -> TDSResult:
        """Public non-halting persistence read surface: always return TDSResult."""
        try:
            value = self.read(name)
            if isinstance(value, TDSResult) and not value.ok:
                return value
            return TDSResult.success(TDSResultCode.PERSIST_READ_OK, "Persisted entry read.", name=name, path=str(self.path), value=value)
        except TDSPersistenceIntegrityError as exc:
            return TDSResult.fail(exc.code, str(exc), name=name, path=str(self.path), meta=exc.meta)
        except Exception as exc:
            return TDSResult.from_exception(TDSResultCode.PERSIST_READ_ERROR, exc, name=name, path=str(self.path))

    def read_many(self, names: List[str]) -> Dict[str, Any]:
        pool = ConcurrencyPool.acquire()
        def _one(n):
            return (n, self.read(n))
        return dict(pool.map_parallel(_one, names))

    def read_many_result(self, names: List[str]) -> TDSResult:
        """Public non-halting batch persistence read surface."""
        try:
            values = self.read_many(names)
            failures = {k: v.as_dict() for k, v in values.items() if isinstance(v, TDSResult) and not v.ok}
            if failures:
                return TDSResult.fail(TDSResultCode.PERSIST_BATCH_READ_PARTIAL, "One or more persisted entries could not be read.", path=str(self.path), value=values, meta={"failures": failures})
            return TDSResult.success(TDSResultCode.PERSIST_BATCH_READ_OK, "Persisted entries read.", path=str(self.path), value=values, meta={"count": len(values)})
        except Exception as exc:
            return TDSResult.from_exception(TDSResultCode.PERSIST_BATCH_READ_ERROR, exc, path=str(self.path), meta={"count": len(names)})

    def keys(self) -> List[str]:
        return [r.name for r in self._idx.all_records()]

    def __len__(self) -> int:
        return len(self._idx)

    def __contains__(self, name: str) -> bool:
        return self._idx.lookup(name) is not None

    def close(self) -> None:
        with self._lock:
            self._release_backing()

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
    Atomic writer: shadow file -> fsync -> rename.

    
    - _finalise(): pre-allocates a bytearray for the full file and writes
      blocks in-place via memoryview slices, then does a single os.write().
      Avoids repeated b''.join() overhead on large directories.
    - write_parallel(): futures submitted as ordered batch; result list
      preserves original entry order.
    """

    def __init__(self, path):
        self.path    = Path(path)
        self._shadow = self.path.with_suffix('.tds~')
        self._meta   = self.path.with_suffix('.tds.meta')

    @staticmethod
    def _serialize_entry(entry: TDSEntry) -> bytes:
        # Persist compressed entries with their selected codec, not whichever
        # process-wide default happens to be active during flush/load.
        return _serialize_payload(entry.data, entry.fmt_id, getattr(entry, 'codec', '') or '')

    @staticmethod
    def _snapshot_slot(node_path: str, entry: TDSEntry, payload: bytes) -> SnapshotSlot:
        return SnapshotSlot(
            slot_key=TDSWriter._slot_key(node_path, entry.name),
            short_name=entry.name,
            payload=payload,
            fmt_id=int(entry.fmt_id),
            payload_kind=str(getattr(entry, 'payload_kind', '') or ''),
            content_hash=str(getattr(entry, 'content_hash', '') or ''),
            raw_size=int(getattr(entry, 'raw_size', 0) or 0),
            stored_size=int(getattr(entry, 'stored_size', 0) or len(payload)),
            codec=str(getattr(entry, 'codec', '') or ''),
        )

    @staticmethod
    def _slot_key(node_path: str, entry_name: str) -> str:
        return f"{node_path}/{entry_name}"

    def write(self, directory: TDSDirectory, recurse: bool = True) -> int:
        idx: SlotIndex = SlotIndex()
        snapshot: List[SnapshotSlot] = []
        cursor = 0

        def _walk(node: TDSDirectory) -> None:
            nonlocal cursor
            node_path = node.path()
            with node._lock:
                entries = list(node._entries.values())
                children = list(node._children.values())
            for entry in entries:
                payload = self._serialize_entry(entry)
                snap = self._snapshot_slot(node_path, entry, payload)
                h = zlib.adler32(snap.slot_key.encode()) & 0x7FFFFFFFFFFFFFFF
                idx.add(SlotRecord(name=snap.slot_key, name_hash=h,
                                   offset=cursor, length=len(payload),
                                   fmt_id=int(entry.fmt_id)))
                snapshot.append(snap)
                cursor += len(payload)
            if recurse:
                for child in children:
                    _walk(child)

        _walk(directory)
        return self._finalise(idx, snapshot, directory)

    def write_parallel(self, directory: TDSDirectory) -> int:
        node_path = directory.path()
        with directory._lock:
            entries = list(directory._entries.values())
        pool = ConcurrencyPool.acquire()

        # Submit all serialisation futures at once, preserve order
        futures = [pool.submit_thread(self._serialize_entry, e) for e in entries]
        serialized: List[Tuple[TDSEntry, bytes]] = [
            (entries[i], futures[i].result()) for i in range(len(futures))
        ]

        idx: SlotIndex = SlotIndex()
        snapshot: List[SnapshotSlot] = []
        cursor = 0
        for entry, payload in serialized:
            snap = self._snapshot_slot(node_path, entry, payload)
            h = zlib.adler32(snap.slot_key.encode()) & 0x7FFFFFFFFFFFFFFF
            idx.add(SlotRecord(name=snap.slot_key, name_hash=h,
                               offset=cursor, length=len(payload),
                               fmt_id=int(entry.fmt_id)))
            snapshot.append(snap)
            cursor += len(payload)
        return self._finalise(idx, snapshot, directory)

    def _finalise(self, idx: SlotIndex, snapshot: List[SnapshotSlot],
                  directory: TDSDirectory) -> int:
        """Emit data and sidecar from the same frozen entry snapshot.

        The data file keeps the existing shadow-write/fsync/replace sequence.
        The sidecar now follows the same write-all/fsync/replace/parent-fsync
        discipline and describes only the entries actually serialized into the
        just-committed data block.
        """
        data_block = b''.join(s.payload for s in snapshot)
        index_block = idx.to_bytes()
        data_offset = FILE_HDR_SIZE
        index_offset = data_offset + len(data_block)
        file_header = _build_file_header(len(idx), index_offset, data_offset)
        header_meta = _parse_file_header(file_header)

        total = len(file_header) + len(data_block) + len(index_block)
        buf = bytearray(total)
        mv = memoryview(buf)
        pos = 0
        mv[pos: pos + len(file_header)] = file_header; pos += len(file_header)
        mv[pos: pos + len(data_block)] = data_block; pos += len(data_block)
        mv[pos: pos + len(index_block)] = index_block

        try:
            fd = open_binary_fd(
                self._shadow, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            try:
                _write_all(fd, buf)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(str(self._shadow), str(self.path))
            _fsync_parent_dir(self.path)
        except Exception:
            try:
                self._shadow.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        snapshot_epoch = int(header_meta['ts'])
        meta = {
            'schema': 'tds.sidecar.v1',
            'snapshot_epoch': snapshot_epoch,
            'tds_header_ts': snapshot_epoch,
            'tds_file_size': total,
            'tds_slot_count': len(idx),
            'tds_index_offset': index_offset,
            'tds_data_offset': data_offset,
            'node_name': directory.name,
            'node_path': directory.path(),
            'flags':     directory.flags,
            'fmt_id':    int(directory.fmt_id),
            'dir_id':    directory.dir_id,
            'ts_create': directory._ts_create,
            'manifest_hash': directory.manifest_policy.manifest_hash,
            'srz': directory.srz.as_dict(),
            'telemetry': directory.telemetry.snapshot(),
            'capabilities': directory.capability_names(),
            'reserved_namespaces': directory.reserved_namespaces.to_dict(),
            'variables': directory.variable_control_snapshot(),
            'entries': {s.short_name: {
                'payload_kind': s.payload_kind,
                'content_hash': s.content_hash,
                'raw_size': int(s.raw_size),
                'stored_size': int(s.stored_size),
                'codec': s.codec,
                'slot_key': s.slot_key,
                'fmt_id': int(s.fmt_id),
                'snapshot_epoch': snapshot_epoch,
            } for s in snapshot},
        }
        meta_tmp = self._meta.with_suffix(self._meta.suffix + '.tmp')
        meta_bytes = dumps_canonical(meta)[0]
        try:
            fd = open_binary_fd(
                meta_tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            try:
                _write_all(fd, meta_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(str(meta_tmp), str(self._meta))
            _fsync_parent_dir(self._meta)
        except Exception:
            try:
                meta_tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        return total


# ////////////////////////////////////////////////////////////////////////////////
# § 14  TDS PERSISTENCE
# ////////////////////////////////////////////////////////////////////////////////

class TDSPersistence:
    """
    Mounts a TDSFileSystem to a real directory.

    
    - flush() uses an explicit deque instead of recursion — no Python stack
      growth on deeply nested filesystems.
    - load_node() iterates reader._idx.all_records() directly instead of
      calling reader.keys() + per-key lookup (halves dict operations).
    """

    def __init__(self, mount_dir, *, create_manifest: bool = True):
        self.mount_dir = Path(mount_dir)
        self.mount_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.mount_dir, 0o700)
        except OSError:
            pass
        if create_manifest:
            write_default_manifest(self.mount_dir, overwrite=False)
        self.manifest_policy: ManifestPolicy = load_manifest(self.mount_dir, inherit=True)
        self._readers: Dict[str, TDSReader] = {}
        self._lock     = threading.Lock()
        self._fs:  Optional[TDSFileSystem] = None

    def _node_path_to_filename(self, node_path: str) -> Path:
        # Preserve legacy-readable filenames for ordinary components while
        # escaping delimiter-bearing components so distinct paths stay distinct.
        def encode_component(component: str) -> str:
            component = component.replace('%', '%25')
            return component.replace('__', '%5F%5F')
        parts = [encode_component(p) for p in node_path.strip('/').split('/') if p]
        safe = '__'.join(parts)
        return self.mount_dir / f"{safe}.tds"

    def flush_node(self, node: TDSDirectory,
                   parallel: bool = False) -> Tuple[str, int]:
        fpath  = self._node_path_to_filename(node.path())
        writer = TDSWriter(fpath)
        nbytes = (writer.write_parallel(node) if parallel
                  else writer.write(node, recurse=False))
        return str(fpath), nbytes

    def flush(self, fs: TDSFileSystem,
              parallel_nodes: bool = True) -> Dict[str, int]:
        # BFS via deque — avoids recursion depth issues
        nodes: List[TDSDirectory] = []
        q = deque([fs.root])
        while q:
            node = q.popleft()
            nodes.append(node)
            with node._lock:
                children = list(node._children.values())
            q.extend(children)

        pool = ConcurrencyPool.acquire()

        def _flush_one(node: TDSDirectory) -> Tuple[str, int]:
            return self.flush_node(node, parallel=False)

        results = (pool.map_parallel(_flush_one, nodes)
                   if parallel_nodes else [_flush_one(n) for n in nodes])
        return dict(results)

    def load_node(self, tds_path,
                  into: Optional[TDSDirectory] = None) -> TDSDirectory:
        tds_path  = Path(tds_path)
        reader    = TDSReader(tds_path)
        stem      = tds_path.stem
        name      = stem.split('__')[-1]
        meta_path = tds_path.with_suffix('.tds.meta')
        flags     = DirFlags.NONE
        fmt_id    = FmtID.RAW_BINARY
        dir_id    = None
        ts_create = None
        srz_meta  = {}
        telemetry_snapshot = {}
        variables_snapshot = {}
        entry_meta = {}
        if meta_path.exists():
            try:
                meta, _json_backend = loads_strict(meta_path.read_bytes(), expected_type=dict)
                name      = str(meta.get('node_name', name))
                flags     = meta.get('flags', int(DirFlags.NONE))
                fmt_id    = FmtID(meta.get('fmt_id', int(FmtID.RAW_BINARY)))
                dir_id    = meta.get('dir_id')
                ts_create = meta.get('ts_create')
                srz_meta  = meta.get('srz', {}) or {}
                telemetry_snapshot = meta.get('telemetry', {}) or {}
                variables_snapshot = meta.get('variables', {}) or {}
                entry_meta = meta.get('entries', {}) or {}
            except Exception:
                pass
        if into is None:
            into = TDSDirectory(
                name=name, fmt_id=fmt_id, flags=flags,
                manifest_policy=self.manifest_policy,
                srz_enabled=bool(srz_meta.get('enabled', False)),
                route_stamp=str(srz_meta.get('route_stamp', '')),
                source_tags=list(srz_meta.get('source_tags', []) or []),
                aliases=list(srz_meta.get('aliases', []) or []),
                latent_id=srz_meta.get('latent_id'),
            )
        if dir_id:    into.dir_id     = dir_id
        if ts_create: into._ts_create = ts_create
        if telemetry_snapshot:
            into.telemetry.restore_snapshot(telemetry_snapshot)
        if variables_snapshot:
            into.variables.restore(variables_snapshot)

        with self._lock:
            self._readers[str(tds_path)] = reader

        # iterate records directly — no keys() + lookup round-trip
        slot_to_name = {str(v.get('slot_key')): str(k) for k, v in entry_meta.items() if isinstance(v, dict) and v.get('slot_key')}
        for rec in reader._idx.all_records():
            short_name = slot_to_name.get(rec.name, rec.name.rsplit('/', 1)[-1])
            entry = _LazyEntry(
                slot_key   = rec.name,
                short_name = short_name,
                fmt_id     = FmtID(rec.fmt_id),
                reader     = reader,
            )
            em = entry_meta.get(short_name, {}) if isinstance(entry_meta, dict) else {}
            if em:
                object.__setattr__(entry, 'payload_kind', str(em.get('payload_kind', '')))
                object.__setattr__(entry, 'content_hash', str(em.get('content_hash', '')))
                object.__setattr__(entry, 'raw_size', int(em.get('raw_size', 0) or 0))
                object.__setattr__(entry, 'stored_size', int(em.get('stored_size', 0) or 0))
                object.__setattr__(entry, 'codec', str(em.get('codec', '')))
            into._entries.put(short_name, entry)
            into._bloom.add(short_name)

        return into

    def close_reader(self, tds_path) -> None:
        key = str(tds_path)
        with self._lock:
            reader = self._readers.pop(key, None)
        if reader is not None:
            reader.close()

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

    def open_readers(self, paths) -> List[TDSReader]:
        pool = ConcurrencyPool.acquire()
        def _open(p):
            r = TDSReader(p)
            with self._lock:
                self._readers[str(p)] = r
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
    Deferred-load entry; unchanged from earlier releases (already correct and optimal).
    """

    def __init__(self, slot_key: str, short_name: str,
                 fmt_id: FmtID, reader: TDSReader):
        object.__setattr__(self, 'name',       short_name)
        object.__setattr__(self, 'fmt_id',     fmt_id)
        object.__setattr__(self, 'data',       None)
        object.__setattr__(self, 'ts_written', 0)
        object.__setattr__(self, 'entry_id',   f"lazy:{short_name}")
        object.__setattr__(self, 'codec',      '')
        object.__setattr__(self, 'payload_kind', '')
        object.__setattr__(self, 'content_hash', '')
        object.__setattr__(self, 'raw_size', 0)
        object.__setattr__(self, 'stored_size', 0)
        object.__setattr__(self, '_slot_key',  slot_key)
        object.__setattr__(self, '_reader',    reader)
        object.__setattr__(self, '_loaded',    False)
        object.__setattr__(self, '_lazy_lock', threading.Lock())

    def __getattribute__(self, item: str) -> Any:
        if item == 'data':
            lock = object.__getattribute__(self, '_lazy_lock')
            with lock:
                if not object.__getattribute__(self, '_loaded'):
                    reader   = object.__getattribute__(self, '_reader')
                    slot_key = object.__getattribute__(self, '_slot_key')
                    codec = object.__getattribute__(self, 'codec')
                    content_hash = object.__getattribute__(self, 'content_hash')
                    object.__setattr__(self, 'data', reader.read(slot_key, codec=codec, content_hash=content_hash))
                    object.__setattr__(self, '_loaded', True)
            return object.__getattribute__(self, 'data')
        return object.__getattribute__(self, item)

    def serialise(self) -> bytes:
        reader   = object.__getattribute__(self, '_reader')
        slot_key = object.__getattribute__(self, '_slot_key')
        return reader.read_raw(slot_key)


# ////////////////////////////////////////////////////////////////////////////////
# § 15  PARALLEL FLUSHER
# ////////////////////////////////////////////////////////////////////////////////

class ParallelFlusher:
    """Schedules concurrent flush of multiple TDSDirectory nodes."""

    def __init__(self, mount_dir):
        self._persist = TDSPersistence(mount_dir)
        self._queue:  List[TDSDirectory] = []
        self._lock    = threading.Lock()

    def enqueue(self, node: TDSDirectory) -> None:
        with self._lock:
            self._queue.append(node)

    def flush_all(self, parallel: bool = True) -> Dict[str, int]:
        with self._lock:
            nodes = list(self._queue)
            self._queue.clear()
        pool = ConcurrencyPool.acquire()

        def _flush(node: TDSDirectory) -> Tuple[str, int]:
            return self._persist.flush_node(node)

        results = (pool.map_parallel(_flush, nodes)
                   if parallel else [_flush(n) for n in nodes])
        return dict(results)

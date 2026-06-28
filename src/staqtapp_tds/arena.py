"""
Staqtapp-TDS v1.6.0 arena layer.

Pure-Python byte arena that preserves the int64 handle contract needed by a
future mmap/shared_memory/native allocator. The public VFS can depend on this
small interface instead of depending on Python object identity.
"""
from __future__ import annotations

import struct
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ArenaStats:
    capacity: int
    used: int
    free: int
    allocations: int


class SharedMemoryArena:
    """
    Append-only byte arena returning int64 offset handles.

    Layout per allocation:
        [8-byte big-endian payload length][payload bytes]

    This class is intentionally pure Python for portability. It is not yet a
    true OS shared-memory allocator, but it gives the VFS the correct handle ABI
    so a later mmap/multiprocessing.shared_memory backend can replace it.
    """

    _HDR = struct.Struct('>Q')

    def __init__(self, capacity: int = 64 * 1024 * 1024):
        if int(capacity) <= self._HDR.size:
            raise ValueError("SharedMemoryArena capacity is too small")
        self._buf = bytearray(int(capacity))
        self._capacity = int(capacity)
        self._offset = 0
        self._allocations = 0
        self._lock = threading.RLock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def used(self) -> int:
        with self._lock:
            return self._offset

    @property
    def free(self) -> int:
        with self._lock:
            return self._capacity - self._offset

    def stats(self) -> ArenaStats:
        with self._lock:
            return ArenaStats(
                capacity=self._capacity,
                used=self._offset,
                free=self._capacity - self._offset,
                allocations=self._allocations,
            )

    def allocate(self, payload: bytes | bytearray | memoryview) -> int:
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        elif not isinstance(payload, (bytes, bytearray)):
            raise TypeError("arena payload must be bytes-like")
        need = self._HDR.size + len(payload)
        with self._lock:
            if self._offset + need > self._capacity:
                raise MemoryError(
                    f"SharedMemoryArena exhausted: need={need}, free={self._capacity - self._offset}"
                )
            handle = self._offset
            self._HDR.pack_into(self._buf, handle, len(payload))
            start = handle + self._HDR.size
            self._buf[start:start + len(payload)] = payload
            self._offset += need
            self._allocations += 1
            return int(handle)

    def read(self, handle: int) -> bytes:
        with self._lock:
            handle = int(handle)
            if handle < 0 or handle + self._HDR.size > self._offset:
                raise KeyError(f"Invalid arena handle: {handle}")
            length = self._HDR.unpack_from(self._buf, handle)[0]
            start = handle + self._HDR.size
            end = start + length
            if end > self._offset:
                raise KeyError(f"Corrupt arena handle: {handle}")
            return bytes(self._buf[start:end])

    def view(self, handle: int) -> memoryview:
        """Return a read-only-style memoryview slice. Caller must not mutate it."""
        with self._lock:
            handle = int(handle)
            if handle < 0 or handle + self._HDR.size > self._offset:
                raise KeyError(f"Invalid arena handle: {handle}")
            length = self._HDR.unpack_from(self._buf, handle)[0]
            start = handle + self._HDR.size
            end = start + length
            if end > self._offset:
                raise KeyError(f"Corrupt arena handle: {handle}")
            return memoryview(self._buf)[start:end]

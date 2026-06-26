# Staqtapp-TDS — Temporal Directory System

> **A virtual file system engineered for ASI-scale computation.**
> Binary-native. Math-accelerated. Concurrency-first. No CSV. No comma crap.
> Updated to v1.2.0, several issues fixed including new features.

---

## Table of Contents

1. [Overview](#overview)
2. [Why Not Existing File Systems?](#why-not-existing-file-systems)
3. [Architecture at a Glance](#architecture-at-a-glance)
4. [Module Map](#module-map)
5. [Binary Format Reference](#binary-format-reference)
   - [In-Memory Directory Header (36 bytes)](#in-memory-directory-header-36-bytes)
   - [On-Disk File Header (44 bytes)](#on-disk-file-header-44-bytes)
   - [Slot Index Record](#slot-index-record)
   - [FmtID Encoding](#fmtid-encoding)
   - [DirFlags Bit Field](#dirflags-bit-field)
6. [Read Path — Three Tiers](#read-path--three-tiers)
7. [Write Path — Atomic Shadow Swap](#write-path--atomic-shadow-swap)
8. [Core Subsystems](#core-subsystems)
   - [HybridRegistry — Probability-LRU](#hybridregistry--probability-lru)
   - [SlotIndex — Numba Binary Search](#slotindex--numba-binary-search)
   - [LoopCacheManager — Pinned Cycle Variables](#loopcachemanager--pinned-cycle-variables)
   - [ConcurrencyPool — Guaranteed Hook](#concurrencypool--guaranteed-hook)
   - [SymbolTable — Matrix-Level Switching](#symboltable--matrix-level-switching)
9. [Numba JIT Kernels](#numba-jit-kernels)
10. [Disk Layout Flowchart](#disk-layout-flowchart)
11. [Read Path Flowchart](#read-path-flowchart)
12. [Write Path Flowchart](#write-path-flowchart)
13. [Directory Tree Flowchart](#directory-tree-flowchart)
14. [Concurrency Model](#concurrency-model)
15. [Quick Start](#quick-start)
16. [API Reference Summary](#api-reference-summary)
17. [File Naming Convention](#file-naming-convention)
18. [Performance Characteristics](#performance-characteristics)
19. [Dependency Matrix](#dependency-matrix)
20. [Roadmap](#roadmap)

---

## New Features added 2026

(1) BloomFilter: zero-seek definite miss path on every read
(2) CompressorRegistry: pluggable codecs (zlib default; lz4/zstd if installed)
(3) EntrySchema: per-entry dtype + shape + type validation
(4) Async surface: TDSDirectory.aread() / awrite()
(5) WriteAheadLog: append + checkpoint + replay for crash recovery
(6) _join_segments now preserves caller-specified dtype

---

## Overview

`.tds` (Temporal Directory System) is a virtual file system built ground-up for the data demands of Artificial Superintelligence — vast, multi-dimensional, mathematically dense, and in constant parallel flux. Where conventional file systems store blobs named by strings and rely on OS-level structures, TDS treats the directory itself as a first-class mathematical object: binary-encoded, CRC-verified, probability-sorted, and concurrency-pooled from the moment it is instantiated.

Every design decision answers the same question: **what does a file system look like when the entity using it processes more information per second than all human libraries combined?**

---

## Why Not Existing File Systems?

| Concern | ext4 / NTFS / APFS | JSON / CSV stores | **TDS** |
|---|---|---|---|
| Header format | Kernel-managed inode (opaque) | Plain text — bytes wasted on commas, quotes, keys | 36-byte binary struct, CRC-verified |
| Timestamp precision | Seconds or milliseconds | String — parsed per read | Nanosecond `uint64`, embedded in header |
| Directory lookup | Hash table (kernel) | Full parse required | Numba O(log n) binary search over sorted hash array |
| Concurrency | File locks, kernel scheduler | None — parse is single-threaded | Guaranteed `ConcurrencyPool` singleton; every node hooks in instantly |
| Variable type awareness | None — all bytes are equal | Fragile schema conventions | `FmtID` OR-flag in header: numpy, symbol table, loop cache, raw, compressed |
| Probability-based access ordering | None | None | `HybridRegistry`: decay-weighted LRU, re-sorted in Numba |
| Pinned cycle variables | Not a concept | Not a concept | `LoopCacheManager`: slots with configurable overwrite cycle |
| Matrix symbol switching | Not a concept | Not a concept | `SymbolTable` + Numba kernel: instant swap across full matrix |
| Atomic writes | `fsync` + rename (manual) | Not atomic | Shadow-file + `fsync` + `os.rename` — built into `TDSWriter` |
| Lazy disk reads | Not a concept | Not a concept | `_LazyEntry`: mmap placeholder, payload loaded on first `.data` access |
| Parallel flush | Not a concept | Not a concept | `ParallelFlusher`: all directory nodes flushed simultaneously |

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────────┐
│                        TDSFileSystem                            │
│   root TDSDirectory                                             │
│   ├── makedirs / resolve / parallel_batch_write                 │
│   └── snapshot_headers                                          │
└───────────────────────┬─────────────────────────────────────────┘
                        │ owns tree of
┌───────────────────────▼─────────────────────────────────────────┐
│                      TDSDirectory                               │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐   │
│  │  Binary Header  │  │  HybridRegistry  │  │ LoopCache     │   │
│  │  36 bytes       │  │  Prob-LRU sorted │  │ Manager       │   │
│  │  CRC32 verified │  │  Numba decay     │  │ cycle slots   │   │
│  └─────────────────┘  └──────────────────┘  └───────────────┘   │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐   │
│  │  TDSEntry dict  │  │  SymbolTable     │  │ Concurrency   │   │
│  │  (name → entry) │  │  bi-dir sym↔id   │  │ Pool hook     │   │
│  └─────────────────┘  └──────────────────┘  └───────────────┘   │
└───────────────────────┬─────────────────────────────────────────┘
                        │ persisted by
┌───────────────────────▼─────────────────────────────────────────┐
│                    TDSPersistence                               │
│  ┌────────────┐  ┌───────────┐  ┌────────────┐  ┌──────────┐    │
│  │ TDSWriter  │  │ TDSReader │  │ SlotIndex  │  │ Parallel │    │
│  │ shadow swap│  │ mmap-back │  │ Numba seek │  │ Flusher  │    │
│  │ fsync safe │  │ lazy load │  │ O(log n)   │  │          │    │
│  └────────────┘  └───────────┘  └────────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────────┘
                        │ accelerated by
┌───────────────────────▼─────────────────────────────────────────┐
│                    Numba JIT Kernels                            │
│  _compute_subdir_offsets  │  _probability_decay                 │
│  _matrix_symbol_swap      │  _recursive_array_join              │
│  _slot_binary_search      │  _build_sorted_order                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Map

| File | Section | Responsibility |
|---|---|---|
| `tds_filesystem.py` | §1 | Binary header encode / decode |
| `tds_filesystem.py` | §2 | Numba JIT math kernels |
| `tds_filesystem.py` | §3 | `HybridRegistry` — probability-LRU |
| `tds_filesystem.py` | §4 | `LoopCacheManager` — pinned cycle vars |
| `tds_filesystem.py` | §5 | `ConcurrencyPool` — guaranteed singleton |
| `tds_filesystem.py` | §6 | `SymbolTable` — bi-directional sym ↔ id |
| `tds_filesystem.py` | §7 | `TDSEntry` — leaf variable storage |
| `tds_filesystem.py` | §8 | `TDSDirectory` — core tree node |
| `tds_filesystem.py` | §9 | `TDSFileSystem` — root mount API |
| `tds_persistence.py` | §10 | File-level constants and struct formats |
| `tds_persistence.py` | §11 | `SlotIndex` + `SlotRecord` — seek table |
| `tds_persistence.py` | §12 | `TDSReader` — mmap random-access reader |
| `tds_persistence.py` | §13 | `TDSWriter` — atomic shadow-swap writer |
| `tds_persistence.py` | §14 | `TDSPersistence` — mount / flush / load |
| `tds_persistence.py` | §14b | `_LazyEntry` — deferred mmap read |
| `tds_persistence.py` | §15 | `ParallelFlusher` — concurrent node flush |

---

## Binary Format Reference

### In-Memory Directory Header (36 bytes)

Every `TDSDirectory` node carries a 36-byte binary header generated by `encode_header()` and verifiable by `decode_header()`. Format: big-endian (`>`).

```
Offset  Size  Type     Field
──────  ────  ───────  ──────────────────────────────────────
0       4     bytes    Magic: 0x54 44 53 01  ("TDS\x01")
4       8     uint64   ts_create — nanosecond creation timestamp
12      8     uint64   ts_mod    — nanosecond last-modified timestamp
20      2     uint16   flags     — DirFlags bit field
22      2     uint16   fmt_id    — FmtID of stored data
24      4     uint32   subdir_count
28      4     uint32   entry_count
32      4     uint32   CRC32 of bytes 0–31 (placeholder = 0 during calc)
──────  ────  ───────  ──────────────────────────────────────
        36             Total
```

### On-Disk File Header (44 bytes)

Every `.tds` file on disk opens with a 44-byte file header generated by `_build_file_header()`. Format: big-endian.

```
Offset  Size  Type     Field
──────  ────  ───────  ──────────────────────────────────────
0       4     bytes    Magic: 0x54 44 53 58  ("TDSX")
4       4     uint32   Format version        (currently 1)
8       8     uint64   slot_count            (number of index entries)
16      8     uint64   index_offset          (byte position of SlotIndex block)
24      8     uint64   data_offset           (byte position of data block)
32      8     uint64   Timestamp (ns)
40      4     uint32   CRC32 of bytes 0–39
──────  ────  ───────  ──────────────────────────────────────
        44             Total
```

### Slot Index Record

Each entry in the `SlotIndex` block on disk is variable-length:

```
Offset  Size      Type     Field
──────  ────────  ───────  ──────────────────────────────────────
0       8         uint64   name_hash  (Adler-32 of name, kept positive)
8       8         uint64   offset     (byte offset within data block)
16      4         uint32   length     (byte length of payload)
20      2         uint16   fmt_id     (FmtID value)
22      2         uint16   name_len   (byte length of name string)
24      name_len  UTF-8    name       (entry name)
──────  ────────  ───────  ──────────────────────────────────────
        24 + N             Total per slot
```

The entire `SlotIndex` block lives **after** the data block. Appending new entries to the data block never requires rewriting the index until a full `flush()` / shadow swap.

### FmtID Encoding

`FmtID` is an `IntFlag` — values can be OR'd together. `COMPRESSED` (0x80) is the OR-able modifier.

| Name | Value | Description |
|---|---|---|
| `RAW_BINARY` | `0x00` | Untyped byte buffer |
| `NUMPY_MATRIX` | `0x01` | NumPy array, stored via `np.save` |
| `PICKLE_OBJ` | `0x02` | Arbitrary Python object, protocol 5 |
| `SYMBOL_TABLE` | `0x03` | Pickled dict from `SymbolTable` |
| `LOOP_CACHE` | `0x04` | Pickled loop-cache slot state |
| `COMPRESSED` | `0x80` | OR-able modifier — zlib level 3 or 6 |

**Examples of combined values:**

| Combined | Hex | Meaning |
|---|---|---|
| `NUMPY_MATRIX \| COMPRESSED` | `0x81` | Compressed numpy array |
| `PICKLE_OBJ \| COMPRESSED` | `0x82` | Compressed pickled object |
| `SYMBOL_TABLE \| COMPRESSED` | `0x83` | Compressed symbol table |

### DirFlags Bit Field

`DirFlags` is packed into the 2-byte `flags` field of the directory header. Flags are OR'd together freely.

| Name | Hex | Effect |
|---|---|---|
| `NONE` | `0x0000` | No special behaviour |
| `READONLY` | `0x0001` | Reject write operations |
| `ENCRYPTED` | `0x0002` | Reserved for encryption layer |
| `PARALLEL_IO` | `0x0004` | Sub-directory reads fan out across pool |
| `LOOP_PINNED` | `0x0008` | Loop-cache slots held in memory |
| `RECURSIVE` | `0x0010` | Enable recursive array join traversal |
| `PROB_SORT` | `0x0020` | `ls()` returns probability-sorted order |

---

## Read Path — Three Tiers

Every `TDSDirectory.read(name)` call resolves through three tiers in strict order, stopping at the first hit.

| Tier | Location | Mechanism | Cost |
|---|---|---|---|
| **1 — Registry Hot Path** | RAM — `HybridRegistry` | `OrderedDict` lookup, bump access count + timestamp | O(1) |
| **2 — Directory Node** | RAM — `TDSDirectory._entries` | Direct dict lookup, optional `TDSEntry.deserialise()` | O(1) + decompression |
| **3 — Lazy mmap** | Disk — `.tds` file via `TDSReader` | `SlotIndex.lookup()` → mmap slice → deserialise | O(log n) + I/O |

After a Tier 2 or Tier 3 hit, the entry is promoted into `HybridRegistry` so the next access hits Tier 1.

---

## Write Path — Atomic Shadow Swap

```
TDSWriter.write(directory)
    │
    ├─ 1. Serialise all entries in parallel (write_parallel) or sequential
    │        FmtID == NUMPY_MATRIX  →  np.save() bytes
    │        FmtID == PICKLE_OBJ    →  pickle.dumps() protocol 5
    │        COMPRESSED flag set    →  zlib.compress(raw, level=3)
    │
    ├─ 2. Build SlotIndex — one SlotRecord per entry
    │        name_hash = Adler-32(name) & 0x7FFFFFFFFFFFFFFF
    │        offset    = running cursor in data block
    │        length    = len(payload)
    │
    ├─ 3. Open shadow file  <name>.tds~
    │        write 44-byte header (index_offset = 0 placeholder)
    │        write data block (all payloads, tightly packed)
    │        write SlotIndex block
    │        rewind to byte 0
    │        overwrite header with real offsets + CRC32
    │
    ├─ 4. f.flush()  →  os.fsync(fd)
    │
    └─ 5. shutil.move(".tds~" → ".tds")   ← atomic POSIX rename
```

Readers never observe a partial file. Either the old complete `.tds` or the new complete `.tds` is visible — never anything in between.

---

## Core Subsystems

### HybridRegistry — Probability-LRU

`HybridRegistry` is the hot-path cache sitting in front of every `TDSDirectory`. It combines two eviction strategies:

**LRU layer** — an `OrderedDict` tracks insertion order. When capacity is exceeded, the least-recently-used entry is evicted. O(1) get and put.

**Probability-decay layer** — when `sorted_keys()` is called (by `ls()` or the search subsystem), the Numba kernel `_probability_decay` scores every entry:

```
score(i) = access_count(i) × e^(−λ × Δt)
```

where `λ = 1e-4` and `Δt` is seconds since last access. Entries accessed often and recently score highest and are returned first. This means the file system naturally pre-positions the data ASI is most likely to need next — without any manual hints.

**Capacity:** 4096 entries per directory node by default. Thread-safe via `RLock`.

### SlotIndex — Numba Binary Search

`SlotIndex` is the on-disk seek table loaded into RAM when a `.tds` file is opened by `TDSReader`. It maintains two parallel numpy arrays rebuilt lazily on first lookup after any mutation:

- `_hashes` — sorted `int64` array of `Adler-32(name)` values
- `_order` — argsort indices mapping sorted position → original record position

Lookup sequence for `read("embed_0003")`:

```
h = Adler-32("embed_0003") & 0x7FFFFFFFFFFFFFFF
idx = _slot_binary_search(_hashes, h)          ← Numba O(log n)
orig = _order[idx]
rec  = _records[orig]
if rec.name != "embed_0003": linear fallback    ← hash collision guard
return rec  →  (offset, length, fmt_id)
```

No string comparison occurs in the hot path — only integer comparison inside the Numba kernel.

### LoopCacheManager — Pinned Cycle Variables

ASI computation involves many variables that are written continuously but whose "current value" is only meaningful at specific overwrite boundaries — gradient accumulators, activation buffers, token streams. `LoopCacheManager` formalises this pattern.

Each named `LoopCacheSlot` has a `cycle` parameter. Every `write(value)` call increments an internal counter. When `counter % cycle == 0`, the slot's `current` value is overwritten and `write()` returns `True` — signalling that the value is now stable for reading.

```python
wm.loop_cache.register("gradient_buf", cycle=8)
for step in range(32):
    if wm.loop_cache.write("gradient_buf", gradient):
        # called 4 times — every 8th write
        publish(wm.loop_cache.read("gradient_buf"))
```

`batch_flush_numpy` concatenates incoming numpy arrays along a specified axis and flushes when the cycle triggers — for streaming matrix data.

### ConcurrencyPool — Guaranteed Hook

`ConcurrencyPool` is a singleton. Every `TDSDirectory` calls `ConcurrencyPool.acquire()` at construction — one line, zero configuration. The pool is created once on first call and reused forever.

| Resource | Count | Use |
|---|---|---|
| `ThreadPoolExecutor` | 64 workers | I/O, registry ops, parallel reads |
| `ProcessPoolExecutor` | 8 workers | CPU-bound compression, heavy serialisation |
| `asyncio` event loop | 1 (daemon thread) | Async coroutine support via `run_async` |

`map_parallel(fn, items)` selects threads or processes based on the `use_processes` flag and returns results in order.

### SymbolTable — Matrix-Level Switching

`SymbolTable` maintains a bidirectional `symbol ↔ float64 ID` mapping. Every interned symbol gets a unique monotonically increasing float ID. This allows token-level or operator-level symbols to be embedded directly into numpy matrices as numeric values, and switched across the entire matrix in a single Numba kernel call:

```python
sym_dir.symbols.intern("NULL")    # → 0.0
sym_dir.symbols.intern("START")   # → 1.0
swapped = sym_dir.symbols.swap("NULL", "START", matrix)
# Every 0.0 in matrix becomes 1.0 — via _matrix_symbol_swap Numba kernel
```

`decode_matrix(matrix)` converts a numeric matrix back to a 2-D list of symbol names for inspection.

---

## Numba JIT Kernels

All kernels use `@njit(cache=True)` — compiled once, cached to disk, reused on every subsequent run. A no-op shim is provided so the entire codebase runs without Numba installed (pure Python fallback).

| Kernel | Signature | Complexity | Purpose |
|---|---|---|---|
| `_compute_subdir_offsets` | `(sizes: int64[]) → int64[]` | O(n) | Prefix-sum of entry byte sizes → absolute seek offsets |
| `_probability_decay` | `(counts, times, now, λ) → float64[]` | O(n) parallel | Decay-weighted scores for registry re-sort |
| `_matrix_symbol_swap` | `(matrix, old_val, new_val) → float64[][]` | O(n²) parallel | In-place symbol substitution across full matrix |
| `_recursive_array_join` | `(arrays, depth) → float64[]` | O(total elements) | Flatten a stack of 1-D arrays via sequential copy |
| `_slot_binary_search` | `(hashes: int64[], target) → int64` | O(log n) | Seek-table lookup — integer comparison only |
| `_build_sorted_order` | `(hashes: int64[]) → int64[]` | O(n log n) | Argsort for SlotIndex rebuild |

---

## Disk Layout Flowchart

```
┌─────────────────────────────────────────────────────────┐
│                    <name>.tds  (on disk)                │
├─────────────────────────────────────────────────────────┤
│  BYTES 0–43          FILE HEADER (44 bytes)             │
│  ┌──────────┬────────┬────────┬────────┬───────┬──────┐ │
│  │  "TDSX"  │  ver=1 │ slots  │ idx_off│dat_off│  ts  │ │
│  │  4 bytes │ 4bytes │ 8bytes │ 8bytes │8bytes │8bytes│ │
│  └──────────┴────────┴────────┴────────┴───────┴──────┘ │
│  + 4 bytes CRC32                                        │
├─────────────────────────────────────────────────────────┤
│  BYTES 44 → idx_off   DATA BLOCK                        │
│  ┌──────────────┬──────────────┬──────────────────────┐ │
│  │  payload[0]  │  payload[1]  │  payload[2] ...      │ │
│  │  (variable)  │  (variable)  │                      │ │
│  └──────────────┴──────────────┴──────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│  BYTES idx_off → EOF  INDEX BLOCK (SlotIndex)           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Slot 0: hash(8) offset(8) len(4) fmt(2) nlen(2) N  │ │
│  │ Slot 1: hash(8) offset(8) len(4) fmt(2) nlen(2) N  │ │
│  │ ...                                                │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

Index lives at the end so the data block can be appended without rewriting it mid-session.

---

## Read Path Flowchart

```
read("embed_0003")
        │
        ▼
┌───────────────────────┐
│  HybridRegistry.get() │  ── hit? ──▶  return entry.data   [Tier 1 — O(1)]
└───────────┬───────────┘
            │ miss
            ▼
┌───────────────────────┐
│  _entries.get(name)   │  ── hit? ──▶  registry.put(entry)
│  (TDSDirectory dict)  │              return entry.data    [Tier 2 — O(1)]
└───────────┬───────────┘
            │ miss (_LazyEntry or cold)
            ▼
┌───────────────────────┐
│  SlotIndex.lookup()   │
│  Adler32(name)        │
│  _slot_binary_search  │  ← Numba O(log n)
│  → SlotRecord         │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  mmap[abs_offset:     │
│       abs_offset+len] │  ← single kernel call, zero copy
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  _deserialise()       │
│  COMPRESSED? → zlib   │
│  NUMPY_MATRIX → load  │
│  PICKLE_OBJ  → loads  │
│  SYMBOL_TABLE→ loads  │
└───────────┬───────────┘
            │
            ▼
     registry.put(entry)
     return data          [Tier 3 — O(log n) + I/O]
```

---

## Write Path Flowchart

```
TDSWriter.write(directory)
        │
        ├─ parallel serialise (ThreadPool)
        │       ┌─────────────────────────────────┐
        │       │ NUMPY_MATRIX → np.save() bytes  │
        │       │ PICKLE_OBJ   → pickle proto 5   │
        │       │ COMPRESSED   → zlib.compress()  │
        │       └─────────────────────────────────┘
        │
        ├─ build SlotIndex
        │       for each entry:
        │         hash = Adler32(name) & 0x7FFF...
        │         record (hash, offset, length, fmt_id)
        │         cursor += len(payload)
        │
        ├─ open  <name>.tds~   (shadow file)
        │
        ├─ write placeholder header (44 bytes)
        ├─ write data block (all payloads concatenated)
        ├─ write SlotIndex block
        │
        ├─ seek(0)
        ├─ overwrite header with real offsets + CRC32
        │
        ├─ f.flush()
        ├─ os.fsync(fd)
        │
        └─ shutil.move(".tds~" → ".tds")   ← ATOMIC
```

---

## Directory Tree Flowchart

```
TDSFileSystem("asi_root")
│
├── TDSDirectory  "databases"        PARALLEL_IO | PROB_SORT
│   ├── TDSDirectory  "vectors"      NUMPY_MATRIX | COMPRESSED
│   │   ├── TDSEntry  "embed_0000"   float32[64,64]
│   │   ├── TDSEntry  "embed_0001"   float32[64,64]
│   │   └── TDSEntry  "embed_N..."   float32[64,64]
│   │
│   └── TDSDirectory  "symbols"      SYMBOL_TABLE | RECURSIVE
│       ├── TDSEntry  "token_v1"     float64[4,4]  ← symbol IDs
│       └── TDSEntry  "token_v2"     float64[4,4]
│
├── TDSDirectory  "working_memory"   LOOP_PINNED
│   └── LoopCacheManager
│       └── LoopCacheSlot  "grad_buf"   cycle=8
│
└── TDSDirectory  "logs"
    └── TDSDirectory  "audit"
        ├── TDSEntry  "event_000000"  dict
        ├── TDSEntry  "event_000001"  dict
        └── ...

On disk (flat layout, mount dir):
  asi_root.tds
  asi_root__databases.tds
  asi_root__databases__vectors.tds         ← 91,953 bytes (6 × 64×64 f32)
  asi_root__databases__symbols.tds         ← 622 bytes
  asi_root__logs.tds
  asi_root__logs__audit.tds               ← 788 bytes (8 log events)
```

`/` separators in directory paths are replaced with `__` in filenames, keeping all `.tds` files in a flat mount directory. O(1) glob to list every file in the system.

---

## Concurrency Model

```
                    ConcurrencyPool (singleton)
                           │
          ┌────────────────┼────────────────┐
          │                │                │
   ThreadPoolExecutor  ProcessPoolExecutor  asyncio loop
   (64 workers)        (8 workers)          (daemon thread)
          │                │                │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌─────▼──────┐
   │ parallel    │  │ CPU-bound   │  │ async      │
   │ mmap reads  │  │ compression │  │ coroutines │
   │ registry ops│  │ serialise   │  │            │
   │ flush nodes │  │             │  │            │
   └─────────────┘  └─────────────┘  └────────────┘
```

**Thread safety:** Every `TDSDirectory` and `HybridRegistry` uses `threading.RLock`. Concurrent reads never block each other — only writes acquire exclusive access. The mmap is opened `ACCESS_READ` and is safe for unlimited concurrent readers on the same fd.

**Parallel flush:** `ParallelFlusher` enqueues directory nodes and calls `pool.map_parallel(_flush, nodes)` — every node writes its own `.tds~` shadow file simultaneously, then renames atomically. Nodes do not share file handles so there is zero cross-node contention.

---

## Quick Start

```python
from tds_filesystem import TDSFileSystem, FmtID, DirFlags
from tds_persistence import TDSPersistence, TDSReader
import numpy as np

# ── Build the FS in memory ────────────────────────────────────────
fs     = TDSFileSystem("asi_root")
vec_db = fs.makedirs("databases/vectors",
                      fmt_id=FmtID.NUMPY_MATRIX,
                      flags=DirFlags.PARALLEL_IO | DirFlags.PROB_SORT)

# Write compressed numpy matrices
for i in range(100):
    mat = np.random.randn(512, 512).astype(np.float32)
    vec_db.write(f"embed_{i:04d}", mat,
                 fmt_id=FmtID.NUMPY_MATRIX, compress=True)

# Register a loop-cache slot (overwrites every 16 writes)
wm = fs.makedirs("working_memory", flags=DirFlags.LOOP_PINNED)
wm.loop_cache.register("grad_buf", cycle=16)

# Symbol table — swap across an entire matrix instantly
sym = fs.makedirs("tokens", flags=DirFlags.RECURSIVE)
sym.symbols.intern("PAD")
sym.symbols.intern("START")
token_mat = np.zeros((32, 32))
swapped   = sym.symbols.swap("PAD", "START", token_mat)

# ── Flush everything to disk ──────────────────────────────────────
persist = TDSPersistence("/var/tds/asi")
persist.mount(fs)
report  = persist.flush(fs, parallel_nodes=True)
persist.unmount()

# ── Read back with random-access reader ──────────────────────────
with TDSReader("/var/tds/asi/asi_root__databases__vectors.tds") as r:
    mat        = r.read("embed_0042")          # single O(log n) seek
    all_embeds = r.read_many(r.keys())         # parallel mmap reads
```

---

## API Reference Summary

### `TDSFileSystem`

| Method | Returns | Description |
|---|---|---|
| `__init__(name)` | — | Create FS with named root directory |
| `makedirs(path, **kwargs)` | `TDSDirectory` | mkdir -p style creation |
| `resolve(path)` | `TDSDirectory` | Walk path string → node |
| `parallel_batch_write(writes)` | `None` | Fan out `[(path, name, value)]` writes |
| `snapshot_headers()` | `Dict[str, dict]` | Decode headers of every node in tree |

### `TDSDirectory`

| Method | Returns | Description |
|---|---|---|
| `write(name, value, fmt_id, compress)` | `TDSEntry` | Store a variable |
| `read(name)` | `Any` | Retrieve a variable (3-tier path) |
| `delete(name)` | `None` | Remove an entry |
| `mkdir(name, **kwargs)` | `TDSDirectory` | Create sub-directory |
| `cd(name)` | `TDSDirectory` | Navigate to child |
| `ls(sort_by_prob)` | `List[str]` | List contents, optionally prob-sorted |
| `parallel_read_all()` | `Dict[str, Any]` | Read all entries via pool |
| `recursive_join(dtype, max_depth)` | `np.ndarray` | Concatenate all numpy arrays in subtree |
| `build_offset_index()` | `np.ndarray` | Compute seek offsets via Numba |
| `to_bytes()` | `bytes` | Serialise node to binary buffer |
| `header_bytes()` | `bytes` | Generate 36-byte binary header |
| `path()` | `str` | Full path string from root |

### `TDSReader`

| Method | Returns | Description |
|---|---|---|
| `read(name)` | `Any` | O(log n) seek + deserialise |
| `read_raw(name)` | `bytes` | Raw compressed payload |
| `read_many(names)` | `Dict[str, Any]` | Parallel mmap reads |
| `keys()` | `List[str]` | All entry names in file |
| `__contains__(name)` | `bool` | Membership test |
| `close()` | `None` | Release mmap and fd |

### `TDSWriter`

| Method | Returns | Description |
|---|---|---|
| `write(directory, recurse)` | `int` | Atomic flush, returns bytes written |
| `write_parallel(directory)` | `int` | Parallel serialise then atomic flush |

### `TDSPersistence`

| Method | Returns | Description |
|---|---|---|
| `mount(fs)` | `None` | Attach FS to this persistence object |
| `flush(fs, parallel_nodes)` | `Dict[str, int]` | Write all nodes, returns `{path: bytes}` |
| `flush_node(node, parallel)` | `Tuple[str, int]` | Write single node |
| `load_node(path, into)` | `TDSDirectory` | Read `.tds` file → directory (lazy) |
| `unmount()` | `Dict[str, int]` | Flush + close all readers |

---

## File Naming Convention

TDS uses a **flat mount layout**. All `.tds` files for a given `TDSFileSystem` live in one directory with path separators encoded as double underscores:

| Virtual Path | Filename on Disk |
|---|---|
| `/asi_root` | `asi_root.tds` |
| `/asi_root/databases` | `asi_root__databases.tds` |
| `/asi_root/databases/vectors` | `asi_root__databases__vectors.tds` |
| `/asi_root/databases/symbols` | `asi_root__databases__symbols.tds` |
| `/asi_root/logs/audit` | `asi_root__logs__audit.tds` |

Benefits: O(1) glob to enumerate all files in the system. No subdirectory traversal. No kernel directory-entry overhead. Every file independently readable via `TDSReader` without mounting the full FS.

---

## Performance Characteristics

| Operation | Complexity | Notes |
|---|---|---|
| `write(name, value)` | O(1) amortised | Dict insert + registry put |
| `read(name)` — Tier 1 hot | O(1) | OrderedDict lookup |
| `read(name)` — Tier 2 cold | O(1) + zlib | Dict lookup + optional decompress |
| `read(name)` — Tier 3 disk | O(log n) + I/O | Numba binary search + mmap slice |
| `ls(sort_by_prob=True)` | O(n log n) | Numba argsort over decay scores |
| `recursive_join()` | O(total elements) | Tree walk + numpy concat |
| `build_offset_index()` | O(n) Numba | Prefix sum via JIT kernel |
| `flush(fs, parallel=True)` | O(nodes) parallel | One thread per node, concurrent writes |
| `read_many(names)` | O(n) parallel | One thread per name, concurrent mmap |
| `_matrix_symbol_swap` | O(rows × cols) JIT | Numba prange parallel rows |
| `SlotIndex.lookup()` | O(log n) | Numba binary search |
| `SlotIndex._rebuild()` | O(n log n) | Triggered lazily, cached |

---

## Dependency Matrix

| Library | Role | Required? |
|---|---|---|
| `numpy` | Matrix storage, JIT arrays, dtype system | **Yes** |
| `numba` | JIT compilation of all math kernels | No — shim provided |
| `zlib` | Compression (level 3 write, level 6 heavy) + CRC32 | **Yes** (stdlib) |
| `pickle` | Python object serialisation protocol 5 | **Yes** (stdlib) |
| `struct` | Binary header pack / unpack | **Yes** (stdlib) |
| `mmap` | Zero-copy random-access disk reads | **Yes** (stdlib) |
| `concurrent.futures` | Thread + process pool | **Yes** (stdlib) |
| `asyncio` | Async coroutine support in pool | **Yes** (stdlib) |
| `threading` | RLock, daemon loop thread | **Yes** (stdlib) |
| `uuid` | Unique directory + entry IDs | **Yes** (stdlib) |

Install with Numba for full performance:
```bash
pip install numpy numba
```

Run without Numba (pure Python fallback, all kernels still functional):
```bash
pip install numpy
```

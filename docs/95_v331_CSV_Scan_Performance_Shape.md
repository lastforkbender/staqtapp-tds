# v3.3.1 — CSV Scan Performance Shape Pass

TDS v3.3.1 keeps the CSV scan/kernel lane narrow and performance-oriented while preserving the v3.2.x/v3.3.x boundary rules. The work remains above TDS storage and does not add CSV behavior to the native C storage hot path.

## Scope

- Broadens the CSV scan reference to accept buffer-backed inputs through `memoryview(...)`, including `bytes`, `bytearray`, `memoryview`, and mmap-style objects.
- Keeps text helpers encode-once and delegates scanning to the byte/memoryview scanner.
- Removes the second-pass temporary span list from scan profile generation by tracking maximum logical record span during the scan.
- Removes unnecessary offset re-filtering after the scanner has already guaranteed in-bounds logical record starts.
- Adds packed row-offset helpers using a compact little-endian uint64 byte-vector shape:
  - `pack_csv_row_offsets(...)`
  - `unpack_csv_row_offsets(...)`
- Adds a dependency-free benchmark script for local CSV scan throughput comparisons:
  - `benchmarks/benchmark_v331_csv_scan.py`

## Non-goals

- No native CSV kernel yet.
- No changes to the native C storage engine.
- No change to the fixed CSV import artifact write count.
- No per-cell or per-row TDS writes.
- No semantic CSV IR, seed registry, or stack runner.
- No README/API PDF regeneration during this intermediate CSV lane.

## Performance shape

```text
CSV bytes / bytearray / memoryview / mmap-like buffer
   ↓ memoryview(raw).cast("B")
Python reference scanner
   ↓ single scan loop
row offsets + mechanical counters + max record span
   ↓ optional compact uint64 offset packing helper
future native sidecar parity target
```

The packed offset helpers are deliberately not wired into the durable import artifact set yet. They define a compact future artifact shape without changing compatibility or the current JSON row-offset contract.

## Boundary discipline

CSV scan optimization remains observational and mechanical. It reads immutable payload bytes, returns compact facts, and does not own storage commits or locks.

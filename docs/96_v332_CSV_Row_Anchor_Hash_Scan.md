# v3.3.2 — CSV Row Anchor Hash Scan

TDS v3.3.2 extends the v3.3.x CSV scan/kernel lane with opt-in row-anchor hashing. The pass remains mechanical and read-only: it derives exact byte hashes for logical CSV records from the preserved source bytes and current row-offset scan, without adding CSV behavior to the native storage engine.

## What changed

- Added `CSVRowAnchorProfile` for exact per-logical-record byte anchors.
- Added `CSVRowAnchorParityReport` for read-only parity checks against durable CSV artifacts.
- Added `scan_csv_row_anchors(...)` for bytes, bytearray, memoryview, and mmap-style buffers.
- Added `scan_csv_text_row_anchors(...)` for encode-once text input.
- Added `validate_csv_row_anchors(...)` for durable artifact parity.
- Added row-anchor tests for quoted newlines, doubled quotes, buffer-backed inputs, chunk boundaries, and fail-closed row-offset drift.
- Added `benchmarks/benchmark_v332_csv_row_anchors.py` as a dependency-free local benchmark helper.

## Architecture boundary

Row anchors are scan evidence, not semantic identity. Each anchor hash covers the exact source bytes for one logical record, including the row terminator when present. This makes future Semantic IR work easier to ground in immutable source bytes while keeping the current release above storage and free of per-cell writes.

```text
raw CSV bytes
   ↓ memoryview scan
logical row offsets
   ↓ exact byte slices
row-anchor sha256 evidence
   ↓ read-only parity report
future Semantic IR / governance layer
```

## Preserved discipline

- No native C storage-engine changes.
- No CSV intelligence in the storage hot path.
- No README.md or README_ja.md update.
- No API PDF regeneration.
- No new import artifacts.
- No per-cell writes.
- Row-anchor generation is opt-in so routine scan profiles remain compact.

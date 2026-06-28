# Changelog

## v2.1.0 — Measured GIL, Chunking, and Table-Depth Seams

- Added EntryIndex.get_handles() for batch handle lookup; native backend releases the GIL across the batch lookup loop.
- Moved the native pop lookup/delete path under GIL-released native locking.
- Extended native Swiss-table stats with tombstones, load factor, max probe, and average probe length.
- Changed chunked text splitting to UTF-8 byte-budget chunks that never split a code point.
- Added radix router stats for max depth, average edge length, and average lookup steps.
- Added v2.1.0 tests covering Unicode chunking, batch lookups, tombstone reuse, and radix observability.

## v2.1.0 — Extended Speed Targets

### Added

- Native Swiss-table-inspired EntryIndex backend.
- Swiss-style control-byte hash fingerprints.
- Triangular probing in native handle table.
- GIL-released native `get_handle()` and `contains()`.
- Python `RadixDirectoryRouter` for compressed-prefix directory routing.
- `TDSFileSystem.resolve_radix()` direct radix path seam.
- `radix_router` and `swiss_table_index` capability flags.
- Tests for radix prefix behavior, radix path resolution, native Swiss stats, and concurrent native reads.

### Preserved

- Pure Python fallback backend.
- Public TDS Python API.
- Variable control semantics: `addvar`, `editvar`, `lockvar`, `unlockvar`, `stalkvar`.
- Text payload behavior.
- Provenance and cluster metadata.
- EntryIndex facade boundary.

### Performance notes

The native backend avoids the GIL only during native key-to-handle lookup and contains checks. Returning Python objects, serialization, compression, persistence, and variable manipulation remain Python-governed.

### Validation

- `pytest`: 34 passed.
- Native build smoke test: passed.
- Native Swiss stats verified.
- Concurrent native read safety test: passed.

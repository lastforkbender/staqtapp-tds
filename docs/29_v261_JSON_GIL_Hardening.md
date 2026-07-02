# v2.6.1 JSON and GIL Hardening

v2.6.1 is a hardening/performance release. It does not widen the public API surface with decorative features. The release centralizes JSON policy and extends native/GIL-free batch work in the chunk verification path.

## Central JSON boundary

All runtime JSON should flow through `staqtapp_tds.tds_json`:

- `loads_fast()` uses `simdjson` when installed and falls back to the standard library.
- `loads_manifest()`, `loads_snapshot()`, and `loads_policy()` provide strict typed entry points.
- `dumps_canonical()` uses `orjson` when installed and falls back to deterministic stdlib JSON.
- `dumps_pretty()` is reserved for admin/CLI/human output.

The module is intentionally stateless: no shared parser object, no reusable global buffers, no retained simdjson document references, and no direct engine locks.

## Native/GIL expansion

The optional native extension now exposes `checksum32_many()`, a batch checksum primitive for chunk verification. The chunked-text path uses this to verify chunk batches in one native/GIL-released operation when the extension is available.

This continues the v2.6 design rule:

```text
Python calls native once
native loops over the batch with the GIL released
Python receives compact results
```

## Chunk verification

Chunked UTF-8 manifests now carry per-chunk `chunk_checksums32` metadata and a `chunk_checksum_backend` label. Reads validate chunk checksums and the full content hash before returning reconstructed text.

Failure behavior remains strict:

```text
checksum mismatch -> quarantine transition -> error
```

## Telemetry

Telemetry now has JSON boundary counters for parse/serialize cost, simdjson read count, and orjson write count. Snapshot consumers can compare GIL release improvements, Python/native transition pressure, and JSON overhead without touching live engine structures.

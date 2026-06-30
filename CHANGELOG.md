# Staqtapp-TDS v2.4.2

## v2.4.2 — Metadata and Native Execution Hardening

- Added `staqtapp_tds.version` and centralized `__version__ = "2.4.2"`.
- Added compact immutable `staqtapp_tds.metadata` records using `@dataclass(slots=True, frozen=True)`.
- Re-exported Spiral trace, trace-set, and aggregation records from the metadata package while preserving the optional `staqtapp_tds.spiral` API.
- Added richer ranking provenance fields: rank method, confidence, rank config id, and verifier id.
- Fixed and validated native extension build configuration with `setup.py`.
- Added GIL-released native batch insert and batch erase paths.
- Added internal tiny-key memory-pool reuse counters for the native Swiss index.
- Added native checksum and UTF-8-safe chunk-boundary helper functions.
- Added execution telemetry fields for pool reuse and allocator calls.
- Updated the professional dashboard system panel to display pool reuse and allocator-call feedback.
- Added v2.4.2 tests for slotted metadata, native batch put/pop, native checksum/chunk bounds, and pool telemetry.

## v2.4.0 — Native Performance Expansion

- Added execution-mode telemetry for native %, Python %, GIL-released %, batch operations, and Python↔native transition rate.
- Added native Swiss-table counters for put, lookup, batch lookup, pop, stats, GIL-released calls, and transitions.
- Changed the native Swiss-table put path to release the GIL while performing native table insertion/update.
- Preserved the professional dashboard as a separated snapshot-only subsystem.
- Added dashboard fields for native execution and Python/native boundary activity.
- Added tests for execution telemetry, native execution counters, and dashboard fields.

## v2.3.7 — Optional Spiral-Compatible Trace Support

- Added `staqtapp_tds.spiral` optional workflow module.
- Added directory-first Spiral-style run helpers:
  - `create_spiral_run()`
  - `SpiralRun.store_search_trace()`
  - `SpiralRun.create_trace_set()`
  - `SpiralRun.store_aggregation()`
  - `SpiralRun.store_final()`
- Added neutral metadata records:
  - `TraceRecord`
  - `TraceSetManifest`
  - `AggregationRecord`
- Added external trace-rank metadata storage without making TDS perform ranking.
- Added Spiral/pipeline telemetry counters to `TelemetryManager` snapshots.
- Added `RuntimeConfig.spiral_support_enabled` policy flag.
- Updated README to reflect current telemetry, semantic storage, professional dashboard, and optional Spiral trace workflow support.
- Cleaned old runtime-source version banners so package versioning is centralized.

## v2.3.5 — Professional Dashboard

- Added professional dark blue/purple/orange admin dashboard structure.
- Added packaged HTML, CSS, JS, and SVG admin assets.
- Added live architecture, timeline, and recommendation-oriented dashboard sections.
- Preserved snapshot-only dashboard refresh behavior.

## v2.3.0 — Observation Layer

- Added `TelemetryManager` and cached dashboard-facing snapshots.
- Added low-interference performance, storage, behavior, index, and recommendation telemetry.

## v2.2.x — Admin Control Plane

- Added local admin panel, RuntimeConfig generation staging/promotion/rollback, local grants, and audit log.

## v2.1.x — Performance Seams

- Added UTF-8 byte-safe chunking, batch EntryIndex lookup, native backend seams, and stronger radix/Swiss-table measurements.

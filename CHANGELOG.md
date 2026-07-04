# Changelog

## v2.8.9 — Spiral Rank Statistics

- Added `SpiralRankStats` for immutable per-run observer statistics.
- Added `SpiralRankRun` and `rank_trace_run(...)` for returning rank results plus stats in one bundle.
- Added `NativeSpiralRankEngine.rank_run(...)` while preserving the existing list-returning `rank(...)` API.
- Captured input/ranked/limited/drop counts, native/fallback path, elapsed/scoring/sorting/shaping timings, min/max/mean score, warnings, and config id.
- Added v2.8.8 tests covering stats shape, limit accounting, empty-run safety, helper export, and `last_stats`.
- Updated English and Japanese README files with the v2.8.8 stats workflow.

## v2.8.8 — Native Spiral Rank Engine

- Added `staqtapp_tds.spiral.rank` with `NativeSpiralRankEngine`, `SpiralRankConfig`, `SpiralRankResult`, and `rank_traces`.
- Added native C-extension `spiral_rank_scores` scoring loop with GIL release and Python fallback.
- Kept Spiral ranking isolated from the storage hot path: copied numeric metadata in, immutable rank results out.
- Added v2.8.8 rank tests covering deterministic ordering, native/Python score equivalence, result shape, and validation.
- Rebuilt bilingual README files with English/Japanese links and unicode flags.

## v2.8.1 — Admin Browser Security Hotfix

- Added per-server CSRF tokens for browser/admin state-changing POST routes.
- Added Origin/Referer rejection for admin POST mutations.
- Reworked dynamic dashboard renderers to use DOM nodes/textContent instead of innerHTML.
- Hardened malformed Content-Length handling in the admin panel.
- Hardened browser settings parsing and exposed language-pack fallback status.
- Preserved the native storage engine and all storage hot-path behavior.

## 2.8.1

- Added external TDS Browser language packs under `static/i18n/` for English, Spanish, Portuguese, Japanese, German, French, and Italian.
- Localized the Browser Operations Console pages, navigation, Settings page, telemetry labels, About dialog, advisory text, and snapshot-page labels through a shared language manager.
- Preserved stable native telemetry keys and engine payloads; only browser presentation text is translated.
- Added language-pack manifest loading with English fallback and localStorage-backed language selection.
- Added tests that verify language-pack packaging, complete key coverage across all seven languages, and key technical terminology translations.
- Left the native storage engine unchanged; v2.8.1 is a browser localization and language-pack quality release.

## 2.7.9

- Completed Browser Operations Console telemetry pages for Snapshot Explorer, Lock Contention, Comparative Views, and Alerts & Events.
- Preserved the v2.7.8 Settings/i18n foundation.
- Left the native storage engine unchanged; v2.7.9 is a browser telemetry completion release.

## 2.7.8

- Added a dedicated TDS Browser Settings page focused on General browser preferences.
- Added local language selection for English, Spanish, Portuguese, Japanese, German, French, and Italian.
- Added startup page selection stored in browser localStorage.
- Added refresh interval selection with manual refresh support.
- Added a polished About TDS Browser dialog with version and visual-system information.
- Added layout-safe localization CSS so long translated labels wrap inside cards/panels instead of expanding horizontally into neighboring panels.
- Left the native storage engine unchanged; v2.7.8 is a browser settings/localization foundation release.

## 2.7.5

- Fixed `/status.json` live telemetry by importing `dumps_pretty` in `admin/panel.py`.
- Fixed diagnostics page grid alignment by using a dedicated diagnostics grid.
- Fixed the Health Ring so its conic-gradient reflects the current health score.
- Wired the workload Maintenance legend to live telemetry and adjusted the donut rendering.
- Eliminated workload percentage rounding drift by deriving the final bucket from the remaining percentage.
- Added `title` and `aria-label` metadata to left navigation links for the collapsed sidebar.
- Removed hidden leftover dashboard markup and unused JavaScript helper code.
- Cleaned fragile CSS leftovers, including stale sidebar variables and shadowed pressure-grid column rules.
- Kept Recovery Planner advisory-only and preserved snapshot-only dashboard data flow.

## 2.7.4

- Added advisory Recovery Planner observer module.
- Integrated recovery plans into telemetry snapshots.
- Added dashboard Recovery Planner rendering with action cards, confidence, primary subsystem, and guardrails.
- Preserved native diagnostics hot-path isolation and snapshot-only browser behavior.
- Added v2.7.4 tests for recovery planning and browser integration.

# v2.7.1

- Added named native diagnostic transition taxonomy for slot lifecycle, index events, memory pool transitions, and snapshot markers.
- Expanded diagnostic event ring capacity to 4096 fixed-width events with occupancy, capacity, and wraparound counters.
- Enriched Python diagnostic snapshots with event/subsystem names for browser rendering while preserving fixed-width native events.
- Added Dashboard transition-ring panel showing ring occupancy and recent native transition events.
- Added v2.7.1 tests for transition taxonomy, event enrichment, and ring accounting.

# v2.7.0

- Centralized JSON parsing and emission in `staqtapp_tds.tds_json` with simdjson-aware reads, orjson canonical writes, strict manifest/snapshot/policy loaders, and stdlib fallback.
- Added native `checksum32_many()` for batch chunk checksum verification with the GIL released when the optional extension is available.
- Added per-chunk checksum metadata for chunked UTF-8 text and read-time checksum/content-hash validation before reconstructed text is returned.
- Added telemetry counters for JSON parse/serialize calls, simdjson reads, orjson writes, and average JSON boundary timing.
- Added v2.7.0 tests for JSON centralization, malformed/strict loaders, native batch checksum parity, chunk corruption detection, and telemetry counters.

# v2.6.0

- Added ASI Storm pressure model with explicit pressure modes and semantic VFS states.
- Added chunk lifecycle telemetry counters for pending, sealed, verified, indexed, exposed, and quarantined states.
- Added dashboard pressure panels with custom SVG icons in the blue/purple/orange theme.
- Added immutable snapshot pressure payloads for browser-only observation and backpressure feedback.
- Routed UTF-8 chunk boundary scanning through the optional native extension when available so large chunk scans can release the GIL before Python manifest commits.
- Added documentation for ASI Storm operations, one-way telemetry isolation, and pressure-mode behavior.

# Staqtapp-TDS v2.5.1

## v2.5.0 — Hardening and One-Way Telemetry

- Added `TelemetryLevel` with `OFF`, `MINIMAL`, `NORMAL`, `ENGINEERING`, and `DEVELOPER` snapshot detail modes.
- Added `TelemetryPublisherThread` so dashboards/exporters read the latest immutable snapshot instead of triggering storage-engine sampling directly.
- Added health state to observation snapshots: status, score, degraded components, snapshot age, telemetry level, and publisher timing.
- Added `staqtapp_tds.verify` with explicit health checks for telemetry snapshots, runtime config, directory traversal, index consistency, and component status.
- Added CLI health verification with `staqtapp-tds-admin verify`.
- Added `RuntimeConfig.telemetry_level` validation for deployment-specific observability levels.
- Added optional native sanitizer build hooks through `STAQTAPP_TDS_SANITIZE`.
- Preserved the dashboard as a separated snapshot-only subsystem; hardening checks are explicit and never run from normal dashboard polling.
- Kept v2.4.2 slotted metadata, native batch paths, checksum/chunk helpers, and memory-pool telemetry intact.

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


## 2.7.3

- Redesigned the browser Operations Console toward the polished Pressure Diagnostics mockup style.
- Added categorized left navigation for overview, diagnostics, analytics, operations, and configuration.
- Added shared console page shells for Snapshot Explorer, Lock Contention, Comparative Views, Recovery Planner, and Alerts & Events.
- Preserved snapshot-only browser behavior and all v2.7.2 pressure telemetry IDs.

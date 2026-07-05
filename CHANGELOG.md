## v3.1.2 - Driver Foundry API

### Added
- Added `DriverFoundry`, an AI-safe build/test/candidate API for rapid driver generation.
- Added `DriverFoundryResult`, `DriverFoundryContext`, `FoundryFault`, `FoundryStage`, `FoundryStatus`, and `DriverFoundryPolicy`.
- Added `foundry_capability_matrix()` for Studio/AI surfaces to display allowed and denied authority.
- Added documentation: `docs/56_v312_Driver_Foundry_API.md`.

### Safety
- The Foundry can validate, compile, audit, test, and submit candidates, but cannot approve, sign, activate, bypass policy, write storage, or execute arbitrary Python.
- Expected source, package, fixture, runtime, and policy failures return structured Foundry results instead of halting the host.
- Foundry test results embed `DriverVMResult` so repair loops receive VM faults, trace, cost, metrics, and context.
- Candidate submission requires successful runtime test evidence by default and only creates `DriverState.CANDIDATE` records.

### Testing
- Added tests for the Foundry authority matrix, success path, runtime-fault repair feedback, structured source rejection, candidate evidence requirements, candidate-only submission, policy rejection, bad fixture handling, and disabled candidate submission.

## v3.1.1 - Driver VM Non-Halting Result Framework

### Added
- Added `DriverVMResult`, a VM-specific non-halting execution envelope inspired by `TDSResult` but extended for driver execution evidence.
- Added `VMStatus`, `VMFault`, and `DriverVMContext` for structured status, fault, metrics, trace, package, and instruction context reporting.
- Kept `VMExecutionResult` as a backwards-compatible public alias.
- Added documentation: `docs/55_v311_Driver_VM_Non_Halting_Result_Framework.md`.

### Safety
- `DriverVMRuntime.execute()` now returns structured results for expected runtime faults instead of raising Python exceptions into the host.
- Bad inputs return `INPUT_REJECTED`; unloaded execution returns `NOT_LOADED`; budget overflow returns `BUDGET_EXCEEDED`; unsupported runtime semantics return `FAULTED`.
- Unexpected handler errors are contained as `INTERNAL_ERROR` at the VM boundary.
- Runtime record snapshots are deep-copied so driver execution does not mutate caller-provided input.
- Added storage-boundary regression coverage to ensure the Driver VM runtime does not import storage-engine internals.

### Runtime Semantics
- Added deterministic runtime support for `MATCH regex_limited=` and `MATCH range=[low, high]`.
- Tightened `MATCH field=...` validation so field matches require at least one predicate operand.
- Unsupported-but-validated operands/adapters now fault explicitly instead of being silently ignored.

### Testing
- Added tests for `DriverVMResult` context, non-loaded execution, bad input, budget overflow, unsupported operands, unsupported adapter execution, regex/range predicates, input immutability, internal-error containment, and storage-boundary imports.


## v3.1.0 - Driver VM Runtime

### Added
- Added `DriverVMRuntime`, the first deterministic executable Driver VM runtime for validated `.tdd` bytecode packages.
- Added runtime support for the safe v1 opcode set: `SCAN`, `READ`, `MATCH`, `EXTRACT`, `SCORE`, `TRACE`, `EMIT`, and `HALT`.
- Added deterministic execution against caller-provided in-memory `.tds` record snapshots.
- Added runtime trace events, emitted result payloads, cost accounting, and fail-closed runtime results.
- Kept `DriverVMSkeleton` as the non-executing audit loader for Studio/contract workflows.
- Added documentation: `docs/54_v310_Driver_VM_Runtime.md`.

### Safety
- Runtime execution remains separate from the Native Storage Engine and receives no storage-internal handles.
- Bytecode must still pass package hash, opcode, driver-class, capability, and budget validation before execution.
- Malformed inputs and unsupported runtime conditions fail closed.

### Testing
- Added execution tests for search and extraction drivers, disabled skeleton behavior, invalid input rejection, and cost-budget enforcement.


## v3.0.9 - Driver Studio Class A Quick Test

### Added
- Non-GUI Driver Studio certification quick-test model.
- Ordered Studio gates: learn, syntax, capabilities, bytecode, VM audit, VM load, registry policy, signing and complete.
- `studio_instruction_reference()` for a future minimal PyQt5 Learn panel/editor.
- `run_studio_quick_test()` to prove validated TDDL can progress through compile, audit, load, policy, sign and activate without execution.
- Documentation: `docs/53_v309_Driver_Studio_Quick_Test.md`.

### Safety
- The Studio quick-test is non-executing. It does not replace the Builder, VM audit, registry, or future native VM runtime.
- Gates are fail-closed and cannot be skipped.

# Changelog

## v3.0.9 - VM Contract Audit + Driver VM Skeleton

### Added
- Added a non-executing VM contract audit layer for compiled TDDL bytecode packages.
- Added `VMInstructionContract`, `vm_contract_table()`, and `audit_vm_contract()`.
- Added a native-facing `DriverVMSkeleton` loader with fail-closed validation.
- Added `VMLoadedPackage`, `VMExecutionResult`, and `VMState`.
- Added documentation: `docs/52_v308_VM_Contract_Audit_Skeleton.md`.

### Safety
- VM loading now validates opcode/name consistency, package hash integrity, driver-class permissions, required capabilities, instruction-count budget, and instruction-cost budget.
- Bytecode execution remains intentionally disabled in v3.0.9.
- The future Driver VM remains separate from the Native Storage Engine.

### Testing
- Added VM contract and loader tests for valid packages, class denial, missing capabilities, tampering, opcode mismatch, disabled execution, and budget rejection.

# v3.0.6 - TDDL Grammar Validation

## v3.0.9 - TDDL Bytecode Package

### Added
- Non-executing TDDL bytecode package model for future native Driver VM.
- Stable v1 opcode mapping for SCAN, READ, MATCH, EXTRACT, SCORE, EMIT, TRACE, HALT.
- Deterministic constant pool, source hash, and package hash generation.
- Bytecode package serialization and round-trip decompilation back to readable IR.
- Tamper-evident bytecode validation tests.

### Safety
- Invalid TDDL never reaches bytecode.
- Unsupported future instructions fail closed instead of being encoded prematurely.
- Bytecode packages must end with exactly one HALT and verify their package hash.

### Compatibility
- No storage format change.
- No native VM execution added yet.
- Existing v3.0.6 grammar validation remains intact.


- Added non-executing TDS Driver Language (TDDL) parser and strict validation layer.
- Added self-describing instruction metadata table for future Builder/Studio.
- Added SCAN/READ/MATCH/EXTRACT/SCORE/EMIT/HALT parameter validation.
- Added fail-closed tests for unsafe scope traversal, undeclared adapters, unsafe adapter names, bad thresholds, unsupported operands, and missing HALT.
- Kept Driver VM execution out of v3.0.6; this release defines syntax contracts only.

# v3.0.6 - Driver Foundation Testbed

## Added

- Added non-executing `staqtapp_tds.drivers` foundation namespace for the future native Driver VM.
- Added draft driver manifest model, deterministic validation, and canonical signing payloads.
- Added registry state model covering candidate, approved, signed, active, retired, and revoked drivers.
- Added mock signature policy tests for unsigned, bad, unknown, revoked, and accepted signatures.
- Added deterministic trace-ranking fixtures for future semantic search/extraction drivers.
- Added `docs/49_v305_Driver_Foundation_Testbed.md`.

## Compatibility

- No storage format changes.
- No public storage API changes.
- No driver execution added in this release.
- Native Storage Engine remains separate from the future Driver VM.

## v3.0.4 — Admin Origin Fail-Closed Safety Patch

- Hardened admin panel POST origin validation so requests missing both `Origin` and `Referer` are rejected instead of accepted.
- Preserved explicit CSRF token validation on `/stage`, `/promote`, and `/rollback`.
- Added regression tests for missing, valid, and invalid admin origin/referer combinations.
- Added documentation for the v3.0.4 admin origin fail-closed patch.

## v3.0.4 — Class A Pickle Boundary

### v3.0.4 Serialization Manager reinforcement

- Added first-class `staqtapp_tds.serialization` subsystem with `SerializationManager`, `CodecRegistry`, and `EncodedPayload`.
- Routed storage payload encode/decode through the Serialization Manager instead of direct format branching in the filesystem hot path.
- Kept pickle support for Python variable compatibility, but isolated it behind the restricted pickle codec and TDS pickle policy boundary.
- Updated `addvar/loadvar/findvar/read/stalkvar` validation coverage for JSON-safe values, bytes, complex Python variables, and legacy pickle migration payloads.
- Refreshed stale legacy tests for the current non-halting `TDSResult` public read API and v3.0.4 version expectations.


- Added `staqtapp_tds.tds_pickle` as the sole pickle policy boundary.
- Replaced direct storage-path `pickle.dumps` / `pickle.loads` calls with `dumps_pickle()` and `loads_pickle()`.
- Added TDS pickle envelope marker for newly written Python-object compatibility payloads.
- Added restricted unpickling by default with a small allowlist of stable Python value classes.
- Added write-time restricted-reader validation so unsupported custom objects fail before being stored.
- Preserved safe legacy pickle reads for unenveloped payloads; unsafe arbitrary-object legacy reads require `TDS_ALLOW_UNSAFE_PICKLE=1`.
- Added tests for envelope roundtrip, malicious global rejection, custom-object write rejection, and legacy safe payload compatibility.

# v2.9.4 - Result Registry Source of Truth

- Added `TDSResultCode`, the authoritative enum for all public `TDSResult.code` values.
- Added `TDS_RESULT_REGISTRY` with category, severity, retryable, surface, value, and description metadata.
- Removed hard-coded `TDSResult` code string literals from public result call sites; call sites now use `TDSResultCode`.
- Added `result_info()` for runtime lookup of code metadata.
- Regenerated `docs/TDS_RESULT_CODES.md` and `docs/TDS_RESULT_CODES.json` from the registry.
- Added tests preventing result-code drift and scattered hard-coded public result code literals.

# v2.9.3 - TDSResult Centralization

- Formalized `TDSResult` as the single public success/error envelope for AI-facing non-halting operations.
- Added `TDS_RESULT_CODES`, `known_result_codes()`, `is_known_result_code()`, and `TDSResult.known_code`.
- Added `docs/API_TDSResult.md` with the full result-code contract.
- Replaced the public Spiral rank row name `SpiralRankResult` with `SpiralRankRecord` to avoid multiple result-envelope titles.
- Added `NativeSpiralRankEngine.rank_result(...)` and `rank_trace_result(...)`, both returning `TDSResult`.

# Changelog

## v2.9.1 — Non-Halting Result Envelope Hardening

- Hardened payload deserialization so decode failures return `TDSResult.fail("PAYLOAD_DESERIALIZE_ERROR", ...)` instead of raw undecoded bytes.
- Added AI-safe `TDSDirectory.read_result(...)`, `write_result(...)`, `delete_result(...)`, and `read_text_result(...)` methods that always return the centralized `TDSResult` envelope.
- Upgraded `TDSResult` to an immutable slotted dataclass with `from_exception(...)`, preserving the standard `{ok, code, message, name, path, value, meta}` pattern.
- Reworked chunked text write failure handling to return `TEXT_CHUNK_WRITE_ERROR` instead of re-raising.
- Added regression tests for non-raw deserialize errors and standard read/write result surfaces.

## v2.8.8 — Spiral Rank Statistics

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
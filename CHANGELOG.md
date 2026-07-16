# v3.5.3 — Guaranteed Storage controlled activation and release qualification

Implemented the complete opt-in path from legacy `.tds` mounts to incremental
immutable segment generations, with verified round-trip migration, explicit
controlled activation, visible operating mode, and lossless rollback into a new
verified legacy mount.

Phase 11 release qualification found and corrected destructive segment-GC
defects: corrupt generations could be omitted from reference accounting, one
reachability proof could be reused across a deletion batch, and a replaced
candidate was not revalidated immediately before unlink. Destructive GC now
fails closed on incomplete generation evidence, repeats reachability for every
candidate and after the final fault boundary, and validates candidate identity
and change metadata before exact unlink accounting.

Release preparation also:

- added explicit root completion records for Phase 10 and Phase 11;
- included the immediate-root Phase 6 through Phase 11 records in source
  distributions so Phase 10 cannot disappear between Phase 9 and Phase 11;
- added corruption, salvage, publication-race, replacement, symlink,
  interruption, concurrency, accounting, and 129-generation soak tests;
- removed the misleading single Dashboard image and false CSV claim;
- added 19 reproducible 1280×800 Browser captures, one for each selected page,
  with the real CSV Interpole Monitor as page 07;
- prepended a rendered, visually verified v3.5.3 release supplement to the
  Programmer Core API Guide and labeled the older v3.1.23 API Surface PDF as
  historical rather than exhaustive for v3.5.3;
- corrected the top spacing of all 634 light-blue API signature strips and
  verified that none intersects the method or class heading above it;
- replaced the independent token-based PyPI workflow with one gated trusted-
  publishing job after Python, platform, native, test, and package validation;
- forced every raw-descriptor TDS, generation, segment, migration-copy, and
  materialization write into Windows binary mode so CRT newline translation
  cannot alter headers, offsets, lengths, checksums, or GC evidence;
- aligned native Spiral score operation boundaries with Python evaluation so
  Apple Clang cannot introduce a one-ULP fused-arithmetic parity difference;
- detached Windows reader snapshots from their source handles so an existing
  reader remains stable without blocking atomic `.tds` replacement;
- set the release identity to v3.5.3 while retaining legacy persistence as the
  default when no explicit storage-mode record exists.

# Documentation refresh - v3.5.2 programmer integration guide

- Added `tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf`.
- Replaced cumulative release-note READMEs with current capability, quick-start, architecture, authority-boundary, and validation summaries in English and Japanese.
- Updated the centralized Browser overview screenshot to include every telemetry page, including CSV Interpole.
- Retained the complete API Surface Reference PDF for exhaustive class inspection.

## v3.5.2 — Semantic IR Atomic Batch Review Contract

Extended the v3.5.1 lifecycle ledger with a bounded, deterministic, all-or-nothing batch-review contract. A batch validates the Formal Semantic IR candidate once, replays current CSV evidence once, validates an optional source lifecycle once, preflights every independently authorized transition against the batch-entry state, and produces either one complete immutable lifecycle result or the original lifecycle unchanged.

Implemented:

- `staqtapp_tds.csv_layer.semantic_ir_lifecycle_batch`
- `CSVSemanticIRBatchAuthorization`
- `CSVSemanticIRBatchItem`
- `CSVSemanticIRTransitionBatch`
- `CSVSemanticIRBatchReceipt`
- `CSVSemanticIRBatchValidationReport`
- `CSVSemanticIRBatchReplayReport`
- separate `review_transition_batch` authorization above per-transition authorization
- deterministic transition-request, batch-authorization, ordered-batch, and receipt fingerprints
- maximum 32 transitions per batch and the existing 256-transition lifecycle ceiling
- duplicate transition, proposition, and authorization identity rejection
- batch-entry predecessor-state preflight for every request
- isolated in-memory append simulation with no rollback-based mutation
- complete batch receipt validation and current-evidence replay
- parity with equivalent sequential v3.5.1 transitions
- compatible consumption of v3.5.1 candidate/lifecycle lineage without rewriting historical fingerprints

Preserved:

- no partial batch acceptance
- no automatic lifecycle transitions
- no intra-batch transition chains for one proposition
- no admitted `committed` or `superseded` state
- no semantic commitment or inferred semantic reasoning
- no persisted Semantic IR artifact
- no CSV or historical evidence mutation
- no Interpole mutation
- no native storage writes, lock control, hot-path entry, or native C engine changes
- no per-row or per-cell writes
- original v3.5.2 implementation introduced no README/API-surface changes; the documentation refresh above supersedes that documentation state

Validation:

```text
v3.5.2 atomic batch/adversarial tests: 21 passed
v3.5.0 foundation tests: 20 passed
v3.5.1 lifecycle tests: 20 passed
full source/fallback suite: 683 passed, 11 skipped
full native-build suite: 694 passed
release and packaged-release checks: passed
```

## v3.5.1 — Semantic IR Lifecycle Transition Contract

Added the first explicit, deterministic Semantic IR lifecycle ledger above the v3.5.0 candidate foundation. The release admits only `proposed -> validated`, `proposed -> contested`, and `validated -> contested`. Every transition requires caller-supplied authorization metadata, source-candidate validation, current evidence replay, predecessor fingerprints, immutable history, and deterministic replay.

Implemented:

- `staqtapp_tds.csv_layer.semantic_ir_lifecycle`
- `CSVSemanticIRTransitionAuthorization`
- `CSVSemanticIRTransitionRequest`
- `CSVSemanticIRTransitionRecord`
- `CSVSemanticIRLifecycleState`
- `CSVSemanticIRLifecycle`
- `CSVSemanticIRLifecycleValidationReport`
- `CSVSemanticIRLifecycleReplayReport`
- explicit authorization scope binding for validation and contestation
- source candidate validation and current v3.4.11 handoff replay on every transition
- global and per-proposition predecessor fingerprint chains
- deterministic authorization, transition, and lifecycle fingerprints
- complete immutable lifecycle replay
- exact serialized contract checks at lifecycle, state, transition-record, and authorization levels
- bounded reason text, history count, and lifecycle payload size

Preserved:

- no automatic lifecycle transitions
- no inferred validation or contestation
- no committed or superseded state admission
- no semantic commitment
- no persisted Semantic IR artifact
- no CSV or historical evidence mutation
- no Interpole mutation
- no native storage writes, lock control, hot-path entry, or native C engine changes
- no per-row or per-cell writes
- original v3.5.2 implementation introduced no README/API-surface changes; the documentation refresh above supersedes that documentation state

Validation target:

```text
v3.5.1 lifecycle/adversarial tests
v3.5.0 + v3.5.1 Semantic IR tests
focused CSV / Semantic IR suite
full source/fallback suite
full native-build suite
release and packaged-release checks
```

## v3.5.0 — Formal Semantic IR Foundation

Introduced the first formal Semantic IR object layer above the completed CSV Suite. The release converts a fully revalidated v3.4.11 handoff into an immutable, deterministic, caller-declared IR candidate. It does not infer semantics, persist an IR artifact, apply lifecycle transitions, or commit semantic truth.

Implemented:

- `staqtapp_tds.csv_layer.semantic_ir`
- `CSVSemanticIRDeclaration`
- `CSVSemanticIREvidenceReference`
- `CSVSemanticIRProposition`
- `CSVSemanticIRCandidate`
- `CSVSemanticIRValidationReport`
- `CSVSemanticIRReplayReport`
- `prepare_csv_semantic_ir_candidate(...)`
- `validate_csv_semantic_ir_candidate(...)`
- `replay_csv_semantic_ir_candidate(...)`
- deterministic declaration and candidate fingerprints
- bounded candidate payloads and proposition/evidence-reference counts
- exact serialized contract validation at candidate, proposition, and evidence-reference levels
- current handoff reconstruction on every candidate build, including stale supplied-handoff rejection
- lifecycle vocabulary for proposed, validated, contested, superseded, and committed states
- v3.5.0 admission restricted to explicit `proposed` declarations only

Preserved:

- explicit opt-in is mandatory
- all propositions are caller declarations; no inference path exists
- every proposition references validated v3.4.11 evidence lanes
- no schema, type, entity, row-identity, or cell-meaning inference
- no AI behavior or automatic semantic reasoning
- no lifecycle transition or semantic commitment
- no persisted Semantic IR artifact
- no retroactive CSV artifact mutation
- no Interpole mutation
- no per-row or per-cell TDS writes
- no native storage writes, lock control, hot-path entry, or native C engine changes
- original v3.5.2 implementation introduced no README/API-surface changes; the documentation refresh above supersedes that documentation state

Validation target:

```text
v3.5.0 foundation/adversarial tests
focused CSV / Semantic IR suite
full source/fallback suite
full native-build suite
release and packaged-release checks
```

## v3.4.11 — CSV Suite Closure / Semantic IR Handoff Contract

Closed the v3.4.x CSV evidence line with a read-only, deterministic handoff contract for the future TDS Semantic IR layer. This release does not implement Semantic IR. It proves that the complete CSV artifact, storage, Interpole, kernel, performance, Browser monitor, and replay chain is valid before a later explicit IR API is allowed to consume evidence references.

Implemented:

- `staqtapp_tds.csv_layer.semantic_handoff`
- `CSVSemanticIRHandoffEvidence`
- `CSVSemanticIRHandoffReport`
- `CSVSemanticIRHandoffValidationReport`
- `prepare_csv_semantic_ir_handoff(...)`
- `validate_csv_semantic_ir_handoff(...)`
- `csv_semantic_ir_handoff_fingerprint(...)`
- `csv_semantic_ir_handoff_summary(...)`
- 19 required evidence lanes spanning the complete CSV suite
- deterministic closure fingerprints and bounded handoff payloads
- before/after TDS directory-state fingerprints proving read-only preparation
- packaged SVG registry validation in the final handoff
- explicit opt-in, immutable evidence-reference, and semantic-exclusion boundaries

Replay hardening corrected:

- serialized Browser snapshots can no longer omit frozen display-contract fields and receive default values silently
- replay now compares the complete display projection, including nested cards, ring nodes, gates, signal lanes, and event rows
- same-count nested display tampering now fails closed
- monitor numeric, index, icon-reference, duplicate-name, and collection-bound checks are stricter
- canonical JSON fingerprints reject non-finite numeric values

Preserved:

- no formal Semantic IR implementation or commitment
- no schema, type, entity, row-identity, or cell-meaning inference
- no AI behavior
- no retroactive CSV artifact mutation
- no per-row or per-cell TDS writes
- no Browser-to-Interpole mutation
- no native storage writes, lock control, or native C storage-engine changes during handoff preparation
- README files and the API PDF remain unchanged

Validation target:

```text
v3.4.11 closure/adversarial tests
focused CSV suite
full source/fallback suite
full native-build suite
release and packaged-release checks
```

## v3.4.6 — CSV Native Scan Kernel Prototype

Added the first optional CSV native scan-kernel sidecar/prototype behind the v3.4.5 readiness contract. The Python reference scanner remains the default-safe path; requested native execution uses the C sidecar when available, falls back cleanly when allowed, and fails closed when `force_native=True`.

Implemented:

- `staqtapp_tds._csv_scan_kernel` optional native C sidecar source
- `staqtapp_tds.csv_layer.native_scan`
- `CSVNativeScanKernelReport`
- `prepare_csv_native_scan_kernel_prototype(...)`
- `commit_csv_native_scan_kernel_prototype_report(...)`
- `load_csv_native_scan_kernel_prototype_report(...)`
- `validate_csv_native_scan_kernel_prototype(...)`
- `csv_native_scan_kernel_report_key(...)`
- `csv_native_scan_kernel_summary(...)`
- deterministic native/reference scan fingerprints
- native/requested/forced/fallback execution reporting
- fail-closed native mismatch and unavailable-native gates

Preserved:

- Python reference fallback remains available
- committed v3.4.5 readiness contract is required
- fresh scan and row-anchor parity are required
- no native storage writes
- no native storage hot-path control
- no native storage lock control
- no native C storage-engine change
- no per-row or per-cell writes
- no schema/type/entity inference
- no semantic conclusions
- no formal IR commitment

Validation:

```text
v3.4.6 tests: 12 passed
Focused CSV suite: 162 passed
Full source/fallback suite: 565 passed, 11 skipped
Native build smoke suite: 576 passed
```

## v3.4.0 - CSV Native Storage Integration Beginning

- Added controlled artifact-level CSV native-storage commit beginning.
- Added `CSVNativeStorageCommitEntry` and `CSVNativeStorageCommitReport`.
- Added `commit_csv_native_storage_artifacts(...)`, `validate_csv_native_storage_commit(...)`, `load_csv_native_storage_commit_report(...)`, `csv_native_storage_commit_report_key(...)`, and `csv_native_storage_commit_summary(...)`.
- Requires a persisted replay proof before storage-backed artifact commit.
- Writes only the fixed CSV artifact set into deterministic storage binding keys.
- Preserves no per-row writes, no per-cell writes, no semantic reasoning, no native C engine change, and no native CSV kernel usage.

## v3.3.9 — CSV Storage Adapter Commit Simulation / Replay Proof

Added a deterministic CSV storage-adapter commit replay layer. This release consumes the v3.3.8 binding contract, simulates the future native storage commit sequence through an in-memory replay plan, and can persist a compact derived replay proof report. It still performs no native storage writes and does not migrate CSV payloads.

Implemented:

- `CSVStorageAdapterReplayStep`
- `CSVStorageAdapterReplayReport`
- `csv_storage_adapter_replay_report_key(...)`
- `prepare_csv_storage_adapter_replay(...)`
- `commit_csv_storage_adapter_replay_report(...)`
- `load_csv_storage_adapter_replay_report(...)`
- `validate_csv_storage_adapter_replay(...)`
- `csv_storage_adapter_replay_summary(...)`
- deterministic replay transaction IDs
- deterministic replay fingerprints
- staged / committed / skipped-optional replay states
- failed hash-check classification before simulated commit
- failed binding-validation classification before simulated commit
- optional replay report persistence as a derived proof artifact

Preserved:

- README.md unchanged
- README_ja.md unchanged
- API PDF unchanged
- native C storage engine unchanged
- normal CSV import artifact count unchanged
- no native CSV payload migration
- no native storage writes
- no per-row writes
- no per-cell writes
- no semantic reasoning

## v3.3.8 — CSV Storage Adapter Dry-Run / Binding Contract

Added a read-only CSV storage-adapter binding contract layer. This release consumes the durable bridge-commit manifest from v3.3.7, revalidates the current artifact hashes and lanes, and resolves every committed artifact into deterministic future storage binding records. It still performs no native storage writes and does not migrate CSV payloads.

Implemented:

- `CSVStorageAdapterBinding`
- `CSVStorageAdapterBindingReport`
- `prepare_csv_storage_adapter_binding(...)`
- `validate_csv_storage_adapter_binding(...)`
- `csv_storage_adapter_binding_summary(...)`
- deterministic future storage binding keys
- ready / missing / drifted / optional-missing / rejected binding statuses
- fail-closed detection of missing committed artifacts
- fail-closed detection of payload hash drift before native storage commit
- nonfatal optional scan-artifact binding gaps when scan artifacts were included but not required

Preserved:

- README.md unchanged
- README_ja.md unchanged
- API PDF unchanged
- native C storage engine unchanged
- normal CSV import artifact count unchanged
- no native CSV payload migration
- no native storage writes
- no per-row writes
- no per-cell writes
- no semantic reasoning

## v3.3.7 — CSV Storage Bridge Commit Manifest

Added a derived CSV storage-bridge commit manifest layer. This release freezes the validated storage bridge plan, payload lanes, provenance expectations, and payload hashes into a compact optional `.tds` report that can be validated for drift before any future native CSV storage adapter ingests data. It remains above native storage and does not migrate payloads into a native CSV kernel.

Implemented:

- `CSVStorageBridgeCommitReport`
- `csv_storage_bridge_commit_report_key(...)`
- `prepare_csv_storage_bridge_commit(...)`
- `commit_csv_storage_bridge_manifest(...)`
- `load_csv_storage_bridge_commit_report(...)`
- `validate_csv_storage_bridge_commit(...)`
- `csv_storage_bridge_commit_summary(...)`
- dry-run bridge commit planning
- derived bridge-commit report persistence
- payload hash/kind drift detection
- optional scan-artifact commit validation

Preserved:

- README.md unchanged
- README_ja.md unchanged
- API PDF unchanged
- native C storage engine unchanged
- normal CSV import artifact count unchanged
- no native CSV payload migration
- no per-row writes
- no per-cell writes
- no semantic reasoning

## v3.3.6 — CSV Storage Bridge Preflight

- Added `CSVStorageBridgeEntry`.
- Added `CSVStorageBridgePreflightReport`.
- Added `csv_storage_bridge_plan(...)`.
- Added `validate_csv_storage_bridge_preflight(...)`.
- Added `csv_storage_bridge_preflight_summary(...)`.
- Added read-only storage-readiness checks for CSV core artifacts.
- Added optional scan-artifact preflight validation.
- Verified expected payload lanes and provenance lanes for future storage integration.
- Preserved native C storage-engine boundary, normal CSV import write shape, and no per-row/per-cell writes.

## v3.3.5 — CSV Artifact Transaction / Recovery Envelope

Added an optional transaction/recovery envelope for CSV `.tds` artifact writes. This release stages the fixed six CSV core artifacts under transaction-specific keys, validates the staged set, commits it into the final CSV namespace, records a transaction report, and detects or recovers interrupted partial artifact sets. The ordinary CSV import path and artifact count remain unchanged.

Implemented:

- `CSVArtifactTransactionReport`
- `begin_csv_artifact_transaction(...)`
- `validate_csv_artifact_transaction(...)`
- `commit_csv_artifact_transaction(...)`
- `detect_partial_csv_artifacts(...)`
- `recover_csv_artifact_transaction(...)`
- `csv_artifact_transaction_keys(...)`
- `load_csv_artifact_transaction_report(...)`
- `new_csv_transaction_id()`
- `validate_csv_transaction_id(...)`
- staged transaction key validation
- fail-closed staged artifact validation
- partial final artifact detection
- staged recovery over partial final state

Validation target:

```text
CSV v3.2.0-v3.3.5 focused tests
full release test suite
release check
```

Preserved:

- README.md unchanged
- README_ja.md unchanged
- API PDF unchanged
- native C storage engine unchanged
- normal CSV import artifact count unchanged
- no per-row writes
- no per-cell writes
- no semantic reasoning

## v3.3.4 — CSV Artifact Security Envelope

Added a read-only CSV artifact security envelope for `.tds` directory integration. This release bounds and validates CSV identifiers, rejects path/control-character artifact names, verifies manifest keysets, and can validate optional scan-artifact key containment after materialization. It keeps all security checks above storage and does not change the fixed CSV import write shape.

Implemented:

- `CSVArtifactSecurityReport`
- `validate_csv_id(...)`
- `is_safe_csv_id(...)`
- `validate_csv_artifact_key(...)`
- `validate_csv_artifact_security(...)`
- bounded generated CSV IDs from `safe_csv_id(...)`
- fail-closed rejection for unsafe custom `csv_id` values before CSV import writes
- fail-closed `validate_csv_artifacts(...)` handling for unsafe IDs
- fail-closed scan-materialization reports for unsafe IDs
- core manifest artifact-key envelope validation
- optional scan-artifact key/readability envelope validation

Validation target:

```text
CSV v3.2.0-v3.3.4 focused tests
full release test suite
release check
```

Preserved:

- README.md unchanged
- README_ja.md unchanged
- API PDF unchanged
- native C storage engine unchanged
- CSV import artifact count unchanged
- no per-row writes
- no per-cell writes
- no semantic reasoning

## v3.3.3 — CSV Scan Artifact Materialization

Added opt-in materialization of CSV scan evidence as compact derived `.tds` JSON artifacts. The release persists scan profiles and optional row-anchor profiles only after parity against durable raw/manifest/row-offset artifacts succeeds, keeping routine CSV imports fixed-shape and leaving the native storage engine untouched.

Implemented:

- `CSVScanArtifactReport`
- `csv_scan_artifact_keys(...)`
- `materialize_csv_scan_artifacts(...)`
- `load_csv_scan_profile(...)`
- `load_csv_row_anchor_profile(...)`
- `load_csv_scan_materialization_report(...)`
- `validate_materialized_csv_scan_artifacts(...)`
- `CSVScanProfile.from_mapping(...)`
- `CSVRowAnchorProfile.from_mapping(...)`
- optional scan-profile-only materialization
- optional scan + row-anchor materialization
- fail-closed pre-write validation when core artifacts drift
- post-materialization validation against the current durable source

Validation target:

```text
CSV v3.2.0-v3.3.3 focused tests
full release test suite
release check
```

Preserved:

- README.md unchanged
- README_ja.md unchanged
- API PDF unchanged
- native C storage engine unchanged
- CSV import artifact count unchanged
- no per-row writes
- no per-cell writes

## v3.3.2 — CSV Row Anchor Hash Scan

Added opt-in row-anchor hashing for the v3.3.x CSV scan/kernel lane. The new row-anchor profile hashes exact logical-record byte slices from the preserved CSV source and validates them against durable row-offset artifacts without writing new import artifacts or touching the native storage engine.

Implemented:

- `CSVRowAnchorProfile`
- `CSVRowAnchorParityReport`
- `scan_csv_row_anchors(...)`
- `scan_csv_text_row_anchors(...)`
- `validate_csv_row_anchors(...)`
- buffer/chunk-boundary row-anchor parity tests
- fail-closed row-offset drift coverage
- `benchmarks/benchmark_v332_csv_row_anchors.py`

Validation target:

```text
CSV v3.2.0-v3.3.2 focused tests
full release test suite
release check
```

Preserved:

- README.md unchanged
- README_ja.md unchanged
- API PDF unchanged
- native C storage engine unchanged
- CSV import artifact count unchanged
- no per-cell writes

## v3.3.1 — CSV Scan Performance Shape Pass

- Broadened `scan_csv_bytes(...)` and `logical_record_offsets_bytes(...)` to accept buffer-backed byte inputs through `memoryview(...)`.
- Added mmap/bytearray/memoryview scan parity coverage so future bytes-first file paths have a tested reference shape.
- Removed the second-pass temporary max-record-span list from scan profile generation.
- Removed unnecessary post-scan offset re-filtering after the scanner has already guaranteed in-bounds logical record starts.
- Added compact packed row-offset helpers: `pack_csv_row_offsets(...)` and `unpack_csv_row_offsets(...)`.
- Added `benchmarks/benchmark_v331_csv_scan.py` for dependency-free local scan throughput checks.
- Preserved the fixed CSV artifact write shape, README files, API PDF, and native C storage engine.

Validation:

```text
CSV v3.2.0-v3.3.1 focused tests passed
```

## v3.3.0 — CSV Scan Reference Foundation

- Added `CSVScanProfile` and `CSVScanParityReport` as the first v3.3.x CSV scan/kernel reference models.
- Added `scan_csv_bytes(...)` and `scan_csv_text(...)` for mechanical byte-scan facts above storage.
- Added `validate_csv_scan_profile(...)` to compare fresh scan profiles with durable raw/manifest/row-offset artifacts.
- Added chunk-boundary scan parity tests across mixed newlines, quoted newlines, doubled quotes, UTF-8, TSV, and unterminated quoted records.
- Preserved the v3.2.x fixed import artifact shape: one raw artifact, five derived JSON artifacts, and no per-cell writes.
- Kept native C storage unchanged; this is the Python correctness reference for any future optional native CSV sidecar.
- Kept README files and API surface PDF unchanged during the intermediate CSV feature branch.

Validation:

```text
CSV v3.2.0-v3.3.0 focused tests passed
```

## v3.2.3 — CSV Reloadability / Adversarial Corpus Pass

- Added `CSVReloadedArtifacts` and `reload_csv_artifacts(...)` for storage-only CSV artifact rehydration.
- Added persisted snapshot reload tests proving validation does not depend on original in-memory import objects.
- Added adversarial CSV corpus coverage for mixed newlines, quoted delimiters/newlines, doubled quotes, TSV/PSV, UTF-8, empty fields, no terminal newline, and unterminated quoted records.
- Added validator result-code payloads while preserving existing error/warning strings.
- Tightened import-report shape validation and fail-closed handling for malformed numeric artifact fields.
- Preserved fixed artifact-write shape: one raw artifact, five derived JSON artifacts, and no per-cell writes.
- Kept native C storage unchanged.
- Kept README files and API surface PDF unchanged during the intermediate CSV feature branch.

Validation:

```text
CSV v3.2.0-v3.2.3 focused tests passed
```

## 3.2.0 - CSV Artifact Foundation

## v3.2.2 — CSV Artifact Validation Excellence Pass

- Added CSV artifact validation reports for the v3.2.x CSV foundation.
- Validates preserved raw CSV hashes, row-offset parity, dialect/manifest consistency, content-hash artifacts, and import-report shape contracts.
- Detects artifact drift such as raw CSV tampering, row-offset corruption, and accidental per-cell-write shape regressions.
- Kept native C storage unchanged.
- Kept README files and API surface PDF unchanged during the intermediate CSV feature branch.

- Added `staqtapp_tds.csv_layer` as the first CSV feature layer above the hardened storage engine.
- Added CSV artifact dataclasses for dialect fingerprints, import manifests, import reports, row-offset maps, and round-trip proof.
- Added `import_csv_bytes(...)` and `import_csv_file(...)` to preserve raw CSV text and write derived JSON artifacts into TDS.
- Added dialect detection with deterministic fallback and logical row-offset generation that respects quoted newlines.
- Added deterministic original and canonical CSV export helpers.
- Added original-byte round-trip proof storage.
- Preserved the native C storage/index hot path: CSV intelligence lives above storage, writes batch-style artifacts, and does not execute inside the native engine.
- Added focused v3.2.0 tests and CSV foundation documentation.

Validation:

```text
CSV foundation tests passed
storage hardening regression coverage passed
source-clean release check passed
```

## 3.2.1 - CSV Foundation Performance & Shape Pass

- Tightened CSV row-offset scanning with a byte/memoryview path.
- Added import shape tests proving fixed artifact writes and no per-cell writes.
- Added larger quoted-newline CSV tests.
- Left README files, API surface PDF, and native C storage engine unchanged.

## Storage Engine Hardening Pre-CVS Patch

- Hardened `.tds` file geometry and slot-index parsing to fail closed on truncated or inconsistent index records.
- Enforced sidecar payload content hashes on read with typed persistence integrity result codes.
- Made compressed persistence codec-stable by carrying entry codec through writer, reader, and lazy-entry paths.
- Coupled sidecar metadata generation to the same frozen snapshot used for the data block and added sidecar epoch/file-size checks.
- Added sidecar write-all/fsync/atomic-replace durability symmetry and mutable JSON/text/raw write snapshot freezing.
- Added focused storage-hardening regression coverage for the pre-CVS reliability layer.

## 3.1.25 - Browser & Studio Visual Consistency Hardening

- Added final-order Browser visual QA CSS rules for sidebar, navigation, panel, workload, hero-orbit, architecture-map, and compact desktop containment.
- Moved the sidebar control-plane card out of absolute positioning and into normal flex flow to prevent nav/card overlap.
- Restored compact desktop 2-column dashboard behavior after later CSS overrides and added 1280×800-safe telemetry page rendering rules.
- Added `docs/screenshots/tds_browser_telemetry_overview_1280x800.png` and embedded it near the top of README.md / README_ja.md for GitHub rendering.
- Improved optional PyQt5 Driver Studio visual consistency through safer minimum window sizing, dock layout behavior, panel minimums, group-box/help-label styling, and Manual Builder split/scroll containment.
- Preserved Browser and Studio authority boundaries: no storage ownership, Registry trust mutation, driver approval/signing/activation, private-key storage, trusted VM authority execution, or policy bypass.

Validation:

```text
393 passed, 11 skipped
release check passed
```


## 3.1.23 - Driver Studio Stress Scenario Matrix

- Extended `staqtapp_tds.studio_pyqt5.operational_stress` with named stress scenarios and a default scenario matrix.
- Added `StudioOperationalStressScenario`, `StudioOperationalStressScenarioResult`, and `StudioOperationalStressScenarioMatrix`.
- Added `DEFAULT_OPERATIONAL_STRESS_SCENARIOS`.
- Added `StudioOperationalStressHarness.run_scenario(...)` for individual stress paths.
- Added `StudioOperationalStressHarness.run_scenario_matrix(...)` for deterministic matrix evidence.
- Added named Browser polling, Studio live-event overflow, Manual Builder payload, `.tds` persistence atomicity, combined Browser + Studio + `.tds`, and authority-boundary denial scenarios.
- Added scenario-matrix capability flags while preserving explicit denied authority flags.
- Updated the API reference PDF under `tds_api_docs/` and linked it from both README files.
- Preserved Studio and Browser authority boundaries: no approval, rejection, quarantine, signing, activation, Registry mutation, trusted VM execution, storage writes through Studio, private keys, or policy bypass.

Validation:

```text
389 passed, 11 skipped
release check passed
```


## 3.1.22 - Driver Studio Operational Stress Harness

- Added `staqtapp_tds.studio_pyqt5.operational_stress`.
- Added `StudioOperationalStressHarness`, `StudioOperationalStressReport`, `StudioOperationalStressObservation`, and `StudioOperationalStressStatus`.
- Added Browser-style `AdminControl.status()` polling stress with JSON status emission checks.
- Added bounded Studio live-event overflow stress that treats event loss as acceptable only when drop counts, retained cursor floor, and retention-gap warnings are explicit.
- Added Manual Builder JSON/signal payload stress for unusual Qt-style form values.
- Added `.tds` atomic persistence reader/writer stress checks for existing-reader usability and fresh-reader latest-generation visibility.
- Added `studio_operational_stress_capability_matrix()` with explicit denied authority flags.
- Added generated API reference PDF under `tds_api_docs/` and linked it from both README files.
- Restored/verified README.md and README_ja.md cross-links.
- Preserved Studio and Browser authority boundaries: no approval, rejection, quarantine, signing, activation, Registry mutation, trusted VM execution, storage writes through Studio, private keys, or policy bypass.

Validation:

```text
382 passed, 11 skipped
```


## 3.1.21 - Driver Studio Runtime Hardening

- Strengthened the optional Driver Studio runtime around bounded live-event streams, drop accounting, and runtime warning payloads.
- Added event-retention floor and dropped-event counts to live bridge state/signal payloads so GUI polling can detect when older retained events were dropped before consumption.
- Added runtime-level retention-gap detection and signal payload warnings without mutating backend state or widening Studio authority.
- Hardened Manual Builder UI Runtime form payload serialization so unusual form values remain JSON/signal safe in accepted and rejected states.
- Removed duplicate Studio factory/method definitions and preserved bridge/runtime/manual-builder compatibility.
- Added focused v3.1.21 runtime-hardening tests for event retention gaps, bounded stream drop accounting, JSON-safe signal payloads, factory compatibility, and authority-boundary preservation.
- Preserved Studio authority boundaries: no approval, rejection, quarantine, signing, activation, Registry mutation, trusted VM execution, storage writes, private keys, or policy bypass.

Validation:

```text
375 passed, 11 skipped
```


## 3.1.20 - Driver Studio Export Integrity Workflow

- Added `staqtapp_tds.studio_pyqt5.export_integrity_workflow`.
- Added `StudioExportIntegrityWorkflow` for review-safe export packet verification above the Export / Audit Console.
- Added `StudioExportIntegrityWorkflowState`, `StudioExportIntegrityCheckpoint`, `StudioExportIntegrityCheckpointStatus`, `StudioExportIntegrityManifestComparison`, `StudioExportIntegrityReviewGate`, and `StudioExportIntegrityWorkflowStatus`.
- Added deterministic manifest hash recomputation and packet hash recomputation.
- Added optional expected manifest hash, packet hash, and manifest field comparison.
- Added progressive checklist checkpoint rows and blocking checkpoint reporting.
- Added intent-only review-safe export handoff gate and deterministic workflow hash.
- Extended `StudioQtBridge` and `StudioLivePanelRuntime` with `export_integrity_workflow()` constructors.
- Preserved Studio authority boundaries: no approval, rejection, quarantine, signing, activation, Registry mutation, trusted VM execution, storage writes, private keys, or policy bypass.

Validation:

```text
367 passed, 11 skipped
```


## 3.1.18 - Driver Studio Manual Builder UI Runtime

- Added `staqtapp_tds.studio_pyqt5.manual_builder_runtime`.
- Added a GUI-ready Manual Builder runtime for form normalization, deterministic TDDL preview, Foundry-routed proposal reports, and signal-friendly state payloads.
- Added joined interaction metadata connecting Builder, Evidence Bundle, Evidence Timeline, Risk Intelligence, and Review Workflow surfaces.
- Added static PyQt5 cockpit visual-quality review for readable fonts, text-overhang risk, component-overlap risk, scrollable preview surfaces, and joined interaction flow.
- Improved PyQt5 theme sizing and shell layout readability while preserving import safety without PyQt5.
- Preserved Studio authority boundaries: no approval, rejection, quarantine, signing, activation, Registry mutation, trusted VM execution, storage writes, private keys, or policy bypass.

## v3.1.17 - Driver VM Performance Evidence Harness

- Added opt-in `staqtapp_tds.drivers.performance` harness for controlled Driver VM performance evidence.
- Added direct Python VM timing and optional Runtime Manager overhead comparison.
- Added native C backend parity slot for future experimental Driver VM conversion work.
- Added deterministic result-hash checks, records/sec, emitted/sec, cost/sec, snapshot hash, and performance evidence hash reporting.
- Added passive `STAQTAPP_TDS_DRIVER_VM_PERF` helper without automatic execution.
- Preserved normal `DriverVMRuntime.execute()` and `DriverRuntimeManager.execute_package()` hot-path behavior.
- Added v3.1.17 docs and tests.

## v3.1.16 - Driver Studio Risk Intelligence Cards

- Added `staqtapp_tds.studio_pyqt5.risk_intelligence`.
- Added `StudioRiskIntelligenceCards` as an evidence-linked risk analysis layer for Driver Studio.
- Added `StudioRiskIntelligenceState`, `StudioRiskIntelligenceCard`, `StudioRiskIntelligenceFactor`, and `StudioRiskIntelligenceBand`.
- Added risk pressure scoring, evidence gap factors, fixture coverage context, Registry observation context, and live review-intent observation factors.
- Added intent-only review-action hints that connect risk analysis to the Review Workflow Console without granting authority.
- Extended `StudioQtBridge` with `risk_intelligence_cards(max_events=256)`.
- Extended `StudioLivePanelRuntime` with `risk_intelligence_cards()`.
- Updated hydrated Risk Card metadata and capability matrices for the Risk Intelligence surface.
- Preserved Studio authority boundaries: no approval, rejection, quarantine, Registry approval calls, signing, activation, Registry mutation, VM authority execution, storage writes, private keys, or policy bypass.
- Added v3.1.16 docs and tests.

Validation:

```text
345 passed, 11 skipped
```

## v3.1.15 - Driver Studio Evidence Timeline

- Added `staqtapp_tds.studio_pyqt5.evidence_timeline`.
- Added `StudioEvidenceTimeline` as the chronological trust-history surface for Driver Studio.
- Added `StudioEvidenceTimelineState`, `StudioEvidenceTimelineItem`, `StudioDriverLifecycleStage`, `StudioRegistryObservationItem`, and `StudioEvidenceTimelineIntegrityCard`.
- Added a first-class `Evidence Timeline` Studio panel with lifecycle rows, timeline cards, hydration columns, SVG iconography, and live refresh contracts.
- Extended `StudioQtBridge` with `evidence_timeline(max_events=256)`.
- Extended `StudioLivePanelRuntime` with `evidence_timeline()`.
- Connected timeline refresh to bundle load, selected-driver context, review-intent submission, and snapshot refresh events.
- Preserved Studio authority boundaries: no approval, rejection, quarantine, Registry approval calls, signing, activation, Registry mutation, VM authority execution, storage writes, private keys, or policy bypass.
- Added v3.1.15 docs and tests.

Validation:

```text
340 passed, 11 skipped
```

## v3.1.14 - Driver Studio Review Workflow Console

- Added `staqtapp_tds.studio_pyqt5.review_workflow`.
- Added `StudioReviewWorkflowConsole` for review readiness, action eligibility, rationale templates, and review history surfaces.
- Added `StudioReviewWorkflowConsoleState`, `StudioReviewWorkflowItem`, `StudioReviewActionEligibility`, `StudioReviewRationaleTemplate`, `StudioReviewHistoryEntry`, and `StudioReviewWorkflowStatus`.
- Added `studio_review_rationale_templates()` and `studio_review_workflow_capability_matrix()`.
- Extended `StudioQtBridge` with `review_workflow_console(max_events=256)`.
- Extended `StudioLivePanelRuntime` with `review_workflow_console()`.
- Preserved Studio authority boundaries: no approval, rejection, quarantine, signing, activation, Registry mutation, VM authority execution, storage writes, private keys, or policy bypass.
- Added v3.1.14 docs and tests.

Validation:

```text
334 passed, 11 skipped
```

## v3.1.13 - Driver Studio Live Panel Runtime

- Added `staqtapp_tds.studio_pyqt5.runtime`.
- Added `StudioLivePanelRuntime` to coordinate live events into hydrated panel refresh packets.
- Added `StudioPanelRuntimeState`, `StudioPanelDirtyMark`, and `StudioPanelRefreshPacket`.
- Added `studio_live_panel_runtime_capability_matrix()`.
- Extended `StudioQtBridge` with `live_panel_runtime(max_events=256)`.
- Added dirty-panel tracking, event-to-panel routing, selection-aware refresh coordination, and Qt model update payloads.
- Preserved Studio authority boundaries: no approval, signing, activation, Registry mutation, VM authority execution, storage writes, private keys, or policy bypass.
- Added v3.1.13 docs and tests.

Validation:

```text
328 passed, 11 skipped
```

## v3.1.12 - Driver Studio Live Cockpit Event Bridge

- Added `staqtapp_tds.studio_pyqt5.live`.
- Added `StudioCockpitEventBridge` for bounded live-update coordination above the hydrated cockpit state.
- Added `StudioLiveCockpitState`, `StudioLiveEvent`, `StudioLiveEventKind`, `StudioCockpitSelection`, and `StudioPanelRefreshContract`.
- Added `studio_panel_refresh_contracts()` and `studio_live_event_bridge_capability_matrix()`.
- Extended `StudioQtBridge` with `live_event_bridge(max_events=256)` and `panel_refresh_contracts()`.
- Added bounded in-memory Studio event stream semantics for bundle load, driver selection, panel refresh, snapshot refresh, review action submission, manual proposal preview, and manual proposal submission.
- Added Qt-signal-friendly `signal_payload()` snapshots for safe polling or signal-style UI updates.
- Preserved Studio authority boundaries: no approval, signing, activation, Registry mutation, VM authority execution, storage writes, private keys, or policy bypass.
- Added v3.1.12 docs and tests.

Validation:

```text
322 passed, 11 skipped
```

## v3.1.11 - Driver Studio Hydrated Cockpit Panels

- Added `staqtapp_tds.studio_pyqt5.hydration`.
- Added `StudioCockpitHydrator`.
- Added `StudioHydratedCockpitState` and `StudioHydratedPanel`.
- Added GUI-ready `StudioTableColumn`, `StudioPanelCard`, `StudioTimelineItem`, `StudioPanelActionDescriptor`, and `StudioFormField` models.
- Added `manual_builder_form_schema()` for the Manual Driver Builder cockpit form.
- Added `studio_cockpit_hydration_capability_matrix()`.
- Extended `StudioQtBridge` with `hydrated_shell_state()`, `hydrate_panel(kind)`, and `manual_builder_form_schema()`.
- Updated optional PyQt5 main-window rendering to consume hydrated panels when PyQt5 is available.
- Preserved Studio authority boundaries: no approval, signing, activation, Registry mutation, VM authority execution, storage writes, private keys, or policy bypass.
- Added v3.1.11 docs and tests.

Validation:

```text
317 passed, 11 skipped
```

## v3.1.10 - Driver Studio Manual Proposal Builder

- Added GUI-neutral manual proposal builder for the Driver Studio cockpit.
- Added deterministic TDDL preview generation from bounded form-friendly task fields.
- Routed manual proposals through `DriverFoundry` for validation, compilation, audit, and optional fixture testing.
- Added Manual Driver Builder panel and SVG icon.
- Preserved Registry, signing, activation, storage, and VM authority boundaries.

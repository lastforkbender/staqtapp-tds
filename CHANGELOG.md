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

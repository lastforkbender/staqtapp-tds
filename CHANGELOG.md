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

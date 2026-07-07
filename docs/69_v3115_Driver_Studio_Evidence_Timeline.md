# v3.1.15 Driver Studio Evidence Timeline

v3.1.15 adds the Driver Studio Evidence Timeline: a chronological trust-history surface for Studio & Evidence. It gives the PyQt5 cockpit and headless services a single spine for proposal, validation, compile, fixture replay, evidence bundle, review, Registry observation, and export preparation.

The timeline is intentionally non-authoritative. It observes hydrated Studio state and live runtime events, then emits GUI/export/audit-ready view models. It does not approve, reject, quarantine, call Registry approval, sign, attach signatures, activate drivers, execute trusted drivers, mutate Registry state, write storage, store private keys, or bypass Runtime Manager / Foundry / Review Board / Registry policy.

## New module

```text
staqtapp_tds.studio_pyqt5.evidence_timeline
```

## New public models

- `StudioEvidenceTimeline`
- `StudioEvidenceTimelineState`
- `StudioEvidenceTimelineItem`
- `StudioDriverLifecycleStage`
- `StudioRegistryObservationItem`
- `StudioEvidenceTimelineIntegrityCard`
- `studio_evidence_timeline_capability_matrix()`

## New panel

```text
StudioPanelKind.EVIDENCE_TIMELINE = "evidence_timeline"
```

The panel is hydrated as a `lifecycle_timeline` surface with stable columns, cards, timeline rows, metrics, and custom SVG iconography.

## Lifecycle stages

```text
draft
proposal
validated
compiled
fixture-tested
evidence-ready
review-submitted
reviewed
registry-approval-requested
approved
signed
active
observed-active
exported
```

## Bridge/runtime additions

```python
bridge.evidence_timeline(max_events=256)
runtime.evidence_timeline()
```

## Live refresh behavior

The Evidence Timeline refreshes on:

- bundle load
- selected-driver changes
- submitted review intent
- snapshot refresh

The refresh contract is `lifecycle_timeline`, selection-aware, observe-only, and GUI-safe.

## Export/audit direction

The timeline prepares the spine for later export/audit packets that can include:

- driver identity
- proposal source hash
- compiled bytecode hash
- fixture replay summary
- evidence bundle hash
- audit trail entries
- review action history
- Registry state observation
- signature / activation observation
- export manifest hash

## Validation

```text
340 passed, 11 skipped
```

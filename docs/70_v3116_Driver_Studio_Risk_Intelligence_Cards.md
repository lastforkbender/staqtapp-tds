# v3.1.16 Driver Studio Risk Intelligence Cards

v3.1.16 adds Risk Intelligence Cards to the optional Driver Studio PyQt5 cockpit. The surface cross-checks the existing Risk Card Inspector with the Evidence Timeline, Fixture Replay Summary, Registry State Observer, Review Workflow Console context, and live cockpit events.

The purpose is administrative analysis diversity: admins can inspect risk pressure, evidence gaps, fixture coverage, review posture, Registry visibility, live review-intent activity, and blocked authority boundaries from one coherent model.

## New module

```text
staqtapp_tds.studio_pyqt5.risk_intelligence
```

## New models

```text
StudioRiskIntelligenceCards
StudioRiskIntelligenceState
StudioRiskIntelligenceCard
StudioRiskIntelligenceFactor
StudioRiskIntelligenceBand
```

## Bridge/runtime additions

```text
bridge.risk_intelligence_cards(max_events=256)
runtime.risk_intelligence_cards()
```

## Analysis inputs

```text
Risk Card Inspector
Evidence Timeline
Fixture Replay Summary
Registry State Observer
Review Workflow Console context
Live Cockpit Event Bridge
```

## Risk factors

Risk Intelligence produces explainable factors such as:

- declared risk level
- review decision posture
- review fault codes
- risk-card explanations
- lifecycle evidence gaps
- fixture replay coverage
- Registry observation state
- live review-intent submissions

## Authority boundary

Risk Intelligence is observe-only. It can render review-action hints, but those hints are not authority actions. Any actual request still travels through the existing `StudioReviewActionRequest` and Runtime Manager / Review Board / Registry authority path.

It cannot approve, reject, quarantine, call Registry approval, sign, attach signatures, activate drivers, run the trusted Driver VM, write storage, mutate Registry state, store private keys, or bypass policy.

## Why it matters

v3.1.15 made trust chronological through the Evidence Timeline. v3.1.16 makes trust more analyzable by asking: does the risk story match the evidence story?

That makes the Studio & Evidence subsystem stronger while preserving the core rule:

```text
Studio explains trust.
Studio does not own trust.
```

## Validation

```text
345 passed, 11 skipped
```

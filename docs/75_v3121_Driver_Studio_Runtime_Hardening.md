# v3.1.21 Driver Studio Runtime Hardening

v3.1.21 strengthens the optional Driver Studio runtime after the v3.1.20 Export Integrity Workflow completion.

The focus is not a new trust feature. It is runtime confidence: safer live-event retention behavior, clearer runtime warning payloads, JSON-safe UI signal data, and additional tests around Studio authority boundaries.

## Added

- bounded live-event stream drop accounting
- retained cursor floor reporting
- dropped event count reporting
- retention-gap detection for slow GUI pollers
- runtime warning payloads for retention gaps
- JSON/signal-safe Manual Builder form payload normalization
- duplicate Studio factory/method cleanup
- focused Driver Studio runtime hardening tests

## Runtime behavior

Driver Studio already uses a bounded event stream above immutable backend snapshots. When GUI polling lags beyond the retained event window, v3.1.21 now exposes that condition explicitly instead of allowing the UI layer to assume it saw every event.

```text
StudioCockpitEventBridge
  -> retained_cursor_floor
  -> dropped_event_count
  -> event_retention_gap

StudioLivePanelRuntime
  -> event_retention_gap
  -> runtime_warnings
  -> signal payload warning fields
```

The runtime still hydrates current immutable snapshots. The retention warning tells the cockpit that some event-console history was dropped from the bounded stream before the runtime consumed it.

## Manual Builder signal safety

Manual Builder form payloads can contain unexpected Qt-side values or extra fields. v3.1.21 recursively normalizes payload values before signal emission so accepted and rejected states remain safe for JSON-style UI models.

## Authority boundary

This release does not make Studio a trust authority.

Studio still cannot:

- approve drivers
- reject drivers as authority
- quarantine drivers as authority
- call Registry approval directly
- sign drivers
- attach signatures
- activate drivers
- execute trusted drivers as authority
- mutate Registry state
- write storage
- store private keys
- bypass Runtime Manager / Foundry / Review Board / Registry policy

## Validation

```text
375 passed, 11 skipped
release check passed
```

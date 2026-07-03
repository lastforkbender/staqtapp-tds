# v2.7.9 Browser Telemetry Pages

TDS v2.7.9 completes the Browser Operations Console telemetry surface introduced by the v2.7.x dashboard work. The update keeps the native storage engine unchanged and focuses on replacing placeholder operations panels with live snapshot-fed telemetry cards.

## Completed pages

- Snapshot Explorer: immutable snapshot sequence, freshness, native build cost, ring fill, dropped events, and server time.
- Lock Contention: lock, bridge, and diagnostic-ring pressure with native transition counters.
- Comparative Views: Swiss index, Radix router, storage, and native bridge comparison tiles.
- Alerts & Events: derived operational alerts from pressure, recovery planner, native diagnostics, and dropped-event counters.

## Design constraints

The browser continues to consume `/status.json` cached snapshots only. These panels do not walk storage state, do not mutate TDS, and do not introduce native-engine behavior changes.

The v2.7.8 settings and localization foundation remains intact, including the seven browser language choices and layout-safe wrapping rules for translated labels.

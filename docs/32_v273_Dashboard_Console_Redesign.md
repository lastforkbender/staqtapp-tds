# v2.7.3 Dashboard Console Redesign

TDS v2.7.3 transforms the browser Operations Console toward a sleeker engineering diagnostic dashboard.

## Scope

- Categorized left navigation matching the Pressure Diagnostics visual hierarchy.
- Shared glass-card page system for diagnostics, analytics, operations, and configuration views.
- Professional SVG icon use throughout the browser UI.
- Pressure Diagnostics remains driven by real v2.7.2 pressure telemetry fields.
- New placeholder page shells for Snapshot Explorer, Lock Contention, Comparative Views, Recovery Planner, and Alerts & Events.

## Safety rule

The dashboard still consumes cached `/status.json` snapshots only. No browser-rendered view calls into the storage hot path.

# TDS v2.7.2 — Pressure Calculations Engine

TDS v2.7.2 adds a pressure-calculation observer layer above the v2.7.1 native
transition-ring diagnostics.  The engine converts copied counters, immutable
telemetry snapshots, and native diagnostic-ring metadata into operator-facing
pressure dimensions.

The pressure engine does **not** run inside the storage hot path.  It owns no
storage objects, acquires no storage locks, and never controls the native engine.
It receives already-copied measurements and emits a dashboard-ready pressure
snapshot.

```text
Native Storage Engine
        ↓ copied counters / transition events
Native Diagnostic Ring
        ↓ immutable snapshot
Python Telemetry Snapshotter
        ↓ copied snapshot only
Pressure Calculations Engine
        ↓ status.json
Browser Operations Console
```

## Component pressure dimensions

The v2.7.2 snapshot exposes these dimensions:

- `engine_pressure`
- `storage_pressure`
- `index_pressure`
- `lock_pressure`
- `ring_buffer_pressure`
- `memory_pressure`
- `bridge_pressure`
- `dashboard_pressure`

Each dimension includes a bounded score, mode label, human-readable cause, and
supporting numeric metrics.  The top-level pressure snapshot also exposes an
overall score, dominant component, and ordered causes list for browser display.

## Browser Operations integration

The dashboard now includes a Pressure Calculations Engine panel that shows each
component score as an operator-readable bar.  It also includes a pressure-causes
panel that explains the dominant signals, for example diagnostic-ring occupancy,
Python bridge transition pressure, lock transition volume, or chunk lifecycle
backlog.

This turns v2.7.1's transition-ring observability into v2.7.2 operational
interpretation: the browser can show not only what changed, but which subsystem
is creating pressure and why.

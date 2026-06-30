# v2.5.0 Hardening and One-Way Telemetry

v2.5.0 begins the TDS Hardening Initiative. The release keeps the professional dashboard as an observer and adds a dedicated telemetry publisher thread so long-running dashboards and future exporters read immutable snapshots instead of contacting storage internals.

## One-way observation path

```
Native/Python engine counters
        ↓
TelemetryManager
        ↓
TelemetryPublisherThread
        ↓
latest immutable snapshot
        ↓
Dashboard / CLI / future exporters
```

The dashboard must not walk Swiss tables, radix routers, chunks, manifests, or provenance graphs. Expensive checks remain explicit operator actions such as `staqtapp-tds-admin verify`.

## Telemetry levels

`TelemetryLevel` supports `OFF`, `MINIMAL`, `NORMAL`, `ENGINEERING`, and `DEVELOPER`. Levels gate snapshot assembly detail rather than hot-path counter updates.

- `MINIMAL`: health and basic counters only.
- `NORMAL`: production-friendly status and component snapshots.
- `ENGINEERING`: index, radix, execution, pool, and GIL feedback.
- `DEVELOPER`: reserved for future deep diagnostics and sanitizer-oriented builds.

## Health verification

`staqtapp_tds.verify` provides explicit health checks for telemetry snapshots, runtime config, directory traversal, index consistency, and component status. These checks are manual/scheduled, not dashboard-poll driven.

## Native sanitizer hooks

The native extension build honors `STAQTAPP_TDS_SANITIZE`:

```
STAQTAPP_TDS_SANITIZE=address python -m pip install -e .
STAQTAPP_TDS_SANITIZE=undefined python -m pip install -e .
STAQTAPP_TDS_SANITIZE=all python -m pip install -e .
```

Sanitizer builds are for development and CI hardening, not default production wheels.

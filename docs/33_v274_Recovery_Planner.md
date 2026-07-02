# v2.7.4 Recovery Planner and Dashboard Finalization

TDS v2.7.4 adds the first real Recovery Planner observer. It consumes the Pressure Calculations Engine output, native diagnostic counters, performance snapshots, and storage counters. It does not mutate storage, chunks, indexes, locks, RuntimeConfig, or native engine state.

## Architecture

```text
Native Storage Engine
    ↓ copied counters / transition events
Native Diagnostic Ring
    ↓ immutable diagnostic snapshot
Pressure Calculations Engine
    ↓ pressure snapshot
Recovery Planner
    ↓ advisory plan
Browser Operations Console
```

## Guardrails

- Recovery actions are advisory only.
- Automatic actions are always reported as zero in this release.
- The planner consumes copied snapshots only.
- Operator-facing browser panels explain evidence, confidence, subsystem, and expected effect.

## Dashboard

The browser console now renders the Recovery Planner as a first-class page using the same visual system as Pressure Diagnostics: command card, confidence card, action list, and guardrails.

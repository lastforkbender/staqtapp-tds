# Search & Extract Driver System Roadmap

The future renowned Search & Extract driver system should remain a separate subsystem from the storage core.

Planned boundaries:

```text
TDS Core
  - storage
  - TDSResult
  - native engine manager
  - telemetry

Search & Extract Drivers
  - driver language
  - registry
  - builder
  - planner
  - executor
  - optional C VM
```

The optional driver VM should use the same native loading discipline introduced in v3.0.1:

1. load through the Native Engine Manager
2. verify TDS native ABI
3. verify driver VM capabilities
4. fall back to Python execution
5. report all load/execution issues through `TDSResult`

No driver VM code is active in v3.0.1. This is intentionally a clean extension boundary.

## v3.1.21 Driver Studio Runtime Hardening

Strengthens the optional Driver Studio runtime with bounded live-event drop accounting, retained cursor floor reporting, retention-gap warnings, JSON-safe Manual Builder signal payloads, and additional authority-boundary tests. Studio remains an observer/intent surface only.


## v3.1.20 Driver Studio Export Integrity Workflow

Adds review-safe export packet verification above the v3.1.19 Export / Audit Console. The workflow recomputes manifest and packet hashes, compares optional expected integrity inputs, progresses checklist checkpoints, and prepares an intent-only review/export handoff gate.

## v3.1.19 Driver Studio Export / Audit Console

Adds hash-backed selected-driver export/audit packet previews while preserving Studio as a non-authoritative visibility and packaging layer.

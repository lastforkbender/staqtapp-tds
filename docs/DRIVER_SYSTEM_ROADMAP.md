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

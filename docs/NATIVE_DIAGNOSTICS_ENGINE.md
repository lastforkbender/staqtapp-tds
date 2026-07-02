# Native Diagnostics Engine

TDS v2.7 introduces the Native Diagnostics Engine foundation. The subsystem is an observer, not a controller.

## Architectural laws

- Diagnostics observes consequences; it does not participate in causes.
- Diagnostics owns no storage objects.
- Diagnostics mutates no VFS, chunk, directory, or index state.
- Storage never waits for diagnostics.
- Browser clients consume immutable snapshots only.

## Native foundation

The native extension exposes copied diagnostic state through:

- atomic counters for hot metrics,
- a bounded diagnostic event ring for tiny transition events,
- immutable snapshot dictionaries returned through `native_diag_snapshot()`,
- degradation flags that do not affect storage behavior.

The event ring is loss-tolerant by design. If the ring wraps, old diagnostic events are overwritten and `events_dropped` increases. Core storage work continues.

## Forbidden ownership

Diagnostics must never hold chunk pointers, directory pointers, index pointers, Python objects, borrowed buffers, or manifest objects. It may expose only IDs, counts, timestamps, state enums, and copied numeric values.

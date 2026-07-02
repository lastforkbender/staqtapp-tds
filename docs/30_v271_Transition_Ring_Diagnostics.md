# TDS v2.7.1 Transition Ring Diagnostics

v2.7.1 upgrades the Native Diagnostics Engine from generic native operation events to named transition events. The storage hot path still emits only fixed-width numeric records and counters. Python enriches those records after snapshot collection so browser telemetry can display names without putting strings, heap allocation, or Python objects into native execution paths.

## Native event ring

The native diagnostic ring is bounded at 4096 events. When it wraps, storage continues and diagnostics increments `events_dropped` and `event_ring_wraparounds`. This preserves the core rule: diagnostics observes storage, but storage never waits for diagnostics.

## Transition families

- Slot lifecycle: allocated, written, updated, deleted, visible.
- Index engine: resized, lookup hit, lookup miss.
- Memory pool: reused, allocated, freed.
- GIL boundary: released events tied to native operation counters.
- Snapshotter: periodic snapshot marker events.

## Browser telemetry

The Dashboard now displays ring occupancy, ring capacity, dropped event count, transition-family counters, and the most recent enriched transition events. These are derived from `/status.json` snapshots only; the browser never touches live native structures.

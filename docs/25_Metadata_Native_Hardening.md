# v2.4.2 Metadata and Native Execution Hardening

v2.4.2 focuses on making the existing TDS architecture smaller, faster, and more measurable without adding new reasoning behavior.

## Slotted metadata records

The `staqtapp_tds.metadata` package contains fixed-shape immutable records using `@dataclass(slots=True, frozen=True)`. These records are appropriate for high-volume metadata such as entries, chunks, namespaces, trace records, trace-set manifests, aggregation records, provenance records, execution counters, and snapshots.

Controllers, managers, dashboards, configuration builders, and security/control-plane classes intentionally remain normal Python classes.

## Native execution additions

The native Swiss index now exposes GIL-released batch insert and batch erase operations in addition to lookup, batch lookup, pop, put, and stats scans. v2.4.2 also adds native checksum and UTF-8 chunk-boundary helpers.

## Memory-pool telemetry

The native index maintains a small internal pool for tiny key buffers. This is not a public API. It exists to reduce allocation churn in delete/reinsert-heavy workloads and to provide future direction for larger native memory-pool work.

The professional dashboard displays pool reuse and allocator-call counters from snapshots only. It does not query native structures directly.

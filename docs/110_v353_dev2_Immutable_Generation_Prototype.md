# v3.5.3-dev2 Immutable Generation Prototype

Status: correctness prototype; not yet wired into the legacy v2 mount path.

## Proven invariants

- A generation is complete and checksum-verified before CURRENT promotion.
- Failure before promotion preserves the previous authoritative generation.
- CURRENT is a minimal atomically replaced pointer.
- Corrupt promoted generations produce explicit fallback status.
- Immediate retention cleanup runs only after successful promotion.
- The read hot path of the existing v2 engine is unchanged.

## Deferred intentionally

- subprocess kill and write-boundary fault matrix
- legacy migration and mount integration
- pinned generations
- background cleanup worker
- immutable segment reuse and garbage collection

# TDS v3.5.3-dev9 — Incremental Immutable Segments

## Objective

Replace repeated whole-image persistence with an explicit content-addressed
segment-generation path without weakening any recovery or publication invariant.
The proven dev8 full-image path remains available and unchanged.

## Storage model

A segment generation consists of:

- immutable SHA-256-addressed segment files under `segments/`;
- an immutable ordered `segments.json` generation manifest under
  `segment-generations/<generation-id>/`;
- the tiny atomically replaced `SEGMENT_CURRENT` pointer.

The ordered manifest records every segment digest and byte length, the complete
logical byte length and SHA-256, parent generation, creation time, segment size,
and application metadata.

## Commit invariant

Before `SEGMENT_CURRENT` publication, every referenced segment and the complete
logical reconstruction are verified. A failure leaves the previously published
segment generation authoritative. Newly written but unreferenced segments are
harmless immutable objects and can be reclaimed only by explicit GC.

## Incremental behavior

Fixed-size content segmentation means an unchanged segment is never rewritten.
A changed segment receives a new content address. Commit reports distinguish:

- segments created;
- segments reused;
- physical bytes written;
- logical bytes represented.

## Materialisation

`GuaranteedStorageBridge.materialize_segmented_current()` streams verified
segments through the same hardened transition-image parser used by dev7/dev8.
It retains path collision rejection, digest verification, double exact-inventory
verification, private reconstruction, and atomic destination publication.

## Reference accounting and garbage collection

Reference counts are derived from all fully valid immutable manifests. GC is
explicit and dry-run by default. Immediately before deletion, reachability is
recomputed while the cross-process mutation lock is held. Referenced segments
are never candidates for deletion.

Commit, generation deletion, and GC share a fail-closed mutation-directory lock.
The implementation never assumes a lock left by a crashed process is stale.
Operator intervention is required after establishing that no mutation remains.

## Recovery

If `SEGMENT_CURRENT` is absent, malformed, or references an invalid generation,
`recover_current()` selects the newest fully valid segment generation and may
atomically repair the pointer. Corrupt or missing segments invalidate the owning
generation.

## Compatibility and activation

The segment path is explicit and opt-in:

- `commit_filesystem()` remains the dev8 full-image path;
- `commit_filesystem_segmented()` is the Phase 9 path;
- full-image `CURRENT` and segmented `SEGMENT_CURRENT` are independent;
- no default storage behavior changes;
- no activation occurs in Phase 9.

Controlled activation remains Phase 10 work.

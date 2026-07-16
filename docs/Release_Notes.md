# TDS Release Notes

## v3.5.3 — Controlled Activation and Release Qualification

- Completed verified legacy-to-segment qualification and explicit controlled
  activation without changing the default legacy persistence path.
- Added mode-aware commits, bounded Browser/admin mode status, and lossless
  rollback of the current guaranteed bytes into a new verified legacy mount.
- Hardened segment GC against corrupt-generation omission, stale batch-wide
  reference proofs, candidate replacement, same-inode mutation, symlink swaps,
  interruption, competing mutation, and inaccurate byte accounting.
- Added a 129-generation incremental/recovery/GC soak and full release evidence
  mapping for fault, corruption, concurrency, performance, platform,
  documentation, API, packaging, and publication gates.
- Replaced the false Browser overview with 19 genuine selected-page captures;
  page 07 is the real CSV Interpole Monitor in `Monitor Ready` state.
- Prepended a rendered three-page v3.5.3 release supplement to the Programmer
  Core API Guide, corrected the top spacing of all 634 light-blue API signature
  strips, and added the current Guaranteed Storage Markdown API index; the old
  v3.1.23 API Surface PDF is explicitly historical, not exhaustive.
- Included the immediate-root Phase 6 through Phase 11 status records in the
  source distribution so the Phase 9 -> Phase 10 -> Phase 11 progression is
  visible directly after extraction.
- Consolidated publication behind all release gates with PyPI trusted
  publishing. A tag is forbidden until cross-platform CI is green.
- Corrected Windows raw-descriptor writes to require binary mode throughout
  persistence, generation, segmentation, migration, and materialization.
- Preserved exact native/Python Spiral score parity on macOS by preventing
  compiler contraction across Python-equivalent arithmetic boundaries.

## v3.5.3-dev10 — Controlled Activation

- Added explicit `legacy` and `guaranteed-segmented` storage modes.
- Required exact verified migration evidence and operator acknowledgement before
  atomic activation.
- Added mode-aware commit status and a bounded observer surface.
- Added lossless rollback that materializes current guaranteed bytes into a new
  verified legacy mount without rewriting the original source or generations.

## v3.5.3-dev2

Added an opt-in immutable full-generation correctness prototype with atomic
CURRENT promotion, streaming SHA-256 verification, observable fallback, and
bounded retention cleanup. The legacy v2 persistence path remains unchanged.

## v3.5.3-dev3 — destructive persistence qualification

- Added real subprocess-death injection across generation commit boundaries.
- Added bounded metadata depth, node-count, type, and byte-size validation.
- Removed a full-payload copy from the generation write path by streaming memoryview slices.
- Expanded durability checkpoints around file and directory fsync operations.
- Development API remains opt-in and is not wired into the legacy mount path.

## v3.5.3-dev4 — Explicit Recovery State Machine

- Added typed recovery classifications for missing or malformed `CURRENT`, missing or incomplete generations, invalid metadata, unsupported schemas, identity mismatch, size mismatch, and checksum mismatch.
- Added `RecoveryReport` and `RejectedGeneration` so recovery decisions are inspectable without parsing prose.
- Recovery scans candidates deterministically newest-to-oldest under a hard candidate-count budget.
- Successful fallback can atomically repair `CURRENT`; inspection-only recovery can disable repair.
- Rejected and corrupt generations are preserved for diagnosis. Recovery performs no implicit deletion.
- Added compound-failure, interrupted-pointer-repair, unsupported-format, bounded-scan, and fail-closed tests.

## v3.5.3-dev5 - Retention and restartable cleanup

- Added persistent generation pins.
- Added explicit acknowledgement for destructive pruning and unpinning.
- Added durable restartable cleanup plans and atomic quarantine-before-delete.
- Rechecks current and pinned protection immediately before each destructive action.
- Recovery continues to preserve rejected evidence and performs no cleanup.
- Corrected all 634 overlapping light-blue API signature strips throughout the
  Programmer Core API Guide.

## v3.5.3-dev5.1 - Buffer streaming hardening

- Formalized commit-buffer ownership through `BufferPolicy`.
- Preserved zero-copy streaming for read-only C-contiguous buffers.
- Rejected mutable and non-contiguous buffers by default before promotion.
- Added explicit immutable snapshot mode for mutable or strided exporters.
- Hardened partial-write retry and zero-progress failure handling.
- Explicitly releases temporary memory views on every exit path.
- Added byte-format, multi-byte exporter, strided-view, mutation, and write-fault tests.

## v3.5.3-dev6 - Guaranteed storage transition fit

- Added an opt-in `GuaranteedStorageBridge` between the stable legacy serializer
  and immutable generations without changing default persistence behavior.
- Complete legacy-compatible mounts are produced in isolated staging and streamed
  into a single atomic generation using bounded memory.
- Added a deterministic transition-image format with per-file SHA-256 digests,
  strict path validation, file-count and path-length budgets, truncation checks,
  and atomic materialisation into a new destination.
- Added `ImmutableGenerationStore.commit_stream()` for stable read-only chunk
  streams; mutable or non-contiguous chunks fail closed before promotion.
- Qualified legacy round-trip equivalence, failed-transition preservation,
  traversal rejection, existing-destination refusal, and stream ownership rules.

## v3.5.3-dev7 — Materialisation Fault Qualification

- Added subprocess crash qualification around every materialisation durability boundary.
- Added unique private extraction directories and explicit materialisation reports.
- Added exact, Unicode-normalized, and case-folded path collision rejection.
- Added a second exact-inventory verification immediately before atomic publication.
- Added short-write, zero-progress, permission, symlink, unexpected-file, and destination-race tests.
- Verified 779 passed and 11 skipped in the complete monolithic suite.

## v3.5.3-dev9 — Incremental Immutable Segments

- Added explicit content-addressed immutable segment generations beside the
  proven full-image generation path.
- Added immutable ordered manifests with complete logical length and SHA-256.
- Unchanged fixed-size segments are reused and never rewritten.
- Added bounded streaming reconstruction through the existing hardened
  materialisation engine.
- Added deterministic segment-generation recovery and pointer repair.
- Added manifest-derived reference accounting and dry-run-first safe GC.
- Added cross-process fail-closed mutation exclusion across commit, generation
  deletion, and segment collection.
- Preserved full legacy compatibility, independent pointers, opt-in behavior,
  and the prohibition on activation before Phase 10.

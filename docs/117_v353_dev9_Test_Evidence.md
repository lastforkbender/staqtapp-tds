# v3.5.3-dev9 Qualification Evidence

## Dedicated Phase 9 qualification

`tests/test_v353_incremental_immutable_segments.py`

- 24 passed
- 0 failed

Coverage includes immutable content addressing, fixed-segment reuse, changed-segment
writes, canonical and exact-schema manifest validation, strict scalar typing,
segment corruption and absence, publication interruption, reference accounting,
dry-run and destructive GC, current-generation protection, deterministic recovery,
legacy-compatible bridge materialisation, independent full-image compatibility,
and fail-closed mutation exclusion.

## Integrated Guaranteed Storage qualification

The Phase 9 suite together with the complete dev8 round-trip and dev7
materialisation-fault suites completed with:

- 49 passed
- 0 failed

## Broader regression partitions

Two completed test-file partitions produced:

- 312 passed / 11 skipped
- 175 passed / 0 skipped

A remaining legacy partition exceeded the execution command ceiling while still
showing passing progress. It is not counted as completed and no failure is
claimed or concealed.

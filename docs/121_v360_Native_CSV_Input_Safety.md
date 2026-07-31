# v3.6.0 Native CSV input-safety repair

## Scope

This is the first native-correctness repair stacked on the v3.6.0 Foundation
Repair contract. It closes one defect class only: mutable Python buffer objects
must never remain the source of GIL-free, two-pass native CSV scans.

It does not add ranking, graph traversal, sentinels, forests, neural inference,
CSV publication changes, storage writes, or activation authority.

## Prior risk

The native CSV sidecar accepted a generic `Py_buffer`, retained its raw pointer,
and released the GIL for both the counting pass and the row-offset pass. A
`bytearray` or mutable buffer exporter could therefore change while C was
reading it. Consequences included:

- non-repeatable scan statistics;
- disagreement between the count and offset passes;
- offset writes based on a stale allocation count; and
- undefined behavior from a concurrent mutable-buffer read.

The allocation expression and chunk-count formula also lacked explicit overflow
proofs.

## Repair contract

The scanner now applies this ownership rule before releasing the GIL:

```text
exact bytes
    -> hold a strong reference
    -> scan zero-copy

any other contiguous buffer exporter
    -> acquire a read buffer while the GIL is held
    -> make exactly one owned bytes snapshot
    -> release the exporter
    -> scan only the snapshot
```

The public prototype ABI and backend names remain unchanged. The module exposes
an additive evidence constant:

```text
CSV_NATIVE_SCAN_INPUT_OWNERSHIP =
    "bytes-zero-copy;other-contiguous-buffers-snapshot"
```

## Arithmetic and two-pass guards

The same repair adds:

- checked `row_count * sizeof(Py_ssize_t)` allocation arithmetic;
- overflow-free ceiling division for `chunk_count`;
- explicit rejection of escape tokens below `-1`;
- a capacity argument for the offset pass;
- a written-offset count returned by the GIL-free pass; and
- fail-closed equality between counted rows and written offsets.

No mismatch is normalized or partially returned.

## Qualification

The focused native qualification covers:

- bytes, bytearray, mutable memoryview, and read-only memoryview parity;
- non-contiguous-buffer rejection before GIL-free work;
- exporter release after the snapshot is taken;
- invalid token and chunk bounds;
- a concurrent mutation stress fixture proving that post-snapshot changes do
  not alter the scan result;
- existing scan, row-anchor, and performance-gate regressions;
- strict C warning compilation; and
- AddressSanitizer and UndefinedBehaviorSanitizer runs.

The release workflow admits the new native sanitizer matrix as a required gate.
A sanitizer failure blocks distribution construction and the aggregate release
gate.

## Authority boundary

This repair remains a mechanical, read-only sidecar. It cannot:

- write TDS storage;
- determine semantic truth;
- change privacy or license policy;
- train or promote a model;
- activate a serving bundle;
- enter storage locks; or
- influence frontier-model logits.

The next native repair must remain separately reviewable rather than expanding
this change into a general native-engine rewrite.

# TDS v3.5.3-dev5.1 — Buffer Streaming Hardening

## Invariant

The checksum and persisted bytes must describe one stable logical snapshot. A failed buffer contract or I/O operation must never promote `CURRENT`.

## Policies

- `require_stable`: zero-copy, read-only, C-contiguous exporters only.
- `snapshot`: explicit immutable copy for mutable or non-contiguous exporters.

## Writer guarantees

- one-dimensional raw-byte view after validation;
- bounded 1 MiB slices;
- retry on partial positive writes;
- fail on zero progress;
- hash only bytes reported written;
- explicit view release;
- verification before pointer promotion.

## Qualification

Tests cover immutable bytes, read-only views, mutable rejection, snapshot semantics, strided views, multi-byte formats, short writes, zero-progress writes, exporter resize after completion, and invalid policy rejection.

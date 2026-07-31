# v3.6.0 Native diagnostic-ring truth repair

## Scope

This is the next bounded Wave A native-correctness repair from the Frontier
Evidence Fabric redesign. It replaces the diagnostic event ring's volatile and
plain-structure publication with one fail-closed C11 atomic protocol and makes
automatic observer detail bounded by default.

It does not add dataset generations, graph traversal, sentinels, random forests,
neural specialists, learned serving, cache writes, storage writes, training,
promotion, or activation authority.

## Publication protocol

The extension declares:

```text
TDS_NATIVE_DIAG_PROTOCOL = c11-atomic-slot-seqlock-mpsc-v1
```

Every ring slot owns an atomic publication version and fixed-width atomic event
fields. A producer claims one slot without waiting, writes the event, and
release-publishes a stable even version. A snapshot accepts a copy only when the
version is unchanged before and after the read and the stored sequence matches
the requested sequence.

A busy slot is dropped and counted. No producer waits for a reader, another
producer, telemetry, Browser, or storage operation.

## Reset behavior

Reset closes event admission, waits only for active event publishers, clears
atomic state, restores the fixed capacity, and reopens publication. It never
acquires a TDS storage/index lock and does not alter index data.

## Sampling contract

The default contract is:

```text
TDS_NATIVE_DIAG_SAMPLING = burst=64;period=1024;manual=all
```

- The first 64 automatic events after reset are retained.
- Thereafter one automatic event is retained per 1,024 attempts.
- Explicit manual diagnostic evidence is never sampled.
- Mechanical operation and transition counters remain exact.

The snapshot exposes attempts, sampled-out detail, slot contention, emitted
events, overwritten events, and wrap count. Sampling is visible evidence rather
than silent loss.

## Qualification

The repair is gated by strict C11 compilation, existing diagnostic compatibility,
concurrent GIL-free publishers, reset pressure, manual-event preservation,
bounded default event volume, ASan, UBSan, platform/native suites, distribution
construction, and the aggregate release gate.

This tranche closes the ring data-race and default per-lookup event-tax defect
classes. It does not claim that all Phase-2 lifecycle, threaded-index, handle,
free-threaded, TSan, or architecture-parity gates are complete.

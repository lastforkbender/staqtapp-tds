# v3.6.0 native architecture parity truth

## Scope

This is the sixth bounded Native Correctness tranche in the Foundation train.
It proves that the native byte, integer, fault, packed-wire, and compatibility
scoring surfaces required by later Trace Ranking have one deterministic meaning
on native x86-64 and AArch64 Linux runners.

It follows the merged input-ownership, checksum/UTF-8, C11 diagnostic-ring,
handle-generation, immutable frozen-index, and lifecycle-admission repairs. It
does not introduce dataset generations, waypoints, a graph planner, sentinels,
forests, neural specialists, learned serving, cache writes, dataset writes,
training, promotion, or activation authority.

## Evidence contract

Each architecture independently emits:

```text
TDS_NATIVE_ARCHITECTURE_PARITY_FORMAT =
  tds.v360.native-architecture-parity.v1

pinned semantic root =
  d2e839477d432cdf9e328982e6e9a245295dd05c80ddac4937232c0b72bc9d09
```

The semantic root is SHA-256 over a domain-separated canonical JSON projection.
It includes only observable contracts and results that must be identical. It
excludes runner names, operating-system image versions, compiler descriptions,
Python build strings, process-local namespace IDs, process-local snapshot IDs,
paths, timestamps, and performance.

The evidence envelope preserves those machine facts separately for audit.
Both reports must bind the same source commit before comparison succeeds.

## Covered native truth

The projection binds:

- Native ABI, engine, capability, checksum, UTF-8, diagnostics, handle,
  frozen-index, packed-lookup, lifecycle, and CSV-kernel contracts.
- CRC32 IEEE and historical FNV-1a results for empty, published check-vector,
  ASCII, UTF-8, and all-byte fixtures; scalar and batch results must agree.
- Strict RFC 3629 chunk boundaries across one- through four-byte code points,
  plus exact fault type, byte range, and reason for malformed sequences.
- CSV scan and row-offset results across empty, quoted-newline, CRLF, UTF-8,
  escape, and bare-CR fixtures at multiple requested chunk sizes.
- Monotonic handles, explicit allocation, collision and exhaustion faults,
  namespace separation, epoch changes, slot generation, stale-reference
  rejection, and resize behavior.
- Immutable tombstone-free frozen snapshots, canonical little-endian offsets,
  canonical signed-`int64` results, missing-handle encoding, source-snapshot
  independence, and malformed-input rejection before output mutation.
- Exact IEEE-754 binary64 result bits for the retained compatibility Spiral
  baseline against an operation-order-matched Python reference.
- Controlled C11 diagnostic reset, manual-event publication, sampling settings,
  counters, stable event fields, and zero authority.

## ARM execution

GitHub Actions builds the extensions independently on:

```text
ubuntu-24.04       -> x86_64
ubuntu-24.04-arm   -> aarch64
```

Each runner executes the projection directly against the compiled extensions,
without importing the broader Python package or optional GUI/scientific
dependencies. Each report is archived even if its pinned-root check fails, so a
platform difference remains preserved evidence rather than disappearing behind
a skipped comparison.

A separate x86 runner downloads both reports and requires:

1. verified canonical root for each report;
2. exactly one x86-64 report and one AArch64 report;
3. identical semantic projections;
4. identical semantic roots;
5. one common source commit; and
6. the pinned expected root.

## Failure meaning

A mismatch is a release blocker. It must be repaired at the earliest differing
native surface. The comparison does not use tolerance, rounded decimal output,
architecture normalization of result bytes, or post-hoc field deletion.
Machine-specific build evidence may differ; native meaning may not.

## Authority boundary

Architecture reports are qualification evidence only:

```text
functional_authority = false
activation_authority = false
```

They cannot activate a package, publish a generation, alter policy, authorize
storage, approve semantics, or enable learned Trace Ranking. The package remains
at the historical `3.5.3.post2` identity until the complete Foundation Repair
exit gate qualifies. The completed release remains `3.6.0`, and later
corrections use patch increments rather than `.postN`.

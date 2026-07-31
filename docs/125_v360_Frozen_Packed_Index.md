# v3.6.0 immutable frozen packed-index repair

## Scope

This is the fifth bounded Native Correctness repair in the Foundation train. It
introduces a handle-only immutable snapshot for request-time native reads and a
caller-owned packed lookup ABI. It follows the merged ownership, checksum/UTF-8,
diagnostic-ring, and handle-generation truth repairs.

It does not introduce dataset generations, waypoint graphs, path planning,
sentinels, forests, neural specialists, learned serving, cache writes, dataset
writes, promotion, activation, or semantic authority.

## Request-path topology

```text
mutable NativeHandleIndex
        |
        | freeze off request path under one source read lock
        v
NativeFrozenHandleIndex
        |- copied immutable key bytes
        |- compact tombstone-free rehashed table
        |- process-local snapshot identity
        |- source namespace and source epoch binding
        |- no mutable-index lock for reads
        `- no mutation surface
```

The snapshot identity is local execution evidence. It is not a durable content
root and must not be exchanged between servers. A later immutable Dataset
Generation and composite ServingEpoch remain responsible for persistent
content-addressed authority.

## Packed lookup ABI

The native extension declares:

```text
TDS_NATIVE_FROZEN_INDEX_CONTRACT =
  immutable-rehash-copy;lock-free-read-v1

TDS_NATIVE_PACKED_LOOKUP_CONTRACT =
  keys-bytes;offsets-le64;handles-le-i64;caller-owned-output-v1
```

Input consists of:

1. exact immutable key bytes containing concatenated keys;
2. exact immutable canonical little-endian `uint64` offsets with `count + 1`
   entries; and
3. one caller-owned writable one-dimensional byte buffer of exactly
   `count * 8` bytes.

The first offset is zero, offsets are strictly increasing and in bounds, and
the final offset equals the key-byte length. Empty key spans are rejected.
Every offset is validated before any output
byte is changed. Missing keys are encoded as signed `int64 -1`, whose canonical
little-endian bytes are eight `0xff` values.

The compatibility ceiling is 65,536 keys per packed call. The future Trace Rank
ABI request profile may only narrow that bound.

## Hot-path behavior

After admission validation, the packed C loop:

- allocates no result array;
- creates no Python integer per result;
- acquires no mutable index lock;
- writes no shared counter or observer state;
- performs one GIL release/reacquisition per complete batch;
- writes directly into caller-owned output; and
- permits concurrent readers of the same immutable snapshot when each worker
  owns its output buffer.

The snapshot contains handles only. Its table is compacted to a deterministic
power-of-two capacity at or above twice the live-entry count. Python entry
objects, per-worker counters, and storage authority remain outside it.

## Qualification

Required evidence includes strict C11 warning compilation, scalar and packed
parity, tombstone rehashing, source-snapshot independence, exact little-endian
encoding, malformed-offset failure before output mutation, maximum/one-over
bounds, deterministic valid/malformed format fuzzing, concurrent readers,
ASan, UBSan, a direct extension-focused TSan smoke, platform/native suites,
distribution construction, and the aggregate release gate.

`tools/benchmark_v360_frozen_index.py` records one-worker and two-worker
aggregate distributions. Its output is performance evidence only. The Phase-2
scaling gate must be replayed on a named reference CPU and bound to exact source,
workload, hardware, and sample identities before release qualification.

## Cross-architecture semantic parity

Phase 2 requires the native truth surfaces to produce one semantic result on
x86-64 and AArch64. `tools/architecture_parity_v360_native.py` projects only
canonical contracts and deterministic results from the checksum registry,
strict UTF-8 boundaries, CSV scan/offset kernels, handle generation/reference
validation, immutable freeze, and caller-owned packed lookup.

The projection deliberately excludes process-local namespace and snapshot IDs,
host paths, wall-clock data, and performance measurements. Canonical JSON is
rooted with SHA-256. Both native architectures must reproduce:

```text
6f45762b762ea7931bc185a95a9e9e253bd83ba0b48a9dd12f7ea130fb6cfb36
```

The release workflow executes the proof on native `x86_64` and `aarch64`
GitHub-hosted Ubuntu runners. Each lane emits a complete architecture report;
a root mismatch is a release failure. This evidence proves the bounded Phase-2
integer/byte semantics covered by the projection. It does not yet qualify a
waypoint graph, fixed-point planner, sentinel forest, or learned serving path.

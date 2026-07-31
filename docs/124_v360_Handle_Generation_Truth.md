# v3.6.0 Native handle-generation truth repair

## Scope

This bounded Wave A native-correctness repair closes the compatibility index's
handle-collision and stale-slot ambiguity classes before immutable dataset
generations, waypoint graphs, sentinels, or forest inference are introduced.

It does not make the mutable compatibility index the future ranking request
path. The next native tranche must freeze mutable construction into immutable
read-only pages and caller-owned packed lookup arenas.

## Identity contract

Every native index receives one positive, process-monotonic namespace identity
and begins at index epoch `1`. The namespace is not caller-selectable and is
never reused during the process lifetime.

A structural resize increments the index epoch. A physical slot increments its
slot generation whenever that slot is reused after deletion. The extension
therefore exposes the fixed reference form:

```text
(namespace_id, index_epoch, slot_index, slot_generation, handle)
```

The exact contract identity is:

```text
TDS_NATIVE_HANDLE_REF_CONTRACT =
    namespace-epoch-slot-generation-handle-v1
```

`get_handle_ref(key)` returns this bounded tuple for an existing key.
`resolve_handle_ref(ref)` succeeds only when every component still matches the
same live slot. It returns `-1` for a different namespace, stale epoch, invalid
slot, stale generation, altered handle, deleted key, or reused slot.

These references are server-process-local capability coordinates. Persistent or
cross-process evidence must additionally bind the immutable dataset generation
and composite ServingEpoch; a low-level handle reference is never an authority
or durable identity by itself.

## Monotonic handle allocation

Automatic handles are positive signed 64-bit integers allocated from one
monotonic high-water mark. They are never reused after deletion.

Explicit handles remain a narrow compatibility surface and must:

- be positive;
- be unique among live entries;
- be at or above the current monotonic high-water mark; and
- advance the high-water mark on acceptance.

An existing key may be reinserted only with its existing handle. Attempted
remapping, collision, reuse below the high-water mark, and signed 64-bit
exhaustion fail deterministically.

## Arithmetic and lifecycle guards

The same repair adds:

- checked power-of-two capacity rounding;
- checked slot-allocation bounds;
- checked capacity doubling;
- overflow-free load-threshold calculation;
- deterministic empty batch behavior;
- one-time initialization enforcement; and
- explicit epoch, slot-generation, handle, and capacity exhaustion failures.

Existing-key insertion is evaluated before resize pressure, so an idempotent
update cannot invalidate references merely because the table is above the
next-new-key resize threshold.

## Python/native adapter surface

`NativeEntryIndexBackend` exposes:

- `identity()`;
- `get_handle_ref(key)`;
- `resolve_handle_ref(ref)`; and
- namespace, epoch, and contract identity in native execution evidence.

The Native Engine Manager reports whether the loaded extension supports the
reference operations and the exact reference contract.

## Authority boundary

This repair cannot:

- write dataset generations;
- determine semantic truth;
- change privacy, license, or provenance policy;
- train or promote a model;
- activate a ServingEpoch;
- enter a frontier-model reasoning loop; or
- grant a mutable handle reference storage authority.

The mutable index remains a compatibility construction surface. The future
request path must consume an immutable frozen view under one pinned generation.

## Qualification

Required coverage includes:

- unique namespace identities;
- stable identity and exact stats evidence;
- explicit collision and remapping rejection;
- no reuse below the monotonic high-water mark;
- signed 64-bit exhaustion;
- cross-index and forged-reference rejection;
- deletion and slot-reuse invalidation;
- resize epoch invalidation;
- idempotent updates without spurious resize;
- empty batches and capacity overflow;
- Python wrapper parity;
- strict C11 warnings;
- ASan and UBSan;
- broad pure/native/platform suites; and
- distribution and aggregate release gates.

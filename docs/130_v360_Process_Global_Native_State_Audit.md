# v3.6.0 Process-Global Native-State Audit

## Status and scope

This is the complete Phase 1 inventory for the two optional native C translation
units present in the v3.6.0 Foundation source. It classifies every object with
static storage duration, including file-scope CPython descriptors and
function-local immutable lookup/keyword tables.

The five required dispositions are used exactly:

1. **immutable after initialization**
2. **atomic observer state**
3. **guarded lifecycle state**
4. **compatibility-only state**
5. **must be migrated**

No object in this audit has storage, semantic, model, policy, release, Browser,
or activation authority. Per-instance `NativeHandleIndex`, frozen-index, module
state, input snapshots, buffers, locks, and request-local values are not
process-global objects and therefore are not listed here.

## Determination

| Disposition | Object count | v3.6.0 result |
|---|---:|---|
| immutable after initialization | 16 | permitted |
| atomic observer state | 10 | permitted and non-authoritative |
| guarded lifecycle state | 1 | permitted with fail-closed admission |
| compatibility-only state | 2 | permitted only as process-local acceleration identity |
| must be migrated | 0 | none remaining |
| **Total** | **29** | **closed** |

A future source change that adds static-duration state must update this audit and
the machine-checkable mutable-state registry before the Foundation Closure can
remain valid.

## `_native_index.c`

### Immutable after initialization

| Object | Scope | Reason and boundary |
|---|---|---|
| `NativeFrozenHandleIndexType` | translation unit | CPython type descriptor; completed by `PyType_Ready`, then treated as read-only. |
| `NativeHandleIndex_methods` | translation unit | CPython method descriptor table; static metadata only. |
| `NativeHandleIndexType` | translation unit | CPython type descriptor; completed by `PyType_Ready`, then treated as read-only. |
| `NativeFrozenHandleIndex_methods` | translation unit | CPython method descriptor table; static metadata only. |
| `module_methods` | translation unit | CPython module method descriptor table; static metadata only. |
| `native_module_slots` | translation unit | PEP 489 module-slot descriptor table; static metadata only. |
| `moduledef` | translation unit | CPython module descriptor; initialized for process admission and not used as mutable TDS authority. |
| `module_diag_snapshot::kwlist` | function local | Immutable keyword-name table used only while parsing one call. |
| `module_diag_set_sampling::kwlist` | function local | Immutable keyword-name table used only while parsing one call. |
| `crc32_ieee_nogil::table` | function local | Immutable 16-entry CRC32 nibble lookup table. |
| `NativeHandleIndex_init::kwlist` | function local | Immutable keyword-name table used only while parsing construction. |
| `module_spiral_rank_scores::kwlist` | function local | Immutable compatibility-ranker keyword-name table. |

### Atomic observer state

| Object | Synchronization and reset boundary |
|---|---|
| `g_diag_enabled` | Lock-free C11 atomic observer enable flag; explicit observer control only. |
| `g_diag_degraded` | Lock-free C11 atomic degradation flag; diagnostic reset only. |
| `g_diag_sequence` | Lock-free C11 event sequence; diagnostic reset only. |
| `g_diag_counters` | Bounded C11 atomic counter array; diagnostic reset barrier. |
| `g_diag_sample_burst` | Lock-free C11 sampling control; explicit observer control only. |
| `g_diag_sample_interval` | Lock-free C11 sampling control; explicit observer control only. |
| `g_diag_automatic_attempts` | Lock-free C11 sampling sequence; diagnostic reset only. |
| `g_diag_active_event_writers` | C11 atomic reset-publication barrier. |
| `g_diag_resetting` | C11 atomic reset gate. |
| `g_diag_ring` | Bounded lossy ring with per-slot C11 atomic publication; event loss cannot affect storage truth. |

### Guarded lifecycle state

| Object | Contract |
|---|---|
| `g_native_module_instance_active` | One process-lifetime module admission through C11 compare-exchange. Subinterpreters, repeat initialization, and free-threaded admission remain fail-closed; process restart is required after successful admission. |

### Compatibility-only state

| Object | Contract |
|---|---|
| `g_index_namespace_sequence` | Monotonic process-local native-index namespace. It is acceleration identity only: never durable, never exchanged, and never evidence authority. Exhaustion fails closed. |
| `g_frozen_snapshot_sequence` | Monotonic process-local frozen-snapshot identity. It is acceleration identity only: never durable, never exchanged, and never evidence authority. Exhaustion fails closed. |

### Must be migrated

None.

## `_csv_scan_kernel.c`

### Immutable after initialization

| Object | Scope | Reason and boundary |
|---|---|---|
| `CsvScanKernelMethods` | translation unit | CPython method descriptor table; static metadata only. |
| `csv_scan_kernel_module` | translation unit | Single-phase stateless CPython module descriptor; initialized once and not a TDS authority. |
| `csv_scan_kernel_scan_bytes::kwlist` | function local | Immutable keyword-name table used only while parsing one call. |
| `csv_scan_kernel_row_offsets::kwlist` | function local | Immutable keyword-name table used only while parsing one call. |

### Atomic observer state

None.

### Guarded lifecycle state

None. The sidecar remains single-phase only because it has no mutable
process-global state and acquires an immutable owned input before releasing the
GIL.

### Compatibility-only state

None.

### Must be migrated

None.

## Machine-checkable boundary

`staqtapp_tds.native.foundation` fail-closes on any new, missing, or renamed
file-scope mutable `g_` state symbol and binds the exact C-source SHA-256 values,
lifecycle markers, immutable-input markers, process-state registry root, and
narrow performance-claim root. This document completes the broader static-
duration inventory, including immutable CPython metadata and function-local
immutable tables.

The machine registry and this complete audit are complementary:

- the registry prevents silent mutation-state expansion;
- this audit proves the full Phase 1 classification;
- neither grants release or runtime authority.

## Performance-claim closure

The v3.6.0 performance claim is permanently narrowed to the evidence actually
qualified for this release:

```text
deterministic native correctness:             qualified
x86-64/AArch64 covered semantic parity:       qualified
shared-runner aggregate no-regression floor:  1.00x
named-reference-CPU claim:                    false
universal scaling claim:                      false
```

A named-reference-CPU result can be added later only as a separately qualified
artifact. Its absence does not widen the v3.6.0 claim and does not authorize any
throughput, scaling, or production-activation statement.

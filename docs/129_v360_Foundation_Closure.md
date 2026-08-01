# v3.6.0 Foundation Closure

## Status

This document closes the bounded v3.6.0 Foundation Repair train on the current
canonical TDS main line. It supersedes the temporary candidate wording in the
individual native-hardening records; it does not rewrite their evidence.

The public source identity is:

```text
3.6.0
```

Corrections use `3.6.1`, `3.6.2`, and later patch releases. The historical
`3.5.3.post1` and `3.5.3.post2` releases remain immutable.

## Scope closed by v3.6.0

The Foundation release contains the independently qualified native and authority
repairs already merged into TDS:

- exact native ABI/capability admission with deterministic Python fallback;
- immutable input ownership before GIL-free checksum, UTF-8, and CSV work;
- explicit CRC32 identity and read-only historical FNV-1a compatibility;
- strict RFC 3629 UTF-8 boundary validation;
- namespace, index-epoch, slot-generation, and monotonic-handle identity;
- bounded C11 atomic diagnostic publication separated from storage locks;
- immutable frozen native indexes and caller-owned packed lookup output;
- PEP 489 native-index initialization and fail-closed lifecycle admission;
- explicit free-threaded and subinterpreter rejection until isolation qualifies;
- exact x86-64/AArch64 semantic parity for the covered native contracts; and
- repeated AArch64 sanitizer, concurrency, malformed-format, and scaling
  qualification.

v3.6.0 adds no Atomic Generation Plane, Eaglegate runtime, graph planner,
learned sentinel, random forest, agent pool, request-path training, model
authority, or activation authority.

## Process-global native-state closure

The native-index extension retains a deliberately closed set of process-scoped
state. Every mutable symbol uses the `g_` prefix and belongs to one of five
mechanical classes:

| Class | Symbols | Contract |
|---|---|---|
| Monotonic identity | `g_index_namespace_sequence`, `g_frozen_snapshot_sequence` | Process-local, non-durable identifiers. Never reset; exhaustion fails closed. |
| Lifecycle guard | `g_native_module_instance_active` | One process-lifetime module admission. Successful unload does not reopen admission; restart is required. |
| Observer control | `g_diag_enabled`, `g_diag_degraded`, `g_diag_sequence`, `g_diag_sample_burst`, `g_diag_sample_interval`, `g_diag_automatic_attempts`, `g_diag_active_event_writers`, `g_diag_resetting` | Lock-free C11 observer controls. They do not own storage objects or storage locks. |
| Observer counters | `g_diag_counters` | Bounded exact mechanical counters, reset only through the diagnostic reset barrier. |
| Observer ring | `g_diag_ring` | Bounded lossy event copies with per-slot C11 publication. Event loss cannot affect storage truth. |

Static CPython type and method descriptors are process-scoped implementation
metadata, initialized before successful module admission. They are not mutable
storage, model, semantic, policy, or release authority.

The optional CSV scan sidecar has no `g_` process-global mutable state. It owns
an immutable input snapshot before releasing the GIL. Its single-phase module
shape is retained only because the module is stateless; adding process-global
mutable state requires a new lifecycle contract and qualification.

The machine-checkable mutable-state registry and source audit live in:

```text
staqtapp_tds.native.foundation
```

A new, missing, or renamed process-global `g_` symbol fails the Foundation
Closure audit until it is explicitly classified and reviewed.

The complete static-duration inventory required by Phase 1 lives in:

```text
docs/130_v360_Process_Global_Native_State_Audit.md
```

That audit applies the five required dispositions exactly to all 29 native C
objects with static storage duration, including immutable CPython descriptors
and function-local immutable tables:

```text
immutable after initialization  16
atomic observer state            10
guarded lifecycle state           1
compatibility-only state          2
must be migrated                  0
```

The machine registry and the complete inventory are complementary. The registry
prevents silent mutable-state expansion; the inventory closes the exact Phase 1
classification boundary. Neither grants runtime or release authority.

## Performance claim boundary

v3.6.0 deliberately makes the narrow claim supported by the evidence:

```text
deterministic native correctness:             qualified
shared-runner aggregate no-regression floor:  1.00x
x86-64/AArch64 covered semantic parity:       qualified
named-reference-CPU scaling claim:            false
universal scaling claim:                      false
```

The hosted measurements remain useful evidence, including the independently
recorded multi-worker x86-64 and AArch64 results. They are not converted into a
universal throughput guarantee. A named-reference-CPU claim may be introduced
later as a separately rooted performance artifact; it is not required for the
v3.6.0 correctness release.

Performance evidence has no functional, storage, semantic, policy, release, or
activation authority.

## Machine-checkable closure report

From a source checkout:

```bash
staqtapp-tds-foundation-closure --root . --json
python -m staqtapp_tds.native.foundation --root . --json
```

The canonical report binds:

- exact release identity;
- native-index and CSV-sidecar source SHA-256 identities;
- the complete mutable process-state registry root;
- declared, missing, and unexpected process-global symbols;
- required lifecycle, diagnostic, immutable-index, and input-ownership markers;
- the narrowed performance-claim root; and
- explicit no-authority declarations.

The report contains no prompt, token sequence, logits, hidden state, KV tensor,
model artifact, or private application content.

## Release exit gate

v3.6.0 is release-ready only when all of the following pass on the exact source
head:

1. The Foundation Closure report passes and is byte-identical across repeated
   execution.
2. Every mutable process-global native symbol is present in the closed registry,
   no unclassified symbol exists, all 29 static-duration objects are present in
   the complete audit, and the `must be migrated` count is zero.
3. Native lifecycle, subinterpreter, and free-threaded policies remain
   fail-closed as declared.
4. Python 3.10 through 3.14, Windows, macOS, Linux native, sanitizer,
   ThreadSanitizer, fuzz, architecture-parity, package-build, and installation
   gates pass.
5. The source, installed metadata, and imported package identity all equal
   `3.6.0`.
6. Temporary transfer/materialization/fixer workflows and premature v3.7 tag,
   release, or publication artifacts are absent.
7. No Atomic Generation, Eaglegate, learned-serving, or activation path is
   admitted by this release.

A production tag and PyPI publication remain separate release-controller
operations after the exact merged source head passes the tag matrix.

## Next architecture line

The next canonical implementation phase is v3.7.0 Atomic Generation
Convergence, reconstructed from current `main`. It must provide one immutable,
crash-safe generation and publication authority for CSV evidence and future TDS
control-plane consumers before Eaglegate is merged.

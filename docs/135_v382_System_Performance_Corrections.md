# v3.8.2 System Performance Corrections

Status: **production release**.

## Scope and authority

The attached v3.8.1 assessment identified one severe native allocator defect
and kept every other observation as a hypothesis. The user's later system-wide
request widened the release review to Core, persistence and observation, CSV
capabilities, Generation Authority, Driver Foundry/VM/Studio, Trace Rank, and
Eaglegate. Corrections were admitted only when they preserved the relevant
semantics and were protected by focused regression sentinels.

Performance evidence remains engineering feedback. It cannot authorize Driver
activation, CSV semantic truth, Generation publication, Eaglegate serving,
canary traffic, promotion, token acceptance, or KV commit.
Eaglegate remains shadow/target-only, and the manual credentialed H100 workflow
has not been executed and remains required for any hardware-evidence claim.

## Corrected findings

| Area | Confirmed failure | Correction | Preserved contract |
|---|---|---|---|
| Native index | Automatic handle allocation scanned the entire table even though the write-locked high-water handle cannot already exist, producing quadratic insertion. | Removed that one scan; explicit requested handles still perform collision and monotonicity checks. | Handle values, exhaustion, deletion, resize, restore, and concurrency semantics. |
| Native footprint | The single native table multiplied a Python shard facade into 4,096 eager slots per empty directory. | Fixed native initial capacity at 1,024 and retained dynamic resize. | Backend selection and resize/reference invalidation rules. |
| Telemetry | One logical read/write/JSON observation acquired the same lock repeatedly. | Updates the same exact counters and timers under one acquisition. | Counter names, totals, timer counts, levels, and snapshot schema. |
| JSON/observation | Every codec call constructed an immutable statistics record; engineering snapshots traversed the directory tree separately for Swiss, radix, and storage views, and native telemetry scanned one table twice. | Updates primitive counters under one lock, materializes the public record only on request, combines Swiss/radix traversal, and shapes both native views from one table scan. | Exact concurrent totals, reset behavior, telemetry levels, failure isolation, and public snapshot schema. |
| Persistence read | Sidecar metadata was linearly scanned per read and compressed payloads were decompressed twice. | Builds O(1) sidecar indexes, publishes a complete reload snapshot under one lock, and deserializes the already verified decompressed bytes. | Sidecar validation, reload atomicity, payload hashes, codec failures, and result codes. |
| Persistence write | Payloads were joined and copied into another full-file bytearray before one write. | Streams header, immutable payloads, and index through a bounded 1 MiB buffer, including partial-write retry and zero-progress failure handling. | On-disk bytes, fsync, atomic replace, sidecar ordering, shadow cleanup, and recovery. |
| CSV import/export | Authoritative bytes were hashed repeatedly and canonical export materialized all rows. | Reuses one source digest and streams parsed rows to the writer. | CSV ID, manifest, row offsets, original bytes, and canonical output. |
| CSV scan evidence | Materialization and parity paths repeated full scans, row hashing, and large profile conversions. | Reuses one scan profile for raw identity, offsets, row anchors, and parity; compares immutable dataclasses directly; resolves artifact writes from the canonical CSV identity instead of redirectable manifest fields. | Reference/native parity fields, row hashes, errors, canonical artifact routing, and artifact schema. |
| CSV generation | Offset validation was O(n log n), packing created many small objects, chunks were copied/hashed repeatedly, and load reconstructed a second full source. | Linear canonical validation with `pack_into`, preflighted bounds, reuse of exact hashed chunk bytes, and direct comparison of lease-verified chunks to authoritative spans. | Generation format, roots, byte identity, lease verification, and failure classes. |
| Semantic IR | Duplicate detection repeatedly called tuple `count`, becoming quadratic. | One-pass seen/duplicate sets with the same sorted error output. | Proposition, transition, authorization, and error ordering. |
| Generation Authority | Immutable manifest roots were repeatedly serialized/hashed and every chunk read repeated a linear search over payload identities. | Admits exact immutable manifest records before caching roots and binary-searches canonical payload names. | Canonical bytes, roots, dataclass field/serialization shape, receipt chains, publication CAS, pins, and payload verification. |
| Driver compile | Direct, Foundry, and Studio paths repeatedly validated the same just-parsed TDDL program. | A fused source-only parse/validate/build gate closes the unchecked builder lexically; arbitrary program compilation still performs full validation. | TDDL validation, bytecode hash, audit, Registry, and signing gates. |
| Runtime Manager/VM | Manager validation duplicated the audit's full validation; every opcode rebuilt the display contract table; SCAN/SCORE performed redundant recursive copies. | Uses the audit's validator, direct immutable cost lookup, and VM-owned records with detached final output. | Independent VM load validation, cost limits, result isolation, and fail-closed faults. |
| Driver Studio | Hydration repeatedly selected the same records and rebuilt timelines/whole-console dictionaries per review request. | Reuses selected records/timeline, indexes queue evidence once, and normalizes manual preview once. | Read-only Studio role, review hashes, action decisions, and Registry authority. |
| Trace Rank admission | Graph admission serialized, decoded, and revalidated the same immutable graph repeatedly. Verified waypoint materialization then revalidated every source binding for every waypoint, producing quadratic work. | Exact base records use one structure/source admission pass and bind a proof-scoped materializer to admitted immutable sources; non-exact subclasses are canonical decode-normalized before sealing. | Exact packed bytes, SHA-256/CRC32, nonzero-padding rejection, references, subclass fail-closed behavior, fault classes, and the fail-closed public materializer. |
| Eaglegate admission | Every decision rebuilt immutable epoch, identity, policy, plan, and request roots and linearly searched plans. | Caches derived roots outside dataclass state and uses an immutable plan map after epoch validation. | Canonical roots, dataclass equality/hash/serialization shape, fallback reasons, qualification gates, and target-only/shadow authority. |

The observation correction also preserves the public custom `"indexes"`
sampler namespace and the legacy per-index failure keys while using a separate
built-in combined index sampler. These compatibility details and the hostile
subclass, manifest-redirect, stale-cache, partial-write, and coordinated reload
sentinels are correctness gates, not benchmark-only checks.

## Local measurement evidence

Measurements were made on Linux x86-64 with CPython 3.12.13 and GCC `-O3`.
They demonstrate local causal shape; they are not universal hardware claims.

| Workload | v3.8.1 baseline | v3.8.2 | Local result |
|---|---:|---:|---:|
| Telemetry `record_read`, 200,000 calls | 0.563514 s | 0.128770 s | 4.38× faster |
| Persistence writer, 64 MiB raw payload, median `tracemalloc` peak | 67,129,697 B | 1,064,702 B | 63.05× lower traced peak |
| Persistence writer, same workload, median elapsed | 385.290 ms | 350.673 ms | 8.98% faster |
| Engineering snapshot, 1,000 directories | 22.872960 ms | 9.463020 ms | 2.42× faster |
| JSON canonical dump | 11.454165 us/op | 2.777573 us/op | 4.12× faster |
| JSON fast load | 9.192910 us/op | 1.876761 us/op | 4.90× faster |
| CSV scan plus row anchors, 757,670 B / 20,001 logical rows | 264.148198 ms | 83.734179 ms | 3.15× faster |
| CSV row-offset pack, 20,001 offsets, median `tracemalloc` peak | 2,753,576 B | 320,463 B | 88.36% lower traced peak |
| Generation root access, 4,096 payload manifest, eight reads | 310.724119 ms | 0.006660 ms | about 46,655× faster |
| Driver VM, 5,000 records / 11 iterations | 158.020 ms | 104.740 ms | 33.72% faster |
| Managed Driver VM, 5,000 records / 11 iterations | 306.791 ms | 220.813 ms | 28.02% faster |
| Studio review actions, same fixture | 13.848 ms | 3.682 ms | 73.41% faster |
| Eaglegate admission, 1 plan, warmed steady state | 65.375542 us/op | 4.524658 us/op | 14.45× faster |
| Eaglegate admission, 3 plans, warmed steady state | 81.217062 us/op | 5.787332 us/op | 14.03× faster |
| Eaglegate admission, 128 plans, warmed steady state | 1.328848 ms/op | 0.096353 ms/op | 13.79× faster |
| Trace admission from graph, 1,600 waypoints | 16.904799 ms | 4.734719 ms | 3.57× faster |
| Trace admission from bytes, 1,600 waypoints | 13.631719 ms | 6.639026 ms | 2.05× faster |
| Trace public fail-closed materialization, 1,600 waypoints | 478.273032 ms | 292.990240 ms | 1.63× faster |
| Trace proof-bound materialization after admission, 1,600 waypoints | not present | 0.505660 ms | new proof-scoped seam |

Every paired row above used the same v3.8.2 benchmark script to drive both
the clean v3.8.1 and v3.8.2 `PYTHONPATH`, and it required exact result roots,
hashes, bytes, or counters to match. `tracemalloc` rows report traced Python
allocations, not process RSS. The Eaglegate rows are repeated steady-state
public-API admission after one expected-result check and two 500-operation
warmups; they do not measure first construction or cold-cache latency. The
Trace public-materializer row is the compatible public-API comparison. The
0.505660 ms v3.8.2 row is a new proof-scoped seam usable only after graph
admission; comparing it with the v3.8.1 public path illustrates removed
validation work, but is not a same-API speedup claim.

## Allocator qualification decision

The experimental 306-process allocator qualifier combined full-TDS 32-byte
`RAW_BINARY` writes with wrapper and raw-C controls, telemetry and thread
cells, unaffected lookup, CPU and RSS recording, and paired baseline/release
runs. It was retired after proving operationally infeasible on the hosted
runner and produced no performance decision. The incomplete run is neither a
pass nor a fail, and v3.8.2 makes no retained allocator-speedup claim.

The native automatic-allocation correction remains covered as a correctness
change. Normal functional and adversarial tests exercise allocation,
collision, deletion, resizing, restoration, exhaustion, concurrency, ABI, and
lifecycle semantics. Sanitizers, supported-platform compatibility matrices,
native and pure distribution builds, and installed-package smoke tests provide
the release coverage for that path.

## Verification

The post-review aggregate suite completed with **1,283 passed and 1 skipped**
with both native extensions active, and **1,230 passed and 49 skipped** after
all generated native modules were removed. The final Driver/Trace/Eaglegate
adversarial matrix added **131 passed**. `scripts/check_release.py`, bytecode
compilation, `git diff --check`, a pure wheel build, and an extracted-wheel
version smoke check also passed. These results qualify the implementation
changes through the normal release gates; they do not create an allocator
performance claim.

The v3.8.2 checkout owns the benchmark scripts. Use each exact same script
against both source trees so the measurement harness itself is held constant:

```bash
BASE=/path/to/clean-v3.8.1
REL=/path/to/v3.8.2
PYTHONPATH="$BASE/src" python "$REL/benchmarks/benchmark_driver_performance_corrections.py" \
  --records 5000 --iterations 11 --label baseline > /tmp/tds-driver-baseline.json
PYTHONPATH="$REL/src" python "$REL/benchmarks/benchmark_driver_performance_corrections.py" \
  --records 5000 --iterations 11 --label release > /tmp/tds-driver-release.json
```

Apply that two-worktree pattern to these entry points:

```bash
CC=gcc STAQTAPP_TDS_BUILD_NATIVE=1 python setup.py build_ext --inplace --force
PYTHONPATH=src python benchmarks/benchmark_csv_generation_performance_corrections.py \
  --rows 20000 --iterations 5 --fs-index-backend python \
  --expected-fs-index-backend python-sharded
PYTHONPATH=src python benchmarks/benchmark_driver_performance_corrections.py \
  --records 5000 --iterations 11
PYTHONPATH=src python benchmarks/benchmark_observation_performance_corrections.py
PYTHONPATH=src python benchmarks/benchmark_persistence_writer_memory.py \
  --payload-mib 64 --repetitions 3 --warmups 1 --fs-index-backend python \
  --expected-fs-index-backend python-sharded
PYTHONPATH=src python benchmarks/benchmark_eaglegate_admission_performance.py
PYTHONPATH=src python benchmarks/benchmark_trace_rank_performance_corrections.py
```

## Deferred design work

The audit also found candidates that cannot be repaired safely as local
micro-optimizations:

- immutable snapshot/proof sharing across recursive CSV storage bridge,
  revalidation, Semantic IR state fingerprints, and handoff orchestration;
- eliminating source-plus-chunk format duplication or changing Generation
  canonical decoding;
- immutable Driver package/snapshot witnesses, signature cache invalidation,
  Registry concurrency, and remaining manager/VM trust-boundary copies;
- Eaglegate qualification-suite proof reuse, redundant lease hashing, off-path
  tuple copies, and outcome-root construction;
- native/Python value-table redesign, diagnostic atomics, snapshot deep-copy
  removal, and persistence representation reuse.

Those items can change TOCTOU, revocation, concurrency, integrity, or public
format behavior. They remain separate decisions and are not silently bundled
into v3.8.2.

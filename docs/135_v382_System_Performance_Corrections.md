# v3.8.2 System Performance Corrections

Status: **NON-RELEASEABLE source candidate**; not a published package.

## Scope and authority

The attached v3.8.1 assessment proved one severe native allocator defect and
kept every other observation as a hypothesis. For this audit branch, the
user's later system-wide request supersedes that allocator-only scope: the
review was widened to Core, persistence and observation, CSV capabilities,
Generation Authority, Driver Foundry/VM/Studio, Trace Rank, and Eaglegate. It
does not supersede or weaken the allocator proof gate. Corrections were
admitted only when they preserved the relevant semantics and were protected by
focused regression sentinels.

Performance evidence remains engineering feedback. It cannot authorize Driver
activation, CSV semantic truth, Generation publication, Eaglegate serving,
canary traffic, promotion, token acceptance, or KV commit.

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

| Workload | v3.8.1 baseline | v3.8.2 candidate | Local result |
|---|---:|---:|---:|
| Raw native automatic inserts, 100,000, one thread, diagnostics off | 26.1628 s | 0.0277 s | 943.6× indication only |
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

Every paired row above used the same candidate benchmark script to drive both
the clean v3.8.1 and candidate `PYTHONPATH`, and it required exact result roots,
hashes, bytes, or counters to match. `tracemalloc` rows report traced Python
allocations, not process RSS. The Eaglegate rows are repeated steady-state
public-API admission after one expected-result check and two 500-operation
warmups; they do not measure first construction or cold-cache latency. The
Trace public-materializer row is the compatible public-API comparison. The
0.505660 ms candidate row is a new proof-scoped seam usable only after graph
admission; comparing it with the v3.8.1 public path illustrates removed
validation work, but is not a same-API speedup claim.

The allocator row is weaker evidence: its baseline was one causal sample while
the candidate used three samples, and it measures the raw C index rather than
the primary full-TDS 32-byte `RAW_BINARY` write path. Raw JSON records from these exploratory
paired runs were not retained as repository artifacts. Retained raw JSON and a
release-quality allocator result remain pending.

## Non-releaseable allocator proof gate

v3.8.2 must not be tagged or published until all of the following are complete
on clean, isolated baseline and candidate worktrees:

- randomized paired AB/BA process order with the full warmup/repetition policy,
  retained raw JSON, exact source/extension identity, and confidence reporting;
- the full-TDS 32-byte `RAW_BINARY` write path as the primary claim, with the
  `NativeEntryIndexBackend` wrapper and raw C index retained as controls;
- diagnostics/telemetry on and off cells, single-thread and multi-thread cells,
  and the declared entry-count matrix;
- unaffected lookup correctness and lookup-latency checks after insertion, not
  insertion throughput alone;
- recorded CPU identity/configuration, process CPU time, and peak RSS in
  addition to wall time and Python-only traced allocation; and
- repeat execution in release CI on the supported native platforms, followed
  by the complete package release gate.

Until that evidence is retained and green, the candidate is
**NON-RELEASEABLE**, regardless of the large raw allocator indication.

## Verification

The post-review aggregate suite completed with **1,283 passed and 1 skipped**
with both native extensions active, and **1,230 passed and 49 skipped** after
all generated native modules were removed. The final Driver/Trace/Eaglegate
adversarial matrix added **131 passed**. `scripts/check_release.py`, bytecode
compilation, `git diff --check`, a pure wheel build, and an extracted-wheel
version smoke check also passed. These results qualify the implementation
changes locally; they do not satisfy the separate allocator evidence gate or
make this candidate releaseable.

The candidate checkout owns the benchmark scripts. Use each exact same script
against both source trees so the measurement harness itself is held constant:

```bash
BASE=/path/to/clean-v3.8.1
CAND=/path/to/v3.8.2-candidate
PYTHONPATH="$BASE/src" python "$CAND/benchmarks/benchmark_driver_performance_corrections.py" \
  --records 5000 --iterations 11 --label baseline > /tmp/tds-driver-baseline.json
PYTHONPATH="$CAND/src" python "$CAND/benchmarks/benchmark_driver_performance_corrections.py" \
  --records 5000 --iterations 11 --label candidate > /tmp/tds-driver-candidate.json
```

Apply that two-worktree pattern to these entry points:

```bash
CC=gcc STAQTAPP_TDS_BUILD_NATIVE=1 python setup.py build_ext --inplace --force
CC=gcc PYTHONPATH=src python benchmarks/benchmark_native_handle_allocator.py \
  --entries 10000 50000 100000 --threads 1 --warmups 2 --repetitions 7 \
  --wrapper --diagnostics normal
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

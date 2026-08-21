# TDS Performance Benchmarks

These benchmarks exist to find scaling defects and measure corrections without
changing semantics. They are not release gates and they do not authorize
storage, semantic, Driver, or Eaglegate behavior.

## Measurement rule

A reported comparison must use:

- the same benchmark script for baseline and candidate;
- the same interpreter, compiler, dependencies, fixture, and command options;
- warmup and repetition counts stated by the benchmark;
- exact equality of the relevant bytes, roots, hashes, counters, or result
  records; and
- elapsed-time or memory statistics identified precisely.

`tracemalloc` reports traced Python allocation, not process RSS. A local result
is evidence for that workload and machine, not a universal hardware claim.

## Current paired measurements

The current measurements compare clean v3.8.1 and v3.8.2 source trees on Linux
x86-64 with CPython 3.12.13 and GCC `-O3`.

| Workload | Baseline | v3.8.2 | Result |
|---|---:|---:|---:|
| Telemetry `record_read`, 200,000 calls | 0.563514 s | 0.128770 s | 4.38× faster |
| Persistence writer, 64 MiB raw payload, median traced peak | 67,129,697 B | 1,064,702 B | 63.05× lower |
| Persistence writer, same workload, median elapsed | 385.290 ms | 350.673 ms | 8.98% faster |
| Engineering snapshot, 1,000 directories | 22.872960 ms | 9.463020 ms | 2.42× faster |
| JSON canonical dump | 11.454165 us/op | 2.777573 us/op | 4.12× faster |
| JSON fast load | 9.192910 us/op | 1.876761 us/op | 4.90× faster |
| CSV scan plus row anchors, 20,001 logical rows | 264.148198 ms | 83.734179 ms | 3.15× faster |
| CSV row-offset pack, median traced peak | 2,753,576 B | 320,463 B | 88.36% lower |
| Eight root reads, 4,096-payload manifest | 310.724119 ms | 0.006660 ms | about 46,655× faster |
| Direct Driver VM, 5,000 records | 158.020 ms | 104.740 ms | 33.72% faster |
| Managed Driver VM, 5,000 records | 306.791 ms | 220.813 ms | 28.02% faster |
| Studio review actions | 13.848 ms | 3.682 ms | 73.41% faster |
| Eaglegate admission, 1/3/128 plans | — | — | 13.79×–14.45× faster |
| Trace graph/byte admission | — | — | 3.57× / 2.05× faster |
| Trace public materialization | 478.273032 ms | 292.990240 ms | 1.63× faster |

The Generation root-access result measures repeated reads of an already
admitted immutable manifest. The Eaglegate result measures warmed public API
admission, not first construction. Trace proof-bound materialization is a new
post-admission seam and must not be represented as a same-API baseline speedup.

No allocator throughput claim is retained. Allocator behavior remains a
correctness and lifecycle concern unless a bounded, reproducible benchmark
produces a complete comparison.

## Compare two source trees

Use the candidate benchmark script against both source trees so the harness is
held constant:

```bash
BASE=/path/to/baseline
CANDIDATE=/path/to/candidate

PYTHONPATH="$BASE/src" \
  python "$CANDIDATE/benchmarks/benchmark_driver_performance_corrections.py" \
  --records 5000 --iterations 11 --label baseline

PYTHONPATH="$CANDIDATE/src" \
  python "$CANDIDATE/benchmarks/benchmark_driver_performance_corrections.py" \
  --records 5000 --iterations 11 --label candidate
```

Apply the same pattern to:

```text
benchmark_csv_generation_performance_corrections.py
benchmark_driver_performance_corrections.py
benchmark_eaglegate_admission_performance.py
benchmark_observation_performance_corrections.py
benchmark_persistence_writer_memory.py
benchmark_trace_rank_performance_corrections.py
benchmark_native_handle_allocator.py
```

Build optional native modules from a clean tree before native measurements:

```bash
STAQTAPP_TDS_BUILD_NATIVE=1 python setup.py build_ext --inplace --force
```

## Interpreting results

Keep a correction only when profiling identifies repeated work or a scaling
failure, the changed path preserves its public contract, and focused regression
tests cover that contract. Representation changes, cache invalidation,
concurrency, revocation, integrity, and trust-boundary changes require separate
design work rather than a benchmark-driven shortcut.

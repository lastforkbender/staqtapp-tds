# v3.6.0 native AArch64 hardening

## Scope

This is the seventh bounded Native Correctness tranche in the Foundation Repair
train. The preceding architecture-parity tranche proved that the covered native
contracts have one exact semantic meaning on x86-64 and AArch64. This tranche
goes deeper on native ARM execution: repeated deterministic operation, sanitizer
coverage, concurrent immutable reads, malformed-format rejection, and hosted
four-core scaling evidence.

It remains before atomic dataset generations, packed waypoints, deterministic
shortest-path planning, sentinel processes, random forests, neural specialists,
learned serving, cache writes, dataset writes, training, promotion, or activation.

## Native ARM target

The qualification workflow runs on GitHub's native:

```text
runner:       ubuntu-24.04-arm
architecture: aarch64
word size:    64-bit
byte order:   little-endian
```

Runner image, processor, Python, compiler, and source commit are preserved in the
artifacts. Those machine facts do not become semantic or release authority.

## Hardening lanes

### Deterministic native soak

`tools/aarch64_hardening_v360.py` directly loads `_native_index` and
`_csv_scan_kernel`, without importing the application, GUI, or scientific
package surface. It binds and repeatedly exercises:

- CRC32 IEEE and historical FNV-1a scalar/batch equality;
- strict RFC 3629 UTF-8 boundaries and malformed-sequence rejection;
- CSV row, quote, newline, span, and chunk-shape semantics;
- immutable frozen-index construction and source-snapshot independence;
- canonical little-endian packed offsets and signed-handle result bytes;
- four concurrent readers with independently owned output buffers; and
- controlled manual diagnostic publication and sampling evidence.

The ordinary ARM lane uses 256 repeated semantic rounds, 8,192 frozen keys,
four readers, and 128 complete packed batches per reader. The tool emits a
domain-separated canonical semantic root and excludes timing, paths, process-local
namespace IDs, process-local snapshot IDs, and timestamps from that root.

### Address and undefined-behavior sanitizers

The two native extensions are independently rebuilt on ARM with strict C11
warnings and either AddressSanitizer or UndefinedBehaviorSanitizer. Each lane
runs a bounded direct-extension soak across checksum, UTF-8, CSV, packed index,
concurrency, and diagnostic surfaces.

A sanitizer fault is a release blocker. It is not normalized into a skip or a
passing result.

### ThreadSanitizer

The immutable frozen-index path is built with ThreadSanitizer on native ARM and
executed through the direct extension-only concurrency harness. This keeps the
proof focused on the C table and caller-owned packed buffers rather than
unrelated Python packages.

If the ARM toolchain cannot support the lane, that limitation must remain
explicit evidence and be resolved or formally excluded under the platform
policy. The workflow does not silently mark an unsupported sanitizer as success.

### Deterministic format fuzz

`tools/aarch64_fuzz_v360.py` replays 10,000 seeded cases over:

- valid and malformed packed offset vectors;
- fail-before-output-mutation behavior;
- checksum scalar/batch parity;
- valid Unicode scalar combinations and strict chunk boundaries;
- malformed UTF-8 classes; and
- CSV quote, embedded-newline, CRLF, UTF-8, and chunk metadata variants.

The seed, case count, result digests, architecture, source commit, and authority
flags are archived.

### Historical hosted ARM scaling evidence

For the original v3.6.0 qualification,
`tools/aarch64_benchmark_v360.py` recorded one-, two-, and four-worker packed
lookup distributions on the native four-core ARM runner. It required aggregate
no-regression relative to one worker, but was intentionally labeled:

```text
shared-runner-no-regression
named_reference_cpu_claim = false
```

The final Phase-2 scaling claim still requires a separately identified reference
CPU, pinned workload and artifact roots, repeated samples, variance, and a
confidence interval. Hosted-runner evidence may reject a regression; it cannot
establish the final performance claim or authorize release.

Beginning with v3.8.2, this helper remains available for optional engineering
investigation but is retired from recurring pull-request, `main`, and release
CI. No timing or scaling threshold is part of the current ARM aggregate.

## Aggregate gate

The recurring ARM hardening aggregate succeeds only when all four non-timing
lanes succeed:

```text
native deterministic soak
AddressSanitizer + UndefinedBehaviorSanitizer
ThreadSanitizer
10,000-case deterministic fuzz
```

Every output declares:

```text
functional_authority = false
activation_authority = false
```

No report can activate a package, publish a generation, approve semantics,
change policy, authorize storage, or enable learned Trace Ranking.

## Failure and evidence policy

Failures are preserved at the earliest invalid stage. A corrected candidate
receives new source and evidence identities; a passing rerun does not overwrite
an earlier failure. ARM mismatch, sanitizer fault, malformed-format acceptance,
caller-output mutation, semantic drift, or concurrency fault blocks the
recurring hardening workflow.

## Release posture

This report was produced while the repository still used the historical
`3.5.3.post2` identity. The required correctness, lifecycle, architecture, ARM,
and release gates are reconciled by `docs/129_v360_Foundation_Closure.md`; the
Foundation source identity is `3.6.0`. Corrections advance the patch number and
do not create another `.postN` release.

## First qualified native ARM result

The initial complete five-lane hardening run was GitHub Actions run `30662625269` on
merge candidate `1ac010b18e0a33a15454f8c97731b391c3313efb`. Every ARM lane
passed. The official deterministic soak profile is now pinned to:

```text
semantic root:
9ed03c78b6a99e1229808c764bee6bb0770aeb00c3905f40614665411006270a

loops:       256
keys:        8192
workers:     4
iterations:  128 per worker
```

The hosted four-core Neoverse-N2 evidence recorded a one-worker p50 of
44.869 million lookups/second, two-worker aggregate p50 of 84.761 million
lookups/second, and four-worker aggregate p50 of 161.860 million
lookups/second. That corresponds to 1.8891x two-worker scaling and 3.6074x
four-worker scaling, with 94.45% and 90.19% aggregate efficiency. This remains
shared-runner evidence, not the final named-reference-CPU claim.

The 10,000-case deterministic fuzz lane rejected all 10,000 malformed packed
requests before output mutation and all 10,000 malformed UTF-8 fixtures.
AddressSanitizer, UndefinedBehaviorSanitizer, ThreadSanitizer, the ARM
subinterpreter rejection harness, and the historical five-lane aggregate ARM
hardening gate all passed.

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

### Hosted ARM scaling evidence

`tools/aarch64_benchmark_v360.py` records one-, two-, and four-worker packed
lookup distributions on the native four-core ARM runner. It requires aggregate
no-regression relative to one worker, but this is intentionally labeled:

```text
shared-runner-no-regression
named_reference_cpu_claim = false
```

The final Phase-2 scaling claim still requires a separately identified reference
CPU, pinned workload and artifact roots, repeated samples, variance, and a
confidence interval. Hosted-runner evidence may reject a regression; it cannot
establish the final performance claim or authorize release.

## Aggregate gate

The ARM hardening aggregate succeeds only when all five lanes succeed:

```text
native deterministic soak
AddressSanitizer + UndefinedBehaviorSanitizer
ThreadSanitizer
10,000-case deterministic fuzz
one/two/four-worker performance evidence
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
caller-output mutation, semantic drift, concurrency fault, or aggregate scaling
regression blocks this tranche.

## Release posture

The repository package remains the historical `3.5.3.post2` identity during
Foundation development. A completed Foundation Repair becomes `3.6.0` only after
all required Phase-2 gates qualify. Corrections advance the patch number and do
not create another `.postN` release.

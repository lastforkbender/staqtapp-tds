# v3.7.0 Atomic CSV Generation Plane contract

## Status

This is the contract-first opening of Phase 3 in the Frontier Evidence Fabric
release train. It is stacked on the v3.6 native correctness repair candidate and
must not be merged ahead of that dependency.

The intended future public release identity is **3.7.0**. No `.postN` identity
is permitted. This branch does not change `staqtapp_tds.__version__`, publish a
package, activate a generation, or enable learned ranking.

## Why this phase precedes ranking

A learned route must never observe a mixture of old and new CSV evidence. The
unit admitted to validation, graph construction, ranking, replay, and rollback
is one complete immutable dataset generation—not a collection of mutable keys
that happen to share a CSV identifier.

```text
original caller bytes
        |
        v
bounded stateful stream parser
        |
        +-- exact chunk bytes
        +-- packed byte/row offsets
        +-- row anchors
        +-- dialect and parser evidence
        +-- closure DAG
        |
        v
sealed immutable generation
        |
        v
atomic current-generation publication
        |
        +-- old complete generation, or
        +-- new complete generation
        |
        v
read lease pinned to one generation root
```

No ranker, sentinel, Browser, Studio, trainer, or frontier model participates in
construction or publication.

## Contract identity

The machine-readable contract identifier is:

```text
tds-csv-generation-v1
```

The generation identity binds, at minimum:

- dataset identifier;
- exact authoritative source-byte SHA-256;
- ordered immutable chunk identities and byte spans;
- parser contract and dialect identity;
- packed row-offset identity;
- row-anchor identity;
- closure-DAG identity;
- checksum algorithm identity;
- manifest-format version;
- complete generation root; and
- optional parent generation root.

Timestamps, host paths, temporary directory names, process identifiers, and
random staging names do not enter semantic identity.

## Source truth

1. Original bytes are authoritative.
2. Decoded text, normalized rows, typed columns, Semantic IR candidates, and
   model-ready features are derived artifacts.
3. A generation can be reconstructed to the exact original byte sequence.
4. UTF-8 or another declared decoder may carry state across chunk boundaries;
   chunks are never independently decoded under a false boundary assumption.
5. A parser or decoder error identifies the exact byte position and fails the
   candidate generation without altering the current generation.

## True streaming contract

The producer accepts a sequence of caller-owned byte blocks and maintains one
bounded parser state across every real split.

A conforming implementation must prove that:

- every input byte is consumed exactly once;
- no chunk is represented merely by shape metadata over one monolithic buffer;
- quoted fields, escapes, CRLF, lone CR, LF, BOM, and decoder carry state survive
  every legal split;
- row offsets are monotonic and remain within the authoritative byte extent;
- the final parser state is sealed explicitly;
- unfinished quoted or decoder state fails closed; and
- empty input has one canonical representation.

The native implementation will expose an init/feed/finalize surface with
caller-owned bounded output pages. It may not allocate an unbounded object graph
or call Python once per byte, row, or field.

## Immutable artifact layout

The first implementation uses a content-addressed generation directory:

```text
generations/
  <generation-root>/
    manifest.json
    source/
      <ordered immutable chunk objects>
    packed/
      row_offsets.bin
      row_anchors.bin
    closure/
      nodes.bin
      edges.bin
      root.json
CURRENT
```

The exact physical layout may later be packed into `.tds` segments without
changing the logical contract. Readers use identities and bounded records, not
host-path discovery.

## Packed formats

- Byte and row offsets use canonical little-endian unsigned 64-bit values.
- Counts use canonical little-endian unsigned 32-bit or 64-bit values as fixed by
  the format header.
- Every packed object declares magic, major/minor format version, element size,
  element count, logical byte extent, checksum algorithm, and content root.
- Reserved bytes are zero.
- Noncanonical ordering, overlap, overflow, unreachable records, trailing data,
  or unknown required flags are hard failures.
- Readers validate all arithmetic before mapping or indexing an object.

## Row anchors

A row anchor binds:

- generation root;
- exact start and end byte offsets;
- row ordinal;
- exact row-byte hash;
- parser/dialect contract root; and
- source chunk-span identity.

Anchors do not infer semantic meaning. Header interpretation, field typing,
privacy, license, provenance, and Semantic IR remain separately declared and
reviewed.

## Closure DAG

The generation closure records the finite set of immutable objects required to
validate and read that generation. It is evaluated once when the generation is
sealed and incrementally by changed-node identity for later generations.

Required properties:

- canonical topological order;
- no cycles;
- no dangling references;
- no duplicate logical node identity with conflicting content;
- one rooted complete closure;
- exact changed-node accounting; and
- no request-path raw scan or full closure rebuild after admission.

## Publication protocol

The deterministic publisher alone may transition a candidate through:

```text
STAGING -> SEALED -> VERIFIED -> PUBLISHED
```

Publication requires:

1. every immutable object is durably written;
2. every object hash and packed-format invariant verifies;
3. exact source-byte reconstruction verifies;
4. closure is complete and rooted;
5. the manifest is canonical and immutable;
6. the current pointer is replaced atomically; and
7. the previous complete generation remains available for rollback while pinned.

A crash at any injected boundary exposes either the prior complete generation or
the new complete generation. It may not expose a partial manifest, mixed chunk
set, unverified closure, or half-updated current pointer.

## Read leases

A read lease pins one generation root and the complete compatible generation
identity for its lifetime. It never follows `CURRENT` after acquisition.

A request that attempts to combine source, offsets, anchors, closure, features,
or graph inputs from different roots fails with a stable generation-mismatch
fault before ranking or materialization.

## Authority boundary

The generation plane may:

- stage immutable source and derived mechanical evidence;
- validate exact formats and identities;
- publish an already verified complete generation; and
- pin, retire, roll back, and garbage-collect unreferenced immutable objects
  under deterministic policy.

It may not:

- infer or commit semantics;
- weaken privacy, license, provenance, or safety policy;
- train or activate a model;
- rank traces;
- accept a learned write plan directly;
- permit Browser or Studio mutation; or
- replace the current generation on validation failure.

## Required fixtures

The Phase-3 test matrix includes:

- empty input;
- one byte and one row;
- every legal split position for quoted, escaped, CRLF, UTF-8, and BOM fixtures;
- very small and maximum qualified chunk pages;
- malformed decoder state;
- unterminated quote;
- duplicate and conflicting chunk identity;
- offset overflow, overlap, reversal, and one-past-end;
- anchor source mismatch;
- closure cycle and dangling edge;
- corrupted object and manifest hash;
- current-pointer tear before, during, and after replacement;
- process death at every publication boundary;
- concurrent old-generation readers during new publication;
- rollback with pinned readers;
- deterministic rebuild on x86-64 and AArch64; and
- exact source-byte round trip.

## CI lanes

| Lane | Release gate |
|---|---|
| Contract | Immutable identities, stable faults, authority boundary, and format versions pass. |
| Stream oracle | Every split produces the same exact bytes, offsets, anchors, and final parser state as the reference parser. |
| Native parity | C init/feed/finalize output is bit-identical to the reference contract. |
| Packed format | Canonical encoding round-trips; malformed and noncanonical objects fail closed. |
| Publication | Crash injection exposes only old or new complete generation. |
| Concurrency | Read leases remain stable across publication, rollback, retirement, and process restart. |
| Closure | One accepted generation proof replaces repeated request-path scans and validations. |
| Sanitizers | ASan, UBSan, TSan, leak, and long-duration soak lanes pass where supported. |
| Fuzz | Parser state, chunk boundaries, encoding, manifests, packed objects, closure, and publication points are fuzzed. |
| Architecture | Byte-identical generation roots and packed artifacts match across supported architectures. |
| Performance | Named-hardware scan/anchor regression is no worse than the locked native baseline by the approved tolerance. |
| Evidence | Source, build, parser, object, closure, test, policy, and review roots are independently verifiable. |
| Rollback | The previous generation and deterministic compatibility reader remain executable. |

Performance evidence remains separate from functional truth and cannot authorize
publication.

## Exit gate

Phase 3 is complete only when:

1. authoritative original bytes round-trip exactly;
2. the stateful native stream parser matches the reference at every real split;
3. packed offsets, anchors, and closure are canonical and bounded;
4. publication is atomic under exhaustive crash injection;
5. readers pin one immutable generation under concurrency and restart;
6. no request-path raw scan or full closure rebuild is required after admission;
7. existing TDS behavior and deterministic compatibility routes remain intact;
8. all mandatory source, platform, native, sanitizer, fuzz, and architecture lanes
   pass; and
9. the learned Trace Ranking layer is still disabled.

Only after this gate may the release train proceed to the packed server-local
waypoint graph and deterministic shortest-path oracle.
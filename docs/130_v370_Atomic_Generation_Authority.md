# v3.7.0 Atomic Generation Authority

## Status

This is the clean convergence implementation of Phase 2 from the TDS
Canonical Foundation Convergence plan. It is constructed on the current
hardened repository line and does not import stale native-repair transfer
artifacts, one-shot materializers, obsolete native workflows, generated status
files, or old copies of already-merged native code.

The intended future public release identity is **3.7.0**. Until this branch is
reviewed, merged, tagged, and published, the README must distinguish public
release status from source-candidate status.

## Governing invariant

One complete immutable generation is the unit of:

- identity;
- validation;
- publication;
- reader pinning;
- recovery;
- rollback; and
- retirement.

A consumer must see either the previous complete generation or the next
complete generation. It may never observe a partial generation or a mixture of
payloads from different generation roots.

```text
caller-owned exact bytes
        |
        v
immutable content-addressed payloads
        |
        v
canonical manifest + qualification roots
        |
        v
STAGING -> SEALED -> VERIFIED -> PUBLISHED
        |
        v
append-only publication record
        |
        v
CURRENT compare-and-swap
        |
        +-- pinned old generation, or
        +-- pinned new generation
```

## Generic primitive

The implementation lives in:

```text
staqtapp_tds.generation.generation_contract
staqtapp_tds.generation.generation_store
```

It is deliberately not limited to CSV. CSV source generations are the first
full qualification fixture, but the same mechanism is intended to hold:

- CSV source generations;
- parsed and derived generations;
- Eaglegate policy epochs;
- exactness qualification artifacts;
- adapter-conformance artifacts;
- runtime capability snapshots;
- promotion and rollback history; and
- Browser-readable observer snapshots.

Each consumer retains its own semantic contract. The Generation Authority
provides immutable identity and publication only.

## Identity model

A `GenerationManifest` binds:

- one canonical namespace;
- an optional parent generation root;
- ordered immutable payload identities;
- exact payload sizes and SHA-256 roots;
- at most one authoritative source payload;
- ordered qualification roots;
- bounded non-secret metadata;
- qualified resource limits;
- exact contract and format identities; and
- one domain-separated manifest and generation root.

Timestamps, process identifiers, host paths, temporary names, random staging
names, and observer timing do not enter generation identity.

## Physical reference layout

```text
<root>/
  objects/
    <sha256-hex>
  generations/
    <generation-sha256-hex>/
      manifest.json
      receipts/
        000-staging.json
        001-sealed.json
        002-verified.json
        003-published.json
        004-retired.json        # optional append-only terminal receipt
  namespaces/
    <sha256(namespace)>/
      publication.jsonl
      CURRENT
      LOCK                      # bounded publication lock, never durable truth
  .staging/
```

Payload objects and generation directories are immutable once published.
`publication.jsonl` is append-only. `CURRENT` is a recoverable cache of the
last valid publication record rather than an independent source of truth.

## Publication protocol

`AtomicGenerationStore.publish()` performs:

1. candidate and resource-bound validation;
2. content-addressed payload writes;
3. file `fsync`;
4. parent-directory `fsync` where supported;
5. canonical manifest and lifecycle receipt construction;
6. exact payload and receipt verification;
7. atomic generation-directory publication;
8. namespace lock acquisition;
9. current-head compare-and-swap validation;
10. append-only publication-record write and `fsync`;
11. atomic `CURRENT` replacement; and
12. recoverable completion.

The candidate parent root must equal the current root. Two publishers using the
same expected current root cannot silently overwrite one another.

## Failure boundaries

The reference store exposes deterministic failure injection at:

```text
before_temporary_write
during_payload_write
after_payload_write
before_file_fsync
after_file_fsync
before_directory_fsync
before_manifest_publication
after_manifest_publication
before_current_head_cas
after_current_head_cas
during_recovery
```

The qualification matrix requires every boundary to leave either no current
generation, the previous complete generation, or the new complete generation.
No boundary may expose a partial current generation.

## Recovery

Recovery:

- validates the append-only publication chain;
- validates every referenced manifest, lifecycle receipt, and payload;
- ignores only a torn final JSONL record;
- rejects a complete invalid record;
- repairs malformed or stale `CURRENT`;
- is deterministic and idempotent; and
- never changes semantic, ranking, model, policy, or activation state.

A publication record committed before a crash can be replayed into `CURRENT`
only after its complete generation verifies.

## Reader pinning

A `GenerationLease` pins one root for its lifetime and never follows `CURRENT`.
Readers pinned to generation N remain stable while N+1 publishes. A restarted
process may explicitly pin an older complete generation by root while its
immutable objects remain retained.

A current or pinned generation cannot be retired.

## Rollback and retirement

Rollback is another append-only publication record with exact expected-current
compare-and-swap. It does not mutate either generation.

Retirement appends the terminal `RETIRED` lifecycle receipt. It grants no
deletion authority by itself. Destructive garbage collection remains a later,
separately qualified policy.

## Authority boundary

The Generation Authority may:

- persist immutable mechanical payloads;
- verify exact identities and resource bounds;
- publish a complete verified generation;
- append publication and lifecycle receipts;
- pin readers;
- recover `CURRENT`;
- roll back to another retained complete generation; and
- record retirement.

It may not:

- infer or commit semantics;
- rank traces;
- train or activate a model;
- weaken privacy, license, provenance, or safety policy;
- accept learned writes directly;
- grant Eaglegate token or KV authority;
- grant Browser publication authority; or
- grant Studio publication authority.

## Qualification included in this tranche

The focused tests prove:

- deterministic domain-separated identity;
- immutable canonical manifests;
- exact lifecycle adjacency;
- append-only publication chaining;
- one-over resource rejection;
- mixed-generation rejection;
- non-widenable authority;
- exact authoritative-byte round trip;
- all declared crash boundaries;
- current-generation completeness;
- current-head compare-and-swap;
- concurrent publisher conflict;
- stable pinned readers;
- restart access to retained generations;
- payload and manifest corruption rejection;
- torn-current repair;
- torn-log-tail recovery;
- complete invalid-log rejection;
- deterministic idempotent recovery;
- rollback;
- retirement restrictions;
- namespace isolation; and
- verified-generation listing.

## Deliberately absent

This tranche adds no:

- native init/feed/finalize CSV parser;
- closure DAG or packed row-anchor implementation;
- graph planner or Dijkstra path oracle;
- learned ranker or sentinel;
- random forest;
- C-driven agent pool;
- Eaglegate execution;
- model, semantic, policy, release, or activation authority;
- automatic destructive garbage collection; or
- performance/speedup claim.

## Merge posture

The new convergence review supersedes the old divergent Atomic CSV contract
review. It must contain the generic contract, reference store, focused tests,
this architecture record, and one dedicated qualification workflow together.

A `3.7.0` release claim is permitted only after the exact merged source passes
the complete repository release matrix and a tag-bound distribution
qualification. Until then it remains a source candidate.

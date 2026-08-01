# v3.7 Atomic Generation convergence

## Status

This branch is the clean v3.7 convergence line created directly from canonical
`main`. It ports the qualified atomic CSV generation contract and deterministic
reference store without carrying the stale v3.6 repair ancestry, temporary patch
transfer files, or obsolete materialization workflows from the earlier branch.

The public package remains `3.5.3.post2` until the v3.6 Foundation Closure and
v3.7 release trains complete their exact merge, tag, and publication gates. This
branch does not claim a published `3.7.0` release.

## What is implemented

The v3.7 source now contains three layers:

```text
immutable generation contract
        ↓
deterministic reference store
        ↓
durable multi-process publication controller
```

### Immutable contract

`staqtapp_tds.csv_layer.generation_contract` binds:

- authoritative original source bytes;
- exact ordered content-addressed chunks and byte spans;
- parser and dialect identities;
- packed row-offset and row-anchor identities;
- one rooted finite closure;
- qualified mechanical limits;
- optional parent generation identity;
- canonical manifest and generation roots;
- append-only lifecycle receipts; and
- a non-widenable mechanical authority declaration.

The lifecycle is:

```text
STAGING -> SEALED -> VERIFIED -> PUBLISHED -> RETIRED
```

A receipt is evidence. It does not by itself make a generation active.

### Deterministic reference store

`staqtapp_tds.csv_layer.generation_store.AtomicCSVGenerationStore` provides:

- real stateful streaming across caller byte-block boundaries;
- exact reconstruction of original bytes;
- canonical little-endian packed row offsets and anchors;
- row hashes bound to exact source spans;
- content-addressed immutable objects;
- closure verification;
- atomic `CURRENT` replacement;
- generation-pinned read leases; and
- crash-injection qualification over the publication path.

The reference store remains the semantic oracle for a later native
init/feed/finalize implementation. Native code may replace the oracle only after
bit-identical output and failure behavior qualify.

### Durable publication controller

`staqtapp_tds.csv_layer.generation_runtime.DurableAtomicCSVGenerationStore`
adds the cross-process controller boundary:

- one advisory publication lock with POSIX and Windows implementations;
- compare-and-swap checked while that process lock is held;
- a durable publication intent before `CURRENT` changes;
- a published receipt that is not activation authority by itself;
- an atomic current pointer as the only active-generation selector;
- an append-only publication commit after pointer replacement;
- recovery that completes an interrupted commit when `CURRENT` already changed;
- recovery that records an abort when an intent never changed `CURRENT`;
- deterministic rollback only to a previously committed generation;
- non-destructive retirement of non-current, unpinned generations; and
- explicit refusal to roll back a retired generation.

No destructive object collection is admitted by this tranche. Retirement marks
lifecycle state but retains bytes and manifests.

## Atomic publication protocol

For a new generation:

```text
verify complete candidate
        ↓
write immutable generation wrapper
        ↓
write STAGING / SEALED / VERIFIED receipts
        ↓
acquire process-local + interprocess publication locks
        ↓
re-read CURRENT and enforce CAS
        ↓
write durable publication intent
        ↓
write PUBLISHED receipt
        ↓
atomically replace CURRENT
        ↓
write durable publication commit
```

Crash behavior is deterministic:

- before `CURRENT` replacement, the old complete generation remains active and
  recovery records the incomplete intent as aborted;
- after `CURRENT` replacement but before the commit record, the new complete
  generation remains active and recovery reconstructs the missing commit; and
- no receipt, Browser page, Studio action, ranker, or model may substitute for
  the exact `CURRENT` pointer.

## Read and rollback behavior

A reader opens one immutable generation lease. That lease never follows
`CURRENT` after acquisition. Publication may advance `CURRENT` while an old
lease continues reading exact old bytes.

Rollback is a separate controller operation. The target must:

- have a complete generation manifest;
- verify successfully;
- have prior committed publication evidence;
- not be retired; and
- pass a fresh compare-and-swap check against the current manifest.

Rollback changes only `CURRENT`; it does not rewrite the generation or its
historical receipts.

## Engineer API

```python
from staqtapp_tds.generation import (
    CSVGenerationLimits,
    DurableAtomicCSVGenerationStore,
)

store = DurableAtomicCSVGenerationStore("./generation-store")
limits = CSVGenerationLimits(
    max_source_bytes=1 << 30,
    max_chunk_bytes=8 << 20,
    max_chunks=4096,
    max_rows=1 << 28,
    max_closure_nodes=1 << 20,
    max_closure_edges=1 << 22,
)

candidate = store.stage(
    "dataset:customers",
    [b"id,name\n", b"1,Ada\n", b"2,Grace\n"],
    chunk_bytes=4 << 20,
    limits=limits,
)

store.publish(candidate, expected_current_manifest_root="")

with store.open_current() as lease:
    source = lease.read_source()
    offsets = lease.row_offsets()
    anchors = lease.row_anchors()
```

Read-only status and deterministic reference qualification are available through:

```bash
staqtapp-tds-generation status --root ./generation-store --verify-current
staqtapp-tds-generation recover --root ./generation-store
staqtapp-tds-generation reference
```

`recover` may append missing commit or abort evidence. It does not select an
unverified generation and does not infer semantics.

## README preservation contract

Both `README.md` and `README_ja.md` receive an additive current-development
status block. The update process records the complete ordered image and Markdown
link target lists before modifying either file.

Qualification rejects any change that:

- removes or changes one of the 19 Browser screenshot targets;
- changes their order;
- removes an existing Markdown link;
- removes the Programmer Core API Guide;
- removes the API Surface Reference;
- removes the programmer API reference, changelog, language, license, or release
  targets; or
- falsely represents v3.7 or Eaglegate as published or active.

## Authority boundary

Atomic Generation may:

- preserve exact source bytes;
- create immutable mechanical evidence;
- validate content and format roots;
- publish a fully verified generation through CAS;
- recover interrupted publication records;
- pin readers;
- roll back to a previously committed generation; and
- retire an inactive, unpinned generation without deleting it.

It may not:

- infer or commit semantic truth;
- rank traces;
- train or activate models;
- accept learned writes;
- weaken privacy, license, provenance, or safety policy;
- permit Browser or Driver Studio publication;
- execute Eaglegate;
- accept speculative tokens; or
- mutate production KV state.

## Qualification gates

The dedicated v3.7 workflow requires:

- Python 3.10 and 3.13 on Linux;
- Python 3.13 on macOS and Windows;
- complete contract and reference-store tests;
- durable publication, recovery, rollback, retirement, and cross-instance CAS
  tests;
- deterministic reference evidence generated twice with byte identity;
- README target-manifest verification;
- package compilation; and
- the ordinary repository release matrix through the draft pull request.

## Deliberately deferred

This tranche does not add:

- native C init/feed/finalize generation construction;
- destructive generation or object garbage collection;
- a packed generic non-CSV generation store;
- distributed consensus or WAN publication;
- learned routing or sentinels;
- random forests or a C-driven agent pool;
- Eaglegate execution;
- production speculative decoding; or
- a `3.7.0` tag or PyPI release.

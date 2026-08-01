# v3.6.0 Foundation Repair contract

## Status

**Closed by the v3.6.0 Foundation Closure contract in `docs/129_v360_Foundation_Closure.md`.**

This is the first implementation contract derived from the **Frontier Evidence
Fabric — Native Trace Ranking Sentinel Redesign** against the immutable
`v3.5.3.post2` / `281cfedf3531beb3c9e2a85330cd2b8210374faa` baseline.

The target release identity is **3.6.0**. No future `.postN` identity is used.
The existing `3.5.3.post2` release remains unchanged and historical.

## Release boundary

v3.6.0 is Wave A foundation repair. It introduces no learned serving, no
sentinel decisions, no graph search, and no learned writes. Its job is to make
later intelligence safe to add.

```text
historical v3.5.3.post2 implementation
        |
        v
v3.6.0: Trace Rank ABI v2 contract + locked baseline
        |
        v
v3.6.0: native correctness repair
        |
        v
v3.7.0: atomic raw-binary CSV generations
```

Wave A spans more than one release: v3.6.0 closes the contract and native-repair
gates; v3.7.0 owns the atomic Dataset Generation Plane. The learned layer stays
disabled until the generation, graph, path-oracle, and process-isolation gates
qualify independently.

## Reconciliation of the earlier DFRNR-1 proposal

| Disposition | Decision |
|---|---|
| KEEP | Deterministic C, fixed-point arithmetic, immutable artifacts, scalar/reference parity, bounded work, stable tie-breaking, evidence roots, fail-closed loading, rollback, and a strong forest baseline. |
| MODIFY | “Multi-agent” becomes isolated Route/Cache/Cost/Integrity roles with one deterministic planner and separate executor/release authority. The model bundle becomes one composite ServingEpoch. Ranking becomes legal-edge shortest-path selection, not an unconstrained scalar scorer. |
| DEFER | Neural specialists, SIMD optimization, site federation, cache-object staging, restricted writes, and network governance. Each returns only after its earlier gates pass. |
| REMOVE | A mandatory neural residual, request-path training, model self-promotion, runtime model graphs, direct learned commits, storage-lock coupling, frontier-logit features, and synchronous telemetry dependencies. |

## Phase-1 implementation surface

The initial source addition is intentionally small:

```text
staqtapp_tds.trace_rank.contract
```

It defines:

- `TRACE_RANK_ABI_VERSION == 2`;
- one request-pinned `ServingEpochIdentity` and mixed-epoch rejection;
- immutable, canonically rooted full-envelope and future vertical-slice limits;
- stable ranked/fallback/abstain outcomes and failure classes;
- a replayable baseline manifest;
- a machine-checkable non-authority declaration; and
- request-shape validation before learned work.

It deliberately does **not** contain:

- graph traversal;
- forest inference;
- cache transition authority;
- storage or semantic mutation;
- training or promotion;
- network I/O;
- Browser/Studio dependencies; or
- request-path telemetry.

## Locked limits

The full ABI v2 envelope follows the proposal's first-release bounds:

| Resource | Hard maximum |
|---|---:|
| Features | 64 |
| Hot-path learned sentinels | 4 |
| Trees per sentinel | 32 |
| Tree depth | 6 |
| Model bytes per sentinel | 256 KiB |
| Complete learned bundle | 2 MiB |
| Candidates | 32 |
| Expanded nodes | 512 |
| Edges | 2,048 |
| Path steps | 16 |
| Alternatives | 4 |
| Request scratch | 64 KiB |
| IPC envelope | exactly 128 bytes |
| Messages per request | 16 |
| Message depth | 8 |

The future v3.9 shadow-only vertical slice narrows this to Route, Cost, and
Integrity; 16 trees of depth 5; 16 candidates; and at most 8 steps. v3.6.0
defines and tests that closed profile but does not execute it.

## Authority contract

The ranker is read-only advice. It cannot be configured to gain any of these
powers:

- storage writes;
- semantic acceptance;
- privacy or license policy changes;
- bundle activation;
- request-path training;
- storage-lock entry; or
- use of frontier-model logits as live ranking authority.

The future process rule remains:

```text
ranker proposes
executor validates
release controller activates
model reasons
```

## Phase-1 exit gate

Phase 1 is complete only when:

1. ABI v2 contract objects are immutable, bounded, and canonically rooted.
2. Empty, malformed, one-over-limit, and mixed-epoch fixtures fail
   deterministically.
3. The deterministic compatibility baseline and objective corpus receive
   immutable roots.
4. Existing TDS behavior remains unchanged.
5. No learned serving path exists.
6. The next published version is `3.6.0`, with corrections using patch bumps
   rather than `.postN` suffixes.

After the v3.6.0 contract and native-repair gates qualified, Wave A may proceed to
the separately versioned v3.7.0 atomic CSV generation work.

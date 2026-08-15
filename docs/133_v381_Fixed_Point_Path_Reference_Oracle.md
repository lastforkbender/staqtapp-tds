# v3.8.1 — Phase 5 Fixed-Point Path Reference Oracle

## Status and claim boundary

Phase 5 supplies a deterministic, bounded, off-path Python reference oracle for
shortest paths over an already-admitted Phase 4 packed waypoint graph. Its
purpose is to fix the path objective, hard exclusions, tie order, receipt
format, and replay behavior before a native implementation is attempted.

This is not a native hot path or production-serving completion. It cannot
execute an edge, mutate source data, publish or promote a ServingEpoch, route a
request, activate a model, or commit output. It is a qualification and replay
surface only.

This reference-only surface is included in the `v3.8.1` package identity. Its
release does not widen the authority boundary described above or authorize a
native serving path, model activation, operation execution, or source mutation.

## Admitted inputs

The oracle accepts only a factory-created `AdmittedPathContext` and an immutable
`TraceRankPathRequest`. Admission binds all of the following:

- canonical packed graph bytes that decode and re-encode exactly;
- exact immutable source bytes and terminal-inclusive row boundaries;
- the ordered dataset Generation set, graph root, feature schema root, server
  namespace root, edge-catalog root, and source-evidence roots;
- every field of one composite `ServingEpochIdentity`;
- a baseline manifest binding the dataset, feature schema, objective contract,
  configuration, deterministic fallback, and implementation identity;
- the Trace Rank authority and limits roots; and
- closed operation, hard-mask, privacy-class, and license-class policy sets
  represented by a qualification root.

For a published CSV Generation, `bind_csv_generation_source` creates the bridge
into the graph ABI. It requires an open pinned lease, retains the exact source
bytes, and converts the CSV row-start vector into the graph's terminal-inclusive
boundary vector. Its bridge root binds the Generation, CSV artifact roots,
namespace, source root, and both row-offset representations.
`admit_csv_packed_graph` requires every bridge lease to remain open while it
serializes and re-admits the graph; a closed bridge fails that factory.

Generic source-evidence, edge-catalog, and controller-qualification roots are
opaque inputs from upstream authorities. Phase 5 binds them but does not
dereference or independently verify them.
Phase 5 does not implement a legal-edge generator, catalog signer, or controller.

## Fixed-point objective and hard exclusions

All path arithmetic is integer fixed point. The effective cost of an admitted
edge is:

```text
subtotal = checked_u64(base_cost + learned_delta)
credited_evidence_gain = min(subtotal, evidence_gain)
effective_cost = subtotal - credited_evidence_gain
```

Path totals use checked `uint64` addition. Overflow fails closed. Although the
Phase 4 wire format has a non-negative `uint32` learned-delta field, this Phase
5 baseline rejects every nonzero learned delta at graph admission. Learned
ranking therefore cannot affect the reference result.

Before search, an edge is excluded when its operation is outside the admitted
closed set, its hard mask is unsatisfied, its destination privacy or license
class is not admitted, or its destination does not strictly increase causal
sequence. Request input cannot self-grant any of those permissions.

## Deterministic bounded search

The reference uses Dijkstra search with a public total order:

1. total effective cost;
2. step count;
3. complete waypoint-index sequence;
4. complete operation sequence; and
5. complete packed edge-index sequence.

The request pins maximum expanded nodes, examined edges, path steps, and total
cost. Each request budget may only narrow the admitted Trace Rank limits. Work
exhaustion returns `ABSTAIN` with `BOUND_EXCEEDED` and no partial path. If the
bounded search completes without a path, the oracle returns a content-free
fallback result; policy exclusions remain visible as counters.

These are logical work bounds, not a memory-layout guarantee. The Python
reference uses normal interpreter objects and a heap. There is no fixed scratch-byte bound.
Nor is there a zero-allocation proof, lock-free proof, syscall-free proof,
latency qualification, or process-isolation boundary.

## Replayable content-free receipt

A ranked receipt binds the request, full ServingEpoch, admitted context, graph,
dataset Generation set, feature schema, server namespace, policy, limits,
baseline manifest, and Trace Rank authority. It records exact waypoint
generation/provenance identities and byte/row spans, packed edge identities,
fixed-point cost components, aggregate totals, work counters, and exclusion
counters.

Canonical JSON bytes and a domain-separated SHA-256 root make the receipt
stable. The strict byte loader rejects noncanonical JSON, unknown or missing
fields, invalid widths, inconsistent totals, and payloads above the fixed
256-KiB receipt bound. Replay then reruns the oracle against the same context
and request and requires byte-for-byte equality. A ranked result therefore
identifies a path; it never performs the path's operations. Sentinel output is
structurally empty in every Phase 5 receipt.

## Qualification evidence

The focused suite covers:

- exact graph, Generation, policy, baseline, and nine-component ServingEpoch
  binding;
- deterministic ties and repeated byte-identical receipts;
- checked overflow, work exhaustion, and hard policy exclusions;
- saturating evidence credit with auditable cost totals;
- tamper detection through exact replay;
- comparison with an independent exhaustive oracle over deterministic random
  acyclic graphs;
- a published CSV Generation pinned through graph admission and path replay;
  and
- absence of storage, execution, training, activation, network, and sentinel
  authority in the reference module.

`.github/workflows/fixed-point-path-reference.yml` runs the Trace Rank ABI, CSV
Generation, packed graph, planner, workflow-contract, and install-contract
tests on Ubuntu with Python 3.10 and 3.13, macOS with Python 3.13, and Windows
with Python 3.13. These lanes establish cross-platform reference behavior; they
do not qualify production latency or a native serving implementation.

## Deliberately absent

- a legal-edge generator, catalog-signing authority, or controller;
- a fixed-dimensional learned forest, model inference, or trainer;
- sentinel generation, isolation, comparison, or feedback;
- a native planner, native executor, operation execution, or production route;
- a fixed scratch-byte contract or zero-allocation/lock/syscall hot-path proof;
- canary, promotion, activation, rollback, or ServingEpoch publication
  authority; and
- any claim that Frontier Fabric or its production-serving path is complete.

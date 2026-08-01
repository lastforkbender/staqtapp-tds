# v3.8 Packed Waypoint and CSR Graph

## Scope

This is Phase 4 of the Frontier Evidence Fabric / Native Trace Ranking design:
a canonical, bounded, source-verifiable packed waypoint graph. It is a data
truth boundary only. It does not run Dijkstra, rank paths, execute operations,
apply a learned model, or grant storage/serving authority.

## Binary ABI

The `tds-packed-waypoint-csr-v1` format binds Trace Rank ABI v2 and uses:

| Property | Fixed value |
|---|---|
| Byte order | Little-endian |
| Header | 256 bytes |
| Integrity | SHA-256 plus CRC32/IEEE-v1 |
| Features | Up to 64 signed Q15 values with a canonical missing mask |
| Generation record | 112 bytes |
| Provenance record | 48 bytes |
| Feature record | 144 bytes |
| Waypoint record | 64 bytes |
| CSR offset | 8 bytes |
| Edge record | 40 bytes |

The header binds every format/algorithm identity, record width, count, section
offset, server namespace, feature schema, hard-mask universe, digest, and
checksum. Identical logical input serializes byte-identically; admitted bytes
decode and re-encode byte-identically.

## Logical records

`Waypoint` binds one server-local causal position to an immutable generation,
exact byte and row spans, predecessor, feature block, and provenance record.
`FeatureBlock` binds fixed-point values, missingness, quantization, and privacy
class. `Edge` binds a permitted operation, destination, deterministic base
cost, signed bounded learned delta, evidence gain, and an immutable hard
eligibility mask. Learned values cannot weaken provenance policy.

The CSR representation consists of generation and provenance tables, feature
pages, `waypoints[]`, monotonic `edge_offsets[]`, and `edges[]`. Local indices
are never authority outside the content-bound graph.

## Admission gates

Before allocating decoded record tuples, the loader validates counts, checked
section arithmetic, total memory, format identities, widths, contiguous layout,
length, SHA-256, and CRC32. It then rejects unresolved references, invalid
causal predecessors, noncanonical ordering, duplicate edges, feature/privacy
mismatch, hard-mask weakening, source/row-span mismatch, reserved fields,
padding, truncation, trailing bytes, and corruption.

`ImmutableSourceBinding` supplies exact source bytes and packed row boundaries.
Every waypoint must materialize to the same authoritative byte span and row
span under the generation/source/offset roots recorded in the graph.

## Deferred work

Fixed-point shortest-path search belongs to the next phase. Learned ranking,
sentinel isolation, model training, composite production epochs, canarying, and
activation are not present here.

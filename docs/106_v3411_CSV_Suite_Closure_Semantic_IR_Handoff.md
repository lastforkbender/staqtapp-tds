# v3.4.11 — CSV Suite Closure / Semantic IR Handoff Contract

TDS v3.4.11 concludes the v3.4.x CSV system line. It does **not** begin formal Semantic IR. Instead, it adds a final read-only admission-readiness contract proving that the complete CSV evidence chain is stable, replayable, bounded, and safe for a later explicit Semantic IR API to consume.

## Complete evidence chain

`prepare_csv_semantic_ir_handoff(...)` validates 19 required evidence lanes:

1. core CSV artifact integrity
2. preserved original-byte identity
3. artifact security envelope
4. storage bridge preflight
5. storage bridge commit proof
6. storage adapter replay proof
7. native storage commit evidence
8. native storage revalidation evidence
9. Interpole timeline
10. determinant vector
11. timeline ring and invertible mirror
12. kernel readiness contract
13. native scan parity
14. native row-anchor parity
15. kernel performance gates
16. Browser monitor snapshot
17. Browser monitor canonical replay
18. frozen Browser display contract
19. packaged SVG icon registry

Every lane contributes a compact source reference and SHA-256 fingerprint. The handoff never copies row or cell payloads into an IR structure.

## Handoff result

A report becomes `ir_handoff_ready` only when:

- all 19 evidence lanes are valid and in the required order;
- artifact, storage, Interpole, kernel, and monitor chains are independently ready;
- the Browser snapshot replays exactly from committed evidence;
- the handoff payload is within its fixed bound;
- the relevant TDS directory state has the same before/after fingerprint;
- no semantic inference or formal IR commitment occurred.

The report marks `semantic_ir_candidate_ready=True`, but also requires `explicit_opt_in_required=True`. Readiness is not permission for automatic interpretation.

## Browser replay closure

The v3.4.10 monitor replay layer had two gaps that were unacceptable at the final CSV boundary:

- a mapping could omit a frozen display-contract key and receive a default during rehydration;
- nested display content could change while list counts remained equal.

v3.4.11 closes both gaps. Validation now checks the original mapping key set, and replay compares every frozen display field, including nested cards, ring nodes, gate rows, signal lanes, and event rows. The canonical display fingerprint is also compared directly.

## Semantic exclusion boundary

The handoff explicitly keeps all of these false:

- semantic reasoning
- semantic conclusions
- schema inference
- type inference
- entity inference
- row identity inference
- cell meaning inference
- formal IR commitment

The future IR layer must enter through a separate, explicit API and reference immutable evidence rather than mutating the CSV artifact family.

## Storage-engine boundary

Handoff preparation calls validation, loading, snapshot, and replay APIs only. It does not call CSV commit APIs. It fingerprints the relevant TDS directory values before and after the full pass and fails closed if any source artifact changes.

The native C storage engine, storage locks, and hot-path control remain outside Semantic IR admission.

## Documentation policy

The main README files and API PDF remain unchanged in v3.4.11. Their update should occur only after the v3.5.x Formal Semantic IR boundary is implemented and stable.

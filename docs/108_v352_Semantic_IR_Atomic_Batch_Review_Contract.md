# TDS v3.5.2 — Semantic IR Atomic Batch Review Contract

TDS v3.5.2 adds a bounded atomic review layer above the v3.5.1 Formal Semantic IR lifecycle ledger. The contract accepts multiple independent transition requests as one ordered review unit while preserving the same read-only, explicit-authorization, deterministic-lineage, and storage-isolation boundaries established by v3.5.0 and v3.5.1.

The batch layer is an envelope above the lifecycle ledger. It does not replace the lifecycle ledger, persist a new semantic artifact, infer semantic meaning, or commit semantic truth.

## Atomic invariant

A batch is accepted only when every transition is independently authorized, collectively conflict-free, bound to one validated candidate and one evidence state, and reproducible as one deterministic lifecycle result.

```text
validated candidate + current CSV evidence + optional source lifecycle
                              |
                              v
                    one batch preflight
                              |
             +----------------+----------------+
             |                                 |
        any failure                       all requests valid
             |                                 |
             v                                 v
 original lifecycle unchanged       one immutable lifecycle result
 zero accepted transitions          ordered receipt + replay proof
```

There is no partial-acceptance mode and no rollback path. TDS does not mutate a lifecycle object during preflight. It constructs the complete result only after all requests pass.

## Public structures

The release introduces:

- `CSVSemanticIRBatchAuthorization`
- `CSVSemanticIRBatchItem`
- `CSVSemanticIRTransitionBatch`
- `CSVSemanticIRBatchReceipt`
- `CSVSemanticIRBatchValidationReport`
- `CSVSemanticIRBatchReplayReport`

The public preparation, validation, replay, fingerprint, and summary functions are:

```python
prepare_csv_semantic_ir_transition_batch(...)
validate_csv_semantic_ir_transition_batch(...)
replay_csv_semantic_ir_transition_batch(...)
csv_semantic_ir_transition_request_fingerprint(...)
csv_semantic_ir_batch_authorization_fingerprint(...)
csv_semantic_ir_transition_batch_fingerprint(...)
csv_semantic_ir_batch_receipt_fingerprint(...)
csv_semantic_ir_transition_batch_summary(...)
csv_semantic_ir_transition_batch_replay_summary(...)
```

## Two authorization levels

Every transition retains its v3.5.1 authorization metadata and target-state scope:

```text
validated -> validate_proposition
contested -> contest_proposition
```

The enclosing batch also requires separate caller-supplied authorization with scope:

```text
review_transition_batch
```

The batch authorization does not replace or weaken per-transition authorization. Both layers are fingerprinted and included in the immutable receipt. TDS validates their shape and scope but does not authenticate actors or resolve external authorization references.

## One-pass source validation

For each batch, TDS performs:

1. one complete candidate validation;
2. one replay against current committed CSV evidence;
3. one source-lifecycle validation when a lifecycle is supplied;
4. one complete preflight of every batch item;
5. one isolated in-memory append simulation after preflight succeeds.

The implementation does not call the public single-transition API repeatedly. This avoids repeated candidate reconstruction, handoff validation, and evidence replay for every item.

## Batch-entry state rule

Every request is evaluated against the lifecycle state that existed when the batch began. v3.5.2 rejects multiple requests for the same proposition in one batch, including apparent chains such as:

```text
proposed -> validated -> contested
```

Those transitions remain valid as two separate lifecycle operations. The first batch contract represents parallel review decisions, not a transaction-program language.

## Deterministic order and lineage

Request order is preserved and fingerprinted. Accepted records are appended in that exact order, producing:

- deterministic sequence numbers;
- one global predecessor chain across the batch;
- unchanged proposition-local predecessor rules;
- deterministic transition fingerprints;
- deterministic resulting lifecycle fingerprint;
- deterministic ordered batch fingerprint;
- deterministic complete receipt fingerprint.

Reordering otherwise identical requests changes the batch and receipt fingerprints and fails serialized validation unless the complete receipt is legitimately rebuilt.

## Fail-closed conflicts

The complete batch is blocked when any of the following is present:

- malformed or missing batch authorization;
- malformed or missing transition authorization;
- duplicate transition IDs in the batch or source history;
- duplicate authorization IDs in the batch or source history;
- multiple requests for one proposition;
- unknown proposition IDs;
- wrong predecessor states;
- forbidden transitions;
- `committed` or `superseded` targets;
- candidate, handoff, raw CSV, or source lifecycle drift;
- transition-count overflow;
- batch or lifecycle payload overflow;
- directory-state mutation;
- nested serialized-field or fingerprint tampering.

A blocked batch contains no accepted transition fingerprints. When a source lifecycle was supplied, the receipt returns that exact lifecycle unchanged. When the batch began directly from the candidate foundation, no lifecycle result is created.

## Bounds

```text
maximum transitions per batch: 32
maximum transitions per lifecycle: 256
batch/receipt payload ceiling: 524,288 bytes
lifecycle payload ceiling: 524,288 bytes
batch authorization reference: 512 characters maximum
per-transition authorization reference: 512 characters maximum
transition reason: 2,048 characters maximum
```

## v3.5.1 lineage compatibility

v3.5.2 accepts compatible v3.5.1 candidate and lifecycle lineage. Current CSV evidence is reconstructed once and compared with a release-neutral candidate projection. Historical candidate, transition, and lifecycle fingerprints are not rewritten. A newly accepted result is stamped with the v3.5.2 release version while retaining the complete historical chain.

Incompatible release versions or any substantive candidate/evidence mismatch fail closed.

## Replay contract

Batch replay:

1. validates the serialized receipt and every nested contract;
2. validates the supplied candidate and optional source lifecycle;
3. reconstructs the batch from current evidence;
4. compares the complete stable receipt projection;
5. compares batch, receipt, and resulting lifecycle fingerprints;
6. proves before/after TDS directory-state identity.

CSV drift, stale handoff evidence, item reordering, authorization tampering, result-lifecycle tampering, missing nested keys, changed atomicity flags, or changed boundary declarations are rejected.

## Storage and semantic boundaries

All of the following remain false:

```text
automatic_lifecycle_transitions
partial_acceptance
semantic_artifact_persisted
formal_ir_committed
semantic_conclusions_committed
committed_state_admitted
superseded_state_admitted
csv_artifact_mutation
retroactive_csv_artifact_mutation
interpole_mutation
native_storage_writes
native_storage_hot_path_touched
native_storage_locks_controlled
native_c_storage_engine_changed
per_row_writes
per_cell_writes
```

The v3.5.2 release contains no native C source changes. Native extensions are built and tested only to prove whole-system compatibility.

## Deferred work

v3.5.2 intentionally does not introduce:

- lifecycle persistence;
- semantic commitment;
- `committed` state admission;
- `superseded` state admission;
- automatic policy transitions;
- automatic conflict resolution;
- batch-local transition programs;
- CSV, Interpole, or native-storage writes.

Persistence and commitment remain separate future design decisions and must not be inferred from batch acceptance.

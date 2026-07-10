# TDS v3.5.1 — Semantic IR Lifecycle Transition Contract

TDS v3.5.1 adds the first explicit lifecycle-transition layer above the v3.5.0 Formal Semantic IR candidate. The transition layer is a separate read-only observer/ledger contract. It does not mutate the source candidate, persist a semantic artifact, infer semantic meaning, or commit semantic truth.

## Admitted transitions

Only the following state changes are admitted:

```text
proposed -> validated
proposed -> contested
validated -> contested
```

The `superseded` and `committed` vocabulary values remain reserved. They are rejected by the v3.5.1 transition API.

## Explicit authorization

Every transition requires caller-supplied authorization metadata:

- authorization ID
- actor ID
- authority scope
- external authorization reference
- `explicit_authorization = true`

The authority scope must match the requested target state:

```text
validated -> validate_proposition
contested -> contest_proposition
```

TDS validates and fingerprints this metadata. It does not authenticate the actor or resolve the external authorization reference; those remain responsibilities of the calling system.

## Candidate and evidence replay

Before accepting any transition, TDS:

1. validates the complete source Semantic IR candidate;
2. replays that candidate against current committed CSV evidence;
3. requires the current v3.4.11 handoff closure to remain valid;
4. verifies that any supplied lifecycle ledger is bound to the same candidate, handoff closure, and raw CSV identity;
5. verifies the requested predecessor state;
6. confirms that the transition is in the narrow admitted transition table.

CSV drift, handoff drift, candidate tampering, lifecycle tampering, unknown proposition IDs, wrong predecessor states, duplicate transition IDs, or malformed authorization fail closed.

## Immutable lineage

Each accepted transition record carries:

- deterministic sequence number;
- transition ID;
- proposition ID;
- predecessor and successor states;
- bounded reason text;
- authorization metadata and authorization fingerprint;
- source candidate fingerprint;
- source declaration fingerprint;
- source evidence-reference fingerprint;
- handoff closure fingerprint;
- global predecessor fingerprint;
- proposition predecessor fingerprint;
- deterministic transition fingerprint.

The lifecycle ledger contains the complete immutable history and a current-state table for every source proposition. A later transition never rewrites a prior record.

## Replay

`replay_csv_semantic_ir_lifecycle(...)` reconstructs the complete ledger from the original source candidate, current committed evidence, and the serialized transition history. It compares the full stable lifecycle projection and fails closed on any mismatch.

## Public API

New module:

```text
staqtapp_tds.csv_layer.semantic_ir_lifecycle
```

Primary dataclasses:

```text
CSVSemanticIRTransitionAuthorization
CSVSemanticIRTransitionRequest
CSVSemanticIRTransitionRecord
CSVSemanticIRLifecycleState
CSVSemanticIRLifecycle
CSVSemanticIRLifecycleValidationReport
CSVSemanticIRLifecycleReplayReport
```

Primary calls:

```text
csv_semantic_ir_transition_authorization_fingerprint(...)
csv_semantic_ir_transition_fingerprint(...)
prepare_csv_semantic_ir_transition(...)
validate_csv_semantic_ir_lifecycle(...)
csv_semantic_ir_lifecycle_fingerprint(...)
replay_csv_semantic_ir_lifecycle(...)
csv_semantic_ir_lifecycle_summary(...)
csv_semantic_ir_lifecycle_replay_summary(...)
```

## Preserved boundaries

All of the following remain false:

```text
automatic_lifecycle_transitions
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

Candidate preparation and lifecycle transition operations remain in memory and read-only with respect to the TDS directory.

## Documentation freeze

The Semantic IR documentation freeze remains active. The following files are unchanged in v3.5.1:

```text
README.md
README_ja.md
tds_api_docs/README.md
tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf
```

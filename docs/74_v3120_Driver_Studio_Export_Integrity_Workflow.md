# v3.1.20 Driver Studio Export Integrity Workflow

v3.1.20 adds a review-safe Export Integrity Workflow above the v3.1.19 Export / Audit Console.

The workflow verifies packet readiness before export/review handoff. It recomputes deterministic manifest and packet hashes, compares optional expected manifest or packet hashes, maps checklist items into checkpoint rows, and emits an intent-only review gate.

## New module

```text
staqtapp_tds.studio_pyqt5.export_integrity_workflow
```

## New models

- `StudioExportIntegrityWorkflow`
- `StudioExportIntegrityWorkflowState`
- `StudioExportIntegrityCheckpoint`
- `StudioExportIntegrityCheckpointStatus`
- `StudioExportIntegrityManifestComparison`
- `StudioExportIntegrityReviewGate`
- `StudioExportIntegrityWorkflowStatus`
- `studio_export_integrity_workflow_capability_matrix()`

## Workflow flow

```text
Export / Audit Console packet preview
  -> manifest hash recompute
  -> packet hash recompute
  -> optional expected manifest/hash comparison
  -> checklist checkpoint progression
  -> review-safe export handoff gate
  -> deterministic workflow hash
```

## Capability

The workflow provides:

- manifest hash recomputation
- packet hash recomputation
- expected manifest hash comparison
- expected packet hash comparison
- expected manifest field comparison
- progressive export checkpoint rows
- review-safe export handoff gate
- deterministic export workflow hash
- bridge/runtime constructors

## Authority boundary

The Export Integrity Workflow is verify-only and intent-only.

It does not:

- approve drivers
- reject drivers
- quarantine drivers
- call Registry approval
- sign drivers
- attach signatures
- activate drivers
- execute trusted drivers
- mutate Registry trust state
- write storage
- store private keys
- bypass Runtime Manager, Foundry, Review Board, or Registry policy

## Relationship to v3.1.19

v3.1.19 prepares hash-backed export/audit packet previews.
v3.1.20 verifies those previews and compares expected integrity inputs before review/export handoff.

Studio remains an evidence, explanation, and interaction surface only. Registry remains the trust authority.

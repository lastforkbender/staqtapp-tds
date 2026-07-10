# v3.3.8 — CSV Storage Adapter Dry-Run / Binding Contract

TDS v3.3.8 adds a read-only storage-adapter binding contract for CSV `.tds` evidence. It consumes an existing committed bridge manifest, revalidates current artifact hashes and payload lanes, and resolves artifacts into deterministic future storage binding records.

The feature is intentionally a dry run. It does not write adapter reports, does not migrate CSV payloads into native storage, and does not touch the native C storage engine.

## Added API

- `CSVStorageAdapterBinding`
- `CSVStorageAdapterBindingReport`
- `prepare_csv_storage_adapter_binding(...)`
- `validate_csv_storage_adapter_binding(...)`
- `csv_storage_adapter_binding_summary(...)`

## Binding statuses

Each binding reports one of these states:

- `ready`: artifact is present, hash-stable, lane-stable, and bindable.
- `missing`: a committed or required artifact is absent or unreadable.
- `drifted`: the current artifact no longer matches the committed hash, payload kind, or provenance lane.
- `optional_missing`: an optional artifact was in the bridge plan but was not committed and remains absent.
- `rejected`: the binding cannot be trusted because the committed plan no longer matches the current bridge plan.

## Boundary

- No native C storage-engine change.
- No native storage writes.
- No CSV payload migration.
- No per-row or per-cell writes.
- No semantic reasoning.
- Normal CSV import shape remains unchanged.

This release creates the adapter-side proof contract needed before a later commit simulation/replay layer or first native storage-backed CSV commit.

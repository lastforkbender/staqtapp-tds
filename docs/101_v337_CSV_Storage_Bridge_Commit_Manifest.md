# v3.3.7 — CSV Storage Bridge Commit Manifest

This release adds an optional derived bridge-commit manifest for CSV `.tds` artifacts. The manifest freezes the storage bridge preflight plan, artifact keys, payload kinds, provenance lanes, and payload SHA-256 values without moving CSV data into a native CSV kernel.

The design intentionally remains above the native storage engine. It provides a durable proof object that a later storage adapter can ingest, and it can be revalidated to detect drift before storage integration proceeds.

## Added API

- `CSVStorageBridgeCommitReport`
- `csv_storage_bridge_commit_report_key(...)`
- `prepare_csv_storage_bridge_commit(...)`
- `commit_csv_storage_bridge_manifest(...)`
- `load_csv_storage_bridge_commit_report(...)`
- `validate_csv_storage_bridge_commit(...)`
- `csv_storage_bridge_commit_summary(...)`

## Boundary

- No native C storage-engine change.
- No CSV payload migration into native storage.
- No per-row or per-cell writes.
- No semantic reasoning.
- Normal CSV import shape remains unchanged.

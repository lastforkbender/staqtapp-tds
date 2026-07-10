# v3.3.6 — CSV Storage Bridge Preflight

TDS v3.3.6 adds a read-only CSV storage-bridge preflight layer. The goal is to
prove the exact artifact plan that later native storage integration must obey
without moving CSV logic into the native storage hot path.

Implemented API surface:

- `CSVStorageBridgeEntry`
- `CSVStorageBridgePreflightReport`
- `csv_storage_bridge_plan(...)`
- `validate_csv_storage_bridge_preflight(...)`
- `csv_storage_bridge_preflight_summary(...)`

The preflight verifies:

- the six required CSV core artifacts
- expected payload lanes (`TEXT_UTF8` for raw CSV, `JSON_UTF8` for derived evidence)
- expected provenance lanes (`REAL` for raw CSV, `DERIVED` for evidence)
- durable entry metadata
- stable payload SHA-256 values
- CSV artifact validation status
- CSV security-envelope status
- optional scan artifact readiness when requested

The pass remains intentionally narrow:

- no native C storage-engine changes
- no storage adapter writes
- no per-row writes
- no per-cell writes
- no semantic reasoning
- no normal CSV import write-shape changes

This prepares the CSV subsystem for a later storage-backed adapter by making the
future bridge contract explicit and testable before native integration begins.

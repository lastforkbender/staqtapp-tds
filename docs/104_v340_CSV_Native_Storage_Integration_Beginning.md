# v3.4.0 CSV Native Storage Integration Beginning

TDS v3.4.0 begins CSV native-storage integration at fixed-artifact granularity.

The adapter requires the prior bridge commit manifest, storage-adapter binding contract, and persisted replay proof before committing any storage-backed CSV artifact entries. The commit writes deterministic storage binding keys for the compact CSV artifact set only. It does not write CSV rows or cells, does not invoke a native CSV kernel, does not change the native C engine, and does not introduce semantic IR behavior.

New API surface:

- `CSVNativeStorageCommitEntry`
- `CSVNativeStorageCommitReport`
- `csv_native_storage_commit_report_key(...)`
- `commit_csv_native_storage_artifacts(...)`
- `load_csv_native_storage_commit_report(...)`
- `validate_csv_native_storage_commit(...)`
- `csv_native_storage_commit_summary(...)`

Validation focus:

- persisted replay proof required
- artifact-level writes only
- deterministic storage binding keys
- payload hash preservation
- payload kind preservation
- optional scan artifacts skipped safely when absent
- source drift rejected before storage writes
- storage drift detected after commit
- no per-row/per-cell storage bloat
- no semantic reasoning

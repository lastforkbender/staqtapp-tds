# v3.3.9 — CSV Storage Adapter Commit Simulation / Replay Proof

TDS v3.3.9 adds a deterministic commit-simulation replay proof for CSV `.tds` evidence. It consumes the v3.3.8 storage-adapter binding contract, orders future adapter operations, and classifies each artifact before any native storage path is touched.

The replay layer intentionally remains above native storage. It does not migrate CSV payloads, does not write per-row or per-cell entries, and does not add semantic interpretation. Its purpose is to prove the sequence that a later native adapter may execute after bridge commit and binding validation are already stable.

Implemented APIs:

- `CSVStorageAdapterReplayStep`
- `CSVStorageAdapterReplayReport`
- `csv_storage_adapter_replay_report_key(...)`
- `prepare_csv_storage_adapter_replay(...)`
- `commit_csv_storage_adapter_replay_report(...)`
- `load_csv_storage_adapter_replay_report(...)`
- `validate_csv_storage_adapter_replay(...)`
- `csv_storage_adapter_replay_summary(...)`

Replay states include `planned`, `staged`, `committed`, `skipped_optional`, `rejected`, `failed_hash_check`, and `failed_binding_validation`. Optional scan artifacts remain nonfatal when included but not required. Required missing artifacts and hash drift are rejected before any simulated payload commit can become valid.

This is the final proof step before the v3.4.x line can begin controlled native storage-backed CSV artifact integration.

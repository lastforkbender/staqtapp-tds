# v3.3.5 — CSV Artifact Transaction / Recovery Envelope

TDS v3.3.5 adds an optional transaction/recovery envelope for CSV `.tds`
artifacts. The CSV layer can now stage the fixed six core import artifacts under
transaction-specific keys, validate the staged set, commit it into the final CSV
namespace, and detect or recover interrupted artifact sets.

This is a storage-readiness pass. It remains above the native storage engine and
preserves the ordinary CSV import write shape.

## Added

- `CSVArtifactTransactionReport`
- `begin_csv_artifact_transaction(...)`
- `validate_csv_artifact_transaction(...)`
- `commit_csv_artifact_transaction(...)`
- `detect_partial_csv_artifacts(...)`
- `recover_csv_artifact_transaction(...)`
- `csv_artifact_transaction_keys(...)`
- `load_csv_artifact_transaction_report(...)`
- `new_csv_transaction_id()`
- `validate_csv_transaction_id(...)`

## Guarantees

- Normal `import_csv_bytes(...)` still writes the same fixed six core artifacts.
- Transaction staging is opt-in.
- Staged artifacts are validated before final commit.
- Partial final artifact sets are detectable.
- A valid staged transaction can recover an empty or partial final set.
- No per-row writes.
- No per-cell writes.
- No semantic reasoning.
- No native storage-engine changes.

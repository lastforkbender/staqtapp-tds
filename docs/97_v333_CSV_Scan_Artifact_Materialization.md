# v3.3.3 — CSV Scan Artifact Materialization

TDS v3.3.3 turns the v3.3.x scan reference layer into optional durable evidence. Before this pass, `scan_csv_bytes(...)` and `scan_csv_row_anchors(...)` produced read-only profiles. This release allows an application to persist those profiles as derived `.tds` JSON artifacts after validation proves the current raw CSV, manifest, and row-offset map agree.

## What changed

- Added `CSVScanArtifactReport` for materialization and validation reports.
- Added `csv_scan_artifact_keys(...)` for optional scan-artifact key names separate from the fixed import artifact set.
- Added `materialize_csv_scan_artifacts(...)` to persist scan profiles and optional row-anchor profiles.
- Added `load_csv_scan_profile(...)`, `load_csv_row_anchor_profile(...)`, and `load_csv_scan_materialization_report(...)`.
- Added `validate_materialized_csv_scan_artifacts(...)` to compare persisted scan evidence against the current durable source.
- Added `from_mapping(...)` loaders for `CSVScanProfile` and `CSVRowAnchorProfile`.
- Added tests for optional scan-only materialization, scan + row-anchor materialization, fixed import write-shape preservation, post-materialization raw drift, and fail-closed pre-write validation.

## Artifact boundary

The new artifacts are intentionally optional and advanced:

```text
core import artifacts
   raw.csv
   manifest.json
   dialect.json
   row_offsets.json
   content_hashes.json
   import_report.json

optional scan artifacts
   scan_profile.json
   row_anchor_profile.json
   scan_materialization_report.json
```

Routine CSV import still writes exactly one raw artifact and five derived JSON artifacts. Scan materialization is explicit and happens only when a caller wants durable scan evidence for later AI, Semantic IR, audit, or storage-integrated workflows.

## Fail-closed rule

`materialize_csv_scan_artifacts(...)` validates durable raw/manifest/row-offset parity before writing scan artifacts. If row offsets drift, the source hash does not match, or row counts disagree, no scan profile or row-anchor profile is written.

```text
read durable raw + manifest + row offsets
   ↓
validate scan parity
   ↓ valid only
write compact derived scan artifact(s)
   ↓
write materialization report
```

## Preserved discipline

- No native C storage-engine changes.
- No CSV intelligence in the storage hot path.
- No README.md or README_ja.md update.
- No API PDF regeneration.
- No change to routine CSV import artifact count.
- No per-row writes.
- No per-cell writes.
- Materialized row anchors remain a single compact derived artifact, not one artifact per logical record.

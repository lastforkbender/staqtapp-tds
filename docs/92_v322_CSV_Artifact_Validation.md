# TDS v3.2.2 CSV Artifact Validation Excellence Pass

TDS v3.2.2 continues the v3.2.x CSV stabilization branch. It does not update
README files, does not regenerate the API surface PDF, and does not change the
native C storage engine.

## Purpose

The CSV Artifact Foundation now has a validation pass that can reload a managed
CSV source and verify that its small fixed artifact set is still internally
consistent.

The validator checks:

- preserved raw CSV text hash versus manifest `raw_sha256`;
- raw byte size versus manifest `raw_size`;
- dialect artifact versus manifest dialect;
- row-offset artifact source hash, monotonicity, bounds, count, and recomputed
  offset parity;
- content-hash artifact agreement with the manifest;
- import-report agreement with row count, column count, raw hash, and fixed
  artifact-write shape;
- continued declaration that CSV imports use derived artifacts only and do not
  touch the native storage hot path.

## Design boundary

The validator is intentionally artifact-level, not cell-level. It proves the
foundation needed before later Semantic IR and seed/stack runners are added
without creating per-cell TDS reads/writes or moving CSV intelligence into the
native storage engine.

```text
TDS stores the truth.
CSV v3.2.x validates the artifact shape.
Later CSV phases can trust this foundation.
```

## New public helper

```python
from staqtapp_tds.csv_layer import validate_csv_artifacts

report = validate_csv_artifacts(directory, csv_id)
assert report.ok
```

The report is JSON-safe for future Browser telemetry.

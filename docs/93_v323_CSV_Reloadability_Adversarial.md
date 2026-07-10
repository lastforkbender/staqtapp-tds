# TDS v3.2.3 CSV Reloadability / Adversarial Corpus Pass

TDS v3.2.3 continues the v3.2.x CSV stabilization branch. It does not update
README files, does not regenerate the API surface PDF, and does not change the
native C storage engine.

## Purpose

The CSV Artifact Foundation now proves that a managed CSV source can be
rehydrated from a persisted `TDSDirectory` snapshot and validated without using
the original in-memory import objects.

This pass strengthens the foundation before any native CSV sidecar, Semantic IR,
seed registry, or stack runner work begins.

## Additions

- Added `CSVReloadedArtifacts`, a JSON-safe reload model for durable CSV
  artifacts read back from TDS storage.
- Added `reload_csv_artifacts(directory, csv_id)` to rehydrate raw CSV,
  manifest, dialect, row-offset map, content hashes, import report, and a
  validation report from storage.
- Added validation result codes through `CSVArtifactValidationReport.result_codes`
  and `primary_result_code` while preserving the existing `errors` and
  `warnings` fields.
- Tightened import-report validation for status, raw artifact count, and derived
  artifact count.
- Made malformed numeric validation fields fail closed instead of throwing from
  the validator.
- Hardened CSV row iteration with newline-preserving `StringIO(..., newline="")`
  so mixed CR/LF inputs are handled by the CSV layer instead of leaking newline
  translation behavior.

## Adversarial coverage

The v3.2.3 tests add reload and validation coverage for:

- persisted snapshot reloadability;
- mixed newline CSV sources;
- quoted delimiters;
- quoted newlines;
- doubled quotes;
- tab-separated and pipe-separated variants;
- UTF-8 text;
- empty fields;
- no terminal newline;
- unterminated quote records;
- bad numeric artifact fields;
- import-report shape drift;
- larger CSV reload sanity with fixed artifact-write shape.

## Boundary preserved

```text
CSV import/validation/reload
   -> reads and writes ordinary TDS artifacts
   -> validates derived artifact agreement
   -> never writes per cell
   -> never mutates the original CSV source
   -> never enters the native C storage hot path
```

README/API PDF are intentionally unchanged for this intermediate CSV phase.

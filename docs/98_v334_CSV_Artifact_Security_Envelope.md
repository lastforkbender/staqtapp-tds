# v3.3.4 — CSV Artifact Security Envelope

TDS v3.3.4 adds a security envelope around the CSV artifact namespace before CSV is integrated with the storage engine. The CSV layer derives durable `.tds` artifact keys from `csv_id`; therefore user-supplied IDs must not be allowed to introduce path separators, control characters, ambiguous leading punctuation, or unbounded key material.

## Scope

This pass is deliberately above storage. It does not parse semantic meaning, does not add row/cell entries, and does not touch the native storage hot path.

The new envelope validates:

- CSV IDs are bounded and artifact-safe.
- Generated IDs from `safe_csv_id(...)` remain within the accepted envelope.
- User-supplied custom IDs fail closed instead of being silently normalized.
- Core manifest artifact keys exactly match the expected CSV namespace.
- Optional scan artifact keys remain inside the same CSV namespace.
- Optional materialized scan artifacts are readable as compact JSON evidence.

## API

```python
validate_csv_id(csv_id)
is_safe_csv_id(csv_id)
validate_csv_artifact_key(key, csv_id)
validate_csv_artifact_security(directory, csv_id, include_scan_artifacts=False)
```

`validate_csv_artifact_security(...)` returns `CSVArtifactSecurityReport`, a compact slotted/frozen dataclass that can be used by advanced callers and browser/admin tooling.

## Safety rules

A valid CSV ID:

- starts with an ASCII letter or digit,
- contains only ASCII letters, digits, `_`, `.`, or `-`,
- is at most 128 characters,
- contains no slash, backslash, whitespace control characters, or empty value.

The key envelope remains intentionally narrower than general TDS entry names because CSV artifact names are generated and predictable.

## Preserved boundaries

- No native C storage-engine change.
- No routine CSV import artifact-count change.
- No per-row writes.
- No per-cell writes.
- No semantic CSV interpretation.
- No README/API PDF regeneration.

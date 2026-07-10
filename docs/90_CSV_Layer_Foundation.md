# TDS v3.2.0 CSV Artifact Foundation

TDS v3.2.0 introduces the first CSV feature layer above the hardened storage engine. The release is deliberately conservative: CSV becomes a managed artifact class, while the native C storage/index engine remains a narrow persistence and lookup layer.

## Boundary rule

```text
TDS native C engine
  -> fast lookup
  -> persistence
  -> integrity checks
  -> no CSV intelligence
  -> no seed-module execution

TDS CSV layer
  -> preserves original CSV text
  -> derives manifests, dialects, row maps, and proof reports
  -> writes derived artifacts back through ordinary TDS APIs
  -> never mutates the original CSV source
```

## Added package

```text
src/staqtapp_tds/csv_layer/
  __init__.py
  artifacts.py
  dialect.py
  exporter.py
  importer.py
  manifest.py
  row_offsets.py
```

## Artifact namespace

The v3.2.0 foundation uses flat, durable artifact keys so it can operate on any `TDSDirectory` without requiring new directory semantics:

```text
csv__<csv_id>__raw.csv
csv__<csv_id>__manifest.json
csv__<csv_id>__dialect.json
csv__<csv_id>__row_offsets.json
csv__<csv_id>__content_hashes.json
csv__<csv_id>__import_report.json
csv__<csv_id>__roundtrip_report.json
```

## Public helpers

```python
from staqtapp_tds.csv_layer import (
    import_csv_bytes,
    import_csv_file,
    export_original_csv,
    export_canonical_csv,
    prove_original_roundtrip,
)
```

## Import behavior

`import_csv_bytes(...)` and `import_csv_file(...)` store the original CSV as a text artifact and write all analysis as JSON-derived artifacts. The manifest records source identity, encoding, raw SHA-256, row count, column count, dialect fingerprint, artifact keys, and native-hot-path boundary flags.

## Dialect and row offsets

The foundation layer uses Python's standard CSV sniffer first and falls back to a deterministic delimiter score when sniffing fails. Logical row offsets are generated outside the storage engine and respect quote state, including quoted newlines.

A future `tds_native_csv_kernels` sidecar may accelerate delimiter scans, quote-state scans, row-offset generation, and row-anchor hashing. That sidecar should remain separate from `tds_native_storage_engine`.

## Round-trip proof

`prove_original_roundtrip(...)` verifies that exporting the preserved source produces the same SHA-256 as the import manifest. This gives future CSV seed stacks a durable proof that the source is still recoverable.

## Future phases this enables

```text
v3.3.0 native CSV kernel sidecar
v3.4.0 CSV Semantic IR
v3.5.0 CSV seed registry
v3.6.0 CSV stack runner
v3.7.0 Browser CSV Operations Console
v3.8.0 semantic reform/export features
v3.9.0 governed AI-assisted seed evolution
v4.0.0 high-intelligence governed CSV semantics
```

The design keeps the storage engine performance standard intact: CSV semantics read snapshots, produce derived artifacts, and commit batch-style outputs through normal TDS storage APIs.

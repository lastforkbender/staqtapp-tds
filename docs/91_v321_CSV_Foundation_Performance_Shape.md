# TDS v3.2.1 CSV Foundation Performance & Shape Pass

TDS v3.2.1 tightens the v3.2.0 CSV Artifact Foundation without changing the
native C storage engine, README files, or API surface PDF.

## Intent

The CSV layer remains above TDS storage. It preserves the original CSV source,
produces derived artifacts, and writes a fixed artifact set instead of row/cell
entries.

## Improvements

- Moved logical-record offset scanning to a byte/memoryview scanner.
- Avoided repeated whole-text encoding during row-offset generation.
- Added a raw-bytes path for row-offset maps built during import.
- Stopped manifest construction from materializing every parsed row when it only
  needs row and column counts.
- Added an import report shape contract: one raw artifact, five derived JSON
  artifacts, and no per-cell writes.
- Added larger quoted-newline tests to guard offset drift.

## Boundaries preserved

- No native C storage-engine changes.
- No multiprocessing inside storage commits.
- No README churn during intermediate CSV phases.
- No API surface PDF regeneration during intermediate CSV phases.
- No original CSV mutation; reform features must remain derived artifacts.

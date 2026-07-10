# v3.3.0 — CSV Scan Reference Foundation

TDS v3.3.0 opens the CSV scan/kernel lane with a narrow Python reference scanner. The scanner remains above the TDS storage engine and produces compact mechanical scan profiles for CSV payloads.

## Scope

- Adds `CSVScanProfile` for mechanical byte-scan facts.
- Adds `CSVScanParityReport` for comparing a fresh scan against durable CSV artifacts.
- Adds `scan_csv_bytes(...)` and `scan_csv_text(...)`.
- Adds `validate_csv_scan_profile(...)` for observational parity checks against raw, manifest, and row-offset artifacts.
- Exercises artificial chunk boundaries to keep the scanner ready for future optional native CSV kernel parity.

## Non-goals

- No semantic CSV IR.
- No seed registry.
- No stack runner.
- No Browser CSV operations console.
- No native storage-engine changes.
- No per-cell TDS writes.
- No mutation of original CSV sources.

## Mechanical scan facts

The scan profile records only source-level facts:

- row offsets
- row count
- LF, CRLF, and CR newline counts outside quotes
- quoted newline count
- delimiter count outside quotes
- quote and escaped-quote counts
- escape-sequence count
- maximum logical record span
- terminal newline state
- open-quote terminal state
- chunk size and chunk count

These facts are intentionally not semantic. They prepare the path for v3.3.x native sidecar parity without moving CSV behavior into the storage hot path.

## Boundary discipline

The scan layer reads immutable bytes or durable artifacts and returns reports. It does not own storage commits and does not widen TDS authority.

```text
TDS storage artifacts
   ↓ read-only snapshot values
CSV Python reference scanner
   ↓ mechanical scan profile
CSV scan parity report
```

Future native CSV kernels, if added, should be optional sidecars that prove parity against this Python reference scanner.

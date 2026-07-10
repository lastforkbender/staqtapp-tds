# v3.4.6 CSV Native Scan Kernel Prototype

TDS v3.4.6 introduces the first optional CSV native scan-kernel sidecar/prototype behind the v3.4.5 kernel-readiness contract.

This release does not move CSV parsing into the storage hot path. The native scan sidecar is observational: it reads immutable CSV bytes, produces a mechanical scan profile, and must match the Python reference scanner before any prototype report can be committed. The Python reference path remains the default-safe path, and requested native execution cleanly falls back unless native use is explicitly forced.

New API surface:

- `CSV_NATIVE_SCAN_KERNEL_VERSION`
- `CSV_NATIVE_SCAN_KERNEL_BACKEND`
- `CSV_NATIVE_SCAN_KERNEL_FALLBACK`
- `CSVNativeScanKernelReport`
- `csv_native_scan_kernel_report_key(...)`
- `prepare_csv_native_scan_kernel_prototype(...)`
- `commit_csv_native_scan_kernel_prototype_report(...)`
- `load_csv_native_scan_kernel_prototype_report(...)`
- `validate_csv_native_scan_kernel_prototype(...)`
- `csv_native_scan_kernel_summary(...)`

New optional sidecar source:

- `src/staqtapp_tds/_csv_scan_kernel.c`
- setup extension target: `staqtapp_tds._csv_scan_kernel`

Admission gate:

- requires a committed v3.4.5 CSV kernel-readiness contract
- validates the readiness contract against fresh evidence before native scan admission
- validates scan parity and row-anchor parity before report readiness
- compares native/fallback scan fingerprints against the Python reference fingerprint
- blocks before commit on row-offset, count, raw-hash, or scan-fingerprint mismatch

Native/fallback behavior:

- default path: Python reference scanner
- optional path: native C scan sidecar when available and requested
- fallback path: Python reference scanner when native is requested but unavailable
- fail-closed path: `force_native=True` blocks if the native sidecar is unavailable or mismatched

Preserved boundaries:

- no native storage writes
- no native storage lock control
- no storage hot-path control
- no native C storage-engine change
- no per-row writes
- no per-cell writes
- no schema inference
- no type inference
- no entity inference
- no semantic conclusions
- no formal IR commitment

Validation focus:

- default-safe no-write prepare report
- commit/load/validate lifecycle
- missing readiness contract fail-closed behavior
- fresh readiness drift blocking
- optional native request with native sidecar or clean fallback
- forced-native unavailable fail-closed behavior
- native mismatch blocking before commit
- persisted report drift detection
- deterministic scan fingerprints
- evidence-neutral boundary preservation
- unsafe CSV ID rejection

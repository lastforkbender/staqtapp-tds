# Native Execution Telemetry

Staqtapp-TDS v2.4.2 adds execution-mode telemetry for performance engineering.

The goal is to show where storage work is happening without making the dashboard part of the storage engine. TDS records boundary-level counters for:

- native backend operations
- Python fallback operations
- GIL-released native calls
- Python↔native transition count
- native batch operation count

The professional dashboard reads these values from cached snapshots only. It does not crawl the Swiss table, radix router, persistence layer, or payload data on each browser refresh.

The native Swiss-table backend now releases the GIL during the native put path, lookup, batch lookup, pop lookup, and stats scan. This is still conservative: Python object ownership remains in the wrapper layer, while the C table maps bytes keys to stable integer handles.

Execution percentages are approximate engineering signals, not profiler output. They are intended to answer questions such as:

- Is more work moving into native code?
- Are batch operations reducing Python/C boundary crossings?
- Is Python fallback dominating a workload?
- Is the dashboard observing without interfering?

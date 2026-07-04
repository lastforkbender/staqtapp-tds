# v2.9.2 TDSResult Centralization

Staqtapp-TDS v2.9.2 formalizes `TDSResult` as the only standard public success/error envelope for AI-facing non-halting operations.

## What changed

- Added `docs/API_TDSResult.md` with the public object contract and result-code catalog.
- Added `TDS_RESULT_CODES`, `known_result_codes()`, and `is_known_result_code()` in `staqtapp_tds.result`.
- Added `TDSResult.known_code` for caller-side validation.
- Removed the public `SpiralRankResult` dataclass name. Spiral rank row data is now `SpiralRankRecord`, because it is a data record, not an operation-status envelope.
- Added `NativeSpiralRankEngine.rank_result(...)` and `rank_trace_result(...)` for AI-safe rank calls that always return `TDSResult`.

## Rule

Any API surface designed to absorb exceptions, malformed input, third-party failures, decode failures, lock conflicts, missing entries, or controlled operational refusal must return `TDSResult`.

Other dataclasses may still exist for metadata, telemetry, config, provenance, snapshots, and rows, but they must not be named or used as public operation-result envelopes.

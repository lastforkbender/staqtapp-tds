# v2.8.8 Spiral Rank Statistics

v2.8.8 adds immutable observer statistics to the Native Spiral Rank Engine.

The stats layer is intentionally outside the storage hot path. It records what a
ranking call did after the call has completed, without feeding back into storage
locks, payload mutation, policy decisions, or rank control.

## Objects

- `SpiralRankStats` — per-run counts, timing, score range, mean score, native/fallback path, and limit/drop behavior.
- `SpiralRankRun` — immutable bundle containing `results` and `stats`.
- `NativeSpiralRankEngine.rank_run(...)` — returns the full bundle.
- `NativeSpiralRankEngine.rank(...)` — preserves the v2.8.7 list-returning API and stores the latest stats on `engine.last_stats`.
- `rank_trace_run(...)` — convenience helper for callers that want both results and stats.

## Statistics captured

- `input_count`
- `ranked_count`
- `limited_count`
- `dropped_by_limit`
- `limit_applied`
- `native`
- `engine`
- `elapsed_ns` / `elapsed_ms`
- `scoring_ns` / `scoring_ms`
- `sorting_ns` / `sorting_ms`
- `shaping_ns` / `shaping_ms`
- `min_score`
- `max_score`
- `mean_score`
- `config_id`
- `warnings`

## Guardrail

These statistics are telemetry. They observe the rank run; they do not control
storage, mutate trace data, train a model, or choose a policy.

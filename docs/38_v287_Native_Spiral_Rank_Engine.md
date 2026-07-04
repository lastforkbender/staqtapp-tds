# v2.8.8 Native Spiral Rank Engine

v2.8.8 adds a native scoring loop for optional Spiral-compatible trace metadata.

The subsystem is deliberately separate from the storage engine. It accepts copied numeric vectors from Python, releases the GIL while calculating scores, and returns copied scores for Python-side deterministic ordering.

It does not read TDS payloads, mutate storage, own locks, aggregate text, assign rewards, train models, or decide ranking policy. The caller owns policy. TDS provides storage, provenance, telemetry boundaries, and a fast auditable scoring primitive.

## Score formula

```text
score = source_score * score_weight
      + confidence * confidence_weight
      - depth * depth_penalty
      - age_ns * age_penalty
```

The default configuration is exposed through `SpiralRankConfig` and the primary API is `NativeSpiralRankEngine`.

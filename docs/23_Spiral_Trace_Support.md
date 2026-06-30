# Optional Spiral-Compatible Trace Support

Staqtapp-TDS can store Spiral-shaped workflow data without becoming a
Spiral implementation.

SPIRAL-style systems use sequential traces, parallel trace sets, and aggregation
outputs. TDS supports that shape as neutral storage:

```text
/spiral_runs/<run_id>/
  problem.json
  search_traces/
  trace_sets/
  aggregations/
  final/
  metadata/
```

TDS stores trace content, externally supplied rank scores, set manifests,
derived-from links, RuntimeConfig provenance, and telemetry counters. Ranking,
reward assignment, aggregation, training, and reasoning remain outside TDS.

This keeps the core directory engagement intact while making TDS useful beneath
multi-agent, verifier, and recursive aggregation workflows.

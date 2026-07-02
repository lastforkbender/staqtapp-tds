<p align="center">
    <img src="docs/dashboard-v2.7.4.png" alt="Staqtapp-TDS v2.7.4 Dashboard" width="100%"/>
</p>

- Image seen above may not reflect the current Staqtapp-TDS Dashboard's features applied


# 🟦🟪🟧 Staqtapp-TDS v2.7.4

Staqtapp-TDS is a content-neutral Temporal Directory System: a directory-first virtual storage engine with radix routing, Swiss-table-style indexing, chunking, persistence, admin control, and an observation dashboard.

The core principle remains unchanged:

> TDS stores, retrieves, indexes, observes, and records provenance. It does not reason, rank, reward, train, or aggregate on behalf of an AI system.

## Highlights

- Directory-first VFS API with semantic routing zones and reserved namespace policy.
- Swiss-table-inspired `EntryIndex` with native backend support where available.
- Radix directory router for deeper namespace routing.
- UTF-8 byte-safe text chunking.
- Serializer and compression policy metadata per entry.
- RuntimeConfig generations with stage/promote/rollback control flow.
- Local-only browser admin panel and professional observability dashboard.
- Telemetry snapshots for performance, storage, index health, behavior, recommendations, and timeline-style feedback.
- Execution-mode telemetry: native %, Python %, GIL-released %, batch ops, and Python↔native transitions.
- Optional Spiral-compatible trace/provenance module for trace-shaped workflows.

## What is new in v2.7.4

v2.7.4 finalizes the dashboard Recovery Planner page and adds an advisory Recovery Planner observer. v2.7.3 extends the Native Diagnostics Engine foundation with named slot/index/memory transition events, ring occupancy telemetry, and browser transition-ring rendering. v2.7.0 introduced native atomic counters, a bounded diagnostic event ring, immutable diagnostic snapshots, a Python diagnostics bridge, and browser Operations Console integration. Diagnostics observes consequences only; it owns no storage objects, mutates no VFS/chunk/index state, and never blocks storage hot paths. v2.7.0 also preserves the v2.6.1 JSON centralization, native checksum batching, and chunk corruption checks.

### Hardening and one-way telemetry

The dashboard remains an observer. Engine subsystems update counters; `TelemetryPublisherThread` periodically builds an immutable snapshot; the dashboard and future exporters read that snapshot. Leaving the browser open all day should not cause Swiss-table scans, radix traversal, integrity verification, benchmarks, or deep diagnostics.

Telemetry levels are available for deployment control:

- `off`
- `minimal`
- `normal`
- `engineering`
- `developer`

Health verification is explicit:

```bash
staqtapp-tds-admin verify --sample
```

Native sanitizer builds are opt-in for development/CI:

```bash
STAQTAPP_TDS_SANITIZE=address python -m pip install -e .
STAQTAPP_TDS_SANITIZE=undefined python -m pip install -e .
```

### Native performance expansion and execution-mode telemetry

v2.5.0 moves TDS back toward engine hardening after the v2.3 dashboard and Spiral-support work. The native Swiss-table backend now reports execution counters and releases the GIL for the native put path in addition to lookup, batch lookup, pop lookup, and stats scans. The observation layer exposes an execution-mode view so the dashboard can show native execution percentage, Python fallback percentage, GIL-released operation percentage, batch operation count, and Python↔native transition rate.

These values are engineering telemetry. They are not a profiler and they do not inspect stored payloads. They answer operational questions such as whether work is moving into native code, whether batch operations are reducing Python/C boundary crossings, and whether dashboard observation remains separated from the hot TDS path.

### Optional Spiral-compatible trace support

v2.5.0 includes `staqtapp_tds.spiral`, an optional workflow module for storing Spiral-shaped data without changing TDS into a reasoning system.

It supports:

- Spiral-like run directories
- search trace records
- trace-set manifests
- aggregation provenance records
- externally supplied rank metadata
- final-output provenance
- snapshot telemetry counters for trace-pipeline activity

It does **not** perform:

- trace ranking decisions
- reward assignment
- aggregation
- model training
- reasoning

A typical layout is:

```text
/spiral_runs/
  run_000041/
    problem.json
    search_traces/
      trace_0001.tds
      trace_0002.tds
    trace_sets/
      set_0001.json
    aggregations/
      agg_0001.tds
    final/
      answer.tds
    metadata/
      trace_trace_0001.json
      aggregation_agg_0001.json
```

Example:

```python
from staqtapp_tds import TDSFileSystem, create_spiral_run

fs = TDSFileSystem("root")
run = create_spiral_run(
    fs.root,
    "run_000041",
    problem={"prompt": "example task"},
    problem_id="p_812",
)

run.store_search_trace(
    "trace_0001",
    "candidate reasoning trace stored as ordinary TDS data",
    rank_score=0.87,
    rank_source="external_verifier_A",
)

run.create_trace_set("set_0001", ["trace_0001"])

run.store_aggregation(
    "agg_0001",
    "aggregated output supplied by the caller",
    derived_from=["trace_0001"],
    rank_score=0.91,
    rank_source="external_verifier_A",
)

run.store_final("answer.tds", "final answer", derived_from=["agg_0001"])
```

### Version cleanup

v2.5.0 centralizes package versioning around `pyproject.toml` and `staqtapp_tds.__version__`. Historical release comments in runtime source files were reduced or removed so the source tree no longer reads like a stack of older version banners.

### Telemetry and semantic storage positioning

The README now reflects the current TDS identity:

```text
Storage Layer
  directory / radix / index / chunking / persistence

Observation Layer
  telemetry manager / snapshots / dashboard / recommendations

Optional Workflow Layers
  Spiral-compatible trace/provenance support
```

The observation layer remains snapshot-driven. The dashboard reads cached telemetry and does not crawl the storage engine on every refresh.

## Professional dashboard

The admin panel is packaged under:

```text
src/staqtapp_tds/admin/
  panel.py
  templates/dashboard.html
  static/css/dashboard.css
  static/js/dashboard.js
  static/icons/*.svg
```

Run locally:

```bash
staqtapp-tds-admin panel
```

or from Python:

```python
from staqtapp_tds.admin.panel import AdminPanelServer
AdminPanelServer().serve_forever()
```

The panel remains local-only by default. In v2.5.1 it also surfaces execution-mode telemetry and a native/GIL feedback timeline so performance work can be verified visually without making the dashboard part of the storage engine.

## RuntimeConfig boundary

TDS supports immutable runtime configuration generations:

```python
from staqtapp_tds import RuntimeConfig, ConfigRegistry

cfg = RuntimeConfig.default().next_generation(
    compression_enabled=True,
    compression="zlib",
    spiral_support_enabled=True,
)
```

`spiral_support_enabled` is a policy flag for deployments that want to advertise or gate the optional trace workflow layer. The core directory behavior remains available either way.

## Design rule

Spiral (Sequential-Parallel-Aggregative-Reinforcement-Learning) support is intentionally neutral:

```text
Agent / verifier / ranker decides.
TDS stores the trace, score, provenance, and metadata.
Dashboard observes storage behavior.
```

That keeps TDS useful underneath advanced AI workflows while preserving its directory engagement and storage identity.


## v2.7.3 Pressure Calculations Engine

Adds component-level operational pressure scoring for engine, storage, index, lock, diagnostic-ring, memory, Python bridge, and dashboard pressure. The browser Operations Console consumes these values from immutable telemetry snapshots only.

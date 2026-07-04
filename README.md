<p align="center">
    <img src="docs/dashboard-2.7.4.png" alt="Staqtapp-TDS v2.8.1 Dashboard" width="100%"/>
</p>


# 🟦🟪🟧 Staqtapp-TDS v3.0.2

🇺🇸 **English** | 🇯🇵 [日本語](README_ja.md)

Staqtapp-TDS is a content-neutral Temporal Directory System: a directory-first virtual storage engine with radix routing, Swiss-table-style indexing, native diagnostics, browser operations telemetry, and optional Spiral-compatible trace workflows.

The core rule remains simple:

> TDS stores, retrieves, indexes, observes, and records provenance. It does not reason, reward, train, or mutate policy decisions on behalf of an AI system.

## v3.0.2 Native Safety + Dashboard Hotfix

v3.0.2 fixes a critical TinyKeyPool safety issue in `_native_index.c` by enforcing a fixed-capacity pooling invariant for small key buffers. It also fixes the wide-desktop dashboard hero graphic so the AI and TDS nodes no longer overlap. The v3.0.1 Native Engine Manager and release-pipeline architecture remain intact.

## v3.0.1 Native Engine Manager

v3.0.1 adds a professional Native Engine Manager as the single authority for optional compiled native engines. TDS now detects the runtime platform, attempts native loading through one controlled boundary, verifies the expected TDS native ABI, records capability diagnostics, and falls back to the Python backend without halting application execution.

The user application does not choose binary filenames. The library owns that responsibility.

```python
from staqtapp_tds import EntryIndex, native_status_result, native_capabilities_result

idx = EntryIndex(backend="auto")
print(idx.native_status_result().as_dict())
print(native_status_result().as_dict())
print(native_capabilities_result().as_dict())
```

Native manager diagnostics return `TDSResult` values and use the centralized result-code registry. Relevant codes include `NATIVE_ENGINE_LOADED`, `NATIVE_ENGINE_FALLBACK`, `NATIVE_ENGINE_UNAVAILABLE`, `NATIVE_ENGINE_INCOMPATIBLE`, `NATIVE_ENGINE_LOAD_ERROR`, `NATIVE_MANAGER_OK`, and `NATIVE_CAPABILITY_OK`.

## Non-halting API contract

Public AI-facing TDS operations use `TDSResult` where success/failure must be reported without raising TDS-generated exceptions. Native import failures, missing compiled binaries, ABI mismatches, and fallback decisions are reported through structured result values, not by stopping the caller.

The authoritative result-code source is:

```text
src/staqtapp_tds/result.py
```

Generated references are available at:

```text
docs/TDS_RESULT_CODES.md
docs/TDS_RESULT_CODES.json
```

## Automated release pipeline scaffold

v3.0.1 adds release-check automation and a future wheel-build scaffold. The current ZIP is a clean source archive and intentionally excludes `.so`, `.pyd`, `.dll`, `.dylib`, `.pyc`, `__pycache__`, and `.pytest_cache` artifacts. Platform wheels and compiled binaries belong to the release-distribution stage after TDS reaches public release readiness.

Design notes:

- `docs/44_v301_Native_Engine_Manager.md`
- `docs/RELEASE_PIPELINE.md`

## Highlights

- Directory-first VFS API with semantic routing zones and reserved namespace policy.
- Native Swiss-table-inspired `EntryIndex` backend where available.
- Native diagnostic event ring with loss-tolerant telemetry snapshots.
- Native Spiral Rank scoring loop with Python fallback and immutable per-run stats.
- Browser Operations Console Spiral Rank page with feedback telemetry, Top-N traces, and timing history.
- GIL-released native execution paths for indexing, checksum, chunk scanning, and rank scoring.
- Browser Operations Console with localized language packs and professional telemetry pages.
- RuntimeConfig generation control with stage, promote, and rollback semantics.
- Optional Spiral-compatible trace/provenance helpers.
- Local-only browser admin panel hardened with CSRF/origin protection and safe DOM rendering.

## Installation

```bash
python -m pip install -e .
```

Run the test suite:

```bash
pytest -q
```

Run the local browser console:

```bash
staqtapp-tds-admin panel
```

Health verification:

```bash
staqtapp-tds-admin verify --sample
```

Native sanitizer builds remain opt-in for development and CI:

```bash
STAQTAPP_TDS_SANITIZE=address python -m pip install -e .
STAQTAPP_TDS_SANITIZE=undefined python -m pip install -e .
```

## Native Spiral Rank Engine

```python
from staqtapp_tds.spiral import NativeSpiralRankEngine

engine = NativeSpiralRankEngine()
ranked = engine.rank(
    trace_ids=["trace_a", "trace_b", "trace_c"],
    scores=[0.91, 0.80, 0.91],
    confidences=[0.95, 0.90, 0.95],
    depths=[3, 1, 1],
    ages_ns=[0, 0, 0],
)

for result in ranked:
    print(result.rank, result.trace_id, result.score, result.native)
```

The score model is intentionally small and auditable:

```text
score = source_score * score_weight
      + confidence * confidence_weight
      - depth * depth_penalty
      - age_ns * age_penalty
```

Defaults live in `SpiralRankConfig`. Python performs validation and stable ordering; the native extension performs the numeric scoring loop when available.

For telemetry-grade visibility, use `rank_run(...)` instead of `rank(...)`:

```python
run = engine.rank_run(["a", "b", "c"], [0.2, 0.9, 0.5], limit=2)
print(run.stats.to_dict())
```

`SpiralRankStats` records `input_count`, `ranked_count`, `limited_count`, `dropped_by_limit`, native/fallback path, elapsed/scoring/sorting/shaping timings, min/max/mean score, warnings, and the active config id. These are observer statistics only; they do not feed back into storage, policy, or scoring control.

## Optional Spiral-compatible trace support

TDS can store Spiral-shaped workflow data without becoming the reasoning system:

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
    "candidate trace stored as ordinary TDS data",
    rank_score=0.87,
    rank_source="external_verifier_A",
)

run.create_trace_set("set_0001", ["trace_0001"])
run.store_final("answer.tds", "final answer", derived_from=["trace_0001"])
```

Typical layout:

```text
/spiral_runs/
  run_000041/
    problem.json
    search_traces/
    trace_sets/
    aggregations/
    final/
    metadata/
```

## Telemetry and dashboard boundary

Telemetry remains one-way and snapshot-driven. The dashboard reads cached telemetry; it does not crawl the storage engine on every refresh and does not put browser activity into the storage hot path.

Telemetry levels:

- `off`
- `minimal`
- `normal`
- `engineering`
- `developer`

## Design boundary

```text
Caller / verifier / ranker decides.
TDS stores trace data, metadata, scores, and provenance.
Native rank scoring accelerates copied numeric metadata only.
Dashboard observes immutable snapshots.
```

This keeps TDS useful under advanced AI workflows while preserving its storage identity.

## Release notes

v3.0.1 builds on the v2.8.7 Native Spiral Rank Engine. It adds immutable Spiral rank statistics, run-bundle export, stats tests, updated bilingual documentation, and preserves the list-returning v2.8.7 rank API.

Additional v3.0.1 design note: `docs/40_v290_Spiral_Rank_Browser_Telemetry.md`.

<p align="center">
    <img src="docs/dashboard-2.7.4.png" alt="Staqtapp-TDS v2.8.1 Dashboard" width="100%"/>
</p>


# 🟦🟪🟧 Staqtapp-TDS v2.9.4

🇺🇸 **English** | 🇯🇵 [日本語](README_ja.md)

Staqtapp-TDS is a content-neutral Temporal Directory System: a directory-first virtual storage engine with radix routing, Swiss-table-style indexing, native diagnostics, browser operations telemetry, and optional Spiral-compatible trace workflows.

The core rule remains simple:

> TDS stores, retrieves, indexes, observes, and records provenance. It does not reason, reward, train, or mutate policy decisions on behalf of an AI system.

## v2.9.4 Non-Halting Result Contract

v2.9.4 formalizes the public TDS return contract for AI systems and long-running services. Public TDS operations that can fail in normal operation return a standardized `TDSResult` instead of halting caller execution with TDS-generated exceptions or ambiguous boolean failure values.

This means callers can use one predictable pattern:

```python
result = directory.write("agent_state", state)

if result.ok:
    stored = result.value
else:
    print(result.code)
    print(result.message)
    print(result.meta)
```

`TDSResult` is the single public success/failure envelope for controlled TDS outcomes. It contains:

- `ok`: `True` for success, `False` for controlled failure.
- `code`: a stable machine-readable result code.
- `message`: a human-readable explanation.
- `name` / `path`: optional TDS location context.
- `value`: the returned object or operation payload when applicable.
- `meta`: structured diagnostics for logging, telemetry, retry policy, or AI decision logic.

The authoritative result-code source is:

```text
src/staqtapp_tds/result.py
```

All public `TDSResult.code` values are defined in `TDSResultCode` and described in `TDS_RESULT_REGISTRY`. Human and machine-readable references are generated from that registry:

```text
docs/TDS_RESULT_CODES.md
docs/TDS_RESULT_CODES.json
```

Additional contract documentation:

```text
docs/API_TDSResult.md
docs/NON_HALTING_API.md
```

Design guarantees for normal TDS-controlled failures:

- Public result-first operations return `TDSResult`.
- Public TDS operations do not intentionally halt caller execution for normal storage, decode, missing-entry, validation, or caught environment failures.
- Result codes are centralized in the runtime registry, not scattered across the codebase as independent status strings.
- Result-code documentation is generated from the runtime registry to prevent documentation drift.
- Compatibility methods that return raw values remain explicit by name, such as `read_value()`, `write_entry()`, and `delete_entry()`.

This guarantee does not claim to prevent process-level failures outside TDS control, such as interpreter termination, operating-system failure, fatal native crashes, `KeyboardInterrupt`, or unrecoverable memory exhaustion.

## v2.9.4 Result Registry Discipline

Staqtapp-TDS defines every public `TDSResult.code` in one runtime source of truth: `src/staqtapp_tds/result.py`. Use `TDSResultCode` for code comparisons and `result_info(code)` for machine-readable metadata. The Markdown and JSON result-code references are generated from that registry.

```python
from staqtapp_tds import TDSResultCode, result_info

result = directory.read("agent_state")

if not result.ok:
    info = result_info(result.code)
    if result.code == TDSResultCode.READ_MISSING.value:
        ...
```

## Highlights

- Directory-first VFS API with semantic routing zones and reserved namespace policy.
- Standardized non-halting `TDSResult` return envelope for public result-first operations.
- Central `TDSResultCode` registry with generated Markdown and JSON references.
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

v2.9.0 builds on the v2.8.7 Native Spiral Rank Engine. It adds immutable Spiral rank statistics, run-bundle export, stats tests, updated bilingual documentation, and preserves the list-returning v2.8.7 rank API.

Additional v2.9.0 design note: `docs/40_v290_Spiral_Rank_Browser_Telemetry.md`.

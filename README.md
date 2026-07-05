<p align="center">
    <img src="docs/dashboard-2.7.4.png" alt="Staqtapp-TDS v2.8.1 Dashboard" width="100%"/>
</p>


# 🟦🟪🟧 Staqtapp-TDS v3.1.2

## v3.1.2 Driver Foundry API

TDS v3.1.2 adds the AI-safe `DriverFoundry` API: a survivable build/test/candidate layer for rapid driver generation without giving an AI system registry trust authority. The Foundry can validate TDDL, compile `.tdd` bytecode, audit VM contracts, test packages through `DriverVMRuntime`, and submit registry candidates. It cannot approve, sign, activate, bypass policy, write storage, or execute arbitrary Python.

Class A Foundry properties:

- AI and Studio callers receive structured `DriverFoundryResult` values rather than raw exceptions for expected source, package, fixture, runtime, and policy failures.
- `DriverVMResult` is preserved inside Foundry test results so repair loops receive trace, faults, cost, context, partial outputs, and emitted-result evidence.
- Candidate submission requires successful runtime test evidence by default and only moves a driver into `DriverState.CANDIDATE`.
- Approval, signing, activation, retirement, and revocation remain outside the Foundry API.
- `foundry_capability_matrix()` exposes the authority boundary for future PyQt5 Studio and AI-agent surfaces.

## v3.1.1 Driver VM Non-Halting Result Framework

TDS v3.1.1 adds `DriverVMResult`, a VM-specific non-halting execution envelope for the Driver VM. Runtime faults stop the driver, not the host process: unloaded execution, bad record input, runtime budget overflow, unsupported operands, unsupported adapter execution, and defensive internal errors all return structured results with `VMStatus`, `VMFault`, `DriverVMContext`, trace, metrics, and partial-output evidence.

Class A runtime result properties:

- `execute()` returns structured `DriverVMResult` values for expected VM faults.
- Successful driver termination reports `VMStatus.HALTED` while preserving the historical `VMState.EXECUTED` compatibility state.
- Bad input returns `INPUT_REJECTED`; runtime budget overflow returns `BUDGET_EXCEEDED`; unsupported semantics return `FAULTED`; unexpected handler errors are contained as `INTERNAL_ERROR`.
- Runtime record snapshots are deep-copied so driver execution does not mutate caller input.
- `MATCH field=...` now requires a predicate before bytecode; `regex_limited` and numeric `range` predicates have deterministic runtime behavior.
- The Driver VM runtime remains separate from storage-engine internals, with a regression test guarding that boundary.

## v3.1.0 Driver VM Runtime

TDS v3.1.0 adds the first deterministic Driver VM runtime for validated `.tdd` bytecode packages. The runtime executes the safe opcode set (`SCAN`, `READ`, `MATCH`, `EXTRACT`, `SCORE`, `TRACE`, `EMIT`, `HALT`) against caller-provided in-memory `.tds` record snapshots. It remains separate from the Native Storage Engine: drivers do not manipulate slots, locks, native indexes, or storage internals.

Class A runtime properties:

- Validated bytecode must pass package hash, opcode, driver-class, capability, and budget checks before execution.
- Runtime inputs are explicit record snapshots, not direct storage-engine handles.
- Execution emits deterministic trace events and bounded results.
- `DriverVMSkeleton` remains available as a non-executing audit loader; `DriverVMRuntime` is the executable path.
- Unsupported or malformed runtime inputs fail closed.

## v3.0.9 Driver Studio Class A Quick Test

TDS v3.0.9 adds a non-GUI Driver Studio readiness path. It models the future Studio as a gated certification workflow: learn, syntax validation, capability checks, bytecode generation, VM audit, VM skeleton load, registry approval, signing and activation. Execution remains disabled; the Studio teaches and orchestrates while Builder/VM/Registry remain authoritative.

## v3.0.9 VM Contract Audit + Driver VM Skeleton

TDS v3.0.9 adds a non-executing VM contract audit and native-facing Driver VM skeleton. Compiled TDDL bytecode can now be loaded only after fail-closed validation of package hash, opcode mapping, instruction contracts, driver-class permissions, required capabilities, and VM budgets. Execution remains intentionally disabled until the separate native Driver VM runtime is built.


🇺🇸 **English** | 🇯🇵 [日本語](README_ja.md)

## v3.0.9 TDDL Grammar Validation

TDS v3.0.9 adds a non-executing TDS Driver Language grammar and validation layer for future Driver VM, Builder, Registry and Studio work. It validates SCAN/READ/MATCH/EXTRACT/SCORE/EMIT/HALT behavior, rejects unsafe adapter names and path escapes, requires declared capabilities/adapters, and exposes an instruction metadata table for a future minimal syntax editor.

This release still does not execute driver programs; it prepares a stable, tested syntax boundary before native Driver VM bytecode is introduced.


Staqtapp-TDS is a content-neutral Temporal Directory System: a directory-first virtual storage engine with radix routing, Swiss-table-style indexing, native diagnostics, browser operations telemetry, and optional Spiral-compatible trace workflows.

The core rule remains simple:

> TDS stores, retrieves, indexes, observes, and records provenance. It does not reason, reward, train, or mutate policy decisions on behalf of an AI system.

## v3.0.9 Admin Origin Fail-Closed Safety Patch

v3.0.9 hardens privileged admin POST routes (`/stage`, `/promote`, `/rollback`) so same-origin validation is fail-closed. Requests missing both `Origin` and `Referer` are rejected even when the CSRF token is valid; valid same-origin `Origin` or `Referer` plus a valid CSRF token is required.

## v3.0.3 Class A Pickle Boundary

v3.0.3 centralizes all Python pickle compatibility into `tds_pickle.py`. TDS no longer calls `pickle.loads()` from the storage hot path. Pickle payloads now use a TDS envelope on write, restricted deserialization by default, write-time validation for restricted compatibility, structured failure metadata, and an explicit `TDS_ALLOW_UNSAFE_PICKLE=1` legacy escape hatch for controlled migrations only. JSON, text, raw binary, and NumPy lanes remain first-class non-pickle paths.

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

## v3.0.9 Serialization Manager

TDS includes a first-class Serialization Manager for variable payloads. `addvar()` infers the best codec, `loadvar()` and `findvar()` recover through the same policy path, and complex Python objects are routed to the restricted pickle codec rather than raw `pickle.loads()` calls in storage code.


## v3.0.9 Driver Foundation Testbed

TDS v3.0.9 adds a non-executing driver foundation for the future native Driver VM and Driver Studio. It introduces tested contracts for driver manifests, registry states, signature-policy rejection, and deterministic trace ranking while keeping the Native Storage Engine separate and unchanged.

The release intentionally does not execute driver programs yet. It prepares the trust and testing surface first so the native VM can be built against stable, regression-tested behavior.


## v3.0.9 TDDL Bytecode Package

TDS v3.0.9 adds a non-executing compiler artifact layer for future native Driver VM work. Validated TDDL can now compile into a deterministic `BytecodePackage` with a stable v1 opcode map, constant pool, source hash, and tamper-evident package hash.

This is intentionally not a runtime VM yet. It prepares `.tddl -> IR -> bytecode package` contracts without allowing driver execution.

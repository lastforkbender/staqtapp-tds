> **v3.5.3 release security contract**
>
> At-rest encryption is not implemented. Requests using `DirFlags.ENCRYPTED` fail closed instead of storing plaintext. New v2 persistence files require their integrity sidecar. `.tds` input should be treated as trusted until explicit resource-budget hardening is complete. Native extensions are optional and are built only when `STAQTAPP_TDS_BUILD_NATIVE=1` is set.

# Staqtapp-TDS v3.5.3

**Temporal Directory System - native-indexed `.tds` storage, controlled variables, trace ranking, CSV evidence operations, semantic review, and centralized observability for AI systems.**

**Programmer start here:** [Staqtapp-TDS Programmer Core API Guide (PDF)](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf)

## Browser Operations Console — all 19 pages

These are 19 separate 1280×800 viewport captures from the packaged, localhost-only TDS Browser. Each capture was made after selecting the corresponding navigation control against a real release-qualification observer snapshot. Page 07 is the actual CSV Interpole Monitor in its `Monitor Ready` state. The images are shown vertically in Browser navigation order; they are not a stitched Dashboard image or a UI mock.

<p align="center"><strong>01 — Dashboard</strong><br>
  <img src="docs/screenshots/browser_pages/01-dashboard-1280x800.png" alt="Staqtapp-TDS Browser page 01, Dashboard, selected in the navigation" width="100%">
</p>
<p align="center"><strong>02 — Engine Health</strong><br>
  <img src="docs/screenshots/browser_pages/02-engine-health-1280x800.png" alt="Staqtapp-TDS Browser page 02, Engine Health, selected in the navigation" width="100%">
</p>
<p align="center"><strong>03 — Real-time Metrics</strong><br>
  <img src="docs/screenshots/browser_pages/03-real-time-metrics-1280x800.png" alt="Staqtapp-TDS Browser page 03, Real-time Metrics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>04 — Transition Timeline</strong><br>
  <img src="docs/screenshots/browser_pages/04-transition-timeline-1280x800.png" alt="Staqtapp-TDS Browser page 04, Transition Timeline, selected in the navigation" width="100%">
</p>
<p align="center"><strong>05 — Event Ring Monitor</strong><br>
  <img src="docs/screenshots/browser_pages/05-event-ring-monitor-1280x800.png" alt="Staqtapp-TDS Browser page 05, Event Ring Monitor, selected in the navigation" width="100%">
</p>
<p align="center"><strong>06 — Pressure Diagnostics</strong><br>
  <img src="docs/screenshots/browser_pages/06-pressure-diagnostics-1280x800.png" alt="Staqtapp-TDS Browser page 06, Pressure Diagnostics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>07 — CSV Interpole</strong><br>
  <img src="docs/screenshots/browser_pages/07-csv-interpole-1280x800.png" alt="Staqtapp-TDS Browser page 07, the real CSV Interpole Monitor in Monitor Ready state, selected in the navigation" width="100%">
</p>
<p align="center"><strong>08 — Snapshot Explorer</strong><br>
  <img src="docs/screenshots/browser_pages/08-snapshot-explorer-1280x800.png" alt="Staqtapp-TDS Browser page 08, Snapshot Explorer, selected in the navigation" width="100%">
</p>
<p align="center"><strong>09 — Lock Contention</strong><br>
  <img src="docs/screenshots/browser_pages/09-lock-contention-1280x800.png" alt="Staqtapp-TDS Browser page 09, Lock Contention, selected in the navigation" width="100%">
</p>
<p align="center"><strong>10 — Workload Analytics</strong><br>
  <img src="docs/screenshots/browser_pages/10-workload-analytics-1280x800.png" alt="Staqtapp-TDS Browser page 10, Workload Analytics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>11 — Spiral Rank</strong><br>
  <img src="docs/screenshots/browser_pages/11-spiral-rank-1280x800.png" alt="Staqtapp-TDS Browser page 11, Spiral Rank, selected in the navigation" width="100%">
</p>
<p align="center"><strong>12 — Index Analytics</strong><br>
  <img src="docs/screenshots/browser_pages/12-index-analytics-1280x800.png" alt="Staqtapp-TDS Browser page 12, Index Analytics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>13 — Storage Analytics</strong><br>
  <img src="docs/screenshots/browser_pages/13-storage-analytics-1280x800.png" alt="Staqtapp-TDS Browser page 13, Storage Analytics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>14 — Comparative Views</strong><br>
  <img src="docs/screenshots/browser_pages/14-comparative-views-1280x800.png" alt="Staqtapp-TDS Browser page 14, Comparative Views, selected in the navigation" width="100%">
</p>
<p align="center"><strong>15 — Recovery Planner</strong><br>
  <img src="docs/screenshots/browser_pages/15-recovery-planner-1280x800.png" alt="Staqtapp-TDS Browser page 15, Recovery Planner, selected in the navigation" width="100%">
</p>
<p align="center"><strong>16 — Policy Proposals</strong><br>
  <img src="docs/screenshots/browser_pages/16-policy-proposals-1280x800.png" alt="Staqtapp-TDS Browser page 16, Policy Proposals, selected in the navigation" width="100%">
</p>
<p align="center"><strong>17 — Alerts &amp; Events</strong><br>
  <img src="docs/screenshots/browser_pages/17-alerts-events-1280x800.png" alt="Staqtapp-TDS Browser page 17, Alerts and Events, selected in the navigation" width="100%">
</p>
<p align="center"><strong>18 — Security</strong><br>
  <img src="docs/screenshots/browser_pages/18-security-1280x800.png" alt="Staqtapp-TDS Browser page 18, Security, selected in the navigation" width="100%">
</p>
<p align="center"><strong>19 — Settings</strong><br>
  <img src="docs/screenshots/browser_pages/19-settings-1280x800.png" alt="Staqtapp-TDS Browser page 19, Settings, selected in the navigation" width="100%">
</p>

[日本語 README](README_ja.md) | [Complete API Surface Reference PDF](tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) | [Changelog](CHANGELOG.md)

## What TDS provides

Staqtapp-TDS is a directory-first storage and operations layer for AI applications. It stores Python values, text, JSON, binary payloads, trace evidence, driver evidence, and managed CSV artifacts in a structured in-memory hierarchy that can be flushed to and mounted from `.tds` files.

TDS is designed around a narrow storage hot path. Native indexing, lookup, persistence, and optional CSV scan kernels stay separate from diagnostics, Browser rendering, Driver Studio, Semantic IR review, and policy-facing evidence workflows.

## Current advantages

| Capability | Practical advantage |
|---|---|
| `.tds` persistence | Atomic file replacement, mmap random access, sidecar integrity metadata, mounted-reader lifecycle, and deterministic directory snapshots. |
| Direct variable control | Add, edit, lock, unlock, find, load, and append through stalk chains without inventing a separate application database API. |
| Non-halting result model | Result-first calls return `TDSResult` with stable codes, messages, values, and metadata instead of forcing ordinary application failures to halt an AI runtime. |
| Native-indexed storage | Optional compiled index and checksum paths with deterministic Python fallbacks and explicit native capability reporting. |
| Trace ranking | Deterministic Spiral-compatible trace ranking with confidence, depth, age, top-N limiting, statistics, and native/Python parity. |
| CSV Suite | Original-byte preservation, dialect evidence, logical row offsets, row anchors, scan parity, artifact transactions, storage binding, native scan evidence, Interpole telemetry, Semantic IR candidates, lifecycle transitions, and atomic batch review. |
| Evidence-bound semantics | TDS records explicit caller declarations and authorized review transitions; it does not silently infer or commit semantic truth. |
| Driver platform | TDDL validation, deterministic bytecode, bounded Driver VM execution, Foundry proposal/test flows, regression evidence, review bundles, and read-only Studio integration. |
| Centralized Browser | One local Browser surface for engine health, pressure, event rings, CSV Interpole, Spiral Rank, snapshots, indexes, storage, recovery, alerts, security, and settings. |
| Observer isolation | Browser, telemetry, diagnostics, and Studio consume snapshots or copied events rather than controlling storage locks. |

## Install

```bash
python -m pip install .

# Optional PyQt5 Driver Studio
python -m pip install ".[gui]"
```

Python 3.10 or newer and NumPy are required. The C extensions are optional; supported operations retain deterministic Python fallback paths unless a caller explicitly forces native-only execution.

## Core storage quick start

```python
from pathlib import Path
from staqtapp_tds import TDSFileSystem, TDSPersistence

fs = TDSFileSystem("agent_state")
models = fs.makedirs("/models/runtime")

models.write_text("system_prompt", "You are a careful planning agent.")
models.write_json("settings", {"temperature": 0.2, "tools": True})
models.write_result("step_count", 7)

result = models.read_result("settings")
if result.ok:
    settings = result.value

store = TDSPersistence(Path("./tds_store"))
store.flush(fs, parallel_nodes=False)

# Load one persisted node from agent_state.tds
loaded_runtime = store.load_node(
    Path("./tds_store/agent_state__models__runtime.tds")
)
assert loaded_runtime.read_value("step_count") == 7
```

## Variable manipulation quick start

```python
state = fs.makedirs("/agent/state")

state.addvar("reward", 1.0)
state.editvar("reward", 1.25)
state.lockvar("reward")

found = state.findvar("reward")
assert found.ok and found.value == 1.25

state.unlockvar("reward")
state.addvar("context", ["initial"])
state.stalkvar("~context", ["observation-1"])
state.stalkvar("~context", ["observation-2"])
latest_context = state.loadvar("context_0002")
```

## Trace ranking quick start

```python
from staqtapp_tds.spiral import rank_traces

ranked = rank_traces(
    ["trace-a", "trace-b", "trace-c"],
    [0.82, 0.95, 0.95],
    confidences=[0.90, 0.92, 0.92],
    depths=[2, 3, 1],
    limit=2,
)

for record in ranked:
    print(record.rank, record.trace_id, record.rank_score)
```

## CSV quick start

```python
from staqtapp_tds.csv_layer import (
    export_original_csv,
    import_csv_bytes,
    prove_original_roundtrip,
    validate_csv_artifacts,
)

csv_dir = fs.makedirs("/datasets")
manifest = import_csv_bytes(
    csv_dir,
    b"id,name,score\n1,Ada,99\n2,Grace,98\n",
    source_name="people.csv",
)

validation = validate_csv_artifacts(csv_dir, manifest.csv_id)
assert validation.ok
assert export_original_csv(csv_dir, manifest.csv_id).startswith("id,name")
assert prove_original_roundtrip(csv_dir, manifest.csv_id).byte_equivalent
```

The CSV layer stores the source and derived evidence as bounded TDS artifacts. It does not write one TDS entry per cell and does not turn the native storage engine into a CSV parser or semantic reasoner.

## Centralized Browser

```bash
staqtapp-tds-admin status
staqtapp-tds-admin verify --sample
staqtapp-tds-admin serve-panel --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. The Browser is local-only by default, requires same-origin and CSRF checks for configuration actions, and reads cached status snapshots rather than walking storage structures on each refresh.

## Architecture boundary

```text
AI application / service
        |
        +-- TDSResult-first storage and variable calls
        +-- trace ranking and provenance
        +-- CSV evidence and Semantic IR review
        +-- Driver Foundry / Runtime Manager / Studio
        |
        v
Python TDS orchestration layer
        |
        +-- immutable snapshots and copied diagnostics --> centralized Browser
        |
        v
native index / optional CSV kernels / .tds persistence
```

Native storage is responsible for narrow mechanical work. Diagnostics, Semantic IR, Driver Studio, and Browser rendering do not control native storage locks.

## Programmer documentation

The [Programmer Core API Guide](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf) is the recommended starting point. Its first three pages are the authoritative v3.5.3 supplement for controlled activation, segment GC, and release qualification. The broad guide then organizes direct calls by task and includes implementation snippets for:

- directory and entry operations;
- `.tds` writing, reading, mounting, and integrity behavior;
- variable manipulation and stalk chains;
- text, JSON, serialization, provenance, and result handling;
- telemetry, verification, pressure, recovery, and native diagnostics;
- trace creation and ranking;
- the complete operational CSV call chain;
- Semantic IR candidates, lifecycle transitions, and atomic batches;
- Driver Foundry, VM, Runtime Manager, regression, review, evidence, Browser, and Driver Studio calls.

Use the current [v3.5.3 Guaranteed Storage API reference](docs/reference/Programmers_API_Reference.md) for the new storage calls. The separate [API Surface Reference PDF](tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) is retained as a historical v3.1.23 Driver/Studio reference; it is not an exhaustive v3.5.3 inventory.

## Safety and authority boundaries

TDS intentionally distinguishes preparation, evidence, review, and authority:

- CSV Semantic IR calls do not autonomously declare semantic truth.
- v3.5.2 admits `proposed`, `validated`, and `contested`; it does not admit `committed` or `superseded`.
- Driver Foundry may validate, compile, audit, test, and submit candidates; it does not sign or activate drivers.
- Driver Studio observes, explains, prepares proposals, and routes review requests; it does not bypass Registry, Review Board, Runtime Manager, or signature policy.
- Browser telemetry is snapshot-based and is not a storage control loop.

## Validation status

Local v3.5.3 release qualification is complete:

- Phase 10 controlled activation, exact migration proof, and lossless rollback tests;
- Phase 11 GC corruption, publication-window, replacement, interruption, concurrency, and accounting tests;
- a 129-generation incremental/recovery/GC soak;
- Python 3.10–3.14, Windows, macOS, Linux, and native-extension CI gates;
- PEP 517 wheel/sdist, metadata, isolated-install, and source-hygiene gates.

Evidence: 832 passed and 11 skipped in the pure monolithic suite; 843 passed in the native-active monolithic suite; and 157 passed in the overlapping v3.5.3/workflow/Browser/CSV qualification group. Both distribution artifacts passed `twine check`, archive-content inspection, and an isolated wheel activation/rollback/GC smoke test. Exact details are recorded in `DEV11_RELEASE_QUALIFICATION_STATUS.txt`. No push or tag has been made. A v3.5.3 tag remains prohibited until the eventual cross-platform GitHub Actions run is green.

## Repository map

```text
src/staqtapp_tds/          core storage, persistence, telemetry, native management
src/staqtapp_tds/csv_layer CSV evidence, transactions, Interpole, Semantic IR
src/staqtapp_tds/drivers/  TDDL, bytecode, VM, Foundry, review and evidence
src/staqtapp_tds/studio_pyqt5/ optional Driver Studio cockpit
src/staqtapp_tds/admin/    centralized Browser and local admin control
examples/                  runnable examples
docs/                      architecture and release contract documents
tds_api_docs/              programmer guide and historical API-surface PDF
```

## License

See [LICENSE](LICENSE).

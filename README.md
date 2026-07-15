> **v3.5.2 remediation security contract**
>
> At-rest encryption is not implemented. Requests using `DirFlags.ENCRYPTED` fail closed instead of storing plaintext. New v2 persistence files require their integrity sidecar. `.tds` input should be treated as trusted until explicit resource-budget hardening is complete. Native extensions are optional and are built only when `STAQTAPP_TDS_BUILD_NATIVE=1` is set.

# Staqtapp-TDS v3.5.2

**Temporal Directory System - native-indexed `.tds` storage, controlled variables, trace ranking, CSV evidence operations, semantic review, and centralized observability for AI systems.**

**Programmer start here:** [Staqtapp-TDS Programmer Core API Guide (PDF)](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf)

<p align="center">
  <img src="docs/screenshots/tds_browser_telemetry_overview_1280x800.png" alt="All 19 Staqtapp-TDS Browser pages captured individually, with CSV Interpole Monitor shown as page 07" width="100%">
</p>

<p align="center"><em>Browser Operations Console</em></p>

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

The new [Programmer Core API Guide](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf) is the recommended starting point. It organizes direct calls by task and includes implementation snippets for:

- directory and entry operations;
- `.tds` writing, reading, mounting, and integrity behavior;
- variable manipulation and stalk chains;
- text, JSON, serialization, provenance, and result handling;
- telemetry, verification, pressure, recovery, and native diagnostics;
- trace creation and ranking;
- the complete operational CSV call chain;
- Semantic IR candidates, lifecycle transitions, and atomic batches;
- Driver Foundry, VM, Runtime Manager, regression, review, evidence, Browser, and Driver Studio calls.

The [API Surface Reference](tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) remains available for broad class-by-class inspection.

## Safety and authority boundaries

TDS intentionally distinguishes preparation, evidence, review, and authority:

- CSV Semantic IR calls do not autonomously declare semantic truth.
- v3.5.2 admits `proposed`, `validated`, and `contested`; it does not admit `committed` or `superseded`.
- Driver Foundry may validate, compile, audit, test, and submit candidates; it does not sign or activate drivers.
- Driver Studio observes, explains, prepares proposals, and routes review requests; it does not bypass Registry, Review Board, Runtime Manager, or signature policy.
- Browser telemetry is snapshot-based and is not a storage control loop.

## Validation status

The v3.5.2 delivery baseline was validated with:

- 683 fallback/source tests passed and 11 native-only tests skipped;
- 694 tests passed with both C extensions built;
- 61 packaged Semantic IR tests passed;
- fresh-archive release checking and packaged native builds passed;
- no compiled objects or cache directories included in the source archive.

## Repository map

```text
src/staqtapp_tds/          core storage, persistence, telemetry, native management
src/staqtapp_tds/csv_layer CSV evidence, transactions, Interpole, Semantic IR
src/staqtapp_tds/drivers/  TDDL, bytecode, VM, Foundry, review and evidence
src/staqtapp_tds/studio_pyqt5/ optional Driver Studio cockpit
src/staqtapp_tds/admin/    centralized Browser and local admin control
examples/                  runnable examples
docs/                      architecture and release contract documents
tds_api_docs/              programmer and full API PDFs
```

## License

See [LICENSE](LICENSE).

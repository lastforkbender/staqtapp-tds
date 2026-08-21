# TDS Developer Guide

This guide targets the current v3.8.3 release and is organized by application
task. For exact signatures, use the programmer references under `tds_api_docs/`,
`docs/reference/Programmers_API_Reference.md`, and the public source docstrings.

## Install and launch

```bash
python -m pip install staqtapp-tds==3.8.3
staqtapp-tds

# Optional PyQt5 Driver Studio cockpit
python -m pip install "staqtapp-tds[gui]==3.8.3"
```

The standard installation includes the HTML Browser and headless Driver Studio
models. Constructing the PyQt5 cockpit requires the `gui` extra. Optional C
extensions are source-build accelerators and require
`STAQTAPP_TDS_BUILD_NATIVE=1`; application code must remain correct with the
Python fallback.

## Create directories and store values

```python
from staqtapp_tds import TDSFileSystem

fs = TDSFileSystem("agent_state")
runtime = fs.makedirs("/models/runtime")

runtime.write_text("prompt.txt", "Be precise.")
runtime.write_json("settings", {"temperature": 0.2})
runtime.write_result("step_count", 7)
```

Names are identities within one directory. Use the explicit overwrite or edit
surface when replacement is intended.

## Handle ordinary failures without halting

Result-first APIs return `TDSResult` for ordinary operational outcomes:

```python
result = runtime.read_result("settings")
if result.ok:
    settings = result.value
else:
    logger.warning("TDS %s: %s", result.code, result.message)
```

Branch on `result.ok` and `result.code`, not on the human-readable message.
Use `result.meta` for diagnostics. Raw compatibility surfaces are explicit and
should not be confused with result-first application calls. See
`docs/NON_HALTING_API.md` and `docs/TDS_RESULT_CODES.md`.

## Use controlled variables

```python
state = fs.makedirs("/agent/state")
state.addvar("reward", 1.0)
state.editvar("reward", 1.25)
state.lockvar("reward")

locked = state.editvar("reward", 2.0)
assert not locked.ok and locked.code == "VAR_LOCKED"

state.unlockvar("reward")
state.addvar("context", ["initial"])
state.stalkvar("~context", ["observation-1"])
```

Variable locks and stalk chains are policy at the variable API boundary. They
do not turn low-level index lookups into a policy engine.

## Persist and reopen a filesystem

```python
from pathlib import Path
from staqtapp_tds import TDSPersistence

store = TDSPersistence(Path("./tds_store"))
store.flush(fs, parallel_nodes=False)

loaded = store.load_node(
    Path("./tds_store/agent_state__models__runtime.tds")
)
assert loaded.read_value("step_count") == 7
```

Treat a `.tds` file and its required sidecar as one integrity unit. Use a new
destination for migration or rollback materialization, retain off-device
backups, and do not interpret local immutable generations as backups.

Guaranteed Storage is opt-in. Qualification does not activate it; activation
and rollback require their explicit acknowledgement and revalidation calls.
Review `docs/reference/Programmers_API_Reference.md` before enabling destructive
retention or segment collection.

## Import and verify CSV data

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
    b"id,name\n1,Ada\n2,Grace\n",
    source_name="people.csv",
)

assert validate_csv_artifacts(csv_dir, manifest.csv_id).ok
assert prove_original_roundtrip(csv_dir, manifest.csv_id).byte_equivalent
assert export_original_csv(csv_dir, manifest.csv_id).startswith("id,name")
```

The CSV layer stores bounded source and evidence artifacts. It does not create
one storage entry per cell and does not give Semantic IR autonomous commit
authority.

## Rank traces

```python
from staqtapp_tds.spiral import rank_traces

rows = rank_traces(
    ["trace-a", "trace-b"],
    [0.82, 0.95],
    confidences=[0.90, 0.92],
    depths=[2, 3],
    limit=2,
)
```

Trace ranking is deterministic evidence processing. Packed graph admission and
reference path planning do not grant execution or serving authority.

## Observe a running application

```bash
staqtapp-tds-admin status
staqtapp-tds-admin verify --sample
staqtapp-tds-admin serve-panel --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. Keep the Browser on loopback unless an external
deployment supplies its own authenticated transport boundary. The Browser
consumes snapshots; it is not a storage control loop.

## Choose the right surface

| Need | Start with |
|---|---|
| Directory values and persistence | `TDSFileSystem`, `TDSDirectory`, `TDSPersistence` |
| Ordinary failure handling | `TDSResult`, `TDSResultCode` |
| Controlled variables | `addvar`, `editvar`, `lockvar`, `stalkvar` |
| CSV byte/evidence operations | `staqtapp_tds.csv_layer` |
| Generic immutable publication | `staqtapp_tds.generation` |
| Driver validation and review | `staqtapp_tds.drivers` |
| Trace graph/reference planning | `staqtapp_tds.trace_rank` |
| Eaglegate qualification | `staqtapp_tds.eaglegate` |
| Browser and telemetry | `staqtapp_tds.admin`, `staqtapp_tds.telemetry` |

## Before shipping

- Exercise the Python fallback even when native modules are enabled.
- Test recovery and rollback with a copy of real data.
- Keep performance claims tied to a reproducible workload and unchanged output.
- Treat pickle payloads and `.tds` input as trusted data.
- Keep semantic, model, policy, and activation decisions outside storage APIs.

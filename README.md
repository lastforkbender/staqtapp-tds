> **v3.8.0 Phase 1–4 convergence release**
>
> Phase 1 closes the v3.6 Foundation; Phase 2 adds the v3.7 Generation
> Authority and exact CSV consumer; Phase 3 binds the lossless Eaglegate Core
> to that sole authority; Phase 4 adds the canonical packed waypoint/CSR graph
> and an executable, exactly pinned vLLM EAGLE shadow qualification path.
> Eaglegate remains off the production request path with no canary, promotion,
> activation, token-acceptance, or KV-commit authority.

> **v3.6.0 Foundation substrate**
>
> The source line retains fail-closed native ABI/lifecycle admission, strict
> checksum and UTF-8 truth, generation-bound handles, bounded C11 diagnostics,
> immutable packed reads, and exact x86-64/AArch64 semantics.

> **Current security contract**
>
> At-rest encryption is not implemented. Requests using `DirFlags.ENCRYPTED` fail closed instead of storing plaintext. New v2 persistence files require their integrity sidecar. `.tds` input should be treated as trusted until explicit resource-budget hardening is complete. Native extensions are optional and are built only when `STAQTAPP_TDS_BUILD_NATIVE=1` is set.

# Staqtapp-TDS v3.8.0

> **Release status:** v3.8.0 is the current production PyPI release. Publication is permitted only from the exact `v3.8.0` tag after the complete aggregate release gate succeeds. The v3.6 Foundation, v3.7 Generation Authority, and v3.8 Eaglegate/packed-graph transitions are included. The manual credentialed H100 workflow has not been executed and remains required for hardware evidence; Eaglegate remains shadow/target-only and has no production activation authority.

**Temporal Directory System - native-indexed `.tds` storage, controlled variables, trace ranking, CSV evidence operations, semantic review, and centralized observability for AI systems.**

**Programmer start here:** [Staqtapp-TDS Programmer Core API Guide (PDF)](https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf)

## Browser Operations Console — all 19 pages

These are 19 separate 1280×800 viewport captures from the packaged, localhost-only TDS Browser. Each capture was made after selecting the corresponding navigation control against a real release-qualification observer snapshot. Page 07 is the actual CSV Interpole Monitor in its `Monitor Ready` state. The images are shown vertically in Browser navigation order; they are not a stitched Dashboard image or a UI mock. For reliable PyPI rendering, the unchanged captures use immutable absolute HTTPS URLs; release CI verifies every remote PNG byte-for-byte and checks that all 19 URLs survive in the built wheel metadata before publication.

<p align="center"><strong>01 — Dashboard</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/01-dashboard-1280x800.png" alt="Staqtapp-TDS Browser page 01, Dashboard, selected in the navigation" width="100%">
</p>
<p align="center"><strong>02 — Engine Health</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/02-engine-health-1280x800.png" alt="Staqtapp-TDS Browser page 02, Engine Health, selected in the navigation" width="100%">
</p>
<p align="center"><strong>03 — Real-time Metrics</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/03-real-time-metrics-1280x800.png" alt="Staqtapp-TDS Browser page 03, Real-time Metrics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>04 — Transition Timeline</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/04-transition-timeline-1280x800.png" alt="Staqtapp-TDS Browser page 04, Transition Timeline, selected in the navigation" width="100%">
</p>
<p align="center"><strong>05 — Event Ring Monitor</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/05-event-ring-monitor-1280x800.png" alt="Staqtapp-TDS Browser page 05, Event Ring Monitor, selected in the navigation" width="100%">
</p>
<p align="center"><strong>06 — Pressure Diagnostics</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/06-pressure-diagnostics-1280x800.png" alt="Staqtapp-TDS Browser page 06, Pressure Diagnostics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>07 — CSV Interpole</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/07-csv-interpole-1280x800.png" alt="Staqtapp-TDS Browser page 07, the real CSV Interpole Monitor in Monitor Ready state, selected in the navigation" width="100%">
</p>
<p align="center"><strong>08 — Snapshot Explorer</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/08-snapshot-explorer-1280x800.png" alt="Staqtapp-TDS Browser page 08, Snapshot Explorer, selected in the navigation" width="100%">
</p>
<p align="center"><strong>09 — Lock Contention</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/09-lock-contention-1280x800.png" alt="Staqtapp-TDS Browser page 09, Lock Contention, selected in the navigation" width="100%">
</p>
<p align="center"><strong>10 — Workload Analytics</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/10-workload-analytics-1280x800.png" alt="Staqtapp-TDS Browser page 10, Workload Analytics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>11 — Spiral Rank</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/11-spiral-rank-1280x800.png" alt="Staqtapp-TDS Browser page 11, Spiral Rank, selected in the navigation" width="100%">
</p>
<p align="center"><strong>12 — Index Analytics</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/12-index-analytics-1280x800.png" alt="Staqtapp-TDS Browser page 12, Index Analytics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>13 — Storage Analytics</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/13-storage-analytics-1280x800.png" alt="Staqtapp-TDS Browser page 13, Storage Analytics, selected in the navigation" width="100%">
</p>
<p align="center"><strong>14 — Comparative Views</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/14-comparative-views-1280x800.png" alt="Staqtapp-TDS Browser page 14, Comparative Views, selected in the navigation" width="100%">
</p>
<p align="center"><strong>15 — Recovery Planner</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/15-recovery-planner-1280x800.png" alt="Staqtapp-TDS Browser page 15, Recovery Planner, selected in the navigation" width="100%">
</p>
<p align="center"><strong>16 — Policy Proposals</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/16-policy-proposals-1280x800.png" alt="Staqtapp-TDS Browser page 16, Policy Proposals, selected in the navigation" width="100%">
</p>
<p align="center"><strong>17 — Alerts &amp; Events</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/17-alerts-events-1280x800.png" alt="Staqtapp-TDS Browser page 17, Alerts and Events, selected in the navigation" width="100%">
</p>
<p align="center"><strong>18 — Security</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/18-security-1280x800.png" alt="Staqtapp-TDS Browser page 18, Security, selected in the navigation" width="100%">
</p>
<p align="center"><strong>19 — Settings</strong><br>
  <img src="https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/v3.5.3/docs/screenshots/browser_pages/19-settings-1280x800.png" alt="Staqtapp-TDS Browser page 19, Settings, selected in the navigation" width="100%">
</p>

[日本語 README](https://github.com/lastforkbender/staqtapp-tds/blob/main/README_ja.md) | [Complete API Surface Reference PDF](https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) | [Changelog](https://github.com/lastforkbender/staqtapp-tds/blob/main/CHANGELOG.md)

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
| Generation Authority | Immutable content-addressed generations, publication head-root CAS, cross-process reader pins, crash recovery, rollback, retirement, and an exact CSV consumer with an executable content-free audit. |
| Packed waypoint graph | Trace Rank ABI v2 fixed-width generation, provenance, Q15 feature, waypoint, CSR, and edge records with checked bounds, exact source spans, canonical rebuild, SHA-256, and CRC32. |
| Eaglegate | Lossless authority contracts, exactness and adapter labs, Generation-backed ServingEpochs, and a real pinned vLLM EAGLE H100 shadow qualification path that cannot activate production serving. |
| Evidence-bound semantics | TDS records explicit caller declarations and authorized review transitions; it does not silently infer or commit semantic truth. |
| Driver platform | TDDL validation, deterministic bytecode, bounded Driver VM execution, Foundry proposal/test flows, regression evidence, review bundles, and read-only Studio integration. |
| Centralized Browser | One local Browser surface for engine health, pressure, event rings, CSV Interpole, Spiral Rank, snapshots, indexes, storage, recovery, alerts, security, and settings. |
| Observer isolation | Browser, telemetry, diagnostics, and Studio consume snapshots or copied events rather than controlling storage locks. |

## Install

```bash
# Current production PyPI release; includes both UIs
python -m pip install staqtapp-tds==3.8.0

# Launch the main TDS telemetry UI
staqtapp-tds

# Exercise real publication, pinning, CAS, rollback, retirement, and recovery
staqtapp-tds-generation-audit
```

Python 3.10 or newer, NumPy, and PyQt5 are required by the standard installation. Driver Studio is installed automatically, while `staqtapp-tds` launches the main HTML/CSS/JS telemetry Browser. The C extensions remain optional; supported operations retain deterministic Python fallback paths unless a caller explicitly forces native-only execution.

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

The [Programmer Core API Guide](https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf) is the recommended starting point. Its first three pages are the authoritative v3.5.3 supplement for controlled activation, segment GC, and release qualification. The broad guide then organizes direct calls by task and includes implementation snippets for:

- directory and entry operations;
- `.tds` writing, reading, mounting, and integrity behavior;
- variable manipulation and stalk chains;
- text, JSON, serialization, provenance, and result handling;
- telemetry, verification, pressure, recovery, and native diagnostics;
- trace creation and ranking;
- the complete operational CSV call chain;
- Semantic IR candidates, lifecycle transitions, and atomic batches;
- Driver Foundry, VM, Runtime Manager, regression, review, evidence, Browser, and Driver Studio calls.

Use the preserved [v3.5.3 Guaranteed Storage API reference](https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/docs/reference/Programmers_API_Reference.md) for those storage calls. The separate [API Surface Reference PDF](https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) is retained as a historical v3.1.23 Driver/Studio reference; it is not an exhaustive v3.5.3 inventory.

## Safety and authority boundaries

TDS intentionally distinguishes preparation, evidence, review, and authority:

- CSV Semantic IR calls do not autonomously declare semantic truth.
- v3.5.2 admits `proposed`, `validated`, and `contested`; it does not admit `committed` or `superseded`.
- Driver Foundry may validate, compile, audit, test, and submit candidates; it does not sign or activate drivers.
- Driver Studio observes, explains, prepares proposals, and routes review requests; it does not bypass Registry, Review Board, Runtime Manager, or signature policy.
- Browser telemetry is snapshot-based and is not a storage control loop.

## Validation status

The v3.8.0 release completes four explicit boundaries. The v3.7
Generation Authority publishes exact CSV and composite Eaglegate generations
with head-root CAS, cross-process pins, deterministic recovery, rollback, and
retirement. Eaglegate adds a non-widenable target-verification constitution,
candidate-bound exactness/adapter evidence, and a single Generation-backed
ServingEpoch lineage. CANARY and ACTIVE publication are rejected.

Phase 4 also provides `tds-packed-waypoint-csr-v1`, a bounded Trace Rank ABI v2
binary graph with exact immutable source/row bindings and byte-identical
decode/re-encode. The named-runtime adapter dynamically constructs real vLLM
`0.26.0` target-only and EAGLE engines for exact pinned target/draft revisions,
H100 SM90 BF16, standard rejection sampling, batch size one, fixed seeds, and
1/2/3-token plans. Local injected-runtime gates pass; the manual credentialed
H100 run remains required for hardware evidence. No production traffic,
activation, direct KV-tensor equivalence, or in-flight cancellation claim is
made. See `docs/130_v370_Atomic_Generation_Authority.md`,
`docs/126_v380_Eaglegate_Generation_Authority.md`,
`docs/131_v380_Eaglegate_Real_vLLM_Shadow.md`, and
`docs/132_v380_Packed_Waypoint_CSR_Graph.md`.

The v3.6.0 Foundation source closes the native and authority repair train with
a machine-checkable process-state ledger, a deterministic closure report, exact
x86-64/AArch64 semantic parity, fail-closed lifecycle admission, sanitizer and
fuzz qualification, and a deliberately narrow shared-runner no-regression
claim. The named-reference-CPU and universal scaling claims remain false. See
`DEV19_V360_FOUNDATION_CLOSURE_STATUS.txt` and
`docs/129_v360_Foundation_Closure.md`.

The historical v3.5.3 runtime release qualification is complete:

- Phase 10 controlled activation, exact migration proof, and lossless rollback tests;
- Phase 11 GC corruption, publication-window, replacement, interruption, concurrency, and accounting tests;
- a 129-generation incremental/recovery/GC soak;
- Python 3.10–3.14, Windows, macOS, Linux, and native-extension CI gates;
- PEP 517 wheel/sdist, metadata, isolated-install, and source-hygiene gates.

Evidence: 832 passed and 11 skipped in the pure monolithic suite; 843 passed in the native-active monolithic suite; and 157 passed in the overlapping v3.5.3/workflow/Browser/CSV qualification group. Both distribution artifacts passed `twine check`, archive-content inspection, and an isolated wheel activation/rollback/GC smoke test. Exact local, review-branch, tag, and publication details are recorded in `DEV11_RELEASE_QUALIFICATION_STATUS.txt`.

Release `v3.5.3` was published from immutable tag [`v3.5.3`](https://github.com/lastforkbender/staqtapp-tds/tree/v3.5.3) at commit `84c253f2a7d68a20ddcab96e94cc107439ccdd32` after the complete pull-request, merged-`main`, and tag matrices passed. PyPI trusted publishing accepted both the universal wheel and source distribution with attestations. See [PyPI](https://pypi.org/project/staqtapp-tds/3.5.3/), the [publication workflow](https://github.com/lastforkbender/staqtapp-tds/actions/runs/29500270923), and the [GitHub Release](https://github.com/lastforkbender/staqtapp-tds/releases/tag/v3.5.3).

Version `3.5.3.post1` was the corrective package presentation release. It keeps
the qualified storage implementation, assigns the post-release package
identity, admits that identity in existing Semantic IR compatibility records,
and corrects the PyPI long description and source-archive status. Release
hygiene now rejects repository-relative image or document targets before any
distribution can be built.

Version `3.5.3.post2` installs the main telemetry Browser and PyQt5 Driver
Studio with every standard installation. The `staqtapp-tds` command launches
the telemetry Browser; native C extensions remain opt-in. Its publication was
restricted to the exact annotated `v3.5.3.post2` tag after the complete
aggregate release gate succeeded.

Version `3.8.0` carries the Phase 1–4 convergence while keeping Eaglegate's
production boundary unchanged. Its release path additionally validates the
PyPI long description from the built wheel and fetches every immutable Browser
screenshot URL to require the expected PNG bytes before trusted publication.

## Repository map

```text
src/staqtapp_tds/          core storage, persistence, telemetry, native management
src/staqtapp_tds/generation/ generic immutable generations, CAS, pinning, recovery
src/staqtapp_tds/eaglegate/ lossless core, ServingEpoch authority, real shadow adapter
src/staqtapp_tds/trace_rank/ ABI v2 contracts and packed waypoint/CSR graph
src/staqtapp_tds/csv_layer CSV evidence, transactions, Interpole, Semantic IR
src/staqtapp_tds/drivers/  TDDL, bytecode, VM, Foundry, review and evidence
src/staqtapp_tds/studio_pyqt5/ Driver Studio cockpit
src/staqtapp_tds/admin/    centralized Browser and local admin control
examples/                  runnable examples
docs/                      architecture and release contract documents
tds_api_docs/              programmer guide and historical API-surface PDF
```

## License

See [LICENSE](https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/LICENSE).

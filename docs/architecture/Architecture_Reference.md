# TDS Architecture Reference

This document describes the current architecture. Release history belongs in
`CHANGELOG.md`; implementation details that are already enforced by code and
tests are not repeated here as phase or status ledgers.

## Core boundary

TDS stores and reports mechanical facts. It does not grant semantic, model,
policy, serving, or release authority.

```text
Application
    |
    v
TDSFileSystem / TDSDirectory / TDSResult
    |
    +-- variables, text, JSON, binary values, provenance
    +-- CSV evidence and explicit semantic-review records
    +-- Driver, Trace Rank, Generation, and Eaglegate integration
    |
    v
EntryIndex / persistence / optional native kernels
    |
    +-- copied counters and bounded events
    v
Telemetry snapshots -> CLI / Browser / Studio observers
```

The storage path produces bounded counters and events. Diagnostics and user
interfaces consume copies; they do not own storage objects or control storage
locks.

## Core storage

`TDSFileSystem` owns the in-memory directory hierarchy and `TDSDirectory`
provides the public value operations. Serialization remains above the index so
the index maps names to handles without knowing Python object policy.

`EntryIndex` selects an optional native backend when it is available and
compatible, otherwise it uses the deterministic Python backend. The public
directory API does not change with backend selection. Native extensions are an
acceleration layer, not an authority layer.

`TDSPersistence` writes `.tds` snapshots and their metadata sidecars. Writers
assemble a stable snapshot, validate layout and payload identities, and publish
through atomic replacement. Readers validate headers, slot bounds, sidecar
identity, codecs, and content hashes before returning values. New format-v2
files require their integrity sidecar.

## Recovery and generations

Recovery is explicit and bounded. It verifies a requested generation or
snapshot before use, reports typed failures, and does not silently delete
rejected evidence.

The repository contains two related generation surfaces:

- Guaranteed Storage provides opt-in immutable segments, qualification,
  controlled activation, rollback, retention, and garbage collection around
  the established storage format.
- Generation Authority provides generic immutable payload generations,
  canonical identities, publication compare-and-swap, reader pins, recovery,
  rollback, and retirement for consumers such as CSV and Eaglegate.

Neither surface changes authority merely because bytes were written. Callers
must use the explicit qualification, publication, activation, or rollback API
appropriate to the subsystem.

## CSV and semantic review

`staqtapp_tds.csv_layer` preserves original CSV bytes and records dialect,
logical row offsets, anchors, scan results, transactions, storage bindings, and
replay evidence. Optional native scanning performs bounded mechanical work and
retains a Python reference path.

Semantic IR records are proposals and review transitions over explicit CSV
evidence. They do not infer semantic truth and cannot bypass the admitted
authorization transitions.

## Drivers and Studio

`staqtapp_tds.drivers` contains TDDL validation, deterministic bytecode, the
bounded Driver VM, Foundry workflows, registry/signature gates, regression
evidence, and review objects. `staqtapp_tds.studio_pyqt5` presents those records
and prepares review intent.

Foundry and Studio do not sign or activate drivers. Runtime Manager and the
registry remain the enforcement boundary.

## Trace Rank and Eaglegate

`staqtapp_tds.trace_rank` admits bounded packed waypoint/CSR graphs and provides
deterministic reference planning and replay receipts. Graph admission does not
create legal-edge, execution, or serving authority.

`staqtapp_tds.eaglegate` provides lossless contracts, exactness checks, adapter
conformance, Generation-backed ServingEpoch candidates, and a target-only vLLM
shadow path. It does not grant production traffic, canary, promotion,
activation, token-acceptance, or KV-commit authority.

## Observation path

`TelemetryManager`, the native diagnostics ring, workspace snapshots, the
Browser, and Driver Studio are observers. The intended path is one-way:

```text
engine counters/events
        -> telemetry publisher
        -> immutable snapshot
        -> Browser / CLI / Studio
```

If a bounded diagnostic ring fills, diagnostic evidence may be dropped and the
drop counter increases; storage work continues. Deep verification remains an
explicit operator action rather than a polling side effect.

## Security posture

- At-rest encryption is not implemented. `DirFlags.ENCRYPTED` fails closed.
- `.tds` input is trusted input until explicit resource-budget hardening is
  complete.
- The Browser is localhost-only by default and configuration actions retain
  same-origin and CSRF enforcement.
- Native modules are optional and require explicit build activation.
- Pickle-compatible lanes should be used only with trusted data.

## Source map

| Area | Primary source |
|---|---|
| Filesystem and persistence | `src/staqtapp_tds/tds_filesystem.py`, `tds_persistence.py` |
| Index and native boundary | `src/staqtapp_tds/index.py`, `backends/`, `_native_index.c` |
| Guaranteed Storage | `generation_store.py`, `segment_store.py`, `storage_activation.py` |
| Generation Authority | `src/staqtapp_tds/generation/` |
| CSV | `src/staqtapp_tds/csv_layer/` |
| Drivers and Studio | `src/staqtapp_tds/drivers/`, `studio_pyqt5/` |
| Trace Rank and Eaglegate | `src/staqtapp_tds/trace_rank/`, `eaglegate/` |
| Browser and telemetry | `src/staqtapp_tds/admin/`, `telemetry.py`, `native/diagnostics.py` |

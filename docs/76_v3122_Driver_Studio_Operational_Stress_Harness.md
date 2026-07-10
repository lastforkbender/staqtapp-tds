# v3.1.22 Driver Studio Operational Stress Harness

v3.1.22 adds a deterministic, headless operational stress harness for the completed Driver Studio runtime and Browser-style observer path.

The purpose is to prove that TDS can keep operating while observer surfaces are under pressure:

```text
.tds operations / telemetry snapshots
        │
        ├── Browser-style AdminControl.status() polling
        │
        └── Driver Studio bounded live runtime polling
```

The harness is evidence-only. It does not approve, reject, quarantine, sign, activate, execute trusted drivers as authority, mutate Registry state, write storage through Studio, store private keys, or bypass Runtime Manager / Foundry / Review Board / Registry policy.

## Added public concepts

```text
staqtapp_tds.studio_pyqt5.operational_stress
StudioOperationalStressHarness
StudioOperationalStressReport
StudioOperationalStressObservation
StudioOperationalStressStatus
studio_operational_stress_capability_matrix()
```

## Stress coverage

The harness currently covers four non-authoritative pressure paths:

1. Browser-style `AdminControl.status()` polling and JSON status emission.
2. Studio live-event overflow against a bounded `StudioLivePanelRuntime` stream.
3. Manual Builder form payload normalization with unusual Qt-style values.
4. `.tds` atomic persistence reader/writer checks with existing reader stability and fresh-reader visibility.

Event overflow is not treated as a failure when it is explicitly reported. The pass condition is that `dropped_event_count`, `retained_cursor_floor`, and `event_retention_gap` make event loss visible while the current immutable snapshot remains usable.

## Result shape

The harness returns `StudioOperationalStressReport`, not an exception-oriented halt path.

Important report fields:

```text
ok
status
reason
iterations
browser_poll_count
studio_event_count
dropped_event_count
event_retention_gap
tds_persistence_checks
observations
warnings
metrics
capability_matrix
```

The report exposes `signal_payload()` so CI, Qt, browser tooling, and AI stress systems can consume the result as JSON-friendly evidence.

## Authority boundary

The capability matrix explicitly denies authority expansion:

```text
stress_harness_is_authority = False
stress_harness_mutates_registry = False
auto_runs_trusted_drivers = False
approve_driver = False
reject_driver = False
quarantine_driver = False
sign_driver = False
activate_driver = False
run_driver_vm = False
write_storage = False
mutate_registry = False
store_private_keys = False
bypass_policy = False
```

This keeps v3.1.22 aligned with the established TDS rule:

```text
Storage owns data.
Runtime Manager gates execution.
Registry owns trust.
Studio and Browser observe copied evidence and snapshots.
Stress tooling increases confidence, not authority.
```

## API PDF repository location

The canonical generated API reference PDF is stored in the repository under:

```text
tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf
```

Both `README.md` and `README_ja.md` link to this PDF and to each other.

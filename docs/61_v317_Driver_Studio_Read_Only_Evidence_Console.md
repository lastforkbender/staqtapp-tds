# v3.1.7 Driver Studio Read-Only Evidence Console

v3.1.7 adds the first Driver Studio panel-model foundation. It is deliberately
non-GUI and PyQt5-neutral: the new objects consume v3.1.6 evidence bundles and
produce immutable panel snapshots that a future PyQt5 Driver Studio can render
as a rich, browser-like cockpit.

The Studio observes trust before it influences trust.

```text
DriverRegressionHarness produces fixture evidence
DriverBatchReviewBoard records admin review decisions
EvidenceBundleExporter freezes the trust chain
DriverStudioReadOnlyConsole renders read-only panel snapshots
Registry still owns approval, signing and activation authority
```

## Public API

The new public types are exported from `staqtapp_tds.drivers`:

- `DriverStudioReadOnlyConsole`
- `DriverStudioConsoleSnapshot`
- `DriverStudioPanelSnapshot`
- `DriverStudioQueueItem`
- `DriverStudioRiskCard`
- `DriverStudioEventRow`
- `StudioPanelKind`
- `StudioPanelStatus`
- `StudioConsoleStatus`
- `studio_readonly_capability_matrix()`

The existing v3.0.9 quick-test API remains available:

- `DriverStudioSession`
- `DriverStudioQuickTestReport`
- `StudioGate`
- `StudioGateResult`
- `run_studio_quick_test()`
- `studio_instruction_reference()`

## Why This Layer Is Non-GUI

The first Studio hardening target is not window layout. It is the read-only data
contract that GUI panels will render. Keeping v3.1.7 PyQt5-neutral makes the
panel model easy to test in CI, prevents GUI dependencies from entering the core
package, and lets the future app remain a presentation layer rather than a trust
authority.

## Panel Model

`DriverStudioReadOnlyConsole.open_bundle()` accepts a `DriverEvidenceBundle`, a
canonical bundle mapping, or a JSON export string. It verifies bundle integrity
through `EvidenceBundleExporter.verify_bundle()` and then returns a
`DriverStudioConsoleSnapshot` with stable panel identifiers:

- `driver_queue`
- `evidence_bundle`
- `audit_trail`
- `fixture_replay`
- `risk_card`
- `registry_state`
- `export_integrity`
- `event_console`

Each panel is a `DriverStudioPanelSnapshot` containing:

- panel kind
- panel status
- title
- summary
- rows
- metrics
- warnings

These payloads are intentionally simple, JSON-compatible structures so a PyQt5
view model can map them into tables, cards, timelines, inspectors, and bottom
console output without re-running evidence logic.

## Read-Only Authority Boundary

`DriverStudioReadOnlyConsole.capability_matrix()` is intended for display in the
future Studio. It can:

- load evidence bundles
- render driver queues
- render evidence bundle metadata
- render audit trails
- render fixture replay summaries
- render risk cards
- render registry state observations
- verify export integrity
- display public signature metadata

It cannot:

- approve drivers
- reject drivers
- call registry approval
- sign drivers
- attach signatures
- activate drivers
- edit TDDL
- edit bytecode
- run the Driver VM
- write storage
- execute Python
- mutate the Registry
- bypass policy
- include private keys

This keeps the future Driver Studio feature-rich without letting the GUI become
an authority owner.

## Risk Cards

`DriverStudioRiskCard` converts evidence bundle records into human-readable
review summaries. A card records:

- driver id
- risk level
- decision status
- summary
- reasons
- blocked authority
- fault codes

The risk card is not an approval engine. It explains why a driver appears clean,
held, quarantined, rejected, or registry-rejected based on exported evidence.

## Integrity Handling

If a bundle verifies, the console status becomes `ready` or `partial` depending
on the bundle status. If a JSON/mapping export has been tampered with, the
console reports `integrity_mismatched`, the export-integrity panel carries a
warning, and the capability matrix remains read-only.

The console does not repair, approve, sign, or activate a mismatched bundle. It
only makes the mismatch visible.

## Example

```python
from staqtapp_tds.drivers import DriverStudioReadOnlyConsole, StudioPanelKind

console = DriverStudioReadOnlyConsole()
snapshot = console.open_bundle(evidence_bundle)

queue_panel = snapshot.panel(StudioPanelKind.DRIVER_QUEUE)
risk_panel = snapshot.panel("risk_card")

assert snapshot.capability_matrix["sign_driver"] is False
assert snapshot.capability_matrix["activate_driver"] is False
```

## Studio Direction

v3.1.7 is the safe bridge from backend evidence maturity to the future PyQt5
Driver Studio. The app can now be designed around persistent panels rather than
popup-heavy workflows:

```text
Driver Evidence Queue | Evidence Workspace | Risk/Registry Inspector
Bottom Event Console  | Export Integrity   | Audit Timeline
```

The next Studio step can safely add GUI rendering on top of these snapshots, or
add controlled review-action submission later. Approval, signing, activation,
Driver VM execution, and Registry authority remain outside this read-only layer.

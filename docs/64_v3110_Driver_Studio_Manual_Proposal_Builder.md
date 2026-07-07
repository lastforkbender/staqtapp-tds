# v3.1.10 Driver Studio Manual Proposal Builder

v3.1.10 adds a GUI-neutral manual proposal builder for the Driver Studio cockpit. It is designed for a future visual PyQt5 panel where an operator can describe a driver task, preview the generated TDDL, and send the proposal through Driver Foundry without giving Studio trust authority.

## Boundary

```text
Driver Studio Cockpit
   |
   v
Manual Driver Builder Panel
   |
   v
StudioManualDriverTask
   |
   v
Deterministic TDDL proposal source
   |
   v
DriverFoundry.propose_driver()
   |
   v
validate / compile / audit / optional fixture test
```

The builder may create proposal source and route it to Foundry. It may not approve, reject, quarantine, call Registry approval directly, submit registry candidates, sign, attach signatures, activate, execute arbitrary Python, write storage, mutate registry state, edit active bytecode, store private keys, or bypass policy.

## Added API

- `DriverStudioManualProposalBuilder`
- `StudioManualDriverTask`
- `StudioManualProposalPreview`
- `StudioManualProposalReport`
- `StudioManualProposalStatus`
- `studio_manual_builder_capability_matrix()`

The optional PyQt5 bridge also exposes:

- `StudioQtBridge.preview_manual_driver_task()`
- `StudioQtBridge.propose_manual_driver_task()`

## Cockpit Panel

`StudioPanelKind.MANUAL_DRIVER_BUILDER` adds a `Manual Driver Builder` panel descriptor with the `proposal_workbench` surface. The descriptor uses custom SVG iconography consistent with the TDS Browser and Driver Studio shell theme.

The panel is intentionally marked as not read-only because it accepts human task fields; however, the generated result remains a proposal and cannot mutate trust state.

## Example

```python
from staqtapp_tds.drivers import DriverStudioManualProposalBuilder, StudioManualDriverTask

builder = DriverStudioManualProposalBuilder()
task = StudioManualDriverTask(
    driver_id="ManualPolicyDriver",
    description="Manual cockpit proposal for policy-routing manifests",
    semantic_query="policy routing",
    emit_limit=2,
)

preview = builder.preview_task(task)
assert preview.ok
assert preview.source_hash.startswith("sha256:")

report = builder.propose_task(task, fixtures={"records": []})
assert report.foundry_result is not None
```

## Authority Matrix

`studio_manual_builder_capability_matrix()` reports positive proposal capabilities and explicit trust denials:

- can render manual builder
- can accept human task fields
- can generate deterministic TDDL source
- can route to Foundry
- can validate, compile, audit, and fixture-test through Foundry
- cannot submit candidates
- cannot approve/sign/activate
- cannot mutate Registry or storage
- cannot store private keys
- cannot bypass policy

## Testing

v3.1.10 adds tests for deterministic TDDL generation, unsafe input rejection before Foundry routing, Foundry-backed fixture testing, bridge hydration, and trust-boundary preservation.

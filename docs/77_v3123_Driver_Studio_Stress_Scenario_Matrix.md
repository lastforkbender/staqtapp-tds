# v3.1.23 Driver Studio Stress Scenario Matrix

v3.1.23 extends the v3.1.22 operational stress harness with a deterministic scenario matrix for named stress paths.

The purpose is to turn individual operational stress checks into a reusable proof matrix:

```text
Browser polling scenario
Studio bounded-event overflow scenario
Manual Builder payload scenario
.tds persistence atomicity scenario
Combined Browser + Studio + .tds scenario
Authority-boundary denial scenario
```

The scenario matrix is evidence-only. It does not approve, reject, quarantine, sign, activate, execute trusted drivers as authority, mutate Registry state, write storage through Studio, store private keys, or bypass Runtime Manager / Foundry / Review Board policy.

## Added public concepts

```text
StudioOperationalStressScenario
StudioOperationalStressScenarioResult
StudioOperationalStressScenarioMatrix
DEFAULT_OPERATIONAL_STRESS_SCENARIOS
StudioOperationalStressHarness.run_scenario(...)
StudioOperationalStressHarness.run_scenario_matrix(...)
```

## Default scenario matrix

The default scenario sequence is:

```text
BROWSER_POLLING
STUDIO_EVENT_OVERFLOW
MANUAL_BUILDER_PAYLOADS
TDS_PERSISTENCE_ATOMICITY
COMBINED_BROWSER_STUDIO_TDS
AUTHORITY_BOUNDARY_DENIAL
```

The combined scenario is the most important operational proof path. It exercises Browser-style `AdminControl.status()` polling, Studio live-event overflow, Manual Builder payload safety, and `.tds` atomic persistence checks together through one non-authoritative report surface.

## Result shape

`StudioOperationalStressScenarioResult` records one named scenario:

```text
scenario
ok
status
detail
observations
warnings
metrics
authority
```

`StudioOperationalStressScenarioMatrix` records the full matrix:

```text
ok
status
reason
iterations
results
warnings
metrics
capability_matrix
```

Both expose `signal_payload()` for JSON-friendly CI, Studio, Browser, and AI stress-tooling integration.

## Authority-boundary scenario

The explicit authority-denial scenario verifies that stress tooling does not gain trust authority:

```text
stress_harness_is_authority = False
stress_harness_mutates_registry = False
auto_runs_trusted_drivers = False
approve_driver = False
reject_driver = False
quarantine_driver = False
call_registry_approve = False
sign_driver = False
attach_signature = False
activate_driver = False
run_driver_vm = False
write_storage = False
execute_python = False
mutate_registry = False
store_private_keys = False
bypass_policy = False
```

## Design rule

```text
Stress scenarios prove operational confidence.
They do not widen Studio, Browser, Runtime Manager, Foundry, Registry, or storage authority.
```

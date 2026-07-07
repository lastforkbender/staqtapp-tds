# v3.1.3 Runtime Manager Evidence Hardening

TDS v3.1.3 matures the Driver VM runtime by adding a production-facing **Driver Runtime Manager** above the low-level `DriverVMRuntime`.

The Runtime Manager is not a UI and is not a trust-authority shortcut. It is the execution gate that turns a compiled `.tdd` package and an in-memory record snapshot into approval-grade evidence for later Runtime Manager, Admin Review, Driver Studio, and AI Foundry workflows.

## Class A boundary

The Runtime Manager preserves the same core separation established in the VM runtime:

```text
Native Storage Engine
  owns bytes, indexes, slots, persistence, locks

Driver Runtime Manager
  owns policy gates, evidence capture, and execution sessions

Driver VM Runtime
  owns deterministic bytecode execution against snapshots only
```

The manager never receives storage handles and never writes storage. It receives caller-supplied immutable-style snapshots:

```python
{"records": [mapping, ...]}
```

The low-level runtime still deep-copies inputs. v3.1.3 adds manager-level snapshot hashing and preservation checks.

## New public API

```python
from staqtapp_tds.drivers import DriverRuntimeManager, RuntimeManagerPolicy

manager = DriverRuntimeManager(policy=RuntimeManagerPolicy())
evidence = manager.execute_package(package, {"records": records})
```

Primary exports:

```text
DriverRuntimeManager
DriverExecutionEvidence
RuntimeManagerPolicy
RuntimeManagerStatus
RuntimeManagerFault
runtime_manager_capability_matrix
```

## DriverExecutionEvidence

`DriverExecutionEvidence` is the approval-grade evidence bundle for a single managed execution.

It includes:

```text
ok
status
reason
driver_id
driver_version
driver_class
package_hash
source_hash
snapshot_hash
evidence_hash
session_id
registry_state
signature_verdict
vm_result
faults
capability_report
policy_report
metrics
trace_complete
deterministic
recommendation
```

This is intentionally richer than `DriverVMResult` because it combines runtime output with the manager-level policy context needed for future admin review.

## RuntimeManagerPolicy

Policy gates include:

```text
max_cost
max_instructions
max_snapshot_records
allowed_driver_classes
allowed_capabilities
denied_capabilities
require_registry_active
require_signature_accept
require_trace_complete
```

By default, the manager allows direct controlled execution for development/testing, but still denies dangerous capabilities such as:

```text
storage.write
python.exec
policy.bypass
external.io
```

For production-style execution, use:

```python
RuntimeManagerPolicy(
    require_registry_active=True,
    require_signature_accept=True,
)
```

## Registry and signature gate

When `require_registry_active=True`, the manager rejects packages unless the registry record is active.

When `require_signature_accept=True`, the manager evaluates the registry signature policy and requires an accepted signature.

This keeps the policy line explicit:

```text
Foundry may create candidates.
Runtime Manager may execute approved/trusted packages.
Registry/Admin remains the trust authority.
```

## Evidence hashes

The manager produces deterministic hashes:

```text
snapshot_hash  hash of the normalized input records
evidence_hash  hash of package, snapshot, VM status, faults, metrics, policy reports
session_id      deterministic execution session key from package_hash + snapshot_hash
```

This makes future replay, review, and batch comparison practical.

## Non-halting behavior

Like `DriverVMResult`, manager execution is result-first. Expected package, input, policy, registry, signature, and runtime faults return structured evidence instead of escaping.

Examples:

```text
PACKAGE_REJECTED
POLICY_REJECTED
REGISTRY_REJECTED
SIGNATURE_REJECTED
INPUT_REJECTED
RUNTIME_FAULTED
INTERNAL_ERROR
EXECUTED
```

## Test coverage

v3.1.3 adds tests proving:

```text
Runtime Manager capability matrix denies trust authority and storage writes
valid package execution returns approval-grade evidence
evidence hashes are deterministic for same package/snapshot
caller snapshots are not mutated
tampered package hashes are rejected
explicitly denied capabilities are rejected before VM execution
driver classes outside policy are rejected
non-active registry candidates are rejected when active trust is required
active signed drivers are accepted when registry/signature trust is required
bad active signatures are rejected
bad fixtures return INPUT_REJECTED evidence
runtime faults are preserved as evidence
```

## Why this comes before admin batch approval

Admin approval should be based on evidence, not just metadata. v3.1.3 prepares that layer. A future batch review can group many drivers together, but each driver will still carry its own independent `DriverExecutionEvidence` bundle.

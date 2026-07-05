# v3.1.0 Driver VM Runtime

TDS v3.1.0 introduces the first executable Driver VM runtime for validated TDDL bytecode packages.

This is intentionally a narrow runtime, not a general-purpose language VM. It executes only the already validated v1 safe opcode set:

```text
SCAN
READ
MATCH
EXTRACT
SCORE
TRACE
EMIT
HALT
```

## Runtime boundary

The Driver VM remains separate from the Native Storage Engine.

The runtime receives explicit in-memory record snapshots:

```python
result = vm.execute({"records": records})
```

It does not receive native storage handles, slot references, locks, table pointers, file descriptors, or direct storage-engine mutation access.

## Runtime loading

A bytecode package must pass the existing contract chain before execution:

```text
TDDL source
  -> grammar validation
  -> bytecode package
  -> package hash validation
  -> VM contract audit
  -> DriverVMRuntime.load()
  -> DriverVMRuntime.execute()
```

## Result shape

Runtime execution returns `VMExecutionResult`:

```text
ok
state
reason
trace
emitted
trace_events
cost_used
```

## Skeleton vs runtime

`DriverVMSkeleton` remains non-executing and is still useful for Studio lessons, audit-only paths, and registry-gate checks.

`DriverVMRuntime` is the executable v3.1.0 path.

## Safety posture

- Unsupported bytecode is rejected before load.
- Invalid instruction classes are rejected by the VM contract audit.
- Missing required capabilities fail closed.
- Runtime cost budgets are enforced.
- Malformed runtime inputs return rejected results.
- Execution is deterministic and bounded.

This release marks the transition from v3.0.x language foundation to v3.1.x execution foundation.

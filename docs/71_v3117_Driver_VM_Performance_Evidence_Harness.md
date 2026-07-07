# v3.1.17 Driver VM Performance Evidence Harness

v3.1.17 adds an opt-in Driver VM Performance Evidence Harness for controlled Python Driver VM timing, Runtime Manager overhead comparison, deterministic result-hash checks, and future native C Driver VM parity targets.

The harness is deliberately outside the normal VM hot path:

```text
DriverVMRuntime.execute()
  -> no automatic benchmark loop
  -> no per-record timer hooks
  -> no profiling instrumentation
  -> unchanged straight Python runtime behavior

DriverVMPerformanceHarness.run_package(...)
  -> explicit controlled repetitions
  -> direct Python VM timing
  -> optional Runtime Manager timing
  -> optional native C backend slot
  -> performance evidence report
```

## Added public objects

- `DriverVMPerformanceHarness`
- `DriverVMPerformancePolicy`
- `DriverVMPerformanceReport`
- `DriverVMPerformanceRun`
- `DriverVMPerformanceSummary`
- `DriverVMPerformanceComparison`
- `DriverVMPerformanceStatus`
- `DriverVMPerformanceBackend`
- `driver_vm_performance_capability_matrix()`
- `driver_vm_performance_enabled()`

## Evidence generated

The report includes:

- package identity
- snapshot hash
- performance evidence hash
- per-run elapsed nanoseconds
- records/sec
- emitted/sec
- cost/sec
- result hash
- deterministic summary per backend
- Python VM vs Runtime Manager parity comparison
- optional Python VM vs native C VM parity comparison
- authority capability report

## Native C conversion value

The harness makes future native conversion measurable before native code becomes active:

```text
Python Driver VM = reference result
Native C Driver VM = candidate accelerator
Performance Harness = parity and speed evidence
Runtime Manager = unchanged policy/evidence gate
Registry = unchanged trust authority
Studio = future observer of performance evidence only
```

A native candidate must return the same `DriverVMResult` shape and preserve result parity before performance gains matter.

## Boundary rules

The harness does not:

- approve drivers
- reject drivers as authority
- quarantine drivers
- sign drivers
- activate drivers
- mutate Registry state
- write storage
- store private keys
- bypass Runtime Manager policy
- run automatically inside `DriverVMRuntime.execute()`
- run automatically inside `DriverRuntimeManager.execute_package()`

## Environment helper

`driver_vm_performance_enabled()` reads `STAQTAPP_TDS_DRIVER_VM_PERF`, but this helper is passive. It never auto-runs the harness. Callers must still explicitly construct and call `DriverVMPerformanceHarness`.

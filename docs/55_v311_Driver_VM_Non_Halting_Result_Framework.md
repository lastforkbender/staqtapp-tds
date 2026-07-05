# v3.1.1 Driver VM Non-Halting Result Framework

TDS v3.1.1 adds a Driver VM-specific non-halting execution envelope:
`DriverVMResult`.

The design follows the same Class A principle as `TDSResult`: expected runtime
conditions must not halt the caller. A driver may halt normally, fault, reject
input, exceed budget, or hit unsupported runtime semantics, but `execute()`
returns structured evidence instead of throwing expected VM exceptions into the
host process.

## Core rule

```text
Driver may fail.
Driver VM may stop that driver.
Host process must not fail.
Storage engine must not be touched.
Trace must explain what happened.
```

## Public result types

### `VMStatus`

`VMStatus` describes the execution outcome:

```text
not_loaded
loaded
halted
faulted
rejected
input_rejected
policy_rejected
budget_exceeded
instruction_limit_exceeded
execution_disabled
internal_error
```

The normal successful terminal status is:

```text
VMStatus.HALTED
```

The historical `VMState.EXECUTED` state remains available for compatibility.

### `VMFault`

`VMFault` carries a structured, Studio-friendly fault:

```python
VMFault(
    code="vm.adapter.unsupported",
    message="EXTRACT adapter execution is not runtime-supported yet: extractor.future.v1",
    instruction_pointer=2,
    instruction="EXTRACT",
    severity="error",
    recoverable=False,
)
```

### `DriverVMContext`

`DriverVMContext` captures compact execution context:

```text
driver_id
driver_version
driver_class
package_hash
instruction_pointer
instruction
cost_used
max_cost
records_seen
current_count
emitted_count
```

This is intended for Runtime Manager diagnostics and the future PyQt5 Driver
Studio execution panel.

### `DriverVMResult`

`DriverVMResult` is the VM-specific result envelope:

```text
ok
status
reason
state
trace
emitted
trace_events
faults
metrics
context
cost_used
package_hash
driver_id
driver_version
partial
```

`VMExecutionResult` remains as a backwards-compatible public alias.

## Non-halting execution behavior

`DriverVMRuntime.execute()` now returns structured results for expected runtime
conditions:

| Condition | Result status |
|---|---|
| No loaded package | `VMStatus.NOT_LOADED` |
| Bad `inputs.records` | `VMStatus.INPUT_REJECTED` |
| Runtime budget exceeded | `VMStatus.BUDGET_EXCEEDED` |
| Unsupported runtime operand | `VMStatus.FAULTED` |
| Unsupported adapter execution | `VMStatus.FAULTED` |
| Defensive unexpected handler error | `VMStatus.INTERNAL_ERROR` |
| Normal `HALT` | `VMStatus.HALTED` |

Package load remains a strict validation boundary. Invalid bytecode, bad package
hashes, unsupported opcodes, and contract audit failures still reject during
`load()`.

## Extended syntax/runtime parity

v3.1.1 also tightens several runtime semantics:

- `MATCH field=...` now requires at least one predicate operand before bytecode.
- `MATCH regex_limited=` has deterministic runtime behavior.
- `MATCH range=[low, high]` has deterministic numeric runtime behavior.
- `SCAN kind/include/exclude` return structured `FAULTED` results until runtime
  semantics are explicitly implemented.
- `EXTRACT using=` returns a structured unsupported-adapter fault until adapter
  execution exists.
- `SCORE by/boost/penalty` return structured unsupported-operand faults until
  policy scoring semantics are explicitly implemented.
- `EMIT mode="proposal"` faults until the future evolution engine is fitted.

This prevents accepted syntax from being silently ignored.

## Immutability and storage boundary

The runtime deep-copies caller-provided record snapshots before execution and
returns copied emitted results. VM execution does not mutate caller records.

A regression test also verifies that the Driver VM runtime module does not
import storage-engine internals such as `TDSFileSystem`, `EntryIndex`, native
index modules, or persistence internals.

## Test coverage added

v3.1.1 adds tests for:

- `DriverVMResult` success shape and context.
- unloaded execution returning `NOT_LOADED`.
- bad records input returning `INPUT_REJECTED`.
- runtime budget overflow returning `BUDGET_EXCEEDED`.
- unsupported runtime operands returning `FAULTED`.
- unsupported adapter execution returning `FAULTED`.
- regex-limited and range predicate runtime semantics.
- `MATCH field` without predicate rejected before bytecode.
- input snapshot immutability.
- expected execute faults not raising.
- internal handler exceptions contained as `INTERNAL_ERROR`.
- storage-boundary import regression.

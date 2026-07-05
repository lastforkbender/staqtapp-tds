# v3.0.8 VM Contract Audit + Driver VM Skeleton

v3.0.8 adds the final non-executing safety layer before the future native TDS Driver VM.

This release does **not** execute TDDL bytecode. It establishes a fail-closed VM contract audit and a native-facing VM loader skeleton so future native execution can be built against stable, tested semantics.

## Added

- `VMInstructionContract`
- `vm_contract_table()`
- `audit_vm_contract()`
- `DriverVMSkeleton`
- `VMLoadedPackage`
- `VMExecutionResult`
- `VMState`

## Contract Table

Every bytecode instruction now has VM-readiness metadata:

- opcode
- execution cost
- deterministic flag
- allowed driver classes
- required capability, if applicable
- adapter/proposal/branch flags

The current bytecode v1 VM contract covers:

| Instruction | Opcode | Role |
| --- | ---: | --- |
| SCAN | `0x01` | Bounded `.tds`/registry scanning |
| READ | `0x02` | Read validated metadata targets |
| MATCH | `0x03` | Field or adapter-backed predicate match |
| EXTRACT | `0x04` | Structured extraction |
| SCORE | `0x05` | Deterministic score/ranking step |
| EMIT | `0x06` | Emit bounded result set |
| TRACE | `0x07` | Emit trace evidence |
| HALT | `0x08` | Deterministic termination |

## Fail-Closed Loader

`DriverVMSkeleton.load(package)` validates:

- bytecode package hash
- bytecode magic/version
- opcode/name consistency
- exactly one final `HALT`
- instruction contract availability
- driver-class instruction permissions
- required capabilities
- instruction count budget
- instruction cost budget

If any check fails, the VM skeleton enters `REJECTED` state and loads nothing.

## No Execution Yet

Calling `execute()` after a valid load returns a structured disabled result:

```text
ok = false
state = execution_disabled
reason = driver bytecode execution is intentionally disabled in v3.0.8 VM skeleton
```

This prevents the VM skeleton from becoming an accidental runtime before the native execution engine is implemented.

## Storage Engine Separation

The Driver VM skeleton does not access the Native Storage Engine internals. It only validates compiled driver artifacts and prepares the contract for a separate native VM subsystem.

## Test Coverage

v3.0.8 adds regression tests for:

- complete VM metadata table
- valid package audit
- valid package load
- class-based instruction denial
- missing required capability denial
- tampered package rejection
- unknown/opcode mismatch rejection
- disabled execution behavior
- instruction budget fail-closed behavior

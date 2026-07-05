# v3.1.2 Driver Foundry API

TDS v3.1.2 introduces the **Driver Foundry API**, a survivable API seam for AI-assisted driver generation. The Foundry is allowed to build, validate, audit, test, and submit driver candidates, but it is not allowed to approve, sign, activate, bypass policy, write storage, or execute arbitrary Python.

This makes rapid AI-assisted driver development possible without weakening the Class A trust boundary.

```text
AI Driver Agent
      ↓
DriverFoundry
      ↓
validate / compile / audit / test
      ↓
DriverVMResult evidence
      ↓
Registry candidate only
      ↓
Human / policy approval and signing outside Foundry
```

## Public API

```python
from staqtapp_tds.drivers import DriverFoundry

foundry = DriverFoundry()

validated = foundry.validate_driver(source)
built = foundry.compile_driver(source)
audited = foundry.audit_driver(built.package)
tested = foundry.test_driver(built.package, {"records": records})
submitted = foundry.submit_candidate(built.package, registry=registry, vm_result=tested.vm_result)
```

Every method returns `DriverFoundryResult` for expected failure paths.

## Result objects

### `DriverFoundryResult`

Carries:

- `ok`
- `stage`
- `status`
- `reason`
- `context`
- `faults`
- `program`
- `package`
- `vm_result`
- `registry_state`
- `metrics`
- `repair_hints`

### `DriverFoundryContext`

Carries:

- stage
- driver ID
- driver version
- driver class
- source hash
- package hash
- instruction count
- capability count
- adapter count
- registry state
- VM status

### `FoundryFault`

Carries:

- code
- message
- stage
- severity
- recoverable flag

## Authority boundary

The Foundry can:

```text
validate_driver      yes
compile_driver       yes
audit_driver         yes
test_driver          yes
submit_candidate     yes, policy permitting
```

The Foundry cannot:

```text
approve_driver       no
sign_driver          no
activate_driver      no
write_storage        no
execute_python       no
bypass_policy        no
```

This boundary is available through:

```python
from staqtapp_tds.drivers import foundry_capability_matrix

matrix = foundry_capability_matrix()
```

## Candidate rule

By default, `submit_candidate()` requires a successful `DriverVMResult` from `test_driver()`. A candidate submission only creates a `DriverState.CANDIDATE` registry record with deterministic test-report evidence.

It does **not** approve, sign, or activate the driver.

## Safety behavior

Expected failures do not halt the host:

- invalid TDDL returns `SOURCE_REJECTED`
- failed package audit returns `PACKAGE_REJECTED`
- bad fixtures return a Foundry test result containing `VMStatus.INPUT_REJECTED`
- runtime faults return `TEST_FAILED` with embedded `DriverVMResult`
- disabled candidate submission returns `POLICY_REJECTED`
- attempts to configure Foundry with signing/activation authority are rejected

## Repair loop

`DriverVMResult` gives the AI feedback language:

```text
status: FAULTED
fault: vm.scan.unsupported_operand
instruction: SCAN
reason: SCAN operands are not runtime-supported yet: ['kind']
repair_hints: Use only runtime-supported operands/adapters...
```

This supports the safe loop:

```text
generate → validate → compile → audit → test → repair → candidate
```

## Testing

v3.1.2 adds tests for:

- Foundry capability matrix denying trust authority
- validate/compile/audit/test success path
- proposal failure returning runtime repair feedback
- invalid source returning structured rejection
- candidate submission requiring successful VM evidence
- candidate creation without activation/signing
- policy rejection for signing/activation authority
- bad fixtures returning structured VM input rejection
- disabled candidate submission

# v3.0.9 Driver Studio Class A Quick Test

TDS v3.0.9 adds a non-GUI Driver Studio readiness layer. This is not the PyQt5 Studio UI and it does not execute drivers. It is a Class A documentation and quick-test path proving that the future Studio can teach and enforce the Driver Language/Registry workflow without duplicating runtime authority.

## Purpose

The Driver Studio must be a certification environment, not a bloated IDE. A programmer should learn the TDS Driver Language, validate a driver, compile bytecode, pass the VM contract audit, load the non-executing VM skeleton, pass registry policy, sign, and activate only after every previous gate succeeds.

The rule is:

```text
No next gate until current gate passes.
```

## Studio gates

```text
learn
syntax
capabilities
bytecode
vm_audit
vm_load
registry_policy
signing
complete
```

Each gate is intentionally backed by the real driver foundation layers:

- `learn` uses the instruction metadata table.
- `syntax` uses the TDDL parser/validator.
- `capabilities` verifies declared capabilities and adapters.
- `bytecode` compiles deterministic `.tdd` package content.
- `vm_audit` verifies opcode, class, capability and cost contracts.
- `vm_load` loads the package into the non-executing VM skeleton.
- `registry_policy` requires a candidate test report before approval.
- `signing` requires accepted signature policy before activation.
- `complete` records successful certification.

## Quick test API

```python
from staqtapp_tds.drivers import run_studio_quick_test

report = run_studio_quick_test(tddl_source)
assert report.ok
assert report.registry_state.value == "active"
print(report.passed_gates)
```

## Minimal editor support

The future PyQt5 Studio can query:

```python
from staqtapp_tds.drivers import studio_instruction_reference

reference = studio_instruction_reference()
```

This provides instruction names, required operands, optional operands, and allowed operand values for the Learn panel and minimal syntax editor. The Studio should display this information but must not become the source of truth. The parser, bytecode compiler, VM audit and registry policy remain authoritative.

## Fail-closed examples

The quick test rejects:

- unsafe path scopes such as `../outside`,
- undeclared adapters,
- unsupported unsafe adapter names,
- bad thresholds,
- missing `HALT`,
- VM contract violations,
- unsigned or unapproved registry paths.

## Safety classification

This layer is intentionally non-executing. It prepares the human-facing Studio while preserving subsystem separation:

```text
Studio teaches and orchestrates.
Builder compiles.
VM audit validates.
Registry signs.
Native VM runtime later executes.
Storage engine remains separate.
```

## Status

v3.0.9 establishes the Driver Studio documentation and quick-test readiness path before building the full PyQt5 Studio or executable Driver VM runtime.

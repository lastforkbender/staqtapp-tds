# v3.0.8 TDDL Bytecode Package

v3.0.8 adds the first non-executing bytecode artifact layer for the future native TDS Driver VM.

The release deliberately does **not** execute driver programs. It proves that validated TDDL can be compiled into a deterministic intermediate representation and compact bytecode package with stable hashing.

## Pipeline

```text
.tddl source
   ↓
TDDL parser / validator
   ↓
TDDLProgram IR
   ↓
BytecodePackage (.tdd-ready artifact model)
   ↓
Future Native Driver VM
```

## Stable v1 opcode map

```text
0x01 SCAN
0x02 READ
0x03 MATCH
0x04 EXTRACT
0x05 SCORE
0x06 EMIT
0x07 TRACE
0x08 HALT
```

`MAP`, `BRANCH`, `CALL`, and `PROPOSE` remain grammar-level concepts but are not emitted into bytecode v1. This keeps v3.0.8 conservative and prevents the artifact layer from getting ahead of the validated execution plan.

## Package contents

```text
Header
  magic = TDD1
  bytecode_version
  grammar_version
  builder_version
  driver_id
  driver_version

Manifest block
Capability block
Adapter dependency block
Limit block
Instruction block
Constant pool
Evolution block
Source hash
Package hash
```

## Safety posture

- Invalid TDDL never compiles.
- Unsupported future instructions fail closed.
- Bytecode must end with exactly one `HALT`.
- Opcode/name mismatches are rejected.
- Operand references must point into the constant pool.
- Package hashes are deterministic and tamper-evident.

## Purpose

This release creates a safe runway for the native Driver VM. The VM can later execute compact, validated opcodes without parsing TDDL text at runtime.

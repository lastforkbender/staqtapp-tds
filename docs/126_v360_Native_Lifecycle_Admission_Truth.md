# v3.6.0 native lifecycle admission truth

## Scope

This is an interim fail-closed lifecycle repair for the Frontier Foundation
train. It converts the native index extension to PEP 489 multi-phase
initialization, adds minimal per-module admission state, rejects unsafe
subinterpreter and repeated process-lifetime module admission, and explicitly
declares its current free-threaded policy.

It does not claim complete per-interpreter state isolation or no-GIL support.
The already-qualified immutable frozen index and packed lookup contracts remain
unchanged.

## Contracts

```text
TDS_NATIVE_MODULE_INIT = multiphase-pep489-v1
TDS_NATIVE_MULTI_INTERPRETER_POLICY = reject-subinterpreters-v1
TDS_NATIVE_GIL_POLICY = compatibility-gil-required-v1
TDS_NATIVE_REINITIALIZATION_POLICY = process-restart-required-v1
```

The extension uses `Py_mod_multiple_interpreters` on Python 3.12 and later to
reject subinterpreter imports. A process-wide atomic admission guard also
rejects every repeated module execution, including an unload/reload attempt and
Python 3.10/3.11 subinterpreter admission where the newer slot is unavailable.

Static extension types and process-scoped observer globals still exist. Module
deallocation therefore does not reopen admission; process restart is the only
safe way to initialize another module instance under this interim policy.

On a free-threaded Python 3.13 or later build, `Py_mod_gil = Py_MOD_GIL_USED`
explicitly requires the compatibility GIL. This prevents an unqualified
no-GIL execution path. Native loops continue to release the compatibility GIL
only at boundaries already covered by the native correctness suite.

## Preserved request-path contracts

```text
TDS_NATIVE_FROZEN_INDEX_CONTRACT =
  immutable-rehash-copy;lock-free-read-v1

TDS_NATIVE_PACKED_LOOKUP_CONTRACT =
  keys-bytes;offsets-le64;handles-le-i64;caller-owned-output-v1
```

Lifecycle admission changes module construction only. It does not alter frozen
lookup identities, packed wire encoding, caller-owned output, request bounds,
or the ranker authority boundary.

## Qualification

The release matrix adds:

- duplicate live-module rejection;
- post-deallocation reinitialization rejection;
- stable ordinary import reuse through `sys.modules`;
- a C embedding harness that imports in the main interpreter and requires
  subinterpreter rejection;
- free-threaded Python 3.13t and 3.14t builds started with `-X gil=0`,
  followed by explicit compatibility-GIL admission and one frozen packed
  lookup parity check on each ABI;
- Python 3.10 through 3.14 native build, import, lifecycle, and complete-suite
  compatibility on Linux, plus the retained macOS native lane; and
- the existing ASan, UBSan, TSan, deterministic fuzz, performance,
  distribution, and aggregate gates.

## Remaining lifecycle work

The final frontier-native engine must move all process-global mutable state into
per-module or per-interpreter state, replace static extension types with
module-bound heap types where required, qualify per-interpreter-GIL operation,
and either prove a `Py_MOD_GIL_NOT_USED` path or keep the Python bridge entirely
outside the ranker request path.

This repair is a professional fail-closed admission boundary. It is not the
final lifecycle architecture and does not authorize ranking, storage, policy,
training, promotion, or activation.

# Non-Halting Public API Contract

Staqtapp-TDS is designed for AI systems and long-running services that must keep control flow alive during normal storage, retrieval, decode, validation, and environment-error conditions.

## Meaning of non-halting

For TDS-controlled operational outcomes, public result-first APIs return a `TDSResult` object instead of requiring the caller to catch TDS-generated exceptions or interpret ambiguous values such as `False`, `None`, or raw bytes.

The standard pattern is:

```python
result = directory.read("agent_state")

if result.ok:
    state = result.value
else:
    handle(result.code, result.message, result.meta)
```

## TDSResult is the standard envelope

`TDSResult` is the single public success/failure envelope for controlled TDS outcomes.

Fields:

| Field | Meaning |
| --- | --- |
| `ok` | `True` for success, `False` for controlled failure. |
| `code` | Stable machine-readable result code. |
| `message` | Human-readable explanation. |
| `name` | Optional TDS entry name context. |
| `path` | Optional TDS path context. |
| `value` | Returned object or operation payload when applicable. |
| `meta` | Structured diagnostics for logging, telemetry, retry policy, or AI control logic. |

## Result-code source of truth

Every public `TDSResult.code` is defined in one runtime source of truth:

```text
src/staqtapp_tds/result.py
```

Use:

```python
from staqtapp_tds import TDSResultCode, result_info
```

The registry metadata is available through `result_info(code)` and `TDS_RESULT_REGISTRY`.

Generated references:

```text
docs/TDS_RESULT_CODES.md
docs/TDS_RESULT_CODES.json
```

These files are generated from the runtime registry and should not be treated as an independent source of truth.

## What TDS converts into TDSResult

Public result-first surfaces should convert controlled outcomes into `TDSResult`, including:

- missing entries,
- read/write/delete failures caught inside the TDS boundary,
- payload decode and deserialize failures,
- unsupported stored payload formats,
- validation failures,
- text/JSON/chunked-text operation failures,
- persistence reader failures,
- variable-control conflicts,
- cluster selector failures,
- Spiral rank controlled failures.

## What TDS does not claim to control

The non-halting contract does not mean TDS can prevent every possible process-level stop. Examples outside the TDS-controlled boundary include:

- Python interpreter termination,
- operating-system failure,
- process kill signals,
- fatal native crashes,
- unrecoverable memory exhaustion,
- `KeyboardInterrupt` or external cancellation,
- hardware failure.

TDS does not intentionally raise TDS-defined exceptions from public result-first APIs for normal operational failures.

## Compatibility methods

Some explicit compatibility methods may return raw values or booleans by design. Their names should make this clear, for example:

```text
read_value()
write_entry()
delete_entry()
```

Use result-first methods for AI systems and production control flow where the non-halting contract matters.

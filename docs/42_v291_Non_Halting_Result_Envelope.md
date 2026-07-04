# v2.9.1 Non-Halting Result Envelope

Staqtapp-TDS v2.9.1 strengthens AI-facing failure semantics. Storage operations intended for AI systems should prefer the `TDSResult` surfaces so callers can branch on `ok` and `code` rather than catching exceptions.

## Standard TDSResult pattern

`TDSResult` is the central success/failure envelope:

- `ok`: boolean success flag
- `code`: stable machine-readable status/error code
- `message`: human-readable summary
- `name` and `path`: optional TDS location context
- `value`: optional successful payload
- `meta`: optional structured diagnostics

It remains a dataclass because that gives TDS a compact, explicit, serializable value object. In v2.9.1 it is immutable and slotted to reduce accidental mutation and memory overhead.

## Deserialization hardening

Malformed payloads no longer fall back to returning raw bytes. `_deserialize_payload(...)` now returns:

```python
TDSResult.fail("PAYLOAD_DESERIALIZE_ERROR", ...)
```

This prevents corrupted or incompatible byte streams from masquerading as valid application data.

## AI-safe directory methods

Use these methods for non-halting AI integration surfaces:

- `read_result(name)`
- `write_result(name, value, ...)`
- `delete_result(name)`
- `read_text_result(name)`

Each returns `TDSResult` on both success and failure.

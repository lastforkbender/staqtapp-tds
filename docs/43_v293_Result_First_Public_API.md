# v2.9.3 Result-First Public API

Staqtapp-TDS now treats `TDSResult` as the public non-halting result envelope for directory read/write/delete circumstances where a caller would otherwise need exceptions, booleans, `None`, or mixed return objects.

## Public rule

```python
result = directory.write("state", {"ready": True})
assert result.ok

result = directory.read("state")
if result.ok:
    value = result.value
else:
    handle(result.code, result.message, result.meta)

result = directory.delete("state")
```

## Explicit raw compatibility surfaces

Raw internal/migration behavior remains available only under names that make the risk clear:

- `write_entry(...) -> TDSEntry`
- `read_value(...) -> Any`
- `delete_entry(...) -> None`

These are not the AI-facing contract. Public non-halting application code should use the `TDSResult` surfaces.

## Central reference files

- `src/staqtapp_tds/result.py` contains `TDS_RESULT_CODES`.
- `docs/TDS_RESULT_CODES.md` is the human-readable catalog.
- `docs/TDS_RESULT_CODES.json` is the machine-readable catalog.

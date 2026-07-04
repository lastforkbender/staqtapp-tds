# v3.0.1 Native Engine Manager

Staqtapp-TDS v3.0.1 adds a platform-aware Native Engine Manager as the single authority for optional compiled native engines.

## Purpose

The application developer should not manually choose platform binaries. TDS inspects the runtime environment, attempts to load a compatible native engine, verifies the expected TDS native ABI, records capability diagnostics, and falls back to the Python backend when native loading is not safe.

This preserves the TDS non-halting contract: native engine import failures, missing binaries, ABI mismatches, and construction errors are contained and reported as structured `TDSResult` diagnostics.

## Public diagnostics

```python
from staqtapp_tds import EntryIndex, native_status_result, native_capabilities_result

print(native_status_result().as_dict())
print(native_capabilities_result().as_dict())

idx = EntryIndex(backend="auto")
print(idx.native_status_result().as_dict())
```

## Result codes

Native manager result codes are defined in the central registry:

- `NATIVE_MANAGER_OK`
- `NATIVE_CAPABILITY_OK`
- `NATIVE_ENGINE_LOADED`
- `NATIVE_ENGINE_FALLBACK`
- `NATIVE_ENGINE_UNAVAILABLE`
- `NATIVE_ENGINE_INCOMPATIBLE`
- `NATIVE_ENGINE_LOAD_ERROR`

The human-readable and machine-readable code references are generated from `src/staqtapp_tds/result.py`:

- `docs/TDS_RESULT_CODES.md`
- `docs/TDS_RESULT_CODES.json`

## Driver-system readiness

The Native Engine Manager is intentionally separate from the future Search & Extract driver language, registry, builder, and optional C VM. Future driver VM binaries should use the same loading discipline:

1. detect platform
2. import native module safely
3. verify TDS native ABI
4. verify capabilities
5. fallback without halting
6. return `TDSResult` diagnostics

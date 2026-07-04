# Non-Halting Execution Contract

Staqtapp-TDS is designed for AI systems, autonomous agents, and long-running services where storage failures must be observable without unexpectedly stopping the caller's execution.

## Contract

Public TDS operations that can encounter ordinary operational failure return `TDSResult` instead of using TDS-generated exceptions as the normal failure path.

A caller should be able to use one standard pattern:

```python
result = tds.write("agent_state", state)

if result.ok:
    ...
else:
    print(result.code)
    print(result.message)
    print(result.meta)
```

## What non-halting means

Non-halting means TDS does not intentionally terminate normal application control flow for recoverable TDS conditions such as:

- invalid names
- missing entries
- serialization or deserialization failure
- read-only directories
- native engine load failure
- native ABI mismatch
- optional native binary absence

Those conditions are represented as `TDSResult` values with centralized result codes.

## What non-halting does not mean

No Python library can guarantee survival from every process-level or interpreter-level condition. Examples outside the TDS operational contract include:

- process termination by the operating system
- interpreter crash
- severe memory exhaustion
- `KeyboardInterrupt` or external cancellation
- hardware failure
- fatal native memory corruption from outside TDS

TDS avoids using those as normal control-flow mechanisms and reports ordinary TDS failures through `TDSResult` wherever the public API boundary can safely do so.

## Native Engine Manager behavior

The Native Engine Manager preserves the non-halting contract for optional compiled engines:

```text
Application
    ↓
Public TDS API
    ↓
Native Engine Manager
    ├─ native module loads and ABI matches → native backend active
    └─ unavailable / incompatible / load failed → Python backend fallback
    ↓
TDSResult diagnostics
```

A missing `.so`, `.pyd`, or incompatible compiled extension should not crash an AI application during normal startup. TDS records native availability, ABI status, platform information, and fallback status through diagnostics and result metadata.

## Result-code source of truth

The authoritative runtime source is:

```text
src/staqtapp_tds/result.py
```

Generated public references are:

```text
docs/TDS_RESULT_CODES.md
docs/TDS_RESULT_CODES.json
```

The result-code reference is generated from the runtime registry so documentation and implementation do not drift.

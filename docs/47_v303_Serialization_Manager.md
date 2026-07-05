# v3.0.4 Serialization Manager

TDS v3.0.4 now includes a first-class Serialization Manager between the public variable API and the storage engine.

## Purpose

The storage engine remains byte-oriented. Python meaning is owned by the variable and serialization layers.

```text
addvar/loadvar/findvar/read
        |
        v
Serialization Manager
        |
        +-- raw_binary
        +-- numpy_matrix
        +-- text_utf8
        +-- json_utf8
        +-- restricted_pickle
        v
TDS storage engine
```

## Class A pickle boundary

Pickle remains available for Python variable compatibility, but it is no longer scattered through the storage path. The manager routes complex Python objects to the restricted pickle codec, which uses the existing TDS pickle envelope and restricted reader policy.

Legacy unenveloped safe pickle payloads remain readable for migration compatibility. Unsafe legacy loading still requires the explicit `TDS_ALLOW_UNSAFE_PICKLE=1` escape hatch.

## Variable API behavior

- `addvar()` uses the manager to infer the best codec.
- `loadvar()` returns the recovered Python value.
- `findvar()` returns the recovered value inside `TDSResult`.
- `read()` follows the same deserialize path and returns `TDSResult`.
- `stalkvar()` continues to merge/evolve variables and stores increments through the same manager path.

## Testing

The v3.0.4 tests now cover:

- manager codec inference for JSON, bytes, and restricted pickle;
- `addvar/loadvar/findvar/read` retrieval through the manager;
- `stalkvar()` increments through the manager;
- safe legacy pickle compatibility;
- unsafe pickle payload rejection through the manager;
- stale legacy tests updated to the current non-halting `TDSResult` read API.

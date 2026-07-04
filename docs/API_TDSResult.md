# TDSResult API Contract

`TDSResult` is the only standard public return envelope for Staqtapp-TDS surfaces that are intended to be non-halting for AI systems.

The rule is simple:

```python
result = directory.read_result("agent_state")

if result.ok:
    value = result.value
else:
    code = result.code
    diagnostics = result.meta
```

AI-facing TDS methods must not require caller-side exception handling for normal conflicts, decode failures, malformed payloads, missing entries, lock conflicts, or third-party/runtime failures caught inside the TDS boundary. They return `TDSResult`.

## Object shape

```python
@dataclass(frozen=True, slots=True)
class TDSResult:
    ok: bool
    code: str = "OK"
    message: str = ""
    name: str = ""
    path: str = ""
    value: Any = None
    meta: dict[str, Any] = {}
```

Field meanings:

| Field | Meaning |
|---|---|
| `ok` | `True` for success or controlled no-op success; `False` for controlled failure. |
| `code` | Stable machine-readable status/error code. Branch on this, not `message`. |
| `message` | Human-readable explanation. Not intended for control flow. |
| `name` | Entry or variable name when applicable. |
| `path` | TDS directory path when applicable. |
| `value` | Payload on success, otherwise normally `None`. |
| `meta` | Structured diagnostics such as exception type, codec, raw size, stats, or lock state. |

Helpers:

```python
result.as_dict()
bool(result)              # same as result.ok
result.known_code         # True when code is in the public catalog
known_result_codes()      # tuple of public codes
is_known_result_code(code)
```

## Centralization rule

Do not create other public `*Result` dataclass return envelopes for AI-facing operations. Use `TDSResult`.

Data records are allowed when they are not success/error envelopes. For example, telemetry snapshots, rank rows, provenance tags, config records, and metadata records may be dataclasses because callers do not branch on them as operation status.

## Public result codes

### Generic filesystem result surfaces

| Method | Code | ok | value | Notes |
|---|---:|:---:|---|---|
| `TDSDirectory.read_result(name)` | `READ_OK` | true | stored object | Entry read successfully. |
| `TDSDirectory.read_result(name)` | `READ_ERROR` | false | `None` | Read failed inside TDS boundary. `meta.exception_type` and `meta.exception_message` are included when available. |
| `TDSDirectory.write_result(...)` | `WRITE_OK` | true | written object | Entry written successfully. |
| `TDSDirectory.write_result(...)` | `WRITE_ERROR` | false | `None` | Write failed inside TDS boundary. |
| `TDSDirectory.delete_result(name)` | `DELETE_OK` | true | `None` | Entry existed and was deleted. |
| `TDSDirectory.delete_result(name)` | `DELETE_MISSING` | true | `None` | Entry was already absent; treated as non-halting idempotent success. |
| `TDSDirectory.delete_result(name)` | `DELETE_ERROR` | false | `None` | Delete failed inside TDS boundary. |

### Payload decode and format codes

| Surface | Code | ok | value | Typical meta |
|---|---:|:---:|---|---|
| payload decoder | `PAYLOAD_DESERIALIZE_ERROR` | false | `None` | `fmt_id`, `base_fmt_id`, `codec`, `raw_size`, `exception_type`, `exception_message` |
| payload decoder | `PAYLOAD_FORMAT_UNSUPPORTED` | false | `None` | `fmt_id`, `base_fmt_id`, `codec`, `raw_size` |

Important: deserialize failures never return raw bytes as a fallback.

### JSON and text surfaces

| Method | Code | ok | value |
|---|---:|:---:|---|
| `write_json` | `JSON_WRITTEN` | true | JSON-safe object |
| `write_json` | `JSON_OVERWRITTEN` | true | JSON-safe object |
| `write_json` | `JSON_EXISTS` | false | `None` |
| `write_text` | `TEXT_WRITTEN` | true | `str` |
| `write_text` | `TEXT_OVERWRITTEN` | true | `str` |
| `write_text`, `write_text_chunked` | `TEXT_EXISTS` | false | `None` |
| text surfaces | `TEXT_TYPE_ERROR` | false | `None` |
| `write_text_chunked` | `TEXT_CHUNK_SIZE_INVALID` | false | `None` |
| `write_text_chunked` | `TEXT_CHUNK_CHECKSUM_ERROR` | false | `None` |
| `write_text_chunked` | `TEXT_CHUNK_WRITE_ERROR` | false | `None` |
| `write_text_chunked` | `TEXT_CHUNKED_WRITTEN` | true | `None` |
| `write_text_chunked` | `TEXT_CHUNKED_OVERWRITTEN` | true | `None` |
| `read_text_result` | `TEXT_READ_OK` | true | `str` |
| `read_text_result` | `TEXT_READ_ERROR` | false | `None` |

### Variable-control surfaces

| Method | Code | ok | value |
|---|---:|:---:|---|
| `addvar` | `VAR_ADDED` | true | stored object |
| `editvar`, `stalkvar` | `VAR_CREATED` | true | stored object |
| `editvar`, `stalkvar` | `VAR_EDITED` | true | stored object |
| `addvar`, `editvar` | `VAR_EXISTS` | false | `None` |
| variable surfaces | `VAR_LOCKED` | false | `None` |
| `unlockvar` | `VAR_UNLOCKED` | true | `None` |
| variable surfaces | `VAR_MISSING` | false | `None` |
| `findvar` | `VAR_FOUND` | true | stored object |
| `stalkvar` | `VAR_INVALID_NAME` | false | `None` |
| `stalkvar` | `VAR_CHAIN_COLLISION` | false | `None` |
| `stalkvar` | `VAR_STALKED` | true | combined object |
| `stalkvar` | `VAR_STALK_CLEARED` | true | `None` |
| `stalkvar` | `VAR_NOOP` | true | `None` |

### Cluster and Spiral non-halting surfaces

| Method | Code | ok | value |
|---|---:|:---:|---|
| `query_requires_selector` | `QUERY_ACCEPTED` | true | `None` |
| `query_requires_selector` | `QUERY_REQUIRES_SELECTOR` | false | `None` |
| `NativeSpiralRankEngine.rank_result` | `SPIRAL_RANK_OK` | true | rank-run dictionary |
| `NativeSpiralRankEngine.rank_result` | `SPIRAL_RANK_ERROR` | false | `None` |

## Adding new AI-facing methods

A new AI-facing method should follow this shape:

```python
def some_operation_result(...) -> TDSResult:
    try:
        value = internal_operation(...)
        return TDSResult.success("SOME_OPERATION_OK", "Operation completed.", value=value)
    except Exception as exc:
        return TDSResult.from_exception("SOME_OPERATION_ERROR", exc)
```

Add every new code to `TDS_RESULT_CODES` and this document in the same change.

# TDSResult Return Code Reference

This file is generated from `src/staqtapp_tds/result.py`.
The runtime source of truth is `TDSResultCode` plus `TDS_RESULT_REGISTRY`; this Markdown file and `TDS_RESULT_CODES.json` must not be hand-edited.

Public non-halting APIs return `TDSResult`. Callers should branch on `result.ok` and `result.code`, then read `result.value` and optional `result.meta`.

## Envelope

```python
TDSResult(ok: bool, code: str, message: str, name: str = "", path: str = "", value: Any = None, meta: dict = {})
```

## Runtime parsing

```python
from staqtapp_tds import TDSResultCode, result_info

result = directory.read("agent_state")
if result.ok:
    value = result.value
elif result.code == TDSResultCode.READ_MISSING.value:
    ...
else:
    info = result_info(result.code)
```

## Compatibility rule

`read()`, `write()`, and `delete()` are result-first public APIs. Explicit raw/legacy migration surfaces are named `read_value()`, `write_entry()`, and `delete_entry()` so non-halting public code does not confuse raw objects with operation status.

## Codes

| Code | ok | Surface | value | Category | Severity | Retryable | Description |
|---|---:|---|---|---|---|---:|---|
| `DELETE_ERROR` | `False` | TDSDirectory.delete/delete_result | None | filesystem | error | `True` | Entry could not be deleted. |
| `DELETE_MISSING` | `True` | TDSDirectory.delete/delete_result | None | filesystem | info | `False` | Delete completed and the entry was already absent. |
| `DELETE_OK` | `True` | TDSDirectory.delete/delete_result | None | filesystem | info | `False` | Entry existed and was removed. |
| `ENTRY_METADATA_MISSING` | `False` | TDSDirectory.entry_metadata_result | None | metadata | warn | `False` | Entry metadata is unavailable because the entry is missing. |
| `ENTRY_METADATA_OK` | `True` | TDSDirectory.entry_metadata_result | metadata dictionary | metadata | info | `False` | Entry metadata was read. |
| `JSON_EXISTS` | `False` | TDSDirectory.write_json | None | json | warn | `False` | JSON entry already exists and overwrite was not enabled. |
| `JSON_OVERWRITTEN` | `True` | TDSDirectory.write_json | JSON-safe object | json | info | `False` | Existing JSON entry was overwritten. |
| `JSON_WRITTEN` | `True` | TDSDirectory.write_json | JSON-safe object | json | info | `False` | JSON entry was stored. |
| `NATIVE_CAPABILITY_OK` | `True` | NativeEngineManager.capabilities_result | native capability snapshot | native | info | `False` | Native platform and capability details were collected. |
| `NATIVE_ENGINE_FALLBACK` | `True` | NativeEngineManager.load_result | python fallback backend | native | warn | `False` | Native engine was not used; TDS safely selected a Python fallback. |
| `NATIVE_ENGINE_INCOMPATIBLE` | `False` | NativeEngineManager.load_result | None | native | error | `False` | A native engine was present but did not satisfy the expected TDS native ABI or capabilities. |
| `NATIVE_ENGINE_LOADED` | `True` | NativeEngineManager.load_result | loaded native backend | native | info | `False` | A compatible native engine was loaded. |
| `NATIVE_ENGINE_LOAD_ERROR` | `False` | NativeEngineManager.load_result | None | native | error | `False` | Native engine loading failed and was contained without halting TDS. |
| `NATIVE_ENGINE_UNAVAILABLE` | `False` | NativeEngineManager.load_result | None | native | warn | `False` | No compiled native engine was available for this runtime platform. |
| `NATIVE_MANAGER_OK` | `True` | NativeEngineManager.status_result | native status snapshot | native | info | `False` | Native engine manager status was produced. |
| `OK` | `True` | generic | operation-specific | generic | info | `False` | Generic successful operation. |
| `PAYLOAD_DESERIALIZE_ERROR` | `False` | payload decoder | None | serialization | error | `False` | Stored payload could not be deserialized and was not returned as raw bytes. |
| `PAYLOAD_FORMAT_UNSUPPORTED` | `False` | payload decoder | None | serialization | error | `False` | Stored payload format is unsupported. |
| `PERSIST_BATCH_READ_ERROR` | `False` | TDSReader.read_many_result | None | persistence | error | `True` | Batch persistence read failed. |
| `PERSIST_BATCH_READ_OK` | `True` | TDSReader.read_many_result | dict[name, object] | persistence | info | `False` | All requested persisted entries were read. |
| `PERSIST_BATCH_READ_PARTIAL` | `False` | TDSReader.read_many_result | dict[name, object|TDSResult] | persistence | warn | `True` | Some persisted entries could not be read. |
| `PERSIST_READ_ERROR` | `False` | TDSReader.read_result | None | persistence | error | `True` | Persisted entry could not be read. |
| `PERSIST_READ_OK` | `True` | TDSReader.read_result | persisted object | persistence | info | `False` | Persisted entry was read. |
| `PROVENANCE_RECORD_MISSING` | `False` | TDSDirectory.provenance_record_result | None | provenance | warn | `False` | Provenance record is unavailable because the entry is missing. |
| `PROVENANCE_RECORD_OK` | `True` | TDSDirectory.provenance_record_result | numpy provenance record | provenance | info | `False` | Provenance record was read. |
| `QUERY_ACCEPTED` | `True` | query_requires_selector | None | cluster | info | `False` | Cluster query selectors were accepted. |
| `QUERY_REQUIRES_SELECTOR` | `False` | query_requires_selector | None | cluster | warn | `False` | Cluster query requires a selector or explicit scan=True. |
| `READ_ERROR` | `False` | TDSDirectory.read/read_result | None | filesystem | error | `False` | Entry could not be read due to an internal or environment error. |
| `READ_MISSING` | `False` | TDSDirectory.read/read_result | None | filesystem | warn | `False` | Requested entry does not exist. |
| `READ_OK` | `True` | TDSDirectory.read/read_result | stored object | filesystem | info | `False` | Entry was read successfully. |
| `SPIRAL_RANK_ERROR` | `False` | NativeSpiralRankEngine.rank_result | None | spiral | error | `True` | Spiral rank failed in a controlled non-halting path. |
| `SPIRAL_RANK_OK` | `True` | NativeSpiralRankEngine.rank_result | rank run dictionary | spiral | info | `False` | Spiral rank completed. |
| `TEXT_CHUNKED_OVERWRITTEN` | `True` | TDSDirectory.write_text_chunked | None | text | info | `False` | Existing chunked text entry was overwritten. |
| `TEXT_CHUNKED_WRITTEN` | `True` | TDSDirectory.write_text_chunked | None | text | info | `False` | Chunked text entry was stored. |
| `TEXT_CHUNK_CHECKSUM_ERROR` | `False` | TDSDirectory.write_text_chunked | None | text | error | `True` | Chunk checksum batch was inconsistent. |
| `TEXT_CHUNK_SIZE_INVALID` | `False` | TDSDirectory.write_text_chunked | None | text | error | `False` | Chunk size must be positive. |
| `TEXT_CHUNK_WRITE_ERROR` | `False` | TDSDirectory.write_text_chunked | None | text | error | `True` | Chunked text entry could not be written. |
| `TEXT_EXISTS` | `False` | TDSDirectory.write_text/write_text_chunked | None | text | warn | `False` | Text entry already exists and overwrite was not enabled. |
| `TEXT_OVERWRITTEN` | `True` | TDSDirectory.write_text | str | text | info | `False` | Existing text entry was overwritten. |
| `TEXT_READ_ERROR` | `False` | TDSDirectory.read_text_result | None | text | error | `False` | Text entry could not be read. |
| `TEXT_READ_OK` | `True` | TDSDirectory.read_text_result | str | text | info | `False` | Text entry was read. |
| `TEXT_TYPE_ERROR` | `False` | text surfaces | None | text | error | `False` | Text operation received a non-string value. |
| `TEXT_WRITTEN` | `True` | TDSDirectory.write_text | str | text | info | `False` | Text entry was stored. |
| `VAR_ADDED` | `True` | VariableControl.addvar | stored object | variables | info | `False` | Variable was added. |
| `VAR_CHAIN_COLLISION` | `False` | VariableControl.stalkvar | None | variables | error | `False` | Stalk chain next name collides with an unrelated entry. |
| `VAR_CREATED` | `True` | VariableControl.editvar/stalkvar | stored object | variables | info | `False` | Variable was created. |
| `VAR_EDITED` | `True` | VariableControl.editvar/stalkvar | stored object | variables | info | `False` | Variable was edited. |
| `VAR_EXISTS` | `False` | VariableControl.addvar/editvar | None | variables | warn | `False` | Variable already exists. |
| `VAR_FOUND` | `True` | VariableControl.findvar | stored object | variables | info | `False` | Variable was found. |
| `VAR_INVALID_NAME` | `False` | VariableControl.stalkvar | None | variables | error | `False` | Variable name is invalid. |
| `VAR_LOCKED` | `False` | VariableControl | None | variables | warn | `False` | Variable is locked. |
| `VAR_MISSING` | `False` | VariableControl | None | variables | warn | `False` | Variable does not exist. |
| `VAR_NOOP` | `True` | VariableControl.stalkvar | None | variables | info | `False` | Operation completed with no state change. |
| `VAR_STALKED` | `True` | VariableControl.stalkvar | combined object | variables | info | `False` | Stalk increment was created. |
| `VAR_STALK_CLEARED` | `True` | VariableControl.stalkvar | None | variables | info | `False` | Stalk chain was cleared. |
| `VAR_UNLOCKED` | `True` | VariableControl.unlockvar | None | variables | info | `False` | Variable was unlocked or lock state updated to unlocked. |
| `WRITE_ERROR` | `False` | TDSDirectory.write/write_result | None | filesystem | error | `True` | Entry could not be written. |
| `WRITE_OK` | `True` | TDSDirectory.write/write_result | written object | filesystem | info | `False` | Entry was written successfully. |

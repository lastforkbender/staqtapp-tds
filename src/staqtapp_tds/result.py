"""Structured non-halting operation results for Staqtapp-TDS.

``TDSResult`` is the single public error/success envelope for AI-facing calls.
Result codes are defined in this module only. Public result call sites should
reference ``TDSResultCode`` members instead of hard-coded string literals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping


class TDSResultCode(str, Enum):
    """Authoritative Staqtapp-TDS result-code enum.

    This is the runtime source of truth for every public ``TDSResult.code``.
    Values remain strings for compatibility with existing callers and JSON logs.
    """

    def __str__(self) -> str:
        return self.value

    OK = "OK"
    READ_OK = "READ_OK"
    READ_ERROR = "READ_ERROR"
    WRITE_OK = "WRITE_OK"
    WRITE_ERROR = "WRITE_ERROR"
    DELETE_OK = "DELETE_OK"
    DELETE_MISSING = "DELETE_MISSING"
    DELETE_ERROR = "DELETE_ERROR"
    READ_MISSING = "READ_MISSING"
    ENTRY_METADATA_OK = "ENTRY_METADATA_OK"
    ENTRY_METADATA_MISSING = "ENTRY_METADATA_MISSING"
    PROVENANCE_RECORD_OK = "PROVENANCE_RECORD_OK"
    PROVENANCE_RECORD_MISSING = "PROVENANCE_RECORD_MISSING"
    PERSIST_READ_OK = "PERSIST_READ_OK"
    PERSIST_READ_ERROR = "PERSIST_READ_ERROR"
    PERSIST_WRITE_ERROR = "PERSIST_WRITE_ERROR"
    PERSIST_HEADER_CORRUPT = "PERSIST_HEADER_CORRUPT"
    PERSIST_INDEX_CORRUPT = "PERSIST_INDEX_CORRUPT"
    PERSIST_SLOT_BOUNDS_ERROR = "PERSIST_SLOT_BOUNDS_ERROR"
    PERSIST_PAYLOAD_HASH_MISMATCH = "PERSIST_PAYLOAD_HASH_MISMATCH"
    PERSIST_CODEC_UNAVAILABLE = "PERSIST_CODEC_UNAVAILABLE"
    PERSIST_SIDECAR_STALE = "PERSIST_SIDECAR_STALE"
    PERSIST_SIDECAR_CORRUPT = "PERSIST_SIDECAR_CORRUPT"
    PERSIST_SNAPSHOT_EPOCH_MISMATCH = "PERSIST_SNAPSHOT_EPOCH_MISMATCH"
    PERSIST_BATCH_READ_OK = "PERSIST_BATCH_READ_OK"
    PERSIST_BATCH_READ_PARTIAL = "PERSIST_BATCH_READ_PARTIAL"
    PERSIST_BATCH_READ_ERROR = "PERSIST_BATCH_READ_ERROR"
    PAYLOAD_DESERIALIZE_ERROR = "PAYLOAD_DESERIALIZE_ERROR"
    PAYLOAD_FORMAT_UNSUPPORTED = "PAYLOAD_FORMAT_UNSUPPORTED"
    JSON_WRITTEN = "JSON_WRITTEN"
    JSON_OVERWRITTEN = "JSON_OVERWRITTEN"
    JSON_EXISTS = "JSON_EXISTS"
    TEXT_WRITTEN = "TEXT_WRITTEN"
    TEXT_OVERWRITTEN = "TEXT_OVERWRITTEN"
    TEXT_EXISTS = "TEXT_EXISTS"
    TEXT_TYPE_ERROR = "TEXT_TYPE_ERROR"
    TEXT_CHUNK_SIZE_INVALID = "TEXT_CHUNK_SIZE_INVALID"
    TEXT_CHUNK_CHECKSUM_ERROR = "TEXT_CHUNK_CHECKSUM_ERROR"
    TEXT_CHUNK_WRITE_ERROR = "TEXT_CHUNK_WRITE_ERROR"
    TEXT_CHUNKED_WRITTEN = "TEXT_CHUNKED_WRITTEN"
    TEXT_CHUNKED_OVERWRITTEN = "TEXT_CHUNKED_OVERWRITTEN"
    TEXT_READ_OK = "TEXT_READ_OK"
    TEXT_READ_ERROR = "TEXT_READ_ERROR"
    VAR_ADDED = "VAR_ADDED"
    VAR_CREATED = "VAR_CREATED"
    VAR_EDITED = "VAR_EDITED"
    VAR_EXISTS = "VAR_EXISTS"
    VAR_LOCKED = "VAR_LOCKED"
    VAR_UNLOCKED = "VAR_UNLOCKED"
    VAR_MISSING = "VAR_MISSING"
    VAR_FOUND = "VAR_FOUND"
    VAR_INVALID_NAME = "VAR_INVALID_NAME"
    VAR_CHAIN_COLLISION = "VAR_CHAIN_COLLISION"
    VAR_STALKED = "VAR_STALKED"
    VAR_STALK_CLEARED = "VAR_STALK_CLEARED"
    VAR_NOOP = "VAR_NOOP"
    QUERY_ACCEPTED = "QUERY_ACCEPTED"
    QUERY_REQUIRES_SELECTOR = "QUERY_REQUIRES_SELECTOR"
    SPIRAL_RANK_OK = "SPIRAL_RANK_OK"
    SPIRAL_RANK_ERROR = "SPIRAL_RANK_ERROR"

    NATIVE_MANAGER_OK = "NATIVE_MANAGER_OK"
    NATIVE_ENGINE_LOADED = "NATIVE_ENGINE_LOADED"
    NATIVE_ENGINE_FALLBACK = "NATIVE_ENGINE_FALLBACK"
    NATIVE_ENGINE_UNAVAILABLE = "NATIVE_ENGINE_UNAVAILABLE"
    NATIVE_ENGINE_INCOMPATIBLE = "NATIVE_ENGINE_INCOMPATIBLE"
    NATIVE_ENGINE_LOAD_ERROR = "NATIVE_ENGINE_LOAD_ERROR"
    NATIVE_CAPABILITY_OK = "NATIVE_CAPABILITY_OK"


@dataclass(frozen=True, slots=True)
class TDSResultInfo:
    """Registry metadata for one ``TDSResultCode``."""

    ok: bool
    surface: str
    value: str | None = None
    category: str = "general"
    severity: str = "info"
    retryable: bool = False
    description: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "surface": self.surface,
            "value": self.value,
            "category": self.category,
            "severity": self.severity,
            "retryable": self.retryable,
            "description": self.description,
        }


def _info(ok: bool, surface: str, value: str | None, category: str, severity: str, retryable: bool, description: str) -> TDSResultInfo:
    return TDSResultInfo(ok=ok, surface=surface, value=value, category=category, severity=severity, retryable=retryable, description=description)


TDS_RESULT_REGISTRY: Mapping[TDSResultCode, TDSResultInfo] = {
    TDSResultCode.OK: _info(True, "generic", "operation-specific", "generic", "info", False, "Generic successful operation."),
    TDSResultCode.READ_OK: _info(True, "TDSDirectory.read/read_result", "stored object", "filesystem", "info", False, "Entry was read successfully."),
    TDSResultCode.READ_ERROR: _info(False, "TDSDirectory.read/read_result", None, "filesystem", "error", False, "Entry could not be read due to an internal or environment error."),
    TDSResultCode.WRITE_OK: _info(True, "TDSDirectory.write/write_result", "written object", "filesystem", "info", False, "Entry was written successfully."),
    TDSResultCode.WRITE_ERROR: _info(False, "TDSDirectory.write/write_result", None, "filesystem", "error", True, "Entry could not be written."),
    TDSResultCode.DELETE_OK: _info(True, "TDSDirectory.delete/delete_result", None, "filesystem", "info", False, "Entry existed and was removed."),
    TDSResultCode.DELETE_MISSING: _info(True, "TDSDirectory.delete/delete_result", None, "filesystem", "info", False, "Delete completed and the entry was already absent."),
    TDSResultCode.DELETE_ERROR: _info(False, "TDSDirectory.delete/delete_result", None, "filesystem", "error", True, "Entry could not be deleted."),
    TDSResultCode.READ_MISSING: _info(False, "TDSDirectory.read/read_result", None, "filesystem", "warn", False, "Requested entry does not exist."),
    TDSResultCode.ENTRY_METADATA_OK: _info(True, "TDSDirectory.entry_metadata_result", "metadata dictionary", "metadata", "info", False, "Entry metadata was read."),
    TDSResultCode.ENTRY_METADATA_MISSING: _info(False, "TDSDirectory.entry_metadata_result", None, "metadata", "warn", False, "Entry metadata is unavailable because the entry is missing."),
    TDSResultCode.PROVENANCE_RECORD_OK: _info(True, "TDSDirectory.provenance_record_result", "numpy provenance record", "provenance", "info", False, "Provenance record was read."),
    TDSResultCode.PROVENANCE_RECORD_MISSING: _info(False, "TDSDirectory.provenance_record_result", None, "provenance", "warn", False, "Provenance record is unavailable because the entry is missing."),
    TDSResultCode.PERSIST_READ_OK: _info(True, "TDSReader.read_result", "persisted object", "persistence", "info", False, "Persisted entry was read."),
    TDSResultCode.PERSIST_READ_ERROR: _info(False, "TDSReader.read_result", None, "persistence", "error", True, "Persisted entry could not be read."),
    TDSResultCode.PERSIST_WRITE_ERROR: _info(False, "TDSWriter", None, "persistence", "error", True, "Persisted file could not be written durably."),
    TDSResultCode.PERSIST_HEADER_CORRUPT: _info(False, "TDSReader.open", None, "persistence", "critical", False, "Persisted file header failed structural or checksum validation."),
    TDSResultCode.PERSIST_INDEX_CORRUPT: _info(False, "TDSReader.open", None, "persistence", "critical", False, "Persisted slot index failed fail-closed structural validation."),
    TDSResultCode.PERSIST_SLOT_BOUNDS_ERROR: _info(False, "TDSReader.open/read", None, "persistence", "critical", False, "Persisted slot points outside the validated data block."),
    TDSResultCode.PERSIST_PAYLOAD_HASH_MISMATCH: _info(False, "TDSReader.read", None, "persistence", "critical", False, "Decoded payload bytes do not match sidecar content_hash."),
    TDSResultCode.PERSIST_CODEC_UNAVAILABLE: _info(False, "TDSReader.read", None, "persistence", "error", False, "Required persisted compression codec is unavailable or could not decode the payload."),
    TDSResultCode.PERSIST_SIDECAR_STALE: _info(False, "TDSPersistence.load_node", None, "persistence", "warn", True, "Sidecar metadata is missing or older than the data snapshot."),
    TDSResultCode.PERSIST_SIDECAR_CORRUPT: _info(False, "TDSPersistence.load_node", None, "persistence", "error", False, "Sidecar metadata could not be parsed or failed validation."),
    TDSResultCode.PERSIST_SNAPSHOT_EPOCH_MISMATCH: _info(False, "TDSPersistence.load_node", None, "persistence", "error", True, "Data and sidecar snapshot epochs disagree."),
    TDSResultCode.PERSIST_BATCH_READ_OK: _info(True, "TDSReader.read_many_result", "dict[name, object]", "persistence", "info", False, "All requested persisted entries were read."),
    TDSResultCode.PERSIST_BATCH_READ_PARTIAL: _info(False, "TDSReader.read_many_result", "dict[name, object|TDSResult]", "persistence", "warn", True, "Some persisted entries could not be read."),
    TDSResultCode.PERSIST_BATCH_READ_ERROR: _info(False, "TDSReader.read_many_result", None, "persistence", "error", True, "Batch persistence read failed."),
    TDSResultCode.PAYLOAD_DESERIALIZE_ERROR: _info(False, "payload decoder", None, "serialization", "error", False, "Stored payload could not be deserialized and was not returned as raw bytes."),
    TDSResultCode.PAYLOAD_FORMAT_UNSUPPORTED: _info(False, "payload decoder", None, "serialization", "error", False, "Stored payload format is unsupported."),
    TDSResultCode.JSON_WRITTEN: _info(True, "TDSDirectory.write_json", "JSON-safe object", "json", "info", False, "JSON entry was stored."),
    TDSResultCode.JSON_OVERWRITTEN: _info(True, "TDSDirectory.write_json", "JSON-safe object", "json", "info", False, "Existing JSON entry was overwritten."),
    TDSResultCode.JSON_EXISTS: _info(False, "TDSDirectory.write_json", None, "json", "warn", False, "JSON entry already exists and overwrite was not enabled."),
    TDSResultCode.TEXT_WRITTEN: _info(True, "TDSDirectory.write_text", "str", "text", "info", False, "Text entry was stored."),
    TDSResultCode.TEXT_OVERWRITTEN: _info(True, "TDSDirectory.write_text", "str", "text", "info", False, "Existing text entry was overwritten."),
    TDSResultCode.TEXT_EXISTS: _info(False, "TDSDirectory.write_text/write_text_chunked", None, "text", "warn", False, "Text entry already exists and overwrite was not enabled."),
    TDSResultCode.TEXT_TYPE_ERROR: _info(False, "text surfaces", None, "text", "error", False, "Text operation received a non-string value."),
    TDSResultCode.TEXT_CHUNK_SIZE_INVALID: _info(False, "TDSDirectory.write_text_chunked", None, "text", "error", False, "Chunk size must be positive."),
    TDSResultCode.TEXT_CHUNK_CHECKSUM_ERROR: _info(False, "TDSDirectory.write_text_chunked", None, "text", "error", True, "Chunk checksum batch was inconsistent."),
    TDSResultCode.TEXT_CHUNK_WRITE_ERROR: _info(False, "TDSDirectory.write_text_chunked", None, "text", "error", True, "Chunked text entry could not be written."),
    TDSResultCode.TEXT_CHUNKED_WRITTEN: _info(True, "TDSDirectory.write_text_chunked", None, "text", "info", False, "Chunked text entry was stored."),
    TDSResultCode.TEXT_CHUNKED_OVERWRITTEN: _info(True, "TDSDirectory.write_text_chunked", None, "text", "info", False, "Existing chunked text entry was overwritten."),
    TDSResultCode.TEXT_READ_OK: _info(True, "TDSDirectory.read_text_result", "str", "text", "info", False, "Text entry was read."),
    TDSResultCode.TEXT_READ_ERROR: _info(False, "TDSDirectory.read_text_result", None, "text", "error", False, "Text entry could not be read."),
    TDSResultCode.VAR_ADDED: _info(True, "VariableControl.addvar", "stored object", "variables", "info", False, "Variable was added."),
    TDSResultCode.VAR_CREATED: _info(True, "VariableControl.editvar/stalkvar", "stored object", "variables", "info", False, "Variable was created."),
    TDSResultCode.VAR_EDITED: _info(True, "VariableControl.editvar/stalkvar", "stored object", "variables", "info", False, "Variable was edited."),
    TDSResultCode.VAR_EXISTS: _info(False, "VariableControl.addvar/editvar", None, "variables", "warn", False, "Variable already exists."),
    TDSResultCode.VAR_LOCKED: _info(False, "VariableControl", None, "variables", "warn", False, "Variable is locked."),
    TDSResultCode.VAR_UNLOCKED: _info(True, "VariableControl.unlockvar", None, "variables", "info", False, "Variable was unlocked or lock state updated to unlocked."),
    TDSResultCode.VAR_MISSING: _info(False, "VariableControl", None, "variables", "warn", False, "Variable does not exist."),
    TDSResultCode.VAR_FOUND: _info(True, "VariableControl.findvar", "stored object", "variables", "info", False, "Variable was found."),
    TDSResultCode.VAR_INVALID_NAME: _info(False, "VariableControl.stalkvar", None, "variables", "error", False, "Variable name is invalid."),
    TDSResultCode.VAR_CHAIN_COLLISION: _info(False, "VariableControl.stalkvar", None, "variables", "error", False, "Stalk chain next name collides with an unrelated entry."),
    TDSResultCode.VAR_STALKED: _info(True, "VariableControl.stalkvar", "combined object", "variables", "info", False, "Stalk increment was created."),
    TDSResultCode.VAR_STALK_CLEARED: _info(True, "VariableControl.stalkvar", None, "variables", "info", False, "Stalk chain was cleared."),
    TDSResultCode.VAR_NOOP: _info(True, "VariableControl.stalkvar", None, "variables", "info", False, "Operation completed with no state change."),
    TDSResultCode.QUERY_ACCEPTED: _info(True, "query_requires_selector", None, "cluster", "info", False, "Cluster query selectors were accepted."),
    TDSResultCode.QUERY_REQUIRES_SELECTOR: _info(False, "query_requires_selector", None, "cluster", "warn", False, "Cluster query requires a selector or explicit scan=True."),
    TDSResultCode.SPIRAL_RANK_OK: _info(True, "NativeSpiralRankEngine.rank_result", "rank run dictionary", "spiral", "info", False, "Spiral rank completed."),
    TDSResultCode.SPIRAL_RANK_ERROR: _info(False, "NativeSpiralRankEngine.rank_result", None, "spiral", "error", True, "Spiral rank failed in a controlled non-halting path."),
    TDSResultCode.NATIVE_MANAGER_OK: _info(True, "NativeEngineManager.status_result", "native status snapshot", "native", "info", False, "Native engine manager status was produced."),
    TDSResultCode.NATIVE_ENGINE_LOADED: _info(True, "NativeEngineManager.load_result", "loaded native backend", "native", "info", False, "A compatible native engine was loaded."),
    TDSResultCode.NATIVE_ENGINE_FALLBACK: _info(True, "NativeEngineManager.load_result", "python fallback backend", "native", "warn", False, "Native engine was not used; TDS safely selected a Python fallback."),
    TDSResultCode.NATIVE_ENGINE_UNAVAILABLE: _info(False, "NativeEngineManager.load_result", None, "native", "warn", False, "No compiled native engine was available for this runtime platform."),
    TDSResultCode.NATIVE_ENGINE_INCOMPATIBLE: _info(False, "NativeEngineManager.load_result", None, "native", "error", False, "A native engine was present but did not satisfy the expected TDS native ABI or capabilities."),
    TDSResultCode.NATIVE_ENGINE_LOAD_ERROR: _info(False, "NativeEngineManager.load_result", None, "native", "error", False, "Native engine loading failed and was contained without halting TDS."),
    TDSResultCode.NATIVE_CAPABILITY_OK: _info(True, "NativeEngineManager.capabilities_result", "native capability snapshot", "native", "info", False, "Native platform and capability details were collected."),
}


TDS_RESULT_CODES: Dict[str, Dict[str, Any]] = {
    code.value: info.as_dict() for code, info in TDS_RESULT_REGISTRY.items()
}


def normalize_result_code(code: TDSResultCode | str) -> str:
    """Return the stable string value for a result code."""
    if isinstance(code, TDSResultCode):
        return code.value
    return str(code)


def result_info(code: TDSResultCode | str) -> TDSResultInfo | None:
    """Return registry metadata for *code*, or None when unknown."""
    value = normalize_result_code(code)
    try:
        return TDS_RESULT_REGISTRY[TDSResultCode(value)]
    except ValueError:
        return None


def known_result_codes() -> tuple[str, ...]:
    """Return the stable public TDSResult code catalog."""
    return tuple(sorted(code.value for code in TDSResultCode))


def is_known_result_code(code: TDSResultCode | str) -> bool:
    """True when *code* is part of the public TDSResult contract."""
    return result_info(code) is not None


@dataclass(frozen=True, slots=True)
class TDSResult:
    """Standard non-halting result envelope.

    Fields:
        ok: True for success, False for controlled failure.
        code: Stable machine-readable status/error code string.
        message: Human-readable explanation.
        name/path: Optional TDS location context.
        value: Optional payload for successful lookups/writes.
        meta: Optional structured diagnostics; never required for control flow.
    """
    ok: bool
    code: TDSResultCode | str = TDSResultCode.OK
    message: str = ""
    name: str = ""
    path: str = ""
    value: Any = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", normalize_result_code(self.code))

    @classmethod
    def success(cls, code: TDSResultCode | str = TDSResultCode.OK, message: str = "", **kw: Any) -> "TDSResult":
        return cls(True, code, message, **kw)

    @classmethod
    def fail(cls, code: TDSResultCode | str, message: str, **kw: Any) -> "TDSResult":
        return cls(False, code, message, **kw)

    @classmethod
    def error(cls, code: TDSResultCode | str, message: str, **kw: Any) -> "TDSResult":
        """Alias for fail() used by hardening code paths."""
        return cls.fail(code, message, **kw)

    @classmethod
    def from_exception(cls, code: TDSResultCode | str, exc: BaseException, **kw: Any) -> "TDSResult":
        """Convert an internal exception into a stable, non-throwing result."""
        meta = dict(kw.pop("meta", {}) or {})
        meta.setdefault("exception_type", type(exc).__name__)
        meta.setdefault("exception_message", str(exc))
        return cls(False, code, str(exc), meta=meta, **kw)

    @property
    def known_code(self) -> bool:
        return is_known_result_code(self.code)

    @property
    def info(self) -> TDSResultInfo | None:
        return result_info(self.code)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "code": normalize_result_code(self.code),
            "message": self.message,
            "name": self.name,
            "path": self.path,
            "value": self.value,
            "meta": dict(self.meta),
        }

    def __bool__(self) -> bool:
        return bool(self.ok)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, TDSResult):
            return self.as_dict() == other.as_dict()
        return self.value == other

    def __getitem__(self, key: Any) -> Any:
        return self.value[key]

    def __iter__(self):
        if self.value is None:
            return iter(())
        return iter(self.value)

    def __len__(self) -> int:
        try:
            return len(self.value)  # type: ignore[arg-type]
        except Exception:
            return 0

    def __array__(self, dtype: Any = None) -> Any:
        try:
            import numpy as _np
            return _np.asarray(self.value, dtype=dtype)
        except Exception:
            return self.value

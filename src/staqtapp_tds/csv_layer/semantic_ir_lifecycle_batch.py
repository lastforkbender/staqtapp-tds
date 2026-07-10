"""Atomic batch review for TDS Formal Semantic IR lifecycle transitions.

v3.5.2 extends the v3.5.1 in-memory lifecycle ledger with a bounded,
deterministic, all-or-nothing batch review contract.  Candidate validation,
current-evidence replay, and source-lifecycle validation occur once per batch.
Every transition remains independently authorized and the enclosing batch
requires a separate explicit review authorization.

The module never persists a Semantic IR artifact, mutates CSV or Interpole
state, enters the native storage hot path, controls native locks, or commits
semantic truth.  A failed batch returns the original lifecycle unchanged (or
no lifecycle when the batch started from the candidate foundation).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.version import __version__

from .manifest import validate_csv_id
from .semantic_ir import (
    CSV_SEMANTIC_IR_COMPATIBLE_RELEASE_VERSIONS,
    CSVSemanticIRCandidate,
    _candidate_projection,
    csv_semantic_ir_candidate_fingerprint,
    prepare_csv_semantic_ir_candidate,
    replay_csv_semantic_ir_candidate,
    validate_csv_semantic_ir_candidate,
)
from .semantic_ir_lifecycle import (
    CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS,
    CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT,
    CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
    CSV_SEMANTIC_IR_MAX_TRANSITIONS,
    CSV_SEMANTIC_IR_TRANSITION_AUTHORIZATION_CONTRACT_KEYS,
    CSV_SEMANTIC_IR_TRANSITION_REQUEST_CONTRACT_KEYS,
    CSVSemanticIRLifecycle,
    CSVSemanticIRLifecycleState,
    CSVSemanticIRTransitionAuthorization,
    CSVSemanticIRTransitionRecord,
    CSVSemanticIRTransitionRequest,
    _candidate_evidence_fingerprint,
    _canonical_json_bytes,
    _coerce_candidate,
    _coerce_request,
    _directory_state_fingerprint,
    _finalize_lifecycle,
    _initial_states,
    _is_sha256,
    _required_scope,
    _sha256_json,
    _valid_id,
    _valid_text,
    csv_semantic_ir_lifecycle_fingerprint,
    csv_semantic_ir_transition_authorization_fingerprint,
    csv_semantic_ir_transition_fingerprint,
    validate_csv_semantic_ir_lifecycle,
)


CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION = "1.0"
CSV_SEMANTIC_IR_MAX_BATCH_TRANSITIONS = 32
CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT = (
    CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT
)
CSV_SEMANTIC_IR_BATCH_AUTHORITY_SCOPES: tuple[str, ...] = (
    "review_transition_batch",
)

CSV_SEMANTIC_IR_BATCH_AUTHORIZATION_CONTRACT_KEYS: tuple[str, ...] = (
    "authorization_id",
    "actor_id",
    "authority_scope",
    "authorization_reference",
    "explicit_authorization",
)
CSV_SEMANTIC_IR_BATCH_ITEM_CONTRACT_KEYS: tuple[str, ...] = (
    "position",
    "request",
    "request_fingerprint",
    "transition_authorization_fingerprint",
)
CSV_SEMANTIC_IR_TRANSITION_BATCH_CONTRACT_KEYS: tuple[str, ...] = (
    "batch_id",
    "csv_id",
    "batch_version",
    "source_candidate_fingerprint",
    "source_lifecycle_fingerprint",
    "source_lifecycle_supplied",
    "handoff_closure_fingerprint",
    "raw_sha256",
    "batch_authorization",
    "batch_authorization_fingerprint",
    "items",
    "all_or_nothing",
    "batch_fingerprint",
    "payload_bytes",
    "payload_byte_limit",
)
CSV_SEMANTIC_IR_BATCH_RECEIPT_CONTRACT_KEYS: tuple[str, ...] = (
    "csv_id",
    "status",
    "batch_version",
    "suite_release_version",
    "mode",
    "receipt_fingerprint",
    "batch",
    "source_candidate_fingerprint",
    "source_lifecycle_fingerprint",
    "source_lifecycle_supplied",
    "handoff_closure_fingerprint",
    "raw_sha256",
    "result_lifecycle",
    "result_lifecycle_fingerprint",
    "result_transition_fingerprints",
    "batch_accepted",
    "all_or_nothing",
    "partial_acceptance",
    "source_candidate_validated",
    "source_candidate_replayed",
    "source_lifecycle_validated",
    "current_handoff_revalidated",
    "immutable_result",
    "deterministic_replay_required",
    "directory_state_fingerprint_before",
    "directory_state_fingerprint_after",
    "directory_state_unchanged",
    "payload_bytes",
    "payload_byte_limit",
    "tds_artifact_writes",
    "csv_artifact_mutation",
    "retroactive_csv_artifact_mutation",
    "interpole_mutation",
    "native_storage_writes",
    "native_storage_hot_path_touched",
    "native_storage_locks_controlled",
    "native_c_storage_engine_changed",
    "per_row_writes",
    "per_cell_writes",
    "semantic_artifact_persisted",
    "formal_ir_committed",
    "semantic_conclusions_committed",
    "committed_state_admitted",
    "superseded_state_admitted",
    "automatic_lifecycle_transitions",
    "warnings",
    "errors",
)

_MAX_BATCH_AUTHORIZATION_REFERENCE_CHARS = 512


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _request_projection(
    request: CSVSemanticIRTransitionRequest | Mapping[str, Any],
) -> dict[str, Any]:
    obj = (
        request
        if isinstance(request, CSVSemanticIRTransitionRequest)
        else CSVSemanticIRTransitionRequest.from_mapping(request)
    )
    return {
        "transition_id": obj.transition_id,
        "proposition_id": obj.proposition_id,
        "from_state": obj.from_state,
        "to_state": obj.to_state,
        "reason": obj.reason,
        "authorization": {
            "authorization_id": obj.authorization.authorization_id,
            "actor_id": obj.authorization.actor_id,
            "authority_scope": obj.authorization.authority_scope,
            "authorization_reference": obj.authorization.authorization_reference,
            "explicit_authorization": obj.authorization.explicit_authorization,
        },
    }


def csv_semantic_ir_transition_request_fingerprint(
    request: CSVSemanticIRTransitionRequest | Mapping[str, Any],
) -> str:
    """Return the deterministic fingerprint of one requested transition."""

    return _canonical_hash(_request_projection(request))


@dataclass(frozen=True, slots=True)
class CSVSemanticIRBatchAuthorization:
    """Explicit authorization for review of one complete transition batch."""

    authorization_id: str
    actor_id: str
    authority_scope: str
    authorization_reference: str
    explicit_authorization: bool = True

    @property
    def ok(self) -> bool:
        return (
            _valid_id(self.authorization_id)
            and _valid_id(self.actor_id)
            and self.authority_scope in CSV_SEMANTIC_IR_BATCH_AUTHORITY_SCOPES
            and _valid_text(
                self.authorization_reference,
                max_chars=_MAX_BATCH_AUTHORIZATION_REFERENCE_CHARS,
            )
            and self.explicit_authorization
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRBatchAuthorization":
        return cls(
            authorization_id=str(data.get("authorization_id", "")),
            actor_id=str(data.get("actor_id", "")),
            authority_scope=str(data.get("authority_scope", "")),
            authorization_reference=str(data.get("authorization_reference", "")),
            explicit_authorization=bool(data.get("explicit_authorization", False)),
        )


def _batch_authorization_projection(
    authorization: CSVSemanticIRBatchAuthorization | Mapping[str, Any],
) -> dict[str, Any]:
    obj = (
        authorization
        if isinstance(authorization, CSVSemanticIRBatchAuthorization)
        else CSVSemanticIRBatchAuthorization.from_mapping(authorization)
    )
    return {
        "authorization_id": obj.authorization_id,
        "actor_id": obj.actor_id,
        "authority_scope": obj.authority_scope,
        "authorization_reference": obj.authorization_reference,
        "explicit_authorization": obj.explicit_authorization,
    }


def csv_semantic_ir_batch_authorization_fingerprint(
    authorization: CSVSemanticIRBatchAuthorization | Mapping[str, Any],
) -> str:
    """Return the deterministic fingerprint for batch-review authorization."""

    return _canonical_hash(_batch_authorization_projection(authorization))


@dataclass(frozen=True, slots=True)
class CSVSemanticIRBatchItem:
    """One ordered transition request in an atomic review batch."""

    position: int
    request: CSVSemanticIRTransitionRequest
    request_fingerprint: str
    transition_authorization_fingerprint: str

    @property
    def ok(self) -> bool:
        return (
            self.position > 0
            and self.request.ok
            and _is_sha256(self.request_fingerprint)
            and self.request_fingerprint
            == csv_semantic_ir_transition_request_fingerprint(self.request)
            and _is_sha256(self.transition_authorization_fingerprint)
            and self.transition_authorization_fingerprint
            == csv_semantic_ir_transition_authorization_fingerprint(
                self.request.authorization
            )
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["request"] = self.request.to_dict()
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRBatchItem":
        raw_request = data.get("request", {})
        if not isinstance(raw_request, Mapping):
            raw_request = {}
        return cls(
            position=int(data.get("position", 0)),
            request=CSVSemanticIRTransitionRequest.from_mapping(raw_request),
            request_fingerprint=str(data.get("request_fingerprint", "")),
            transition_authorization_fingerprint=str(
                data.get("transition_authorization_fingerprint", "")
            ),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRTransitionBatch:
    """Immutable ordered input envelope for atomic lifecycle review."""

    batch_id: str
    csv_id: str
    batch_version: str
    source_candidate_fingerprint: str
    source_lifecycle_fingerprint: str
    source_lifecycle_supplied: bool
    handoff_closure_fingerprint: str
    raw_sha256: str
    batch_authorization: CSVSemanticIRBatchAuthorization
    batch_authorization_fingerprint: str
    items: tuple[CSVSemanticIRBatchItem, ...]
    all_or_nothing: bool
    batch_fingerprint: str
    payload_bytes: int
    payload_byte_limit: int = CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT

    @property
    def ok(self) -> bool:
        transition_ids = tuple(item.request.transition_id for item in self.items)
        proposition_ids = tuple(item.request.proposition_id for item in self.items)
        authorization_ids = tuple(
            item.request.authorization.authorization_id for item in self.items
        )
        return (
            _valid_id(self.batch_id)
            and _valid_id(self.csv_id)
            and self.batch_version == CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION
            and _is_sha256(self.source_candidate_fingerprint)
            and _is_sha256(self.source_lifecycle_fingerprint)
            and _is_sha256(self.handoff_closure_fingerprint)
            and _is_sha256(self.raw_sha256)
            and self.batch_authorization.ok
            and self.batch_authorization_fingerprint
            == csv_semantic_ir_batch_authorization_fingerprint(
                self.batch_authorization
            )
            and 0 < len(self.items) <= CSV_SEMANTIC_IR_MAX_BATCH_TRANSITIONS
            and tuple(item.position for item in self.items)
            == tuple(range(1, len(self.items) + 1))
            and all(item.ok for item in self.items)
            and len(set(transition_ids)) == len(transition_ids)
            and len(set(proposition_ids)) == len(proposition_ids)
            and len(set(authorization_ids)) == len(authorization_ids)
            and self.all_or_nothing
            and _is_sha256(self.batch_fingerprint)
            and self.batch_fingerprint
            == csv_semantic_ir_transition_batch_fingerprint(self)
            and self.payload_bytes == _transition_batch_payload_bytes(self)
            and self.payload_bytes <= self.payload_byte_limit
            and self.payload_byte_limit
            <= CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["batch_authorization"] = self.batch_authorization.to_dict()
        data["items"] = [item.to_dict() for item in self.items]
        data["item_count"] = len(self.items)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRTransitionBatch":
        raw_authorization = data.get("batch_authorization", {})
        if not isinstance(raw_authorization, Mapping):
            raw_authorization = {}
        raw_items = data.get("items", ()) or ()
        if not isinstance(raw_items, (list, tuple)):
            raw_items = ()
        return cls(
            batch_id=str(data.get("batch_id", "")),
            csv_id=str(data.get("csv_id", "")),
            batch_version=str(
                data.get("batch_version", CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION)
            ),
            source_candidate_fingerprint=str(
                data.get("source_candidate_fingerprint", "")
            ),
            source_lifecycle_fingerprint=str(
                data.get("source_lifecycle_fingerprint", "")
            ),
            source_lifecycle_supplied=bool(
                data.get("source_lifecycle_supplied", False)
            ),
            handoff_closure_fingerprint=str(
                data.get("handoff_closure_fingerprint", "")
            ),
            raw_sha256=str(data.get("raw_sha256", "")),
            batch_authorization=CSVSemanticIRBatchAuthorization.from_mapping(
                raw_authorization
            ),
            batch_authorization_fingerprint=str(
                data.get("batch_authorization_fingerprint", "")
            ),
            items=tuple(
                CSVSemanticIRBatchItem.from_mapping(item)
                for item in raw_items
                if isinstance(item, Mapping)
            ),
            all_or_nothing=bool(data.get("all_or_nothing", False)),
            batch_fingerprint=str(data.get("batch_fingerprint", "")),
            payload_bytes=int(data.get("payload_bytes", 0)),
            payload_byte_limit=int(
                data.get(
                    "payload_byte_limit",
                    CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT,
                )
            ),
        )


def _transition_batch_projection(
    batch: CSVSemanticIRTransitionBatch | Mapping[str, Any],
) -> dict[str, Any]:
    obj = (
        batch
        if isinstance(batch, CSVSemanticIRTransitionBatch)
        else CSVSemanticIRTransitionBatch.from_mapping(batch)
    )
    return {
        "batch_id": obj.batch_id,
        "csv_id": obj.csv_id,
        "batch_version": obj.batch_version,
        "source_candidate_fingerprint": obj.source_candidate_fingerprint,
        "source_lifecycle_fingerprint": obj.source_lifecycle_fingerprint,
        "source_lifecycle_supplied": obj.source_lifecycle_supplied,
        "handoff_closure_fingerprint": obj.handoff_closure_fingerprint,
        "raw_sha256": obj.raw_sha256,
        "batch_authorization": _batch_authorization_projection(
            obj.batch_authorization
        ),
        "batch_authorization_fingerprint": obj.batch_authorization_fingerprint,
        "items": [
            {
                "position": item.position,
                "request": _request_projection(item.request),
                "request_fingerprint": item.request_fingerprint,
                "transition_authorization_fingerprint": (
                    item.transition_authorization_fingerprint
                ),
            }
            for item in obj.items
        ],
        "all_or_nothing": obj.all_or_nothing,
        "payload_byte_limit": obj.payload_byte_limit,
    }


def csv_semantic_ir_transition_batch_fingerprint(
    batch: CSVSemanticIRTransitionBatch | Mapping[str, Any],
) -> str:
    """Return the deterministic fingerprint for the ordered batch envelope."""

    return _canonical_hash(_transition_batch_projection(batch))


def _transition_batch_payload_bytes(
    batch: CSVSemanticIRTransitionBatch | Mapping[str, Any],
) -> int:
    projection = _transition_batch_projection(batch)
    projection["batch_fingerprint"] = csv_semantic_ir_transition_batch_fingerprint(
        batch
    )
    return len(_canonical_json_bytes(projection))


def _finalize_transition_batch(
    batch: CSVSemanticIRTransitionBatch,
) -> CSVSemanticIRTransitionBatch:
    fingerprint = csv_semantic_ir_transition_batch_fingerprint(batch)
    interim = replace(batch, batch_fingerprint=fingerprint)
    return replace(interim, payload_bytes=_transition_batch_payload_bytes(interim))


@dataclass(frozen=True, slots=True)
class CSVSemanticIRBatchReceipt:
    """Immutable outcome and replay proof for an atomic lifecycle batch."""

    csv_id: str
    status: str
    batch_version: str
    suite_release_version: str
    mode: str
    receipt_fingerprint: str
    batch: CSVSemanticIRTransitionBatch
    source_candidate_fingerprint: str
    source_lifecycle_fingerprint: str
    source_lifecycle_supplied: bool
    handoff_closure_fingerprint: str
    raw_sha256: str
    result_lifecycle: CSVSemanticIRLifecycle | None
    result_lifecycle_fingerprint: str
    result_transition_fingerprints: tuple[str, ...]
    batch_accepted: bool
    all_or_nothing: bool = True
    partial_acceptance: bool = False
    source_candidate_validated: bool = True
    source_candidate_replayed: bool = True
    source_lifecycle_validated: bool = True
    current_handoff_revalidated: bool = True
    immutable_result: bool = True
    deterministic_replay_required: bool = True
    directory_state_fingerprint_before: str = ""
    directory_state_fingerprint_after: str = ""
    directory_state_unchanged: bool = True
    payload_bytes: int = 0
    payload_byte_limit: int = CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT
    tds_artifact_writes: int = 0
    csv_artifact_mutation: bool = False
    retroactive_csv_artifact_mutation: bool = False
    interpole_mutation: bool = False
    native_storage_writes: bool = False
    native_storage_hot_path_touched: bool = False
    native_storage_locks_controlled: bool = False
    native_c_storage_engine_changed: bool = False
    per_row_writes: bool = False
    per_cell_writes: bool = False
    semantic_artifact_persisted: bool = False
    formal_ir_committed: bool = False
    semantic_conclusions_committed: bool = False
    committed_state_admitted: bool = False
    superseded_state_admitted: bool = False
    automatic_lifecycle_transitions: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.status == "semantic_ir_transition_batch_ready"
            and self.batch_version == CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION
            and self.suite_release_version == __version__
            and self.mode == "formal_semantic_ir_atomic_batch_review"
            and _is_sha256(self.receipt_fingerprint)
            and self.receipt_fingerprint
            == csv_semantic_ir_batch_receipt_fingerprint(self)
            and self.batch.ok
            and self.source_candidate_fingerprint
            == self.batch.source_candidate_fingerprint
            and self.source_lifecycle_fingerprint
            == self.batch.source_lifecycle_fingerprint
            and self.source_lifecycle_supplied
            == self.batch.source_lifecycle_supplied
            and self.handoff_closure_fingerprint
            == self.batch.handoff_closure_fingerprint
            and self.raw_sha256 == self.batch.raw_sha256
            and self.result_lifecycle is not None
            and self.result_lifecycle.ok
            and self.result_lifecycle_fingerprint
            == self.result_lifecycle.lifecycle_fingerprint
            and self.result_lifecycle_fingerprint
            == csv_semantic_ir_lifecycle_fingerprint(self.result_lifecycle)
            and len(self.result_transition_fingerprints) == len(self.batch.items)
            and tuple(
                record.transition_fingerprint
                for record in self.result_lifecycle.history[-len(self.batch.items) :]
            )
            == self.result_transition_fingerprints
            and self.batch_accepted
            and self.all_or_nothing
            and not self.partial_acceptance
            and self.source_candidate_validated
            and self.source_candidate_replayed
            and self.source_lifecycle_validated
            and self.current_handoff_revalidated
            and self.immutable_result
            and self.deterministic_replay_required
            and self.directory_state_unchanged
            and _is_sha256(self.directory_state_fingerprint_before)
            and self.directory_state_fingerprint_before
            == self.directory_state_fingerprint_after
            and self.payload_bytes == _batch_receipt_payload_bytes(self)
            and self.payload_bytes <= self.payload_byte_limit
            and self.payload_byte_limit
            <= CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT
            and self.tds_artifact_writes == 0
            and not self.csv_artifact_mutation
            and not self.retroactive_csv_artifact_mutation
            and not self.interpole_mutation
            and not self.native_storage_writes
            and not self.native_storage_hot_path_touched
            and not self.native_storage_locks_controlled
            and not self.native_c_storage_engine_changed
            and not self.per_row_writes
            and not self.per_cell_writes
            and not self.semantic_artifact_persisted
            and not self.formal_ir_committed
            and not self.semantic_conclusions_committed
            and not self.committed_state_admitted
            and not self.superseded_state_admitted
            and not self.automatic_lifecycle_transitions
            and not self.errors
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["batch"] = self.batch.to_dict()
        data["result_lifecycle"] = (
            self.result_lifecycle.to_dict()
            if self.result_lifecycle is not None
            else None
        )
        data["result_transition_fingerprints"] = list(
            self.result_transition_fingerprints
        )
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRBatchReceipt":
        raw_batch = data.get("batch", {})
        if not isinstance(raw_batch, Mapping):
            raw_batch = {}
        raw_lifecycle = data.get("result_lifecycle")
        lifecycle = (
            CSVSemanticIRLifecycle.from_mapping(raw_lifecycle)
            if isinstance(raw_lifecycle, Mapping)
            else None
        )
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "semantic_ir_transition_batch_blocked")),
            batch_version=str(
                data.get("batch_version", CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION)
            ),
            suite_release_version=str(data.get("suite_release_version", "")),
            mode=str(data.get("mode", "formal_semantic_ir_atomic_batch_review")),
            receipt_fingerprint=str(data.get("receipt_fingerprint", "")),
            batch=CSVSemanticIRTransitionBatch.from_mapping(raw_batch),
            source_candidate_fingerprint=str(
                data.get("source_candidate_fingerprint", "")
            ),
            source_lifecycle_fingerprint=str(
                data.get("source_lifecycle_fingerprint", "")
            ),
            source_lifecycle_supplied=bool(
                data.get("source_lifecycle_supplied", False)
            ),
            handoff_closure_fingerprint=str(
                data.get("handoff_closure_fingerprint", "")
            ),
            raw_sha256=str(data.get("raw_sha256", "")),
            result_lifecycle=lifecycle,
            result_lifecycle_fingerprint=str(
                data.get("result_lifecycle_fingerprint", "")
            ),
            result_transition_fingerprints=tuple(
                str(value)
                for value in data.get("result_transition_fingerprints", ()) or ()
            ),
            batch_accepted=bool(data.get("batch_accepted", False)),
            all_or_nothing=bool(data.get("all_or_nothing", False)),
            partial_acceptance=bool(data.get("partial_acceptance", False)),
            source_candidate_validated=bool(
                data.get("source_candidate_validated", False)
            ),
            source_candidate_replayed=bool(
                data.get("source_candidate_replayed", False)
            ),
            source_lifecycle_validated=bool(
                data.get("source_lifecycle_validated", False)
            ),
            current_handoff_revalidated=bool(
                data.get("current_handoff_revalidated", False)
            ),
            immutable_result=bool(data.get("immutable_result", False)),
            deterministic_replay_required=bool(
                data.get("deterministic_replay_required", False)
            ),
            directory_state_fingerprint_before=str(
                data.get("directory_state_fingerprint_before", "")
            ),
            directory_state_fingerprint_after=str(
                data.get("directory_state_fingerprint_after", "")
            ),
            directory_state_unchanged=bool(
                data.get("directory_state_unchanged", False)
            ),
            payload_bytes=int(data.get("payload_bytes", 0)),
            payload_byte_limit=int(
                data.get(
                    "payload_byte_limit",
                    CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT,
                )
            ),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            csv_artifact_mutation=bool(data.get("csv_artifact_mutation", False)),
            retroactive_csv_artifact_mutation=bool(
                data.get("retroactive_csv_artifact_mutation", False)
            ),
            interpole_mutation=bool(data.get("interpole_mutation", False)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            native_storage_hot_path_touched=bool(
                data.get("native_storage_hot_path_touched", False)
            ),
            native_storage_locks_controlled=bool(
                data.get("native_storage_locks_controlled", False)
            ),
            native_c_storage_engine_changed=bool(
                data.get("native_c_storage_engine_changed", False)
            ),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            semantic_artifact_persisted=bool(
                data.get("semantic_artifact_persisted", False)
            ),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
            semantic_conclusions_committed=bool(
                data.get("semantic_conclusions_committed", False)
            ),
            committed_state_admitted=bool(
                data.get("committed_state_admitted", False)
            ),
            superseded_state_admitted=bool(
                data.get("superseded_state_admitted", False)
            ),
            automatic_lifecycle_transitions=bool(
                data.get("automatic_lifecycle_transitions", False)
            ),
            warnings=tuple(str(value) for value in data.get("warnings", ()) or ()),
            errors=tuple(str(value) for value in data.get("errors", ()) or ()),
        )


def _batch_receipt_projection(
    receipt: CSVSemanticIRBatchReceipt | Mapping[str, Any],
) -> dict[str, Any]:
    obj = (
        receipt
        if isinstance(receipt, CSVSemanticIRBatchReceipt)
        else CSVSemanticIRBatchReceipt.from_mapping(receipt)
    )
    return {
        "csv_id": obj.csv_id,
        "status": obj.status,
        "batch_version": obj.batch_version,
        "suite_release_version": obj.suite_release_version,
        "mode": obj.mode,
        "batch": {
            **_transition_batch_projection(obj.batch),
            "batch_fingerprint": obj.batch.batch_fingerprint,
            "payload_bytes": obj.batch.payload_bytes,
        },
        "source_candidate_fingerprint": obj.source_candidate_fingerprint,
        "source_lifecycle_fingerprint": obj.source_lifecycle_fingerprint,
        "source_lifecycle_supplied": obj.source_lifecycle_supplied,
        "handoff_closure_fingerprint": obj.handoff_closure_fingerprint,
        "raw_sha256": obj.raw_sha256,
        "result_lifecycle_fingerprint": obj.result_lifecycle_fingerprint,
        "result_transition_fingerprints": list(
            obj.result_transition_fingerprints
        ),
        "batch_accepted": obj.batch_accepted,
        "all_or_nothing": obj.all_or_nothing,
        "partial_acceptance": obj.partial_acceptance,
        "source_candidate_validated": obj.source_candidate_validated,
        "source_candidate_replayed": obj.source_candidate_replayed,
        "source_lifecycle_validated": obj.source_lifecycle_validated,
        "current_handoff_revalidated": obj.current_handoff_revalidated,
        "immutable_result": obj.immutable_result,
        "deterministic_replay_required": obj.deterministic_replay_required,
        "directory_state_fingerprint_before": obj.directory_state_fingerprint_before,
        "directory_state_fingerprint_after": obj.directory_state_fingerprint_after,
        "directory_state_unchanged": obj.directory_state_unchanged,
        "payload_byte_limit": obj.payload_byte_limit,
        "tds_artifact_writes": obj.tds_artifact_writes,
        "csv_artifact_mutation": obj.csv_artifact_mutation,
        "retroactive_csv_artifact_mutation": obj.retroactive_csv_artifact_mutation,
        "interpole_mutation": obj.interpole_mutation,
        "native_storage_writes": obj.native_storage_writes,
        "native_storage_hot_path_touched": obj.native_storage_hot_path_touched,
        "native_storage_locks_controlled": obj.native_storage_locks_controlled,
        "native_c_storage_engine_changed": obj.native_c_storage_engine_changed,
        "per_row_writes": obj.per_row_writes,
        "per_cell_writes": obj.per_cell_writes,
        "semantic_artifact_persisted": obj.semantic_artifact_persisted,
        "formal_ir_committed": obj.formal_ir_committed,
        "semantic_conclusions_committed": obj.semantic_conclusions_committed,
        "committed_state_admitted": obj.committed_state_admitted,
        "superseded_state_admitted": obj.superseded_state_admitted,
        "automatic_lifecycle_transitions": obj.automatic_lifecycle_transitions,
        "warnings": list(obj.warnings),
        "errors": list(obj.errors),
    }


def csv_semantic_ir_batch_receipt_fingerprint(
    receipt: CSVSemanticIRBatchReceipt | Mapping[str, Any],
) -> str:
    """Return the deterministic fingerprint for a complete batch receipt."""

    return _canonical_hash(_batch_receipt_projection(receipt))


def _batch_receipt_payload_bytes(
    receipt: CSVSemanticIRBatchReceipt | Mapping[str, Any],
) -> int:
    projection = _batch_receipt_projection(receipt)
    projection["receipt_fingerprint"] = csv_semantic_ir_batch_receipt_fingerprint(
        receipt
    )
    return len(_canonical_json_bytes(projection))


def _finalize_batch_receipt(
    receipt: CSVSemanticIRBatchReceipt,
) -> CSVSemanticIRBatchReceipt:
    fingerprint = csv_semantic_ir_batch_receipt_fingerprint(receipt)
    interim = replace(receipt, receipt_fingerprint=fingerprint)
    return replace(interim, payload_bytes=_batch_receipt_payload_bytes(interim))


def _empty_batch_authorization() -> CSVSemanticIRBatchAuthorization:
    return CSVSemanticIRBatchAuthorization("", "", "", "", False)


def _coerce_batch_authorization(
    authorization: CSVSemanticIRBatchAuthorization | Mapping[str, Any],
) -> tuple[CSVSemanticIRBatchAuthorization, tuple[str, ...]]:
    if isinstance(authorization, CSVSemanticIRBatchAuthorization):
        return authorization, ()
    raw = dict(authorization)
    missing = tuple(
        f"batch_authorization_contract_missing:{key}"
        for key in CSV_SEMANTIC_IR_BATCH_AUTHORIZATION_CONTRACT_KEYS
        if key not in raw
    )
    return CSVSemanticIRBatchAuthorization.from_mapping(raw), missing


def _build_batch_item(
    position: int,
    request: CSVSemanticIRTransitionRequest,
) -> CSVSemanticIRBatchItem:
    return CSVSemanticIRBatchItem(
        position=position,
        request=request,
        request_fingerprint=csv_semantic_ir_transition_request_fingerprint(request),
        transition_authorization_fingerprint=(
            csv_semantic_ir_transition_authorization_fingerprint(
                request.authorization
            )
        ),
    )


def _coerce_batch_requests(
    requests: Sequence[CSVSemanticIRTransitionRequest | Mapping[str, Any]]
    | Iterable[CSVSemanticIRTransitionRequest | Mapping[str, Any]],
) -> tuple[tuple[CSVSemanticIRBatchItem, ...], tuple[str, ...]]:
    errors: list[str] = []
    try:
        raw_requests = tuple(requests)
    except Exception as exc:
        return (), (f"transition_batch_requests_unreadable:{type(exc).__name__}:{exc}",)

    items: list[CSVSemanticIRBatchItem] = []
    for index, raw_request in enumerate(raw_requests, start=1):
        try:
            request, request_errors = _coerce_request(raw_request)
            errors.extend(f"batch_item:{index}:{value}" for value in request_errors)
            items.append(_build_batch_item(index, request))
        except Exception as exc:
            errors.append(
                f"batch_item:{index}:transition_request_unreadable:{type(exc).__name__}:{exc}"
            )
    return tuple(items), tuple(errors)


def _replay_candidate_once(
    directory: TDSDirectory,
    csv_id: str,
    candidate: CSVSemanticIRCandidate,
    candidate_raw: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Replay current or compatible legacy candidate evidence exactly once."""

    if candidate.suite_release_version == __version__:
        replay = replay_csv_semantic_ir_candidate(directory, csv_id, candidate_raw)
        errors = tuple(replay.errors)
        if not replay.ok and not errors:
            errors = ("semantic_ir_source_candidate_replay_blocked",)
        return replay.ok, errors, tuple(replay.warnings)

    if candidate.suite_release_version not in CSV_SEMANTIC_IR_COMPATIBLE_RELEASE_VERSIONS:
        return (
            False,
            (
                f"semantic_ir_source_candidate_release_incompatible:{candidate.suite_release_version}",
            ),
            (),
        )

    declarations = tuple(item.as_declaration() for item in candidate.propositions)
    rebuilt = prepare_csv_semantic_ir_candidate(
        directory,
        csv_id,
        declarations,
        explicit_opt_in=True,
        payload_byte_limit=candidate.payload_byte_limit,
    )
    if not rebuilt.ok:
        errors = tuple(f"semantic_ir_rebuild:{value}" for value in rebuilt.errors)
        if not errors:
            errors = ("semantic_ir_rebuild_blocked",)
        return False, errors, tuple(rebuilt.warnings)

    source_projection = _candidate_projection(candidate)
    rebuilt_projection = _candidate_projection(rebuilt)
    for projection in (source_projection, rebuilt_projection):
        projection.pop("suite_release_version", None)
        projection.pop("directory_state_fingerprint_before", None)
        projection.pop("directory_state_fingerprint_after", None)
    mismatched = tuple(
        key
        for key in sorted(set(source_projection) | set(rebuilt_projection))
        if source_projection.get(key) != rebuilt_projection.get(key)
    )
    if mismatched:
        return (
            False,
            tuple(f"semantic_ir_compatible_replay_mismatch:{key}" for key in mismatched),
            tuple(rebuilt.warnings),
        )
    return (
        True,
        (),
        (
            f"semantic_ir_compatible_release_replay:{candidate.suite_release_version}->{__version__}",
        ),
    )


def _make_transition_record(
    *,
    candidate: CSVSemanticIRCandidate,
    request: CSVSemanticIRTransitionRequest,
    current: CSVSemanticIRLifecycleState,
    history: tuple[CSVSemanticIRTransitionRecord, ...],
) -> CSVSemanticIRTransitionRecord:
    proposition = next(
        item
        for item in candidate.propositions
        if item.proposition_id == request.proposition_id
    )
    authorization_fingerprint = (
        csv_semantic_ir_transition_authorization_fingerprint(request.authorization)
    )
    predecessor_fingerprint = (
        history[-1].transition_fingerprint
        if history
        else candidate.candidate_fingerprint
    )
    proposition_predecessor_fingerprint = (
        current.last_transition_fingerprint
        if current.transition_count > 0
        else candidate.candidate_fingerprint
    )
    record = CSVSemanticIRTransitionRecord(
        sequence=len(history) + 1,
        transition_id=request.transition_id,
        proposition_id=request.proposition_id,
        from_state=request.from_state,
        to_state=request.to_state,
        reason=request.reason,
        authorization=request.authorization,
        authorization_fingerprint=authorization_fingerprint,
        source_candidate_fingerprint=candidate.candidate_fingerprint,
        source_declaration_fingerprint=proposition.declaration_fingerprint,
        source_evidence_fingerprint=_candidate_evidence_fingerprint(
            candidate,
            proposition.proposition_id,
        ),
        handoff_closure_fingerprint=candidate.handoff_closure_fingerprint,
        predecessor_fingerprint=predecessor_fingerprint,
        proposition_predecessor_fingerprint=proposition_predecessor_fingerprint,
        transition_fingerprint="",
    )
    return replace(
        record,
        transition_fingerprint=csv_semantic_ir_transition_fingerprint(record),
    )


def _append_prevalidated_transition(
    *,
    candidate: CSVSemanticIRCandidate,
    request: CSVSemanticIRTransitionRequest,
    current_states: tuple[CSVSemanticIRLifecycleState, ...],
    history: tuple[CSVSemanticIRTransitionRecord, ...],
) -> tuple[
    tuple[CSVSemanticIRLifecycleState, ...],
    tuple[CSVSemanticIRTransitionRecord, ...],
    CSVSemanticIRTransitionRecord,
]:
    state_by_id = {item.proposition_id: item for item in current_states}
    current = state_by_id[request.proposition_id]
    record = _make_transition_record(
        candidate=candidate,
        request=request,
        current=current,
        history=history,
    )
    if not record.ok:
        raise ValueError(f"resolved_transition_record_invalid:{request.transition_id}")
    proposition_predecessor_fingerprint = (
        current.last_transition_fingerprint
        if current.transition_count > 0
        else candidate.candidate_fingerprint
    )
    updated = CSVSemanticIRLifecycleState(
        proposition_id=current.proposition_id,
        state=request.to_state,
        source_declaration_fingerprint=current.source_declaration_fingerprint,
        predecessor_fingerprint=proposition_predecessor_fingerprint,
        last_transition_fingerprint=record.transition_fingerprint,
        transition_count=current.transition_count + 1,
    )
    new_states = tuple(
        updated if item.proposition_id == updated.proposition_id else item
        for item in current_states
    )
    return new_states, history + (record,), record


def _blocked_receipt(
    *,
    csv_id: str,
    batch: CSVSemanticIRTransitionBatch,
    state_before: str,
    state_after: str,
    payload_byte_limit: int,
    result_lifecycle: CSVSemanticIRLifecycle | None,
    source_candidate_fingerprint: str,
    source_lifecycle_fingerprint: str,
    source_lifecycle_supplied: bool,
    handoff_closure_fingerprint: str,
    raw_sha256: str,
    source_candidate_validated: bool,
    source_candidate_replayed: bool,
    source_lifecycle_validated: bool,
    current_handoff_revalidated: bool,
    errors: Iterable[str],
    warnings: Iterable[str] = (),
) -> CSVSemanticIRBatchReceipt:
    unchanged = state_before == state_after
    fallback_fingerprint = (
        result_lifecycle.lifecycle_fingerprint
        if result_lifecycle is not None
        else source_lifecycle_fingerprint
    )
    receipt = CSVSemanticIRBatchReceipt(
        csv_id=csv_id,
        status="semantic_ir_transition_batch_blocked",
        batch_version=CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
        suite_release_version=__version__,
        mode="formal_semantic_ir_atomic_batch_review",
        receipt_fingerprint="",
        batch=batch,
        source_candidate_fingerprint=source_candidate_fingerprint,
        source_lifecycle_fingerprint=source_lifecycle_fingerprint,
        source_lifecycle_supplied=source_lifecycle_supplied,
        handoff_closure_fingerprint=handoff_closure_fingerprint,
        raw_sha256=raw_sha256,
        result_lifecycle=result_lifecycle,
        result_lifecycle_fingerprint=fallback_fingerprint,
        result_transition_fingerprints=(),
        batch_accepted=False,
        source_candidate_validated=source_candidate_validated,
        source_candidate_replayed=source_candidate_replayed,
        source_lifecycle_validated=source_lifecycle_validated,
        current_handoff_revalidated=current_handoff_revalidated,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        payload_byte_limit=payload_byte_limit,
        tds_artifact_writes=0 if unchanged else 1,
        csv_artifact_mutation=not unchanged,
        warnings=tuple(dict.fromkeys(str(value) for value in warnings)),
        errors=tuple(dict.fromkeys(str(value) for value in errors)),
    )
    return _finalize_batch_receipt(receipt)


def prepare_csv_semantic_ir_transition_batch(
    directory: TDSDirectory,
    csv_id: str,
    source_candidate: CSVSemanticIRCandidate | Mapping[str, Any],
    requests: Sequence[CSVSemanticIRTransitionRequest | Mapping[str, Any]]
    | Iterable[CSVSemanticIRTransitionRequest | Mapping[str, Any]],
    *,
    batch_id: str,
    batch_authorization: CSVSemanticIRBatchAuthorization | Mapping[str, Any],
    source_lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any] | None = None,
    payload_byte_limit: int = CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT,
) -> CSVSemanticIRBatchReceipt:
    """Review and accept a bounded transition batch atomically in memory.

    The source candidate is validated and replayed once.  The source lifecycle
    is validated once when supplied.  Every item is preflighted against the
    batch-entry lifecycle state before any result lifecycle is constructed.
    """

    effective_limit = max(
        1024,
        min(
            int(payload_byte_limit),
            CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT,
        ),
    )
    safe_id = str(csv_id)
    empty_state = _sha256_json([])

    try:
        authorization_obj, authorization_errors = _coerce_batch_authorization(
            batch_authorization
        )
    except Exception as exc:
        authorization_obj = _empty_batch_authorization()
        authorization_errors = (
            f"batch_authorization_unreadable:{type(exc).__name__}:{exc}",
        )
    items, item_contract_errors = _coerce_batch_requests(requests)

    try:
        validate_csv_id(safe_id)
        state_before = _directory_state_fingerprint(directory, safe_id)
    except Exception as exc:
        batch = _finalize_transition_batch(
            CSVSemanticIRTransitionBatch(
                batch_id=str(batch_id),
                csv_id=safe_id,
                batch_version=CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
                source_candidate_fingerprint="",
                source_lifecycle_fingerprint="",
                source_lifecycle_supplied=source_lifecycle is not None,
                handoff_closure_fingerprint="",
                raw_sha256="",
                batch_authorization=authorization_obj,
                batch_authorization_fingerprint=(
                    csv_semantic_ir_batch_authorization_fingerprint(
                        authorization_obj
                    )
                ),
                items=items,
                all_or_nothing=True,
                batch_fingerprint="",
                payload_bytes=0,
                payload_byte_limit=effective_limit,
            )
        )
        return _blocked_receipt(
            csv_id=safe_id,
            batch=batch,
            state_before=empty_state,
            state_after=empty_state,
            payload_byte_limit=effective_limit,
            result_lifecycle=None,
            source_candidate_fingerprint="",
            source_lifecycle_fingerprint="",
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint="",
            raw_sha256="",
            source_candidate_validated=False,
            source_candidate_replayed=False,
            source_lifecycle_validated=source_lifecycle is None,
            current_handoff_revalidated=False,
            errors=(
                *authorization_errors,
                *item_contract_errors,
                f"csv_id_unsafe:{type(exc).__name__}:{exc}",
            ),
        )

    errors: list[str] = [*authorization_errors, *item_contract_errors]
    warnings: list[str] = []
    candidate: CSVSemanticIRCandidate | None = None
    candidate_raw: Mapping[str, Any] = {}
    candidate_validated = False
    candidate_replayed = False
    source_lifecycle_validated = source_lifecycle is None
    prior: CSVSemanticIRLifecycle | None = None
    current_states: tuple[CSVSemanticIRLifecycleState, ...] = ()
    history: tuple[CSVSemanticIRTransitionRecord, ...] = ()
    source_candidate_fingerprint = ""
    source_lifecycle_fingerprint = ""
    handoff_closure_fingerprint = ""
    raw_sha256 = ""

    try:
        candidate, candidate_raw = _coerce_candidate(source_candidate)
        source_candidate_fingerprint = candidate.candidate_fingerprint
        handoff_closure_fingerprint = candidate.handoff_closure_fingerprint
        raw_sha256 = candidate.raw_sha256
        source_lifecycle_fingerprint = candidate.candidate_fingerprint
    except Exception as exc:
        errors.append(
            f"semantic_ir_source_candidate_unreadable:{type(exc).__name__}:{exc}"
        )

    if candidate is not None:
        candidate_validation = validate_csv_semantic_ir_candidate(candidate_raw)
        candidate_validated = candidate_validation.ok and candidate.ok
        if not candidate_validated:
            errors.extend(
                f"semantic_ir_source_candidate:{value}"
                for value in candidate_validation.errors
            )
            errors.extend(
                f"semantic_ir_source_candidate:{value}" for value in candidate.errors
            )
            if not candidate_validation.errors and not candidate.errors:
                errors.append("semantic_ir_source_candidate_not_ready")
        if candidate.csv_id != safe_id:
            errors.append("semantic_ir_source_candidate_csv_id_mismatch")
        if candidate.candidate_fingerprint != csv_semantic_ir_candidate_fingerprint(
            candidate
        ):
            errors.append("semantic_ir_source_candidate_fingerprint_mismatch")

        if not errors:
            (
                candidate_replayed,
                candidate_replay_errors,
                candidate_replay_warnings,
            ) = _replay_candidate_once(
                directory,
                safe_id,
                candidate,
                candidate_raw,
            )
            warnings.extend(candidate_replay_warnings)
            if not candidate_replayed:
                errors.extend(
                    f"semantic_ir_source_candidate_replay:{value}"
                    for value in candidate_replay_errors
                )

        current_states = _initial_states(candidate) if candidate.ok else ()

    if source_lifecycle is not None and candidate is not None and not errors:
        try:
            lifecycle_raw = (
                source_lifecycle.to_dict()
                if isinstance(source_lifecycle, CSVSemanticIRLifecycle)
                else dict(source_lifecycle)
            )
            prior = (
                source_lifecycle
                if isinstance(source_lifecycle, CSVSemanticIRLifecycle)
                else CSVSemanticIRLifecycle.from_mapping(lifecycle_raw)
            )
            prior_validation = validate_csv_semantic_ir_lifecycle(
                lifecycle_raw,
                source_candidate=candidate_raw,
            )
            source_lifecycle_validated = prior_validation.ok and prior.ok
            if not source_lifecycle_validated:
                errors.extend(
                    f"semantic_ir_source_lifecycle:{value}"
                    for value in prior_validation.errors
                )
                errors.extend(
                    f"semantic_ir_source_lifecycle:{value}" for value in prior.errors
                )
                if not prior_validation.errors and not prior.errors:
                    errors.append("semantic_ir_source_lifecycle_not_ready")
            elif prior.csv_id != safe_id:
                errors.append("semantic_ir_source_lifecycle_csv_id_mismatch")
            elif (
                prior.source_candidate_fingerprint
                != candidate.candidate_fingerprint
            ):
                errors.append("semantic_ir_source_lifecycle_candidate_mismatch")
            elif (
                prior.handoff_closure_fingerprint
                != candidate.handoff_closure_fingerprint
            ):
                errors.append("semantic_ir_source_lifecycle_handoff_mismatch")
            else:
                source_lifecycle_fingerprint = prior.lifecycle_fingerprint
                current_states = prior.current_states
                history = prior.history
        except Exception as exc:
            errors.append(
                f"semantic_ir_source_lifecycle_unreadable:{type(exc).__name__}:{exc}"
            )

    batch = _finalize_transition_batch(
        CSVSemanticIRTransitionBatch(
            batch_id=str(batch_id),
            csv_id=safe_id,
            batch_version=CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
            source_candidate_fingerprint=source_candidate_fingerprint,
            source_lifecycle_fingerprint=source_lifecycle_fingerprint,
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint=handoff_closure_fingerprint,
            raw_sha256=raw_sha256,
            batch_authorization=authorization_obj,
            batch_authorization_fingerprint=(
                csv_semantic_ir_batch_authorization_fingerprint(authorization_obj)
            ),
            items=items,
            all_or_nothing=True,
            batch_fingerprint="",
            payload_bytes=0,
            payload_byte_limit=effective_limit,
        )
    )

    if not _valid_id(batch.batch_id):
        errors.append("transition_batch_id_invalid")
    if not authorization_obj.explicit_authorization:
        errors.append("transition_batch_explicit_authorization_required")
    if not authorization_obj.ok:
        errors.append("transition_batch_authorization_invalid")
    if not items:
        errors.append("transition_batch_empty")
    if len(items) > CSV_SEMANTIC_IR_MAX_BATCH_TRANSITIONS:
        errors.append(
            f"transition_batch_count_exceeded:{len(items)}>{CSV_SEMANTIC_IR_MAX_BATCH_TRANSITIONS}"
        )
    if len(history) + len(items) > CSV_SEMANTIC_IR_MAX_TRANSITIONS:
        errors.append(
            f"semantic_ir_transition_count_exceeded:{len(history) + len(items)}>{CSV_SEMANTIC_IR_MAX_TRANSITIONS}"
        )
    if batch.payload_bytes > effective_limit:
        errors.append(
            f"transition_batch_payload_too_large:{batch.payload_bytes}>{effective_limit}"
        )

    transition_ids = tuple(item.request.transition_id for item in items)
    proposition_ids = tuple(item.request.proposition_id for item in items)
    authorization_ids = tuple(
        item.request.authorization.authorization_id for item in items
    )
    duplicate_transition_ids = sorted(
        {value for value in transition_ids if transition_ids.count(value) > 1}
    )
    duplicate_proposition_ids = sorted(
        {value for value in proposition_ids if proposition_ids.count(value) > 1}
    )
    duplicate_authorization_ids = sorted(
        {value for value in authorization_ids if authorization_ids.count(value) > 1}
    )
    errors.extend(
        f"transition_batch_duplicate_transition_id:{value}"
        for value in duplicate_transition_ids
    )
    errors.extend(
        f"transition_batch_duplicate_proposition_id:{value}"
        for value in duplicate_proposition_ids
    )
    errors.extend(
        f"transition_batch_duplicate_authorization_id:{value}"
        for value in duplicate_authorization_ids
    )

    existing_transition_ids = {record.transition_id for record in history}
    existing_authorization_ids = {
        record.authorization.authorization_id for record in history
    }
    state_by_id = {state.proposition_id: state for state in current_states}
    proposition_by_id = (
        {item.proposition_id: item for item in candidate.propositions}
        if candidate is not None
        else {}
    )

    for item in items:
        request = item.request
        prefix = f"batch_item:{item.position}:transition:{request.transition_id or '<empty>'}"
        if not item.ok:
            errors.append(f"{prefix}:batch_item_invalid")
        if not _valid_id(request.transition_id):
            errors.append(f"{prefix}:transition_id_invalid")
        if not _valid_id(request.proposition_id):
            errors.append(f"{prefix}:proposition_id_invalid")
        if (request.from_state, request.to_state) not in CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS:
            errors.append(
                f"{prefix}:transition_not_admitted:{request.from_state}->{request.to_state}"
            )
        if request.to_state in {"committed", "superseded"}:
            errors.append(f"{prefix}:deferred_state_not_admitted:{request.to_state}")
        if not request.authorization.explicit_authorization:
            errors.append(f"{prefix}:explicit_authorization_required")
        if not request.authorization.ok:
            errors.append(f"{prefix}:authorization_invalid")
        expected_scope = _required_scope(request.to_state)
        if request.authorization.authority_scope != expected_scope:
            errors.append(
                f"{prefix}:authorization_scope_mismatch:{request.authorization.authority_scope}!={expected_scope}"
            )
        if request.transition_id in existing_transition_ids:
            errors.append(f"{prefix}:duplicate_transition_id_in_source_lifecycle")
        if request.authorization.authorization_id in existing_authorization_ids:
            errors.append(
                f"{prefix}:duplicate_authorization_id_in_source_lifecycle"
            )
        current = state_by_id.get(request.proposition_id)
        proposition = proposition_by_id.get(request.proposition_id)
        if current is None or proposition is None:
            errors.append(f"{prefix}:proposition_not_found:{request.proposition_id}")
        elif current.state != request.from_state:
            errors.append(
                f"{prefix}:predecessor_state_mismatch:{request.from_state}!={current.state}"
            )

    state_after_preflight = _directory_state_fingerprint(directory, safe_id)
    if state_after_preflight != state_before:
        errors.append("semantic_ir_transition_batch_mutated_tds_directory_state")

    if errors or candidate is None:
        return _blocked_receipt(
            csv_id=safe_id,
            batch=batch,
            state_before=state_before,
            state_after=state_after_preflight,
            payload_byte_limit=effective_limit,
            result_lifecycle=prior,
            source_candidate_fingerprint=source_candidate_fingerprint,
            source_lifecycle_fingerprint=source_lifecycle_fingerprint,
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint=handoff_closure_fingerprint,
            raw_sha256=raw_sha256,
            source_candidate_validated=candidate_validated,
            source_candidate_replayed=candidate_replayed,
            source_lifecycle_validated=source_lifecycle_validated,
            current_handoff_revalidated=candidate_replayed,
            errors=errors,
            warnings=warnings,
        )

    working_states = current_states
    working_history = history
    accepted_records: list[CSVSemanticIRTransitionRecord] = []
    try:
        for item in items:
            working_states, working_history, record = _append_prevalidated_transition(
                candidate=candidate,
                request=item.request,
                current_states=working_states,
                history=working_history,
            )
            accepted_records.append(record)
    except Exception as exc:
        state_after = _directory_state_fingerprint(directory, safe_id)
        return _blocked_receipt(
            csv_id=safe_id,
            batch=batch,
            state_before=state_before,
            state_after=state_after,
            payload_byte_limit=effective_limit,
            result_lifecycle=prior,
            source_candidate_fingerprint=source_candidate_fingerprint,
            source_lifecycle_fingerprint=source_lifecycle_fingerprint,
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint=handoff_closure_fingerprint,
            raw_sha256=raw_sha256,
            source_candidate_validated=True,
            source_candidate_replayed=True,
            source_lifecycle_validated=source_lifecycle_validated,
            current_handoff_revalidated=True,
            errors=(f"transition_batch_atomic_simulation_failed:{type(exc).__name__}:{exc}",),
            warnings=warnings,
        )

    state_after = _directory_state_fingerprint(directory, safe_id)
    if state_after != state_before:
        return _blocked_receipt(
            csv_id=safe_id,
            batch=batch,
            state_before=state_before,
            state_after=state_after,
            payload_byte_limit=effective_limit,
            result_lifecycle=prior,
            source_candidate_fingerprint=source_candidate_fingerprint,
            source_lifecycle_fingerprint=source_lifecycle_fingerprint,
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint=handoff_closure_fingerprint,
            raw_sha256=raw_sha256,
            source_candidate_validated=True,
            source_candidate_replayed=True,
            source_lifecycle_validated=source_lifecycle_validated,
            current_handoff_revalidated=True,
            errors=("semantic_ir_transition_batch_mutated_tds_directory_state",),
            warnings=warnings,
        )

    lifecycle = _finalize_lifecycle(
        CSVSemanticIRLifecycle(
            csv_id=safe_id,
            status="semantic_ir_lifecycle_ready",
            lifecycle_version=CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
            suite_release_version=__version__,
            mode="formal_semantic_ir_lifecycle",
            lifecycle_fingerprint="",
            source_candidate_fingerprint=candidate.candidate_fingerprint,
            handoff_closure_fingerprint=candidate.handoff_closure_fingerprint,
            raw_sha256=candidate.raw_sha256,
            current_states=working_states,
            history=working_history,
            allowed_transitions=CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS,
            source_candidate_validated=True,
            source_candidate_replayed=True,
            current_handoff_revalidated=True,
            lifecycle_transitions_applied=True,
            directory_state_fingerprint_before=state_before,
            directory_state_fingerprint_after=state_after,
            directory_state_unchanged=True,
            payload_byte_limit=min(
                effective_limit,
                CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT,
            ),
            tds_artifact_writes=0,
            warnings=tuple(dict.fromkeys(warnings)),
            errors=(),
        )
    )

    if lifecycle.payload_bytes > lifecycle.payload_byte_limit or not lifecycle.ok:
        detail = (
            f"semantic_ir_lifecycle_payload_too_large:{lifecycle.payload_bytes}>{lifecycle.payload_byte_limit}"
            if lifecycle.payload_bytes > lifecycle.payload_byte_limit
            else "semantic_ir_transition_batch_result_lifecycle_invalid"
        )
        return _blocked_receipt(
            csv_id=safe_id,
            batch=batch,
            state_before=state_before,
            state_after=state_after,
            payload_byte_limit=effective_limit,
            result_lifecycle=prior,
            source_candidate_fingerprint=source_candidate_fingerprint,
            source_lifecycle_fingerprint=source_lifecycle_fingerprint,
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint=handoff_closure_fingerprint,
            raw_sha256=raw_sha256,
            source_candidate_validated=True,
            source_candidate_replayed=True,
            source_lifecycle_validated=source_lifecycle_validated,
            current_handoff_revalidated=True,
            errors=(detail,),
            warnings=warnings,
        )

    receipt = _finalize_batch_receipt(
        CSVSemanticIRBatchReceipt(
            csv_id=safe_id,
            status="semantic_ir_transition_batch_ready",
            batch_version=CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
            suite_release_version=__version__,
            mode="formal_semantic_ir_atomic_batch_review",
            receipt_fingerprint="",
            batch=batch,
            source_candidate_fingerprint=candidate.candidate_fingerprint,
            source_lifecycle_fingerprint=source_lifecycle_fingerprint,
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint=candidate.handoff_closure_fingerprint,
            raw_sha256=candidate.raw_sha256,
            result_lifecycle=lifecycle,
            result_lifecycle_fingerprint=lifecycle.lifecycle_fingerprint,
            result_transition_fingerprints=tuple(
                record.transition_fingerprint for record in accepted_records
            ),
            batch_accepted=True,
            source_candidate_validated=True,
            source_candidate_replayed=True,
            source_lifecycle_validated=source_lifecycle_validated,
            current_handoff_revalidated=True,
            directory_state_fingerprint_before=state_before,
            directory_state_fingerprint_after=state_after,
            directory_state_unchanged=True,
            payload_byte_limit=effective_limit,
            warnings=tuple(dict.fromkeys(warnings)),
            errors=(),
        )
    )

    if receipt.payload_bytes > effective_limit or not receipt.ok:
        detail = (
            f"transition_batch_receipt_payload_too_large:{receipt.payload_bytes}>{effective_limit}"
            if receipt.payload_bytes > effective_limit
            else "transition_batch_receipt_invalid"
        )
        return _blocked_receipt(
            csv_id=safe_id,
            batch=batch,
            state_before=state_before,
            state_after=state_after,
            payload_byte_limit=effective_limit,
            result_lifecycle=prior,
            source_candidate_fingerprint=source_candidate_fingerprint,
            source_lifecycle_fingerprint=source_lifecycle_fingerprint,
            source_lifecycle_supplied=source_lifecycle is not None,
            handoff_closure_fingerprint=handoff_closure_fingerprint,
            raw_sha256=raw_sha256,
            source_candidate_validated=True,
            source_candidate_replayed=True,
            source_lifecycle_validated=source_lifecycle_validated,
            current_handoff_revalidated=True,
            errors=(detail,),
            warnings=warnings,
        )
    return receipt


@dataclass(frozen=True, slots=True)
class CSVSemanticIRBatchValidationReport:
    """Exact serialized-contract and lineage validation for a batch receipt."""

    csv_id: str
    status: str
    batch_version: str
    source_receipt_fingerprint: str
    recomputed_receipt_fingerprint: str
    source_batch_fingerprint: str
    recomputed_batch_fingerprint: str
    source_payload_bytes: int
    recomputed_payload_bytes: int
    payload_byte_limit: int
    missing_receipt_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_batch_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_batch_authorization_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_item_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_request_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_transition_authorization_keys: tuple[str, ...] = field(
        default_factory=tuple
    )
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.status == "semantic_ir_transition_batch_valid"
            and self.batch_version == CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION
            and self.source_receipt_fingerprint
            == self.recomputed_receipt_fingerprint
            and self.source_batch_fingerprint == self.recomputed_batch_fingerprint
            and self.source_payload_bytes == self.recomputed_payload_bytes
            and self.source_payload_bytes <= self.payload_byte_limit
            and not self.missing_receipt_keys
            and not self.missing_batch_keys
            and not self.missing_batch_authorization_keys
            and not self.missing_item_keys
            and not self.missing_request_keys
            and not self.missing_transition_authorization_keys
            and not self.errors
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def validate_csv_semantic_ir_transition_batch(
    receipt: CSVSemanticIRBatchReceipt | Mapping[str, Any],
    *,
    source_candidate: CSVSemanticIRCandidate | Mapping[str, Any] | None = None,
    source_lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any] | None = None,
) -> CSVSemanticIRBatchValidationReport:
    """Validate a serialized batch receipt and its nested lifecycle result."""

    try:
        raw = receipt.to_dict() if isinstance(receipt, CSVSemanticIRBatchReceipt) else dict(receipt)
        obj = receipt if isinstance(receipt, CSVSemanticIRBatchReceipt) else CSVSemanticIRBatchReceipt.from_mapping(raw)
    except Exception as exc:
        return CSVSemanticIRBatchValidationReport(
            csv_id="",
            status="semantic_ir_transition_batch_blocked",
            batch_version=CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
            source_receipt_fingerprint="",
            recomputed_receipt_fingerprint="",
            source_batch_fingerprint="",
            recomputed_batch_fingerprint="",
            source_payload_bytes=0,
            recomputed_payload_bytes=0,
            payload_byte_limit=CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT,
            errors=(f"transition_batch_receipt_unreadable:{type(exc).__name__}:{exc}",),
        )

    errors: list[str] = []
    missing_receipt_keys = tuple(
        key for key in CSV_SEMANTIC_IR_BATCH_RECEIPT_CONTRACT_KEYS if key not in raw
    )
    errors.extend(
        f"transition_batch_receipt_contract_missing:{key}"
        for key in missing_receipt_keys
    )

    raw_batch = raw.get("batch", {})
    if not isinstance(raw_batch, Mapping):
        errors.append("transition_batch_contract_not_mapping")
        raw_batch = {}
    missing_batch_keys = tuple(
        key
        for key in CSV_SEMANTIC_IR_TRANSITION_BATCH_CONTRACT_KEYS
        if key not in raw_batch
    )
    errors.extend(
        f"transition_batch_contract_missing:{key}" for key in missing_batch_keys
    )

    raw_batch_authorization = raw_batch.get("batch_authorization", {})
    if not isinstance(raw_batch_authorization, Mapping):
        errors.append("transition_batch_authorization_not_mapping")
        raw_batch_authorization = {}
    missing_batch_authorization_keys = tuple(
        key
        for key in CSV_SEMANTIC_IR_BATCH_AUTHORIZATION_CONTRACT_KEYS
        if key not in raw_batch_authorization
    )
    errors.extend(
        f"transition_batch_authorization_contract_missing:{key}"
        for key in missing_batch_authorization_keys
    )

    missing_item_keys: list[str] = []
    missing_request_keys: list[str] = []
    missing_transition_authorization_keys: list[str] = []
    raw_items = raw_batch.get("items", ()) or ()
    if not isinstance(raw_items, (list, tuple)):
        errors.append("transition_batch_items_not_sequence")
        raw_items = ()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            errors.append(f"transition_batch_item_not_mapping:{index}")
            continue
        for key in CSV_SEMANTIC_IR_BATCH_ITEM_CONTRACT_KEYS:
            if key not in raw_item:
                missing_item_keys.append(f"{index}:{key}")
        raw_request = raw_item.get("request", {})
        if not isinstance(raw_request, Mapping):
            errors.append(f"transition_batch_request_not_mapping:{index}")
            raw_request = {}
        for key in CSV_SEMANTIC_IR_TRANSITION_REQUEST_CONTRACT_KEYS:
            if key not in raw_request:
                missing_request_keys.append(f"{index}:{key}")
        raw_authorization = raw_request.get("authorization", {})
        if not isinstance(raw_authorization, Mapping):
            errors.append(f"transition_batch_item_authorization_not_mapping:{index}")
            raw_authorization = {}
        for key in CSV_SEMANTIC_IR_TRANSITION_AUTHORIZATION_CONTRACT_KEYS:
            if key not in raw_authorization:
                missing_transition_authorization_keys.append(f"{index}:{key}")

    errors.extend(
        f"transition_batch_item_contract_missing:{value}"
        for value in missing_item_keys
    )
    errors.extend(
        f"transition_batch_request_contract_missing:{value}"
        for value in missing_request_keys
    )
    errors.extend(
        f"transition_batch_item_authorization_contract_missing:{value}"
        for value in missing_transition_authorization_keys
    )

    recomputed_batch_fingerprint = csv_semantic_ir_transition_batch_fingerprint(
        obj.batch
    )
    recomputed_receipt_fingerprint = csv_semantic_ir_batch_receipt_fingerprint(obj)
    recomputed_payload_bytes = _batch_receipt_payload_bytes(obj)

    if obj.batch_version != CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION:
        errors.append(f"transition_batch_version_mismatch:{obj.batch_version}")
    if obj.suite_release_version != __version__:
        errors.append(
            f"transition_batch_release_version_mismatch:{obj.suite_release_version}"
        )
    if obj.mode != "formal_semantic_ir_atomic_batch_review":
        errors.append(f"transition_batch_mode_mismatch:{obj.mode}")
    if obj.batch.batch_fingerprint != recomputed_batch_fingerprint:
        errors.append("transition_batch_fingerprint_mismatch")
    if obj.receipt_fingerprint != recomputed_receipt_fingerprint:
        errors.append("transition_batch_receipt_fingerprint_mismatch")
    if obj.payload_bytes != recomputed_payload_bytes:
        errors.append(
            f"transition_batch_receipt_payload_size_mismatch:{obj.payload_bytes}!={recomputed_payload_bytes}"
        )
    if obj.payload_bytes > obj.payload_byte_limit:
        errors.append(
            f"transition_batch_receipt_payload_too_large:{obj.payload_bytes}>{obj.payload_byte_limit}"
        )
    if obj.payload_byte_limit > CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT:
        errors.append(
            f"transition_batch_receipt_payload_limit_unbounded:{obj.payload_byte_limit}"
        )
    if obj.batch.payload_bytes != _transition_batch_payload_bytes(obj.batch):
        errors.append("transition_batch_payload_size_mismatch")
    if not obj.batch.ok:
        errors.append("transition_batch_input_envelope_invalid")

    if obj.source_candidate_fingerprint != obj.batch.source_candidate_fingerprint:
        errors.append("transition_batch_candidate_binding_mismatch")
    if obj.source_lifecycle_fingerprint != obj.batch.source_lifecycle_fingerprint:
        errors.append("transition_batch_source_lifecycle_binding_mismatch")
    if obj.source_lifecycle_supplied != obj.batch.source_lifecycle_supplied:
        errors.append("transition_batch_source_lifecycle_presence_mismatch")
    if obj.handoff_closure_fingerprint != obj.batch.handoff_closure_fingerprint:
        errors.append("transition_batch_handoff_binding_mismatch")
    if obj.raw_sha256 != obj.batch.raw_sha256:
        errors.append("transition_batch_raw_sha256_binding_mismatch")

    if not obj.all_or_nothing or obj.partial_acceptance:
        errors.append("transition_batch_atomicity_boundary_invalid")
    forbidden_flags = (
        ("csv_artifact_mutation", obj.csv_artifact_mutation),
        ("retroactive_csv_artifact_mutation", obj.retroactive_csv_artifact_mutation),
        ("interpole_mutation", obj.interpole_mutation),
        ("native_storage_writes", obj.native_storage_writes),
        ("native_storage_hot_path_touched", obj.native_storage_hot_path_touched),
        ("native_storage_locks_controlled", obj.native_storage_locks_controlled),
        ("native_c_storage_engine_changed", obj.native_c_storage_engine_changed),
        ("per_row_writes", obj.per_row_writes),
        ("per_cell_writes", obj.per_cell_writes),
        ("semantic_artifact_persisted", obj.semantic_artifact_persisted),
        ("formal_ir_committed", obj.formal_ir_committed),
        ("semantic_conclusions_committed", obj.semantic_conclusions_committed),
        ("committed_state_admitted", obj.committed_state_admitted),
        ("superseded_state_admitted", obj.superseded_state_admitted),
        ("automatic_lifecycle_transitions", obj.automatic_lifecycle_transitions),
    )
    errors.extend(
        f"transition_batch_forbidden_boundary_enabled:{name}"
        for name, enabled in forbidden_flags
        if enabled
    )
    if obj.tds_artifact_writes != 0:
        errors.append(f"transition_batch_tds_artifact_writes:{obj.tds_artifact_writes}")
    if not obj.directory_state_unchanged or (
        obj.directory_state_fingerprint_before
        != obj.directory_state_fingerprint_after
    ):
        errors.append("transition_batch_directory_state_changed")

    if obj.status == "semantic_ir_transition_batch_ready":
        if not obj.batch_accepted:
            errors.append("transition_batch_ready_without_acceptance")
        if obj.errors:
            errors.append("transition_batch_ready_contains_errors")
        if obj.result_lifecycle is None:
            errors.append("transition_batch_result_lifecycle_missing")
        else:
            lifecycle_validation = validate_csv_semantic_ir_lifecycle(
                obj.result_lifecycle.to_dict(),
                source_candidate=source_candidate,
            )
            if not lifecycle_validation.ok or not obj.result_lifecycle.ok:
                errors.extend(
                    f"transition_batch_result_lifecycle:{value}"
                    for value in lifecycle_validation.errors
                )
                if not lifecycle_validation.errors:
                    errors.append("transition_batch_result_lifecycle_invalid")
            if (
                obj.result_lifecycle_fingerprint
                != obj.result_lifecycle.lifecycle_fingerprint
            ):
                errors.append("transition_batch_result_lifecycle_fingerprint_mismatch")
            tail = obj.result_lifecycle.history[-len(obj.batch.items) :]
            if tuple(record.transition_fingerprint for record in tail) != (
                obj.result_transition_fingerprints
            ):
                errors.append("transition_batch_result_transition_fingerprints_mismatch")
            if tuple(record.transition_id for record in tail) != tuple(
                item.request.transition_id for item in obj.batch.items
            ):
                errors.append("transition_batch_result_order_mismatch")
    elif obj.status == "semantic_ir_transition_batch_blocked":
        if obj.batch_accepted:
            errors.append("transition_batch_blocked_with_acceptance")
        if obj.result_transition_fingerprints:
            errors.append("transition_batch_blocked_contains_accepted_transitions")
        if not obj.errors:
            errors.append("transition_batch_blocked_without_errors")
    else:
        errors.append(f"transition_batch_status_invalid:{obj.status}")

    if source_candidate is not None:
        try:
            candidate_obj, candidate_raw = _coerce_candidate(source_candidate)
            candidate_validation = validate_csv_semantic_ir_candidate(candidate_raw)
            if not candidate_validation.ok or not candidate_obj.ok:
                errors.extend(
                    f"transition_batch_source_candidate:{value}"
                    for value in candidate_validation.errors
                )
                if not candidate_validation.errors:
                    errors.append("transition_batch_source_candidate_invalid")
            if candidate_obj.candidate_fingerprint != obj.source_candidate_fingerprint:
                errors.append("transition_batch_source_candidate_fingerprint_mismatch")
            if candidate_obj.handoff_closure_fingerprint != obj.handoff_closure_fingerprint:
                errors.append("transition_batch_source_candidate_handoff_mismatch")
            if candidate_obj.raw_sha256 != obj.raw_sha256:
                errors.append("transition_batch_source_candidate_raw_sha256_mismatch")
        except Exception as exc:
            errors.append(
                f"transition_batch_source_candidate_unreadable:{type(exc).__name__}:{exc}"
            )

    if source_lifecycle is not None:
        try:
            lifecycle_raw = (
                source_lifecycle.to_dict()
                if isinstance(source_lifecycle, CSVSemanticIRLifecycle)
                else dict(source_lifecycle)
            )
            lifecycle_obj = (
                source_lifecycle
                if isinstance(source_lifecycle, CSVSemanticIRLifecycle)
                else CSVSemanticIRLifecycle.from_mapping(lifecycle_raw)
            )
            lifecycle_validation = validate_csv_semantic_ir_lifecycle(
                lifecycle_raw,
                source_candidate=source_candidate,
            )
            if not lifecycle_validation.ok or not lifecycle_obj.ok:
                errors.extend(
                    f"transition_batch_source_lifecycle:{value}"
                    for value in lifecycle_validation.errors
                )
                if not lifecycle_validation.errors:
                    errors.append("transition_batch_source_lifecycle_invalid")
            if lifecycle_obj.lifecycle_fingerprint != obj.source_lifecycle_fingerprint:
                errors.append("transition_batch_source_lifecycle_fingerprint_mismatch")
        except Exception as exc:
            errors.append(
                f"transition_batch_source_lifecycle_unreadable:{type(exc).__name__}:{exc}"
            )
    elif obj.source_lifecycle_supplied:
        errors.append("transition_batch_source_lifecycle_required_for_validation")

    return CSVSemanticIRBatchValidationReport(
        csv_id=obj.csv_id,
        status=(
            "semantic_ir_transition_batch_valid"
            if not errors
            else "semantic_ir_transition_batch_blocked"
        ),
        batch_version=obj.batch_version,
        source_receipt_fingerprint=obj.receipt_fingerprint,
        recomputed_receipt_fingerprint=recomputed_receipt_fingerprint,
        source_batch_fingerprint=obj.batch.batch_fingerprint,
        recomputed_batch_fingerprint=recomputed_batch_fingerprint,
        source_payload_bytes=obj.payload_bytes,
        recomputed_payload_bytes=recomputed_payload_bytes,
        payload_byte_limit=obj.payload_byte_limit,
        missing_receipt_keys=missing_receipt_keys,
        missing_batch_keys=missing_batch_keys,
        missing_batch_authorization_keys=missing_batch_authorization_keys,
        missing_item_keys=tuple(missing_item_keys),
        missing_request_keys=tuple(missing_request_keys),
        missing_transition_authorization_keys=tuple(
            missing_transition_authorization_keys
        ),
        errors=tuple(dict.fromkeys(errors)),
        warnings=obj.warnings,
    )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRBatchReplayReport:
    """Replay result for a complete atomic lifecycle batch receipt."""

    csv_id: str
    status: str
    batch_version: str
    source_receipt_fingerprint: str
    replay_receipt_fingerprint: str
    source_batch_fingerprint: str
    replay_batch_fingerprint: str
    source_result_lifecycle_fingerprint: str
    replay_result_lifecycle_fingerprint: str
    mismatched_fields: tuple[str, ...] = field(default_factory=tuple)
    directory_state_fingerprint_before: str = ""
    directory_state_fingerprint_after: str = ""
    directory_state_unchanged: bool = True
    tds_artifact_writes: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.status == "semantic_ir_transition_batch_replay_valid"
            and self.batch_version == CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION
            and self.source_receipt_fingerprint
            == self.replay_receipt_fingerprint
            and self.source_batch_fingerprint == self.replay_batch_fingerprint
            and self.source_result_lifecycle_fingerprint
            == self.replay_result_lifecycle_fingerprint
            and not self.mismatched_fields
            and self.directory_state_unchanged
            and self.tds_artifact_writes == 0
            and not self.errors
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def replay_csv_semantic_ir_transition_batch(
    directory: TDSDirectory,
    csv_id: str,
    source_candidate: CSVSemanticIRCandidate | Mapping[str, Any],
    source_receipt: CSVSemanticIRBatchReceipt | Mapping[str, Any],
    *,
    source_lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any] | None = None,
) -> CSVSemanticIRBatchReplayReport:
    """Reconstruct a batch receipt against current evidence and compare it."""

    safe_id = str(csv_id)
    try:
        validate_csv_id(safe_id)
        state_before = _directory_state_fingerprint(directory, safe_id)
    except Exception as exc:
        empty_state = _sha256_json([])
        return CSVSemanticIRBatchReplayReport(
            csv_id=safe_id,
            status="semantic_ir_transition_batch_replay_blocked",
            batch_version=CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
            source_receipt_fingerprint="",
            replay_receipt_fingerprint="",
            source_batch_fingerprint="",
            replay_batch_fingerprint="",
            source_result_lifecycle_fingerprint="",
            replay_result_lifecycle_fingerprint="",
            directory_state_fingerprint_before=empty_state,
            directory_state_fingerprint_after=empty_state,
            errors=(f"csv_id_unsafe:{type(exc).__name__}:{exc}",),
        )

    try:
        raw = (
            source_receipt.to_dict()
            if isinstance(source_receipt, CSVSemanticIRBatchReceipt)
            else dict(source_receipt)
        )
        source_obj = (
            source_receipt
            if isinstance(source_receipt, CSVSemanticIRBatchReceipt)
            else CSVSemanticIRBatchReceipt.from_mapping(raw)
        )
    except Exception as exc:
        state_after = _directory_state_fingerprint(directory, safe_id)
        return CSVSemanticIRBatchReplayReport(
            csv_id=safe_id,
            status="semantic_ir_transition_batch_replay_blocked",
            batch_version=CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
            source_receipt_fingerprint="",
            replay_receipt_fingerprint="",
            source_batch_fingerprint="",
            replay_batch_fingerprint="",
            source_result_lifecycle_fingerprint="",
            replay_result_lifecycle_fingerprint="",
            directory_state_fingerprint_before=state_before,
            directory_state_fingerprint_after=state_after,
            directory_state_unchanged=state_before == state_after,
            errors=(f"transition_batch_receipt_unreadable:{type(exc).__name__}:{exc}",),
        )

    validation = validate_csv_semantic_ir_transition_batch(
        raw,
        source_candidate=source_candidate,
        source_lifecycle=source_lifecycle,
    )
    errors: list[str] = []
    if not validation.ok:
        errors.extend(
            f"transition_batch_source_receipt:{value}"
            for value in validation.errors
        )
        if not validation.errors:
            errors.append("transition_batch_source_receipt_invalid")

    replayed: CSVSemanticIRBatchReceipt | None = None
    if not errors:
        replayed = prepare_csv_semantic_ir_transition_batch(
            directory,
            safe_id,
            source_candidate,
            tuple(item.request for item in source_obj.batch.items),
            batch_id=source_obj.batch.batch_id,
            batch_authorization=source_obj.batch.batch_authorization,
            source_lifecycle=source_lifecycle,
            payload_byte_limit=source_obj.payload_byte_limit,
        )
        if replayed.status != source_obj.status:
            errors.append(
                f"transition_batch_replay_status_mismatch:{replayed.status}!={source_obj.status}"
            )

    mismatched_fields: list[str] = []
    if replayed is not None:
        source_projection = _batch_receipt_projection(source_obj)
        replay_projection = _batch_receipt_projection(replayed)
        mismatched_fields.extend(
            key
            for key in sorted(set(source_projection) | set(replay_projection))
            if source_projection.get(key) != replay_projection.get(key)
        )
        if source_obj.receipt_fingerprint != replayed.receipt_fingerprint:
            errors.append("transition_batch_replay_receipt_fingerprint_mismatch")

    state_after = _directory_state_fingerprint(directory, safe_id)
    unchanged = state_before == state_after
    if not unchanged:
        errors.append("transition_batch_replay_mutated_tds_directory_state")

    return CSVSemanticIRBatchReplayReport(
        csv_id=safe_id,
        status=(
            "semantic_ir_transition_batch_replay_valid"
            if not errors and not mismatched_fields and replayed is not None
            else "semantic_ir_transition_batch_replay_blocked"
        ),
        batch_version=source_obj.batch_version,
        source_receipt_fingerprint=source_obj.receipt_fingerprint,
        replay_receipt_fingerprint=(
            replayed.receipt_fingerprint if replayed is not None else ""
        ),
        source_batch_fingerprint=source_obj.batch.batch_fingerprint,
        replay_batch_fingerprint=(
            replayed.batch.batch_fingerprint if replayed is not None else ""
        ),
        source_result_lifecycle_fingerprint=(
            source_obj.result_lifecycle_fingerprint
        ),
        replay_result_lifecycle_fingerprint=(
            replayed.result_lifecycle_fingerprint if replayed is not None else ""
        ),
        mismatched_fields=tuple(mismatched_fields),
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        tds_artifact_writes=0 if unchanged else 1,
        warnings=source_obj.warnings,
        errors=tuple(dict.fromkeys(errors)),
    )


def csv_semantic_ir_transition_batch_summary(
    receipt: CSVSemanticIRBatchReceipt,
) -> dict[str, Any]:
    """Return a compact operational summary for one batch receipt."""

    return {
        "csv_id": receipt.csv_id,
        "status": receipt.status,
        "batch_id": receipt.batch.batch_id,
        "batch_fingerprint": receipt.batch.batch_fingerprint,
        "receipt_fingerprint": receipt.receipt_fingerprint,
        "item_count": len(receipt.batch.items),
        "batch_accepted": receipt.batch_accepted,
        "source_lifecycle_supplied": receipt.source_lifecycle_supplied,
        "result_lifecycle_fingerprint": receipt.result_lifecycle_fingerprint,
        "directory_state_unchanged": receipt.directory_state_unchanged,
        "tds_artifact_writes": receipt.tds_artifact_writes,
        "errors": list(receipt.errors),
        "warnings": list(receipt.warnings),
        "ok": receipt.ok,
    }


def csv_semantic_ir_transition_batch_replay_summary(
    report: CSVSemanticIRBatchReplayReport,
) -> dict[str, Any]:
    """Return a compact operational summary for batch replay."""

    return {
        "csv_id": report.csv_id,
        "status": report.status,
        "source_receipt_fingerprint": report.source_receipt_fingerprint,
        "replay_receipt_fingerprint": report.replay_receipt_fingerprint,
        "mismatched_fields": list(report.mismatched_fields),
        "directory_state_unchanged": report.directory_state_unchanged,
        "tds_artifact_writes": report.tds_artifact_writes,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "ok": report.ok,
    }

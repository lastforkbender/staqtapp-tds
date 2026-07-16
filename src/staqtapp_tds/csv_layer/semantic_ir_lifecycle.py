"""Explicit Semantic IR lifecycle transitions for the TDS CSV Suite.

v3.5.1 adds a narrow, deterministic, read-only lifecycle ledger above the
v3.5.0 Formal Semantic IR candidate.  A transition is never inferred and is
never treated as semantic commitment.  The caller must supply an explicit
transition request and explicit authorization metadata.  TDS validates and
replays the source candidate against current CSV evidence before accepting a
transition.

Only these transitions are admitted:

    proposed -> validated
    proposed -> contested
    validated -> contested

The ``superseded`` and ``committed`` vocabulary values remain reserved and are
not admitted by this module.  Lifecycle ledgers are immutable in-memory values;
no CSV, Interpole, native-storage, or TDS artifact is written.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.version import __version__

from .manifest import validate_csv_id
from .semantic_ir import (
    CSV_SEMANTIC_IR_PROPOSITION_STATES,
    CSVSemanticIRCandidate,
    csv_semantic_ir_candidate_fingerprint,
    replay_csv_semantic_ir_candidate,
    validate_csv_semantic_ir_candidate,
)


CSV_SEMANTIC_IR_LIFECYCLE_VERSION = "1.0"
CSV_SEMANTIC_IR_LIFECYCLE_COMPATIBLE_RELEASE_VERSIONS: tuple[str, ...] = (
    "3.5.1",
    "3.5.2",
    "3.5.3",
)
CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT = 524_288
CSV_SEMANTIC_IR_MAX_TRANSITIONS = 256
CSV_SEMANTIC_IR_LIFECYCLE_STATES: tuple[str, ...] = (
    "proposed",
    "validated",
    "contested",
)
CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("proposed", "validated"),
    ("proposed", "contested"),
    ("validated", "contested"),
)
CSV_SEMANTIC_IR_TRANSITION_AUTHORITY_SCOPES: tuple[str, ...] = (
    "validate_proposition",
    "contest_proposition",
)

CSV_SEMANTIC_IR_TRANSITION_AUTHORIZATION_CONTRACT_KEYS: tuple[str, ...] = (
    "authorization_id",
    "actor_id",
    "authority_scope",
    "authorization_reference",
    "explicit_authorization",
)
CSV_SEMANTIC_IR_TRANSITION_REQUEST_CONTRACT_KEYS: tuple[str, ...] = (
    "transition_id",
    "proposition_id",
    "from_state",
    "to_state",
    "reason",
    "authorization",
)
CSV_SEMANTIC_IR_TRANSITION_RECORD_CONTRACT_KEYS: tuple[str, ...] = (
    "sequence",
    "transition_id",
    "proposition_id",
    "from_state",
    "to_state",
    "reason",
    "authorization",
    "authorization_fingerprint",
    "source_candidate_fingerprint",
    "source_declaration_fingerprint",
    "source_evidence_fingerprint",
    "handoff_closure_fingerprint",
    "predecessor_fingerprint",
    "proposition_predecessor_fingerprint",
    "transition_fingerprint",
    "explicit_authorization",
    "source_candidate_validated",
    "source_candidate_replayed",
    "current_handoff_revalidated",
    "automatic_transition",
    "semantic_commitment",
)
CSV_SEMANTIC_IR_LIFECYCLE_STATE_CONTRACT_KEYS: tuple[str, ...] = (
    "proposition_id",
    "state",
    "source_declaration_fingerprint",
    "predecessor_fingerprint",
    "last_transition_fingerprint",
    "transition_count",
)
CSV_SEMANTIC_IR_LIFECYCLE_CONTRACT_KEYS: tuple[str, ...] = (
    "csv_id",
    "status",
    "lifecycle_version",
    "suite_release_version",
    "mode",
    "lifecycle_fingerprint",
    "source_candidate_fingerprint",
    "handoff_closure_fingerprint",
    "raw_sha256",
    "current_states",
    "history",
    "allowed_transitions",
    "explicit_authorization_required",
    "source_candidate_validated",
    "source_candidate_replayed",
    "current_handoff_revalidated",
    "immutable_history",
    "deterministic_replay_required",
    "lifecycle_transitions_applied",
    "automatic_lifecycle_transitions",
    "semantic_artifact_persisted",
    "formal_ir_committed",
    "semantic_conclusions_committed",
    "committed_state_admitted",
    "superseded_state_admitted",
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
    "warnings",
    "errors",
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_MAX_AUTHORIZATION_REFERENCE_CHARS = 512
_MAX_REASON_CHARS = 2048


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: str) -> bool:
    value = str(value)
    if len(value) != 64 or value.lower() != value:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _valid_id(value: str) -> bool:
    return bool(_SAFE_ID_RE.fullmatch(str(value)))


def _valid_text(value: str, *, max_chars: int) -> bool:
    value = str(value)
    if not value or len(value) > max_chars:
        return False
    return all(ch >= " " and ch != "\x7f" for ch in value)


def _value_fingerprint(value: Any) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    try:
        return _sha256_json(value)
    except Exception:
        return hashlib.sha256(repr(value).encode("utf-8", errors="replace")).hexdigest()


def _directory_state_fingerprint(directory: TDSDirectory, csv_id: str) -> str:
    rows: list[dict[str, Any]] = []
    entries = getattr(directory, "_entries", {})
    for key in sorted(str(v) for v in entries.keys()):
        if csv_id and csv_id not in key:
            continue
        try:
            entry = entries[key]
            payload = getattr(entry, "value", getattr(entry, "data", entry))
            rows.append(
                {
                    "key": key,
                    "payload_fingerprint": _value_fingerprint(payload),
                    "provenance": str(getattr(entry, "provenance", "")),
                    "fmt_id": int(getattr(entry, "fmt_id", 0)),
                }
            )
        except Exception as exc:
            rows.append({"key": key, "unreadable": f"{type(exc).__name__}:{exc}"})
    return _sha256_json(rows)


def _required_scope(to_state: str) -> str:
    return "validate_proposition" if to_state == "validated" else "contest_proposition"


@dataclass(frozen=True, slots=True)
class CSVSemanticIRTransitionAuthorization:
    """Caller-supplied authorization metadata for one transition.

    TDS validates the shape and records the reference deterministically.  It
    does not authenticate the actor or resolve the external authorization
    reference.
    """

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
            and self.authority_scope in CSV_SEMANTIC_IR_TRANSITION_AUTHORITY_SCOPES
            and _valid_text(
                self.authorization_reference,
                max_chars=_MAX_AUTHORIZATION_REFERENCE_CHARS,
            )
            and self.explicit_authorization
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRTransitionAuthorization":
        return cls(
            authorization_id=str(data.get("authorization_id", "")),
            actor_id=str(data.get("actor_id", "")),
            authority_scope=str(data.get("authority_scope", "")),
            authorization_reference=str(data.get("authorization_reference", "")),
            explicit_authorization=bool(data.get("explicit_authorization", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRTransitionRequest:
    """One explicit requested lifecycle transition."""

    transition_id: str
    proposition_id: str
    from_state: str
    to_state: str
    reason: str
    authorization: CSVSemanticIRTransitionAuthorization

    @property
    def ok(self) -> bool:
        return (
            _valid_id(self.transition_id)
            and _valid_id(self.proposition_id)
            and (self.from_state, self.to_state) in CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS
            and _valid_text(self.reason, max_chars=_MAX_REASON_CHARS)
            and self.authorization.ok
            and self.authorization.authority_scope == _required_scope(self.to_state)
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["authorization"] = self.authorization.to_dict()
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRTransitionRequest":
        raw_authorization = data.get("authorization", {})
        if not isinstance(raw_authorization, Mapping):
            raw_authorization = {}
        return cls(
            transition_id=str(data.get("transition_id", "")),
            proposition_id=str(data.get("proposition_id", "")),
            from_state=str(data.get("from_state", "")),
            to_state=str(data.get("to_state", "")),
            reason=str(data.get("reason", "")),
            authorization=CSVSemanticIRTransitionAuthorization.from_mapping(raw_authorization),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRTransitionRecord:
    """Immutable accepted lifecycle transition and its complete lineage."""

    sequence: int
    transition_id: str
    proposition_id: str
    from_state: str
    to_state: str
    reason: str
    authorization: CSVSemanticIRTransitionAuthorization
    authorization_fingerprint: str
    source_candidate_fingerprint: str
    source_declaration_fingerprint: str
    source_evidence_fingerprint: str
    handoff_closure_fingerprint: str
    predecessor_fingerprint: str
    proposition_predecessor_fingerprint: str
    transition_fingerprint: str
    explicit_authorization: bool = True
    source_candidate_validated: bool = True
    source_candidate_replayed: bool = True
    current_handoff_revalidated: bool = True
    automatic_transition: bool = False
    semantic_commitment: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.sequence > 0
            and _valid_id(self.transition_id)
            and _valid_id(self.proposition_id)
            and (self.from_state, self.to_state) in CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS
            and _valid_text(self.reason, max_chars=_MAX_REASON_CHARS)
            and self.authorization.ok
            and self.authorization.authority_scope == _required_scope(self.to_state)
            and _is_sha256(self.authorization_fingerprint)
            and _is_sha256(self.source_candidate_fingerprint)
            and _is_sha256(self.source_declaration_fingerprint)
            and _is_sha256(self.source_evidence_fingerprint)
            and _is_sha256(self.handoff_closure_fingerprint)
            and _is_sha256(self.predecessor_fingerprint)
            and _is_sha256(self.proposition_predecessor_fingerprint)
            and _is_sha256(self.transition_fingerprint)
            and self.explicit_authorization
            and self.source_candidate_validated
            and self.source_candidate_replayed
            and self.current_handoff_revalidated
            and not self.automatic_transition
            and not self.semantic_commitment
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["authorization"] = self.authorization.to_dict()
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRTransitionRecord":
        raw_authorization = data.get("authorization", {})
        if not isinstance(raw_authorization, Mapping):
            raw_authorization = {}
        return cls(
            sequence=int(data.get("sequence", 0)),
            transition_id=str(data.get("transition_id", "")),
            proposition_id=str(data.get("proposition_id", "")),
            from_state=str(data.get("from_state", "")),
            to_state=str(data.get("to_state", "")),
            reason=str(data.get("reason", "")),
            authorization=CSVSemanticIRTransitionAuthorization.from_mapping(raw_authorization),
            authorization_fingerprint=str(data.get("authorization_fingerprint", "")),
            source_candidate_fingerprint=str(data.get("source_candidate_fingerprint", "")),
            source_declaration_fingerprint=str(data.get("source_declaration_fingerprint", "")),
            source_evidence_fingerprint=str(data.get("source_evidence_fingerprint", "")),
            handoff_closure_fingerprint=str(data.get("handoff_closure_fingerprint", "")),
            predecessor_fingerprint=str(data.get("predecessor_fingerprint", "")),
            proposition_predecessor_fingerprint=str(
                data.get("proposition_predecessor_fingerprint", "")
            ),
            transition_fingerprint=str(data.get("transition_fingerprint", "")),
            explicit_authorization=bool(data.get("explicit_authorization", False)),
            source_candidate_validated=bool(data.get("source_candidate_validated", False)),
            source_candidate_replayed=bool(data.get("source_candidate_replayed", False)),
            current_handoff_revalidated=bool(data.get("current_handoff_revalidated", False)),
            automatic_transition=bool(data.get("automatic_transition", False)),
            semantic_commitment=bool(data.get("semantic_commitment", False)),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRLifecycleState:
    """Current lifecycle state for one source proposition."""

    proposition_id: str
    state: str
    source_declaration_fingerprint: str
    predecessor_fingerprint: str
    last_transition_fingerprint: str
    transition_count: int

    @property
    def ok(self) -> bool:
        return (
            _valid_id(self.proposition_id)
            and self.state in CSV_SEMANTIC_IR_LIFECYCLE_STATES
            and _is_sha256(self.source_declaration_fingerprint)
            and _is_sha256(self.predecessor_fingerprint)
            and self.transition_count >= 0
            and (
                (self.transition_count == 0 and self.last_transition_fingerprint == "")
                or (
                    self.transition_count > 0
                    and _is_sha256(self.last_transition_fingerprint)
                )
            )
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRLifecycleState":
        return cls(
            proposition_id=str(data.get("proposition_id", "")),
            state=str(data.get("state", "")),
            source_declaration_fingerprint=str(
                data.get("source_declaration_fingerprint", "")
            ),
            predecessor_fingerprint=str(data.get("predecessor_fingerprint", "")),
            last_transition_fingerprint=str(data.get("last_transition_fingerprint", "")),
            transition_count=int(data.get("transition_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRLifecycle:
    """Immutable in-memory lifecycle ledger for one Formal Semantic IR candidate."""

    csv_id: str
    status: str
    lifecycle_version: str
    suite_release_version: str
    mode: str
    lifecycle_fingerprint: str
    source_candidate_fingerprint: str
    handoff_closure_fingerprint: str
    raw_sha256: str
    current_states: tuple[CSVSemanticIRLifecycleState, ...]
    history: tuple[CSVSemanticIRTransitionRecord, ...]
    allowed_transitions: tuple[tuple[str, str], ...]
    explicit_authorization_required: bool = True
    source_candidate_validated: bool = True
    source_candidate_replayed: bool = True
    current_handoff_revalidated: bool = True
    immutable_history: bool = True
    deterministic_replay_required: bool = True
    lifecycle_transitions_applied: bool = True
    automatic_lifecycle_transitions: bool = False
    semantic_artifact_persisted: bool = False
    formal_ir_committed: bool = False
    semantic_conclusions_committed: bool = False
    committed_state_admitted: bool = False
    superseded_state_admitted: bool = False
    directory_state_fingerprint_before: str = ""
    directory_state_fingerprint_after: str = ""
    directory_state_unchanged: bool = True
    payload_bytes: int = 0
    payload_byte_limit: int = CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT
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
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        state_ids = tuple(item.proposition_id for item in self.current_states)
        transition_ids = tuple(item.transition_id for item in self.history)
        return (
            self.status == "semantic_ir_lifecycle_ready"
            and self.lifecycle_version == CSV_SEMANTIC_IR_LIFECYCLE_VERSION
            and self.suite_release_version
            in CSV_SEMANTIC_IR_LIFECYCLE_COMPATIBLE_RELEASE_VERSIONS
            and self.mode == "formal_semantic_ir_lifecycle"
            and _is_sha256(self.lifecycle_fingerprint)
            and _is_sha256(self.source_candidate_fingerprint)
            and _is_sha256(self.handoff_closure_fingerprint)
            and _is_sha256(self.raw_sha256)
            and bool(self.current_states)
            and len(set(state_ids)) == len(state_ids)
            and all(item.ok for item in self.current_states)
            and 0 < len(self.history) <= CSV_SEMANTIC_IR_MAX_TRANSITIONS
            and len(set(transition_ids)) == len(transition_ids)
            and all(item.ok for item in self.history)
            and self.allowed_transitions == CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS
            and self.explicit_authorization_required
            and self.source_candidate_validated
            and self.source_candidate_replayed
            and self.current_handoff_revalidated
            and self.immutable_history
            and self.deterministic_replay_required
            and self.lifecycle_transitions_applied
            and not self.automatic_lifecycle_transitions
            and not self.semantic_artifact_persisted
            and not self.formal_ir_committed
            and not self.semantic_conclusions_committed
            and not self.committed_state_admitted
            and not self.superseded_state_admitted
            and self.directory_state_unchanged
            and _is_sha256(self.directory_state_fingerprint_before)
            and self.directory_state_fingerprint_before
            == self.directory_state_fingerprint_after
            and self.payload_bytes <= self.payload_byte_limit
            and self.payload_byte_limit <= CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT
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
            and not self.errors
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["current_states"] = [item.to_dict() for item in self.current_states]
        data["history"] = [item.to_dict() for item in self.history]
        data["allowed_transitions"] = [list(item) for item in self.allowed_transitions]
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["state_count"] = len(self.current_states)
        data["transition_count"] = len(self.history)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRLifecycle":
        raw_allowed = data.get("allowed_transitions", ()) or ()
        allowed: list[tuple[str, str]] = []
        for value in raw_allowed:
            if isinstance(value, (list, tuple)) and len(value) == 2:
                allowed.append((str(value[0]), str(value[1])))
            else:
                allowed.append(("", ""))
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "semantic_ir_lifecycle_blocked")),
            lifecycle_version=str(
                data.get("lifecycle_version", CSV_SEMANTIC_IR_LIFECYCLE_VERSION)
            ),
            suite_release_version=str(data.get("suite_release_version", "")),
            mode=str(data.get("mode", "formal_semantic_ir_lifecycle")),
            lifecycle_fingerprint=str(data.get("lifecycle_fingerprint", "")),
            source_candidate_fingerprint=str(
                data.get("source_candidate_fingerprint", "")
            ),
            handoff_closure_fingerprint=str(
                data.get("handoff_closure_fingerprint", "")
            ),
            raw_sha256=str(data.get("raw_sha256", "")),
            current_states=tuple(
                CSVSemanticIRLifecycleState.from_mapping(v)
                for v in data.get("current_states", ()) or ()
            ),
            history=tuple(
                CSVSemanticIRTransitionRecord.from_mapping(v)
                for v in data.get("history", ()) or ()
            ),
            allowed_transitions=tuple(allowed),
            explicit_authorization_required=bool(
                data.get("explicit_authorization_required", False)
            ),
            source_candidate_validated=bool(data.get("source_candidate_validated", False)),
            source_candidate_replayed=bool(data.get("source_candidate_replayed", False)),
            current_handoff_revalidated=bool(
                data.get("current_handoff_revalidated", False)
            ),
            immutable_history=bool(data.get("immutable_history", False)),
            deterministic_replay_required=bool(
                data.get("deterministic_replay_required", False)
            ),
            lifecycle_transitions_applied=bool(
                data.get("lifecycle_transitions_applied", False)
            ),
            automatic_lifecycle_transitions=bool(
                data.get("automatic_lifecycle_transitions", False)
            ),
            semantic_artifact_persisted=bool(
                data.get("semantic_artifact_persisted", False)
            ),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
            semantic_conclusions_committed=bool(
                data.get("semantic_conclusions_committed", False)
            ),
            committed_state_admitted=bool(data.get("committed_state_admitted", False)),
            superseded_state_admitted=bool(
                data.get("superseded_state_admitted", False)
            ),
            directory_state_fingerprint_before=str(
                data.get("directory_state_fingerprint_before", "")
            ),
            directory_state_fingerprint_after=str(
                data.get("directory_state_fingerprint_after", "")
            ),
            directory_state_unchanged=bool(data.get("directory_state_unchanged", False)),
            payload_bytes=int(data.get("payload_bytes", 0)),
            payload_byte_limit=int(
                data.get(
                    "payload_byte_limit",
                    CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT,
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
            warnings=tuple(str(v) for v in data.get("warnings", ()) or ()),
            errors=tuple(str(v) for v in data.get("errors", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRLifecycleValidationReport:
    """Serialized lifecycle integrity and lineage validation."""

    csv_id: str
    status: str
    lifecycle_version: str
    source_lifecycle_fingerprint: str
    recomputed_lifecycle_fingerprint: str
    source_payload_bytes: int
    recomputed_payload_bytes: int
    payload_byte_limit: int
    missing_contract_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_state_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_record_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_authorization_keys: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.status == "semantic_ir_lifecycle_valid"
            and self.lifecycle_version == CSV_SEMANTIC_IR_LIFECYCLE_VERSION
            and self.source_lifecycle_fingerprint
            == self.recomputed_lifecycle_fingerprint
            and self.source_payload_bytes == self.recomputed_payload_bytes
            and self.source_payload_bytes <= self.payload_byte_limit
            and not self.missing_contract_keys
            and not self.missing_state_keys
            and not self.missing_record_keys
            and not self.missing_authorization_keys
            and not self.errors
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


@dataclass(frozen=True, slots=True)
class CSVSemanticIRLifecycleReplayReport:
    """Replay result for a complete immutable lifecycle ledger."""

    csv_id: str
    status: str
    lifecycle_version: str
    source_lifecycle_fingerprint: str
    replay_lifecycle_fingerprint: str
    source_candidate_fingerprint: str
    replay_candidate_fingerprint: str
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
            self.status == "semantic_ir_lifecycle_replay_valid"
            and self.lifecycle_version == CSV_SEMANTIC_IR_LIFECYCLE_VERSION
            and self.source_lifecycle_fingerprint
            == self.replay_lifecycle_fingerprint
            and self.source_candidate_fingerprint == self.replay_candidate_fingerprint
            and not self.mismatched_fields
            and self.directory_state_unchanged
            and self.tds_artifact_writes == 0
            and not self.errors
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def _authorization_projection(
    authorization: CSVSemanticIRTransitionAuthorization | Mapping[str, Any],
) -> dict[str, Any]:
    obj = (
        authorization
        if isinstance(authorization, CSVSemanticIRTransitionAuthorization)
        else CSVSemanticIRTransitionAuthorization.from_mapping(authorization)
    )
    return {
        "authorization_id": obj.authorization_id,
        "actor_id": obj.actor_id,
        "authority_scope": obj.authority_scope,
        "authorization_reference": obj.authorization_reference,
        "explicit_authorization": obj.explicit_authorization,
    }


def csv_semantic_ir_transition_authorization_fingerprint(
    authorization: CSVSemanticIRTransitionAuthorization | Mapping[str, Any],
) -> str:
    """Return the deterministic fingerprint for authorization metadata."""
    return _sha256_json(_authorization_projection(authorization))


def _record_projection(
    record: CSVSemanticIRTransitionRecord | Mapping[str, Any],
) -> dict[str, Any]:
    obj = (
        record
        if isinstance(record, CSVSemanticIRTransitionRecord)
        else CSVSemanticIRTransitionRecord.from_mapping(record)
    )
    return {
        "sequence": obj.sequence,
        "transition_id": obj.transition_id,
        "proposition_id": obj.proposition_id,
        "from_state": obj.from_state,
        "to_state": obj.to_state,
        "reason": obj.reason,
        "authorization": _authorization_projection(obj.authorization),
        "authorization_fingerprint": obj.authorization_fingerprint,
        "source_candidate_fingerprint": obj.source_candidate_fingerprint,
        "source_declaration_fingerprint": obj.source_declaration_fingerprint,
        "source_evidence_fingerprint": obj.source_evidence_fingerprint,
        "handoff_closure_fingerprint": obj.handoff_closure_fingerprint,
        "predecessor_fingerprint": obj.predecessor_fingerprint,
        "proposition_predecessor_fingerprint": obj.proposition_predecessor_fingerprint,
        "explicit_authorization": obj.explicit_authorization,
        "source_candidate_validated": obj.source_candidate_validated,
        "source_candidate_replayed": obj.source_candidate_replayed,
        "current_handoff_revalidated": obj.current_handoff_revalidated,
        "automatic_transition": obj.automatic_transition,
        "semantic_commitment": obj.semantic_commitment,
    }


def csv_semantic_ir_transition_fingerprint(
    record: CSVSemanticIRTransitionRecord | Mapping[str, Any],
) -> str:
    """Return the deterministic fingerprint for one transition record."""
    return _sha256_json(_record_projection(record))


def _lifecycle_projection(
    lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any],
) -> dict[str, Any]:
    obj = (
        lifecycle
        if isinstance(lifecycle, CSVSemanticIRLifecycle)
        else CSVSemanticIRLifecycle.from_mapping(lifecycle)
    )
    return {
        "csv_id": obj.csv_id,
        "status": obj.status,
        "lifecycle_version": obj.lifecycle_version,
        "suite_release_version": obj.suite_release_version,
        "mode": obj.mode,
        "source_candidate_fingerprint": obj.source_candidate_fingerprint,
        "handoff_closure_fingerprint": obj.handoff_closure_fingerprint,
        "raw_sha256": obj.raw_sha256,
        "current_states": [
            {key: value for key, value in item.to_dict().items() if key != "ok"}
            for item in obj.current_states
        ],
        "history": [
            {key: value for key, value in item.to_dict().items() if key != "ok"}
            for item in obj.history
        ],
        "allowed_transitions": [list(item) for item in obj.allowed_transitions],
        "explicit_authorization_required": obj.explicit_authorization_required,
        "source_candidate_validated": obj.source_candidate_validated,
        "source_candidate_replayed": obj.source_candidate_replayed,
        "current_handoff_revalidated": obj.current_handoff_revalidated,
        "immutable_history": obj.immutable_history,
        "deterministic_replay_required": obj.deterministic_replay_required,
        "lifecycle_transitions_applied": obj.lifecycle_transitions_applied,
        "automatic_lifecycle_transitions": obj.automatic_lifecycle_transitions,
        "semantic_artifact_persisted": obj.semantic_artifact_persisted,
        "formal_ir_committed": obj.formal_ir_committed,
        "semantic_conclusions_committed": obj.semantic_conclusions_committed,
        "committed_state_admitted": obj.committed_state_admitted,
        "superseded_state_admitted": obj.superseded_state_admitted,
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
        "warnings": list(obj.warnings),
        "errors": list(obj.errors),
    }


def csv_semantic_ir_lifecycle_fingerprint(
    lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any],
) -> str:
    """Return the deterministic fingerprint for a lifecycle ledger."""
    return _sha256_json(_lifecycle_projection(lifecycle))


def _lifecycle_payload_bytes(
    lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any],
) -> int:
    projection = _lifecycle_projection(lifecycle)
    projection["lifecycle_fingerprint"] = csv_semantic_ir_lifecycle_fingerprint(lifecycle)
    return len(_canonical_json_bytes(projection))


def _finalize_lifecycle(lifecycle: CSVSemanticIRLifecycle) -> CSVSemanticIRLifecycle:
    fingerprint = csv_semantic_ir_lifecycle_fingerprint(lifecycle)
    payload_bytes = _lifecycle_payload_bytes(
        replace(lifecycle, lifecycle_fingerprint=fingerprint)
    )
    return replace(
        lifecycle,
        lifecycle_fingerprint=fingerprint,
        payload_bytes=payload_bytes,
    )


def _candidate_evidence_fingerprint(candidate: CSVSemanticIRCandidate, proposition_id: str) -> str:
    proposition = next(
        item for item in candidate.propositions if item.proposition_id == proposition_id
    )
    return _sha256_json(
        [
            {key: value for key, value in ref.to_dict().items() if key != "ok"}
            for ref in proposition.evidence
        ]
    )


def _initial_states(candidate: CSVSemanticIRCandidate) -> tuple[CSVSemanticIRLifecycleState, ...]:
    return tuple(
        CSVSemanticIRLifecycleState(
            proposition_id=item.proposition_id,
            state="proposed",
            source_declaration_fingerprint=item.declaration_fingerprint,
            predecessor_fingerprint=candidate.candidate_fingerprint,
            last_transition_fingerprint="",
            transition_count=0,
        )
        for item in candidate.propositions
    )


def _blocked_lifecycle(
    *,
    csv_id: str,
    state_before: str,
    state_after: str,
    payload_byte_limit: int,
    source_candidate_fingerprint: str = "",
    handoff_closure_fingerprint: str = "",
    raw_sha256: str = "",
    current_states: tuple[CSVSemanticIRLifecycleState, ...] = (),
    history: tuple[CSVSemanticIRTransitionRecord, ...] = (),
    source_candidate_validated: bool = False,
    source_candidate_replayed: bool = False,
    current_handoff_revalidated: bool = False,
    errors: Iterable[str] = (),
    warnings: Iterable[str] = (),
) -> CSVSemanticIRLifecycle:
    unchanged = state_before == state_after
    lifecycle = CSVSemanticIRLifecycle(
        csv_id=csv_id,
        status="semantic_ir_lifecycle_blocked",
        lifecycle_version=CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
        suite_release_version=__version__,
        mode="formal_semantic_ir_lifecycle",
        lifecycle_fingerprint="",
        source_candidate_fingerprint=source_candidate_fingerprint,
        handoff_closure_fingerprint=handoff_closure_fingerprint,
        raw_sha256=raw_sha256,
        current_states=current_states,
        history=history,
        allowed_transitions=CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS,
        source_candidate_validated=source_candidate_validated,
        source_candidate_replayed=source_candidate_replayed,
        current_handoff_revalidated=current_handoff_revalidated,
        lifecycle_transitions_applied=bool(history),
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        payload_byte_limit=payload_byte_limit,
        tds_artifact_writes=0 if unchanged else 1,
        csv_artifact_mutation=not unchanged,
        warnings=tuple(dict.fromkeys(str(v) for v in warnings)),
        errors=tuple(dict.fromkeys(str(v) for v in errors)),
    )
    return _finalize_lifecycle(lifecycle)


def _coerce_candidate(
    candidate: CSVSemanticIRCandidate | Mapping[str, Any],
) -> tuple[CSVSemanticIRCandidate, Mapping[str, Any]]:
    raw = candidate.to_dict() if isinstance(candidate, CSVSemanticIRCandidate) else dict(candidate)
    obj = candidate if isinstance(candidate, CSVSemanticIRCandidate) else CSVSemanticIRCandidate.from_mapping(raw)
    return obj, raw


def _coerce_request(
    request: CSVSemanticIRTransitionRequest | Mapping[str, Any],
) -> tuple[CSVSemanticIRTransitionRequest, tuple[str, ...]]:
    if isinstance(request, CSVSemanticIRTransitionRequest):
        return request, ()
    raw = dict(request)
    missing = [
        f"transition_request_contract_missing:{key}"
        for key in CSV_SEMANTIC_IR_TRANSITION_REQUEST_CONTRACT_KEYS
        if key not in raw
    ]
    raw_auth = raw.get("authorization", {})
    if not isinstance(raw_auth, Mapping):
        missing.append("transition_authorization_not_mapping")
        raw_auth = {}
    missing.extend(
        f"transition_authorization_contract_missing:{key}"
        for key in CSV_SEMANTIC_IR_TRANSITION_AUTHORIZATION_CONTRACT_KEYS
        if key not in raw_auth
    )
    return CSVSemanticIRTransitionRequest.from_mapping(raw), tuple(missing)


def prepare_csv_semantic_ir_transition(
    directory: TDSDirectory,
    csv_id: str,
    source_candidate: CSVSemanticIRCandidate | Mapping[str, Any],
    request: CSVSemanticIRTransitionRequest | Mapping[str, Any],
    *,
    source_lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any] | None = None,
    payload_byte_limit: int = CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT,
) -> CSVSemanticIRLifecycle:
    """Apply one explicitly authorized transition to an immutable ledger.

    The source candidate is validated and replayed against current committed
    CSV evidence on every call.  The returned lifecycle is not persisted.
    """

    effective_limit = max(
        1024,
        min(int(payload_byte_limit), CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT),
    )
    safe_id = str(csv_id)
    try:
        validate_csv_id(safe_id)
    except Exception as exc:
        empty_state = _sha256_json([])
        return _blocked_lifecycle(
            csv_id=safe_id,
            state_before=empty_state,
            state_after=empty_state,
            payload_byte_limit=effective_limit,
            errors=(f"csv_id_unsafe:{type(exc).__name__}:{exc}",),
        )

    state_before = _directory_state_fingerprint(directory, safe_id)
    errors: list[str] = []
    warnings: list[str] = []

    try:
        candidate, candidate_raw = _coerce_candidate(source_candidate)
    except Exception as exc:
        state_after = _directory_state_fingerprint(directory, safe_id)
        return _blocked_lifecycle(
            csv_id=safe_id,
            state_before=state_before,
            state_after=state_after,
            payload_byte_limit=effective_limit,
            errors=(f"semantic_ir_source_candidate_unreadable:{type(exc).__name__}:{exc}",),
        )

    candidate_validation = validate_csv_semantic_ir_candidate(candidate_raw)
    if not candidate_validation.ok or not candidate.ok:
        errors.extend(
            f"semantic_ir_source_candidate:{value}"
            for value in candidate_validation.errors
        )
        errors.extend(
            f"semantic_ir_source_candidate:{value}" for value in candidate.errors
        )
        if not errors:
            errors.append("semantic_ir_source_candidate_not_ready")
    if candidate.csv_id != safe_id:
        errors.append("semantic_ir_source_candidate_csv_id_mismatch")
    if candidate.candidate_fingerprint != csv_semantic_ir_candidate_fingerprint(candidate):
        errors.append("semantic_ir_source_candidate_fingerprint_mismatch")

    candidate_replay_ok = False
    if not errors:
        replay = replay_csv_semantic_ir_candidate(
            directory,
            safe_id,
            candidate_raw,
        )
        candidate_replay_ok = replay.ok
        if not replay.ok:
            errors.extend(
                f"semantic_ir_source_candidate_replay:{value}" for value in replay.errors
            )
            if not replay.errors:
                errors.append("semantic_ir_source_candidate_replay_blocked")

    current_states = _initial_states(candidate) if candidate.ok else ()
    history: tuple[CSVSemanticIRTransitionRecord, ...] = ()

    if source_lifecycle is not None and not errors:
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
            if not prior_validation.ok or not prior.ok:
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
            elif prior.source_candidate_fingerprint != candidate.candidate_fingerprint:
                errors.append("semantic_ir_source_lifecycle_candidate_mismatch")
            elif prior.handoff_closure_fingerprint != candidate.handoff_closure_fingerprint:
                errors.append("semantic_ir_source_lifecycle_handoff_mismatch")
            else:
                current_states = prior.current_states
                history = prior.history
        except Exception as exc:
            errors.append(
                f"semantic_ir_source_lifecycle_unreadable:{type(exc).__name__}:{exc}"
            )

    try:
        request_obj, request_errors = _coerce_request(request)
        errors.extend(request_errors)
    except Exception as exc:
        request_obj = CSVSemanticIRTransitionRequest(
            transition_id="",
            proposition_id="",
            from_state="",
            to_state="",
            reason="",
            authorization=CSVSemanticIRTransitionAuthorization("", "", "", "", False),
        )
        errors.append(f"semantic_ir_transition_request_unreadable:{type(exc).__name__}:{exc}")

    prefix = f"transition:{request_obj.transition_id or '<empty>'}"
    if not _valid_id(request_obj.transition_id):
        errors.append(f"{prefix}:transition_id_invalid")
    if not _valid_id(request_obj.proposition_id):
        errors.append(f"{prefix}:proposition_id_invalid")
    if request_obj.from_state not in CSV_SEMANTIC_IR_PROPOSITION_STATES:
        errors.append(f"{prefix}:from_state_invalid:{request_obj.from_state}")
    if request_obj.to_state not in CSV_SEMANTIC_IR_PROPOSITION_STATES:
        errors.append(f"{prefix}:to_state_invalid:{request_obj.to_state}")
    if (request_obj.from_state, request_obj.to_state) not in CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS:
        errors.append(
            f"{prefix}:transition_not_admitted:{request_obj.from_state}->{request_obj.to_state}"
        )
    if request_obj.to_state in {"committed", "superseded"}:
        errors.append(f"{prefix}:deferred_state_not_admitted:{request_obj.to_state}")
    if not _valid_text(request_obj.reason, max_chars=_MAX_REASON_CHARS):
        errors.append(f"{prefix}:reason_invalid")
    if not request_obj.authorization.explicit_authorization:
        errors.append(f"{prefix}:explicit_authorization_required")
    if not request_obj.authorization.ok:
        errors.append(f"{prefix}:authorization_invalid")
    expected_scope = _required_scope(request_obj.to_state)
    if request_obj.authorization.authority_scope != expected_scope:
        errors.append(
            f"{prefix}:authorization_scope_mismatch:{request_obj.authorization.authority_scope}!={expected_scope}"
        )
    if request_obj.transition_id in {item.transition_id for item in history}:
        errors.append(f"{prefix}:duplicate_transition_id")
    if len(history) >= CSV_SEMANTIC_IR_MAX_TRANSITIONS:
        errors.append(
            f"semantic_ir_transition_count_exceeded:{len(history) + 1}>{CSV_SEMANTIC_IR_MAX_TRANSITIONS}"
        )

    state_by_id = {item.proposition_id: item for item in current_states}
    proposition_by_id = {item.proposition_id: item for item in candidate.propositions}
    current = state_by_id.get(request_obj.proposition_id)
    proposition = proposition_by_id.get(request_obj.proposition_id)
    if current is None or proposition is None:
        errors.append(f"{prefix}:proposition_not_found:{request_obj.proposition_id}")
    elif current.state != request_obj.from_state:
        errors.append(
            f"{prefix}:predecessor_state_mismatch:{request_obj.from_state}!={current.state}"
        )

    new_history = history
    new_states = current_states
    if not errors and current is not None and proposition is not None:
        authorization_fingerprint = (
            csv_semantic_ir_transition_authorization_fingerprint(
                request_obj.authorization
            )
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
            transition_id=request_obj.transition_id,
            proposition_id=request_obj.proposition_id,
            from_state=request_obj.from_state,
            to_state=request_obj.to_state,
            reason=request_obj.reason,
            authorization=request_obj.authorization,
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
        record = replace(
            record,
            transition_fingerprint=csv_semantic_ir_transition_fingerprint(record),
        )
        if not record.ok:
            errors.append(f"{prefix}:resolved_transition_record_invalid")
        else:
            updated = CSVSemanticIRLifecycleState(
                proposition_id=current.proposition_id,
                state=request_obj.to_state,
                source_declaration_fingerprint=current.source_declaration_fingerprint,
                predecessor_fingerprint=proposition_predecessor_fingerprint,
                last_transition_fingerprint=record.transition_fingerprint,
                transition_count=current.transition_count + 1,
            )
            new_states = tuple(
                updated if item.proposition_id == updated.proposition_id else item
                for item in current_states
            )
            new_history = history + (record,)

    state_after = _directory_state_fingerprint(directory, safe_id)
    unchanged = state_before == state_after
    if not unchanged:
        errors.append("semantic_ir_lifecycle_mutated_tds_directory_state")

    if errors:
        return _blocked_lifecycle(
            csv_id=safe_id,
            state_before=state_before,
            state_after=state_after,
            payload_byte_limit=effective_limit,
            source_candidate_fingerprint=candidate.candidate_fingerprint,
            handoff_closure_fingerprint=candidate.handoff_closure_fingerprint,
            raw_sha256=candidate.raw_sha256,
            current_states=current_states,
            history=history,
            source_candidate_validated=candidate_validation.ok and candidate.ok,
            source_candidate_replayed=candidate_replay_ok,
            current_handoff_revalidated=candidate_replay_ok,
            errors=errors,
            warnings=warnings,
        )

    lifecycle = CSVSemanticIRLifecycle(
        csv_id=safe_id,
        status="semantic_ir_lifecycle_ready",
        lifecycle_version=CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
        suite_release_version=__version__,
        mode="formal_semantic_ir_lifecycle",
        lifecycle_fingerprint="",
        source_candidate_fingerprint=candidate.candidate_fingerprint,
        handoff_closure_fingerprint=candidate.handoff_closure_fingerprint,
        raw_sha256=candidate.raw_sha256,
        current_states=new_states,
        history=new_history,
        allowed_transitions=CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS,
        source_candidate_validated=True,
        source_candidate_replayed=True,
        current_handoff_revalidated=True,
        lifecycle_transitions_applied=True,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        payload_byte_limit=effective_limit,
        tds_artifact_writes=0,
        warnings=tuple(dict.fromkeys(warnings)),
        errors=(),
    )
    lifecycle = _finalize_lifecycle(lifecycle)
    if lifecycle.payload_bytes > effective_limit:
        lifecycle = replace(
            lifecycle,
            status="semantic_ir_lifecycle_blocked",
            errors=(
                f"semantic_ir_lifecycle_payload_too_large:{lifecycle.payload_bytes}>{effective_limit}",
            ),
        )
        lifecycle = _finalize_lifecycle(lifecycle)
    return lifecycle


def validate_csv_semantic_ir_lifecycle(
    lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any],
    *,
    source_candidate: CSVSemanticIRCandidate | Mapping[str, Any] | None = None,
) -> CSVSemanticIRLifecycleValidationReport:
    """Validate serialized lifecycle structure, fingerprints, and lineage."""

    try:
        raw = lifecycle.to_dict() if isinstance(lifecycle, CSVSemanticIRLifecycle) else dict(lifecycle)
        obj = lifecycle if isinstance(lifecycle, CSVSemanticIRLifecycle) else CSVSemanticIRLifecycle.from_mapping(raw)
        recomputed_fingerprint = csv_semantic_ir_lifecycle_fingerprint(obj)
        recomputed_payload_bytes = _lifecycle_payload_bytes(obj)
    except Exception as exc:
        error = f"semantic_ir_lifecycle_unreadable:{type(exc).__name__}:{exc}"
        return CSVSemanticIRLifecycleValidationReport(
            csv_id="",
            status="semantic_ir_lifecycle_blocked",
            lifecycle_version=CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
            source_lifecycle_fingerprint="",
            recomputed_lifecycle_fingerprint="",
            source_payload_bytes=0,
            recomputed_payload_bytes=0,
            payload_byte_limit=CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT,
            errors=(error,),
        )

    errors: list[str] = []
    warnings: list[str] = []
    missing_contract_keys = tuple(
        key for key in CSV_SEMANTIC_IR_LIFECYCLE_CONTRACT_KEYS if key not in raw
    )
    errors.extend(
        f"semantic_ir_lifecycle_contract_missing:{key}"
        for key in missing_contract_keys
    )

    missing_state_keys: list[str] = []
    raw_states = raw.get("current_states", ()) or ()
    if not isinstance(raw_states, (list, tuple)):
        errors.append("semantic_ir_lifecycle_states_not_sequence")
        raw_states = ()
    for index, raw_state in enumerate(raw_states):
        if not isinstance(raw_state, Mapping):
            errors.append(f"semantic_ir_lifecycle_state_not_mapping:{index}")
            continue
        for key in CSV_SEMANTIC_IR_LIFECYCLE_STATE_CONTRACT_KEYS:
            if key not in raw_state:
                token = f"{index}:{key}"
                missing_state_keys.append(token)
                errors.append(f"semantic_ir_lifecycle_state_contract_missing:{token}")

    missing_record_keys: list[str] = []
    missing_authorization_keys: list[str] = []
    raw_history = raw.get("history", ()) or ()
    if not isinstance(raw_history, (list, tuple)):
        errors.append("semantic_ir_lifecycle_history_not_sequence")
        raw_history = ()
    for index, raw_record in enumerate(raw_history):
        if not isinstance(raw_record, Mapping):
            errors.append(f"semantic_ir_transition_record_not_mapping:{index}")
            continue
        for key in CSV_SEMANTIC_IR_TRANSITION_RECORD_CONTRACT_KEYS:
            if key not in raw_record:
                token = f"{index}:{key}"
                missing_record_keys.append(token)
                errors.append(f"semantic_ir_transition_record_contract_missing:{token}")
        raw_auth = raw_record.get("authorization", {})
        if not isinstance(raw_auth, Mapping):
            errors.append(f"semantic_ir_transition_authorization_not_mapping:{index}")
            continue
        for key in CSV_SEMANTIC_IR_TRANSITION_AUTHORIZATION_CONTRACT_KEYS:
            if key not in raw_auth:
                token = f"{index}:{key}"
                missing_authorization_keys.append(token)
                errors.append(
                    f"semantic_ir_transition_authorization_contract_missing:{token}"
                )

    if obj.lifecycle_version != CSV_SEMANTIC_IR_LIFECYCLE_VERSION:
        errors.append(f"semantic_ir_lifecycle_version_mismatch:{obj.lifecycle_version}")
    if (
        obj.suite_release_version
        not in CSV_SEMANTIC_IR_LIFECYCLE_COMPATIBLE_RELEASE_VERSIONS
    ):
        errors.append(
            f"semantic_ir_lifecycle_release_version_mismatch:{obj.suite_release_version}"
        )
    if obj.mode != "formal_semantic_ir_lifecycle":
        errors.append(f"semantic_ir_lifecycle_mode_mismatch:{obj.mode}")
    if obj.status not in {
        "semantic_ir_lifecycle_ready",
        "semantic_ir_lifecycle_blocked",
    }:
        errors.append(f"semantic_ir_lifecycle_status_invalid:{obj.status}")
    elif obj.status == "semantic_ir_lifecycle_blocked":
        errors.append("semantic_ir_lifecycle_source_blocked")
    if obj.lifecycle_fingerprint != recomputed_fingerprint:
        errors.append("semantic_ir_lifecycle_fingerprint_mismatch")
    if obj.payload_bytes != recomputed_payload_bytes:
        errors.append(
            f"semantic_ir_lifecycle_payload_size_mismatch:{obj.payload_bytes}!={recomputed_payload_bytes}"
        )
    if obj.payload_bytes > obj.payload_byte_limit:
        errors.append(
            f"semantic_ir_lifecycle_payload_too_large:{obj.payload_bytes}>{obj.payload_byte_limit}"
        )
    if obj.payload_byte_limit > CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT:
        errors.append(
            f"semantic_ir_lifecycle_payload_limit_unbounded:{obj.payload_byte_limit}"
        )
    if obj.allowed_transitions != CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS:
        errors.append("semantic_ir_lifecycle_allowed_transitions_mismatch")
    if not obj.history:
        errors.append("semantic_ir_lifecycle_history_empty")
    if len(obj.history) > CSV_SEMANTIC_IR_MAX_TRANSITIONS:
        errors.append(
            f"semantic_ir_transition_count_exceeded:{len(obj.history)}>{CSV_SEMANTIC_IR_MAX_TRANSITIONS}"
        )
    if obj.errors:
        errors.append("semantic_ir_lifecycle_contains_errors")

    required_true = (
        "explicit_authorization_required",
        "source_candidate_validated",
        "source_candidate_replayed",
        "current_handoff_revalidated",
        "immutable_history",
        "deterministic_replay_required",
        "lifecycle_transitions_applied",
        "directory_state_unchanged",
    )
    for field_name in required_true:
        if not bool(getattr(obj, field_name)):
            errors.append(f"semantic_ir_lifecycle_required_boundary_false:{field_name}")

    forbidden_true = (
        "automatic_lifecycle_transitions",
        "semantic_artifact_persisted",
        "formal_ir_committed",
        "semantic_conclusions_committed",
        "committed_state_admitted",
        "superseded_state_admitted",
        "csv_artifact_mutation",
        "retroactive_csv_artifact_mutation",
        "interpole_mutation",
        "native_storage_writes",
        "native_storage_hot_path_touched",
        "native_storage_locks_controlled",
        "native_c_storage_engine_changed",
        "per_row_writes",
        "per_cell_writes",
    )
    for field_name in forbidden_true:
        if bool(getattr(obj, field_name)):
            errors.append(f"semantic_ir_lifecycle_forbidden_boundary_true:{field_name}")
    if obj.tds_artifact_writes != 0:
        errors.append(
            f"semantic_ir_lifecycle_tds_artifact_writes_nonzero:{obj.tds_artifact_writes}"
        )
    if (
        not _is_sha256(obj.directory_state_fingerprint_before)
        or not _is_sha256(obj.directory_state_fingerprint_after)
        or obj.directory_state_fingerprint_before
        != obj.directory_state_fingerprint_after
    ):
        errors.append("semantic_ir_lifecycle_directory_state_changed")

    candidate_obj: CSVSemanticIRCandidate | None = None
    if source_candidate is not None:
        try:
            candidate_obj, candidate_raw = _coerce_candidate(source_candidate)
            candidate_validation = validate_csv_semantic_ir_candidate(candidate_raw)
            if not candidate_validation.ok or not candidate_obj.ok:
                errors.extend(
                    f"semantic_ir_lifecycle_source_candidate:{value}"
                    for value in candidate_validation.errors
                )
            if candidate_obj.candidate_fingerprint != obj.source_candidate_fingerprint:
                errors.append("semantic_ir_lifecycle_source_candidate_fingerprint_mismatch")
            if candidate_obj.csv_id != obj.csv_id:
                errors.append("semantic_ir_lifecycle_source_candidate_csv_id_mismatch")
            if (
                candidate_obj.handoff_closure_fingerprint
                != obj.handoff_closure_fingerprint
            ):
                errors.append("semantic_ir_lifecycle_source_handoff_mismatch")
            if candidate_obj.raw_sha256 != obj.raw_sha256:
                errors.append("semantic_ir_lifecycle_source_raw_sha256_mismatch")
        except Exception as exc:
            errors.append(
                f"semantic_ir_lifecycle_source_candidate_unreadable:{type(exc).__name__}:{exc}"
            )
            candidate_obj = None

    state_ids = tuple(item.proposition_id for item in obj.current_states)
    if len(set(state_ids)) != len(state_ids):
        errors.append("semantic_ir_lifecycle_duplicate_state_proposition_id")
    transition_ids = tuple(item.transition_id for item in obj.history)
    if len(set(transition_ids)) != len(transition_ids):
        errors.append("semantic_ir_lifecycle_duplicate_transition_id")

    if candidate_obj is not None:
        proposition_by_id = {
            item.proposition_id: item for item in candidate_obj.propositions
        }
        working = {
            item.proposition_id: {
                "state": "proposed",
                "declaration": item.declaration_fingerprint,
                "last": "",
                "count": 0,
                "predecessor": candidate_obj.candidate_fingerprint,
            }
            for item in candidate_obj.propositions
        }
        if set(working) != set(state_ids):
            errors.append("semantic_ir_lifecycle_state_set_mismatch")
        base_candidate_fingerprint = candidate_obj.candidate_fingerprint
    else:
        proposition_by_id = {}
        working = {
            item.proposition_id: {
                "state": "proposed",
                "declaration": item.source_declaration_fingerprint,
                "last": "",
                "count": 0,
                "predecessor": obj.source_candidate_fingerprint,
            }
            for item in obj.current_states
        }
        base_candidate_fingerprint = obj.source_candidate_fingerprint

    previous_global = base_candidate_fingerprint
    for index, record in enumerate(obj.history):
        prefix = f"semantic_ir_transition:{index}:{record.transition_id or '<empty>'}"
        if record.sequence != index + 1:
            errors.append(f"{prefix}:sequence_mismatch:{record.sequence}!={index + 1}")
        if not record.ok:
            errors.append(f"{prefix}:invalid")
        if record.authorization_fingerprint != csv_semantic_ir_transition_authorization_fingerprint(
            record.authorization
        ):
            errors.append(f"{prefix}:authorization_fingerprint_mismatch")
        if record.transition_fingerprint != csv_semantic_ir_transition_fingerprint(record):
            errors.append(f"{prefix}:transition_fingerprint_mismatch")
        if record.predecessor_fingerprint != previous_global:
            errors.append(f"{prefix}:predecessor_fingerprint_mismatch")
        if record.source_candidate_fingerprint != obj.source_candidate_fingerprint:
            errors.append(f"{prefix}:source_candidate_fingerprint_mismatch")
        if record.handoff_closure_fingerprint != obj.handoff_closure_fingerprint:
            errors.append(f"{prefix}:handoff_fingerprint_mismatch")
        if (record.from_state, record.to_state) not in CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS:
            errors.append(f"{prefix}:transition_not_admitted")
        if record.to_state in {"committed", "superseded"}:
            errors.append(f"{prefix}:deferred_state_not_admitted")

        state = working.get(record.proposition_id)
        if state is None:
            errors.append(f"{prefix}:proposition_not_found")
        else:
            expected_prop_predecessor = state["last"] or base_candidate_fingerprint
            if record.proposition_predecessor_fingerprint != expected_prop_predecessor:
                errors.append(f"{prefix}:proposition_predecessor_fingerprint_mismatch")
            if record.from_state != state["state"]:
                errors.append(
                    f"{prefix}:state_lineage_mismatch:{record.from_state}!={state['state']}"
                )
            if record.source_declaration_fingerprint != state["declaration"]:
                errors.append(f"{prefix}:source_declaration_fingerprint_mismatch")
            if candidate_obj is not None:
                proposition = proposition_by_id.get(record.proposition_id)
                if proposition is not None:
                    expected_evidence = _candidate_evidence_fingerprint(
                        candidate_obj,
                        record.proposition_id,
                    )
                    if record.source_evidence_fingerprint != expected_evidence:
                        errors.append(f"{prefix}:source_evidence_fingerprint_mismatch")
            state["state"] = record.to_state
            state["predecessor"] = expected_prop_predecessor
            state["last"] = record.transition_fingerprint
            state["count"] += 1
        previous_global = record.transition_fingerprint

    state_by_id = {item.proposition_id: item for item in obj.current_states}
    for proposition_id, derived in working.items():
        actual = state_by_id.get(proposition_id)
        if actual is None:
            continue
        if actual.state != derived["state"]:
            errors.append(f"semantic_ir_lifecycle_current_state_mismatch:{proposition_id}")
        if actual.source_declaration_fingerprint != derived["declaration"]:
            errors.append(
                f"semantic_ir_lifecycle_current_declaration_mismatch:{proposition_id}"
            )
        if actual.predecessor_fingerprint != derived["predecessor"]:
            errors.append(
                f"semantic_ir_lifecycle_current_predecessor_mismatch:{proposition_id}"
            )
        if actual.last_transition_fingerprint != derived["last"]:
            errors.append(
                f"semantic_ir_lifecycle_current_last_transition_mismatch:{proposition_id}"
            )
        if actual.transition_count != derived["count"]:
            errors.append(
                f"semantic_ir_lifecycle_current_transition_count_mismatch:{proposition_id}"
            )
        if not actual.ok:
            errors.append(f"semantic_ir_lifecycle_current_state_invalid:{proposition_id}")

    if "state_count" in raw and int(raw.get("state_count", -1)) != len(obj.current_states):
        errors.append("semantic_ir_lifecycle_state_count_mismatch")
    if "transition_count" in raw and int(raw.get("transition_count", -1)) != len(obj.history):
        errors.append("semantic_ir_lifecycle_transition_count_mismatch")

    return CSVSemanticIRLifecycleValidationReport(
        csv_id=obj.csv_id,
        status="semantic_ir_lifecycle_valid" if not errors else "semantic_ir_lifecycle_blocked",
        lifecycle_version=obj.lifecycle_version,
        source_lifecycle_fingerprint=obj.lifecycle_fingerprint,
        recomputed_lifecycle_fingerprint=recomputed_fingerprint,
        source_payload_bytes=obj.payload_bytes,
        recomputed_payload_bytes=recomputed_payload_bytes,
        payload_byte_limit=obj.payload_byte_limit,
        missing_contract_keys=missing_contract_keys,
        missing_state_keys=tuple(missing_state_keys),
        missing_record_keys=tuple(missing_record_keys),
        missing_authorization_keys=tuple(missing_authorization_keys),
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _replay_projection(lifecycle: CSVSemanticIRLifecycle) -> dict[str, Any]:
    projection = _lifecycle_projection(lifecycle)
    projection.pop("directory_state_fingerprint_before", None)
    projection.pop("directory_state_fingerprint_after", None)
    return projection


def replay_csv_semantic_ir_lifecycle(
    directory: TDSDirectory,
    csv_id: str,
    source_candidate: CSVSemanticIRCandidate | Mapping[str, Any],
    source_lifecycle: CSVSemanticIRLifecycle | Mapping[str, Any],
) -> CSVSemanticIRLifecycleReplayReport:
    """Replay every transition from the source candidate and current evidence."""

    safe_id = str(csv_id)
    state_before = _directory_state_fingerprint(directory, safe_id)
    try:
        candidate, candidate_raw = _coerce_candidate(source_candidate)
        lifecycle_raw = (
            source_lifecycle.to_dict()
            if isinstance(source_lifecycle, CSVSemanticIRLifecycle)
            else dict(source_lifecycle)
        )
        source = (
            source_lifecycle
            if isinstance(source_lifecycle, CSVSemanticIRLifecycle)
            else CSVSemanticIRLifecycle.from_mapping(lifecycle_raw)
        )
    except Exception as exc:
        state_after = _directory_state_fingerprint(directory, safe_id)
        return CSVSemanticIRLifecycleReplayReport(
            csv_id=safe_id,
            status="semantic_ir_lifecycle_replay_blocked",
            lifecycle_version=CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
            source_lifecycle_fingerprint="",
            replay_lifecycle_fingerprint="",
            source_candidate_fingerprint="",
            replay_candidate_fingerprint="",
            directory_state_fingerprint_before=state_before,
            directory_state_fingerprint_after=state_after,
            directory_state_unchanged=state_before == state_after,
            errors=(f"semantic_ir_lifecycle_source_unreadable:{type(exc).__name__}:{exc}",),
        )

    validation = validate_csv_semantic_ir_lifecycle(
        lifecycle_raw,
        source_candidate=candidate_raw,
    )
    errors: list[str] = []
    warnings: list[str] = []
    if not validation.ok:
        errors.extend(
            f"semantic_ir_lifecycle_source:{value}" for value in validation.errors
        )

    replayed: CSVSemanticIRLifecycle | None = None
    for record in source.history:
        request = CSVSemanticIRTransitionRequest(
            transition_id=record.transition_id,
            proposition_id=record.proposition_id,
            from_state=record.from_state,
            to_state=record.to_state,
            reason=record.reason,
            authorization=record.authorization,
        )
        replayed = prepare_csv_semantic_ir_transition(
            directory,
            safe_id,
            candidate_raw,
            request,
            source_lifecycle=replayed,
            payload_byte_limit=source.payload_byte_limit,
        )
        if not replayed.ok:
            errors.extend(
                f"semantic_ir_lifecycle_rebuild:{value}" for value in replayed.errors
            )
            break

    if replayed is None:
        errors.append("semantic_ir_lifecycle_replay_history_empty")
        replayed = _blocked_lifecycle(
            csv_id=safe_id,
            state_before=state_before,
            state_after=state_before,
            payload_byte_limit=source.payload_byte_limit,
            source_candidate_fingerprint=candidate.candidate_fingerprint,
            handoff_closure_fingerprint=candidate.handoff_closure_fingerprint,
            raw_sha256=candidate.raw_sha256,
            errors=("semantic_ir_lifecycle_replay_history_empty",),
        )

    source_projection = _replay_projection(source)
    replay_projection = _replay_projection(replayed)
    mismatched_fields = tuple(
        key
        for key in sorted(set(source_projection) | set(replay_projection))
        if source_projection.get(key) != replay_projection.get(key)
    )
    errors.extend(
        f"semantic_ir_lifecycle_replay_mismatch:{key}"
        for key in mismatched_fields
    )

    state_after = _directory_state_fingerprint(directory, safe_id)
    unchanged = state_before == state_after
    if not unchanged:
        errors.append("semantic_ir_lifecycle_replay_mutated_tds_directory_state")

    status = (
        "semantic_ir_lifecycle_replay_valid"
        if not errors and not mismatched_fields
        else "semantic_ir_lifecycle_replay_blocked"
    )
    return CSVSemanticIRLifecycleReplayReport(
        csv_id=safe_id,
        status=status,
        lifecycle_version=CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
        source_lifecycle_fingerprint=source.lifecycle_fingerprint,
        replay_lifecycle_fingerprint=replayed.lifecycle_fingerprint,
        source_candidate_fingerprint=source.source_candidate_fingerprint,
        replay_candidate_fingerprint=replayed.source_candidate_fingerprint,
        mismatched_fields=mismatched_fields,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        tds_artifact_writes=0 if unchanged else 1,
        warnings=tuple(dict.fromkeys(warnings)),
        errors=tuple(dict.fromkeys(errors)),
    )


def csv_semantic_ir_lifecycle_summary(
    lifecycle: CSVSemanticIRLifecycle,
) -> dict[str, Any]:
    """Return a compact JSON-safe lifecycle summary."""
    return lifecycle.to_dict()


def csv_semantic_ir_lifecycle_replay_summary(
    report: CSVSemanticIRLifecycleReplayReport,
) -> dict[str, Any]:
    """Return a compact JSON-safe lifecycle replay summary."""
    return report.to_dict()

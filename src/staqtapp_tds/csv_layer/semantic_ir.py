"""Formal Semantic IR candidate foundation for the TDS CSV Suite.

v3.5.0 introduces an immutable, deterministic, explicitly opted-in Semantic
IR candidate object above the completed CSV evidence handoff.  The module does
not infer semantics and does not commit semantic truth.  Callers must provide
bounded declarations, each declaration must reference validated handoff
evidence, and candidate preparation remains read-only with respect to CSV
artifacts, Interpole reports, native storage, and the native C hot path.

The initial foundation defines the longer-term lifecycle vocabulary while only
admitting ``proposed`` propositions.  Later releases may add explicit,
separately authorized transition APIs.  No transition occurs here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from staqtapp_tds.tds_filesystem import TDSDirectory
from staqtapp_tds.version import __version__

from .manifest import validate_csv_id
from .semantic_handoff import (
    CSV_SEMANTIC_IR_HANDOFF_VERSION,
    CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES,
    CSVSemanticIRHandoffEvidence,
    CSVSemanticIRHandoffReport,
    prepare_csv_semantic_ir_handoff,
    validate_csv_semantic_ir_handoff,
)


CSV_SEMANTIC_IR_VERSION = "1.0"
CSV_SEMANTIC_IR_COMPATIBLE_RELEASE_VERSIONS: tuple[str, ...] = (
    "3.5.0",
    "3.5.1",
    "3.5.2",
    "3.5.3",
)
CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT = 131_072
CSV_SEMANTIC_IR_MAX_PROPOSITIONS = 256
CSV_SEMANTIC_IR_MAX_EVIDENCE_REFS_PER_PROPOSITION = len(
    CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES
)

CSV_SEMANTIC_IR_PROPOSITION_STATES: tuple[str, ...] = (
    "proposed",
    "validated",
    "contested",
    "superseded",
    "committed",
)
CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES: tuple[str, ...] = ("proposed",)
CSV_SEMANTIC_IR_SEMANTIC_KINDS: tuple[str, ...] = (
    "dataset_concept",
    "column_role",
    "column_type",
    "entity",
    "relationship",
    "row_identity",
    "cell_meaning",
    "custom",
)
CSV_SEMANTIC_IR_SUBJECT_SCOPES: tuple[str, ...] = (
    "dataset",
    "column",
    "row_range",
    "row_anchor",
    "custom",
)

CSV_SEMANTIC_IR_DECLARATION_CONTRACT_KEYS: tuple[str, ...] = (
    "proposition_id",
    "semantic_kind",
    "subject_scope",
    "subject_locator",
    "predicate",
    "object_value",
    "state",
    "evidence_names",
)
CSV_SEMANTIC_IR_EVIDENCE_REF_CONTRACT_KEYS: tuple[str, ...] = (
    "evidence_name",
    "evidence_kind",
    "source_key",
    "fingerprint",
    "handoff_closure_fingerprint",
    "read_only",
    "immutable_source",
)
CSV_SEMANTIC_IR_PROPOSITION_CONTRACT_KEYS: tuple[str, ...] = (
    "proposition_id",
    "semantic_kind",
    "subject_scope",
    "subject_locator",
    "predicate",
    "object_value",
    "state",
    "evidence",
    "declaration_fingerprint",
    "explicit_declaration",
    "inferred",
)
CSV_SEMANTIC_IR_CANDIDATE_CONTRACT_KEYS: tuple[str, ...] = (
    "csv_id",
    "status",
    "ir_version",
    "suite_release_version",
    "mode",
    "candidate_fingerprint",
    "handoff_version",
    "handoff_closure_fingerprint",
    "raw_sha256",
    "propositions",
    "state_vocabulary",
    "accepted_states",
    "explicit_opt_in",
    "source_handoff_revalidated",
    "caller_declarations_only",
    "evidence_references_only",
    "immutable_source_evidence",
    "deterministic_replay_required",
    "lifecycle_transitions_applied",
    "semantic_artifact_persisted",
    "formal_ir_committed",
    "automatic_semantic_reasoning",
    "semantic_conclusions_committed",
    "ai_behavior",
    "automatic_schema_inference",
    "automatic_type_inference",
    "automatic_entity_inference",
    "automatic_row_identity_inference",
    "automatic_cell_meaning_inference",
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

_PROPOSITION_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_MAX_LOCATOR_CHARS = 512
_MAX_PREDICATE_CHARS = 256
_MAX_OBJECT_VALUE_CHARS = 2048


@dataclass(frozen=True, slots=True)
class CSVSemanticIRDeclaration:
    """One explicit caller declaration used to construct an IR proposition."""

    proposition_id: str
    semantic_kind: str
    subject_scope: str
    subject_locator: str
    predicate: str
    object_value: str
    state: str = "proposed"
    evidence_names: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_names"] = list(self.evidence_names)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRDeclaration":
        return cls(
            proposition_id=str(data.get("proposition_id", "")),
            semantic_kind=str(data.get("semantic_kind", "")),
            subject_scope=str(data.get("subject_scope", "")),
            subject_locator=str(data.get("subject_locator", "")),
            predicate=str(data.get("predicate", "")),
            object_value=str(data.get("object_value", "")),
            state=str(data.get("state", "proposed")),
            evidence_names=tuple(str(v) for v in data.get("evidence_names", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIREvidenceReference:
    """Immutable reference to one validated CSV handoff evidence lane."""

    evidence_name: str
    evidence_kind: str
    source_key: str
    fingerprint: str
    handoff_closure_fingerprint: str
    read_only: bool = True
    immutable_source: bool = True

    @property
    def ok(self) -> bool:
        return (
            self.evidence_name in CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES
            and bool(self.evidence_kind)
            and bool(self.source_key)
            and _is_sha256(self.fingerprint)
            and _is_sha256(self.handoff_closure_fingerprint)
            and self.read_only
            and self.immutable_source
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIREvidenceReference":
        return cls(
            evidence_name=str(data.get("evidence_name", "")),
            evidence_kind=str(data.get("evidence_kind", "")),
            source_key=str(data.get("source_key", "")),
            fingerprint=str(data.get("fingerprint", "")),
            handoff_closure_fingerprint=str(data.get("handoff_closure_fingerprint", "")),
            read_only=bool(data.get("read_only", True)),
            immutable_source=bool(data.get("immutable_source", True)),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRProposition:
    """Resolved immutable Semantic IR proposition.

    v3.5.0 propositions are declarations only.  They are never inferred and
    their lifecycle state must remain ``proposed``.
    """

    proposition_id: str
    semantic_kind: str
    subject_scope: str
    subject_locator: str
    predicate: str
    object_value: str
    state: str
    evidence: tuple[CSVSemanticIREvidenceReference, ...]
    declaration_fingerprint: str
    explicit_declaration: bool = True
    inferred: bool = False

    @property
    def ok(self) -> bool:
        names = tuple(item.evidence_name for item in self.evidence)
        return (
            _valid_proposition_id(self.proposition_id)
            and self.semantic_kind in CSV_SEMANTIC_IR_SEMANTIC_KINDS
            and self.subject_scope in CSV_SEMANTIC_IR_SUBJECT_SCOPES
            and _valid_text(self.subject_locator, max_chars=_MAX_LOCATOR_CHARS)
            and _valid_text(self.predicate, max_chars=_MAX_PREDICATE_CHARS)
            and _valid_text(self.object_value, max_chars=_MAX_OBJECT_VALUE_CHARS)
            and self.state in CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES
            and 0 < len(self.evidence) <= CSV_SEMANTIC_IR_MAX_EVIDENCE_REFS_PER_PROPOSITION
            and len(set(names)) == len(names)
            and all(item.ok for item in self.evidence)
            and _is_sha256(self.declaration_fingerprint)
            and self.explicit_declaration
            and not self.inferred
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRProposition":
        return cls(
            proposition_id=str(data.get("proposition_id", "")),
            semantic_kind=str(data.get("semantic_kind", "")),
            subject_scope=str(data.get("subject_scope", "")),
            subject_locator=str(data.get("subject_locator", "")),
            predicate=str(data.get("predicate", "")),
            object_value=str(data.get("object_value", "")),
            state=str(data.get("state", "proposed")),
            evidence=tuple(
                CSVSemanticIREvidenceReference.from_mapping(v)
                for v in data.get("evidence", ()) or ()
            ),
            declaration_fingerprint=str(data.get("declaration_fingerprint", "")),
            explicit_declaration=bool(data.get("explicit_declaration", True)),
            inferred=bool(data.get("inferred", False)),
        )

    def as_declaration(self) -> CSVSemanticIRDeclaration:
        return CSVSemanticIRDeclaration(
            proposition_id=self.proposition_id,
            semantic_kind=self.semantic_kind,
            subject_scope=self.subject_scope,
            subject_locator=self.subject_locator,
            predicate=self.predicate,
            object_value=self.object_value,
            state=self.state,
            evidence_names=tuple(item.evidence_name for item in self.evidence),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRCandidate:
    """Read-only Formal Semantic IR candidate produced from explicit declarations."""

    csv_id: str
    status: str
    ir_version: str
    suite_release_version: str
    mode: str
    candidate_fingerprint: str
    handoff_version: str
    handoff_closure_fingerprint: str
    raw_sha256: str
    propositions: tuple[CSVSemanticIRProposition, ...]
    state_vocabulary: tuple[str, ...]
    accepted_states: tuple[str, ...]
    explicit_opt_in: bool
    source_handoff_revalidated: bool = True
    caller_declarations_only: bool = True
    evidence_references_only: bool = True
    immutable_source_evidence: bool = True
    deterministic_replay_required: bool = True
    lifecycle_transitions_applied: bool = False
    semantic_artifact_persisted: bool = False
    formal_ir_committed: bool = False
    automatic_semantic_reasoning: bool = False
    semantic_conclusions_committed: bool = False
    ai_behavior: bool = False
    automatic_schema_inference: bool = False
    automatic_type_inference: bool = False
    automatic_entity_inference: bool = False
    automatic_row_identity_inference: bool = False
    automatic_cell_meaning_inference: bool = False
    directory_state_fingerprint_before: str = ""
    directory_state_fingerprint_after: str = ""
    directory_state_unchanged: bool = True
    payload_bytes: int = 0
    payload_byte_limit: int = CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT
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
        ids = tuple(item.proposition_id for item in self.propositions)
        return (
            self.status == "semantic_ir_candidate_ready"
            and self.ir_version == CSV_SEMANTIC_IR_VERSION
            and self.suite_release_version in CSV_SEMANTIC_IR_COMPATIBLE_RELEASE_VERSIONS
            and self.mode == "formal_semantic_ir_candidate"
            and _is_sha256(self.candidate_fingerprint)
            and self.handoff_version == CSV_SEMANTIC_IR_HANDOFF_VERSION
            and _is_sha256(self.handoff_closure_fingerprint)
            and _is_sha256(self.raw_sha256)
            and 0 < len(self.propositions) <= CSV_SEMANTIC_IR_MAX_PROPOSITIONS
            and len(set(ids)) == len(ids)
            and all(item.ok for item in self.propositions)
            and self.state_vocabulary == CSV_SEMANTIC_IR_PROPOSITION_STATES
            and self.accepted_states == CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES
            and self.explicit_opt_in
            and self.source_handoff_revalidated
            and self.caller_declarations_only
            and self.evidence_references_only
            and self.immutable_source_evidence
            and self.deterministic_replay_required
            and not self.lifecycle_transitions_applied
            and not self.semantic_artifact_persisted
            and not self.formal_ir_committed
            and not self.automatic_semantic_reasoning
            and not self.semantic_conclusions_committed
            and not self.ai_behavior
            and not self.automatic_schema_inference
            and not self.automatic_type_inference
            and not self.automatic_entity_inference
            and not self.automatic_row_identity_inference
            and not self.automatic_cell_meaning_inference
            and self.directory_state_unchanged
            and _is_sha256(self.directory_state_fingerprint_before)
            and self.directory_state_fingerprint_before == self.directory_state_fingerprint_after
            and self.payload_bytes <= self.payload_byte_limit
            and self.payload_byte_limit <= CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT
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
        data["propositions"] = [item.to_dict() for item in self.propositions]
        data["state_vocabulary"] = list(self.state_vocabulary)
        data["accepted_states"] = list(self.accepted_states)
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["proposition_count"] = len(self.propositions)
        data["evidence_reference_count"] = sum(len(item.evidence) for item in self.propositions)
        data["ok"] = self.ok
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CSVSemanticIRCandidate":
        return cls(
            csv_id=str(data.get("csv_id", "")),
            status=str(data.get("status", "semantic_ir_candidate_blocked")),
            ir_version=str(data.get("ir_version", CSV_SEMANTIC_IR_VERSION)),
            suite_release_version=str(data.get("suite_release_version", "")),
            mode=str(data.get("mode", "formal_semantic_ir_candidate")),
            candidate_fingerprint=str(data.get("candidate_fingerprint", "")),
            handoff_version=str(data.get("handoff_version", "")),
            handoff_closure_fingerprint=str(data.get("handoff_closure_fingerprint", "")),
            raw_sha256=str(data.get("raw_sha256", "")),
            propositions=tuple(
                CSVSemanticIRProposition.from_mapping(v)
                for v in data.get("propositions", ()) or ()
            ),
            state_vocabulary=tuple(str(v) for v in data.get("state_vocabulary", ()) or ()),
            accepted_states=tuple(str(v) for v in data.get("accepted_states", ()) or ()),
            explicit_opt_in=bool(data.get("explicit_opt_in", False)),
            source_handoff_revalidated=bool(data.get("source_handoff_revalidated", False)),
            caller_declarations_only=bool(data.get("caller_declarations_only", True)),
            evidence_references_only=bool(data.get("evidence_references_only", True)),
            immutable_source_evidence=bool(data.get("immutable_source_evidence", True)),
            deterministic_replay_required=bool(data.get("deterministic_replay_required", True)),
            lifecycle_transitions_applied=bool(data.get("lifecycle_transitions_applied", False)),
            semantic_artifact_persisted=bool(data.get("semantic_artifact_persisted", False)),
            formal_ir_committed=bool(data.get("formal_ir_committed", False)),
            automatic_semantic_reasoning=bool(data.get("automatic_semantic_reasoning", False)),
            semantic_conclusions_committed=bool(data.get("semantic_conclusions_committed", False)),
            ai_behavior=bool(data.get("ai_behavior", False)),
            automatic_schema_inference=bool(data.get("automatic_schema_inference", False)),
            automatic_type_inference=bool(data.get("automatic_type_inference", False)),
            automatic_entity_inference=bool(data.get("automatic_entity_inference", False)),
            automatic_row_identity_inference=bool(data.get("automatic_row_identity_inference", False)),
            automatic_cell_meaning_inference=bool(data.get("automatic_cell_meaning_inference", False)),
            directory_state_fingerprint_before=str(data.get("directory_state_fingerprint_before", "")),
            directory_state_fingerprint_after=str(data.get("directory_state_fingerprint_after", "")),
            directory_state_unchanged=bool(data.get("directory_state_unchanged", False)),
            payload_bytes=int(data.get("payload_bytes", 0)),
            payload_byte_limit=int(data.get("payload_byte_limit", CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT)),
            tds_artifact_writes=int(data.get("tds_artifact_writes", 0)),
            csv_artifact_mutation=bool(data.get("csv_artifact_mutation", False)),
            retroactive_csv_artifact_mutation=bool(data.get("retroactive_csv_artifact_mutation", False)),
            interpole_mutation=bool(data.get("interpole_mutation", False)),
            native_storage_writes=bool(data.get("native_storage_writes", False)),
            native_storage_hot_path_touched=bool(data.get("native_storage_hot_path_touched", False)),
            native_storage_locks_controlled=bool(data.get("native_storage_locks_controlled", False)),
            native_c_storage_engine_changed=bool(data.get("native_c_storage_engine_changed", False)),
            per_row_writes=bool(data.get("per_row_writes", False)),
            per_cell_writes=bool(data.get("per_cell_writes", False)),
            warnings=tuple(str(v) for v in data.get("warnings", ()) or ()),
            errors=tuple(str(v) for v in data.get("errors", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class CSVSemanticIRValidationReport:
    """Integrity and boundary validation for a serialized IR candidate."""

    csv_id: str
    status: str
    ir_version: str
    source_candidate_fingerprint: str
    recomputed_candidate_fingerprint: str
    source_payload_bytes: int
    recomputed_payload_bytes: int
    payload_byte_limit: int
    missing_contract_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_proposition_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_evidence_ref_keys: tuple[str, ...] = field(default_factory=tuple)
    duplicate_proposition_ids: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    tds_artifact_writes: int = 0
    native_storage_writes: bool = False
    native_storage_hot_path_touched: bool = False
    lifecycle_transitions_applied: bool = False
    formal_ir_committed: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.status == "semantic_ir_candidate_valid"
            and not self.errors
            and self.source_candidate_fingerprint == self.recomputed_candidate_fingerprint
            and self.source_payload_bytes == self.recomputed_payload_bytes
            and self.source_payload_bytes <= self.payload_byte_limit
            and not self.missing_contract_keys
            and not self.missing_proposition_keys
            and not self.missing_evidence_ref_keys
            and not self.duplicate_proposition_ids
            and self.tds_artifact_writes == 0
            and not self.native_storage_writes
            and not self.native_storage_hot_path_touched
            and not self.lifecycle_transitions_applied
            and not self.formal_ir_committed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name in (
            "missing_contract_keys",
            "missing_proposition_keys",
            "missing_evidence_ref_keys",
            "duplicate_proposition_ids",
            "errors",
            "warnings",
        ):
            data[name] = list(getattr(self, name))
        data["ok"] = self.ok
        return data


@dataclass(frozen=True, slots=True)
class CSVSemanticIRReplayReport:
    """Replay proof for a source IR candidate against current CSV evidence."""

    csv_id: str
    status: str
    ir_version: str
    source_candidate_fingerprint: str
    replay_candidate_fingerprint: str
    source_handoff_closure_fingerprint: str
    replay_handoff_closure_fingerprint: str
    mismatched_fields: tuple[str, ...] = field(default_factory=tuple)
    directory_state_fingerprint_before: str = ""
    directory_state_fingerprint_after: str = ""
    directory_state_unchanged: bool = True
    tds_artifact_writes: int = 0
    native_storage_writes: bool = False
    native_storage_hot_path_touched: bool = False
    lifecycle_transitions_applied: bool = False
    formal_ir_committed: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.status == "semantic_ir_replay_valid"
            and not self.errors
            and not self.mismatched_fields
            and self.source_candidate_fingerprint == self.replay_candidate_fingerprint
            and self.source_handoff_closure_fingerprint == self.replay_handoff_closure_fingerprint
            and self.directory_state_unchanged
            and self.tds_artifact_writes == 0
            and not self.native_storage_writes
            and not self.native_storage_hot_path_touched
            and not self.lifecycle_transitions_applied
            and not self.formal_ir_committed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mismatched_fields"] = list(self.mismatched_fields)
        data["warnings"] = list(self.warnings)
        data["errors"] = list(self.errors)
        data["ok"] = self.ok
        return data


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


def _valid_proposition_id(value: str) -> bool:
    return bool(_PROPOSITION_ID_RE.fullmatch(str(value)))


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


def _declaration_projection(declaration: CSVSemanticIRDeclaration) -> dict[str, Any]:
    return declaration.to_dict()


def csv_semantic_ir_declaration_fingerprint(
    declaration: CSVSemanticIRDeclaration | Mapping[str, Any],
) -> str:
    obj = declaration if isinstance(declaration, CSVSemanticIRDeclaration) else CSVSemanticIRDeclaration.from_mapping(declaration)
    return _sha256_json(_declaration_projection(obj))


def _candidate_projection(candidate: CSVSemanticIRCandidate | Mapping[str, Any]) -> dict[str, Any]:
    obj = candidate if isinstance(candidate, CSVSemanticIRCandidate) else CSVSemanticIRCandidate.from_mapping(candidate)
    return {
        "csv_id": obj.csv_id,
        "status": obj.status,
        "ir_version": obj.ir_version,
        "suite_release_version": obj.suite_release_version,
        "mode": obj.mode,
        "handoff_version": obj.handoff_version,
        "handoff_closure_fingerprint": obj.handoff_closure_fingerprint,
        "raw_sha256": obj.raw_sha256,
        "propositions": [
            {
                key: value
                for key, value in proposition.to_dict().items()
                if key != "ok"
            }
            for proposition in obj.propositions
        ],
        "state_vocabulary": list(obj.state_vocabulary),
        "accepted_states": list(obj.accepted_states),
        "explicit_opt_in": obj.explicit_opt_in,
        "source_handoff_revalidated": obj.source_handoff_revalidated,
        "caller_declarations_only": obj.caller_declarations_only,
        "evidence_references_only": obj.evidence_references_only,
        "immutable_source_evidence": obj.immutable_source_evidence,
        "deterministic_replay_required": obj.deterministic_replay_required,
        "lifecycle_transitions_applied": obj.lifecycle_transitions_applied,
        "semantic_artifact_persisted": obj.semantic_artifact_persisted,
        "formal_ir_committed": obj.formal_ir_committed,
        "automatic_semantic_reasoning": obj.automatic_semantic_reasoning,
        "semantic_conclusions_committed": obj.semantic_conclusions_committed,
        "ai_behavior": obj.ai_behavior,
        "automatic_schema_inference": obj.automatic_schema_inference,
        "automatic_type_inference": obj.automatic_type_inference,
        "automatic_entity_inference": obj.automatic_entity_inference,
        "automatic_row_identity_inference": obj.automatic_row_identity_inference,
        "automatic_cell_meaning_inference": obj.automatic_cell_meaning_inference,
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


def csv_semantic_ir_candidate_fingerprint(
    candidate: CSVSemanticIRCandidate | Mapping[str, Any],
) -> str:
    return _sha256_json(_candidate_projection(candidate))


def _candidate_payload_bytes(candidate: CSVSemanticIRCandidate | Mapping[str, Any]) -> int:
    projection = _candidate_projection(candidate)
    projection["candidate_fingerprint"] = csv_semantic_ir_candidate_fingerprint(candidate)
    return len(_canonical_json_bytes(projection))


def _finalize_candidate_integrity(candidate: CSVSemanticIRCandidate) -> CSVSemanticIRCandidate:
    fingerprint = csv_semantic_ir_candidate_fingerprint(candidate)
    payload_bytes = _candidate_payload_bytes(replace(candidate, candidate_fingerprint=fingerprint))
    return replace(candidate, candidate_fingerprint=fingerprint, payload_bytes=payload_bytes)


def _blocked_candidate(
    *,
    csv_id: str,
    explicit_opt_in: bool,
    payload_byte_limit: int,
    state_before: str,
    state_after: str,
    source_handoff_revalidated: bool = False,
    handoff_closure_fingerprint: str = "",
    raw_sha256: str = "",
    propositions: tuple[CSVSemanticIRProposition, ...] = (),
    errors: Iterable[str] = (),
    warnings: Iterable[str] = (),
) -> CSVSemanticIRCandidate:
    unchanged = state_before == state_after
    candidate = CSVSemanticIRCandidate(
        csv_id=csv_id,
        status="semantic_ir_candidate_blocked",
        ir_version=CSV_SEMANTIC_IR_VERSION,
        suite_release_version=__version__,
        mode="formal_semantic_ir_candidate",
        candidate_fingerprint="",
        handoff_version=CSV_SEMANTIC_IR_HANDOFF_VERSION,
        handoff_closure_fingerprint=handoff_closure_fingerprint,
        raw_sha256=raw_sha256,
        propositions=propositions,
        state_vocabulary=CSV_SEMANTIC_IR_PROPOSITION_STATES,
        accepted_states=CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES,
        explicit_opt_in=explicit_opt_in,
        source_handoff_revalidated=source_handoff_revalidated,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        payload_byte_limit=payload_byte_limit,
        tds_artifact_writes=0 if unchanged else 1,
        csv_artifact_mutation=not unchanged,
        warnings=tuple(dict.fromkeys(str(v) for v in warnings)),
        errors=tuple(dict.fromkeys(str(v) for v in errors)),
    )
    return _finalize_candidate_integrity(candidate)


def _coerce_declaration(
    value: CSVSemanticIRDeclaration | Mapping[str, Any],
    *,
    index: int,
) -> tuple[CSVSemanticIRDeclaration, tuple[str, ...]]:
    if isinstance(value, CSVSemanticIRDeclaration):
        return value, ()
    raw = dict(value)
    missing = tuple(key for key in CSV_SEMANTIC_IR_DECLARATION_CONTRACT_KEYS if key not in raw)
    declaration = CSVSemanticIRDeclaration.from_mapping(raw)
    return declaration, tuple(f"declaration_contract_missing:{index}:{key}" for key in missing)


def _validate_declaration(
    declaration: CSVSemanticIRDeclaration,
    *,
    index: int,
    handoff_evidence: Mapping[str, CSVSemanticIRHandoffEvidence],
    handoff_closure_fingerprint: str,
) -> tuple[CSVSemanticIRProposition | None, tuple[str, ...]]:
    errors: list[str] = []
    prefix = f"declaration:{index}:{declaration.proposition_id or '<empty>'}"

    if not _valid_proposition_id(declaration.proposition_id):
        errors.append(f"{prefix}:proposition_id_invalid")
    if declaration.semantic_kind not in CSV_SEMANTIC_IR_SEMANTIC_KINDS:
        errors.append(f"{prefix}:semantic_kind_invalid:{declaration.semantic_kind}")
    if declaration.subject_scope not in CSV_SEMANTIC_IR_SUBJECT_SCOPES:
        errors.append(f"{prefix}:subject_scope_invalid:{declaration.subject_scope}")
    if not _valid_text(declaration.subject_locator, max_chars=_MAX_LOCATOR_CHARS):
        errors.append(f"{prefix}:subject_locator_invalid")
    if not _valid_text(declaration.predicate, max_chars=_MAX_PREDICATE_CHARS):
        errors.append(f"{prefix}:predicate_invalid")
    if not _valid_text(declaration.object_value, max_chars=_MAX_OBJECT_VALUE_CHARS):
        errors.append(f"{prefix}:object_value_invalid")
    if declaration.state not in CSV_SEMANTIC_IR_PROPOSITION_STATES:
        errors.append(f"{prefix}:state_unknown:{declaration.state}")
    elif declaration.state not in CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES:
        errors.append(f"{prefix}:state_not_admitted_in_foundation:{declaration.state}")

    evidence_names = tuple(declaration.evidence_names)
    if not evidence_names:
        errors.append(f"{prefix}:evidence_names_empty")
    if len(evidence_names) > CSV_SEMANTIC_IR_MAX_EVIDENCE_REFS_PER_PROPOSITION:
        errors.append(
            f"{prefix}:evidence_reference_count_exceeded:{len(evidence_names)}>{CSV_SEMANTIC_IR_MAX_EVIDENCE_REFS_PER_PROPOSITION}"
        )
    if len(set(evidence_names)) != len(evidence_names):
        errors.append(f"{prefix}:duplicate_evidence_names")
    for name in evidence_names:
        if name not in CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES:
            errors.append(f"{prefix}:evidence_name_unknown:{name}")
        elif name not in handoff_evidence or not handoff_evidence[name].ok:
            errors.append(f"{prefix}:evidence_not_ready:{name}")

    if errors:
        return None, tuple(errors)

    evidence = tuple(
        CSVSemanticIREvidenceReference(
            evidence_name=name,
            evidence_kind=handoff_evidence[name].evidence_kind,
            source_key=handoff_evidence[name].source_key,
            fingerprint=handoff_evidence[name].fingerprint,
            handoff_closure_fingerprint=handoff_closure_fingerprint,
        )
        for name in evidence_names
    )
    proposition = CSVSemanticIRProposition(
        proposition_id=declaration.proposition_id,
        semantic_kind=declaration.semantic_kind,
        subject_scope=declaration.subject_scope,
        subject_locator=declaration.subject_locator,
        predicate=declaration.predicate,
        object_value=declaration.object_value,
        state=declaration.state,
        evidence=evidence,
        declaration_fingerprint=csv_semantic_ir_declaration_fingerprint(declaration),
    )
    if not proposition.ok:
        return None, (f"{prefix}:resolved_proposition_invalid",)
    return proposition, ()


def prepare_csv_semantic_ir_candidate(
    directory: TDSDirectory,
    csv_id: str,
    declarations: Sequence[CSVSemanticIRDeclaration | Mapping[str, Any]],
    *,
    explicit_opt_in: bool = False,
    source_handoff: CSVSemanticIRHandoffReport | Mapping[str, Any] | None = None,
    payload_byte_limit: int = CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT,
) -> CSVSemanticIRCandidate:
    """Build a deterministic read-only Formal Semantic IR candidate.

    The caller must set ``explicit_opt_in=True`` and provide one or more
    complete declarations.  This function never persists the candidate.
    """
    effective_limit = max(256, min(int(payload_byte_limit), CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT))
    safe_id = str(csv_id)
    try:
        validate_csv_id(safe_id)
    except Exception as exc:
        empty_state = _sha256_json([])
        return _blocked_candidate(
            csv_id=safe_id,
            explicit_opt_in=explicit_opt_in,
            payload_byte_limit=effective_limit,
            state_before=empty_state,
            state_after=empty_state,
            errors=(f"csv_id_unsafe:{type(exc).__name__}:{exc}",),
        )

    state_before = _directory_state_fingerprint(directory, safe_id)
    if not explicit_opt_in:
        state_after = _directory_state_fingerprint(directory, safe_id)
        return _blocked_candidate(
            csv_id=safe_id,
            explicit_opt_in=False,
            payload_byte_limit=effective_limit,
            state_before=state_before,
            state_after=state_after,
            errors=("semantic_ir_explicit_opt_in_required",),
        )

    # Always reconstruct current admission evidence.  A supplied handoff is an
    # additional expected snapshot, never an authority that can bypass current
    # CSV drift/replay checks.
    handoff = prepare_csv_semantic_ir_handoff(directory, safe_id)
    handoff_validation = validate_csv_semantic_ir_handoff(handoff)
    handoff_errors: list[str] = []
    if not handoff_validation.ok or not handoff.ok:
        handoff_errors.extend(f"semantic_ir_handoff:{value}" for value in handoff_validation.errors)
        handoff_errors.extend(f"semantic_ir_handoff:{value}" for value in handoff.errors)
        if not handoff_errors:
            handoff_errors.append("semantic_ir_handoff_not_ready")

    if source_handoff is not None:
        try:
            source_raw: Mapping[str, Any] | CSVSemanticIRHandoffReport
            if isinstance(source_handoff, CSVSemanticIRHandoffReport):
                source_obj = source_handoff
                source_raw = source_handoff
            else:
                source_raw = dict(source_handoff)
                source_obj = CSVSemanticIRHandoffReport.from_mapping(source_raw)
            source_validation = validate_csv_semantic_ir_handoff(source_raw)
            if not source_validation.ok or not source_obj.ok:
                handoff_errors.extend(
                    f"semantic_ir_source_handoff:{value}" for value in source_validation.errors
                )
                handoff_errors.extend(
                    f"semantic_ir_source_handoff:{value}" for value in source_obj.errors
                )
            else:
                if source_obj.csv_id != handoff.csv_id:
                    handoff_errors.append("semantic_ir_source_handoff_csv_id_mismatch")
                if source_obj.closure_fingerprint != handoff.closure_fingerprint:
                    handoff_errors.append("semantic_ir_source_handoff_stale_or_drifted")
                if source_obj.raw_sha256 != handoff.raw_sha256:
                    handoff_errors.append("semantic_ir_source_handoff_raw_sha256_mismatch")
        except Exception as exc:
            handoff_errors.append(
                f"semantic_ir_source_handoff_unreadable:{type(exc).__name__}:{exc}"
            )

    if handoff_errors:
        state_after = _directory_state_fingerprint(directory, safe_id)
        return _blocked_candidate(
            csv_id=safe_id,
            explicit_opt_in=True,
            payload_byte_limit=effective_limit,
            state_before=state_before,
            state_after=state_after,
            source_handoff_revalidated=True,
            handoff_closure_fingerprint=handoff.closure_fingerprint,
            raw_sha256=handoff.raw_sha256,
            errors=handoff_errors,
        )

    aggregate_errors: list[str] = []
    aggregate_warnings: list[str] = []
    if not declarations:
        aggregate_errors.append("semantic_ir_declarations_empty")
    if len(declarations) > CSV_SEMANTIC_IR_MAX_PROPOSITIONS:
        aggregate_errors.append(
            f"semantic_ir_proposition_count_exceeded:{len(declarations)}>{CSV_SEMANTIC_IR_MAX_PROPOSITIONS}"
        )

    handoff_evidence = {item.evidence_name: item for item in handoff.evidence}
    propositions: list[CSVSemanticIRProposition] = []
    for index, value in enumerate(declarations[: CSV_SEMANTIC_IR_MAX_PROPOSITIONS]):
        try:
            declaration, coercion_errors = _coerce_declaration(value, index=index)
        except Exception as exc:
            aggregate_errors.append(f"declaration_unreadable:{index}:{type(exc).__name__}:{exc}")
            continue
        aggregate_errors.extend(coercion_errors)
        proposition, declaration_errors = _validate_declaration(
            declaration,
            index=index,
            handoff_evidence=handoff_evidence,
            handoff_closure_fingerprint=handoff.closure_fingerprint,
        )
        aggregate_errors.extend(declaration_errors)
        if proposition is not None:
            propositions.append(proposition)

    proposition_ids = tuple(item.proposition_id for item in propositions)
    duplicates = tuple(sorted({value for value in proposition_ids if proposition_ids.count(value) > 1}))
    aggregate_errors.extend(f"duplicate_proposition_id:{value}" for value in duplicates)

    state_after = _directory_state_fingerprint(directory, safe_id)
    unchanged = state_before == state_after
    if not unchanged:
        aggregate_errors.append("semantic_ir_candidate_mutated_tds_directory_state")

    ready = (
        not aggregate_errors
        and bool(propositions)
        and len(propositions) == len(declarations)
        and unchanged
    )
    candidate = CSVSemanticIRCandidate(
        csv_id=safe_id,
        status="semantic_ir_candidate_ready" if ready else "semantic_ir_candidate_blocked",
        ir_version=CSV_SEMANTIC_IR_VERSION,
        suite_release_version=__version__,
        mode="formal_semantic_ir_candidate",
        candidate_fingerprint="",
        handoff_version=handoff.handoff_version,
        handoff_closure_fingerprint=handoff.closure_fingerprint,
        raw_sha256=handoff.raw_sha256,
        propositions=tuple(propositions),
        state_vocabulary=CSV_SEMANTIC_IR_PROPOSITION_STATES,
        accepted_states=CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES,
        explicit_opt_in=True,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        payload_byte_limit=effective_limit,
        tds_artifact_writes=0 if unchanged else 1,
        csv_artifact_mutation=not unchanged,
        warnings=tuple(dict.fromkeys(aggregate_warnings)),
        errors=tuple(dict.fromkeys(aggregate_errors)),
    )
    candidate = _finalize_candidate_integrity(candidate)
    if candidate.payload_bytes > effective_limit:
        candidate = replace(
            candidate,
            status="semantic_ir_candidate_blocked",
            errors=tuple(
                dict.fromkeys(
                    candidate.errors
                    + (f"semantic_ir_payload_too_large:{candidate.payload_bytes}>{effective_limit}",)
                )
            ),
        )
        candidate = _finalize_candidate_integrity(candidate)
    return candidate


def validate_csv_semantic_ir_candidate(
    candidate: CSVSemanticIRCandidate | Mapping[str, Any],
) -> CSVSemanticIRValidationReport:
    """Validate a serialized IR candidate without reading or writing TDS."""
    try:
        raw = candidate.to_dict() if isinstance(candidate, CSVSemanticIRCandidate) else dict(candidate)
        obj = candidate if isinstance(candidate, CSVSemanticIRCandidate) else CSVSemanticIRCandidate.from_mapping(raw)
        recomputed_fingerprint = csv_semantic_ir_candidate_fingerprint(obj)
        recomputed_payload_bytes = _candidate_payload_bytes(obj)
    except Exception as exc:
        error = f"semantic_ir_candidate_unreadable:{type(exc).__name__}:{exc}"
        return CSVSemanticIRValidationReport(
            csv_id="",
            status="semantic_ir_candidate_blocked",
            ir_version=CSV_SEMANTIC_IR_VERSION,
            source_candidate_fingerprint="",
            recomputed_candidate_fingerprint="",
            source_payload_bytes=0,
            recomputed_payload_bytes=0,
            payload_byte_limit=CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT,
            errors=(error,),
        )

    errors: list[str] = []
    warnings: list[str] = []
    missing_contract_keys = tuple(key for key in CSV_SEMANTIC_IR_CANDIDATE_CONTRACT_KEYS if key not in raw)
    errors.extend(f"semantic_ir_contract_missing:{key}" for key in missing_contract_keys)

    missing_proposition_keys: list[str] = []
    missing_evidence_ref_keys: list[str] = []
    raw_propositions = raw.get("propositions", ()) or ()
    if not isinstance(raw_propositions, (list, tuple)):
        errors.append("semantic_ir_propositions_not_sequence")
        raw_propositions = ()
    for index, raw_proposition in enumerate(raw_propositions):
        if not isinstance(raw_proposition, Mapping):
            errors.append(f"semantic_ir_proposition_not_mapping:{index}")
            continue
        for key in CSV_SEMANTIC_IR_PROPOSITION_CONTRACT_KEYS:
            if key not in raw_proposition:
                token = f"{index}:{key}"
                missing_proposition_keys.append(token)
                errors.append(f"semantic_ir_proposition_contract_missing:{token}")
        raw_evidence = raw_proposition.get("evidence", ()) or ()
        if not isinstance(raw_evidence, (list, tuple)):
            errors.append(f"semantic_ir_evidence_not_sequence:{index}")
            continue
        for evidence_index, raw_ref in enumerate(raw_evidence):
            if not isinstance(raw_ref, Mapping):
                errors.append(f"semantic_ir_evidence_ref_not_mapping:{index}:{evidence_index}")
                continue
            for key in CSV_SEMANTIC_IR_EVIDENCE_REF_CONTRACT_KEYS:
                if key not in raw_ref:
                    token = f"{index}:{evidence_index}:{key}"
                    missing_evidence_ref_keys.append(token)
                    errors.append(f"semantic_ir_evidence_ref_contract_missing:{token}")

    ids = tuple(item.proposition_id for item in obj.propositions)
    duplicate_ids = tuple(sorted({value for value in ids if ids.count(value) > 1}))
    errors.extend(f"duplicate_proposition_id:{value}" for value in duplicate_ids)

    if obj.ir_version != CSV_SEMANTIC_IR_VERSION:
        errors.append(f"semantic_ir_version_mismatch:{obj.ir_version}")
    if obj.suite_release_version not in CSV_SEMANTIC_IR_COMPATIBLE_RELEASE_VERSIONS:
        errors.append(f"suite_release_version_mismatch:{obj.suite_release_version}")
    if obj.mode != "formal_semantic_ir_candidate":
        errors.append(f"semantic_ir_mode_mismatch:{obj.mode}")
    if obj.handoff_version != CSV_SEMANTIC_IR_HANDOFF_VERSION:
        errors.append(f"semantic_ir_handoff_version_mismatch:{obj.handoff_version}")
    if obj.candidate_fingerprint != recomputed_fingerprint:
        errors.append("semantic_ir_candidate_fingerprint_mismatch")
    if obj.payload_bytes != recomputed_payload_bytes:
        errors.append(f"semantic_ir_payload_size_mismatch:{obj.payload_bytes}!={recomputed_payload_bytes}")
    if obj.payload_bytes > obj.payload_byte_limit:
        errors.append(f"semantic_ir_payload_too_large:{obj.payload_bytes}>{obj.payload_byte_limit}")
    if obj.payload_byte_limit > CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT:
        errors.append(f"semantic_ir_payload_limit_unbounded:{obj.payload_byte_limit}")
    if obj.status not in {"semantic_ir_candidate_ready", "semantic_ir_candidate_blocked"}:
        errors.append(f"semantic_ir_status_invalid:{obj.status}")
    elif obj.status == "semantic_ir_candidate_blocked":
        errors.append("semantic_ir_candidate_source_blocked")
    if obj.status == "semantic_ir_candidate_ready" and not obj.ok:
        errors.append("semantic_ir_candidate_not_ready")
    if obj.status == "semantic_ir_candidate_ready" and not obj.propositions:
        errors.append("semantic_ir_candidate_empty")
    if obj.errors:
        errors.append("semantic_ir_candidate_contains_errors")
    if len(obj.propositions) > CSV_SEMANTIC_IR_MAX_PROPOSITIONS:
        errors.append(
            f"semantic_ir_proposition_count_exceeded:{len(obj.propositions)}>{CSV_SEMANTIC_IR_MAX_PROPOSITIONS}"
        )
    if obj.state_vocabulary != CSV_SEMANTIC_IR_PROPOSITION_STATES:
        errors.append("semantic_ir_state_vocabulary_mismatch")
    if obj.accepted_states != CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES:
        errors.append("semantic_ir_accepted_states_mismatch")
    if not _is_sha256(obj.handoff_closure_fingerprint):
        errors.append("semantic_ir_handoff_fingerprint_invalid")
    if not _is_sha256(obj.raw_sha256):
        errors.append("semantic_ir_raw_sha256_invalid")
    if not _is_sha256(obj.directory_state_fingerprint_before) or not _is_sha256(obj.directory_state_fingerprint_after):
        errors.append("semantic_ir_directory_state_fingerprint_invalid")
    if obj.directory_state_fingerprint_before != obj.directory_state_fingerprint_after or not obj.directory_state_unchanged:
        errors.append("semantic_ir_directory_state_changed")

    required_true = (
        "explicit_opt_in",
        "source_handoff_revalidated",
        "caller_declarations_only",
        "evidence_references_only",
        "immutable_source_evidence",
        "deterministic_replay_required",
    )
    for field_name in required_true:
        if not bool(getattr(obj, field_name)):
            errors.append(f"semantic_ir_required_boundary_false:{field_name}")
    forbidden_true = (
        "lifecycle_transitions_applied",
        "semantic_artifact_persisted",
        "formal_ir_committed",
        "automatic_semantic_reasoning",
        "semantic_conclusions_committed",
        "ai_behavior",
        "automatic_schema_inference",
        "automatic_type_inference",
        "automatic_entity_inference",
        "automatic_row_identity_inference",
        "automatic_cell_meaning_inference",
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
            errors.append(f"semantic_ir_forbidden_boundary_true:{field_name}")
    if obj.tds_artifact_writes != 0:
        errors.append(f"semantic_ir_tds_artifact_writes_nonzero:{obj.tds_artifact_writes}")

    for index, proposition in enumerate(obj.propositions):
        prefix = f"semantic_ir_proposition:{index}:{proposition.proposition_id or '<empty>'}"
        if not proposition.ok:
            errors.append(f"{prefix}:invalid")
        if proposition.state not in CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES:
            errors.append(f"{prefix}:state_not_admitted:{proposition.state}")
        if not proposition.explicit_declaration or proposition.inferred:
            errors.append(f"{prefix}:not_explicit_declaration")
        declaration = proposition.as_declaration()
        if proposition.declaration_fingerprint != csv_semantic_ir_declaration_fingerprint(declaration):
            errors.append(f"{prefix}:declaration_fingerprint_mismatch")
        names = tuple(ref.evidence_name for ref in proposition.evidence)
        if len(set(names)) != len(names):
            errors.append(f"{prefix}:duplicate_evidence_names")
        for ref in proposition.evidence:
            if not ref.ok:
                errors.append(f"{prefix}:evidence_ref_invalid:{ref.evidence_name}")
            if ref.handoff_closure_fingerprint != obj.handoff_closure_fingerprint:
                errors.append(f"{prefix}:handoff_fingerprint_mismatch:{ref.evidence_name}")

    if "proposition_count" in raw and int(raw.get("proposition_count", -1)) != len(obj.propositions):
        errors.append("semantic_ir_proposition_count_mismatch")
    expected_ref_count = sum(len(item.evidence) for item in obj.propositions)
    if "evidence_reference_count" in raw and int(raw.get("evidence_reference_count", -1)) != expected_ref_count:
        errors.append("semantic_ir_evidence_reference_count_mismatch")

    return CSVSemanticIRValidationReport(
        csv_id=obj.csv_id,
        status="semantic_ir_candidate_valid" if not errors else "semantic_ir_candidate_blocked",
        ir_version=obj.ir_version,
        source_candidate_fingerprint=obj.candidate_fingerprint,
        recomputed_candidate_fingerprint=recomputed_fingerprint,
        source_payload_bytes=obj.payload_bytes,
        recomputed_payload_bytes=recomputed_payload_bytes,
        payload_byte_limit=obj.payload_byte_limit,
        missing_contract_keys=missing_contract_keys,
        missing_proposition_keys=tuple(missing_proposition_keys),
        missing_evidence_ref_keys=tuple(missing_evidence_ref_keys),
        duplicate_proposition_ids=duplicate_ids,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _replay_projection(candidate: CSVSemanticIRCandidate) -> dict[str, Any]:
    projection = _candidate_projection(candidate)
    projection.pop("directory_state_fingerprint_before", None)
    projection.pop("directory_state_fingerprint_after", None)
    return projection


def replay_csv_semantic_ir_candidate(
    directory: TDSDirectory,
    csv_id: str,
    source_candidate: CSVSemanticIRCandidate | Mapping[str, Any],
) -> CSVSemanticIRReplayReport:
    """Rebuild a candidate from current committed evidence and compare it."""
    safe_id = str(csv_id)
    state_before = _directory_state_fingerprint(directory, safe_id)
    try:
        raw = source_candidate.to_dict() if isinstance(source_candidate, CSVSemanticIRCandidate) else dict(source_candidate)
        source = source_candidate if isinstance(source_candidate, CSVSemanticIRCandidate) else CSVSemanticIRCandidate.from_mapping(raw)
    except Exception as exc:
        state_after = _directory_state_fingerprint(directory, safe_id)
        return CSVSemanticIRReplayReport(
            csv_id=safe_id,
            status="semantic_ir_replay_blocked",
            ir_version=CSV_SEMANTIC_IR_VERSION,
            source_candidate_fingerprint="",
            replay_candidate_fingerprint="",
            source_handoff_closure_fingerprint="",
            replay_handoff_closure_fingerprint="",
            directory_state_fingerprint_before=state_before,
            directory_state_fingerprint_after=state_after,
            directory_state_unchanged=state_before == state_after,
            errors=(f"semantic_ir_source_unreadable:{type(exc).__name__}:{exc}",),
        )

    validation = validate_csv_semantic_ir_candidate(raw)
    errors: list[str] = []
    warnings: list[str] = []
    if not validation.ok:
        errors.extend(f"semantic_ir_source:{value}" for value in validation.errors)

    declarations = tuple(item.as_declaration() for item in source.propositions)
    replay = prepare_csv_semantic_ir_candidate(
        directory,
        safe_id,
        declarations,
        explicit_opt_in=True,
        payload_byte_limit=source.payload_byte_limit,
    )
    if not replay.ok:
        errors.extend(f"semantic_ir_rebuild:{value}" for value in replay.errors)

    source_projection = _replay_projection(source)
    replay_projection = _replay_projection(replay)
    mismatched_fields = tuple(
        key
        for key in sorted(set(source_projection) | set(replay_projection))
        if source_projection.get(key) != replay_projection.get(key)
    )
    errors.extend(f"semantic_ir_replay_mismatch:{key}" for key in mismatched_fields)

    state_after = _directory_state_fingerprint(directory, safe_id)
    unchanged = state_before == state_after
    if not unchanged:
        errors.append("semantic_ir_replay_mutated_tds_directory_state")

    status = "semantic_ir_replay_valid" if not errors and not mismatched_fields else "semantic_ir_replay_blocked"
    return CSVSemanticIRReplayReport(
        csv_id=safe_id,
        status=status,
        ir_version=CSV_SEMANTIC_IR_VERSION,
        source_candidate_fingerprint=source.candidate_fingerprint,
        replay_candidate_fingerprint=replay.candidate_fingerprint,
        source_handoff_closure_fingerprint=source.handoff_closure_fingerprint,
        replay_handoff_closure_fingerprint=replay.handoff_closure_fingerprint,
        mismatched_fields=mismatched_fields,
        directory_state_fingerprint_before=state_before,
        directory_state_fingerprint_after=state_after,
        directory_state_unchanged=unchanged,
        tds_artifact_writes=0 if unchanged else 1,
        warnings=tuple(dict.fromkeys(warnings)),
        errors=tuple(dict.fromkeys(errors)),
    )


def csv_semantic_ir_candidate_summary(candidate: CSVSemanticIRCandidate) -> dict[str, Any]:
    """Return a compact JSON-safe candidate summary."""
    return candidate.to_dict()


def csv_semantic_ir_replay_summary(report: CSVSemanticIRReplayReport) -> dict[str, Any]:
    """Return a compact JSON-safe replay summary."""
    return report.to_dict()

"""Generic immutable Generation Authority contracts for TDS v3.7.

The Generation Authority is a mechanical storage/publication primitive. It
binds immutable payloads and qualification evidence into one generation,
records append-only lifecycle/publication receipts, and gives readers one
pinned generation identity. It has no semantic, ranking, model, policy, or
activation authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

GENERATION_FORMAT_VERSION = 1
GENERATION_CONTRACT_ID = "tds-generation-authority-v1"
GENERATION_HASH_ALGORITHM = "sha256"
GENERATION_LIFECYCLE = (
    "staging",
    "sealed",
    "verified",
    "published",
    "retired",
)

_ROOT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,190}$")
_DOMAIN = b"STAQTAPP-TDS\x00GENERATION-AUTHORITY\x00V1\x00"
_UINT63_MAX = (1 << 63) - 1


class GenerationFault(str, Enum):
    NONE = "none"
    INVALID_INPUT = "invalid_input"
    BOUND_EXCEEDED = "bound_exceeded"
    IDENTITY_MISMATCH = "identity_mismatch"
    INCOMPLETE_GENERATION = "incomplete_generation"
    NONCANONICAL = "noncanonical"
    INTEGRITY_FAILURE = "integrity_failure"
    PUBLICATION_CONFLICT = "publication_conflict"
    IO_FAILURE = "io_failure"
    RECOVERY_FAILURE = "recovery_failure"
    AUTHORITY_REJECTED = "authority_rejected"


class GenerationState(str, Enum):
    STAGING = "staging"
    SEALED = "sealed"
    VERIFIED = "verified"
    PUBLISHED = "published"
    RETIRED = "retired"


class PublicationAction(str, Enum):
    PUBLISH = "publish"
    ROLLBACK = "rollback"


class GenerationContractError(ValueError):
    """A deterministic Generation Authority contract failure."""

    def __init__(
        self,
        message: str,
        *,
        fault: GenerationFault = GenerationFault.INVALID_INPUT,
    ) -> None:
        super().__init__(message)
        self.fault = fault


def _require_int(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GenerationContractError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise GenerationContractError(
            f"{name} must be between {minimum} and {maximum}",
            fault=GenerationFault.BOUND_EXCEEDED,
        )
    return value


def _require_name(name: str, value: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise GenerationContractError(f"{name} is not canonical")
    return value


def require_root(name: str, value: str | None, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _ROOT_RE.fullmatch(value):
        raise GenerationContractError(
            f"{name} must be a canonical sha256 root",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    return value


def canonical_json_bytes(value: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def canonical_root(domain: str, value: Mapping[str, Any] | Sequence[Any]) -> str:
    domain_bytes = _require_name("root domain", domain).encode("ascii")
    digest = hashlib.sha256(_DOMAIN + domain_bytes + b"\x00" + canonical_json_bytes(value))
    return f"sha256:{digest.hexdigest()}"


def bytes_root(data: bytes) -> str:
    if not isinstance(data, bytes):
        raise GenerationContractError("payload data must be exact bytes")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@dataclass(frozen=True, slots=True)
class QualifiedGenerationLimits:
    max_payloads: int = 4096
    max_payload_bytes: int = 1 << 34
    max_single_payload_bytes: int = 1 << 32
    max_qualification_roots: int = 256
    max_metadata_entries: int = 128
    max_manifest_bytes: int = 8 << 20
    max_publication_records: int = 1 << 31
    max_reader_pins: int = 1 << 20

    def __post_init__(self) -> None:
        _require_int("max_payloads", self.max_payloads, 1, 1 << 20)
        _require_int("max_payload_bytes", self.max_payload_bytes, 1, _UINT63_MAX)
        _require_int(
            "max_single_payload_bytes",
            self.max_single_payload_bytes,
            1,
            self.max_payload_bytes,
        )
        _require_int(
            "max_qualification_roots",
            self.max_qualification_roots,
            0,
            1 << 20,
        )
        _require_int("max_metadata_entries", self.max_metadata_entries, 0, 1 << 20)
        _require_int("max_manifest_bytes", self.max_manifest_bytes, 1024, 1 << 30)
        _require_int(
            "max_publication_records",
            self.max_publication_records,
            1,
            _UINT63_MAX,
        )
        _require_int("max_reader_pins", self.max_reader_pins, 1, 1 << 30)

    def canonical_dict(self) -> dict[str, int]:
        return asdict(self)

    @property
    def limits_root(self) -> str:
        return canonical_root("limits", self.canonical_dict())


DEFAULT_GENERATION_LIMITS = QualifiedGenerationLimits()


@dataclass(frozen=True, slots=True)
class GenerationPayload:
    name: str
    media_type: str
    size: int
    content_root: str
    authoritative: bool = False

    def __post_init__(self) -> None:
        _require_name("payload name", self.name)
        _require_name("payload media_type", self.media_type)
        _require_int("payload size", self.size, 0, _UINT63_MAX)
        require_root("payload content_root", self.content_root)
        if not isinstance(self.authoritative, bool):
            raise GenerationContractError("payload authoritative must be boolean")

    def canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def payload_root(self) -> str:
        return canonical_root("payload-identity", self.canonical_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationPayload":
        if set(value) != {
            "name",
            "media_type",
            "size",
            "content_root",
            "authoritative",
        }:
            raise GenerationContractError("payload fields are not canonical")
        return cls(
            name=value["name"],
            media_type=value["media_type"],
            size=value["size"],
            content_root=value["content_root"],
            authoritative=value["authoritative"],
        )


@dataclass(frozen=True, slots=True)
class QualificationRoot:
    name: str
    evidence_root: str

    def __post_init__(self) -> None:
        _require_name("qualification name", self.name)
        require_root("qualification evidence_root", self.evidence_root)

    def canonical_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def qualification_root(self) -> str:
        return canonical_root("qualification", self.canonical_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QualificationRoot":
        if set(value) != {"name", "evidence_root"}:
            raise GenerationContractError("qualification fields are not canonical")
        return cls(name=value["name"], evidence_root=value["evidence_root"])


@dataclass(frozen=True, slots=True)
class GenerationManifest:
    namespace: str
    parent_generation_root: str | None
    payloads: tuple[GenerationPayload, ...]
    qualifications: tuple[QualificationRoot, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()
    limits: QualifiedGenerationLimits = DEFAULT_GENERATION_LIMITS
    format_version: int = GENERATION_FORMAT_VERSION
    contract_id: str = GENERATION_CONTRACT_ID

    def __post_init__(self) -> None:
        _require_name("namespace", self.namespace)
        require_root(
            "parent_generation_root",
            self.parent_generation_root,
            optional=True,
        )
        if self.format_version != GENERATION_FORMAT_VERSION:
            raise GenerationContractError("unsupported generation format version")
        if self.contract_id != GENERATION_CONTRACT_ID:
            raise GenerationContractError("unsupported generation contract")
        if not isinstance(self.payloads, tuple) or not self.payloads:
            raise GenerationContractError("generation requires at least one payload")
        if not isinstance(self.qualifications, tuple):
            raise GenerationContractError("qualifications must be a tuple")
        if not isinstance(self.metadata, tuple):
            raise GenerationContractError("metadata must be a tuple")
        if tuple(sorted(self.payloads, key=lambda item: item.name)) != self.payloads:
            raise GenerationContractError(
                "payloads must be sorted by canonical name",
                fault=GenerationFault.NONCANONICAL,
            )
        payload_names = tuple(item.name for item in self.payloads)
        if len(set(payload_names)) != len(payload_names):
            raise GenerationContractError("duplicate payload name")
        if tuple(sorted(self.qualifications, key=lambda item: item.name)) != self.qualifications:
            raise GenerationContractError(
                "qualifications must be sorted by canonical name",
                fault=GenerationFault.NONCANONICAL,
            )
        qualification_names = tuple(item.name for item in self.qualifications)
        if len(set(qualification_names)) != len(qualification_names):
            raise GenerationContractError("duplicate qualification name")
        normalized_metadata: list[tuple[str, str]] = []
        for entry in self.metadata:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 2
                or not isinstance(entry[0], str)
                or not isinstance(entry[1], str)
            ):
                raise GenerationContractError("metadata entries must be string pairs")
            key = _require_name("metadata key", entry[0])
            value = entry[1]
            if not value or value != value.strip() or len(value.encode("utf-8")) > 4096:
                raise GenerationContractError("metadata value is not canonical")
            normalized_metadata.append((key, value))
        if tuple(sorted(normalized_metadata)) != self.metadata:
            raise GenerationContractError(
                "metadata must be sorted and unique",
                fault=GenerationFault.NONCANONICAL,
            )
        if len({key for key, _ in self.metadata}) != len(self.metadata):
            raise GenerationContractError("duplicate metadata key")
        if len(self.payloads) > self.limits.max_payloads:
            raise GenerationContractError(
                "payload count exceeds qualified limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        if len(self.qualifications) > self.limits.max_qualification_roots:
            raise GenerationContractError(
                "qualification count exceeds qualified limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        if len(self.metadata) > self.limits.max_metadata_entries:
            raise GenerationContractError(
                "metadata count exceeds qualified limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        total = 0
        authoritative_count = 0
        for payload in self.payloads:
            if payload.size > self.limits.max_single_payload_bytes:
                raise GenerationContractError(
                    "single payload exceeds qualified limit",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            if total > self.limits.max_payload_bytes - payload.size:
                raise GenerationContractError(
                    "payload bytes exceed qualified limit",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            total += payload.size
            authoritative_count += int(payload.authoritative)
        if authoritative_count > 1:
            raise GenerationContractError(
                "a generation may declare at most one authoritative source payload"
            )
        if len(self.canonical_bytes()) > self.limits.max_manifest_bytes:
            raise GenerationContractError(
                "manifest exceeds qualified limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "format_version": self.format_version,
            "namespace": self.namespace,
            "parent_generation_root": self.parent_generation_root,
            "payloads": [item.canonical_dict() for item in self.payloads],
            "qualifications": [
                item.canonical_dict() for item in self.qualifications
            ],
            "metadata": [[key, value] for key, value in self.metadata],
            "limits": self.limits.canonical_dict(),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @property
    def manifest_root(self) -> str:
        return canonical_root("manifest", self.canonical_dict())

    @property
    def generation_root(self) -> str:
        return canonical_root(
            "generation",
            {
                "manifest_root": self.manifest_root,
                "namespace": self.namespace,
                "parent_generation_root": self.parent_generation_root,
                "payload_roots": [item.payload_root for item in self.payloads],
                "qualification_roots": [
                    item.qualification_root for item in self.qualifications
                ],
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationManifest":
        expected = {
            "contract_id",
            "format_version",
            "namespace",
            "parent_generation_root",
            "payloads",
            "qualifications",
            "metadata",
            "limits",
        }
        if set(value) != expected:
            raise GenerationContractError("manifest fields are not canonical")
        limits_value = value["limits"]
        if not isinstance(limits_value, Mapping):
            raise GenerationContractError("manifest limits are malformed")
        limits = QualifiedGenerationLimits(**dict(limits_value))
        payload_values = value["payloads"]
        qualification_values = value["qualifications"]
        metadata_values = value["metadata"]
        if not isinstance(payload_values, list):
            raise GenerationContractError("manifest payloads are malformed")
        if not isinstance(qualification_values, list):
            raise GenerationContractError("manifest qualifications are malformed")
        if not isinstance(metadata_values, list):
            raise GenerationContractError("manifest metadata is malformed")
        metadata: list[tuple[str, str]] = []
        for item in metadata_values:
            if not isinstance(item, list) or len(item) != 2:
                raise GenerationContractError("manifest metadata entry is malformed")
            metadata.append((item[0], item[1]))
        return cls(
            contract_id=value["contract_id"],
            format_version=value["format_version"],
            namespace=value["namespace"],
            parent_generation_root=value["parent_generation_root"],
            payloads=tuple(GenerationPayload.from_dict(item) for item in payload_values),
            qualifications=tuple(
                QualificationRoot.from_dict(item) for item in qualification_values
            ),
            metadata=tuple(metadata),
            limits=limits,
        )


@dataclass(frozen=True, slots=True)
class GenerationLifecycleReceipt:
    generation_root: str
    manifest_root: str
    state: GenerationState
    sequence: int
    predecessor_receipt_root: str | None

    def __post_init__(self) -> None:
        require_root("generation_root", self.generation_root)
        require_root("manifest_root", self.manifest_root)
        if not isinstance(self.state, GenerationState):
            raise GenerationContractError("receipt state is invalid")
        _require_int("receipt sequence", self.sequence, 0, len(GENERATION_LIFECYCLE) - 1)
        require_root(
            "predecessor_receipt_root",
            self.predecessor_receipt_root,
            optional=True,
        )
        if self.sequence != GENERATION_LIFECYCLE.index(self.state.value):
            raise GenerationContractError(
                "receipt sequence does not match lifecycle state",
                fault=GenerationFault.NONCANONICAL,
            )
        if self.sequence == 0 and self.predecessor_receipt_root is not None:
            raise GenerationContractError("staging receipt cannot have a predecessor")
        if self.sequence > 0 and self.predecessor_receipt_root is None:
            raise GenerationContractError("non-initial receipt requires a predecessor")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": GENERATION_CONTRACT_ID,
            "generation_root": self.generation_root,
            "manifest_root": self.manifest_root,
            "state": self.state.value,
            "sequence": self.sequence,
            "predecessor_receipt_root": self.predecessor_receipt_root,
        }

    @property
    def receipt_root(self) -> str:
        return canonical_root("lifecycle-receipt", self.canonical_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationLifecycleReceipt":
        expected = {
            "contract_id",
            "generation_root",
            "manifest_root",
            "state",
            "sequence",
            "predecessor_receipt_root",
        }
        if set(value) != expected or value["contract_id"] != GENERATION_CONTRACT_ID:
            raise GenerationContractError("lifecycle receipt fields are not canonical")
        return cls(
            generation_root=value["generation_root"],
            manifest_root=value["manifest_root"],
            state=GenerationState(value["state"]),
            sequence=value["sequence"],
            predecessor_receipt_root=value["predecessor_receipt_root"],
        )


@dataclass(frozen=True, slots=True)
class GenerationPublicationRecord:
    namespace: str
    publication_sequence: int
    action: PublicationAction
    generation_root: str
    manifest_root: str
    published_receipt_root: str
    previous_generation_root: str | None
    predecessor_record_root: str | None

    def __post_init__(self) -> None:
        _require_name("namespace", self.namespace)
        _require_int("publication_sequence", self.publication_sequence, 1, _UINT63_MAX)
        if not isinstance(self.action, PublicationAction):
            raise GenerationContractError("publication action is invalid")
        require_root("generation_root", self.generation_root)
        require_root("manifest_root", self.manifest_root)
        require_root("published_receipt_root", self.published_receipt_root)
        require_root(
            "previous_generation_root",
            self.previous_generation_root,
            optional=True,
        )
        require_root(
            "predecessor_record_root",
            self.predecessor_record_root,
            optional=True,
        )
        if self.publication_sequence == 1 and self.predecessor_record_root is not None:
            raise GenerationContractError("first publication cannot have a predecessor")
        if self.publication_sequence > 1 and self.predecessor_record_root is None:
            raise GenerationContractError("publication requires predecessor record")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": GENERATION_CONTRACT_ID,
            "namespace": self.namespace,
            "publication_sequence": self.publication_sequence,
            "action": self.action.value,
            "generation_root": self.generation_root,
            "manifest_root": self.manifest_root,
            "published_receipt_root": self.published_receipt_root,
            "previous_generation_root": self.previous_generation_root,
            "predecessor_record_root": self.predecessor_record_root,
        }

    @property
    def record_root(self) -> str:
        return canonical_root("publication-record", self.canonical_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationPublicationRecord":
        expected = {
            "contract_id",
            "namespace",
            "publication_sequence",
            "action",
            "generation_root",
            "manifest_root",
            "published_receipt_root",
            "previous_generation_root",
            "predecessor_record_root",
        }
        if set(value) != expected or value["contract_id"] != GENERATION_CONTRACT_ID:
            raise GenerationContractError("publication record fields are not canonical")
        return cls(
            namespace=value["namespace"],
            publication_sequence=value["publication_sequence"],
            action=PublicationAction(value["action"]),
            generation_root=value["generation_root"],
            manifest_root=value["manifest_root"],
            published_receipt_root=value["published_receipt_root"],
            previous_generation_root=value["previous_generation_root"],
            predecessor_record_root=value["predecessor_record_root"],
        )


@dataclass(frozen=True, slots=True)
class GenerationHead:
    namespace: str
    publication_sequence: int
    generation_root: str
    manifest_root: str
    publication_record_root: str

    def __post_init__(self) -> None:
        _require_name("namespace", self.namespace)
        _require_int("publication_sequence", self.publication_sequence, 1, _UINT63_MAX)
        require_root("generation_root", self.generation_root)
        require_root("manifest_root", self.manifest_root)
        require_root("publication_record_root", self.publication_record_root)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": GENERATION_CONTRACT_ID,
            "namespace": self.namespace,
            "publication_sequence": self.publication_sequence,
            "generation_root": self.generation_root,
            "manifest_root": self.manifest_root,
            "publication_record_root": self.publication_record_root,
        }

    @property
    def head_root(self) -> str:
        return canonical_root("current-head", self.canonical_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationHead":
        expected = {
            "contract_id",
            "namespace",
            "publication_sequence",
            "generation_root",
            "manifest_root",
            "publication_record_root",
        }
        if set(value) != expected or value["contract_id"] != GENERATION_CONTRACT_ID:
            raise GenerationContractError("head fields are not canonical")
        return cls(
            namespace=value["namespace"],
            publication_sequence=value["publication_sequence"],
            generation_root=value["generation_root"],
            manifest_root=value["manifest_root"],
            publication_record_root=value["publication_record_root"],
        )


@dataclass(frozen=True, slots=True)
class GenerationAuthorityBoundary:
    immutable_payload_publication: bool = True
    compare_and_swap_publication: bool = True
    reader_pinning: bool = True
    deterministic_recovery: bool = True
    retirement_recording: bool = True
    semantic_authority: bool = False
    ranking_authority: bool = False
    model_authority: bool = False
    policy_authority: bool = False
    training_authority: bool = False
    activation_authority: bool = False
    browser_publication_authority: bool = False
    studio_publication_authority: bool = False
    learned_write_authority: bool = False

    def __post_init__(self) -> None:
        permitted = (
            self.immutable_payload_publication,
            self.compare_and_swap_publication,
            self.reader_pinning,
            self.deterministic_recovery,
            self.retirement_recording,
        )
        denied = (
            self.semantic_authority,
            self.ranking_authority,
            self.model_authority,
            self.policy_authority,
            self.training_authority,
            self.activation_authority,
            self.browser_publication_authority,
            self.studio_publication_authority,
            self.learned_write_authority,
        )
        if not all(permitted) or any(denied):
            raise GenerationContractError(
                "Generation Authority boundary cannot be widened",
                fault=GenerationFault.AUTHORITY_REJECTED,
            )

    def canonical_dict(self) -> dict[str, bool]:
        return asdict(self)

    @property
    def boundary_root(self) -> str:
        return canonical_root("authority-boundary", self.canonical_dict())


GENERATION_AUTHORITY = GenerationAuthorityBoundary()


def build_manifest(
    *,
    namespace: str,
    payloads: Mapping[str, tuple[bytes, str, bool]],
    parent_generation_root: str | None = None,
    qualifications: Mapping[str, str] | None = None,
    metadata: Mapping[str, str] | None = None,
    limits: QualifiedGenerationLimits = DEFAULT_GENERATION_LIMITS,
) -> GenerationManifest:
    if not isinstance(payloads, Mapping) or not payloads:
        raise GenerationContractError("payloads must be a non-empty mapping")
    payload_records: list[GenerationPayload] = []
    for name, spec in payloads.items():
        if (
            not isinstance(spec, tuple)
            or len(spec) != 3
            or not isinstance(spec[0], bytes)
            or not isinstance(spec[1], str)
            or not isinstance(spec[2], bool)
        ):
            raise GenerationContractError(
                "payload specification must be (bytes, media_type, authoritative)"
            )
        data, media_type, authoritative = spec
        payload_records.append(
            GenerationPayload(
                name=name,
                media_type=media_type,
                size=len(data),
                content_root=bytes_root(data),
                authoritative=authoritative,
            )
        )
    qualification_records = tuple(
        QualificationRoot(name=name, evidence_root=root)
        for name, root in sorted((qualifications or {}).items())
    )
    metadata_records = tuple(sorted((metadata or {}).items()))
    return GenerationManifest(
        namespace=namespace,
        parent_generation_root=parent_generation_root,
        payloads=tuple(sorted(payload_records, key=lambda item: item.name)),
        qualifications=qualification_records,
        metadata=metadata_records,
        limits=limits,
    )


def build_lifecycle_chain(
    manifest: GenerationManifest,
    *,
    through: GenerationState = GenerationState.PUBLISHED,
) -> tuple[GenerationLifecycleReceipt, ...]:
    target = GENERATION_LIFECYCLE.index(through.value)
    result: list[GenerationLifecycleReceipt] = []
    predecessor: str | None = None
    for sequence, state_value in enumerate(GENERATION_LIFECYCLE[: target + 1]):
        receipt = GenerationLifecycleReceipt(
            generation_root=manifest.generation_root,
            manifest_root=manifest.manifest_root,
            state=GenerationState(state_value),
            sequence=sequence,
            predecessor_receipt_root=predecessor,
        )
        result.append(receipt)
        predecessor = receipt.receipt_root
    return tuple(result)


def validate_lifecycle_chain(
    manifest: GenerationManifest,
    receipts: Sequence[GenerationLifecycleReceipt],
    *,
    required_state: GenerationState = GenerationState.PUBLISHED,
) -> GenerationLifecycleReceipt:
    if not receipts:
        raise GenerationContractError(
            "lifecycle receipt chain is empty",
            fault=GenerationFault.INCOMPLETE_GENERATION,
        )
    expected_states = GENERATION_LIFECYCLE[
        : GENERATION_LIFECYCLE.index(required_state.value) + 1
    ]
    if len(receipts) < len(expected_states):
        raise GenerationContractError(
            "lifecycle receipt chain is incomplete",
            fault=GenerationFault.INCOMPLETE_GENERATION,
        )
    predecessor: str | None = None
    for index, state_value in enumerate(expected_states):
        receipt = receipts[index]
        if receipt.state.value != state_value or receipt.sequence != index:
            raise GenerationContractError(
                "lifecycle transition is not adjacent",
                fault=GenerationFault.NONCANONICAL,
            )
        if (
            receipt.generation_root != manifest.generation_root
            or receipt.manifest_root != manifest.manifest_root
            or receipt.predecessor_receipt_root != predecessor
        ):
            raise GenerationContractError(
                "lifecycle receipt identity mismatch",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        predecessor = receipt.receipt_root
    return receipts[len(expected_states) - 1]


def validate_publication_record(
    record: GenerationPublicationRecord,
    *,
    previous_record: GenerationPublicationRecord | None,
    expected_current_root: str | None,
) -> None:
    require_root("expected_current_root", expected_current_root, optional=True)
    if previous_record is None:
        if record.publication_sequence != 1:
            raise GenerationContractError(
                "first publication sequence must be one",
                fault=GenerationFault.NONCANONICAL,
            )
        if record.predecessor_record_root is not None:
            raise GenerationContractError("first publication has predecessor")
        if record.previous_generation_root != expected_current_root:
            raise GenerationContractError(
                "first publication current-root mismatch",
                fault=GenerationFault.PUBLICATION_CONFLICT,
            )
        return
    if record.namespace != previous_record.namespace:
        raise GenerationContractError(
            "publication namespace mismatch",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    if record.publication_sequence != previous_record.publication_sequence + 1:
        raise GenerationContractError(
            "publication sequence is not contiguous",
            fault=GenerationFault.NONCANONICAL,
        )
    if record.predecessor_record_root != previous_record.record_root:
        raise GenerationContractError(
            "publication predecessor mismatch",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    if record.previous_generation_root != expected_current_root:
        raise GenerationContractError(
            "publication compare-and-swap conflict",
            fault=GenerationFault.PUBLICATION_CONFLICT,
        )


def validate_generation_bindings(
    expected_generation_root: str,
    bindings: Mapping[str, str],
) -> None:
    require_root("expected_generation_root", expected_generation_root)
    if not isinstance(bindings, Mapping) or not bindings:
        raise GenerationContractError("generation bindings must be non-empty")
    for name, root in bindings.items():
        _require_name("binding name", name)
        require_root(f"binding {name}", root)
        if root != expected_generation_root:
            raise GenerationContractError(
                f"mixed generation binding: {name}",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )


def manifest_from_json(data: bytes) -> GenerationManifest:
    if not isinstance(data, bytes):
        raise GenerationContractError("manifest input must be bytes")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationContractError("manifest JSON is malformed") from exc
    if not isinstance(value, Mapping):
        raise GenerationContractError("manifest JSON must be an object")
    manifest = GenerationManifest.from_dict(value)
    if manifest.canonical_bytes() != data:
        raise GenerationContractError(
            "manifest JSON is not canonical",
            fault=GenerationFault.NONCANONICAL,
        )
    return manifest


def publication_record_from_json(data: bytes) -> GenerationPublicationRecord:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationContractError("publication JSON is malformed") from exc
    if not isinstance(value, Mapping):
        raise GenerationContractError("publication JSON must be an object")
    record = GenerationPublicationRecord.from_dict(value)
    if canonical_json_bytes(record.canonical_dict()) != data:
        raise GenerationContractError(
            "publication JSON is not canonical",
            fault=GenerationFault.NONCANONICAL,
        )
    return record


__all__ = [
    "DEFAULT_GENERATION_LIMITS",
    "GENERATION_AUTHORITY",
    "GENERATION_CONTRACT_ID",
    "GENERATION_FORMAT_VERSION",
    "GENERATION_HASH_ALGORITHM",
    "GENERATION_LIFECYCLE",
    "GenerationAuthorityBoundary",
    "GenerationContractError",
    "GenerationFault",
    "GenerationHead",
    "GenerationLifecycleReceipt",
    "GenerationManifest",
    "GenerationPayload",
    "GenerationPublicationRecord",
    "GenerationState",
    "PublicationAction",
    "QualificationRoot",
    "QualifiedGenerationLimits",
    "build_lifecycle_chain",
    "build_manifest",
    "bytes_root",
    "canonical_json_bytes",
    "canonical_root",
    "manifest_from_json",
    "publication_record_from_json",
    "require_root",
    "validate_generation_bindings",
    "validate_lifecycle_chain",
    "validate_publication_record",
]

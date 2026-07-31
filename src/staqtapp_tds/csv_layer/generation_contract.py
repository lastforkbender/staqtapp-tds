"""Contract-only identities for the atomic CSV Generation Plane.

This module intentionally performs no storage publication, native parsing,
graph construction, ranking, training, or activation.  It fixes the immutable
identity, bounds, authority, and transition rules that the v3.7 implementation
must satisfy before learned Trace Ranking can consume CSV evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

CSV_GENERATION_FORMAT_VERSION = 1
CSV_GENERATION_CONTRACT_ID = "tds-csv-generation-v1"
CSV_GENERATION_CHECKSUM_ALGORITHM = "crc32-ieee-v1"

_UINT32_MAX = (1 << 32) - 1
_UINT63_MAX = (1 << 63) - 1
_IDENTITY_MAX_BYTES = 192
_ROOT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROOT_DOMAIN_PREFIX = b"STAQTAPP-TDS\x00CSV-GENERATION\x00V1\x00"


class CSVGenerationFault(str, Enum):
    """Stable Phase-3 contract failure classes."""

    NONE = "none"
    INVALID_INPUT = "invalid_input"
    BOUND_EXCEEDED = "bound_exceeded"
    IDENTITY_MISMATCH = "identity_mismatch"
    INCOMPLETE_GENERATION = "incomplete_generation"
    NONCANONICAL = "noncanonical"
    AUTHORITY_REJECTED = "authority_rejected"
    PUBLICATION_CONFLICT = "publication_conflict"


class CSVGenerationState(str, Enum):
    """Deterministic publication-controller states."""

    STAGING = "staging"
    SEALED = "sealed"
    VERIFIED = "verified"
    PUBLISHED = "published"
    RETIRED = "retired"


class CSVGenerationContractError(ValueError):
    """A deterministic generation contract failure with a stable fault."""

    def __init__(
        self,
        message: str,
        *,
        fault: CSVGenerationFault = CSVGenerationFault.INVALID_INPUT,
    ) -> None:
        super().__init__(message)
        self.fault = fault


def _require_int(name: str, value: int, *, minimum: int = 0, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CSVGenerationContractError(f"{name} must be an integer")
    if value < minimum:
        raise CSVGenerationContractError(f"{name} must be at least {minimum}")
    if value > maximum:
        raise CSVGenerationContractError(
            f"{name} exceeds the wire-format maximum {maximum}",
            fault=CSVGenerationFault.BOUND_EXCEEDED,
        )
    return value


def _validate_identity(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise CSVGenerationContractError(f"{name} must be a non-empty string")
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise CSVGenerationContractError(f"{name} must be printable ASCII") from exc
    if len(raw) > _IDENTITY_MAX_BYTES:
        raise CSVGenerationContractError(
            f"{name} exceeds {_IDENTITY_MAX_BYTES} encoded bytes",
            fault=CSVGenerationFault.BOUND_EXCEEDED,
        )
    if any(byte < 0x21 or byte > 0x7E for byte in raw):
        raise CSVGenerationContractError(
            f"{name} must not contain whitespace or control characters"
        )
    return value


def _validate_root(name: str, value: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not isinstance(value, str) or not _ROOT_PATTERN.fullmatch(value):
        raise CSVGenerationContractError(
            f"{name} must be an exact lowercase sha256:<64-hex> identity",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    return value


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CSVGenerationContractError("value is not canonically JSON encodable") from exc


def _canonical_root(domain: str, value: Mapping[str, Any]) -> str:
    material = (
        _ROOT_DOMAIN_PREFIX
        + domain.encode("ascii")
        + b"\x00"
        + _canonical_json_bytes(value)
    )
    return "sha256:" + hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class CSVGenerationLimits:
    """A qualified profile that can only narrow mechanical wire maxima."""

    max_source_bytes: int
    max_chunk_bytes: int
    max_chunks: int
    max_rows: int
    max_closure_nodes: int
    max_closure_edges: int

    def __post_init__(self) -> None:
        _require_int(
            "max_source_bytes",
            self.max_source_bytes,
            minimum=0,
            maximum=_UINT63_MAX,
        )
        _require_int(
            "max_chunk_bytes",
            self.max_chunk_bytes,
            minimum=1,
            maximum=_UINT32_MAX,
        )
        _require_int(
            "max_chunks",
            self.max_chunks,
            minimum=1,
            maximum=_UINT32_MAX,
        )
        _require_int(
            "max_rows",
            self.max_rows,
            minimum=0,
            maximum=_UINT63_MAX,
        )
        _require_int(
            "max_closure_nodes",
            self.max_closure_nodes,
            minimum=1,
            maximum=_UINT32_MAX,
        )
        _require_int(
            "max_closure_edges",
            self.max_closure_edges,
            minimum=0,
            maximum=_UINT32_MAX,
        )
        if self.max_chunk_bytes > self.max_source_bytes and self.max_source_bytes != 0:
            raise CSVGenerationContractError(
                "max_chunk_bytes cannot exceed a non-zero max_source_bytes"
            )

    def canonical_dict(self) -> dict[str, int | str]:
        return {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def limits_root(self) -> str:
        return _canonical_root("limits", self.canonical_dict())

    @classmethod
    def qualification_profile(cls) -> "CSVGenerationLimits":
        """Initial bounded qualification profile; deployments may narrow it."""

        return cls(
            max_source_bytes=1 << 40,
            max_chunk_bytes=64 << 20,
            max_chunks=1 << 20,
            max_rows=1 << 40,
            max_closure_nodes=1 << 24,
            max_closure_edges=1 << 26,
        )


@dataclass(frozen=True, slots=True)
class CSVChunkDescriptor:
    """One ordered non-empty immutable source-byte span."""

    ordinal: int
    start_offset: int
    end_offset: int
    content_root: str
    checksum_algorithm: str = CSV_GENERATION_CHECKSUM_ALGORITHM

    def __post_init__(self) -> None:
        _require_int("ordinal", self.ordinal, minimum=0, maximum=_UINT32_MAX)
        _require_int(
            "start_offset", self.start_offset, minimum=0, maximum=_UINT63_MAX
        )
        _require_int("end_offset", self.end_offset, minimum=0, maximum=_UINT63_MAX)
        if self.end_offset <= self.start_offset:
            raise CSVGenerationContractError(
                "chunk spans must be non-empty and strictly increasing",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        _validate_root("content_root", self.content_root)
        _validate_identity("checksum_algorithm", self.checksum_algorithm)
        if self.checksum_algorithm != CSV_GENERATION_CHECKSUM_ALGORITHM:
            raise CSVGenerationContractError(
                "new generation chunks must use crc32-ieee-v1",
                fault=CSVGenerationFault.NONCANONICAL,
            )

    def canonical_dict(self) -> dict[str, int | str]:
        return asdict(self)



def chunk_sequence_root(chunks: Sequence[CSVChunkDescriptor]) -> str:
    """Return the root of one exact ordered chunk sequence."""

    return _canonical_root(
        "chunk-sequence",
        {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            "chunks": [chunk.canonical_dict() for chunk in chunks],
        },
    )


@dataclass(frozen=True, slots=True)
class CSVGenerationIdentity:
    """One complete immutable generation identity."""

    dataset_id: str
    source_sha256: str
    chunk_sequence_root: str
    parser_contract_root: str
    dialect_root: str
    row_offsets_root: str
    row_anchors_root: str
    closure_root: str
    limits_root: str
    parent_generation_root: str = ""

    def __post_init__(self) -> None:
        _validate_identity("dataset_id", self.dataset_id)
        for item in fields(self):
            if item.name == "dataset_id":
                continue
            _validate_root(
                item.name,
                getattr(self, item.name),
                allow_empty=item.name == "parent_generation_root",
            )

    def canonical_dict(self) -> dict[str, str | int]:
        return {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def generation_root(self) -> str:
        return _canonical_root("generation", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CSVGenerationManifest:
    """Canonical immutable structure of one sealed generation."""

    identity: CSVGenerationIdentity
    source_bytes: int
    row_count: int
    closure_node_count: int
    closure_edge_count: int
    chunks: tuple[CSVChunkDescriptor, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CSVGenerationIdentity):
            raise CSVGenerationContractError(
                "identity must be a CSVGenerationIdentity instance"
            )
        _require_int(
            "source_bytes", self.source_bytes, minimum=0, maximum=_UINT63_MAX
        )
        _require_int("row_count", self.row_count, minimum=0, maximum=_UINT63_MAX)
        _require_int(
            "closure_node_count",
            self.closure_node_count,
            minimum=1,
            maximum=_UINT32_MAX,
        )
        _require_int(
            "closure_edge_count",
            self.closure_edge_count,
            minimum=0,
            maximum=_UINT32_MAX,
        )
        if not isinstance(self.chunks, tuple) or any(
            not isinstance(chunk, CSVChunkDescriptor) for chunk in self.chunks
        ):
            raise CSVGenerationContractError(
                "chunks must be a tuple of CSVChunkDescriptor values"
            )

        if self.source_bytes == 0:
            if self.chunks:
                raise CSVGenerationContractError(
                    "empty input has one canonical representation with no chunks",
                    fault=CSVGenerationFault.NONCANONICAL,
                )
        else:
            if not self.chunks:
                raise CSVGenerationContractError(
                    "non-empty input requires at least one source chunk",
                    fault=CSVGenerationFault.INCOMPLETE_GENERATION,
                )
            expected_start = 0
            for ordinal, chunk in enumerate(self.chunks):
                if chunk.ordinal != ordinal:
                    raise CSVGenerationContractError(
                        "chunk ordinals must be contiguous from zero",
                        fault=CSVGenerationFault.NONCANONICAL,
                    )
                if chunk.start_offset != expected_start:
                    raise CSVGenerationContractError(
                        "chunk spans must be contiguous without gaps or overlap",
                        fault=CSVGenerationFault.NONCANONICAL,
                    )
                expected_start = chunk.end_offset
            if expected_start != self.source_bytes:
                raise CSVGenerationContractError(
                    "ordered chunks do not cover the exact authoritative byte extent",
                    fault=CSVGenerationFault.INCOMPLETE_GENERATION,
                )

        if chunk_sequence_root(self.chunks) != self.identity.chunk_sequence_root:
            raise CSVGenerationContractError(
                "chunk sequence does not match the generation identity",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            "identity": self.identity.canonical_dict(),
            "generation_root": self.identity.generation_root,
            "source_bytes": self.source_bytes,
            "row_count": self.row_count,
            "closure_node_count": self.closure_node_count,
            "closure_edge_count": self.closure_edge_count,
            "chunks": [chunk.canonical_dict() for chunk in self.chunks],
        }

    @property
    def manifest_root(self) -> str:
        return _canonical_root("manifest", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CSVGenerationReceipt:
    """Append-only controller evidence for one generation state."""

    generation_root: str
    manifest_root: str
    state: CSVGenerationState
    previous_receipt_root: str = ""

    def __post_init__(self) -> None:
        _validate_root("generation_root", self.generation_root)
        _validate_root("manifest_root", self.manifest_root)
        _validate_root(
            "previous_receipt_root", self.previous_receipt_root, allow_empty=True
        )
        if not isinstance(self.state, CSVGenerationState):
            raise CSVGenerationContractError(
                "state must be a CSVGenerationState instance"
            )

    def canonical_dict(self) -> dict[str, str | int]:
        return {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            "generation_root": self.generation_root,
            "manifest_root": self.manifest_root,
            "state": self.state.value,
            "previous_receipt_root": self.previous_receipt_root,
        }

    @property
    def receipt_root(self) -> str:
        return _canonical_root("receipt", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CSVGenerationAuthorityBoundary:
    """Machine-checkable declaration that the generation plane is mechanical."""

    original_bytes_authoritative: bool = True
    decoded_text_is_derived: bool = True
    immutable_after_seal: bool = True
    may_rank_traces: bool = False
    may_train_models: bool = False
    may_activate_models: bool = False
    may_commit_semantics: bool = False
    may_change_policy: bool = False
    may_accept_learned_writes: bool = False
    browser_or_studio_may_publish: bool = False

    def __post_init__(self) -> None:
        expected = {
            "original_bytes_authoritative": True,
            "decoded_text_is_derived": True,
            "immutable_after_seal": True,
            "may_rank_traces": False,
            "may_train_models": False,
            "may_activate_models": False,
            "may_commit_semantics": False,
            "may_change_policy": False,
            "may_accept_learned_writes": False,
            "browser_or_studio_may_publish": False,
        }
        if asdict(self) != expected:
            raise CSVGenerationContractError(
                "CSV generation authority cannot be widened by configuration",
                fault=CSVGenerationFault.AUTHORITY_REJECTED,
            )

    @property
    def authority_root(self) -> str:
        return _canonical_root(
            "authority",
            {
                "contract_id": CSV_GENERATION_CONTRACT_ID,
                "format_version": CSV_GENERATION_FORMAT_VERSION,
                **asdict(self),
            },
        )


CSV_GENERATION_AUTHORITY = CSVGenerationAuthorityBoundary()
CSV_GENERATION_QUALIFICATION_LIMITS = CSVGenerationLimits.qualification_profile()

_ALLOWED_TRANSITIONS = {
    CSVGenerationState.STAGING: CSVGenerationState.SEALED,
    CSVGenerationState.SEALED: CSVGenerationState.VERIFIED,
    CSVGenerationState.VERIFIED: CSVGenerationState.PUBLISHED,
    CSVGenerationState.PUBLISHED: CSVGenerationState.RETIRED,
}


def validate_manifest(
    manifest: CSVGenerationManifest,
    limits: CSVGenerationLimits = CSV_GENERATION_QUALIFICATION_LIMITS,
) -> None:
    """Validate one complete manifest against its exact qualified limits."""

    if not isinstance(manifest, CSVGenerationManifest):
        raise CSVGenerationContractError(
            "manifest must be a CSVGenerationManifest instance"
        )
    if not isinstance(limits, CSVGenerationLimits):
        raise CSVGenerationContractError("limits must be CSVGenerationLimits")
    if manifest.identity.limits_root != limits.limits_root:
        raise CSVGenerationContractError(
            "manifest limits identity does not match the admitted profile",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    values = {
        "source_bytes": (manifest.source_bytes, limits.max_source_bytes),
        "chunk_count": (len(manifest.chunks), limits.max_chunks),
        "row_count": (manifest.row_count, limits.max_rows),
        "closure_node_count": (
            manifest.closure_node_count,
            limits.max_closure_nodes,
        ),
        "closure_edge_count": (
            manifest.closure_edge_count,
            limits.max_closure_edges,
        ),
    }
    for name, (value, ceiling) in values.items():
        if value > ceiling:
            raise CSVGenerationContractError(
                f"{name} exceeds the admitted generation profile",
                fault=CSVGenerationFault.BOUND_EXCEEDED,
            )
    for chunk in manifest.chunks:
        if chunk.end_offset - chunk.start_offset > limits.max_chunk_bytes:
            raise CSVGenerationContractError(
                "source chunk exceeds the admitted chunk-size limit",
                fault=CSVGenerationFault.BOUND_EXCEEDED,
            )


def validate_receipt_transition(
    previous: CSVGenerationReceipt,
    candidate: CSVGenerationReceipt,
) -> None:
    """Require one exact adjacent append-only controller transition."""

    if previous.generation_root != candidate.generation_root:
        raise CSVGenerationContractError(
            "receipt transition mixes generation roots",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    if previous.manifest_root != candidate.manifest_root:
        raise CSVGenerationContractError(
            "receipt transition mixes manifest roots",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    if candidate.previous_receipt_root != previous.receipt_root:
        raise CSVGenerationContractError(
            "receipt transition does not bind the previous receipt",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    expected = _ALLOWED_TRANSITIONS.get(previous.state)
    if candidate.state is not expected:
        raise CSVGenerationContractError(
            f"invalid generation transition {previous.state.value}->{candidate.state.value}",
            fault=CSVGenerationFault.NONCANONICAL,
        )


def validate_atomic_publication(
    *,
    observed_current_manifest_root: str,
    expected_current_manifest_root: str,
    candidate: CSVGenerationReceipt,
) -> None:
    """Validate a deterministic compare-and-swap publication decision."""

    _validate_root("observed_current_manifest_root", observed_current_manifest_root)
    _validate_root("expected_current_manifest_root", expected_current_manifest_root)
    if observed_current_manifest_root != expected_current_manifest_root:
        raise CSVGenerationContractError(
            "current generation changed before publication",
            fault=CSVGenerationFault.PUBLICATION_CONFLICT,
        )
    if candidate.state is not CSVGenerationState.PUBLISHED:
        raise CSVGenerationContractError(
            "only a verified published receipt may replace CURRENT",
            fault=CSVGenerationFault.INCOMPLETE_GENERATION,
        )


def validate_pinned_generation(
    expected_generation_root: str,
    component_roots: Mapping[str, str],
) -> None:
    """Reject mixed source/offset/anchor/closure inputs before any ranking work."""

    _validate_root("expected_generation_root", expected_generation_root)
    if not isinstance(component_roots, Mapping) or not component_roots:
        raise CSVGenerationContractError(
            "at least one generation-bound component is required"
        )
    for name, value in component_roots.items():
        _validate_identity("component name", str(name))
        _validate_root(str(name), value)
        if value != expected_generation_root:
            raise CSVGenerationContractError(
                f"component {name!r} belongs to a different generation",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )

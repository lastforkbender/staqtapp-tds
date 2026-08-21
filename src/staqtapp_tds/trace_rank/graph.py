"""Canonical Phase-4 packed waypoint and CSR graph format.

This module is a data-truth boundary.  It serializes immutable source-bound
waypoints, provenance, fixed-point features, and legal graph edges.  It does
not search the graph, execute a plan, infer a learned score, or write storage.

Binary contract ``tds-packed-waypoint-csr-v1``
------------------------------------------------

* byte order: little endian (format identity 1)
* format version: 1; Trace Rank ABI version: 2
* hash: SHA-256 (identity 1)
* checksum: CRC32/IEEE (identity 1)
* feature quantization: signed Q15 fixed point (identity 1)
* learned edge delta: bounded non-negative uint32
* header: 256 bytes
* sections: generation, provenance, feature, waypoint, CSR offsets, edge

The SHA-256 and CRC32 values cover the canonical header with both integrity
fields zeroed followed by every section byte.  Consequently counts, offsets,
identities, records, and hard eligibility masks are all integrity-bound.
"""
from __future__ import annotations

import hashlib
import re
import struct
import zlib
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

PACKED_GRAPH_FORMAT_ID = "tds-packed-waypoint-csr-v1"
PACKED_GRAPH_FORMAT_VERSION = 1
PACKED_GRAPH_ABI_VERSION = 2
PACKED_GRAPH_ENDIANNESS = "little"
PACKED_GRAPH_ENDIANNESS_ID = 1
PACKED_GRAPH_HASH_ALGORITHM = "sha256"
PACKED_GRAPH_HASH_ALGORITHM_ID = 1
PACKED_GRAPH_CHECKSUM_ALGORITHM = "crc32-ieee-v1"
PACKED_GRAPH_CHECKSUM_ALGORITHM_ID = 1
PACKED_GRAPH_QUANTIZATION = "q15-fixed-point-v1"
PACKED_GRAPH_QUANTIZATION_ID = 1
PACKED_GRAPH_MAGIC = b"TDSWGPH4"

MAX_FEATURE_VALUES = 64
_UINT8_MAX = (1 << 8) - 1
_UINT16_MAX = (1 << 16) - 1
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1
_INT16_MIN = -(1 << 15)
_INT16_MAX = (1 << 15) - 1
_INT32_MAX = (1 << 31) - 1
_ROOT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# The padding bytes in every record are emitted as zero and checked explicitly
# during decode.  Record widths are part of the persisted ABI.
_HEADER = struct.Struct(
    "<8sHHBBBBHHHHHHHHIQQIIIIIQQQQQQ32s32s32sI36x"
)
_GENERATION = struct.Struct("<32s32s32sQQ")
_PROVENANCE = struct.Struct("<32sIHHQ")
_FEATURE = struct.Struct("<HBBIQ64h")
_WAYPOINT = struct.Struct("<IQiIQQQQII4x")
_CSR_OFFSET = struct.Struct("<Q")
_EDGE = struct.Struct("<IHHQIIQI4x")

HEADER_SIZE = _HEADER.size
GENERATION_RECORD_SIZE = _GENERATION.size
PROVENANCE_RECORD_SIZE = _PROVENANCE.size
FEATURE_RECORD_SIZE = _FEATURE.size
WAYPOINT_RECORD_SIZE = _WAYPOINT.size
CSR_OFFSET_RECORD_SIZE = _CSR_OFFSET.size
EDGE_RECORD_SIZE = _EDGE.size

if HEADER_SIZE != 256:  # pragma: no cover - import-time ABI assertion
    raise RuntimeError("packed graph header ABI is not 256 bytes")


class PackedGraphFault(str, Enum):
    """Stable failure classes for persisted graph admission."""

    INVALID_INPUT = "invalid_input"
    BOUND_EXCEEDED = "bound_exceeded"
    NONCANONICAL = "noncanonical"
    UNSUPPORTED_FORMAT = "unsupported_format"
    INTEGRITY_FAILURE = "integrity_failure"
    REFERENCE_ERROR = "reference_error"
    SOURCE_MISMATCH = "source_mismatch"


class PackedGraphError(ValueError):
    """A deterministic packed-graph validation failure."""

    def __init__(
        self,
        message: str,
        *,
        fault: PackedGraphFault = PackedGraphFault.INVALID_INPUT,
    ) -> None:
        super().__init__(message)
        self.fault = fault


def _require_int(name: str, value: int, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise PackedGraphError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise PackedGraphError(
            f"{name} must be between {minimum} and {maximum}",
            fault=PackedGraphFault.BOUND_EXCEEDED,
        )
    return value


def _root_digest(name: str, value: str) -> bytes:
    if type(value) is not str or not _ROOT_RE.fullmatch(value):
        raise PackedGraphError(
            f"{name} must be a canonical sha256 root",
            fault=PackedGraphFault.SOURCE_MISMATCH,
        )
    return bytes.fromhex(value[7:])


def _digest_root(value: bytes) -> str:
    return "sha256:" + value.hex()


def _bytes_root(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _checked_mul(name: str, left: int, right: int) -> int:
    if left and right > _UINT64_MAX // left:
        raise PackedGraphError(
            f"{name} overflows uint64",
            fault=PackedGraphFault.BOUND_EXCEEDED,
        )
    return left * right


def _checked_add(name: str, left: int, right: int) -> int:
    if right > _UINT64_MAX - left:
        raise PackedGraphError(
            f"{name} overflows uint64",
            fault=PackedGraphFault.BOUND_EXCEEDED,
        )
    return left + right


@dataclass(frozen=True, slots=True)
class PackedGraphLimits:
    """Limits that may narrow, but never widen, the Phase-4 envelope."""

    max_generations: int = 4_096
    max_provenance_records: int = 1 << 20
    max_feature_blocks: int = 1 << 20
    max_waypoints: int = 1 << 20
    max_edges: int = 1 << 22
    max_graph_bytes: int = 1 << 31

    def __post_init__(self) -> None:
        hard = {
            "max_generations": (1, 4_096),
            "max_provenance_records": (1, 1 << 20),
            "max_feature_blocks": (1, 1 << 20),
            "max_waypoints": (1, 1 << 20),
            "max_edges": (0, 1 << 22),
            "max_graph_bytes": (HEADER_SIZE, 1 << 31),
        }
        for name, (minimum, maximum) in hard.items():
            _require_int(name, getattr(self, name), minimum, maximum)


DEFAULT_PACKED_GRAPH_LIMITS = PackedGraphLimits()


class _ImmutableSourceRootCacheSlots:
    """Derived roots kept outside dataclass fields and canonical shape."""

    __slots__ = ("_source_root_cache", "_row_offsets_root_cache")


@dataclass(frozen=True, slots=True)
class ImmutableSourceBinding(_ImmutableSourceRootCacheSlots):
    """Authoritative bytes and row boundaries for one immutable generation.

    ``row_offsets`` is a canonical half-open boundary vector: it begins at
    zero, is non-decreasing (empty rows are legal), and ends at the exact byte
    length.  A row span ``[a, b)`` therefore maps to the byte span
    ``[row_offsets[a], row_offsets[b])`` without decoding the source.
    """

    generation_root: str
    source_bytes: bytes
    row_offsets: tuple[int, ...]

    def __post_init__(self) -> None:
        _root_digest("generation_root", self.generation_root)
        if type(self.source_bytes) is not bytes:
            raise PackedGraphError("source_bytes must be exact immutable bytes")
        if not isinstance(self.row_offsets, tuple) or not self.row_offsets:
            raise PackedGraphError("row_offsets must be a non-empty tuple")
        if len(self.row_offsets) > _UINT32_MAX + 1:
            raise PackedGraphError(
                "row offset count exceeds the packed format",
                fault=PackedGraphFault.BOUND_EXCEEDED,
            )
        previous = -1
        for index, offset in enumerate(self.row_offsets):
            _require_int(f"row_offsets[{index}]", offset, 0, _UINT64_MAX)
            if offset < previous:
                raise PackedGraphError(
                    "row_offsets must be non-decreasing",
                    fault=PackedGraphFault.NONCANONICAL,
                )
            previous = offset
        if self.row_offsets[0] != 0:
            raise PackedGraphError("row_offsets must begin at zero")
        if self.row_offsets[-1] != len(self.source_bytes):
            raise PackedGraphError(
                "row_offsets must end at the authoritative source length",
                fault=PackedGraphFault.SOURCE_MISMATCH,
            )
        self._set_derived_roots()

    def _set_derived_roots(self) -> None:
        object.__setattr__(
            self,
            "_source_root_cache",
            _bytes_root(self.source_bytes),
        )
        object.__setattr__(
            self,
            "_row_offsets_root_cache",
            _bytes_root(self.packed_row_offsets()),
        )

    def _ensure_derived_roots(self) -> None:
        """Restore derived slots omitted by copy/pickle protocols."""

        try:
            object.__getattribute__(self, "_source_root_cache")
            object.__getattribute__(self, "_row_offsets_root_cache")
        except AttributeError:
            self._set_derived_roots()

    @property
    def source_root(self) -> str:
        self._ensure_derived_roots()
        return self._source_root_cache

    @property
    def row_count(self) -> int:
        return len(self.row_offsets) - 1

    def packed_row_offsets(self) -> bytes:
        packed = bytearray(len(self.row_offsets) * CSR_OFFSET_RECORD_SIZE)
        for index, value in enumerate(self.row_offsets):
            _CSR_OFFSET.pack_into(packed, index * CSR_OFFSET_RECORD_SIZE, value)
        return bytes(packed)

    @property
    def row_offsets_root(self) -> str:
        self._ensure_derived_roots()
        return self._row_offsets_root_cache

    def materialize_rows(self, row_start: int, row_end: int) -> bytes:
        _require_int("row_start", row_start, 0, self.row_count)
        _require_int("row_end", row_end, 0, self.row_count)
        if row_start >= row_end:
            raise PackedGraphError("row range must be non-empty and half-open")
        return self.source_bytes[
            self.row_offsets[row_start] : self.row_offsets[row_end]
        ]


@dataclass(frozen=True, slots=True)
class GenerationBinding:
    """Fixed-width binding from graph identity to exact source bytes/rows."""

    generation_root: str
    source_root: str
    row_offsets_root: str
    source_size: int
    row_count: int

    def __post_init__(self) -> None:
        _root_digest("generation_root", self.generation_root)
        _root_digest("source_root", self.source_root)
        _root_digest("row_offsets_root", self.row_offsets_root)
        _require_int("source_size", self.source_size, 0, _UINT64_MAX)
        _require_int("row_count", self.row_count, 0, _UINT64_MAX)

    @classmethod
    def from_source(cls, source: ImmutableSourceBinding) -> GenerationBinding:
        return cls(
            generation_root=source.generation_root,
            source_root=source.source_root,
            row_offsets_root=source.row_offsets_root,
            source_size=len(source.source_bytes),
            row_count=source.row_count,
        )

    def _pack(self) -> bytes:
        return _GENERATION.pack(
            _root_digest("generation_root", self.generation_root),
            _root_digest("source_root", self.source_root),
            _root_digest("row_offsets_root", self.row_offsets_root),
            self.source_size,
            self.row_count,
        )

    @classmethod
    def _unpack(cls, raw: bytes) -> GenerationBinding:
        generation, source, offsets, source_size, row_count = _GENERATION.unpack(raw)
        return cls(
            _digest_root(generation),
            _digest_root(source),
            _digest_root(offsets),
            source_size,
            row_count,
        )


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Fixed-width immutable provenance and hard-policy binding."""

    provenance_root: str
    generation_index: int
    privacy_class: int = 0
    license_class: int = 0
    policy_mask: int = 0

    def __post_init__(self) -> None:
        _root_digest("provenance_root", self.provenance_root)
        _require_int("generation_index", self.generation_index, 0, _UINT32_MAX)
        _require_int("privacy_class", self.privacy_class, 0, _UINT16_MAX)
        _require_int("license_class", self.license_class, 0, _UINT16_MAX)
        _require_int("policy_mask", self.policy_mask, 0, _UINT64_MAX)

    def _pack(self) -> bytes:
        return _PROVENANCE.pack(
            _root_digest("provenance_root", self.provenance_root),
            self.generation_index,
            self.privacy_class,
            self.license_class,
            self.policy_mask,
        )

    @classmethod
    def _unpack(cls, raw: bytes) -> ProvenanceRecord:
        root, generation, privacy, license_class, policy = _PROVENANCE.unpack(raw)
        return cls(_digest_root(root), generation, privacy, license_class, policy)

    def _canonical_key(self) -> tuple[int, bytes, int, int, int]:
        return (
            self.generation_index,
            _root_digest("provenance_root", self.provenance_root),
            self.privacy_class,
            self.license_class,
            self.policy_mask,
        )


@dataclass(frozen=True, slots=True)
class FeatureBlock:
    """One fixed-width, privacy-classified Q15 feature vector."""

    values: tuple[int, ...]
    missing_mask: int = 0
    privacy_class: int = 0
    quantization_id: int = PACKED_GRAPH_QUANTIZATION_ID
    flags: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            raise PackedGraphError("feature values must be a tuple")
        if not 1 <= len(self.values) <= MAX_FEATURE_VALUES:
            raise PackedGraphError(
                f"feature count must be between 1 and {MAX_FEATURE_VALUES}",
                fault=PackedGraphFault.BOUND_EXCEEDED,
            )
        _require_int("missing_mask", self.missing_mask, 0, _UINT64_MAX)
        _require_int("privacy_class", self.privacy_class, 0, _UINT8_MAX)
        if self.quantization_id != PACKED_GRAPH_QUANTIZATION_ID:
            raise PackedGraphError(
                "unsupported feature quantization",
                fault=PackedGraphFault.UNSUPPORTED_FORMAT,
            )
        if self.flags != 0:
            raise PackedGraphError(
                "feature flags must be zero in format v1",
                fault=PackedGraphFault.UNSUPPORTED_FORMAT,
            )
        if self.missing_mask >> len(self.values):
            raise PackedGraphError("missing_mask contains out-of-range feature bits")
        for index, value in enumerate(self.values):
            _require_int(f"feature[{index}]", value, _INT16_MIN, _INT16_MAX)
            if self.missing_mask & (1 << index) and value != 0:
                raise PackedGraphError(
                    "missing feature values must use canonical zero storage",
                    fault=PackedGraphFault.NONCANONICAL,
                )

    def _pack(self) -> bytes:
        values = self.values + (0,) * (MAX_FEATURE_VALUES - len(self.values))
        return _FEATURE.pack(
            len(self.values),
            self.quantization_id,
            self.privacy_class,
            self.flags,
            self.missing_mask,
            *values,
        )

    @classmethod
    def _unpack(cls, raw: bytes) -> FeatureBlock:
        unpacked = _FEATURE.unpack(raw)
        count, quantization, privacy, flags, missing = unpacked[:5]
        values = unpacked[5:]
        if count < 1 or count > MAX_FEATURE_VALUES:
            raise PackedGraphError(
                "packed feature count is invalid",
                fault=PackedGraphFault.INTEGRITY_FAILURE,
            )
        if any(values[count:]):
            raise PackedGraphError(
                "packed feature padding is non-zero",
                fault=PackedGraphFault.NONCANONICAL,
            )
        return cls(tuple(values[:count]), missing, privacy, quantization, flags)


@dataclass(frozen=True, slots=True)
class Waypoint:
    """Fixed-width exact source and provenance locator."""

    generation_index: int
    causal_sequence: int
    predecessor_index: int
    byte_start: int
    byte_end: int
    row_start: int
    row_end: int
    feature_index: int
    provenance_index: int
    flags: int = 0

    def __post_init__(self) -> None:
        _require_int("generation_index", self.generation_index, 0, _UINT32_MAX)
        _require_int("causal_sequence", self.causal_sequence, 0, _UINT64_MAX)
        _require_int("predecessor_index", self.predecessor_index, -1, _INT32_MAX)
        _require_int("byte_start", self.byte_start, 0, _UINT64_MAX)
        _require_int("byte_end", self.byte_end, 0, _UINT64_MAX)
        _require_int("row_start", self.row_start, 0, _UINT64_MAX)
        _require_int("row_end", self.row_end, 0, _UINT64_MAX)
        _require_int("feature_index", self.feature_index, 0, _UINT32_MAX)
        _require_int("provenance_index", self.provenance_index, 0, _UINT32_MAX)
        if self.flags != 0:
            raise PackedGraphError(
                "waypoint flags must be zero in format v1",
                fault=PackedGraphFault.UNSUPPORTED_FORMAT,
            )
        if self.byte_start >= self.byte_end:
            raise PackedGraphError("waypoint byte span must be non-empty")
        if self.row_start >= self.row_end:
            raise PackedGraphError("waypoint row span must be non-empty")

    def _pack(self) -> bytes:
        return _WAYPOINT.pack(
            self.generation_index,
            self.causal_sequence,
            self.predecessor_index,
            self.flags,
            self.byte_start,
            self.byte_end,
            self.row_start,
            self.row_end,
            self.feature_index,
            self.provenance_index,
        )

    @classmethod
    def _unpack(cls, raw: bytes) -> Waypoint:
        if raw[-4:] != bytes(4):
            raise PackedGraphError(
                "waypoint padding is non-zero",
                fault=PackedGraphFault.NONCANONICAL,
            )
        generation, causal, predecessor, flags, b0, b1, r0, r1, feature, provenance = _WAYPOINT.unpack(raw)
        return cls(
            generation,
            causal,
            predecessor,
            b0,
            b1,
            r0,
            r1,
            feature,
            provenance,
            flags,
        )

    def _canonical_key(self) -> tuple[int, ...]:
        return (
            self.causal_sequence,
            self.generation_index,
            self.byte_start,
            self.byte_end,
            self.row_start,
            self.row_end,
            self.provenance_index,
            self.feature_index,
            self.predecessor_index,
        )


@dataclass(frozen=True, slots=True)
class Edge:
    """Fixed-width legal edge with a bounded non-negative advisory delta."""

    destination_index: int
    operation: int
    base_cost: int
    learned_delta: int
    evidence_gain: int
    hard_eligibility_mask: int
    flags: int = 0

    def __post_init__(self) -> None:
        _require_int("destination_index", self.destination_index, 0, _UINT32_MAX)
        _require_int("operation", self.operation, 1, _UINT16_MAX)
        _require_int("base_cost", self.base_cost, 0, _UINT64_MAX)
        _require_int("learned_delta", self.learned_delta, 0, _UINT32_MAX)
        _require_int("evidence_gain", self.evidence_gain, 0, _UINT32_MAX)
        _require_int(
            "hard_eligibility_mask", self.hard_eligibility_mask, 0, _UINT64_MAX
        )
        if self.flags != 0:
            raise PackedGraphError(
                "edge flags must be zero in format v1",
                fault=PackedGraphFault.UNSUPPORTED_FORMAT,
            )

    def _pack(self) -> bytes:
        return _EDGE.pack(
            self.destination_index,
            self.operation,
            self.flags,
            self.base_cost,
            self.learned_delta,
            self.evidence_gain,
            self.hard_eligibility_mask,
            0,
        )

    @classmethod
    def _unpack(cls, raw: bytes) -> Edge:
        if raw[-4:] != bytes(4):
            raise PackedGraphError(
                "edge padding is non-zero",
                fault=PackedGraphFault.NONCANONICAL,
            )
        destination, operation, flags, base, delta, gain, hard_mask, reserved = _EDGE.unpack(raw)
        if reserved != 0:
            raise PackedGraphError(
                "edge reserved field is non-zero",
                fault=PackedGraphFault.NONCANONICAL,
            )
        return cls(destination, operation, base, delta, gain, hard_mask, flags)

    def _canonical_key(self) -> tuple[int, ...]:
        return (
            self.destination_index,
            self.operation,
            self.base_cost,
            self.learned_delta,
            self.evidence_gain,
            self.hard_eligibility_mask,
        )


def _layout(
    generation_count: int,
    provenance_count: int,
    feature_count: int,
    waypoint_count: int,
    edge_count: int,
    limits: PackedGraphLimits,
) -> tuple[tuple[int, int, int, int, int, int], int]:
    counts = (
        ("generation", generation_count, limits.max_generations),
        ("provenance", provenance_count, limits.max_provenance_records),
        ("feature", feature_count, limits.max_feature_blocks),
        ("waypoint", waypoint_count, limits.max_waypoints),
        ("edge", edge_count, limits.max_edges),
    )
    for name, count, maximum in counts:
        _require_int(f"{name}_count", count, 0, maximum)

    offset_count = _checked_add("CSR offset count", waypoint_count, 1)
    sizes = (
        _checked_mul("generation section", generation_count, GENERATION_RECORD_SIZE),
        _checked_mul("provenance section", provenance_count, PROVENANCE_RECORD_SIZE),
        _checked_mul("feature section", feature_count, FEATURE_RECORD_SIZE),
        _checked_mul("waypoint section", waypoint_count, WAYPOINT_RECORD_SIZE),
        _checked_mul("CSR offset section", offset_count, CSR_OFFSET_RECORD_SIZE),
        _checked_mul("edge section", edge_count, EDGE_RECORD_SIZE),
    )
    offsets: list[int] = []
    cursor = HEADER_SIZE
    for index, size in enumerate(sizes):
        offsets.append(cursor)
        cursor = _checked_add(f"section {index} end", cursor, size)
        if cursor > limits.max_graph_bytes:
            raise PackedGraphError(
                "packed graph exceeds the qualified memory bound",
                fault=PackedGraphFault.BOUND_EXCEEDED,
            )
    return tuple(offsets), cursor  # type: ignore[return-value]


def _pack_header(
    *,
    total_size: int,
    hard_mask_universe: int,
    counts: tuple[int, int, int, int, int],
    offsets: tuple[int, int, int, int, int, int],
    server_namespace_digest: bytes,
    feature_schema_digest: bytes,
    content_digest: bytes = bytes(32),
    content_crc32: int = 0,
) -> bytes:
    return _HEADER.pack(
        PACKED_GRAPH_MAGIC,
        PACKED_GRAPH_FORMAT_VERSION,
        PACKED_GRAPH_ABI_VERSION,
        PACKED_GRAPH_ENDIANNESS_ID,
        PACKED_GRAPH_HASH_ALGORITHM_ID,
        PACKED_GRAPH_CHECKSUM_ALGORITHM_ID,
        PACKED_GRAPH_QUANTIZATION_ID,
        HEADER_SIZE,
        GENERATION_RECORD_SIZE,
        PROVENANCE_RECORD_SIZE,
        FEATURE_RECORD_SIZE,
        WAYPOINT_RECORD_SIZE,
        CSR_OFFSET_RECORD_SIZE,
        EDGE_RECORD_SIZE,
        0,
        0,
        total_size,
        hard_mask_universe,
        *counts,
        *offsets,
        server_namespace_digest,
        feature_schema_digest,
        content_digest,
        content_crc32,
    )


@dataclass(frozen=True, slots=True)
class PackedWaypointGraph:
    """An immutable, source-bound packed graph with CSR adjacency."""

    server_namespace_root: str
    feature_schema_root: str
    hard_mask_universe: int
    generations: tuple[GenerationBinding, ...]
    provenance: tuple[ProvenanceRecord, ...]
    feature_blocks: tuple[FeatureBlock, ...]
    waypoints: tuple[Waypoint, ...]
    edge_offsets: tuple[int, ...]
    edges: tuple[Edge, ...]

    def __post_init__(self) -> None:
        self._validate_structure(DEFAULT_PACKED_GRAPH_LIMITS)

    @classmethod
    def build(
        cls,
        *,
        server_namespace_root: str,
        feature_schema_root: str,
        hard_mask_universe: int,
        source_bindings: tuple[ImmutableSourceBinding, ...],
        provenance: tuple[ProvenanceRecord, ...],
        feature_blocks: tuple[FeatureBlock, ...],
        waypoints: tuple[Waypoint, ...],
        edge_offsets: tuple[int, ...],
        edges: tuple[Edge, ...],
        limits: PackedGraphLimits = DEFAULT_PACKED_GRAPH_LIMITS,
    ) -> PackedWaypointGraph:
        if cls is not PackedWaypointGraph:
            raise PackedGraphError(
                "packed graph factories must be called on PackedWaypointGraph"
            )
        if type(limits) is not PackedGraphLimits:
            raise PackedGraphError("limits must be an exact PackedGraphLimits")
        sources = _validate_source_order(source_bindings)
        graph = PackedWaypointGraph(
            server_namespace_root=server_namespace_root,
            feature_schema_root=feature_schema_root,
            hard_mask_universe=hard_mask_universe,
            generations=tuple(GenerationBinding.from_source(item) for item in sources),
            provenance=provenance,
            feature_blocks=feature_blocks,
            waypoints=waypoints,
            edge_offsets=edge_offsets,
            edges=edges,
        )
        # The exact base constructor validates the default hard envelope. An
        # identity check (never overloadable equality) selects the additional
        # narrower-limit pass.
        if limits is not DEFAULT_PACKED_GRAPH_LIMITS:
            PackedWaypointGraph._validate_structure(graph, limits)
        graph._validate_sources(sources)
        return graph

    def _validate_structure(self, limits: PackedGraphLimits) -> None:
        if type(limits) is not PackedGraphLimits:
            raise PackedGraphError("limits must be an exact PackedGraphLimits")
        _root_digest("server_namespace_root", self.server_namespace_root)
        _root_digest("feature_schema_root", self.feature_schema_root)
        _require_int("hard_mask_universe", self.hard_mask_universe, 1, _UINT64_MAX)
        collections = (
            ("generations", self.generations, GenerationBinding),
            ("provenance", self.provenance, ProvenanceRecord),
            ("feature_blocks", self.feature_blocks, FeatureBlock),
            ("waypoints", self.waypoints, Waypoint),
            ("edge_offsets", self.edge_offsets, int),
            ("edges", self.edges, Edge),
        )
        for name, value, item_type in collections:
            if not isinstance(value, tuple):
                raise PackedGraphError(f"{name} must be an immutable tuple")
            if item_type is not int and any(not isinstance(item, item_type) for item in value):
                raise PackedGraphError(f"{name} contains an invalid record")
        if not self.generations or not self.provenance or not self.feature_blocks or not self.waypoints:
            raise PackedGraphError(
                "a packed graph requires generation, provenance, feature, and waypoint records"
            )
        _layout(
            len(self.generations),
            len(self.provenance),
            len(self.feature_blocks),
            len(self.waypoints),
            len(self.edges),
            limits,
        )

        generation_keys = tuple(item.generation_root for item in self.generations)
        if any(right < left for left, right in pairwise(generation_keys)):
            raise PackedGraphError(
                "generation table is not in canonical root order",
                fault=PackedGraphFault.NONCANONICAL,
            )
        if any(right == left for left, right in pairwise(generation_keys)):
            raise PackedGraphError("generation table contains duplicate roots")

        provenance_keys = tuple(item._canonical_key() for item in self.provenance)
        if any(right < left for left, right in pairwise(provenance_keys)):
            raise PackedGraphError(
                "provenance table is not in canonical order",
                fault=PackedGraphFault.NONCANONICAL,
            )
        provenance_roots = tuple(item.provenance_root for item in self.provenance)
        if len(set(provenance_roots)) != len(provenance_roots):
            raise PackedGraphError("provenance roots must be unique")
        for record in self.provenance:
            if record.generation_index >= len(self.generations):
                raise PackedGraphError(
                    "provenance generation reference is out of range",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            if record.policy_mask & ~self.hard_mask_universe:
                raise PackedGraphError(
                    "provenance policy mask exceeds the immutable universe",
                    fault=PackedGraphFault.INTEGRITY_FAILURE,
                )

        feature_keys = tuple(item._pack() for item in self.feature_blocks)
        if any(right < left for left, right in pairwise(feature_keys)):
            raise PackedGraphError(
                "feature table is not in canonical order",
                fault=PackedGraphFault.NONCANONICAL,
            )
        if any(right == left for left, right in pairwise(feature_keys)):
            raise PackedGraphError("feature table contains duplicate blocks")

        waypoint_keys = tuple(item._canonical_key() for item in self.waypoints)
        if any(right < left for left, right in pairwise(waypoint_keys)):
            raise PackedGraphError(
                "waypoint table is not in canonical causal order",
                fault=PackedGraphFault.NONCANONICAL,
            )
        causal = tuple(item.causal_sequence for item in self.waypoints)
        if any(right <= left for left, right in pairwise(causal)):
            raise PackedGraphError("waypoint causal_sequence values must be unique")
        for index, waypoint in enumerate(self.waypoints):
            if waypoint.generation_index >= len(self.generations):
                raise PackedGraphError(
                    "waypoint generation reference is out of range",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            if waypoint.feature_index >= len(self.feature_blocks):
                raise PackedGraphError(
                    "waypoint feature reference is out of range",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            if waypoint.provenance_index >= len(self.provenance):
                raise PackedGraphError(
                    "waypoint provenance reference is out of range",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            provenance = self.provenance[waypoint.provenance_index]
            if provenance.generation_index != waypoint.generation_index:
                raise PackedGraphError(
                    "waypoint provenance is bound to another generation",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            feature = self.feature_blocks[waypoint.feature_index]
            if feature.privacy_class != provenance.privacy_class:
                raise PackedGraphError(
                    "waypoint feature privacy class does not match provenance",
                    fault=PackedGraphFault.INTEGRITY_FAILURE,
                )
            generation = self.generations[waypoint.generation_index]
            if waypoint.byte_end > generation.source_size:
                raise PackedGraphError(
                    "waypoint byte span exceeds its generation",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            if waypoint.row_end > generation.row_count:
                raise PackedGraphError(
                    "waypoint row span exceeds its generation",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            if waypoint.predecessor_index >= index:
                raise PackedGraphError(
                    "waypoint predecessor must precede the waypoint",
                    fault=PackedGraphFault.REFERENCE_ERROR,
                )
            if waypoint.predecessor_index >= 0:
                predecessor = self.waypoints[waypoint.predecessor_index]
                if predecessor.causal_sequence >= waypoint.causal_sequence:
                    raise PackedGraphError(
                        "waypoint predecessor violates causal order",
                        fault=PackedGraphFault.REFERENCE_ERROR,
                    )

        if len(self.edge_offsets) != len(self.waypoints) + 1:
            raise PackedGraphError("CSR offset count must equal waypoint count plus one")
        if not self.edge_offsets or self.edge_offsets[0] != 0:
            raise PackedGraphError("CSR offsets must begin at zero")
        previous = -1
        for index, offset in enumerate(self.edge_offsets):
            _require_int(f"edge_offsets[{index}]", offset, 0, len(self.edges))
            if offset < previous:
                raise PackedGraphError(
                    "CSR offsets must be non-decreasing",
                    fault=PackedGraphFault.NONCANONICAL,
                )
            previous = offset
        if self.edge_offsets[-1] != len(self.edges):
            raise PackedGraphError("final CSR offset must equal edge count")

        for source_index in range(len(self.waypoints)):
            start = self.edge_offsets[source_index]
            end = self.edge_offsets[source_index + 1]
            row = self.edges[start:end]
            keys = tuple(edge._canonical_key() for edge in row)
            if any(right < left for left, right in pairwise(keys)):
                raise PackedGraphError(
                    "CSR edge row is not in canonical order",
                    fault=PackedGraphFault.NONCANONICAL,
                )
            endpoint_operations = tuple(
                (edge.destination_index, edge.operation) for edge in row
            )
            if len(set(endpoint_operations)) != len(endpoint_operations):
                raise PackedGraphError("CSR edge row contains a duplicate operation")
            for edge in row:
                if edge.destination_index >= len(self.waypoints):
                    raise PackedGraphError(
                        "edge destination reference is out of range",
                        fault=PackedGraphFault.REFERENCE_ERROR,
                    )
                if edge.hard_eligibility_mask & ~self.hard_mask_universe:
                    raise PackedGraphError(
                        "edge hard eligibility mask exceeds the immutable universe",
                        fault=PackedGraphFault.INTEGRITY_FAILURE,
                    )
                destination = self.waypoints[edge.destination_index]
                required_mask = self.provenance[
                    destination.provenance_index
                ].policy_mask
                if edge.hard_eligibility_mask & required_mask != required_mask:
                    raise PackedGraphError(
                        "edge hard mask weakens destination provenance policy",
                        fault=PackedGraphFault.INTEGRITY_FAILURE,
                    )

    def _validate_sources(
        self, source_bindings: tuple[ImmutableSourceBinding, ...]
    ) -> tuple[ImmutableSourceBinding, ...]:
        sources = _validate_source_order(source_bindings)
        if len(sources) != len(self.generations):
            raise PackedGraphError(
                "source binding count does not match generation table",
                fault=PackedGraphFault.SOURCE_MISMATCH,
            )
        for index, (record, source) in enumerate(zip(self.generations, sources)):
            if record != GenerationBinding.from_source(source):
                raise PackedGraphError(
                    f"source binding {index} does not match its generation record",
                    fault=PackedGraphFault.SOURCE_MISMATCH,
                )
        for index, waypoint in enumerate(self.waypoints):
            source = sources[waypoint.generation_index]
            expected_start = source.row_offsets[waypoint.row_start]
            expected_end = source.row_offsets[waypoint.row_end]
            if (waypoint.byte_start, waypoint.byte_end) != (
                expected_start,
                expected_end,
            ):
                raise PackedGraphError(
                    f"waypoint {index} byte span does not exactly bind its row span",
                    fault=PackedGraphFault.SOURCE_MISMATCH,
                )
        return sources

    def to_bytes(
        self,
        source_bindings: tuple[ImmutableSourceBinding, ...],
        *,
        limits: PackedGraphLimits = DEFAULT_PACKED_GRAPH_LIMITS,
    ) -> bytes:
        """Serialize after all counts, sizes, references, and sources validate."""

        self._validate_structure(limits)
        self._validate_sources(source_bindings)
        counts = (
            len(self.generations),
            len(self.provenance),
            len(self.feature_blocks),
            len(self.waypoints),
            len(self.edges),
        )
        offsets, total_size = _layout(*counts, limits)

        # Every bound and final size is proven before the one bounded output
        # buffer is allocated. Fixed-width records are copied directly into
        # their admitted sections, without full-size section/body temporaries.
        result = bytearray(total_size)

        def pack_records(records: tuple[object, ...], start: int, width: int) -> None:
            cursor = start
            for record in records:
                raw = record._pack()  # type: ignore[attr-defined]
                if len(raw) != width:  # pragma: no cover - internal ABI invariant
                    raise PackedGraphError("serialized record width invariant failed")
                result[cursor : cursor + width] = raw
                cursor += width

        pack_records(self.generations, offsets[0], GENERATION_RECORD_SIZE)
        pack_records(self.provenance, offsets[1], PROVENANCE_RECORD_SIZE)
        pack_records(self.feature_blocks, offsets[2], FEATURE_RECORD_SIZE)
        pack_records(self.waypoints, offsets[3], WAYPOINT_RECORD_SIZE)
        cursor = offsets[4]
        for item in self.edge_offsets:
            _CSR_OFFSET.pack_into(result, cursor, item)
            cursor += CSR_OFFSET_RECORD_SIZE
        pack_records(self.edges, offsets[5], EDGE_RECORD_SIZE)
        server_digest = _root_digest(
            "server_namespace_root", self.server_namespace_root
        )
        schema_digest = _root_digest("feature_schema_root", self.feature_schema_root)
        zero_header = _pack_header(
            total_size=total_size,
            hard_mask_universe=self.hard_mask_universe,
            counts=counts,
            offsets=offsets,
            server_namespace_digest=server_digest,
            feature_schema_digest=schema_digest,
        )
        result[:HEADER_SIZE] = zero_header
        view = memoryview(result)
        digest = hashlib.sha256(view).digest()
        checksum = zlib.crc32(view) & _UINT32_MAX
        view.release()
        header = _pack_header(
            total_size=total_size,
            hard_mask_universe=self.hard_mask_universe,
            counts=counts,
            offsets=offsets,
            server_namespace_digest=server_digest,
            feature_schema_digest=schema_digest,
            content_digest=digest,
            content_crc32=checksum,
        )
        result[:HEADER_SIZE] = header
        return bytes(result)

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        source_bindings: tuple[ImmutableSourceBinding, ...],
        *,
        limits: PackedGraphLimits = DEFAULT_PACKED_GRAPH_LIMITS,
    ) -> PackedWaypointGraph:
        """Decode and admit only a canonical, exact-source-bound graph."""

        if cls is not PackedWaypointGraph:
            raise PackedGraphError(
                "packed graph factories must be called on PackedWaypointGraph"
            )
        if type(limits) is not PackedGraphLimits:
            raise PackedGraphError("limits must be an exact PackedGraphLimits")
        if type(payload) is not bytes:
            raise PackedGraphError("packed graph payload must be exact immutable bytes")
        if len(payload) < HEADER_SIZE:
            raise PackedGraphError(
                "packed graph header is truncated",
                fault=PackedGraphFault.INTEGRITY_FAILURE,
            )
        values = _HEADER.unpack_from(payload, 0)
        (
            magic,
            format_version,
            abi_version,
            endianness,
            hash_algorithm,
            checksum_algorithm,
            quantization,
            header_size,
            generation_size,
            provenance_size,
            feature_size,
            waypoint_size,
            csr_offset_size,
            edge_size,
            reserved,
            flags,
            total_size,
            hard_mask_universe,
            generation_count,
            provenance_count,
            feature_count,
            waypoint_count,
            edge_count,
            generation_offset,
            provenance_offset,
            feature_offset,
            waypoint_offset,
            csr_offset,
            edge_offset,
            server_digest,
            schema_digest,
            stored_digest,
            stored_crc32,
        ) = values
        if magic != PACKED_GRAPH_MAGIC:
            raise PackedGraphError(
                "packed graph magic is invalid",
                fault=PackedGraphFault.UNSUPPORTED_FORMAT,
            )
        expected_format = (
            format_version == PACKED_GRAPH_FORMAT_VERSION
            and abi_version == PACKED_GRAPH_ABI_VERSION
            and endianness == PACKED_GRAPH_ENDIANNESS_ID
            and hash_algorithm == PACKED_GRAPH_HASH_ALGORITHM_ID
            and checksum_algorithm == PACKED_GRAPH_CHECKSUM_ALGORITHM_ID
            and quantization == PACKED_GRAPH_QUANTIZATION_ID
        )
        if not expected_format:
            raise PackedGraphError(
                "packed graph format identities are unsupported",
                fault=PackedGraphFault.UNSUPPORTED_FORMAT,
            )
        expected_widths = (
            HEADER_SIZE,
            GENERATION_RECORD_SIZE,
            PROVENANCE_RECORD_SIZE,
            FEATURE_RECORD_SIZE,
            WAYPOINT_RECORD_SIZE,
            CSR_OFFSET_RECORD_SIZE,
            EDGE_RECORD_SIZE,
        )
        actual_widths = (
            header_size,
            generation_size,
            provenance_size,
            feature_size,
            waypoint_size,
            csr_offset_size,
            edge_size,
        )
        if actual_widths != expected_widths or reserved != 0 or flags != 0:
            raise PackedGraphError(
                "packed graph record widths or reserved fields are unsupported",
                fault=PackedGraphFault.UNSUPPORTED_FORMAT,
            )

        counts = (
            generation_count,
            provenance_count,
            feature_count,
            waypoint_count,
            edge_count,
        )
        expected_offsets, expected_total = _layout(*counts, limits)
        stored_offsets = (
            generation_offset,
            provenance_offset,
            feature_offset,
            waypoint_offset,
            csr_offset,
            edge_offset,
        )
        if stored_offsets != expected_offsets or total_size != expected_total:
            raise PackedGraphError(
                "packed graph sections are not canonical and contiguous",
                fault=PackedGraphFault.NONCANONICAL,
            )
        if len(payload) != total_size:
            reason = "trailing bytes" if len(payload) > total_size else "truncated body"
            raise PackedGraphError(
                f"packed graph contains {reason}",
                fault=PackedGraphFault.INTEGRITY_FAILURE,
            )

        zero_header = _pack_header(
            total_size=total_size,
            hard_mask_universe=hard_mask_universe,
            counts=counts,
            offsets=expected_offsets,
            server_namespace_digest=server_digest,
            feature_schema_digest=schema_digest,
        )
        body = memoryview(payload)[HEADER_SIZE:]
        hasher = hashlib.sha256()
        hasher.update(zero_header)
        hasher.update(body)
        actual_digest = hasher.digest()
        actual_crc32 = zlib.crc32(zero_header)
        actual_crc32 = zlib.crc32(body, actual_crc32) & _UINT32_MAX
        body.release()
        if stored_digest != actual_digest or stored_crc32 != actual_crc32:
            raise PackedGraphError(
                "packed graph hash or checksum mismatch",
                fault=PackedGraphFault.INTEGRITY_FAILURE,
            )
        canonical_header = _pack_header(
            total_size=total_size,
            hard_mask_universe=hard_mask_universe,
            counts=counts,
            offsets=expected_offsets,
            server_namespace_digest=server_digest,
            feature_schema_digest=schema_digest,
            content_digest=stored_digest,
            content_crc32=stored_crc32,
        )
        if payload[:HEADER_SIZE] != canonical_header:
            raise PackedGraphError(
                "packed graph header is not canonical",
                fault=PackedGraphFault.NONCANONICAL,
            )

        # Counts and all section byte ranges were admitted above.  Only now do
        # we allocate Python record tuples.
        def records(start: int, count: int, record_size: int):
            return (
                payload[start + index * record_size : start + (index + 1) * record_size]
                for index in range(count)
            )

        generations = tuple(
            GenerationBinding._unpack(raw)
            for raw in records(generation_offset, generation_count, GENERATION_RECORD_SIZE)
        )
        provenance = tuple(
            ProvenanceRecord._unpack(raw)
            for raw in records(provenance_offset, provenance_count, PROVENANCE_RECORD_SIZE)
        )
        feature_blocks = tuple(
            FeatureBlock._unpack(raw)
            for raw in records(feature_offset, feature_count, FEATURE_RECORD_SIZE)
        )
        waypoints = tuple(
            Waypoint._unpack(raw)
            for raw in records(waypoint_offset, waypoint_count, WAYPOINT_RECORD_SIZE)
        )
        edge_offsets = tuple(
            _CSR_OFFSET.unpack(raw)[0]
            for raw in records(csr_offset, waypoint_count + 1, CSR_OFFSET_RECORD_SIZE)
        )
        edges = tuple(
            Edge._unpack(raw)
            for raw in records(edge_offset, edge_count, EDGE_RECORD_SIZE)
        )
        graph = PackedWaypointGraph(
            server_namespace_root=_digest_root(server_digest),
            feature_schema_root=_digest_root(schema_digest),
            hard_mask_universe=hard_mask_universe,
            generations=generations,
            provenance=provenance,
            feature_blocks=feature_blocks,
            waypoints=waypoints,
            edge_offsets=edge_offsets,
            edges=edges,
        )
        if limits is not DEFAULT_PACKED_GRAPH_LIMITS:
            PackedWaypointGraph._validate_structure(graph, limits)
        graph._validate_sources(source_bindings)
        return graph

    def materialize_waypoint(
        self,
        waypoint_index: int,
        source_bindings: tuple[ImmutableSourceBinding, ...],
    ) -> bytes:
        """Return the exact authoritative source bytes for one row span."""

        _require_int("waypoint_index", waypoint_index, 0, len(self.waypoints) - 1)
        sources = self._validate_sources(source_bindings)
        return self._materialize_admitted_waypoint(waypoint_index, sources)

    def _materialize_admitted_waypoint(
        self,
        waypoint_index: int,
        source_bindings: tuple[ImmutableSourceBinding, ...],
    ) -> bytes:
        """Materialize from bindings already admitted with this graph."""

        _require_int("waypoint_index", waypoint_index, 0, len(self.waypoints) - 1)
        waypoint = self.waypoints[waypoint_index]
        source = source_bindings[waypoint.generation_index]
        # Whole-graph admission already proved that these exact row boundaries
        # equal the byte span. The proof-bound path performs one immutable slice;
        # the public materializer above still revalidates all supplied sources.
        return source.source_bytes[waypoint.byte_start : waypoint.byte_end]

    @property
    def format_descriptor(self) -> dict[str, int | str]:
        return {
            "format_id": PACKED_GRAPH_FORMAT_ID,
            "format_version": PACKED_GRAPH_FORMAT_VERSION,
            "trace_rank_abi_version": PACKED_GRAPH_ABI_VERSION,
            "endianness": PACKED_GRAPH_ENDIANNESS,
            "endianness_id": PACKED_GRAPH_ENDIANNESS_ID,
            "hash_algorithm": PACKED_GRAPH_HASH_ALGORITHM,
            "hash_algorithm_id": PACKED_GRAPH_HASH_ALGORITHM_ID,
            "checksum_algorithm": PACKED_GRAPH_CHECKSUM_ALGORITHM,
            "checksum_algorithm_id": PACKED_GRAPH_CHECKSUM_ALGORITHM_ID,
            "quantization": PACKED_GRAPH_QUANTIZATION,
            "quantization_id": PACKED_GRAPH_QUANTIZATION_ID,
            "header_size": HEADER_SIZE,
            "generation_record_size": GENERATION_RECORD_SIZE,
            "provenance_record_size": PROVENANCE_RECORD_SIZE,
            "feature_record_size": FEATURE_RECORD_SIZE,
            "waypoint_record_size": WAYPOINT_RECORD_SIZE,
            "csr_offset_record_size": CSR_OFFSET_RECORD_SIZE,
            "edge_record_size": EDGE_RECORD_SIZE,
        }


def _validate_source_order(
    source_bindings: tuple[ImmutableSourceBinding, ...],
) -> tuple[ImmutableSourceBinding, ...]:
    if not isinstance(source_bindings, tuple):
        raise PackedGraphError("source_bindings must be an immutable tuple")
    if any(not isinstance(item, ImmutableSourceBinding) for item in source_bindings):
        raise PackedGraphError("source_bindings contains an invalid record")
    roots = tuple(item.generation_root for item in source_bindings)
    if any(right < left for left, right in pairwise(roots)):
        raise PackedGraphError(
            "source bindings are not in canonical generation-root order",
            fault=PackedGraphFault.NONCANONICAL,
        )
    if any(right == left for left, right in pairwise(roots)):
        raise PackedGraphError("source bindings contain duplicate generation roots")
    return source_bindings


__all__ = [
    "CSR_OFFSET_RECORD_SIZE",
    "DEFAULT_PACKED_GRAPH_LIMITS",
    "EDGE_RECORD_SIZE",
    "FEATURE_RECORD_SIZE",
    "GENERATION_RECORD_SIZE",
    "HEADER_SIZE",
    "MAX_FEATURE_VALUES",
    "PACKED_GRAPH_ABI_VERSION",
    "PACKED_GRAPH_CHECKSUM_ALGORITHM",
    "PACKED_GRAPH_CHECKSUM_ALGORITHM_ID",
    "PACKED_GRAPH_ENDIANNESS",
    "PACKED_GRAPH_ENDIANNESS_ID",
    "PACKED_GRAPH_FORMAT_ID",
    "PACKED_GRAPH_FORMAT_VERSION",
    "PACKED_GRAPH_HASH_ALGORITHM",
    "PACKED_GRAPH_HASH_ALGORITHM_ID",
    "PACKED_GRAPH_MAGIC",
    "PACKED_GRAPH_QUANTIZATION",
    "PACKED_GRAPH_QUANTIZATION_ID",
    "PROVENANCE_RECORD_SIZE",
    "WAYPOINT_RECORD_SIZE",
    "Edge",
    "FeatureBlock",
    "GenerationBinding",
    "ImmutableSourceBinding",
    "PackedGraphError",
    "PackedGraphFault",
    "PackedGraphLimits",
    "PackedWaypointGraph",
    "ProvenanceRecord",
    "Waypoint",
]

"""Deterministic reference implementation of the atomic CSV Generation Plane.

The reference is deliberately mechanical and read-oriented.  It preserves exact
source bytes, maintains CSV row state across real input splits, emits canonical
packed offsets and anchors, roots one finite closure, publishes with an atomic
CURRENT replacement, and gives readers generation-pinned immutable leases.

It does not rank traces, infer semantics, train or activate models, accept
learned writes, or enter the Native Trace Ranking request path.  The later C
init/feed/finalize implementation must be bit-identical to this oracle before it
can replace any reference operation.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence
import zlib

from staqtapp_tds.csv_layer.generation_contract import (
    CSV_GENERATION_CHECKSUM_ALGORITHM,
    CSV_GENERATION_CONTRACT_ID,
    CSV_GENERATION_FORMAT_VERSION,
    CSV_GENERATION_QUALIFICATION_LIMITS,
    CSVChunkDescriptor,
    CSVGenerationContractError,
    CSVGenerationFault,
    CSVGenerationIdentity,
    CSVGenerationLimits,
    CSVGenerationManifest,
    CSVGenerationReceipt,
    CSVGenerationState,
    chunk_sequence_root,
    validate_manifest,
    validate_receipt_transition,
)

_ROOT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_OFFSET_MAGIC = b"TDSROF1\x00"
_ANCHOR_MAGIC = b"TDSRAN1\x00"
_OFFSET_HEADER = struct.Struct("<8sHHIQQ32s")
_ANCHOR_HEADER = struct.Struct("<8sHHIQQ32s")
_ANCHOR_RECORD = struct.Struct("<QQQII32s")
_U64 = struct.Struct("<Q")

CSV_REFERENCE_PARSER_ID = "tds-csv-row-stream-oracle-v1"
CSV_GENERATION_FAULT_POINTS = (
    "after_staged_verify",
    "after_manifest_write",
    "after_verified_receipt",
    "after_published_receipt",
    "before_current_replace",
    "after_current_replace",
)


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
        raise CSVGenerationContractError(
            "generation value is not canonically JSON encodable"
        ) from exc


def _content_root(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _root_hex(root: str) -> str:
    if not isinstance(root, str) or not _ROOT_PATTERN.fullmatch(root):
        raise CSVGenerationContractError(
            "expected exact lowercase sha256:<64-hex> identity",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    return root[7:]


def _root_digest(root: str) -> bytes:
    return bytes.fromhex(_root_hex(root))


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write_exact(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise CSVGenerationContractError(
                f"immutable artifact collision at {path}",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            if path.read_bytes() != data:
                raise CSVGenerationContractError(
                    f"immutable artifact collision at {path}",
                    fault=CSVGenerationFault.IDENTITY_MISMATCH,
                )
            temporary.unlink(missing_ok=True)
            return
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


_REFERENCE_PARSER_CONTRACT = {
    "contract_id": CSV_GENERATION_CONTRACT_ID,
    "format_version": CSV_GENERATION_FORMAT_VERSION,
    "parser_id": CSV_REFERENCE_PARSER_ID,
    "row_endings": ["crlf", "lf", "cr"],
    "stateful_across_feed_boundaries": True,
    "original_bytes_authoritative": True,
    "empty_input_rows": 0,
    "trailing_line_ending_adds_empty_row": False,
}
CSV_REFERENCE_PARSER_ROOT = _content_root(
    _canonical_json_bytes(_REFERENCE_PARSER_CONTRACT)
)


@dataclass(frozen=True, slots=True)
class CSVStreamProfile:
    """Exact byte-level CSV row-boundary profile for the reference parser."""

    delimiter: int = ord(",")
    quote: int = ord('"')
    escape: int | None = None
    doublequote: bool = True

    def __post_init__(self) -> None:
        for name in ("delimiter", "quote"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise CSVGenerationContractError(f"{name} must be an integer byte")
            if value < 0 or value > 255:
                raise CSVGenerationContractError(f"{name} is outside byte range")
        if self.escape is not None:
            if isinstance(self.escape, bool) or not isinstance(self.escape, int):
                raise CSVGenerationContractError("escape must be None or an integer byte")
            if self.escape < 0 or self.escape > 255:
                raise CSVGenerationContractError("escape is outside byte range")
            if self.escape in {self.delimiter, self.quote}:
                raise CSVGenerationContractError(
                    "escape must differ from delimiter and quote"
                )
        if self.delimiter == self.quote:
            raise CSVGenerationContractError("delimiter and quote must differ")
        if not isinstance(self.doublequote, bool):
            raise CSVGenerationContractError("doublequote must be boolean")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            "parser_root": CSV_REFERENCE_PARSER_ROOT,
            "delimiter": self.delimiter,
            "quote": self.quote,
            "escape": self.escape,
            "doublequote": self.doublequote,
        }

    @property
    def dialect_root(self) -> str:
        return _content_root(_canonical_json_bytes(self.canonical_dict()))


@dataclass(frozen=True, slots=True)
class CSVRowAnchorRecord:
    """Exact mechanical source-row evidence."""

    ordinal: int
    start_offset: int
    end_offset: int
    first_chunk: int
    last_chunk: int
    row_sha256: str


@dataclass(frozen=True, slots=True)
class StagedCSVGeneration:
    """One complete deterministic candidate that has not changed CURRENT."""

    manifest: CSVGenerationManifest
    limits: CSVGenerationLimits
    profile: CSVStreamProfile

    @property
    def generation_root(self) -> str:
        return self.manifest.identity.generation_root

    @property
    def manifest_root(self) -> str:
        return self.manifest.manifest_root


@dataclass(frozen=True, slots=True)
class CurrentCSVGeneration:
    """Canonical contents of the atomically replaced CURRENT pointer."""

    generation_root: str
    manifest_root: str
    published_receipt_root: str


@dataclass(frozen=True, slots=True)
class CSVGenerationVerification:
    """Independent verification result for one immutable generation."""

    generation_root: str
    manifest_root: str
    source_sha256: str
    source_bytes: int
    chunk_count: int
    row_count: int
    closure_node_count: int
    closure_edge_count: int


@dataclass(frozen=True, slots=True)
class _RawRowAnchor:
    start_offset: int
    end_offset: int
    digest: bytes


class InjectedGenerationCrash(RuntimeError):
    """Qualification-only simulated process death at a named publication point."""


class _CSVRowStreamOracle:
    """Byte-state oracle that retains quote and line-ending state across feeds."""

    def __init__(self, profile: CSVStreamProfile) -> None:
        self.profile = profile
        self.offset = 0
        self.in_quotes = False
        self.pending_quote = False
        self.pending_escape = False
        self.pending_cr = False
        self.field_start = True
        self.row_open = False
        self.row_start = 0
        self.row_hasher: hashlib._Hash | None = None
        self.row_offsets: list[int] = []
        self.anchors: list[_RawRowAnchor] = []
        self.finished = False

    def _open_row(self) -> None:
        if self.row_open:
            return
        self.row_open = True
        self.row_start = self.offset
        self.row_offsets.append(self.offset)
        self.row_hasher = hashlib.sha256()

    def _hash_byte(self, byte: int) -> None:
        self._open_row()
        assert self.row_hasher is not None
        self.row_hasher.update(bytes((byte,)))
        self.offset += 1

    def _finish_row(self) -> None:
        if not self.row_open or self.row_hasher is None:
            raise CSVGenerationContractError(
                "internal row-state underflow",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        self.anchors.append(
            _RawRowAnchor(
                start_offset=self.row_start,
                end_offset=self.offset,
                digest=self.row_hasher.digest(),
            )
        )
        self.row_open = False
        self.row_hasher = None
        self.field_start = True

    def _outside_after_hash(self, byte: int) -> None:
        if self.field_start and byte == self.profile.quote:
            self.in_quotes = True
            self.field_start = False
            return
        if byte == self.profile.delimiter:
            self.field_start = True
            return
        if byte == 13:
            self.pending_cr = True
            return
        if byte == 10:
            self._finish_row()
            return
        self.field_start = False

    def feed(self, block: bytes) -> None:
        if self.finished:
            raise CSVGenerationContractError("cannot feed a finalized CSV stream")
        if not isinstance(block, bytes):
            raise CSVGenerationContractError("stream oracle requires immutable bytes")

        for byte in block:
            if self.pending_cr:
                if byte == 10:
                    self._hash_byte(byte)
                    self.pending_cr = False
                    self._finish_row()
                    continue
                self.pending_cr = False
                self._finish_row()

            self._hash_byte(byte)

            if self.in_quotes:
                if self.pending_escape:
                    self.pending_escape = False
                    continue
                if self.pending_quote:
                    if self.profile.doublequote and byte == self.profile.quote:
                        self.pending_quote = False
                        continue
                    self.pending_quote = False
                    self.in_quotes = False
                    self.field_start = False
                    self._outside_after_hash(byte)
                    continue
                if self.profile.escape is not None and byte == self.profile.escape:
                    self.pending_escape = True
                    continue
                if byte == self.profile.quote:
                    if self.profile.doublequote:
                        self.pending_quote = True
                    else:
                        self.in_quotes = False
                    continue
                continue

            self._outside_after_hash(byte)

    def finalize(self) -> tuple[tuple[int, ...], tuple[_RawRowAnchor, ...]]:
        if self.finished:
            raise CSVGenerationContractError("CSV stream was already finalized")
        self.finished = True
        if self.pending_escape:
            raise CSVGenerationContractError(
                "CSV stream ended after an escape byte",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            )
        if self.pending_quote:
            self.pending_quote = False
            self.in_quotes = False
        if self.in_quotes:
            raise CSVGenerationContractError(
                "CSV stream ended inside an open quoted field",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            )
        if self.pending_cr:
            self.pending_cr = False
            self._finish_row()
        elif self.row_open:
            self._finish_row()
        return tuple(self.row_offsets), tuple(self.anchors)


def _pack_row_offsets(
    offsets: Sequence[int], *, source_bytes: int, source_sha256: str
) -> bytes:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in offsets
    ):
        raise CSVGenerationContractError("row offsets must be non-negative integers")
    if tuple(sorted(offsets)) != tuple(offsets) or len(set(offsets)) != len(offsets):
        raise CSVGenerationContractError(
            "row offsets must be strictly increasing",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    if offsets and offsets[-1] >= source_bytes:
        raise CSVGenerationContractError(
            "row offset lies outside the authoritative source extent",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    header = _OFFSET_HEADER.pack(
        _OFFSET_MAGIC,
        CSV_GENERATION_FORMAT_VERSION,
        0,
        _U64.size,
        len(offsets),
        source_bytes,
        _root_digest(source_sha256),
    )
    return header + b"".join(_U64.pack(value) for value in offsets)


def decode_row_offsets(data: bytes) -> tuple[int, int, str, tuple[int, ...]]:
    """Validate and decode the canonical packed row-offset artifact."""

    if not isinstance(data, bytes) or len(data) < _OFFSET_HEADER.size:
        raise CSVGenerationContractError("row-offset artifact is truncated")
    magic, major, minor, record_bytes, count, source_bytes, digest = (
        _OFFSET_HEADER.unpack_from(data)
    )
    if (
        magic != _OFFSET_MAGIC
        or major != CSV_GENERATION_FORMAT_VERSION
        or minor != 0
        or record_bytes != _U64.size
    ):
        raise CSVGenerationContractError(
            "row-offset header is noncanonical",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    expected = _OFFSET_HEADER.size + count * _U64.size
    if expected != len(data):
        raise CSVGenerationContractError(
            "row-offset artifact length does not match its count",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    offsets = tuple(
        _U64.unpack_from(data, _OFFSET_HEADER.size + index * _U64.size)[0]
        for index in range(count)
    )
    if offsets and (
        offsets[0] != 0
        or tuple(sorted(offsets)) != offsets
        or len(set(offsets)) != len(offsets)
        or offsets[-1] >= source_bytes
    ):
        raise CSVGenerationContractError(
            "row-offset records are noncanonical",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    return count, source_bytes, "sha256:" + digest.hex(), offsets


def _pack_row_anchors(
    anchors: Sequence[CSVRowAnchorRecord],
    *,
    source_bytes: int,
    source_sha256: str,
) -> bytes:
    header = _ANCHOR_HEADER.pack(
        _ANCHOR_MAGIC,
        CSV_GENERATION_FORMAT_VERSION,
        0,
        _ANCHOR_RECORD.size,
        len(anchors),
        source_bytes,
        _root_digest(source_sha256),
    )
    records = []
    for expected_ordinal, anchor in enumerate(anchors):
        if anchor.ordinal != expected_ordinal:
            raise CSVGenerationContractError(
                "row-anchor ordinals must be contiguous from zero",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        records.append(
            _ANCHOR_RECORD.pack(
                anchor.ordinal,
                anchor.start_offset,
                anchor.end_offset,
                anchor.first_chunk,
                anchor.last_chunk,
                _root_digest(anchor.row_sha256),
            )
        )
    return header + b"".join(records)


def decode_row_anchors(
    data: bytes,
) -> tuple[int, int, str, tuple[CSVRowAnchorRecord, ...]]:
    """Validate and decode the canonical packed row-anchor artifact."""

    if not isinstance(data, bytes) or len(data) < _ANCHOR_HEADER.size:
        raise CSVGenerationContractError("row-anchor artifact is truncated")
    magic, major, minor, record_bytes, count, source_bytes, digest = (
        _ANCHOR_HEADER.unpack_from(data)
    )
    if (
        magic != _ANCHOR_MAGIC
        or major != CSV_GENERATION_FORMAT_VERSION
        or minor != 0
        or record_bytes != _ANCHOR_RECORD.size
    ):
        raise CSVGenerationContractError(
            "row-anchor header is noncanonical",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    expected = _ANCHOR_HEADER.size + count * _ANCHOR_RECORD.size
    if expected != len(data):
        raise CSVGenerationContractError(
            "row-anchor artifact length does not match its count",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    anchors = []
    previous_end = 0
    for ordinal in range(count):
        values = _ANCHOR_RECORD.unpack_from(
            data, _ANCHOR_HEADER.size + ordinal * _ANCHOR_RECORD.size
        )
        stored_ordinal, start, end, first_chunk, last_chunk, row_digest = values
        if stored_ordinal != ordinal or start != previous_end or end <= start:
            raise CSVGenerationContractError(
                "row-anchor spans are noncanonical",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        if end > source_bytes or first_chunk > last_chunk:
            raise CSVGenerationContractError(
                "row-anchor record lies outside its source or chunk range",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        anchors.append(
            CSVRowAnchorRecord(
                ordinal=ordinal,
                start_offset=start,
                end_offset=end,
                first_chunk=first_chunk,
                last_chunk=last_chunk,
                row_sha256="sha256:" + row_digest.hex(),
            )
        )
        previous_end = end
    if anchors and anchors[-1].end_offset != source_bytes:
        raise CSVGenerationContractError(
            "row anchors do not cover the exact source extent",
            fault=CSVGenerationFault.INCOMPLETE_GENERATION,
        )
    if not anchors and source_bytes != 0:
        raise CSVGenerationContractError(
            "non-empty source requires row anchors",
            fault=CSVGenerationFault.INCOMPLETE_GENERATION,
        )
    return count, source_bytes, "sha256:" + digest.hex(), tuple(anchors)


def _chunk_for_span(
    chunks: Sequence[CSVChunkDescriptor], start: int, end: int
) -> tuple[int, int]:
    if end <= start:
        raise CSVGenerationContractError("row spans must be non-empty")
    chunk_ends = [chunk.end_offset for chunk in chunks]
    first = bisect_right(chunk_ends, start)
    last = bisect_left(chunk_ends, end)
    if first >= len(chunks) or last >= len(chunks) or first > last:
        raise CSVGenerationContractError(
            "row span is not covered by source chunks",
            fault=CSVGenerationFault.INCOMPLETE_GENERATION,
        )
    return first, last


def _closure_payload(
    chunks: Sequence[CSVChunkDescriptor],
    chunk_crc32: Sequence[int],
    *,
    row_offsets_root: str,
    row_anchors_root: str,
) -> dict[str, Any]:
    if len(chunks) != len(chunk_crc32):
        raise CSVGenerationContractError("chunk checksum evidence length mismatch")
    nodes: list[dict[str, Any]] = []
    for chunk, checksum in zip(chunks, chunk_crc32):
        nodes.append(
            {
                "kind": "source_chunk",
                "ordinal": chunk.ordinal,
                "root": chunk.content_root,
                "bytes": chunk.end_offset - chunk.start_offset,
                "checksum_algorithm": chunk.checksum_algorithm,
                "checksum32": checksum,
                "dependencies": [],
            }
        )
    chunk_roots = [chunk.content_root for chunk in chunks]
    nodes.append(
        {
            "kind": "row_offsets",
            "root": row_offsets_root,
            "dependencies": chunk_roots,
        }
    )
    nodes.append(
        {
            "kind": "row_anchors",
            "root": row_anchors_root,
            "dependencies": [*chunk_roots, row_offsets_root],
        }
    )
    return {
        "contract_id": CSV_GENERATION_CONTRACT_ID,
        "format_version": CSV_GENERATION_FORMAT_VERSION,
        "topological": True,
        "nodes": nodes,
    }


def _manifest_wrapper(
    staged: StagedCSVGeneration,
) -> dict[str, Any]:
    return {
        "contract_id": CSV_GENERATION_CONTRACT_ID,
        "format_version": CSV_GENERATION_FORMAT_VERSION,
        "manifest_root": staged.manifest_root,
        "limits": staged.limits.canonical_dict(),
        "profile": staged.profile.canonical_dict(),
        "manifest": staged.manifest.canonical_dict(),
    }


def _strip_contract_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    if result.pop("contract_id", None) != CSV_GENERATION_CONTRACT_ID:
        raise CSVGenerationContractError("artifact has the wrong contract identity")
    if result.pop("format_version", None) != CSV_GENERATION_FORMAT_VERSION:
        raise CSVGenerationContractError("artifact has the wrong format version")
    return result


def _staged_from_wrapper(value: Mapping[str, Any]) -> StagedCSVGeneration:
    wrapper = _strip_contract_fields(value)
    required = {"manifest_root", "limits", "profile", "manifest"}
    if set(wrapper) != required:
        raise CSVGenerationContractError(
            "generation wrapper has unknown or missing fields",
            fault=CSVGenerationFault.NONCANONICAL,
        )

    limits = CSVGenerationLimits(**_strip_contract_fields(wrapper["limits"]))
    profile_values = _strip_contract_fields(wrapper["profile"])
    parser_root = profile_values.pop("parser_root", None)
    if parser_root != CSV_REFERENCE_PARSER_ROOT:
        raise CSVGenerationContractError(
            "generation references an unqualified parser contract",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    profile = CSVStreamProfile(**profile_values)

    manifest_values = _strip_contract_fields(wrapper["manifest"])
    generation_root = manifest_values.pop("generation_root", None)
    identity_values = _strip_contract_fields(manifest_values.pop("identity"))
    chunks = tuple(
        CSVChunkDescriptor(**chunk) for chunk in manifest_values.pop("chunks")
    )
    manifest = CSVGenerationManifest(
        identity=CSVGenerationIdentity(**identity_values),
        chunks=chunks,
        **manifest_values,
    )
    if generation_root != manifest.identity.generation_root:
        raise CSVGenerationContractError(
            "stored generation root does not match the manifest identity",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    if wrapper["manifest_root"] != manifest.manifest_root:
        raise CSVGenerationContractError(
            "stored manifest root does not match canonical manifest bytes",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    if manifest.identity.limits_root != limits.limits_root:
        raise CSVGenerationContractError(
            "stored limits do not match the manifest identity",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    if manifest.identity.dialect_root != profile.dialect_root:
        raise CSVGenerationContractError(
            "stored dialect does not match the manifest identity",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    return StagedCSVGeneration(manifest=manifest, limits=limits, profile=profile)


def _decode_canonical_json(data: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CSVGenerationContractError("artifact is not canonical JSON") from exc
    if not isinstance(value, dict) or _canonical_json_bytes(value) != data:
        raise CSVGenerationContractError(
            "JSON artifact is not in canonical encoding",
            fault=CSVGenerationFault.NONCANONICAL,
        )
    return value


class CSVGenerationLease:
    """One immutable generation pin; it never follows CURRENT after acquisition."""

    def __init__(
        self,
        store: "AtomicCSVGenerationStore",
        staged: StagedCSVGeneration,
    ) -> None:
        self._store = store
        self.staged = staged
        self._closed = False
        self._store._pin(staged.generation_root)

    @property
    def manifest(self) -> CSVGenerationManifest:
        return self.staged.manifest

    @property
    def generation_root(self) -> str:
        return self.staged.generation_root

    def read_source(self) -> bytes:
        self._require_open()
        return self._store._read_source(self.manifest)

    def row_offsets(self) -> tuple[int, ...]:
        self._require_open()
        data = self._store._read_object(self.manifest.identity.row_offsets_root)
        return decode_row_offsets(data)[3]

    def row_anchors(self) -> tuple[CSVRowAnchorRecord, ...]:
        self._require_open()
        data = self._store._read_object(self.manifest.identity.row_anchors_root)
        return decode_row_anchors(data)[3]

    def _require_open(self) -> None:
        if self._closed:
            raise CSVGenerationContractError("generation lease is closed")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._store._unpin(self.generation_root)

    def __enter__(self) -> "CSVGenerationLease":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class AtomicCSVGenerationStore:
    """Content-addressed reference store with atomic current-generation swaps."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.objects_dir = self.root / "objects"
        self.staging_dir = self.root / "staging"
        self.generations_dir = self.root / "generations"
        self.receipts_dir = self.root / "receipts"
        self.current_path = self.root / "CURRENT"
        for directory in (
            self.objects_dir,
            self.staging_dir,
            self.generations_dir,
            self.receipts_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._publication_lock = threading.RLock()
        self._pin_lock = threading.Lock()
        self._pins: dict[str, int] = {}

    def _object_path(self, root: str) -> Path:
        return self.objects_dir / _root_hex(root)

    def _write_object(self, data: bytes) -> str:
        root = _content_root(data)
        _atomic_write_exact(self._object_path(root), data)
        return root

    def _read_object(self, root: str) -> bytes:
        path = self._object_path(root)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise CSVGenerationContractError(
                f"missing immutable object {root}",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            ) from exc
        if _content_root(data) != root:
            raise CSVGenerationContractError(
                f"immutable object failed content verification: {root}",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return data

    def _staging_path(self, manifest_root: str) -> Path:
        return self.staging_dir / f"{_root_hex(manifest_root)}.json"

    def _generation_manifest_path(self, generation_root: str) -> Path:
        return self.generations_dir / _root_hex(generation_root) / "manifest.json"

    def _receipt_path(self, receipt_root: str) -> Path:
        return self.receipts_dir / f"{_root_hex(receipt_root)}.json"

    def _write_receipt(self, receipt: CSVGenerationReceipt) -> None:
        wrapper = {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            "receipt_root": receipt.receipt_root,
            "receipt": receipt.canonical_dict(),
        }
        _atomic_write_exact(
            self._receipt_path(receipt.receipt_root), _canonical_json_bytes(wrapper)
        )

    def stage(
        self,
        dataset_id: str,
        blocks: Iterable[bytes | bytearray | memoryview],
        *,
        chunk_bytes: int,
        profile: CSVStreamProfile | None = None,
        limits: CSVGenerationLimits = CSV_GENERATION_QUALIFICATION_LIMITS,
        parent_generation_root: str = "",
    ) -> StagedCSVGeneration:
        """Stream one candidate into immutable objects without changing CURRENT."""

        selected_profile = profile or CSVStreamProfile()
        if not isinstance(limits, CSVGenerationLimits):
            raise CSVGenerationContractError("limits must be CSVGenerationLimits")
        if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int):
            raise CSVGenerationContractError("chunk_bytes must be an integer")
        if chunk_bytes <= 0 or chunk_bytes > limits.max_chunk_bytes:
            raise CSVGenerationContractError(
                "chunk_bytes exceeds the admitted generation profile",
                fault=CSVGenerationFault.BOUND_EXCEEDED,
            )

        parser = _CSVRowStreamOracle(selected_profile)
        source_hasher = hashlib.sha256()
        buffer = bytearray()
        chunks: list[CSVChunkDescriptor] = []
        checksums: list[int] = []
        total_bytes = 0

        def flush_chunk() -> None:
            nonlocal buffer
            if not buffer:
                return
            if len(chunks) >= limits.max_chunks:
                raise CSVGenerationContractError(
                    "chunk count exceeds the admitted generation profile",
                    fault=CSVGenerationFault.BOUND_EXCEEDED,
                )
            raw = bytes(buffer)
            start = chunks[-1].end_offset if chunks else 0
            end = start + len(raw)
            root = self._write_object(raw)
            chunks.append(
                CSVChunkDescriptor(
                    ordinal=len(chunks),
                    start_offset=start,
                    end_offset=end,
                    content_root=root,
                )
            )
            checksums.append(zlib.crc32(raw) & 0xFFFFFFFF)
            buffer = bytearray()

        for block in blocks:
            try:
                snapshot = bytes(block)
            except Exception as exc:
                raise CSVGenerationContractError(
                    "generation input blocks must support an exact byte snapshot"
                ) from exc
            if not snapshot:
                continue
            if total_bytes + len(snapshot) > limits.max_source_bytes:
                raise CSVGenerationContractError(
                    "source bytes exceed the admitted generation profile",
                    fault=CSVGenerationFault.BOUND_EXCEEDED,
                )
            parser.feed(snapshot)
            source_hasher.update(snapshot)
            total_bytes += len(snapshot)
            position = 0
            while position < len(snapshot):
                take = min(chunk_bytes - len(buffer), len(snapshot) - position)
                buffer.extend(snapshot[position : position + take])
                position += take
                if len(buffer) == chunk_bytes:
                    flush_chunk()
        flush_chunk()

        row_offsets, raw_anchors = parser.finalize()
        if parser.offset != total_bytes:
            raise CSVGenerationContractError(
                "stream parser did not consume the exact source extent",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            )
        if len(row_offsets) > limits.max_rows:
            raise CSVGenerationContractError(
                "row count exceeds the admitted generation profile",
                fault=CSVGenerationFault.BOUND_EXCEEDED,
            )

        source_root = "sha256:" + source_hasher.hexdigest()
        offset_bytes = _pack_row_offsets(
            row_offsets, source_bytes=total_bytes, source_sha256=source_root
        )
        row_offsets_root = self._write_object(offset_bytes)

        anchors: list[CSVRowAnchorRecord] = []
        for ordinal, anchor in enumerate(raw_anchors):
            first_chunk, last_chunk = _chunk_for_span(
                chunks, anchor.start_offset, anchor.end_offset
            )
            anchors.append(
                CSVRowAnchorRecord(
                    ordinal=ordinal,
                    start_offset=anchor.start_offset,
                    end_offset=anchor.end_offset,
                    first_chunk=first_chunk,
                    last_chunk=last_chunk,
                    row_sha256="sha256:" + anchor.digest.hex(),
                )
            )
        anchor_bytes = _pack_row_anchors(
            anchors, source_bytes=total_bytes, source_sha256=source_root
        )
        row_anchors_root = self._write_object(anchor_bytes)

        closure = _closure_payload(
            chunks,
            checksums,
            row_offsets_root=row_offsets_root,
            row_anchors_root=row_anchors_root,
        )
        closure_bytes = _canonical_json_bytes(closure)
        closure_root = self._write_object(closure_bytes)
        closure_node_count = len(closure["nodes"])
        closure_edge_count = sum(
            len(node["dependencies"]) for node in closure["nodes"]
        )

        identity = CSVGenerationIdentity(
            dataset_id=dataset_id,
            source_sha256=source_root,
            chunk_sequence_root=chunk_sequence_root(tuple(chunks)),
            parser_contract_root=CSV_REFERENCE_PARSER_ROOT,
            dialect_root=selected_profile.dialect_root,
            row_offsets_root=row_offsets_root,
            row_anchors_root=row_anchors_root,
            closure_root=closure_root,
            limits_root=limits.limits_root,
            parent_generation_root=parent_generation_root,
        )
        manifest = CSVGenerationManifest(
            identity=identity,
            source_bytes=total_bytes,
            row_count=len(anchors),
            closure_node_count=closure_node_count,
            closure_edge_count=closure_edge_count,
            chunks=tuple(chunks),
        )
        validate_manifest(manifest, limits)
        staged = StagedCSVGeneration(
            manifest=manifest,
            limits=limits,
            profile=selected_profile,
        )
        _atomic_write_exact(
            self._staging_path(staged.manifest_root),
            _canonical_json_bytes(_manifest_wrapper(staged)),
        )
        return staged

    def load_staged(self, manifest_root: str) -> StagedCSVGeneration:
        path = self._staging_path(manifest_root)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise CSVGenerationContractError(
                "staged generation manifest is missing",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            ) from exc
        staged = _staged_from_wrapper(_decode_canonical_json(data))
        if staged.manifest_root != manifest_root:
            raise CSVGenerationContractError(
                "staging filename does not match its manifest root",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return staged

    def _read_source(self, manifest: CSVGenerationManifest) -> bytes:
        parts = [self._read_object(chunk.content_root) for chunk in manifest.chunks]
        data = b"".join(parts)
        if len(data) != manifest.source_bytes:
            raise CSVGenerationContractError(
                "source chunks do not reconstruct the declared byte extent",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            )
        if _content_root(data) != manifest.identity.source_sha256:
            raise CSVGenerationContractError(
                "source reconstruction failed its SHA-256 identity",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return data

    def _hash_source_span(
        self,
        manifest: CSVGenerationManifest,
        start: int,
        end: int,
    ) -> str:
        hasher = hashlib.sha256()
        remaining_start = start
        for chunk in manifest.chunks:
            if chunk.end_offset <= remaining_start:
                continue
            if chunk.start_offset >= end:
                break
            data = self._read_object(chunk.content_root)
            local_start = max(remaining_start, chunk.start_offset) - chunk.start_offset
            local_end = min(end, chunk.end_offset) - chunk.start_offset
            hasher.update(data[local_start:local_end])
        return "sha256:" + hasher.hexdigest()

    def verify(
        self, staged: StagedCSVGeneration | str
    ) -> CSVGenerationVerification:
        """Independently verify all immutable objects and the rooted closure."""

        candidate = self.load_staged(staged) if isinstance(staged, str) else staged
        if not isinstance(candidate, StagedCSVGeneration):
            raise CSVGenerationContractError(
                "verify requires a staged generation or exact manifest root"
            )
        manifest = candidate.manifest
        validate_manifest(manifest, candidate.limits)

        source_hasher = hashlib.sha256()
        checksums: list[int] = []
        for chunk in manifest.chunks:
            data = self._read_object(chunk.content_root)
            if len(data) != chunk.end_offset - chunk.start_offset:
                raise CSVGenerationContractError(
                    "source chunk length does not match its declared span",
                    fault=CSVGenerationFault.IDENTITY_MISMATCH,
                )
            source_hasher.update(data)
            checksums.append(zlib.crc32(data) & 0xFFFFFFFF)
        source_root = "sha256:" + source_hasher.hexdigest()
        if source_root != manifest.identity.source_sha256:
            raise CSVGenerationContractError(
                "streamed source verification failed",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )

        offset_data = self._read_object(manifest.identity.row_offsets_root)
        offset_count, offset_extent, offset_source, offsets = decode_row_offsets(
            offset_data
        )
        anchor_data = self._read_object(manifest.identity.row_anchors_root)
        anchor_count, anchor_extent, anchor_source, anchors = decode_row_anchors(
            anchor_data
        )
        if not (
            offset_count
            == anchor_count
            == manifest.row_count
            == len(offsets)
            == len(anchors)
        ):
            raise CSVGenerationContractError(
                "row offset, anchor, and manifest counts disagree",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        if not (
            offset_extent
            == anchor_extent
            == manifest.source_bytes
            and offset_source
            == anchor_source
            == manifest.identity.source_sha256
        ):
            raise CSVGenerationContractError(
                "packed row evidence is bound to the wrong source",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        for ordinal, (offset, anchor) in enumerate(zip(offsets, anchors)):
            expected_end = (
                offsets[ordinal + 1]
                if ordinal + 1 < len(offsets)
                else manifest.source_bytes
            )
            if offset != anchor.start_offset or expected_end != anchor.end_offset:
                raise CSVGenerationContractError(
                    "row offsets and row anchors disagree",
                    fault=CSVGenerationFault.IDENTITY_MISMATCH,
                )
            first_chunk, last_chunk = _chunk_for_span(
                manifest.chunks, anchor.start_offset, anchor.end_offset
            )
            if (first_chunk, last_chunk) != (
                anchor.first_chunk,
                anchor.last_chunk,
            ):
                raise CSVGenerationContractError(
                    "row anchor has the wrong source chunk span",
                    fault=CSVGenerationFault.IDENTITY_MISMATCH,
                )
            if (
                self._hash_source_span(
                    manifest, anchor.start_offset, anchor.end_offset
                )
                != anchor.row_sha256
            ):
                raise CSVGenerationContractError(
                    "row anchor hash does not match exact source bytes",
                    fault=CSVGenerationFault.IDENTITY_MISMATCH,
                )

        expected_closure = _canonical_json_bytes(
            _closure_payload(
                manifest.chunks,
                checksums,
                row_offsets_root=manifest.identity.row_offsets_root,
                row_anchors_root=manifest.identity.row_anchors_root,
            )
        )
        closure_data = self._read_object(manifest.identity.closure_root)
        if closure_data != expected_closure:
            raise CSVGenerationContractError(
                "closure DAG does not match the complete generation object set",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        closure = _decode_canonical_json(closure_data)
        node_count = len(closure["nodes"])
        edge_count = sum(len(node["dependencies"]) for node in closure["nodes"])
        if (node_count, edge_count) != (
            manifest.closure_node_count,
            manifest.closure_edge_count,
        ):
            raise CSVGenerationContractError(
                "closure counts do not match the manifest",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )

        return CSVGenerationVerification(
            generation_root=manifest.identity.generation_root,
            manifest_root=manifest.manifest_root,
            source_sha256=source_root,
            source_bytes=manifest.source_bytes,
            chunk_count=len(manifest.chunks),
            row_count=manifest.row_count,
            closure_node_count=node_count,
            closure_edge_count=edge_count,
        )

    def _generation_wrapper_path(self, generation_root: str) -> Path:
        return self._generation_manifest_path(generation_root)

    def _write_generation_wrapper(self, staged: StagedCSVGeneration) -> None:
        _atomic_write_exact(
            self._generation_wrapper_path(staged.generation_root),
            _canonical_json_bytes(_manifest_wrapper(staged)),
        )

    def load_generation(self, generation_root: str) -> StagedCSVGeneration:
        path = self._generation_wrapper_path(generation_root)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise CSVGenerationContractError(
                "published generation manifest is missing",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            ) from exc
        staged = _staged_from_wrapper(_decode_canonical_json(data))
        if staged.generation_root != generation_root:
            raise CSVGenerationContractError(
                "generation directory does not match its identity",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return staged

    def _pointer_bytes(self, pointer: CurrentCSVGeneration) -> bytes:
        payload = {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            **asdict(pointer),
        }
        payload_bytes = _canonical_json_bytes(payload)
        return _canonical_json_bytes(
            {
                "payload": payload,
                "payload_sha256": _content_root(payload_bytes),
            }
        )

    def read_current(self) -> CurrentCSVGeneration | None:
        try:
            data = self.current_path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CSVGenerationContractError("cannot read CURRENT") from exc
        wrapper = _decode_canonical_json(data)
        if set(wrapper) != {"payload", "payload_sha256"}:
            raise CSVGenerationContractError(
                "CURRENT has unknown or missing fields",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        payload = wrapper["payload"]
        if not isinstance(payload, dict):
            raise CSVGenerationContractError("CURRENT payload is malformed")
        if wrapper["payload_sha256"] != _content_root(
            _canonical_json_bytes(payload)
        ):
            raise CSVGenerationContractError(
                "CURRENT failed integrity verification",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        values = _strip_contract_fields(payload)
        if set(values) != {
            "generation_root",
            "manifest_root",
            "published_receipt_root",
        }:
            raise CSVGenerationContractError(
                "CURRENT payload has unknown or missing fields",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        for root in values.values():
            _root_hex(root)
        return CurrentCSVGeneration(**values)

    def publish(
        self,
        staged: StagedCSVGeneration | str,
        *,
        expected_current_manifest_root: str | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> CSVGenerationReceipt:
        """Verify and atomically publish one complete candidate generation."""

        candidate = self.load_staged(staged) if isinstance(staged, str) else staged
        if not isinstance(candidate, StagedCSVGeneration):
            raise CSVGenerationContractError(
                "publish requires a staged generation or exact manifest root"
            )

        def inject(point: str) -> None:
            if fault_injector is not None:
                fault_injector(point)

        with self._publication_lock:
            self.verify(candidate)
            inject("after_staged_verify")
            self._write_generation_wrapper(candidate)
            inject("after_manifest_write")

            staging = CSVGenerationReceipt(
                candidate.generation_root,
                candidate.manifest_root,
                CSVGenerationState.STAGING,
            )
            sealed = CSVGenerationReceipt(
                candidate.generation_root,
                candidate.manifest_root,
                CSVGenerationState.SEALED,
                staging.receipt_root,
            )
            verified = CSVGenerationReceipt(
                candidate.generation_root,
                candidate.manifest_root,
                CSVGenerationState.VERIFIED,
                sealed.receipt_root,
            )
            published = CSVGenerationReceipt(
                candidate.generation_root,
                candidate.manifest_root,
                CSVGenerationState.PUBLISHED,
                verified.receipt_root,
            )
            validate_receipt_transition(staging, sealed)
            validate_receipt_transition(sealed, verified)
            validate_receipt_transition(verified, published)
            for receipt in (staging, sealed, verified):
                self._write_receipt(receipt)
            inject("after_verified_receipt")
            self._write_receipt(published)
            inject("after_published_receipt")

            current = self.read_current()
            observed = "" if current is None else current.manifest_root
            expected = (
                observed
                if expected_current_manifest_root is None
                else expected_current_manifest_root
            )
            if expected and not _ROOT_PATTERN.fullmatch(expected):
                raise CSVGenerationContractError(
                    "expected current manifest root is malformed"
                )
            if observed != expected:
                raise CSVGenerationContractError(
                    "CURRENT changed before publication",
                    fault=CSVGenerationFault.PUBLICATION_CONFLICT,
                )
            inject("before_current_replace")
            pointer = CurrentCSVGeneration(
                generation_root=candidate.generation_root,
                manifest_root=candidate.manifest_root,
                published_receipt_root=published.receipt_root,
            )
            _atomic_replace(self.current_path, self._pointer_bytes(pointer))
            inject("after_current_replace")
            return published

    def _pin(self, generation_root: str) -> None:
        with self._pin_lock:
            self._pins[generation_root] = self._pins.get(generation_root, 0) + 1

    def _unpin(self, generation_root: str) -> None:
        with self._pin_lock:
            count = self._pins.get(generation_root, 0)
            if count <= 0:
                raise CSVGenerationContractError("generation pin underflow")
            if count == 1:
                self._pins.pop(generation_root, None)
            else:
                self._pins[generation_root] = count - 1

    def pin_count(self, generation_root: str) -> int:
        with self._pin_lock:
            return self._pins.get(generation_root, 0)

    def open_generation(self, generation_root: str) -> CSVGenerationLease:
        staged = self.load_generation(generation_root)
        self.verify(staged)
        return CSVGenerationLease(self, staged)

    def open_current(self) -> CSVGenerationLease:
        pointer = self.read_current()
        if pointer is None:
            raise CSVGenerationContractError(
                "no CSV generation is currently published",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            )
        staged = self.load_generation(pointer.generation_root)
        if staged.manifest_root != pointer.manifest_root:
            raise CSVGenerationContractError(
                "CURRENT mixes generation and manifest identities",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        self.verify(staged)
        return CSVGenerationLease(self, staged)

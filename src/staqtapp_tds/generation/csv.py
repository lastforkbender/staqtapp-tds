"""CSV consumer for the generic immutable Generation Authority.

This module gives CSV source bytes a complete, generation-scoped binding.  It
does not maintain a second store or CURRENT pointer: candidates are built by
``AtomicGenerationStore`` and readers are pinned by ``GenerationLease``.

The byte-level row oracle is deliberately independent of text decoding.  The
authoritative payload is always the exact source byte string supplied by the
caller, including a BOM, mixed line endings, and bytes that are not UTF-8.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import struct
from typing import Any, Mapping, Sequence

from .generation_contract import (
    GenerationContractError,
    GenerationFault,
    bytes_root,
    canonical_json_bytes,
    require_root,
)
from .generation_store import (
    AtomicGenerationStore,
    GenerationCandidate,
    GenerationLease,
    PublicationResult,
)

CSV_GENERATION_FORMAT_VERSION = 1
CSV_GENERATION_CONTRACT_ID = "tds-csv-generation-binding-v1"
CSV_REFERENCE_PARSER_ID = "tds-csv-byte-row-oracle-v1"

CSV_SOURCE_PAYLOAD = "csv.source"
CSV_BINDING_PAYLOAD = "csv.binding"
CSV_CHUNKS_PAYLOAD = "csv.chunks"
CSV_PARSER_PAYLOAD = "csv.parser"
CSV_DIALECT_PAYLOAD = "csv.dialect"
CSV_ROW_OFFSETS_PAYLOAD = "csv.row-offsets"
CSV_ROW_ANCHORS_PAYLOAD = "csv.row-anchors"
CSV_CHUNK_PAYLOAD_PREFIX = "csv.chunk."

_CSV_FIXED_PAYLOADS = frozenset(
    {
        CSV_SOURCE_PAYLOAD,
        CSV_BINDING_PAYLOAD,
        CSV_CHUNKS_PAYLOAD,
        CSV_PARSER_PAYLOAD,
        CSV_DIALECT_PAYLOAD,
        CSV_ROW_OFFSETS_PAYLOAD,
        CSV_ROW_ANCHORS_PAYLOAD,
    }
)
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,190}$")
_UINT32_MAX = (1 << 32) - 1
_UINT63_MAX = (1 << 63) - 1

_OFFSET_MAGIC = b"TDSCRO1\x00"
_ANCHOR_MAGIC = b"TDSCRA1\x00"
_OFFSET_HEADER = struct.Struct(">8sHHIQQ32s")
_ANCHOR_HEADER = struct.Struct(">8sHHIQQQ32s32s")
_U64 = struct.Struct(">Q")
_ANCHOR_RECORD = struct.Struct(">QQQ32s")


def _require_int(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GenerationContractError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise GenerationContractError(
            f"{name} must be between {minimum} and {maximum}",
            fault=GenerationFault.BOUND_EXCEEDED,
        )
    return value


def _required_root(name: str, value: str) -> str:
    validated = require_root(name, value)
    assert validated is not None
    return validated


def _optional_root(name: str, value: str | None) -> str | None:
    return require_root(name, value, optional=True)


def _root_digest(name: str, root: str) -> bytes:
    return bytes.fromhex(_required_root(name, root).split(":", 1)[1])


def _digest_root(digest: bytes) -> str:
    return "sha256:" + digest.hex()


def _canonical_object(data: bytes, description: str) -> Mapping[str, Any]:
    if not isinstance(data, bytes):
        raise GenerationContractError(f"{description} must be exact bytes")
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationContractError(f"{description} is malformed JSON") from exc
    if not isinstance(value, dict):
        raise GenerationContractError(f"{description} must be a JSON object")
    if canonical_json_bytes(value) != data:
        raise GenerationContractError(
            f"{description} is not canonical JSON",
            fault=GenerationFault.NONCANONICAL,
        )
    return value


@dataclass(frozen=True, slots=True)
class CSVGenerationLimits:
    """Qualified mechanical limits for one CSV consumer candidate."""

    max_source_bytes: int = 1 << 32
    max_chunk_bytes: int = 64 << 20
    max_chunks: int = 1 << 20
    max_rows: int = 1 << 32
    max_anchor_count: int = 1024

    def __post_init__(self) -> None:
        _require_int("max_source_bytes", self.max_source_bytes, 0, _UINT63_MAX)
        _require_int("max_chunk_bytes", self.max_chunk_bytes, 1, _UINT32_MAX)
        _require_int("max_chunks", self.max_chunks, 0, _UINT32_MAX)
        _require_int("max_rows", self.max_rows, 0, _UINT63_MAX)
        _require_int("max_anchor_count", self.max_anchor_count, 1, _UINT32_MAX)


DEFAULT_CSV_GENERATION_LIMITS = CSVGenerationLimits()


@dataclass(frozen=True, slots=True)
class CSVParserContract:
    """The exact parser behavior qualified by this consumer."""

    parser_id: str = CSV_REFERENCE_PARSER_ID
    row_endings: tuple[str, ...] = ("crlf", "lf", "cr")
    stateful_across_feed_boundaries: bool = True
    original_bytes_authoritative: bool = True
    empty_input_rows: int = 0
    trailing_line_ending_adds_empty_row: bool = False
    strict_after_closing_quote: bool = True

    def __post_init__(self) -> None:
        if self.parser_id != CSV_REFERENCE_PARSER_ID:
            raise GenerationContractError("unsupported CSV parser contract")
        if (
            not isinstance(self.row_endings, tuple)
            or self.row_endings != ("crlf", "lf", "cr")
        ):
            raise GenerationContractError("unsupported CSV row-ending contract")
        flags = (
            self.stateful_across_feed_boundaries,
            self.original_bytes_authoritative,
            self.trailing_line_ending_adds_empty_row,
            self.strict_after_closing_quote,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise GenerationContractError("CSV parser flags must be boolean")
        if flags != (True, True, False, True) or self.empty_input_rows != 0:
            raise GenerationContractError("CSV parser authority cannot be widened")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            "parser_id": self.parser_id,
            "row_endings": list(self.row_endings),
            "stateful_across_feed_boundaries": self.stateful_across_feed_boundaries,
            "original_bytes_authoritative": self.original_bytes_authoritative,
            "empty_input_rows": self.empty_input_rows,
            "trailing_line_ending_adds_empty_row": (
                self.trailing_line_ending_adds_empty_row
            ),
            "strict_after_closing_quote": self.strict_after_closing_quote,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())


CSV_REFERENCE_PARSER = CSVParserContract()
CSV_REFERENCE_PARSER_BYTES = CSV_REFERENCE_PARSER.canonical_bytes()
CSV_REFERENCE_PARSER_ROOT = bytes_root(CSV_REFERENCE_PARSER_BYTES)


@dataclass(frozen=True, slots=True)
class CSVDialect:
    """Byte-level dialect used only to locate CSV record boundaries."""

    delimiter: int = ord(",")
    quote: int = ord('"')
    escape: int | None = None
    doublequote: bool = True

    def __post_init__(self) -> None:
        _require_int("delimiter", self.delimiter, 0, 255)
        _require_int("quote", self.quote, 0, 255)
        if self.delimiter == self.quote:
            raise GenerationContractError("delimiter and quote must differ")
        if self.delimiter in (10, 13) or self.quote in (10, 13):
            raise GenerationContractError(
                "delimiter and quote must differ from CSV row-ending bytes"
            )
        if self.escape is not None:
            _require_int("escape", self.escape, 0, 255)
            if self.escape in {self.delimiter, self.quote, 10, 13}:
                raise GenerationContractError(
                    "escape must differ from delimiter, quote, and row endings"
                )
        if not isinstance(self.doublequote, bool):
            raise GenerationContractError("doublequote must be boolean")

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

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @property
    def dialect_root(self) -> str:
        return bytes_root(self.canonical_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "CSVDialect":
        value = _canonical_object(data, "CSV dialect")
        expected = {
            "contract_id",
            "format_version",
            "parser_root",
            "delimiter",
            "quote",
            "escape",
            "doublequote",
        }
        if set(value) != expected:
            raise GenerationContractError(
                "CSV dialect fields are not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        if (
            value["contract_id"] != CSV_GENERATION_CONTRACT_ID
            or value["format_version"] != CSV_GENERATION_FORMAT_VERSION
            or value["parser_root"] != CSV_REFERENCE_PARSER_ROOT
        ):
            raise GenerationContractError(
                "CSV dialect parser binding mismatch",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        result = cls(
            delimiter=value["delimiter"],
            quote=value["quote"],
            escape=value["escape"],
            doublequote=value["doublequote"],
        )
        if result.canonical_bytes() != data:
            raise GenerationContractError(
                "CSV dialect is not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        return result


class CSVRowBoundaryOracle:
    """Streaming byte oracle whose result is invariant under every feed split."""

    def __init__(self, dialect: CSVDialect | None = None) -> None:
        self.dialect = dialect or CSVDialect()
        if not isinstance(self.dialect, CSVDialect):
            raise GenerationContractError("dialect must be a CSVDialect")
        self._position = 0
        self._row_open = False
        self._row_offsets: list[int] = []
        self._in_quotes = False
        self._pending_quote = False
        self._pending_escape = False
        self._pending_cr = False
        self._field_start = True
        self._after_quote = False
        self._finished = False

    @property
    def bytes_consumed(self) -> int:
        return self._position

    def _open_row(self, start: int) -> None:
        if not self._row_open:
            self._row_open = True
            self._row_offsets.append(start)

    def _finish_row(self) -> None:
        if not self._row_open:
            raise GenerationContractError(
                "CSV row state underflow",
                fault=GenerationFault.NONCANONICAL,
            )
        self._row_open = False
        self._field_start = True
        self._after_quote = False

    def _outside_after_closed_quote(self, byte: int) -> None:
        if byte == self.dialect.delimiter:
            self._after_quote = False
            self._field_start = True
        elif byte == 13:
            self._pending_cr = True
        elif byte == 10:
            self._finish_row()
        else:
            raise GenerationContractError(
                "unexpected byte after a closing CSV quote",
                fault=GenerationFault.NONCANONICAL,
            )

    def _outside(self, byte: int) -> None:
        if self._after_quote:
            self._outside_after_closed_quote(byte)
            return
        if self._field_start and byte == self.dialect.quote:
            self._in_quotes = True
            self._field_start = False
        elif byte == self.dialect.delimiter:
            self._field_start = True
        elif byte == 13:
            self._pending_cr = True
        elif byte == 10:
            self._finish_row()
        else:
            self._field_start = False

    def feed(self, block: bytes) -> None:
        if self._finished:
            raise GenerationContractError("cannot feed a finalized CSV oracle")
        if not isinstance(block, bytes):
            raise GenerationContractError("CSV oracle blocks must be exact bytes")

        for byte in block:
            current_start = self._position
            self._position += 1

            if self._pending_cr:
                if byte == 10:
                    self._pending_cr = False
                    self._finish_row()
                    continue
                self._pending_cr = False
                self._finish_row()

            self._open_row(current_start)

            if self._in_quotes:
                if self._pending_escape:
                    self._pending_escape = False
                    continue
                if self._pending_quote:
                    if self.dialect.doublequote and byte == self.dialect.quote:
                        self._pending_quote = False
                        continue
                    self._pending_quote = False
                    self._in_quotes = False
                    self._after_quote = True
                    self._outside_after_closed_quote(byte)
                    continue
                if self.dialect.escape is not None and byte == self.dialect.escape:
                    self._pending_escape = True
                    continue
                if byte == self.dialect.quote:
                    if self.dialect.doublequote:
                        self._pending_quote = True
                    else:
                        self._in_quotes = False
                        self._after_quote = True
                    continue
                continue

            self._outside(byte)

    def finalize(self) -> tuple[int, ...]:
        if self._finished:
            raise GenerationContractError("CSV oracle was already finalized")
        self._finished = True
        if self._pending_escape:
            raise GenerationContractError(
                "CSV source ended after an escape byte",
                fault=GenerationFault.INCOMPLETE_GENERATION,
            )
        if self._pending_quote:
            self._pending_quote = False
            self._in_quotes = False
            self._after_quote = True
        if self._in_quotes:
            raise GenerationContractError(
                "CSV source ended inside an open quoted field",
                fault=GenerationFault.INCOMPLETE_GENERATION,
            )
        if self._pending_cr:
            self._pending_cr = False
            self._finish_row()
        elif self._row_open:
            self._finish_row()
        return tuple(self._row_offsets)


@dataclass(frozen=True, slots=True)
class CSVRowAnchor:
    row_ordinal: int
    start_offset: int
    end_offset: int
    content_root: str

    def __post_init__(self) -> None:
        _require_int("row_ordinal", self.row_ordinal, 0, _UINT63_MAX)
        _require_int("start_offset", self.start_offset, 0, _UINT63_MAX)
        _require_int("end_offset", self.end_offset, 1, _UINT63_MAX)
        if self.end_offset <= self.start_offset:
            raise GenerationContractError(
                "CSV anchor span must be non-empty",
                fault=GenerationFault.NONCANONICAL,
            )
        _required_root("anchor content_root", self.content_root)


def pack_row_offsets(
    offsets: Sequence[int],
    *,
    source_size: int,
    source_root: str,
) -> bytes:
    """Pack source-bound row starts in one canonical fixed-width format."""

    _require_int("source_size", source_size, 0, _UINT63_MAX)
    digest = _root_digest("source_root", source_root)
    normalized = tuple(offsets)
    _require_int("row count", len(normalized), 0, _UINT63_MAX)
    for value in normalized:
        _require_int("row offset", value, 0, _UINT63_MAX)
    if normalized:
        if (
            normalized[0] != 0
            or tuple(sorted(normalized)) != normalized
            or len(set(normalized)) != len(normalized)
            or normalized[-1] >= source_size
        ):
            raise GenerationContractError(
                "row offsets are not canonical source row starts",
                fault=GenerationFault.NONCANONICAL,
            )
    elif source_size != 0:
        raise GenerationContractError(
            "non-empty CSV source requires a row start",
            fault=GenerationFault.INCOMPLETE_GENERATION,
        )
    header = _OFFSET_HEADER.pack(
        _OFFSET_MAGIC,
        CSV_GENERATION_FORMAT_VERSION,
        0,
        _U64.size,
        len(normalized),
        source_size,
        digest,
    )
    return header + b"".join(_U64.pack(value) for value in normalized)


def decode_row_offsets(data: bytes) -> tuple[int, int, str, tuple[int, ...]]:
    """Decode and reject any noncanonical packed row-offset artifact."""

    if not isinstance(data, bytes) or len(data) < _OFFSET_HEADER.size:
        raise GenerationContractError("CSV row-offset artifact is truncated")
    magic, major, minor, record_size, count, source_size, digest = (
        _OFFSET_HEADER.unpack_from(data)
    )
    if (
        magic != _OFFSET_MAGIC
        or major != CSV_GENERATION_FORMAT_VERSION
        or minor != 0
        or record_size != _U64.size
    ):
        raise GenerationContractError(
            "CSV row-offset header is noncanonical",
            fault=GenerationFault.NONCANONICAL,
        )
    expected_size = _OFFSET_HEADER.size + count * _U64.size
    if len(data) != expected_size:
        raise GenerationContractError(
            "CSV row-offset length does not match its count",
            fault=GenerationFault.NONCANONICAL,
        )
    offsets = tuple(
        _U64.unpack_from(data, _OFFSET_HEADER.size + index * _U64.size)[0]
        for index in range(count)
    )
    source_root = _digest_root(digest)
    canonical = pack_row_offsets(
        offsets,
        source_size=source_size,
        source_root=source_root,
    )
    if canonical != data:
        raise GenerationContractError(
            "CSV row-offset artifact is noncanonical",
            fault=GenerationFault.NONCANONICAL,
        )
    return count, source_size, source_root, offsets


def _select_anchor_indices(row_count: int, anchor_limit: int) -> tuple[int, ...]:
    if row_count == 0:
        return ()
    count = min(row_count, anchor_limit)
    if count == row_count:
        return tuple(range(row_count))
    if count == 1:
        return (0,)
    return tuple(
        (index * (row_count - 1)) // (count - 1) for index in range(count)
    )


def _build_row_anchors(
    source: bytes,
    offsets: Sequence[int],
    *,
    anchor_limit: int,
) -> tuple[CSVRowAnchor, ...]:
    indices = _select_anchor_indices(len(offsets), anchor_limit)
    result: list[CSVRowAnchor] = []
    for ordinal in indices:
        start = offsets[ordinal]
        end = offsets[ordinal + 1] if ordinal + 1 < len(offsets) else len(source)
        result.append(
            CSVRowAnchor(
                row_ordinal=ordinal,
                start_offset=start,
                end_offset=end,
                content_root=bytes_root(source[start:end]),
            )
        )
    return tuple(result)


def pack_row_anchors(
    anchors: Sequence[CSVRowAnchor],
    *,
    row_count: int,
    source_size: int,
    source_root: str,
    offsets_root: str,
) -> bytes:
    """Pack a bounded, source- and offset-bound deterministic anchor sample."""

    _require_int("row_count", row_count, 0, _UINT63_MAX)
    _require_int("source_size", source_size, 0, _UINT63_MAX)
    source_digest = _root_digest("source_root", source_root)
    offsets_digest = _root_digest("offsets_root", offsets_root)
    normalized = tuple(anchors)
    if row_count > 0 and not normalized:
        raise GenerationContractError(
            "non-empty row set requires at least one bounded anchor",
            fault=GenerationFault.INCOMPLETE_GENERATION,
        )
    if len(normalized) > row_count:
        raise GenerationContractError(
            "anchor count exceeds row count",
            fault=GenerationFault.NONCANONICAL,
        )
    previous_ordinal = -1
    previous_start = -1
    records: list[bytes] = []
    for anchor in normalized:
        if not isinstance(anchor, CSVRowAnchor):
            raise GenerationContractError("anchors must be CSVRowAnchor values")
        if (
            anchor.row_ordinal <= previous_ordinal
            or anchor.start_offset <= previous_start
            or anchor.row_ordinal >= row_count
            or anchor.end_offset > source_size
        ):
            raise GenerationContractError(
                "CSV anchors are not ordered within the source",
                fault=GenerationFault.NONCANONICAL,
            )
        records.append(
            _ANCHOR_RECORD.pack(
                anchor.row_ordinal,
                anchor.start_offset,
                anchor.end_offset,
                _root_digest("anchor content_root", anchor.content_root),
            )
        )
        previous_ordinal = anchor.row_ordinal
        previous_start = anchor.start_offset
    if row_count == 0 and (source_size != 0 or normalized):
        raise GenerationContractError(
            "empty row set has one canonical anchor representation",
            fault=GenerationFault.NONCANONICAL,
        )
    header = _ANCHOR_HEADER.pack(
        _ANCHOR_MAGIC,
        CSV_GENERATION_FORMAT_VERSION,
        0,
        _ANCHOR_RECORD.size,
        row_count,
        len(normalized),
        source_size,
        source_digest,
        offsets_digest,
    )
    return header + b"".join(records)


def decode_row_anchors(
    data: bytes,
) -> tuple[int, int, str, str, tuple[CSVRowAnchor, ...]]:
    """Decode and reject any noncanonical packed row-anchor artifact."""

    if not isinstance(data, bytes) or len(data) < _ANCHOR_HEADER.size:
        raise GenerationContractError("CSV row-anchor artifact is truncated")
    values = _ANCHOR_HEADER.unpack_from(data)
    (
        magic,
        major,
        minor,
        record_size,
        row_count,
        anchor_count,
        source_size,
        source_digest,
        offsets_digest,
    ) = values
    if (
        magic != _ANCHOR_MAGIC
        or major != CSV_GENERATION_FORMAT_VERSION
        or minor != 0
        or record_size != _ANCHOR_RECORD.size
    ):
        raise GenerationContractError(
            "CSV row-anchor header is noncanonical",
            fault=GenerationFault.NONCANONICAL,
        )
    expected_size = _ANCHOR_HEADER.size + anchor_count * _ANCHOR_RECORD.size
    if len(data) != expected_size:
        raise GenerationContractError(
            "CSV row-anchor length does not match its count",
            fault=GenerationFault.NONCANONICAL,
        )
    anchors: list[CSVRowAnchor] = []
    for index in range(anchor_count):
        ordinal, start, end, digest = _ANCHOR_RECORD.unpack_from(
            data,
            _ANCHOR_HEADER.size + index * _ANCHOR_RECORD.size,
        )
        anchors.append(
            CSVRowAnchor(
                row_ordinal=ordinal,
                start_offset=start,
                end_offset=end,
                content_root=_digest_root(digest),
            )
        )
    source_root = _digest_root(source_digest)
    offsets_root = _digest_root(offsets_digest)
    canonical = pack_row_anchors(
        anchors,
        row_count=row_count,
        source_size=source_size,
        source_root=source_root,
        offsets_root=offsets_root,
    )
    if canonical != data:
        raise GenerationContractError(
            "CSV row-anchor artifact is noncanonical",
            fault=GenerationFault.NONCANONICAL,
        )
    return row_count, source_size, source_root, offsets_root, tuple(anchors)


@dataclass(frozen=True, slots=True)
class CSVChunkIdentity:
    ordinal: int
    payload_name: str
    start_offset: int
    end_offset: int
    content_root: str

    def __post_init__(self) -> None:
        _require_int("chunk ordinal", self.ordinal, 0, _UINT32_MAX)
        if (
            not isinstance(self.payload_name, str)
            or not _NAME_RE.fullmatch(self.payload_name)
            or not self.payload_name.startswith(CSV_CHUNK_PAYLOAD_PREFIX)
        ):
            raise GenerationContractError("chunk payload name is not canonical")
        _require_int("chunk start_offset", self.start_offset, 0, _UINT63_MAX)
        _require_int("chunk end_offset", self.end_offset, 1, _UINT63_MAX)
        if self.end_offset <= self.start_offset:
            raise GenerationContractError(
                "chunk spans must be non-empty",
                fault=GenerationFault.NONCANONICAL,
            )
        _required_root("chunk content_root", self.content_root)

    def canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CSVChunkIdentity":
        if set(value) != {
            "ordinal",
            "payload_name",
            "start_offset",
            "end_offset",
            "content_root",
        }:
            raise GenerationContractError(
                "chunk identity fields are not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        return cls(
            ordinal=value["ordinal"],
            payload_name=value["payload_name"],
            start_offset=value["start_offset"],
            end_offset=value["end_offset"],
            content_root=value["content_root"],
        )


@dataclass(frozen=True, slots=True)
class CSVChunkIndex:
    source_root: str
    source_size: int
    chunk_bytes: int
    chunks: tuple[CSVChunkIdentity, ...]

    def __post_init__(self) -> None:
        _required_root("chunk index source_root", self.source_root)
        _require_int("chunk index source_size", self.source_size, 0, _UINT63_MAX)
        _require_int("chunk_bytes", self.chunk_bytes, 1, _UINT32_MAX)
        if not isinstance(self.chunks, tuple):
            raise GenerationContractError("chunks must be a tuple")
        expected_start = 0
        for ordinal, chunk in enumerate(self.chunks):
            if not isinstance(chunk, CSVChunkIdentity):
                raise GenerationContractError(
                    "chunk index entries must be CSVChunkIdentity values"
                )
            expected_name = f"{CSV_CHUNK_PAYLOAD_PREFIX}{ordinal:08d}"
            if (
                chunk.ordinal != ordinal
                or chunk.payload_name != expected_name
                or chunk.start_offset != expected_start
                or chunk.end_offset - chunk.start_offset > self.chunk_bytes
            ):
                raise GenerationContractError(
                    "chunk identities are not canonical and contiguous",
                    fault=GenerationFault.NONCANONICAL,
                )
            if ordinal + 1 < len(self.chunks):
                if chunk.end_offset - chunk.start_offset != self.chunk_bytes:
                    raise GenerationContractError(
                        "only the final CSV chunk may be short",
                        fault=GenerationFault.NONCANONICAL,
                    )
            expected_start = chunk.end_offset
        if expected_start != self.source_size:
            raise GenerationContractError(
                "chunks do not cover the authoritative source extent",
                fault=GenerationFault.INCOMPLETE_GENERATION,
            )
        if self.source_size == 0 and self.chunks:
            raise GenerationContractError(
                "empty source has one no-chunk representation",
                fault=GenerationFault.NONCANONICAL,
            )
        if self.source_size != 0 and not self.chunks:
            raise GenerationContractError(
                "non-empty source requires chunks",
                fault=GenerationFault.INCOMPLETE_GENERATION,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_GENERATION_CONTRACT_ID,
            "format_version": CSV_GENERATION_FORMAT_VERSION,
            "source_root": self.source_root,
            "source_size": self.source_size,
            "chunk_bytes": self.chunk_bytes,
            "chunks": [chunk.canonical_dict() for chunk in self.chunks],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @property
    def chunks_root(self) -> str:
        return bytes_root(self.canonical_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "CSVChunkIndex":
        value = _canonical_object(data, "CSV chunk index")
        if set(value) != {
            "contract_id",
            "format_version",
            "source_root",
            "source_size",
            "chunk_bytes",
            "chunks",
        }:
            raise GenerationContractError(
                "CSV chunk-index fields are not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        if (
            value["contract_id"] != CSV_GENERATION_CONTRACT_ID
            or value["format_version"] != CSV_GENERATION_FORMAT_VERSION
            or not isinstance(value["chunks"], list)
        ):
            raise GenerationContractError("CSV chunk-index contract mismatch")
        result = cls(
            source_root=value["source_root"],
            source_size=value["source_size"],
            chunk_bytes=value["chunk_bytes"],
            chunks=tuple(CSVChunkIdentity.from_dict(item) for item in value["chunks"]),
        )
        if result.canonical_bytes() != data:
            raise GenerationContractError(
                "CSV chunk index is not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        return result


@dataclass(frozen=True, slots=True)
class CSVGenerationBinding:
    """All inputs and evidence that must belong to one CSV generation."""

    namespace: str
    parent_generation_root: str | None
    source_root: str
    source_size: int
    chunks_root: str
    chunk_count: int
    chunk_bytes: int
    parser_root: str
    dialect_root: str
    row_offsets_root: str
    row_count: int
    row_anchors_root: str
    anchor_count: int
    anchor_limit: int
    closure_root: str
    evidence_root: str
    contract_id: str = CSV_GENERATION_CONTRACT_ID
    format_version: int = CSV_GENERATION_FORMAT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not _NAME_RE.fullmatch(self.namespace):
            raise GenerationContractError("CSV binding namespace is not canonical")
        _optional_root("parent_generation_root", self.parent_generation_root)
        for name in (
            "source_root",
            "chunks_root",
            "parser_root",
            "dialect_root",
            "row_offsets_root",
            "row_anchors_root",
            "closure_root",
            "evidence_root",
        ):
            _required_root(name, getattr(self, name))
        _require_int("source_size", self.source_size, 0, _UINT63_MAX)
        _require_int("chunk_count", self.chunk_count, 0, _UINT32_MAX)
        _require_int("chunk_bytes", self.chunk_bytes, 1, _UINT32_MAX)
        _require_int("row_count", self.row_count, 0, _UINT63_MAX)
        _require_int("anchor_count", self.anchor_count, 0, _UINT32_MAX)
        _require_int("anchor_limit", self.anchor_limit, 1, _UINT32_MAX)
        expected_chunks = (
            (self.source_size + self.chunk_bytes - 1) // self.chunk_bytes
            if self.source_size
            else 0
        )
        if self.chunk_count != expected_chunks:
            raise GenerationContractError(
                "CSV binding chunk count is not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        if (self.source_size == 0) != (self.row_count == 0):
            raise GenerationContractError(
                "CSV binding row count does not match its source extent",
                fault=GenerationFault.NONCANONICAL,
            )
        if self.anchor_count != min(self.row_count, self.anchor_limit):
            raise GenerationContractError(
                "CSV binding anchor count is not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        if self.contract_id != CSV_GENERATION_CONTRACT_ID:
            raise GenerationContractError("unsupported CSV generation contract")
        if self.format_version != CSV_GENERATION_FORMAT_VERSION:
            raise GenerationContractError("unsupported CSV generation format")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "format_version": self.format_version,
            "namespace": self.namespace,
            "parent_generation_root": self.parent_generation_root,
            "source_root": self.source_root,
            "source_size": self.source_size,
            "chunks_root": self.chunks_root,
            "chunk_count": self.chunk_count,
            "chunk_bytes": self.chunk_bytes,
            "parser_root": self.parser_root,
            "dialect_root": self.dialect_root,
            "row_offsets_root": self.row_offsets_root,
            "row_count": self.row_count,
            "row_anchors_root": self.row_anchors_root,
            "anchor_count": self.anchor_count,
            "anchor_limit": self.anchor_limit,
            "closure_root": self.closure_root,
            "evidence_root": self.evidence_root,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @property
    def binding_root(self) -> str:
        return bytes_root(self.canonical_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "CSVGenerationBinding":
        value = _canonical_object(data, "CSV generation binding")
        expected = {
            "contract_id",
            "format_version",
            "namespace",
            "parent_generation_root",
            "source_root",
            "source_size",
            "chunks_root",
            "chunk_count",
            "chunk_bytes",
            "parser_root",
            "dialect_root",
            "row_offsets_root",
            "row_count",
            "row_anchors_root",
            "anchor_count",
            "anchor_limit",
            "closure_root",
            "evidence_root",
        }
        if set(value) != expected:
            raise GenerationContractError(
                "CSV generation-binding fields are not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        result = cls(**dict(value))
        if result.canonical_bytes() != data:
            raise GenerationContractError(
                "CSV generation binding is not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        return result


def _build_chunk_index(source: bytes, chunk_bytes: int) -> CSVChunkIndex:
    chunks: list[CSVChunkIdentity] = []
    for ordinal, start in enumerate(range(0, len(source), chunk_bytes)):
        end = min(start + chunk_bytes, len(source))
        raw = source[start:end]
        chunks.append(
            CSVChunkIdentity(
                ordinal=ordinal,
                payload_name=f"{CSV_CHUNK_PAYLOAD_PREFIX}{ordinal:08d}",
                start_offset=start,
                end_offset=end,
                content_root=bytes_root(raw),
            )
        )
    return CSVChunkIndex(
        source_root=bytes_root(source),
        source_size=len(source),
        chunk_bytes=chunk_bytes,
        chunks=tuple(chunks),
    )


def _qualification_roots(binding: CSVGenerationBinding) -> dict[str, str]:
    return {
        CSV_BINDING_PAYLOAD: binding.binding_root,
        CSV_CHUNKS_PAYLOAD: binding.chunks_root,
        "csv.closure": binding.closure_root,
        CSV_DIALECT_PAYLOAD: binding.dialect_root,
        "csv.evidence": binding.evidence_root,
        CSV_PARSER_PAYLOAD: binding.parser_root,
        CSV_ROW_ANCHORS_PAYLOAD: binding.row_anchors_root,
        CSV_ROW_OFFSETS_PAYLOAD: binding.row_offsets_root,
        CSV_SOURCE_PAYLOAD: binding.source_root,
    }


def build_csv_generation_candidate(
    store: AtomicGenerationStore,
    *,
    namespace: str,
    source: bytes,
    closure_root: str,
    evidence_root: str,
    parent_generation_root: str | None = None,
    dialect: CSVDialect | None = None,
    chunk_bytes: int = 64 << 10,
    oracle_block_bytes: int = 64 << 10,
    limits: CSVGenerationLimits = DEFAULT_CSV_GENERATION_LIMITS,
    metadata: Mapping[str, str] | None = None,
) -> GenerationCandidate:
    """Build one complete CSV candidate exclusively through ``store``."""

    if not isinstance(store, AtomicGenerationStore):
        raise GenerationContractError("store must be an AtomicGenerationStore")
    if not isinstance(source, bytes):
        raise GenerationContractError("authoritative CSV source must be exact bytes")
    if not isinstance(limits, CSVGenerationLimits):
        raise GenerationContractError("limits must be CSVGenerationLimits")
    _required_root("closure_root", closure_root)
    _required_root("evidence_root", evidence_root)
    _optional_root("parent_generation_root", parent_generation_root)
    _require_int("chunk_bytes", chunk_bytes, 1, limits.max_chunk_bytes)
    _require_int("oracle_block_bytes", oracle_block_bytes, 1, _UINT32_MAX)
    if len(source) > limits.max_source_bytes:
        raise GenerationContractError(
            "CSV source exceeds its qualified byte bound",
            fault=GenerationFault.BOUND_EXCEEDED,
        )

    selected_dialect = dialect or CSVDialect()
    if not isinstance(selected_dialect, CSVDialect):
        raise GenerationContractError("dialect must be a CSVDialect")
    oracle = CSVRowBoundaryOracle(selected_dialect)
    for start in range(0, len(source), oracle_block_bytes):
        oracle.feed(source[start : start + oracle_block_bytes])
    offsets = oracle.finalize()
    if oracle.bytes_consumed != len(source):
        raise GenerationContractError(
            "CSV oracle did not consume the authoritative source extent",
            fault=GenerationFault.INTEGRITY_FAILURE,
        )
    if len(offsets) > limits.max_rows:
        raise GenerationContractError(
            "CSV row count exceeds its qualified bound",
            fault=GenerationFault.BOUND_EXCEEDED,
        )

    source_root = bytes_root(source)
    chunk_index = _build_chunk_index(source, chunk_bytes)
    if len(chunk_index.chunks) > limits.max_chunks:
        raise GenerationContractError(
            "CSV chunk count exceeds its qualified bound",
            fault=GenerationFault.BOUND_EXCEEDED,
        )
    if len(chunk_index.chunks) + len(_CSV_FIXED_PAYLOADS) > store.limits.max_payloads:
        raise GenerationContractError(
            "CSV payload count exceeds the Generation Authority bound",
            fault=GenerationFault.BOUND_EXCEEDED,
        )

    offsets_data = pack_row_offsets(
        offsets,
        source_size=len(source),
        source_root=source_root,
    )
    offsets_root = bytes_root(offsets_data)
    anchors = _build_row_anchors(
        source,
        offsets,
        anchor_limit=limits.max_anchor_count,
    )
    anchors_data = pack_row_anchors(
        anchors,
        row_count=len(offsets),
        source_size=len(source),
        source_root=source_root,
        offsets_root=offsets_root,
    )
    chunk_index_data = chunk_index.canonical_bytes()
    dialect_data = selected_dialect.canonical_bytes()
    binding = CSVGenerationBinding(
        namespace=namespace,
        parent_generation_root=parent_generation_root,
        source_root=source_root,
        source_size=len(source),
        chunks_root=bytes_root(chunk_index_data),
        chunk_count=len(chunk_index.chunks),
        chunk_bytes=chunk_bytes,
        parser_root=CSV_REFERENCE_PARSER_ROOT,
        dialect_root=bytes_root(dialect_data),
        row_offsets_root=offsets_root,
        row_count=len(offsets),
        row_anchors_root=bytes_root(anchors_data),
        anchor_count=len(anchors),
        anchor_limit=limits.max_anchor_count,
        closure_root=closure_root,
        evidence_root=evidence_root,
    )

    payloads: dict[str, bytes] = {
        CSV_SOURCE_PAYLOAD: source,
        CSV_BINDING_PAYLOAD: binding.canonical_bytes(),
        CSV_CHUNKS_PAYLOAD: chunk_index_data,
        CSV_PARSER_PAYLOAD: CSV_REFERENCE_PARSER_BYTES,
        CSV_DIALECT_PAYLOAD: dialect_data,
        CSV_ROW_OFFSETS_PAYLOAD: offsets_data,
        CSV_ROW_ANCHORS_PAYLOAD: anchors_data,
    }
    media_types = {
        CSV_SOURCE_PAYLOAD: "text/csv",
        CSV_BINDING_PAYLOAD: "application/json",
        CSV_CHUNKS_PAYLOAD: "application/json",
        CSV_PARSER_PAYLOAD: "application/json",
        CSV_DIALECT_PAYLOAD: "application/json",
        CSV_ROW_OFFSETS_PAYLOAD: "application/octet-stream",
        CSV_ROW_ANCHORS_PAYLOAD: "application/octet-stream",
    }
    for chunk in chunk_index.chunks:
        payloads[chunk.payload_name] = source[chunk.start_offset : chunk.end_offset]
        media_types[chunk.payload_name] = "application/octet-stream"

    selected_metadata = dict(metadata or {})
    if selected_metadata.get("consumer", CSV_GENERATION_CONTRACT_ID) != (
        CSV_GENERATION_CONTRACT_ID
    ):
        raise GenerationContractError("CSV consumer metadata cannot be overridden")
    selected_metadata["consumer"] = CSV_GENERATION_CONTRACT_ID
    return store.build_candidate(
        namespace=namespace,
        payloads=payloads,
        media_types=media_types,
        authoritative_payload=CSV_SOURCE_PAYLOAD,
        parent_generation_root=parent_generation_root,
        qualifications=_qualification_roots(binding),
        metadata=selected_metadata,
    )


def publish_csv_generation(
    store: AtomicGenerationStore,
    candidate: GenerationCandidate,
    *,
    expected_head_root: str | None,
) -> PublicationResult:
    """Publish with the generic store's head-identity compare-and-swap."""

    _optional_root("expected_head_root", expected_head_root)
    return store.publish(candidate, expected_head_root=expected_head_root)


@dataclass(frozen=True, slots=True)
class LoadedCSVGeneration:
    generation_root: str
    namespace: str
    binding: CSVGenerationBinding
    source: bytes
    dialect: CSVDialect
    chunks: tuple[CSVChunkIdentity, ...]
    row_offsets: tuple[int, ...]
    row_anchors: tuple[CSVRowAnchor, ...]

    @property
    def row_count(self) -> int:
        return len(self.row_offsets)


def _payload_identity_map(lease: GenerationLease) -> dict[str, Any]:
    return {payload.name: payload for payload in lease.manifest.payloads}


def _require_payload_root(
    identities: Mapping[str, Any],
    name: str,
    expected_root: str,
) -> None:
    identity = identities.get(name)
    if identity is None or identity.content_root != expected_root:
        raise GenerationContractError(
            f"mixed generation binding: {name}",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )


def load_csv_generation(lease: GenerationLease) -> LoadedCSVGeneration:
    """Verify every CSV binding and reconstruct the exact source from chunks."""

    if not isinstance(lease, GenerationLease):
        raise GenerationContractError("lease must be a GenerationLease")
    identities = _payload_identity_map(lease)
    if not _CSV_FIXED_PAYLOADS.issubset(identities):
        raise GenerationContractError(
            "CSV generation is missing a required payload",
            fault=GenerationFault.INCOMPLETE_GENERATION,
        )
    authoritative = tuple(
        item.name for item in lease.manifest.payloads if item.authoritative
    )
    if authoritative != (CSV_SOURCE_PAYLOAD,):
        raise GenerationContractError(
            "CSV source is not the sole authoritative payload",
            fault=GenerationFault.AUTHORITY_REJECTED,
        )

    binding_data = lease.read_payload(CSV_BINDING_PAYLOAD)
    binding = CSVGenerationBinding.from_bytes(binding_data)
    if (
        binding.namespace != lease.namespace
        or binding.namespace != lease.manifest.namespace
        or binding.parent_generation_root
        != lease.manifest.parent_generation_root
    ):
        raise GenerationContractError(
            "CSV binding belongs to another generation lineage",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )

    _require_payload_root(identities, CSV_BINDING_PAYLOAD, binding.binding_root)
    _require_payload_root(identities, CSV_SOURCE_PAYLOAD, binding.source_root)
    _require_payload_root(identities, CSV_CHUNKS_PAYLOAD, binding.chunks_root)
    _require_payload_root(identities, CSV_PARSER_PAYLOAD, binding.parser_root)
    _require_payload_root(identities, CSV_DIALECT_PAYLOAD, binding.dialect_root)
    _require_payload_root(
        identities,
        CSV_ROW_OFFSETS_PAYLOAD,
        binding.row_offsets_root,
    )
    _require_payload_root(
        identities,
        CSV_ROW_ANCHORS_PAYLOAD,
        binding.row_anchors_root,
    )

    qualifications = {
        item.name: item.evidence_root for item in lease.manifest.qualifications
    }
    if qualifications != _qualification_roots(binding):
        raise GenerationContractError(
            "CSV qualification roots do not match the generation binding",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    metadata = dict(lease.manifest.metadata)
    if metadata.get("consumer") != CSV_GENERATION_CONTRACT_ID:
        raise GenerationContractError(
            "generation does not declare the CSV consumer contract",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )

    parser_data = lease.read_payload(CSV_PARSER_PAYLOAD)
    if parser_data != CSV_REFERENCE_PARSER_BYTES:
        raise GenerationContractError(
            "CSV parser payload is not the qualified reference contract",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    dialect_data = lease.read_payload(CSV_DIALECT_PAYLOAD)
    dialect = CSVDialect.from_bytes(dialect_data)

    chunk_index_data = lease.read_payload(CSV_CHUNKS_PAYLOAD)
    chunk_index = CSVChunkIndex.from_bytes(chunk_index_data)
    if (
        chunk_index.source_root != binding.source_root
        or chunk_index.source_size != binding.source_size
        or chunk_index.chunk_bytes != binding.chunk_bytes
        or len(chunk_index.chunks) != binding.chunk_count
    ):
        raise GenerationContractError(
            "CSV chunk identities do not match the generation binding",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    expected_payload_names = _CSV_FIXED_PAYLOADS | {
        chunk.payload_name for chunk in chunk_index.chunks
    }
    if set(identities) != expected_payload_names:
        raise GenerationContractError(
            "CSV generation payload set is not canonical",
            fault=GenerationFault.NONCANONICAL,
        )
    for chunk in chunk_index.chunks:
        _require_payload_root(identities, chunk.payload_name, chunk.content_root)

    reconstructed_parts: list[bytes] = []
    for chunk in chunk_index.chunks:
        raw = lease.read_payload(chunk.payload_name)
        if (
            len(raw) != chunk.end_offset - chunk.start_offset
            or bytes_root(raw) != chunk.content_root
        ):
            raise GenerationContractError(
                f"CSV chunk identity mismatch: {chunk.payload_name}",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        reconstructed_parts.append(raw)
    reconstructed = b"".join(reconstructed_parts)
    source = lease.read_payload(CSV_SOURCE_PAYLOAD)
    if (
        len(source) != binding.source_size
        or bytes_root(source) != binding.source_root
        or reconstructed != source
    ):
        raise GenerationContractError(
            "CSV chunks do not reconstruct the byte-identical source",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )

    offsets_data = lease.read_payload(CSV_ROW_OFFSETS_PAYLOAD)
    row_count, source_size, source_root, offsets = decode_row_offsets(offsets_data)
    if (
        row_count != binding.row_count
        or source_size != binding.source_size
        or source_root != binding.source_root
    ):
        raise GenerationContractError(
            "CSV row offsets do not match the generation binding",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    anchors_data = lease.read_payload(CSV_ROW_ANCHORS_PAYLOAD)
    (
        anchor_row_count,
        anchor_source_size,
        anchor_source_root,
        anchor_offsets_root,
        anchors,
    ) = decode_row_anchors(anchors_data)
    if (
        anchor_row_count != binding.row_count
        or anchor_source_size != binding.source_size
        or anchor_source_root != binding.source_root
        or anchor_offsets_root != binding.row_offsets_root
        or len(anchors) != binding.anchor_count
    ):
        raise GenerationContractError(
            "CSV row anchors do not match the generation binding",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )

    oracle = CSVRowBoundaryOracle(dialect)
    for start in range(0, len(source), max(1, min(binding.chunk_bytes, 64 << 10))):
        oracle.feed(source[start : start + min(binding.chunk_bytes, 64 << 10)])
    expected_offsets = oracle.finalize()
    if expected_offsets != offsets:
        raise GenerationContractError(
            "CSV row offsets fail the bound parser contract",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    expected_anchors = _build_row_anchors(
        source,
        offsets,
        anchor_limit=binding.anchor_limit,
    )
    if anchors != expected_anchors:
        raise GenerationContractError(
            "CSV row anchors fail exact source verification",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )

    return LoadedCSVGeneration(
        generation_root=lease.generation_root,
        namespace=lease.namespace,
        binding=binding,
        source=source,
        dialect=dialect,
        chunks=chunk_index.chunks,
        row_offsets=offsets,
        row_anchors=anchors,
    )


class CSVGenerationLease:
    """A verified CSV view that owns one generic generation pin."""

    def __init__(self, lease: GenerationLease) -> None:
        self._lease = lease
        try:
            self.loaded = load_csv_generation(lease)
        except BaseException:
            lease.close()
            raise

    @property
    def generation_root(self) -> str:
        return self.loaded.generation_root

    @property
    def binding(self) -> CSVGenerationBinding:
        return self.loaded.binding

    @property
    def row_offsets(self) -> tuple[int, ...]:
        return self.loaded.row_offsets

    @property
    def row_anchors(self) -> tuple[CSVRowAnchor, ...]:
        return self.loaded.row_anchors

    @property
    def closed(self) -> bool:
        return self._lease.closed

    def read_source(self) -> bytes:
        if self.closed:
            raise GenerationContractError("CSV generation lease is closed")
        return self.loaded.source

    def close(self) -> None:
        self._lease.close()

    def __enter__(self) -> "CSVGenerationLease":
        if self.closed:
            raise GenerationContractError("CSV generation lease is closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def open_csv_generation(
    store: AtomicGenerationStore,
    namespace: str,
    generation_root: str | None = None,
) -> CSVGenerationLease:
    """Pin and fully verify one current or explicitly selected CSV generation."""

    lease = store.pin(namespace, generation_root)
    return CSVGenerationLease(lease)


__all__ = [
    "CSV_BINDING_PAYLOAD",
    "CSV_CHUNKS_PAYLOAD",
    "CSV_CHUNK_PAYLOAD_PREFIX",
    "CSV_DIALECT_PAYLOAD",
    "CSV_GENERATION_CONTRACT_ID",
    "CSV_GENERATION_FORMAT_VERSION",
    "CSV_PARSER_PAYLOAD",
    "CSV_REFERENCE_PARSER",
    "CSV_REFERENCE_PARSER_BYTES",
    "CSV_REFERENCE_PARSER_ID",
    "CSV_REFERENCE_PARSER_ROOT",
    "CSV_ROW_ANCHORS_PAYLOAD",
    "CSV_ROW_OFFSETS_PAYLOAD",
    "CSV_SOURCE_PAYLOAD",
    "CSVChunkIdentity",
    "CSVChunkIndex",
    "CSVDialect",
    "CSVGenerationBinding",
    "CSVGenerationLease",
    "CSVGenerationLimits",
    "CSVParserContract",
    "CSVRowAnchor",
    "CSVRowBoundaryOracle",
    "DEFAULT_CSV_GENERATION_LIMITS",
    "LoadedCSVGeneration",
    "build_csv_generation_candidate",
    "decode_row_anchors",
    "decode_row_offsets",
    "load_csv_generation",
    "open_csv_generation",
    "pack_row_anchors",
    "pack_row_offsets",
    "publish_csv_generation",
]

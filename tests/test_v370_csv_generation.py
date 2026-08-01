from __future__ import annotations

from pathlib import Path

import pytest

from staqtapp_tds.generation.csv import (
    CSV_BINDING_PAYLOAD,
    CSV_CHUNKS_PAYLOAD,
    CSV_ROW_ANCHORS_PAYLOAD,
    CSV_ROW_OFFSETS_PAYLOAD,
    CSV_SOURCE_PAYLOAD,
    CSVChunkIndex,
    CSVDialect,
    CSVGenerationBinding,
    CSVGenerationLimits,
    CSVRowBoundaryOracle,
    build_csv_generation_candidate,
    decode_row_anchors,
    decode_row_offsets,
    open_csv_generation,
    publish_csv_generation,
)
from staqtapp_tds.generation.generation_contract import (
    GenerationContractError,
    GenerationFault,
    bytes_root,
)
from staqtapp_tds.generation.generation_store import AtomicGenerationStore


def _root(label: str) -> str:
    return bytes_root(label.encode("ascii"))


def _rows() -> tuple[bytes, ...]:
    return (
        b"\xef\xbb\xbfid,text\r\n",
        b'1,"line one\r\nline two"\r\n',
        b'2,"quote ""inside"""\n',
        b'3,"embedded\rcarriage"\r',
        b"4,opaque-\xff",
    )


def _fixture() -> bytes:
    return b"".join(_rows())


def _expected_offsets() -> tuple[int, ...]:
    starts: list[int] = []
    position = 0
    for row in _rows():
        starts.append(position)
        position += len(row)
    return tuple(starts)


def test_row_boundary_oracle_is_identical_at_every_input_split() -> None:
    source = _fixture()
    expected = _expected_offsets()
    for split in range(len(source) + 1):
        oracle = CSVRowBoundaryOracle()
        oracle.feed(source[:split])
        oracle.feed(source[split:])
        assert oracle.finalize() == expected
        assert oracle.bytes_consumed == len(source)

    bytewise = CSVRowBoundaryOracle()
    for byte in source:
        bytewise.feed(bytes((byte,)))
    assert bytewise.finalize() == expected


def test_row_boundary_oracle_retains_escape_and_quote_state_across_splits() -> None:
    dialect = CSVDialect(escape=ord("\\"))
    source = b'id,value\r\n1,"escaped \\" quote\r\ninside"\r\n2,done'
    expected = (0, 10, 40)
    for split in range(len(source) + 1):
        oracle = CSVRowBoundaryOracle(dialect)
        oracle.feed(source[:split])
        oracle.feed(source[split:])
        assert oracle.finalize() == expected

    unterminated = CSVRowBoundaryOracle()
    unterminated.feed(b'id,value\n1,"open')
    with pytest.raises(GenerationContractError) as incomplete:
        unterminated.finalize()
    assert incomplete.value.fault is GenerationFault.INCOMPLETE_GENERATION

    invalid = CSVRowBoundaryOracle()
    with pytest.raises(GenerationContractError) as noncanonical:
        invalid.feed(b'id,value\n1,"closed"x\n')
    assert noncanonical.value.fault is GenerationFault.NONCANONICAL


def test_csv_candidate_uses_generic_store_and_round_trips_exact_source(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    source = _fixture()
    candidate = build_csv_generation_candidate(
        store,
        namespace="dataset:split-oracle",
        source=source,
        closure_root=_root("closure"),
        evidence_root=_root("evidence"),
        chunk_bytes=7,
        oracle_block_bytes=3,
        limits=CSVGenerationLimits(
            max_source_bytes=4096,
            max_chunk_bytes=64,
            max_chunks=256,
            max_rows=256,
            max_anchor_count=3,
        ),
    )
    payloads = candidate.payload_map()
    assert payloads[CSV_SOURCE_PAYLOAD] == source
    assert bytes_root(payloads[CSV_SOURCE_PAYLOAD]) == next(
        item.content_root
        for item in candidate.manifest.payloads
        if item.name == CSV_SOURCE_PAYLOAD and item.authoritative
    )

    binding = CSVGenerationBinding.from_bytes(payloads[CSV_BINDING_PAYLOAD])
    chunks = CSVChunkIndex.from_bytes(payloads[CSV_CHUNKS_PAYLOAD])
    assert binding.chunk_count == len(chunks.chunks) == (len(source) + 6) // 7
    assert b"".join(payloads[item.payload_name] for item in chunks.chunks) == source

    result = publish_csv_generation(store, candidate, expected_head_root=None)
    assert result.manifest.generation_root == candidate.generation_root
    with open_csv_generation(store, "dataset:split-oracle") as lease:
        assert lease.generation_root == candidate.generation_root
        assert lease.read_source() == source
        assert lease.row_offsets == _expected_offsets()
        assert tuple(item.row_ordinal for item in lease.row_anchors) == (0, 2, 4)
        assert lease.binding.closure_root == _root("closure")
        assert lease.binding.evidence_root == _root("evidence")
    assert store.pin_count(candidate.generation_root) == 0


def test_offsets_and_bounded_anchors_are_canonical_and_source_bound(
    tmp_path: Path,
) -> None:
    source = b"".join(f"{index},value\r\n".encode("ascii") for index in range(20))
    store = AtomicGenerationStore(tmp_path / "packed")
    candidate = build_csv_generation_candidate(
        store,
        namespace="dataset:packed",
        source=source,
        closure_root=_root("packed-closure"),
        evidence_root=_root("packed-evidence"),
        chunk_bytes=11,
        oracle_block_bytes=1,
        limits=CSVGenerationLimits(
            max_source_bytes=4096,
            max_chunk_bytes=32,
            max_chunks=512,
            max_rows=64,
            max_anchor_count=4,
        ),
    )
    payloads = candidate.payload_map()
    offset_data = payloads[CSV_ROW_OFFSETS_PAYLOAD]
    anchor_data = payloads[CSV_ROW_ANCHORS_PAYLOAD]
    count, extent, source_root, offsets = decode_row_offsets(offset_data)
    anchor_rows, anchor_extent, anchor_source, offsets_root, anchors = (
        decode_row_anchors(anchor_data)
    )
    assert count == anchor_rows == 20
    assert extent == anchor_extent == len(source)
    assert source_root == anchor_source == bytes_root(source)
    assert offsets_root == bytes_root(offset_data)
    assert tuple(item.row_ordinal for item in anchors) == (0, 6, 12, 19)
    assert tuple(offsets[item.row_ordinal] for item in anchors) == tuple(
        item.start_offset for item in anchors
    )

    with pytest.raises(GenerationContractError) as trailing:
        decode_row_offsets(offset_data + b"\x00")
    assert trailing.value.fault is GenerationFault.NONCANONICAL
    with pytest.raises(GenerationContractError) as magic:
        decode_row_anchors(b"BADMAGIC" + anchor_data[8:])
    assert magic.value.fault is GenerationFault.NONCANONICAL


def test_pinned_csv_reader_stays_on_old_generation(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "pins")
    namespace = "dataset:pins"
    first_source = b"id,value\n1,old\n"
    first = build_csv_generation_candidate(
        store,
        namespace=namespace,
        source=first_source,
        closure_root=_root("first-closure"),
        evidence_root=_root("first-evidence"),
        chunk_bytes=4,
    )
    first_result = publish_csv_generation(store, first, expected_head_root=None)
    pinned = open_csv_generation(store, namespace)

    second_source = b"id,value\n1,new\n2,complete\n"
    second = build_csv_generation_candidate(
        store,
        namespace=namespace,
        source=second_source,
        closure_root=_root("second-closure"),
        evidence_root=_root("second-evidence"),
        parent_generation_root=first_result.head.generation_root,
        chunk_bytes=4,
    )
    publish_csv_generation(
        store,
        second,
        expected_head_root=first_result.head.head_root,
    )
    assert pinned.read_source() == first_source
    with open_csv_generation(store, namespace) as current:
        assert current.read_source() == second_source
        assert current.generation_root == second.generation_root
    pinned.close()


def test_mixed_generation_binding_is_rejected_on_lease_load(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "mixed")
    namespace = "dataset:mixed"
    first = build_csv_generation_candidate(
        store,
        namespace=namespace,
        source=b"id,value\n1,first\n",
        closure_root=_root("first-closure"),
        evidence_root=_root("first-evidence"),
        chunk_bytes=5,
    )
    second = build_csv_generation_candidate(
        store,
        namespace=namespace,
        source=b"id,value\n1,second\n",
        closure_root=_root("second-closure"),
        evidence_root=_root("second-evidence"),
        chunk_bytes=5,
    )
    mixed_payloads = first.payload_map()
    mixed_payloads[CSV_BINDING_PAYLOAD] = second.payload_map()[CSV_BINDING_PAYLOAD]
    mixed = store.build_candidate(
        namespace=namespace,
        payloads=mixed_payloads,
        media_types={item.name: item.media_type for item in first.manifest.payloads},
        authoritative_payload=CSV_SOURCE_PAYLOAD,
        qualifications={
            item.name: item.evidence_root for item in first.manifest.qualifications
        },
        metadata=dict(first.manifest.metadata),
    )
    publish_csv_generation(store, mixed, expected_head_root=None)
    with pytest.raises(GenerationContractError) as mismatch:
        open_csv_generation(store, namespace)
    assert mismatch.value.fault is GenerationFault.IDENTITY_MISMATCH
    assert store.pin_count(mixed.generation_root) == 0


def test_empty_source_and_exact_bytes_input_contract(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "empty")
    candidate = build_csv_generation_candidate(
        store,
        namespace="dataset:empty",
        source=b"",
        closure_root=_root("empty-closure"),
        evidence_root=_root("empty-evidence"),
        chunk_bytes=4,
    )
    binding = CSVGenerationBinding.from_bytes(
        candidate.payload_map()[CSV_BINDING_PAYLOAD]
    )
    assert binding.source_size == binding.row_count == binding.chunk_count == 0
    publish_csv_generation(store, candidate, expected_head_root=None)
    with open_csv_generation(store, "dataset:empty") as lease:
        assert lease.read_source() == b""
        assert lease.row_offsets == ()
        assert lease.row_anchors == ()

    with pytest.raises(GenerationContractError, match="exact bytes"):
        build_csv_generation_candidate(
            AtomicGenerationStore(tmp_path / "mutable"),
            namespace="dataset:mutable",
            source=bytearray(b"mutable"),  # type: ignore[arg-type]
            closure_root=_root("mutable-closure"),
            evidence_root=_root("mutable-evidence"),
        )

from __future__ import annotations

import copy
import hashlib
import pickle
import struct
import zlib
from dataclasses import asdict, fields, replace

import pytest
import staqtapp_tds.trace_rank.graph as packed_graph_module

from staqtapp_tds.trace_rank.graph import (
    CSR_OFFSET_RECORD_SIZE,
    EDGE_RECORD_SIZE,
    FEATURE_RECORD_SIZE,
    GENERATION_RECORD_SIZE,
    HEADER_SIZE,
    PACKED_GRAPH_ABI_VERSION,
    PACKED_GRAPH_CHECKSUM_ALGORITHM,
    PACKED_GRAPH_CHECKSUM_ALGORITHM_ID,
    PACKED_GRAPH_ENDIANNESS,
    PACKED_GRAPH_ENDIANNESS_ID,
    PACKED_GRAPH_FORMAT_ID,
    PACKED_GRAPH_FORMAT_VERSION,
    PACKED_GRAPH_HASH_ALGORITHM,
    PACKED_GRAPH_HASH_ALGORITHM_ID,
    PACKED_GRAPH_MAGIC,
    PACKED_GRAPH_QUANTIZATION,
    PACKED_GRAPH_QUANTIZATION_ID,
    PROVENANCE_RECORD_SIZE,
    WAYPOINT_RECORD_SIZE,
    Edge,
    FeatureBlock,
    ImmutableSourceBinding,
    PackedGraphError,
    PackedGraphFault,
    PackedGraphLimits,
    PackedWaypointGraph,
    ProvenanceRecord,
    Waypoint,
)


def root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("ascii")).hexdigest()


def row_offsets(raw: bytes) -> tuple[int, ...]:
    result = [0]
    for line in raw.splitlines(keepends=True):
        result.append(result[-1] + len(line))
    return tuple(result)


def fixture_graph(
    *,
    two_features: bool = False,
    two_edges: bool = False,
) -> tuple[PackedWaypointGraph, tuple[ImmutableSourceBinding, ...]]:
    raw = b"id,name\n1,Ada\n2,Grace\n"
    offsets = row_offsets(raw)
    sources = (
        ImmutableSourceBinding(root("generation-a"), raw, offsets),
    )
    provenance = (
        ProvenanceRecord(
            root("provenance-a"),
            generation_index=0,
            privacy_class=2,
            license_class=1,
            policy_mask=0b0011,
        ),
    )
    first_feature = FeatureBlock(
        (1, 0),
        missing_mask=0b10,
        privacy_class=2,
    )
    features = (first_feature,)
    if two_features:
        features = (first_feature, FeatureBlock((2, 0), missing_mask=0b10, privacy_class=2))
    waypoints = (
        Waypoint(
            generation_index=0,
            causal_sequence=10,
            predecessor_index=-1,
            byte_start=offsets[0],
            byte_end=offsets[1],
            row_start=0,
            row_end=1,
            feature_index=0,
            provenance_index=0,
        ),
        Waypoint(
            generation_index=0,
            causal_sequence=20,
            predecessor_index=0,
            byte_start=offsets[1],
            byte_end=offsets[3],
            row_start=1,
            row_end=3,
            feature_index=int(two_features),
            provenance_index=0,
        ),
    )
    edges = (
        Edge(
            destination_index=1,
            operation=1,
            base_cost=100,
            learned_delta=7,
            evidence_gain=11,
            hard_eligibility_mask=0b0011,
        ),
    )
    edge_vector = (0, 1, 1)
    if two_edges:
        edges = (
            Edge(0, 1, 50, 2, 3, 0b0011),
            Edge(1, 1, 100, 7, 11, 0b0011),
        )
        edge_vector = (0, 2, 2)
    graph = PackedWaypointGraph.build(
        server_namespace_root=root("server-local-a"),
        feature_schema_root=root("feature-schema-q15-v1"),
        hard_mask_universe=0b0111,
        source_bindings=sources,
        provenance=provenance,
        feature_blocks=features,
        waypoints=waypoints,
        edge_offsets=edge_vector,
        edges=edges,
    )
    return graph, sources


def test_phase4_format_declares_exact_byte_contract_and_widths() -> None:
    graph, sources = fixture_graph()
    blob = graph.to_bytes(sources)
    descriptor = graph.format_descriptor

    assert descriptor == {
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
        "header_size": 256,
        "generation_record_size": 112,
        "provenance_record_size": 48,
        "feature_record_size": 144,
        "waypoint_record_size": 64,
        "csr_offset_record_size": 8,
        "edge_record_size": 40,
    }
    assert (
        HEADER_SIZE,
        GENERATION_RECORD_SIZE,
        PROVENANCE_RECORD_SIZE,
        FEATURE_RECORD_SIZE,
        WAYPOINT_RECORD_SIZE,
        CSR_OFFSET_RECORD_SIZE,
        EDGE_RECORD_SIZE,
    ) == (256, 112, 48, 144, 64, 8, 40)
    header_prefix = struct.unpack_from("<8sHHBBBB", blob)
    assert header_prefix == (
        PACKED_GRAPH_MAGIC,
        1,
        2,
        1,
        1,
        1,
        1,
    )


def test_build_is_byte_identical_and_decode_reencode_is_exact() -> None:
    first, sources = fixture_graph()
    second, second_sources = fixture_graph()

    first_blob = first.to_bytes(sources)
    second_blob = second.to_bytes(second_sources)
    assert first_blob == second_blob

    decoded = PackedWaypointGraph.from_bytes(first_blob, sources)
    assert decoded == first
    assert decoded.to_bytes(sources) == first_blob


def test_fixture_packed_bytes_retain_the_v380_golden_identity() -> None:
    graph, sources = fixture_graph()
    blob = graph.to_bytes(sources)

    assert len(blob) == 752
    assert hashlib.sha256(blob).hexdigest() == (
        "8375decdb4da0a5addb63320fc8cdc2adfc5f146bbbb2599d855966689f06f9f"
    )


def test_source_root_caches_do_not_change_the_public_dataclass_shape() -> None:
    _graph, sources = fixture_graph()
    source = sources[0]

    assert tuple(item.name for item in fields(source)) == (
        "generation_root",
        "source_bytes",
        "row_offsets",
    )
    assert set(asdict(source)) == {"generation_root", "source_bytes", "row_offsets"}


@pytest.mark.parametrize("copier", [copy.copy, copy.deepcopy, pickle.dumps])
def test_source_root_caches_survive_standard_copy_protocols(copier) -> None:
    _graph, sources = fixture_graph()
    source = sources[0]

    if copier is pickle.dumps:
        copied = pickle.loads(copier(source))
    else:
        copied = copier(source)

    assert copied == source
    assert copied.source_root == source.source_root
    assert copied.row_offsets_root == source.row_offsets_root


def test_waypoint_exactly_round_trips_authoritative_row_spans() -> None:
    graph, sources = fixture_graph()

    assert graph.materialize_waypoint(0, sources) == b"id,name\n"
    assert graph.materialize_waypoint(1, sources) == b"1,Ada\n2,Grace\n"
    assert graph.waypoints[1].byte_start == sources[0].row_offsets[1]
    assert graph.waypoints[1].byte_end == sources[0].row_offsets[3]


def test_source_bytes_and_row_boundaries_are_generation_authority() -> None:
    graph, sources = fixture_graph()
    blob = graph.to_bytes(sources)
    altered = (
        ImmutableSourceBinding(
            sources[0].generation_root,
            b"id,name\n1,Eve\n2,Grace\n",
            sources[0].row_offsets,
        ),
    )

    with pytest.raises(PackedGraphError) as error:
        PackedWaypointGraph.from_bytes(blob, altered)
    assert error.value.fault is PackedGraphFault.SOURCE_MISMATCH

    shifted = replace(graph.waypoints[0], byte_end=graph.waypoints[0].byte_end + 1)
    malformed = replace(graph, waypoints=(shifted, graph.waypoints[1]))
    with pytest.raises(PackedGraphError) as error:
        malformed.to_bytes(sources)
    assert error.value.fault is PackedGraphFault.SOURCE_MISMATCH


def test_reference_resolution_rejects_cross_generation_or_missing_records() -> None:
    graph, _sources = fixture_graph()

    with pytest.raises(PackedGraphError) as error:
        replace(
            graph,
            waypoints=(
                replace(graph.waypoints[0], feature_index=99),
                graph.waypoints[1],
            ),
        )
    assert error.value.fault is PackedGraphFault.REFERENCE_ERROR

    with pytest.raises(PackedGraphError) as error:
        replace(graph, edges=(replace(graph.edges[0], destination_index=99),))
    assert error.value.fault is PackedGraphFault.REFERENCE_ERROR

    with pytest.raises(PackedGraphError) as error:
        replace(
            graph,
            waypoints=(
                graph.waypoints[0],
                replace(graph.waypoints[1], predecessor_index=1),
            ),
        )
    assert error.value.fault is PackedGraphFault.REFERENCE_ERROR


def test_hard_masks_cannot_escape_or_weaken_provenance_policy() -> None:
    graph, _sources = fixture_graph()

    with pytest.raises(PackedGraphError) as error:
        replace(
            graph,
            edges=(replace(graph.edges[0], hard_eligibility_mask=0b1000),),
        )
    assert error.value.fault is PackedGraphFault.INTEGRITY_FAILURE

    with pytest.raises(PackedGraphError) as error:
        replace(
            graph,
            edges=(replace(graph.edges[0], hard_eligibility_mask=0b0001),),
        )
    assert error.value.fault is PackedGraphFault.INTEGRITY_FAILURE


def test_csr_shape_and_edge_order_are_canonical() -> None:
    graph, _sources = fixture_graph(two_edges=True)

    with pytest.raises(PackedGraphError):
        replace(graph, edge_offsets=(0, 2))
    with pytest.raises(PackedGraphError) as error:
        replace(graph, edge_offsets=(0, 2, 1))
    assert error.value.fault is PackedGraphFault.NONCANONICAL
    with pytest.raises(PackedGraphError) as error:
        replace(graph, edges=tuple(reversed(graph.edges)))
    assert error.value.fault is PackedGraphFault.NONCANONICAL


def test_generation_feature_and_source_table_order_is_rejected() -> None:
    graph, sources = fixture_graph(two_features=True)

    with pytest.raises(PackedGraphError) as error:
        replace(graph, feature_blocks=tuple(reversed(graph.feature_blocks)))
    assert error.value.fault is PackedGraphFault.NONCANONICAL

    with pytest.raises(PackedGraphError) as error:
        graph.to_bytes(list(sources))  # type: ignore[arg-type]
    assert error.value.fault is PackedGraphFault.INVALID_INPUT


def test_missing_features_have_one_canonical_zero_representation() -> None:
    assert FeatureBlock((12, 0), missing_mask=0b10)
    with pytest.raises(PackedGraphError) as error:
        FeatureBlock((12, 9), missing_mask=0b10)
    assert error.value.fault is PackedGraphFault.NONCANONICAL
    with pytest.raises(PackedGraphError):
        FeatureBlock((1,), missing_mask=0b10)


def test_learned_delta_is_bounded_non_negative() -> None:
    graph, sources = fixture_graph()
    maximum = replace(graph.edges[0], learned_delta=(1 << 32) - 1)
    rebuilt = replace(graph, edges=(maximum,))
    encoded = rebuilt.to_bytes(sources)
    decoded = PackedWaypointGraph.from_bytes(encoded, sources)
    assert decoded.edges[0].learned_delta == (1 << 32) - 1
    with pytest.raises(PackedGraphError):
        replace(graph.edges[0], learned_delta=-1)
    with pytest.raises(PackedGraphError):
        replace(graph.edges[0], learned_delta=1 << 32)


def test_feature_privacy_class_must_match_bound_provenance() -> None:
    graph, _sources = fixture_graph()
    with pytest.raises(PackedGraphError) as error:
        replace(
            graph,
            feature_blocks=(replace(graph.feature_blocks[0], privacy_class=1),),
        )
    assert error.value.fault is PackedGraphFault.INTEGRITY_FAILURE


def test_decode_rejects_truncation_trailing_bytes_and_corruption() -> None:
    graph, sources = fixture_graph()
    blob = graph.to_bytes(sources)

    for malformed in (blob[:-1], blob + b"\x00"):
        with pytest.raises(PackedGraphError) as error:
            PackedWaypointGraph.from_bytes(malformed, sources)
        assert error.value.fault is PackedGraphFault.INTEGRITY_FAILURE

    corrupted = bytearray(blob)
    corrupted[-1] ^= 0x01
    with pytest.raises(PackedGraphError) as error:
        PackedWaypointGraph.from_bytes(bytes(corrupted), sources)
    assert error.value.fault is PackedGraphFault.INTEGRITY_FAILURE


def _reseal_noncanonical_payload(payload: bytearray) -> bytes:
    values = packed_graph_module._HEADER.unpack_from(payload, 0)
    counts = tuple(values[18:23])
    offsets = tuple(values[23:29])
    zero_header = packed_graph_module._pack_header(
        total_size=values[16],
        hard_mask_universe=values[17],
        counts=counts,
        offsets=offsets,
        server_namespace_digest=values[29],
        feature_schema_digest=values[30],
    )
    material = zero_header + bytes(payload[HEADER_SIZE:])
    header = packed_graph_module._pack_header(
        total_size=values[16],
        hard_mask_universe=values[17],
        counts=counts,
        offsets=offsets,
        server_namespace_digest=values[29],
        feature_schema_digest=values[30],
        content_digest=hashlib.sha256(material).digest(),
        content_crc32=zlib.crc32(material) & ((1 << 32) - 1),
    )
    payload[:HEADER_SIZE] = header
    return bytes(payload)


@pytest.mark.parametrize(
    ("offset_index", "record_size"),
    (
        (26, WAYPOINT_RECORD_SIZE),
        (28, EDGE_RECORD_SIZE),
    ),
)
def test_decode_rejects_integrity_valid_nonzero_record_padding(
    offset_index: int,
    record_size: int,
) -> None:
    graph, sources = fixture_graph()
    malformed = bytearray(graph.to_bytes(sources))
    header = packed_graph_module._HEADER.unpack_from(malformed, 0)
    malformed[header[offset_index] + record_size - 1] = 1

    with pytest.raises(PackedGraphError) as error:
        PackedWaypointGraph.from_bytes(
            _reseal_noncanonical_payload(malformed),
            sources,
        )

    assert error.value.fault is PackedGraphFault.NONCANONICAL


def test_decode_still_rejects_integrity_valid_cross_record_ordering() -> None:
    graph, sources = fixture_graph()
    malformed = bytearray(graph.to_bytes(sources))
    header = packed_graph_module._HEADER.unpack_from(malformed, 0)
    waypoint_offset = header[26]
    first = bytes(malformed[waypoint_offset : waypoint_offset + WAYPOINT_RECORD_SIZE])
    second = bytes(
        malformed[
            waypoint_offset + WAYPOINT_RECORD_SIZE :
            waypoint_offset + 2 * WAYPOINT_RECORD_SIZE
        ]
    )
    malformed[waypoint_offset : waypoint_offset + WAYPOINT_RECORD_SIZE] = second
    malformed[
        waypoint_offset + WAYPOINT_RECORD_SIZE :
        waypoint_offset + 2 * WAYPOINT_RECORD_SIZE
    ] = first

    with pytest.raises(PackedGraphError) as error:
        PackedWaypointGraph.from_bytes(
            _reseal_noncanonical_payload(malformed),
            sources,
        )

    assert error.value.fault is PackedGraphFault.NONCANONICAL


def test_decode_still_rejects_integrity_valid_cross_record_reference() -> None:
    graph, sources = fixture_graph()
    malformed = bytearray(graph.to_bytes(sources))
    header = packed_graph_module._HEADER.unpack_from(malformed, 0)
    waypoint_offset = header[26]
    # feature_index is the first uint32 after the four uint64 spans.
    struct.pack_into("<I", malformed, waypoint_offset + 52, len(graph.feature_blocks))

    with pytest.raises(PackedGraphError) as error:
        PackedWaypointGraph.from_bytes(
            _reseal_noncanonical_payload(malformed),
            sources,
        )

    assert error.value.fault is PackedGraphFault.REFERENCE_ERROR


def test_decode_rejects_unknown_version_and_record_width_before_records() -> None:
    graph, sources = fixture_graph()
    blob = graph.to_bytes(sources)

    bad_version = bytearray(blob)
    struct.pack_into("<H", bad_version, 8, PACKED_GRAPH_FORMAT_VERSION + 1)
    with pytest.raises(PackedGraphError) as error:
        PackedWaypointGraph.from_bytes(bytes(bad_version), sources)
    assert error.value.fault is PackedGraphFault.UNSUPPORTED_FORMAT

    bad_width = bytearray(blob)
    # header_size begins after magic, two uint16 versions, and four identities.
    struct.pack_into("<H", bad_width, 16, HEADER_SIZE - 1)
    with pytest.raises(PackedGraphError) as error:
        PackedWaypointGraph.from_bytes(bytes(bad_width), sources)
    assert error.value.fault is PackedGraphFault.UNSUPPORTED_FORMAT


def test_qualified_count_and_memory_bounds_fail_before_serialization() -> None:
    graph, sources = fixture_graph()
    blob_size = len(graph.to_bytes(sources))

    with pytest.raises(PackedGraphError) as error:
        graph.to_bytes(sources, limits=PackedGraphLimits(max_edges=0))
    assert error.value.fault is PackedGraphFault.BOUND_EXCEEDED

    with pytest.raises(PackedGraphError) as error:
        graph.to_bytes(
            sources,
            limits=PackedGraphLimits(max_graph_bytes=blob_size - 1),
        )
    assert error.value.fault is PackedGraphFault.BOUND_EXCEEDED


def test_binary_surface_has_no_search_or_execution_authority() -> None:
    graph, _sources = fixture_graph()

    for command in ("search", "dijkstra", "execute", "commit"):
        assert not hasattr(graph, command)
        assert not hasattr(packed_graph_module, command)

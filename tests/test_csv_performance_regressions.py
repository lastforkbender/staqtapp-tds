from __future__ import annotations

import inspect

import pytest

from staqtapp_tds import TDSFileSystem
from staqtapp_tds.csv_layer import (
    export_canonical_csv,
    import_csv_bytes,
    load_csv_row_anchor_profile,
    materialize_csv_scan_artifacts,
    scan_csv_row_anchors,
    validate_materialized_csv_scan_artifacts,
)
from staqtapp_tds.csv_layer import manifest as manifest_module
from staqtapp_tds.csv_layer import scan_artifacts as scan_artifacts_module
from staqtapp_tds.csv_layer.semantic_ir import _duplicate_strings as ir_duplicates
from staqtapp_tds.csv_layer.semantic_ir_lifecycle_batch import (
    _duplicate_strings as batch_duplicates,
)
from staqtapp_tds.generation import csv as generation_csv
from staqtapp_tds.generation.csv import (
    CSV_CHUNKS_PAYLOAD,
    CSV_SOURCE_PAYLOAD,
    CSVChunkIndex,
    CSVGenerationLimits,
    build_csv_generation_candidate,
    open_csv_generation,
    pack_row_offsets,
    publish_csv_generation,
)
from staqtapp_tds.generation.generation_contract import (
    GenerationContractError,
    QualifiedGenerationLimits,
    bytes_root,
)
from staqtapp_tds.generation.generation_store import AtomicGenerationStore


def _root(label: str) -> str:
    return bytes_root(label.encode("ascii"))


def test_import_reuses_one_authoritative_source_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real_sha256_hex = manifest_module.sha256_hex

    def counted(data: bytes) -> str:
        nonlocal calls
        calls += 1
        return real_sha256_hex(data)

    monkeypatch.setattr(manifest_module, "sha256_hex", counted)
    fs = TDSFileSystem("root")
    raw = ("id,value\n" + "".join(f"{index},value-{index}\n" for index in range(2000))).encode()

    manifest = import_csv_bytes(fs.root, raw, source_name="one-hash.csv")

    assert calls == 1
    assert manifest.raw_sha256 == real_sha256_hex(raw)
    assert manifest.csv_id.endswith(manifest.raw_sha256[:12])


def test_import_rejects_explicit_unsafe_id_before_hashing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_hash(_data: bytes) -> str:
        raise AssertionError("source hashing ran before explicit csv_id validation")

    monkeypatch.setattr(manifest_module, "sha256_hex", must_not_hash)
    with pytest.raises(ValueError, match="unsafe"):
        manifest_module.build_manifest(
            source_name="invalid.csv",
            text="a,b\n1,2\n",
            raw=b"a,b\n1,2\n",
            encoding="utf-8",
            dialect=manifest_module.CSVDialectFingerprint(),
            csv_id="../invalid",
        )


def test_scan_materialization_and_validation_each_scan_source_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs = TDSFileSystem("root")
    raw = b'id,note\n1,"line\none"\n2,"quote "" kept"\n3,done\n'
    manifest = import_csv_bytes(fs.root, raw, source_name="single-scan.csv")
    real_scan = scan_artifacts_module.scan_csv_bytes
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(scan_artifacts_module, "scan_csv_bytes", counted)
    materialized = materialize_csv_scan_artifacts(
        fs.root,
        manifest.csv_id,
        include_row_anchors=True,
        chunk_size=3,
    )
    assert materialized.ok is True
    assert calls == 1

    stored_anchors = load_csv_row_anchor_profile(fs.root, manifest.csv_id)
    expected_anchors = scan_csv_row_anchors(
        raw,
        manifest.dialect,
        encoding=manifest.encoding,
        chunk_size=3,
    )
    assert stored_anchors == expected_anchors

    calls = 0
    validation = validate_materialized_csv_scan_artifacts(
        fs.root,
        manifest.csv_id,
        require_row_anchors=True,
        chunk_size=3,
    )
    assert validation.ok is True
    assert calls == 1


def test_canonical_export_remains_exact_while_rows_are_streamed() -> None:
    fs = TDSFileSystem("root")
    raw = b'name,note\r\nAda,"line one"\r\nGrace,"comma, kept"\r\n'
    manifest = import_csv_bytes(fs.root, raw, source_name="stream-export.csv")

    assert export_canonical_csv(fs.root, manifest.csv_id) == (
        'name,note\nAda,line one\nGrace,"comma, kept"\n'
    )
    source = inspect.getsource(export_canonical_csv)
    assert "writerows(iter_rows(" in source
    assert "read_rows(" not in source


def test_row_offset_packing_is_linear_shape_and_byte_exact() -> None:
    offsets = tuple(range(50_000))
    source_root = _root("offset-source")

    payload = pack_row_offsets(
        offsets,
        source_size=50_001,
        source_root=source_root,
    )

    assert len(payload) == generation_csv._OFFSET_HEADER.size + len(offsets) * 8
    source = inspect.getsource(pack_row_offsets)
    assert "sorted(" not in source
    assert "set(" not in source
    assert "pack_into" in source
    with pytest.raises(GenerationContractError, match="not canonical"):
        pack_row_offsets((0, 2, 1), source_size=3, source_root=source_root)


def test_candidate_reuses_source_root_and_hashed_chunk_bytes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = b"".join(f"{index:04d},payload-{index:04d}\n".encode() for index in range(40))
    store = AtomicGenerationStore(tmp_path / "candidate")
    real_bytes_root = generation_csv.bytes_root
    calls: list[tuple[str, bytes]] = []

    def tracked(data: bytes) -> str:
        root = real_bytes_root(data)
        calls.append((root, data))
        return root

    monkeypatch.setattr(generation_csv, "bytes_root", tracked)
    candidate = build_csv_generation_candidate(
        store,
        namespace="dataset:chunk-reuse",
        source=source,
        closure_root=_root("chunk-closure"),
        evidence_root=_root("chunk-evidence"),
        chunk_bytes=37,
    )
    payloads = candidate.payload_map()
    chunks = CSVChunkIndex.from_bytes(payloads[CSV_CHUNKS_PAYLOAD])

    assert sum(data is source for _, data in calls) == 1
    for chunk in chunks.chunks:
        chunk_payload = payloads[chunk.payload_name]
        assert any(
            root == chunk.content_root and data is chunk_payload
            for root, data in calls
        )


def test_candidate_rejects_payload_count_before_chunk_materialization(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits = QualifiedGenerationLimits(max_payloads=8)
    store = AtomicGenerationStore(tmp_path / "bounded", limits=limits)

    def must_not_build(*args, **kwargs):
        raise AssertionError("chunk materialization ran before the payload-count gate")

    monkeypatch.setattr(generation_csv, "_build_chunks", must_not_build)
    with pytest.raises(GenerationContractError, match="payload count"):
        build_csv_generation_candidate(
            store,
            namespace="dataset:bounded",
            source=b"a,b\n1,2\n",
            closure_root=_root("bounded-closure"),
            evidence_root=_root("bounded-evidence"),
            chunk_bytes=5,
            limits=CSVGenerationLimits(max_chunk_bytes=8),
        )


def test_candidate_rejects_chunk_count_before_row_oracle(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicGenerationStore(tmp_path / "chunk-bounded")

    def must_not_scan(*args, **kwargs):
        raise AssertionError("row oracle ran before the chunk-count gate")

    monkeypatch.setattr(generation_csv, "CSVRowBoundaryOracle", must_not_scan)
    with pytest.raises(GenerationContractError, match="chunk count"):
        build_csv_generation_candidate(
            store,
            namespace="dataset:chunk-bounded",
            source=b"a,b\n1,2\n",
            closure_root=_root("chunk-bounded-closure"),
            evidence_root=_root("chunk-bounded-evidence"),
            chunk_bytes=1,
            limits=CSVGenerationLimits(max_chunk_bytes=1, max_chunks=1),
        )


def test_csv_generation_load_does_not_rehash_verified_source_or_chunks(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = b"id,value\n1,alpha\n2,beta\n3,gamma\n"
    store = AtomicGenerationStore(tmp_path / "load")
    candidate = build_csv_generation_candidate(
        store,
        namespace="dataset:verified-read",
        source=source,
        closure_root=_root("load-closure"),
        evidence_root=_root("load-evidence"),
        chunk_bytes=7,
    )
    publish_csv_generation(store, candidate, expected_head_root=None)
    payloads = candidate.payload_map()
    chunks = CSVChunkIndex.from_bytes(payloads[CSV_CHUNKS_PAYLOAD])
    verified_values = {source, *(payloads[item.payload_name] for item in chunks.chunks)}
    real_bytes_root = generation_csv.bytes_root
    redundant_hashes: list[bytes] = []

    def tracked(data: bytes) -> str:
        if data in verified_values:
            redundant_hashes.append(data)
        return real_bytes_root(data)

    monkeypatch.setattr(generation_csv, "bytes_root", tracked)
    with open_csv_generation(store, "dataset:verified-read") as lease:
        assert lease.read_source() == source

    assert redundant_hashes == []
    load_source = inspect.getsource(generation_csv.load_csv_generation)
    assert "reconstructed_parts" not in load_source
    assert 'b"".join' not in load_source


def test_semantic_duplicate_detection_has_linear_shape() -> None:
    values = tuple(f"p-{index}" for index in range(10_000)) + ("p-3", "p-9")

    assert ir_duplicates(values) == ("p-3", "p-9")
    assert batch_duplicates(values) == ["p-3", "p-9"]
    assert ".count(" not in inspect.getsource(ir_duplicates)
    assert ".count(" not in inspect.getsource(batch_duplicates)

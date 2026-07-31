from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import shutil
import threading

import pytest

from staqtapp_tds.csv_layer.generation_contract import (
    CSVGenerationContractError,
    CSVGenerationFault,
    CSVGenerationLimits,
)
from staqtapp_tds.csv_layer.generation_store import (
    CSV_GENERATION_FAULT_POINTS,
    AtomicCSVGenerationStore,
    CSVStreamProfile,
    InjectedGenerationCrash,
    decode_row_anchors,
    decode_row_offsets,
)


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fixture() -> bytes:
    return (
        b"\xef\xbb\xbfid,text\r\n"
        b"1,\"line one\r\nline two\"\r\n"
        b"2,\"quote \"\"inside\"\"\"\n"
        b"3,emoji-\xf0\x9f\x99\x82"
    )


def _small_limits(**overrides: int) -> CSVGenerationLimits:
    values = {
        "max_source_bytes": 4_096,
        "max_chunk_bytes": 64,
        "max_chunks": 256,
        "max_rows": 256,
        "max_closure_nodes": 512,
        "max_closure_edges": 2_048,
    }
    values.update(overrides)
    return CSVGenerationLimits(**values)


def test_every_real_input_split_produces_one_exact_generation(tmp_path: Path) -> None:
    raw = _fixture()
    expected_identity: tuple[str, str, tuple[int, ...], tuple[object, ...]] | None = None

    for split in range(len(raw) + 1):
        store = AtomicCSVGenerationStore(tmp_path / f"split-{split:03d}")
        staged = store.stage(
            "dataset:split-oracle",
            (raw[:split], raw[split:]),
            chunk_bytes=7,
            limits=_small_limits(),
        )
        verification = store.verify(staged)
        assert verification.source_bytes == len(raw)
        assert verification.row_count == 4
        assert verification.chunk_count == (len(raw) + 6) // 7

        published = store.publish(staged, expected_current_manifest_root="")
        assert published.generation_root == staged.generation_root
        with store.open_current() as lease:
            assert lease.read_source() == raw
            observed = (
                lease.generation_root,
                lease.manifest.manifest_root,
                lease.row_offsets(),
                lease.row_anchors(),
            )
        if expected_identity is None:
            expected_identity = observed
        else:
            assert observed == expected_identity


def test_packed_offsets_and_anchors_are_canonical_and_source_bound(
    tmp_path: Path,
) -> None:
    raw = _fixture()
    store = AtomicCSVGenerationStore(tmp_path / "packed")
    staged = store.stage(
        "dataset:packed",
        (raw[index : index + 3] for index in range(0, len(raw), 3)),
        chunk_bytes=11,
        limits=_small_limits(),
    )
    offset_data = store._read_object(staged.manifest.identity.row_offsets_root)
    anchor_data = store._read_object(staged.manifest.identity.row_anchors_root)
    offset_count, offset_extent, offset_source, offsets = decode_row_offsets(offset_data)
    anchor_count, anchor_extent, anchor_source, anchors = decode_row_anchors(anchor_data)

    assert offset_count == anchor_count == staged.manifest.row_count == 4
    assert offset_extent == anchor_extent == len(raw)
    assert offset_source == anchor_source == staged.manifest.identity.source_sha256
    assert offsets == tuple(anchor.start_offset for anchor in anchors)
    assert anchors[-1].end_offset == len(raw)

    with pytest.raises(CSVGenerationContractError):
        decode_row_offsets(offset_data + b"\x00")
    with pytest.raises(CSVGenerationContractError):
        decode_row_anchors(b"BADMAGIC" + anchor_data[8:])


def test_crash_injection_exposes_only_old_or_new_complete_generation(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    old_raw = b"id,value\n1,old\n"
    new_raw = b"id,value\n1,new\n2,complete\n"
    store = AtomicCSVGenerationStore(base)
    old = store.stage(
        "dataset:crash",
        (old_raw,),
        chunk_bytes=5,
        limits=_small_limits(),
    )
    store.publish(old, expected_current_manifest_root="")

    for point in CSV_GENERATION_FAULT_POINTS:
        case = tmp_path / f"crash-{point}"
        shutil.copytree(base, case)
        candidate_store = AtomicCSVGenerationStore(case)
        new = candidate_store.stage(
            "dataset:crash",
            (new_raw[:7], new_raw[7:13], new_raw[13:]),
            chunk_bytes=5,
            limits=_small_limits(),
            parent_generation_root=old.generation_root,
        )

        def inject(observed: str) -> None:
            if observed == point:
                raise InjectedGenerationCrash(point)

        with pytest.raises(InjectedGenerationCrash, match=point):
            candidate_store.publish(
                new,
                expected_current_manifest_root=old.manifest_root,
                fault_injector=inject,
            )

        reopened = AtomicCSVGenerationStore(case)
        current = reopened.read_current()
        assert current is not None
        expected = new_raw if point == "after_current_replace" else old_raw
        with reopened.open_current() as lease:
            assert lease.read_source() == expected
            reopened.verify(lease.staged)


def test_generation_pinned_reader_remains_stable_during_publication(
    tmp_path: Path,
) -> None:
    store = AtomicCSVGenerationStore(tmp_path / "leases")
    old_raw = b"id,value\n1,old\n"
    new_raw = b"id,value\n1,new\n"
    old = store.stage(
        "dataset:leases",
        (old_raw,),
        chunk_bytes=4,
        limits=_small_limits(),
    )
    store.publish(old, expected_current_manifest_root="")
    lease = store.open_current()
    assert store.pin_count(old.generation_root) == 1

    stop = threading.Event()
    failures: list[BaseException] = []

    def reader() -> None:
        try:
            while not stop.is_set():
                assert lease.read_source() == old_raw
        except BaseException as exc:  # pragma: no cover - surfaced below
            failures.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(reader)
        new = store.stage(
            "dataset:leases",
            (new_raw[:3], new_raw[3:]),
            chunk_bytes=4,
            limits=_small_limits(),
            parent_generation_root=old.generation_root,
        )
        store.publish(new, expected_current_manifest_root=old.manifest_root)
        with store.open_current() as current:
            assert current.read_source() == new_raw
            assert current.generation_root == new.generation_root
        stop.set()
        future.result(timeout=10)

    assert not failures
    assert lease.read_source() == old_raw
    lease.close()
    assert store.pin_count(old.generation_root) == 0


def test_compare_and_swap_conflict_never_changes_current(tmp_path: Path) -> None:
    store = AtomicCSVGenerationStore(tmp_path / "cas")
    old = store.stage(
        "dataset:cas",
        (b"old\n",),
        chunk_bytes=4,
        limits=_small_limits(),
    )
    store.publish(old, expected_current_manifest_root="")
    new = store.stage(
        "dataset:cas",
        (b"new\n",),
        chunk_bytes=4,
        limits=_small_limits(),
        parent_generation_root=old.generation_root,
    )
    with pytest.raises(CSVGenerationContractError) as conflict:
        store.publish(
            new,
            expected_current_manifest_root=_root("not-current"),
        )
    assert conflict.value.fault is CSVGenerationFault.PUBLICATION_CONFLICT
    with store.open_current() as lease:
        assert lease.generation_root == old.generation_root
        assert lease.read_source() == b"old\n"


def test_failed_stream_candidate_leaves_current_unchanged(tmp_path: Path) -> None:
    store = AtomicCSVGenerationStore(tmp_path / "invalid")
    old = store.stage(
        "dataset:invalid",
        (b"id,value\n1,old\n",),
        chunk_bytes=5,
        limits=_small_limits(),
    )
    store.publish(old, expected_current_manifest_root="")
    with pytest.raises(CSVGenerationContractError) as incomplete:
        store.stage(
            "dataset:invalid",
            (b'id,value\n1,"unterminated',),
            chunk_bytes=5,
            limits=_small_limits(),
            parent_generation_root=old.generation_root,
        )
    assert incomplete.value.fault is CSVGenerationFault.INCOMPLETE_GENERATION
    with store.open_current() as lease:
        assert lease.generation_root == old.generation_root


def test_corrupt_object_and_current_pointer_fail_closed(tmp_path: Path) -> None:
    store = AtomicCSVGenerationStore(tmp_path / "corruption")
    staged = store.stage(
        "dataset:corruption",
        (b"id,value\n1,ok\n",),
        chunk_bytes=5,
        limits=_small_limits(),
    )
    store.publish(staged, expected_current_manifest_root="")
    first_chunk = staged.manifest.chunks[0]
    object_path = store._object_path(first_chunk.content_root)
    original = object_path.read_bytes()
    object_path.write_bytes(bytes((original[0] ^ 0x01,)) + original[1:])
    with pytest.raises(CSVGenerationContractError) as corrupt:
        store.verify(staged)
    assert corrupt.value.fault is CSVGenerationFault.IDENTITY_MISMATCH

    object_path.write_bytes(original)
    store.current_path.write_bytes(store.current_path.read_bytes() + b"\n")
    with pytest.raises(CSVGenerationContractError):
        store.read_current()


def test_limits_fail_before_publication_and_empty_input_is_canonical(
    tmp_path: Path,
) -> None:
    store = AtomicCSVGenerationStore(tmp_path / "limits")
    limited = _small_limits(
        max_source_bytes=8,
        max_chunk_bytes=4,
        max_chunks=1,
    )
    with pytest.raises(CSVGenerationContractError) as source_bound:
        store.stage(
            "dataset:limits",
            (b"123456789",),
            chunk_bytes=4,
            limits=limited,
        )
    assert source_bound.value.fault is CSVGenerationFault.BOUND_EXCEEDED
    assert store.read_current() is None

    with pytest.raises(CSVGenerationContractError) as chunk_bound:
        store.stage(
            "dataset:limits",
            (b"12345",),
            chunk_bytes=4,
            limits=limited,
        )
    assert chunk_bound.value.fault is CSVGenerationFault.BOUND_EXCEEDED

    empty = store.stage(
        "dataset:empty",
        (b"", memoryview(b"")),
        chunk_bytes=4,
        limits=_small_limits(),
    )
    assert empty.manifest.source_bytes == 0
    assert empty.manifest.row_count == 0
    assert empty.manifest.chunks == ()
    store.verify(empty)
    store.publish(empty, expected_current_manifest_root="")
    with store.open_current() as lease:
        assert lease.read_source() == b""
        assert lease.row_offsets() == ()
        assert lease.row_anchors() == ()

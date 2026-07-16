from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from staqtapp_tds import (
    GuaranteedStorageBridge,
    ImmutableSegmentStore,
    SegmentIntegrityError,
    SegmentStoreError,
    TDSFileSystem,
)


def _fs(value: bytes = b"alpha") -> TDSFileSystem:
    fs = TDSFileSystem("root")
    directory = fs.root.mkdir("data")
    directory.write("item", value)
    return fs


def test_segment_generation_round_trip(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    report = store.commit(b"abcdefghij")
    assert report.generation.segment_count == 3
    assert report.logical_bytes == 10
    assert store.read_current() == b"abcdefghij"
    assert store.current_generation() == report.generation.generation_id


def test_identical_generation_reuses_every_segment(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    first = store.commit(b"abcdefgh")
    second = store.commit(b"abcdefgh")
    assert first.segments_created == 2
    assert second.segments_created == 0
    assert second.segments_reused == 2
    assert second.bytes_written == 0


def test_only_changed_fixed_segment_is_written(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    store.commit(b"AAAABBBBCCCC")
    report = store.commit(b"AAAAXXXXCCCC")
    assert report.segments_created == 1
    assert report.segments_reused == 2
    assert report.bytes_written == 4
    assert store.read_current() == b"AAAAXXXXCCCC"


def test_manifest_is_immutable_and_verified(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    report = store.commit(b"abcdefgh")
    manifest = report.generation.path / store.MANIFEST_NAME
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(SegmentIntegrityError):
        store.verify(report.generation.generation_id)


def test_corrupt_segment_is_rejected(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    report = store.commit(b"abcdefgh")
    ref = report.generation.segments[0]
    store._segment_path(ref.sha256).write_bytes(b"xxxx")
    with pytest.raises(SegmentIntegrityError, match="checksum mismatch"):
        store.verify(report.generation.generation_id)


def test_missing_segment_is_rejected(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    report = store.commit(b"abcdefgh")
    store._segment_path(report.generation.segments[0].sha256).unlink()
    with pytest.raises(SegmentIntegrityError, match="missing"):
        store.read_current()


def test_failed_publication_leaves_previous_current_authoritative(tmp_path: Path) -> None:
    def crash(name: str) -> None:
        if name == "segment_current_before_replace" and armed[0]:
            raise RuntimeError("crash")

    armed = [False]
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4, fault_hook=crash)
    first = store.commit(b"abcdefgh")
    armed[0] = True
    with pytest.raises(RuntimeError, match="crash"):
        store.commit(b"ijklmnop")
    assert store.current_generation() == first.generation.generation_id
    assert store.read_current() == b"abcdefgh"


def test_reference_counts_count_generations_not_duplicate_occurrences(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    first = store.commit(b"AAAAAAAA")
    store.commit(b"AAAABBBB")
    a = hashlib.sha256(b"AAAA").hexdigest()
    b = hashlib.sha256(b"BBBB").hexdigest()
    assert store.reference_counts()[a] == 2
    assert store.reference_counts()[b] == 1
    assert first.generation.unique_segment_count == 1


def test_gc_never_removes_referenced_segments(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    first = store.commit(b"AAAABBBB")
    second = store.commit(b"CCCCDDDD")
    store.delete_generation(first.generation.generation_id)
    dry = store.collect_unreferenced_segments(dry_run=True)
    assert dry.removed_segments == ()
    assert len(dry.retained_unreferenced) == 2
    actual = store.collect_unreferenced_segments(dry_run=False)
    assert len(actual.removed_segments) == 2
    assert store.read_current() == b"CCCCDDDD"
    assert store.verify(second.generation.generation_id)


def test_current_generation_cannot_be_deleted(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    current = store.commit(b"data").generation.generation_id
    with pytest.raises(SegmentStoreError, match="current"):
        store.delete_generation(current)


def test_bridge_segmented_commit_and_materialisation(tmp_path: Path) -> None:
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    report = bridge.commit_filesystem_segmented(_fs(), parallel_nodes=False)
    destination = bridge.materialize_segmented_current(tmp_path / "mount")
    assert report.transition_mode == "legacy-compatible-incremental-segments"
    assert report.generation.application_metadata["storage_schema"] == "tds.incremental-segments.v1"
    assert report.files_archived > 0
    assert len([p for p in destination.rglob("*") if p.is_file()]) == report.files_archived
    assert list(destination.rglob("*.tds"))


def test_bridge_unchanged_filesystem_reuses_segments(tmp_path: Path) -> None:
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    bridge.segment_store.segment_bytes = 64
    first = bridge.commit_filesystem_segmented(_fs(), parallel_nodes=False)
    second = bridge.commit_filesystem_segmented(_fs(), parallel_nodes=False)
    assert second.segments_reused > 0
    assert second.physical_bytes_written < second.generation.logical_size
    assert first.generation.generation_id != second.generation.generation_id


def test_full_image_path_remains_independent_and_compatible(tmp_path: Path, monkeypatch) -> None:
    # Simulate the Windows CRT contract even on POSIX: every raw descriptor
    # write must request O_BINARY before byte-exact storage content is emitted.
    platform_binary_flag = getattr(os, "O_BINARY", 0)
    sentinel = 1 << 29
    real_open = os.open
    binary_write_paths: list[str] = []

    def tracked_open(path, flags, mode=0o777, *, dir_fd=None):
        if flags & os.O_WRONLY:
            assert flags & sentinel, f"raw descriptor write omitted O_BINARY: {path}"
            binary_write_paths.append(str(path))
        clean_flags = (flags & ~sentinel) | platform_binary_flag
        if dir_fd is None:
            return real_open(path, clean_flags, mode)
        return real_open(path, clean_flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "O_BINARY", sentinel, raising=False)
    monkeypatch.setattr(os, "open", tracked_open)

    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    full = bridge.commit_filesystem(_fs(), parallel_nodes=False)
    segmented = bridge.commit_filesystem_segmented(_fs(b"beta"), parallel_nodes=False)
    assert bridge.store.current_generation() == full.generation.generation_id
    assert bridge.segment_store.current_generation() == segmented.generation.generation_id
    assert bridge.materialize_current(tmp_path / "full").is_dir()
    assert bridge.materialize_segmented_current(tmp_path / "segmented").is_dir()
    assert any(path.endswith(".tds~") for path in binary_write_paths)
    assert any(path.endswith("data.tds") for path in binary_write_paths)
    assert any("segments" in path for path in binary_write_paths)
    assert any(".materializing-" in path for path in binary_write_paths)


def test_segment_names_are_content_addresses(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    info = store.commit(b"abcd").generation
    ref = info.segments[0]
    assert ref.sha256 == hashlib.sha256(b"abcd").hexdigest()
    assert store._segment_path(ref.sha256).name == ref.sha256 + ".seg"


def test_recovery_repairs_malformed_segment_pointer(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    first = store.commit(b"AAAA").generation
    second = store.commit(b"BBBB").generation
    store.current_path.write_text("not-a-generation\n", encoding="ascii")
    recovered = store.recover_current()
    assert recovered.generation_id == second.generation_id
    assert store.current_generation() == second.generation_id
    assert first.generation_id != recovered.generation_id


def test_mutation_lock_fails_closed(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    store.mutation_lock_path.mkdir()
    with pytest.raises(SegmentStoreError, match="lock"):
        store.commit(b"data")
    with pytest.raises(SegmentStoreError, match="lock"):
        store.collect_unreferenced_segments(dry_run=False)

@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("parent_generation", 7, "parent"),
        ("created_ns", True, "creation time"),
        ("segment_bytes", True, "segment size policy"),
        ("logical_size", True, "logical size"),
        ("logical_sha256", "not-a-digest", "logical checksum"),
        ("application_metadata", [], "application metadata"),
    ],
)
def test_manifest_rejects_wrong_scalar_types(tmp_path: Path, field: str, value: object, message: str) -> None:
    from staqtapp_tds.tds_json import dumps_canonical, loads_strict

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    info = store.commit(b"abcdefgh").generation
    manifest_path = info.path / store.MANIFEST_NAME
    manifest, _ = loads_strict(manifest_path.read_bytes(), expected_type=dict)
    manifest[field] = value
    manifest_path.write_bytes(dumps_canonical(manifest)[0])
    with pytest.raises(SegmentIntegrityError, match=message):
        store.verify(info.generation_id)


def test_manifest_rejects_unexpected_fields(tmp_path: Path) -> None:
    from staqtapp_tds.tds_json import dumps_canonical, loads_strict

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    info = store.commit(b"abcdefgh").generation
    manifest_path = info.path / store.MANIFEST_NAME
    manifest, _ = loads_strict(manifest_path.read_bytes(), expected_type=dict)
    manifest["future_unqualified_field"] = 1
    manifest_path.write_bytes(dumps_canonical(manifest)[0])
    with pytest.raises(SegmentIntegrityError, match="unexpected"):
        store.verify(info.generation_id)


def test_segment_reference_rejects_boolean_size(tmp_path: Path) -> None:
    from staqtapp_tds.tds_json import dumps_canonical, loads_strict

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    info = store.commit(b"abcd").generation
    manifest_path = info.path / store.MANIFEST_NAME
    manifest, _ = loads_strict(manifest_path.read_bytes(), expected_type=dict)
    manifest["segments"][0]["size"] = True
    manifest_path.write_bytes(dumps_canonical(manifest)[0])
    with pytest.raises(SegmentIntegrityError, match="reference size"):
        store.verify(info.generation_id)

import hashlib
from pathlib import Path

import pytest

from staqtapp_tds import ImmutableSegmentStore, SegmentIntegrityError, SegmentStoreError


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _orphan_two_segments(store: ImmutableSegmentStore) -> tuple[Path, Path]:
    old = store.commit(b"AAAABBBB").generation
    store.commit(b"CCCC").generation
    store.delete_generation(old.generation_id)
    return store._segment_path(_digest(b"AAAA")), store._segment_path(_digest(b"BBBB"))


def test_corrupt_generation_blocks_destructive_gc_and_preserves_orphans(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    orphan_a, orphan_b = _orphan_two_segments(store)
    corrupt_id = "sgen-00000000000000000001-deadbeefcafe"
    corrupt_dir = store.generations_dir / corrupt_id
    corrupt_dir.mkdir()
    (corrupt_dir / store.MANIFEST_NAME).write_bytes(b"{not-json")

    dry = store.collect_unreferenced_segments(dry_run=True)
    assert dry.blocked is True
    assert dry.invalid_generations == (corrupt_id,)
    assert set(dry.candidate_segments) == {_digest(b"AAAA"), _digest(b"BBBB")}
    with pytest.raises(SegmentIntegrityError, match="reference accounting is incomplete"):
        store.reference_counts()

    actual = store.collect_unreferenced_segments(dry_run=False)
    assert actual.blocked is True
    assert actual.removed_segments == ()
    assert orphan_a.exists() and orphan_b.exists()


def test_partially_damaged_generation_blocks_gc_from_destroying_salvageable_segments(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    damaged = store.commit(b"AAAABBBB").generation
    current = store.commit(b"CCCC").generation
    missing = store._segment_path(_digest(b"AAAA"))
    salvageable = store._segment_path(_digest(b"BBBB"))
    missing.unlink()

    report = store.collect_unreferenced_segments(dry_run=False)
    assert report.blocked is True
    assert damaged.generation_id in report.invalid_generations
    assert report.removed_segments == ()
    assert salvageable.exists()
    assert store.verify(current.generation_id)


def test_reference_published_at_gc_boundary_is_rechecked_and_retained(tmp_path: Path) -> None:
    armed = [False]
    raced = [False]

    def hook(name: str) -> None:
        if name == "segment_gc_before_delete" and armed[0] and not raced[0]:
            raced[0] = True
            # Deliberately bypass the public lock to simulate an injected writer
            # that appears at the final publication boundary.
            store._commit_stream_locked((b"AAAA",), application_metadata={"injected": True})

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4, fault_hook=hook)
    old = store.commit(b"AAAA").generation
    store.commit(b"BBBB")
    store.delete_generation(old.generation_id)
    orphan = store._segment_path(_digest(b"AAAA"))
    armed[0] = True

    report = store.collect_unreferenced_segments(dry_run=False)
    assert raced[0] is True
    assert report.removed_segments == ()
    assert _digest(b"AAAA") in report.retained_unreferenced
    assert orphan.exists()
    assert store.read_current() == b"AAAA"


def test_changed_candidate_inode_is_not_unlinked_or_misreported(tmp_path: Path) -> None:
    swapped = [False]
    candidate: Path | None = None

    def hook(name: str) -> None:
        nonlocal candidate
        if name == "segment_gc_before_delete" and not swapped[0]:
            swapped[0] = True
            assert candidate is not None
            candidate.unlink()
            candidate.write_bytes(b"replacement-evidence")

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4, fault_hook=hook)
    old = store.commit(b"AAAA").generation
    store.commit(b"BBBB")
    store.delete_generation(old.generation_id)
    candidate = store._segment_path(_digest(b"AAAA"))

    report = store.collect_unreferenced_segments(dry_run=False)
    assert report.removed_segments == ()
    assert report.removed_bytes == 0
    assert report.changed_candidates == (_digest(b"AAAA"),)
    assert candidate.read_bytes() == b"replacement-evidence"


def test_same_inode_candidate_content_change_is_not_unlinked_or_misreported(tmp_path: Path) -> None:
    changed = [False]
    candidate: Path | None = None

    def hook(name: str) -> None:
        nonlocal candidate
        if name == "segment_gc_before_delete" and not changed[0]:
            changed[0] = True
            assert candidate is not None
            candidate.write_bytes(b"EEEE")

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4, fault_hook=hook)
    old = store.commit(b"AAAA").generation
    store.commit(b"BBBB")
    store.delete_generation(old.generation_id)
    candidate = store._segment_path(_digest(b"AAAA"))
    original_inode = candidate.stat().st_ino

    report = store.collect_unreferenced_segments(dry_run=False)
    assert candidate.stat().st_ino == original_inode
    assert candidate.read_bytes() == b"EEEE"
    assert report.removed_segments == ()
    assert report.removed_bytes == 0
    assert report.changed_candidates == (_digest(b"AAAA"),)


def test_symlink_swap_never_unlinks_external_target(tmp_path: Path) -> None:
    swapped = [False]
    candidate: Path | None = None
    external = tmp_path / "external-evidence"
    external.write_bytes(b"must-survive")

    def hook(name: str) -> None:
        nonlocal candidate
        if name == "segment_gc_before_delete" and not swapped[0]:
            swapped[0] = True
            assert candidate is not None
            candidate.unlink()
            try:
                candidate.symlink_to(external)
            except (OSError, NotImplementedError):
                pytest.skip("symlinks unavailable")

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4, fault_hook=hook)
    old = store.commit(b"AAAA").generation
    store.commit(b"BBBB")
    store.delete_generation(old.generation_id)
    candidate = store._segment_path(_digest(b"AAAA"))

    report = store.collect_unreferenced_segments(dry_run=False)
    assert report.removed_segments == ()
    assert report.changed_candidates == (_digest(b"AAAA"),)
    assert candidate.is_symlink()
    assert external.read_bytes() == b"must-survive"


def test_interrupted_gc_is_idempotently_resumable(tmp_path: Path) -> None:
    fired = [False]

    def hook(name: str) -> None:
        if name == "segment_gc_after_delete" and not fired[0]:
            fired[0] = True
            raise RuntimeError("injected GC interruption")

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4, fault_hook=hook)
    orphan_a, orphan_b = _orphan_two_segments(store)
    with pytest.raises(RuntimeError, match="interruption"):
        store.collect_unreferenced_segments(dry_run=False)
    assert orphan_a.exists() != orphan_b.exists()

    store._fault_hook = None
    resumed = store.collect_unreferenced_segments(dry_run=False)
    assert len(resumed.removed_segments) == 1
    assert not orphan_a.exists() and not orphan_b.exists()
    assert store.read_current() == b"CCCC"


def test_public_mutation_cannot_enter_while_gc_holds_exclusion(tmp_path: Path) -> None:
    competing_store: ImmutableSegmentStore | None = None
    blocked = [False]

    def hook(name: str) -> None:
        if name == "segment_gc_before_delete" and not blocked[0]:
            assert competing_store is not None
            with pytest.raises(SegmentStoreError, match="lock"):
                competing_store.commit(b"DDDD")
            blocked[0] = True

    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4, fault_hook=hook)
    competing_store = ImmutableSegmentStore(store.root, segment_bytes=4)
    orphan_a, orphan_b = _orphan_two_segments(store)
    report = store.collect_unreferenced_segments(dry_run=False)
    assert blocked[0] is True
    assert len(report.removed_segments) == 2
    assert not orphan_a.exists() and not orphan_b.exists()
    assert store.read_current() == b"CCCC"


def test_gc_byte_accounting_matches_files_actually_unlinked(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "store", segment_bytes=4)
    orphan_a, orphan_b = _orphan_two_segments(store)
    expected_bytes = orphan_a.stat().st_size + orphan_b.stat().st_size
    report = store.collect_unreferenced_segments(dry_run=False)
    assert report.blocked is False
    assert set(report.removed_segments) == {_digest(b"AAAA"), _digest(b"BBBB")}
    assert report.removed_bytes == expected_bytes

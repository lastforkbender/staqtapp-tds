from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from staqtapp_tds.csv_layer.generation_contract import (
    CSVGenerationContractError,
    CSVGenerationFault,
    CSVGenerationLimits,
)
from staqtapp_tds.csv_layer.generation_runtime import (
    CSV_DURABLE_PUBLICATION_AUTHORITY,
    CSVPublicationAuthorityBoundary,
    CSVPublicationOperation,
    DurableAtomicCSVGenerationStore,
)


def _limits() -> CSVGenerationLimits:
    return CSVGenerationLimits(
        max_source_bytes=16_384,
        max_chunk_bytes=128,
        max_chunks=512,
        max_rows=512,
        max_closure_nodes=1_024,
        max_closure_edges=4_096,
    )


def _stage(
    store: DurableAtomicCSVGenerationStore,
    dataset: str,
    payload: bytes,
    *,
    parent: str = "",
):
    return store.stage(
        dataset,
        (payload[:3], payload[3:8], payload[8:]),
        chunk_bytes=5,
        limits=_limits(),
        parent_generation_root=parent,
    )


def _raise_at(wanted: str):
    def inject(point: str) -> None:
        if point == wanted:
            raise RuntimeError(wanted)

    return inject


def test_durable_publication_records_intent_commit_and_verified_current(
    tmp_path: Path,
) -> None:
    store = DurableAtomicCSVGenerationStore(tmp_path / "durable")
    staged = _stage(store, "dataset:durable", b"id,value\n1,stable\n")
    receipt = store.publish(staged, expected_current_manifest_root="")

    current = store.read_current()
    assert current is not None
    assert current.generation_root == staged.generation_root
    assert current.manifest_root == staged.manifest_root
    assert current.published_receipt_root == receipt.receipt_root
    assert len(tuple(store.intents_dir.glob("*.json"))) == 1
    assert len(tuple(store.commits_dir.glob("*.json"))) == 1
    assert tuple(store.aborts_dir.glob("*.json")) == ()

    report = store.recover_publication()
    assert report.current_verified is True
    assert report.current_generation_root == staged.generation_root
    assert report.completed_intent_roots == ()
    assert report.aborted_intent_roots == ()
    assert report.report_root.startswith("sha256:")


def test_recovery_aborts_intent_that_never_replaced_current(tmp_path: Path) -> None:
    store = DurableAtomicCSVGenerationStore(tmp_path / "abort")
    old = _stage(store, "dataset:abort", b"id,value\n1,old\n")
    store.publish(old, expected_current_manifest_root="")
    new = _stage(
        store,
        "dataset:abort",
        b"id,value\n1,new\n2,complete\n",
        parent=old.generation_root,
    )

    with pytest.raises(RuntimeError, match="after_publication_intent"):
        store.publish(
            new,
            expected_current_manifest_root=old.manifest_root,
            fault_injector=_raise_at("after_publication_intent"),
        )

    with store.open_current() as lease:
        assert lease.generation_root == old.generation_root
    report = DurableAtomicCSVGenerationStore(store.root).recover_publication()
    assert report.current_verified is True
    assert len(report.aborted_intent_roots) == 1
    assert report.completed_intent_roots == ()
    with store.open_current() as lease:
        assert lease.generation_root == old.generation_root


def test_recovery_completes_commit_after_current_replace(tmp_path: Path) -> None:
    store = DurableAtomicCSVGenerationStore(tmp_path / "complete")
    old = _stage(store, "dataset:complete", b"id,value\n1,old\n")
    store.publish(old, expected_current_manifest_root="")
    new = _stage(
        store,
        "dataset:complete",
        b"id,value\n1,new\n",
        parent=old.generation_root,
    )

    before_commits = len(tuple(store.commits_dir.glob("*.json")))
    with pytest.raises(RuntimeError, match="after_current_replace"):
        store.publish(
            new,
            expected_current_manifest_root=old.manifest_root,
            fault_injector=_raise_at("after_current_replace"),
        )
    assert len(tuple(store.commits_dir.glob("*.json"))) == before_commits

    reopened = DurableAtomicCSVGenerationStore(store.root)
    with reopened.open_current() as lease:
        assert lease.generation_root == new.generation_root
    report = reopened.recover_publication()
    assert report.current_verified is True
    assert len(report.completed_intent_roots) == 1
    assert report.aborted_intent_roots == ()
    assert len(tuple(reopened.commits_dir.glob("*.json"))) == before_commits + 1


def test_cross_instance_cas_allows_exactly_one_winner(tmp_path: Path) -> None:
    root = tmp_path / "race"
    first = DurableAtomicCSVGenerationStore(root)
    old = _stage(first, "dataset:race", b"id,value\n1,old\n")
    first.publish(old, expected_current_manifest_root="")

    left_store = DurableAtomicCSVGenerationStore(root)
    right_store = DurableAtomicCSVGenerationStore(root)
    left = _stage(
        left_store,
        "dataset:race",
        b"id,value\n1,left\n",
        parent=old.generation_root,
    )
    right = _stage(
        right_store,
        "dataset:race",
        b"id,value\n1,right\n",
        parent=old.generation_root,
    )
    barrier = threading.Barrier(2)

    def publish(store: DurableAtomicCSVGenerationStore, candidate):
        barrier.wait(timeout=10)
        try:
            store.publish(
                candidate,
                expected_current_manifest_root=old.manifest_root,
            )
            return ("published", candidate.generation_root)
        except CSVGenerationContractError as exc:
            return (exc.fault.value, candidate.generation_root)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: publish(*pair),
                ((left_store, left), (right_store, right)),
            )
        )

    assert sorted(result[0] for result in results) == [
        CSVGenerationFault.PUBLICATION_CONFLICT.value,
        "published",
    ]
    winner = next(candidate_root for status, candidate_root in results if status == "published")
    with DurableAtomicCSVGenerationStore(root).open_current() as lease:
        assert lease.generation_root == winner
        assert lease.staged.manifest.identity.parent_generation_root == old.generation_root


def test_rollback_and_retirement_are_separate_bounded_authorities(
    tmp_path: Path,
) -> None:
    store = DurableAtomicCSVGenerationStore(tmp_path / "rollback")
    old = _stage(store, "dataset:rollback", b"id,value\n1,old\n")
    store.publish(old, expected_current_manifest_root="")
    new = _stage(
        store,
        "dataset:rollback",
        b"id,value\n1,new\n",
        parent=old.generation_root,
    )
    store.publish(new, expected_current_manifest_root=old.manifest_root)

    rollback = store.rollback(
        old.generation_root,
        expected_current_manifest_root=new.manifest_root,
    )
    assert rollback.operation is CSVPublicationOperation.ROLLBACK
    with store.open_current() as lease:
        assert lease.generation_root == old.generation_root

    retirement = store.retire_generation(new.generation_root)
    assert retirement.generation_root == new.generation_root
    assert store.is_retired(new.generation_root) is True
    assert store.retire_generation(new.generation_root) == retirement
    with pytest.raises(CSVGenerationContractError) as retired:
        store.rollback(new.generation_root)
    assert retired.value.fault is CSVGenerationFault.AUTHORITY_REJECTED
    with pytest.raises(CSVGenerationContractError) as current:
        store.retire_generation(old.generation_root)
    assert current.value.fault is CSVGenerationFault.AUTHORITY_REJECTED


def test_pinned_generation_cannot_be_retired(tmp_path: Path) -> None:
    store = DurableAtomicCSVGenerationStore(tmp_path / "pins")
    old = _stage(store, "dataset:pins", b"id,value\n1,old\n")
    store.publish(old, expected_current_manifest_root="")
    new = _stage(
        store,
        "dataset:pins",
        b"id,value\n1,new\n",
        parent=old.generation_root,
    )
    store.publish(new, expected_current_manifest_root=old.manifest_root)

    lease = store.open_generation(old.generation_root)
    with pytest.raises(CSVGenerationContractError) as pinned:
        store.retire_generation(old.generation_root)
    assert pinned.value.fault is CSVGenerationFault.AUTHORITY_REJECTED
    lease.close()
    assert store.retire_generation(old.generation_root).generation_root == old.generation_root


def test_publication_authority_is_non_widenable_and_content_free() -> None:
    authority = CSV_DURABLE_PUBLICATION_AUTHORITY
    assert authority.interprocess_lock_required is True
    assert authority.compare_and_swap_required is True
    assert authority.current_pointer_is_activation_authority is True
    assert authority.receipts_are_activation_authority is False
    assert authority.may_commit_semantics is False
    assert authority.may_accept_learned_writes is False
    assert authority.browser_or_studio_may_publish is False
    assert authority.authority_root.startswith("sha256:")
    with pytest.raises(CSVGenerationContractError) as widened:
        CSVPublicationAuthorityBoundary(may_rank_traces=True)
    assert widened.value.fault is CSVGenerationFault.AUTHORITY_REJECTED
    material = str(authority.canonical_dict()).lower()
    for forbidden in ("prompt", "logits", "hidden_state", "kv_tensor"):
        assert forbidden not in material

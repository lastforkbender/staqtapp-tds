from __future__ import annotations

from dataclasses import replace
import multiprocessing
import os
from pathlib import Path

import pytest

from staqtapp_tds.generation.generation_contract import (
    DEFAULT_GENERATION_LIMITS,
    GenerationFault,
    GenerationPublicationRecord,
    PublicationAction,
    canonical_json_bytes,
)
from staqtapp_tds.generation.generation_store import (
    AtomicGenerationStore,
    GenerationPublicationConflict,
    GenerationStoreError,
)


def _candidate(
    store: AtomicGenerationStore,
    namespace: str,
    payload: bytes,
    parent: str | None,
):
    return store.build_candidate(
        namespace=namespace,
        payloads={"source": payload},
        authoritative_payload="source",
        parent_generation_root=parent,
    )


def _publish_first(store: AtomicGenerationStore, namespace: str):
    return store.publish(
        _candidate(store, namespace, b"generation-a\n", None),
        expected_head_root=None,
    )


def _exit_with_namespace_lock(root: str, namespace: str, ready) -> None:
    store = AtomicGenerationStore(root)
    with store._namespace_lock(namespace):
        ready.set()
        os._exit(0)


def _hold_cross_process_pin(
    root: str,
    namespace: str,
    generation_root: str,
    ready,
    release,
) -> None:
    store = AtomicGenerationStore(root)
    lease = store.pin(namespace, generation_root)
    ready.set()
    if not release.wait(30):
        os._exit(3)
    lease.close()


def test_generation_descriptors_request_binary_mode_for_canonical_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform_binary_flag = getattr(os, "O_BINARY", 0)
    sentinel = 1 << 29
    real_open = os.open
    regular_calls: list[tuple[str, int]] = []

    def tracked_open(path, flags, mode=0o777, *, dir_fd=None):
        path_text = os.fspath(path)
        if not flags & getattr(os, "O_DIRECTORY", 0):
            regular_calls.append((path_text, flags))
        clean_flags = (flags & ~sentinel) | platform_binary_flag
        if dir_fd is None:
            return real_open(path, clean_flags, mode)
        return real_open(path, clean_flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "O_BINARY", sentinel, raising=False)
    monkeypatch.setattr(os, "open", tracked_open)

    store = AtomicGenerationStore(tmp_path / "authority")
    published = _publish_first(store, "dataset:binary-records")
    assert store.current_head("dataset:binary-records") == published.head

    generation_calls = [
        flags
        for path, flags in regular_calls
        if path.endswith(("LOCK", "publication.jsonl"))
    ]
    assert generation_calls
    assert all(flags & sentinel for flags in generation_calls)
    raw_log = store._publication_log_path("dataset:binary-records").read_bytes()
    assert raw_log.endswith(b"\n")
    assert b"\r\n" not in raw_log


def test_nested_process_pins_share_one_os_lock_until_the_last_close(
    tmp_path: Path,
) -> None:
    namespace = "dataset:nested-pins"
    store = AtomicGenerationStore(tmp_path / "authority")
    published = _publish_first(store, namespace)

    first = store.pin(namespace, published.head.generation_root)
    second = store.pin(namespace, published.head.generation_root)
    assert first._pin_fd == second._pin_fd
    assert store.pin_count(published.head.generation_root) == 2

    first.close()
    assert store.pin_count(published.head.generation_root) == 1
    assert store._pin_locks[published.head.generation_root][1] == 1
    second.close()
    assert store.pin_count(published.head.generation_root) == 0
    assert published.head.generation_root not in store._pin_locks


def test_namespace_lock_is_persistent_but_crash_released(tmp_path: Path) -> None:
    namespace = "dataset:crash-lock"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(
        target=_exit_with_namespace_lock,
        args=(str(tmp_path), namespace, ready),
    )
    process.start()
    assert ready.wait(30)
    process.join(30)
    assert process.exitcode == 0

    store = AtomicGenerationStore(tmp_path)
    assert (store._namespace_dir(namespace) / "LOCK").is_file()
    published = _publish_first(store, namespace)
    assert store.current_head(namespace) == published.head


def test_head_root_cas_rejects_aba_after_rollback(tmp_path: Path) -> None:
    namespace = "dataset:aba"
    store = AtomicGenerationStore(tmp_path)
    first = _publish_first(store, namespace)
    stale_head_root = first.head.head_root
    second = store.publish(
        _candidate(
            store,
            namespace,
            b"generation-b\n",
            first.manifest.generation_root,
        ),
        expected_head_root=first.head.head_root,
    )
    rolled = store.rollback(
        namespace,
        first.manifest.generation_root,
        expected_head_root=second.head.head_root,
    )
    assert rolled.head.generation_root == first.manifest.generation_root
    assert rolled.head.head_root != stale_head_root

    third = _candidate(
        store,
        namespace,
        b"generation-c\n",
        first.manifest.generation_root,
    )
    with pytest.raises(GenerationPublicationConflict):
        store.publish(third, expected_head_root=stale_head_root)
    published = store.publish(third, expected_head_root=rolled.head.head_root)
    assert store.current_head(namespace) == published.head


def test_rollback_rejects_materialized_never_published_generation(
    tmp_path: Path,
) -> None:
    namespace = "dataset:orphan"
    store = AtomicGenerationStore(tmp_path)
    first = _publish_first(store, namespace)
    orphan = _candidate(
        store,
        namespace,
        b"orphan\n",
        first.manifest.generation_root,
    )
    store._materialize_generation(orphan)

    with pytest.raises(GenerationStoreError, match="never published"):
        store.pin(namespace, orphan.generation_root)
    with pytest.raises(GenerationPublicationConflict, match="never published"):
        store.rollback(
            namespace,
            orphan.generation_root,
            expected_head_root=first.head.head_root,
        )
    assert store.current_head(namespace) == first.head


def test_cross_process_pin_blocks_retirement_and_retired_pin_is_rejected(
    tmp_path: Path,
) -> None:
    namespace = "dataset:process-pin"
    store = AtomicGenerationStore(tmp_path, lock_attempts=20)
    first = _publish_first(store, namespace)
    second = store.publish(
        _candidate(
            store,
            namespace,
            b"generation-b\n",
            first.manifest.generation_root,
        ),
        expected_head_root=first.head.head_root,
    )
    assert second.head.generation_root != first.manifest.generation_root

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_cross_process_pin,
        args=(
            str(tmp_path),
            namespace,
            first.manifest.generation_root,
            ready,
            release,
        ),
    )
    process.start()
    assert ready.wait(30)
    with pytest.raises(GenerationStoreError, match="pinned"):
        store.retire(namespace, first.manifest.generation_root)

    release.set()
    process.join(30)
    assert process.exitcode == 0
    retired = store.retire(namespace, first.manifest.generation_root)
    assert retired.state.value == "retired"
    with pytest.raises(GenerationStoreError, match="retired"):
        AtomicGenerationStore(tmp_path).pin(
            namespace,
            first.manifest.generation_root,
        )


def test_loaded_manifest_and_publication_log_obey_reopen_limits(
    tmp_path: Path,
) -> None:
    namespace = "dataset:reopen-bounds"
    broad = replace(DEFAULT_GENERATION_LIMITS, max_publication_records=3)
    store = AtomicGenerationStore(tmp_path, limits=broad)
    first = store.publish(
        store.build_candidate(
            namespace=namespace,
            payloads={"a": b"a", "b": b"b"},
            parent_generation_root=None,
        ),
        expected_head_root=None,
    )
    second = store.publish(
        _candidate(store, namespace, b"second", first.manifest.generation_root),
        expected_head_root=first.head.head_root,
    )
    store.publish(
        _candidate(store, namespace, b"third", second.manifest.generation_root),
        expected_head_root=second.head.head_root,
    )

    tight_log = AtomicGenerationStore(
        tmp_path,
        limits=replace(broad, max_publication_records=2),
    )
    with pytest.raises(GenerationStoreError) as log_error:
        tight_log.recover(namespace)
    assert log_error.value.fault is GenerationFault.BOUND_EXCEEDED

    tight_manifest = AtomicGenerationStore(
        tmp_path,
        limits=replace(broad, max_payloads=1),
    )
    with pytest.raises(GenerationStoreError) as manifest_error:
        tight_manifest.verify_generation(first.manifest.generation_root)
    assert manifest_error.value.fault is GenerationFault.BOUND_EXCEEDED


def test_publication_limit_rejects_append_at_exact_bound(tmp_path: Path) -> None:
    namespace = "dataset:append-bound"
    limits = replace(DEFAULT_GENERATION_LIMITS, max_publication_records=1)
    store = AtomicGenerationStore(tmp_path, limits=limits)
    first = _publish_first(store, namespace)
    with pytest.raises(GenerationStoreError) as error:
        store.publish(
            _candidate(
                store,
                namespace,
                b"generation-b\n",
                first.manifest.generation_root,
            ),
            expected_head_root=first.head.head_root,
        )
    assert error.value.fault is GenerationFault.BOUND_EXCEEDED
    assert store.current_head(namespace) == first.head


def test_symlink_payload_read_fails_closed(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("platform does not expose symlinks")
    namespace = "dataset:symlink"
    store = AtomicGenerationStore(tmp_path)
    first = _publish_first(store, namespace)
    identity = first.manifest.payloads[0]
    object_path = store._object_path(identity.content_root)
    external = tmp_path / "external-source"
    external.write_bytes(b"generation-a\n")
    object_path.unlink()
    try:
        object_path.symlink_to(external)
    except OSError:
        pytest.skip("symlink creation is not permitted")
    with pytest.raises(GenerationStoreError) as error:
        store.verify_generation(first.manifest.generation_root)
    assert error.value.fault is GenerationFault.INTEGRITY_FAILURE


def test_recovery_rejects_publish_manifest_parent_lineage_forgery(
    tmp_path: Path,
) -> None:
    namespace = "dataset:lineage"
    store = AtomicGenerationStore(tmp_path)
    first = _publish_first(store, namespace)
    forged = _candidate(
        store,
        namespace,
        b"forged\n",
        "sha256:" + "f" * 64,
    )
    manifest, published = store._materialize_generation(forged)
    record = GenerationPublicationRecord(
        namespace=namespace,
        publication_sequence=2,
        action=PublicationAction.PUBLISH,
        generation_root=manifest.generation_root,
        manifest_root=manifest.manifest_root,
        published_receipt_root=published.receipt_root,
        previous_generation_root=first.manifest.generation_root,
        predecessor_record_root=first.record.record_root,
    )
    store._append_publication_record(namespace, record)

    with pytest.raises(GenerationStoreError, match="parent") as error:
        store.recover(namespace)
    assert error.value.fault is GenerationFault.RECOVERY_FAILURE


def test_recovery_rejects_rollback_to_never_published_generation(
    tmp_path: Path,
) -> None:
    namespace = "dataset:rollback-lineage"
    store = AtomicGenerationStore(tmp_path)
    first = _publish_first(store, namespace)
    orphan = _candidate(
        store,
        namespace,
        b"rollback-orphan\n",
        first.manifest.generation_root,
    )
    manifest, published = store._materialize_generation(orphan)
    record = GenerationPublicationRecord(
        namespace=namespace,
        publication_sequence=2,
        action=PublicationAction.ROLLBACK,
        generation_root=manifest.generation_root,
        manifest_root=manifest.manifest_root,
        published_receipt_root=published.receipt_root,
        previous_generation_root=first.manifest.generation_root,
        predecessor_record_root=first.record.record_root,
    )
    store._append_publication_record(namespace, record)

    with pytest.raises(GenerationStoreError, match="never published") as error:
        store.recover(namespace)
    assert error.value.fault is GenerationFault.RECOVERY_FAILURE


def test_corrupt_retired_receipt_fails_closed(tmp_path: Path) -> None:
    namespace = "dataset:retired-corrupt"
    store = AtomicGenerationStore(tmp_path)
    first = _publish_first(store, namespace)
    second = store.publish(
        _candidate(
            store,
            namespace,
            b"generation-b\n",
            first.manifest.generation_root,
        ),
        expected_head_root=first.head.head_root,
    )
    assert second.head.generation_root != first.manifest.generation_root
    receipt = store.retire(namespace, first.manifest.generation_root)
    corrupt = receipt.canonical_dict()
    corrupt["predecessor_receipt_root"] = "sha256:" + "0" * 64
    path = (
        store._generation_dir(first.manifest.generation_root)
        / "receipts"
        / "004-retired.json"
    )
    path.write_bytes(canonical_json_bytes(corrupt))
    with pytest.raises(GenerationStoreError) as error:
        store.is_retired(first.manifest.generation_root)
    assert error.value.fault is GenerationFault.INTEGRITY_FAILURE


def test_recovery_fsyncs_directory_after_current_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = "dataset:delete-current"
    store = AtomicGenerationStore(tmp_path)
    store.recover(namespace)  # create and fsync the persistent namespace lock
    current = store._head_path(namespace)
    current.write_bytes(b"{}")
    calls: list[Path] = []
    monkeypatch.setattr(store, "_fsync_directory", lambda path: calls.append(path))

    result = store.recover(namespace)
    assert result.head is None
    assert not current.exists()
    assert current.parent in calls


def test_abandoned_staging_entry_is_never_recovered_as_current(
    tmp_path: Path,
) -> None:
    namespace = "dataset:abandoned-stage"
    store = AtomicGenerationStore(tmp_path)
    abandoned = store.staging_dir / "generation-abandoned"
    abandoned.mkdir()
    (abandoned / "manifest.json").write_bytes(b"{}")

    recovered = store.recover(namespace)
    assert recovered.head is None
    assert abandoned.is_dir()
    first = _publish_first(store, namespace)
    assert store.recover(namespace).head == first.head


def test_bounded_state_model_enforces_transition_invariants(tmp_path: Path) -> None:
    namespace = "dataset:model"
    store = AtomicGenerationStore(tmp_path)
    published: dict[str, object] = {}
    retired: set[str] = set()

    first = _publish_first(store, namespace)
    published[first.manifest.generation_root] = first
    with pytest.raises(GenerationStoreError, match="CURRENT"):
        store.retire(namespace, first.manifest.generation_root)

    lease = store.pin(namespace, first.manifest.generation_root)
    second = store.publish(
        _candidate(
            store,
            namespace,
            b"generation-b\n",
            first.manifest.generation_root,
        ),
        expected_head_root=first.head.head_root,
    )
    published[second.manifest.generation_root] = second
    with pytest.raises(GenerationStoreError, match="pinned"):
        store.retire(namespace, first.manifest.generation_root)
    assert store.recover(namespace).head == second.head
    lease.close()

    rolled = store.rollback(
        namespace,
        first.manifest.generation_root,
        expected_head_root=second.head.head_root,
    )
    with pytest.raises(GenerationStoreError, match="CURRENT"):
        store.retire(namespace, first.manifest.generation_root)
    third = store.publish(
        _candidate(
            store,
            namespace,
            b"generation-c\n",
            first.manifest.generation_root,
        ),
        expected_head_root=rolled.head.head_root,
    )
    published[third.manifest.generation_root] = third
    store.retire(namespace, second.manifest.generation_root)
    retired.add(second.manifest.generation_root)

    with pytest.raises(GenerationStoreError, match="retired"):
        store.pin(namespace, second.manifest.generation_root)
    with pytest.raises(GenerationStoreError, match="retired"):
        store.rollback(
            namespace,
            second.manifest.generation_root,
            expected_head_root=third.head.head_root,
        )
    final = store.recover(namespace).head
    assert final == third.head
    assert final.generation_root in published
    assert final.generation_root not in retired

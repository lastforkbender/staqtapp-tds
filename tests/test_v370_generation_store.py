from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from staqtapp_tds.generation.generation_contract import (
    GENERATION_AUTHORITY,
    GenerationFault,
)
from staqtapp_tds.generation.generation_store import (
    FAILURE_BOUNDARIES,
    AtomicGenerationStore,
    GenerationPublicationConflict,
    GenerationStoreError,
)


class InjectedFailure(RuntimeError):
    pass


def candidate(
    store: AtomicGenerationStore,
    namespace: str,
    source: bytes,
    *,
    parent: str | None,
):
    return store.build_candidate(
        namespace=namespace,
        payloads={
            "source": source,
            "offsets": len(source).to_bytes(8, "little"),
        },
        media_types={
            "source": "application/octet-stream",
            "offsets": "application/vnd.staqtapp.offsets",
        },
        authoritative_payload="source",
        parent_generation_root=parent,
        qualifications={
            "source-roundtrip": "sha256:" + "1" * 64,
        },
        metadata={"consumer": "csv-first"},
    )


def publish_first(store: AtomicGenerationStore, namespace: str = "dataset:people"):
    first = candidate(store, namespace, b"id,name\n1,Ada\n", parent=None)
    return store.publish(first, expected_current_root=None)


def test_publish_current_and_exact_authoritative_roundtrip(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    result = publish_first(store)
    assert store.current_head("dataset:people") == result.head
    with store.pin("dataset:people") as lease:
        assert lease.generation_root == result.manifest.generation_root
        assert lease.read_payload("source") == b"id,name\n1,Ada\n"
        assert lease.read_payload("offsets") == (14).to_bytes(8, "little")
    assert store.pin_count(result.manifest.generation_root) == 0
    assert GENERATION_AUTHORITY.semantic_authority is False


@pytest.mark.parametrize(
    "boundary",
    tuple(item for item in FAILURE_BOUNDARIES if item != "during_recovery"),
)
def test_crash_boundaries_expose_only_none_or_complete_generation(
    tmp_path: Path,
    boundary: str,
):
    seen = False

    def inject(name: str):
        nonlocal seen
        if name == boundary and not seen:
            seen = True
            raise InjectedFailure(boundary)

    store = AtomicGenerationStore(tmp_path, failure_injector=inject)
    item = candidate(store, "dataset:crash", b"one\n", parent=None)
    with pytest.raises(InjectedFailure):
        store.publish(item, expected_current_root=None)

    store.failure_injector = None
    recovered = store.recover("dataset:crash")
    if recovered.head is None:
        assert store.list_generations("dataset:crash") in ((), (item.generation_root,))
    else:
        manifest, _ = store.verify_generation(recovered.head.generation_root)
        assert manifest.generation_root == item.generation_root
        with store.pin("dataset:crash") as lease:
            assert lease.read_payload("source") == b"one\n"


def test_recovery_failure_injection_never_mutates_a_valid_head(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:recovery-fault")

    def inject(name: str):
        if name == "during_recovery":
            raise InjectedFailure(name)

    store.failure_injector = inject
    with pytest.raises(InjectedFailure):
        store.recover("dataset:recovery-fault")
    store.failure_injector = None
    head = store.current_head("dataset:recovery-fault")
    assert head is not None
    assert head.generation_root == first.manifest.generation_root


def test_failed_second_publication_preserves_a_complete_head(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:failure")

    fired = False

    def inject(name: str):
        nonlocal fired
        if name == "before_current_head_cas" and not fired:
            fired = True
            raise OSError("simulated disk or permission failure")

    store.failure_injector = inject
    second = candidate(
        store,
        "dataset:failure",
        b"id,name\n2,Grace\n",
        parent=first.manifest.generation_root,
    )
    with pytest.raises(OSError):
        store.publish(
            second,
            expected_current_root=first.manifest.generation_root,
        )

    store.failure_injector = None
    recovered = store.recover("dataset:failure")
    assert recovered.head is not None
    manifest, _ = store.verify_generation(recovered.head.generation_root)
    assert manifest.generation_root in {
        first.manifest.generation_root,
        second.manifest.generation_root,
    }


def test_reader_pinned_to_n_remains_stable_while_n_plus_one_publishes(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:pins")
    lease = store.pin("dataset:pins")
    second = candidate(
        store,
        "dataset:pins",
        b"id,name\n2,Grace\n",
        parent=first.manifest.generation_root,
    )
    published = store.publish(
        second,
        expected_current_root=first.manifest.generation_root,
    )
    assert store.current_head("dataset:pins").generation_root == published.manifest.generation_root
    assert lease.generation_root == first.manifest.generation_root
    assert lease.read_payload("source") == b"id,name\n1,Ada\n"
    with pytest.raises(GenerationStoreError):
        store.retire("dataset:pins", first.manifest.generation_root)
    lease.close()
    retired = store.retire("dataset:pins", first.manifest.generation_root)
    assert retired.state.value == "retired"


def test_two_publishers_with_one_expected_head_cannot_overwrite_silently(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:cas")
    expected = first.manifest.generation_root
    candidates = (
        candidate(store, "dataset:cas", b"a\n", parent=expected),
        candidate(store, "dataset:cas", b"b\n", parent=expected),
    )

    def attempt(item):
        try:
            return ("ok", store.publish(item, expected_current_root=expected))
        except GenerationPublicationConflict as exc:
            return ("conflict", exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, candidates))
    assert sorted(kind for kind, _ in results) == ["conflict", "ok"]
    head = store.current_head("dataset:cas")
    assert head.generation_root in {item.generation_root for item in candidates}


def test_corrupt_payload_and_manifest_fail_closed(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:corruption")
    source_identity = next(
        item for item in first.manifest.payloads if item.name == "source"
    )
    store._object_path(source_identity.content_root).write_bytes(b"corrupt")
    with pytest.raises(GenerationStoreError) as error:
        store.verify_generation(first.manifest.generation_root)
    assert error.value.fault is GenerationFault.INTEGRITY_FAILURE

    clean = AtomicGenerationStore(tmp_path / "manifest")
    second = publish_first(clean, "dataset:manifest")
    path = clean._generation_dir(second.manifest.generation_root) / "manifest.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(Exception):
        clean.verify_generation(second.manifest.generation_root)


def test_recovery_repairs_torn_current_deterministically_and_idempotently(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:recover")
    current = store._head_path("dataset:recover")
    current.write_bytes(b'{"torn":')
    first_recovery = store.recover("dataset:recover")
    second_recovery = store.recover("dataset:recover")
    assert first_recovery.repaired is True
    assert first_recovery.head.generation_root == first.manifest.generation_root
    assert second_recovery.repaired is False
    assert second_recovery.head == first_recovery.head


def test_recovery_ignores_only_a_torn_final_log_record(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:log")
    log = store._publication_log_path("dataset:log")
    with log.open("ab") as handle:
        handle.write(b'{"contract_id":')
    result = store.recover("dataset:log")
    assert result.ignored_torn_tail is True
    assert result.head.generation_root == first.manifest.generation_root
    assert log.read_bytes().endswith(b"\n")
    assert b'{"contract_id":' not in log.read_bytes().splitlines()[-1]


def test_complete_invalid_log_record_is_not_silently_ignored(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    publish_first(store, "dataset:bad-log")
    log = store._publication_log_path("dataset:bad-log")
    with log.open("ab") as handle:
        handle.write(b'{"complete":"but-invalid"}\n')
    with pytest.raises(Exception):
        store.recover("dataset:bad-log")


def test_rollback_is_append_only_and_restores_exact_old_generation(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:rollback")
    second_candidate = candidate(
        store,
        "dataset:rollback",
        b"id,name\n2,Grace\n",
        parent=first.manifest.generation_root,
    )
    second = store.publish(
        second_candidate,
        expected_current_root=first.manifest.generation_root,
    )
    rolled = store.rollback(
        "dataset:rollback",
        first.manifest.generation_root,
        expected_current_root=second.manifest.generation_root,
    )
    assert rolled.record.action.value == "rollback"
    assert rolled.record.publication_sequence == 3
    with store.pin("dataset:rollback") as lease:
        assert lease.generation_root == first.manifest.generation_root
        assert lease.read_payload("source") == b"id,name\n1,Ada\n"


def test_current_generation_cannot_be_retired(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:current")
    with pytest.raises(GenerationStoreError):
        store.retire("dataset:current", first.manifest.generation_root)


def test_parent_must_equal_current(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:parent")
    wrong = candidate(
        store,
        "dataset:parent",
        b"wrong\n",
        parent="sha256:" + "f" * 64,
    )
    with pytest.raises(GenerationPublicationConflict):
        store.publish(wrong, expected_current_root=first.manifest.generation_root)


def test_namespace_isolation(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    a = publish_first(store, "dataset:a")
    b = publish_first(store, "dataset:b")
    assert a.manifest.generation_root != b.manifest.generation_root
    assert store.current_head("dataset:a").generation_root == a.manifest.generation_root
    assert store.current_head("dataset:b").generation_root == b.manifest.generation_root
    with pytest.raises(GenerationStoreError):
        store.pin("dataset:a", b.manifest.generation_root)


def test_list_generations_returns_only_verified_generations(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:list")
    junk = store.generations_dir / ("0" * 64)
    junk.mkdir()
    assert store.list_generations("dataset:list") == (first.manifest.generation_root,)


def test_new_store_instance_can_pin_old_generation_after_restart(tmp_path: Path):
    store = AtomicGenerationStore(tmp_path)
    first = publish_first(store, "dataset:restart")
    second = store.publish(
        candidate(
            store,
            "dataset:restart",
            b"id,name\n2,Grace\n",
            parent=first.manifest.generation_root,
        ),
        expected_current_root=first.manifest.generation_root,
    )
    restarted = AtomicGenerationStore(tmp_path)
    assert restarted.current_head("dataset:restart").generation_root == second.manifest.generation_root
    with restarted.pin("dataset:restart", first.manifest.generation_root) as lease:
        assert lease.read_payload("source") == b"id,name\n1,Ada\n"

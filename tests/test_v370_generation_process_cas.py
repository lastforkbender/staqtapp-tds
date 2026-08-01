from __future__ import annotations

import multiprocessing
from pathlib import Path
from queue import Empty

from staqtapp_tds.generation.generation_store import (
    AtomicGenerationStore,
    GenerationPublicationConflict,
)


def _candidate(
    store: AtomicGenerationStore,
    namespace: str,
    source: bytes,
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
    )


def _publish_worker(
    root: str,
    namespace: str,
    expected_generation_root: str,
    expected_head_root: str,
    source: bytes,
    start_event,
    result_queue,
) -> None:
    store = AtomicGenerationStore(root)
    item = _candidate(store, namespace, source, expected_generation_root)
    if not start_event.wait(30):
        result_queue.put(("error", "start-event-timeout"))
        return
    try:
        published = store.publish(item, expected_head_root=expected_head_root)
    except GenerationPublicationConflict:
        result_queue.put(("conflict", item.generation_root))
    except BaseException as exc:  # child-process evidence must preserve the defect
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))
    else:
        result_queue.put(("ok", published.manifest.generation_root))


def test_two_process_publishers_with_one_expected_head_have_one_winner(
    tmp_path: Path,
) -> None:
    namespace = "dataset:process-cas"
    store = AtomicGenerationStore(tmp_path)
    first = store.publish(
        _candidate(store, namespace, b"baseline\n", None),
        expected_head_root=None,
    )
    expected_generation = first.manifest.generation_root
    expected_head = first.head.head_root

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_publish_worker,
            args=(
                str(tmp_path),
                namespace,
                expected_generation,
                expected_head,
                source,
                start_event,
                result_queue,
            ),
        )
        for source in (b"candidate-a\n", b"candidate-b\n")
    ]
    for process in processes:
        process.start()
    start_event.set()

    for process in processes:
        process.join(60)
        assert process.exitcode == 0

    results = []
    for _ in processes:
        try:
            results.append(result_queue.get(timeout=10))
        except Empty as exc:
            raise AssertionError("child publisher did not report a result") from exc

    assert sorted(kind for kind, _ in results) == ["conflict", "ok"]
    winner = next(root for kind, root in results if kind == "ok")
    head = AtomicGenerationStore(tmp_path).current_head(namespace)
    assert head is not None
    assert head.generation_root == winner

"""Deterministic executable audit for the v3.7 Generation Authority.

The audit deliberately emits only content-free roots, counters, and gate
results.  It exercises the installed public API against a fresh authority
root; it is not a fixture that bypasses publication or reader pinning.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from typing import Any, ContextManager

from .csv import (
    build_csv_generation_candidate,
    open_csv_generation,
    publish_csv_generation,
)
from .generation_contract import bytes_root, canonical_json_bytes
from .generation_store import (
    AtomicGenerationStore,
    GenerationPublicationConflict,
    GenerationStoreError,
)


AUDIT_NAMESPACE = "audit:v370-generation-authority"
_FIRST_SOURCE = b"id,value\r\n1,foundation\r\n"
_SECOND_SOURCE = b"id,value\r\n1,foundation\r\n2,authority\r\n"
_STALE_SOURCE = b"id,value\r\n1,stale-writer\r\n"


def _root(label: str) -> str:
    return bytes_root(label.encode("ascii"))


def run_generation_authority_audit(root: str | Path) -> dict[str, Any]:
    """Run the bounded v3.7 audit and return its canonical content-free result."""

    store = AtomicGenerationStore(root)
    empty = store.recover(AUDIT_NAMESPACE)
    if empty.head is not None:
        raise GenerationStoreError("audit namespace must start without a CURRENT head")

    first = build_csv_generation_candidate(
        store,
        namespace=AUDIT_NAMESPACE,
        source=_FIRST_SOURCE,
        closure_root=_root("v370-audit:first:closure"),
        evidence_root=_root("v370-audit:first:evidence"),
        chunk_bytes=8,
        oracle_block_bytes=3,
    )
    first_publication = publish_csv_generation(
        store,
        first,
        expected_head_root=None,
    )
    pinned_first = open_csv_generation(store, AUDIT_NAMESPACE)

    second = build_csv_generation_candidate(
        store,
        namespace=AUDIT_NAMESPACE,
        source=_SECOND_SOURCE,
        closure_root=_root("v370-audit:second:closure"),
        evidence_root=_root("v370-audit:second:evidence"),
        parent_generation_root=first.generation_root,
        chunk_bytes=8,
        oracle_block_bytes=5,
    )
    second_publication = publish_csv_generation(
        store,
        second,
        expected_head_root=first_publication.head.head_root,
    )

    pin_stability = pinned_first.read_source() == _FIRST_SOURCE
    with open_csv_generation(store, AUDIT_NAMESPACE) as current:
        current_round_trip = current.read_source() == _SECOND_SOURCE

    stale = build_csv_generation_candidate(
        store,
        namespace=AUDIT_NAMESPACE,
        source=_STALE_SOURCE,
        closure_root=_root("v370-audit:stale:closure"),
        evidence_root=_root("v370-audit:stale:evidence"),
        parent_generation_root=first.generation_root,
        chunk_bytes=8,
    )
    stale_cas_rejected = False
    try:
        publish_csv_generation(
            store,
            stale,
            expected_head_root=first_publication.head.head_root,
        )
    except GenerationPublicationConflict:
        stale_cas_rejected = True

    orphan_pin_rejected = False
    try:
        store.pin(AUDIT_NAMESPACE, stale.generation_root)
    except GenerationStoreError:
        orphan_pin_rejected = True

    pinned_first.close()
    rollback = store.rollback(
        AUDIT_NAMESPACE,
        first.generation_root,
        expected_head_root=second_publication.head.head_root,
    )
    store.retire(AUDIT_NAMESPACE, second.generation_root)
    retired_pin_rejected = False
    try:
        store.pin(AUDIT_NAMESPACE, second.generation_root)
    except GenerationStoreError:
        retired_pin_rejected = True

    first_recovery = store.recover(AUDIT_NAMESPACE)
    second_recovery = store.recover(AUDIT_NAMESPACE)
    recovery_idempotent = first_recovery == second_recovery
    head = store.current_head(AUDIT_NAMESPACE)

    gates = {
        "current_round_trip": current_round_trip,
        "orphan_pin_rejected": orphan_pin_rejected,
        "pin_stability": pin_stability,
        "recovery_idempotent": recovery_idempotent,
        "retired_pin_rejected": retired_pin_rejected,
        "rollback_restored_first": bool(
            head is not None
            and head.generation_root == first.generation_root
            and rollback.head.head_root == head.head_root
        ),
        "stale_head_cas_rejected": stale_cas_rejected,
    }
    if not all(gates.values()):
        failed = ", ".join(name for name, passed in gates.items() if not passed)
        raise GenerationStoreError(f"generation audit gates failed: {failed}")

    return {
        "audit": "tds-v370-generation-authority-audit-v1",
        "authority": "staqtapp_tds.generation.AtomicGenerationStore",
        "source_content_in_report": False,
        "gates": gates,
        "namespace": AUDIT_NAMESPACE,
        "publication_records": second_recovery.valid_records,
        "roots": {
            "first_generation": first.generation_root,
            "final_head": head.head_root if head is not None else None,
            "second_generation": second.generation_root,
            "stale_unpublished_generation": stale.generation_root,
        },
        "status": "pass",
    }


def _root_context(path: str | None) -> ContextManager[str | Path]:
    if path is not None:
        return nullcontext(Path(path))
    return tempfile.TemporaryDirectory(prefix="tds-v370-generation-audit-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic v3.7 Generation Authority audit.",
    )
    parser.add_argument(
        "--root",
        help="fresh authority root (a temporary directory is used when omitted)",
    )
    args = parser.parse_args(argv)
    with _root_context(args.root) as root:
        result = run_generation_authority_audit(root)
    print(canonical_json_bytes(result).decode("ascii"))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the script
    raise SystemExit(main())

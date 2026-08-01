"""Public v3.7 Atomic Generation API and engineer command surface.

The module exposes immutable CSV generation contracts, the deterministic
reference store, and the durable cross-process publication controller. It does
not import or execute optional native extensions, learned ranking, Eaglegate, or
model runtimes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

from staqtapp_tds.csv_layer.generation_contract import (
    CSV_GENERATION_AUTHORITY,
    CSV_GENERATION_CHECKSUM_ALGORITHM,
    CSV_GENERATION_CONTRACT_ID,
    CSV_GENERATION_FORMAT_VERSION,
    CSV_GENERATION_QUALIFICATION_LIMITS,
    CSVChunkDescriptor,
    CSVGenerationAuthorityBoundary,
    CSVGenerationContractError,
    CSVGenerationFault,
    CSVGenerationIdentity,
    CSVGenerationLimits,
    CSVGenerationManifest,
    CSVGenerationReceipt,
    CSVGenerationState,
    chunk_sequence_root,
    validate_atomic_publication,
    validate_manifest,
    validate_pinned_generation,
    validate_receipt_transition,
)
from staqtapp_tds.csv_layer.generation_runtime import (
    CSV_DURABLE_PUBLICATION_AUTHORITY,
    CSV_DURABLE_PUBLICATION_CONTRACT_ID,
    CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
    CSV_DURABLE_PUBLICATION_MAX_RECOVERY_RECORDS,
    CSVGenerationRetirement,
    CSVPublicationAbort,
    CSVPublicationAuthorityBoundary,
    CSVPublicationCommit,
    CSVPublicationIntent,
    CSVPublicationOperation,
    CSVPublicationRecoveryDisposition,
    CSVPublicationRecoveryReport,
    DurableAtomicCSVGenerationStore,
)
from staqtapp_tds.csv_layer.generation_store import (
    CSV_GENERATION_FAULT_POINTS,
    CSV_REFERENCE_PARSER_ID,
    CSV_REFERENCE_PARSER_ROOT,
    AtomicCSVGenerationStore,
    CSVGenerationLease,
    CSVGenerationVerification,
    CSVRowAnchorRecord,
    CSVStreamProfile,
    CurrentCSVGeneration,
    InjectedGenerationCrash,
    StagedCSVGeneration,
    decode_row_anchors,
    decode_row_offsets,
)

GENERATION_AUDIT_CONTRACT_ID = "tds-v370-generation-audit-v1"
_AUDIT_DOMAIN = b"STAQTAPP-TDS\x00V370-GENERATION-AUDIT\x00V1\x00"


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _audit_root(domain: str, value: dict[str, Any]) -> str:
    material = (
        _AUDIT_DOMAIN
        + domain.encode("ascii")
        + b"\x00"
        + _canonical_json_bytes(value)
    )
    return "sha256:" + hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class GenerationStoreStatus:
    """Content-free read-only status for one generation-store root."""

    store_exists: bool
    current_generation_root: str
    current_manifest_root: str
    current_published_receipt_root: str
    current_verified: bool
    object_count: int
    staged_manifest_count: int
    published_generation_count: int
    receipt_count: int
    publication_intent_count: int
    publication_commit_count: int
    publication_abort_count: int
    retirement_count: int

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": GENERATION_AUDIT_CONTRACT_ID,
            **asdict(self),
            "raw_content_included": False,
            "semantic_authority": False,
            "model_authority": False,
            "activation_authority": False,
        }

    @property
    def status_root(self) -> str:
        return _audit_root("store-status", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ReferenceGenerationAuditReport:
    """Deterministic end-to-end reference evidence."""

    old_generation_root: str
    new_generation_root: str
    rollback_commit_root: str
    retirement_root: str
    recovery_report_root: str
    final_current_generation_root: str
    old_reader_stable: bool
    exact_source_round_trip: bool
    cas_enforced: bool
    retired_generation_blocked_from_rollback: bool

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": GENERATION_AUDIT_CONTRACT_ID,
            "csv_generation_contract_id": CSV_GENERATION_CONTRACT_ID,
            "durable_publication_contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
            **asdict(self),
            "original_bytes_authoritative": True,
            "raw_content_included": False,
            "learned_serving_included": False,
            "eaglegate_included": False,
            "semantic_authority": False,
            "model_authority": False,
            "activation_authority": False,
        }

    @property
    def report_root(self) -> str:
        return _audit_root("reference-report", self.canonical_dict())


def inspect_generation_store(
    root: str | Path,
    *,
    verify_current: bool = False,
) -> GenerationStoreStatus:
    """Read content-free store status without changing CURRENT or recovery records."""

    path = Path(root)
    if not path.exists():
        return GenerationStoreStatus(
            store_exists=False,
            current_generation_root="",
            current_manifest_root="",
            current_published_receipt_root="",
            current_verified=False,
            object_count=0,
            staged_manifest_count=0,
            published_generation_count=0,
            receipt_count=0,
            publication_intent_count=0,
            publication_commit_count=0,
            publication_abort_count=0,
            retirement_count=0,
        )
    store = DurableAtomicCSVGenerationStore(path)
    current = store.read_current()
    verified = False
    if current is not None and verify_current:
        with store.open_current():
            verified = True

    def count(directory: Path, pattern: str) -> int:
        return sum(1 for item in directory.glob(pattern) if item.is_file())

    return GenerationStoreStatus(
        store_exists=True,
        current_generation_root="" if current is None else current.generation_root,
        current_manifest_root="" if current is None else current.manifest_root,
        current_published_receipt_root=(
            "" if current is None else current.published_receipt_root
        ),
        current_verified=verified,
        object_count=count(store.objects_dir, "*"),
        staged_manifest_count=count(store.staging_dir, "*.json"),
        published_generation_count=count(store.generations_dir, "*/manifest.json"),
        receipt_count=count(store.receipts_dir, "*.json"),
        publication_intent_count=count(store.intents_dir, "*.json"),
        publication_commit_count=count(store.commits_dir, "*.json"),
        publication_abort_count=count(store.aborts_dir, "*.json"),
        retirement_count=count(store.retirements_dir, "*.json"),
    )


def run_reference_generation_audit() -> ReferenceGenerationAuditReport:
    """Exercise stage, publish, pin, CAS, rollback, retirement, and recovery."""

    limits = CSVGenerationLimits(
        max_source_bytes=16_384,
        max_chunk_bytes=128,
        max_chunks=512,
        max_rows=512,
        max_closure_nodes=1_024,
        max_closure_edges=4_096,
    )
    old_bytes = b"id,value\r\n1,old\r\n"
    new_bytes = b"id,value\r\n1,new\r\n2,complete\r\n"
    with TemporaryDirectory(prefix="tds-v370-audit-") as temporary:
        store = DurableAtomicCSVGenerationStore(temporary)
        old = store.stage(
            "dataset:reference-audit",
            (old_bytes[:1], old_bytes[1:7], old_bytes[7:]),
            chunk_bytes=5,
            limits=limits,
        )
        store.publish(old, expected_current_manifest_root="")
        old_lease = store.open_current()
        new = store.stage(
            "dataset:reference-audit",
            (new_bytes[:2], new_bytes[2:11], new_bytes[11:]),
            chunk_bytes=5,
            limits=limits,
            parent_generation_root=old.generation_root,
        )
        store.publish(new, expected_current_manifest_root=old.manifest_root)
        old_reader_stable = old_lease.read_source() == old_bytes
        exact_round_trip = False
        with store.open_current() as current:
            exact_round_trip = current.read_source() == new_bytes
        old_lease.close()

        cas_enforced = False
        try:
            store.publish(new, expected_current_manifest_root=old.manifest_root)
        except CSVGenerationContractError as exc:
            cas_enforced = exc.fault is CSVGenerationFault.PUBLICATION_CONFLICT

        rollback = store.rollback(
            old.generation_root,
            expected_current_manifest_root=new.manifest_root,
        )
        retirement = store.retire_generation(new.generation_root)
        retired_blocked = False
        try:
            store.rollback(new.generation_root)
        except CSVGenerationContractError as exc:
            retired_blocked = exc.fault is CSVGenerationFault.AUTHORITY_REJECTED
        recovery = store.recover_publication()
        with store.open_current() as current:
            final_root = current.generation_root

    return ReferenceGenerationAuditReport(
        old_generation_root=old.generation_root,
        new_generation_root=new.generation_root,
        rollback_commit_root=rollback.commit_root,
        retirement_root=retirement.retirement_root,
        recovery_report_root=recovery.report_root,
        final_current_generation_root=final_root,
        old_reader_stable=old_reader_stable,
        exact_source_round_trip=exact_round_trip,
        cas_enforced=cas_enforced,
        retired_generation_blocked_from_rollback=retired_blocked,
    )


def _emit(value: dict[str, Any], *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(value, sort_keys=True, indent=2))
    else:
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-generation")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="read content-free store status")
    status.add_argument("--root", required=True)
    status.add_argument("--verify-current", action="store_true")

    recover = subparsers.add_parser(
        "recover", help="reconcile interrupted publication intent records"
    )
    recover.add_argument("--root", required=True)

    subparsers.add_parser(
        "reference", help="run the deterministic self-contained v3.7 audit"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            status = inspect_generation_store(
                args.root, verify_current=args.verify_current
            )
            payload = status.canonical_dict()
            payload["status_root"] = status.status_root
        elif args.command == "recover":
            report = DurableAtomicCSVGenerationStore(args.root).recover_publication()
            payload = report.canonical_dict()
            payload["report_root"] = report.report_root
        else:
            report = run_reference_generation_audit()
            payload = report.canonical_dict()
            payload["report_root"] = report.report_root
    except (CSVGenerationContractError, OSError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "activation_authority": False,
            },
            pretty=args.pretty,
        )
        return 1
    payload["ok"] = True
    _emit(payload, pretty=args.pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [name for name in globals() if name.startswith("CSV")]
__all__ += [
    "AtomicCSVGenerationStore",
    "DurableAtomicCSVGenerationStore",
    "GenerationStoreStatus",
    "InjectedGenerationCrash",
    "ReferenceGenerationAuditReport",
    "StagedCSVGeneration",
    "chunk_sequence_root",
    "decode_row_anchors",
    "decode_row_offsets",
    "inspect_generation_store",
    "run_reference_generation_audit",
    "validate_atomic_publication",
    "validate_manifest",
    "validate_pinned_generation",
    "validate_receipt_transition",
]

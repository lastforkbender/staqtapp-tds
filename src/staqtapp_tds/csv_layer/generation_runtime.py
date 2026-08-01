"""Crash-recoverable publication controller for atomic CSV generations.

The reference generation store proves deterministic byte, chunk, row-offset,
row-anchor, closure, and lease semantics. This module adds the controller
boundary needed for multi-process publication, recovery, rollback, and
retirement without granting semantic, model, learned-write, Browser, or Studio
authority.

A generation is active only when the atomically replaced ``CURRENT`` pointer
references its exact manifest and published receipt. Standalone receipts or
publication intents are evidence; they are never activation authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Mapping

from staqtapp_tds.csv_layer.generation_contract import (
    CSV_GENERATION_CONTRACT_ID,
    CSV_GENERATION_FORMAT_VERSION,
    CSVGenerationContractError,
    CSVGenerationFault,
    CSVGenerationReceipt,
    CSVGenerationState,
    validate_receipt_transition,
)
from staqtapp_tds.csv_layer.generation_store import (
    AtomicCSVGenerationStore,
    CurrentCSVGeneration,
    StagedCSVGeneration,
    _atomic_replace,
    _atomic_write_exact,
    _canonical_json_bytes,
    _content_root,
    _decode_canonical_json,
    _root_hex,
)

CSV_DURABLE_PUBLICATION_FORMAT_VERSION = 1
CSV_DURABLE_PUBLICATION_CONTRACT_ID = "tds-csv-generation-publication-v1"
CSV_DURABLE_PUBLICATION_MAX_RECOVERY_RECORDS = 4096
_ROOT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLICATION_DOMAIN = b"STAQTAPP-TDS\x00CSV-GENERATION-PUBLICATION\x00V1\x00"


class CSVPublicationOperation(str, Enum):
    """Stable controller operations."""

    PUBLISH = "publish"
    ROLLBACK = "rollback"


class CSVPublicationRecoveryDisposition(str, Enum):
    """Stable recovery classification for an interrupted intent."""

    COMPLETED = "completed"
    ABORTED_BEFORE_CURRENT = "aborted_before_current"


def _validate_root(name: str, value: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not isinstance(value, str) or not _ROOT_PATTERN.fullmatch(value):
        raise CSVGenerationContractError(
            f"{name} must be an exact lowercase sha256:<64-hex> root",
            fault=CSVGenerationFault.IDENTITY_MISMATCH,
        )
    return value


def _canonical_root(domain: str, payload: Mapping[str, Any]) -> str:
    if not isinstance(domain, str) or not domain or not domain.isascii():
        raise CSVGenerationContractError("publication root domain must be ASCII")
    material = (
        _PUBLICATION_DOMAIN
        + domain.encode("ascii")
        + b"\x00"
        + _canonical_json_bytes(payload)
    )
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _require_exact_keys(value: Mapping[str, Any], required: set[str], name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != required:
        raise CSVGenerationContractError(
            f"{name} has unknown or missing fields",
            fault=CSVGenerationFault.NONCANONICAL,
        )


@dataclass(frozen=True, slots=True)
class CSVPublicationAuthorityBoundary:
    """Non-widenable authority declaration for the durable controller."""

    interprocess_lock_required: bool = True
    compare_and_swap_required: bool = True
    current_pointer_is_activation_authority: bool = True
    receipts_are_activation_authority: bool = False
    may_commit_semantics: bool = False
    may_rank_traces: bool = False
    may_train_models: bool = False
    may_activate_models: bool = False
    may_accept_learned_writes: bool = False
    browser_or_studio_may_publish: bool = False

    def __post_init__(self) -> None:
        expected = {
            "interprocess_lock_required": True,
            "compare_and_swap_required": True,
            "current_pointer_is_activation_authority": True,
            "receipts_are_activation_authority": False,
            "may_commit_semantics": False,
            "may_rank_traces": False,
            "may_train_models": False,
            "may_activate_models": False,
            "may_accept_learned_writes": False,
            "browser_or_studio_may_publish": False,
        }
        if asdict(self) != expected:
            raise CSVGenerationContractError(
                "durable publication authority cannot be widened",
                fault=CSVGenerationFault.AUTHORITY_REJECTED,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
            "format_version": CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return _canonical_root("authority", self.canonical_dict())


CSV_DURABLE_PUBLICATION_AUTHORITY = CSVPublicationAuthorityBoundary()


@dataclass(frozen=True, slots=True)
class CSVPublicationIntent:
    """Durable intent written after CAS succeeds and before CURRENT changes."""

    operation: CSVPublicationOperation
    generation_root: str
    manifest_root: str
    published_receipt_root: str
    published_receipt_previous_root: str
    expected_current_manifest_root: str
    previous_current_generation_root: str
    previous_current_manifest_root: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation, CSVPublicationOperation):
            raise CSVGenerationContractError("operation must be CSVPublicationOperation")
        for name in (
            "generation_root",
            "manifest_root",
            "published_receipt_root",
            "published_receipt_previous_root",
        ):
            _validate_root(name, getattr(self, name))
        for name in (
            "expected_current_manifest_root",
            "previous_current_generation_root",
            "previous_current_manifest_root",
        ):
            _validate_root(name, getattr(self, name), allow_empty=True)
        previous_pair = (
            self.previous_current_generation_root,
            self.previous_current_manifest_root,
        )
        if (previous_pair[0] == "") != (previous_pair[1] == ""):
            raise CSVGenerationContractError(
                "previous CURRENT generation and manifest roots must be both empty or both set",
                fault=CSVGenerationFault.NONCANONICAL,
            )
        if self.expected_current_manifest_root != self.previous_current_manifest_root:
            raise CSVGenerationContractError(
                "intent expected root must equal the observed previous CURRENT root",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
            "format_version": CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
            "operation": self.operation.value,
            "generation_root": self.generation_root,
            "manifest_root": self.manifest_root,
            "published_receipt_root": self.published_receipt_root,
            "published_receipt_previous_root": self.published_receipt_previous_root,
            "expected_current_manifest_root": self.expected_current_manifest_root,
            "previous_current_generation_root": self.previous_current_generation_root,
            "previous_current_manifest_root": self.previous_current_manifest_root,
        }

    @property
    def intent_root(self) -> str:
        return _canonical_root("intent", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CSVPublicationCommit:
    """Append-only evidence that one intent reached an atomic CURRENT value."""

    intent_root: str
    operation: CSVPublicationOperation
    generation_root: str
    manifest_root: str
    published_receipt_root: str
    previous_current_generation_root: str
    previous_current_manifest_root: str
    current_pointer_root: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation, CSVPublicationOperation):
            raise CSVGenerationContractError("operation must be CSVPublicationOperation")
        for name in (
            "intent_root",
            "generation_root",
            "manifest_root",
            "published_receipt_root",
            "current_pointer_root",
        ):
            _validate_root(name, getattr(self, name))
        for name in (
            "previous_current_generation_root",
            "previous_current_manifest_root",
        ):
            _validate_root(name, getattr(self, name), allow_empty=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
            "format_version": CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
            "intent_root": self.intent_root,
            "operation": self.operation.value,
            "generation_root": self.generation_root,
            "manifest_root": self.manifest_root,
            "published_receipt_root": self.published_receipt_root,
            "previous_current_generation_root": self.previous_current_generation_root,
            "previous_current_manifest_root": self.previous_current_manifest_root,
            "current_pointer_root": self.current_pointer_root,
        }

    @property
    def commit_root(self) -> str:
        return _canonical_root("commit", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CSVPublicationAbort:
    """Append-only evidence that an intent never became CURRENT."""

    intent_root: str
    disposition: CSVPublicationRecoveryDisposition
    observed_current_generation_root: str
    observed_current_manifest_root: str

    def __post_init__(self) -> None:
        _validate_root("intent_root", self.intent_root)
        if self.disposition is not CSVPublicationRecoveryDisposition.ABORTED_BEFORE_CURRENT:
            raise CSVGenerationContractError("invalid publication abort disposition")
        _validate_root(
            "observed_current_generation_root",
            self.observed_current_generation_root,
            allow_empty=True,
        )
        _validate_root(
            "observed_current_manifest_root",
            self.observed_current_manifest_root,
            allow_empty=True,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
            "format_version": CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
            "intent_root": self.intent_root,
            "disposition": self.disposition.value,
            "observed_current_generation_root": self.observed_current_generation_root,
            "observed_current_manifest_root": self.observed_current_manifest_root,
        }

    @property
    def abort_root(self) -> str:
        return _canonical_root("abort", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CSVGenerationRetirement:
    """Durable retirement marker; retirement never deletes generation bytes."""

    generation_root: str
    manifest_root: str
    retired_receipt_root: str
    published_receipt_root: str

    def __post_init__(self) -> None:
        for name in (
            "generation_root",
            "manifest_root",
            "retired_receipt_root",
            "published_receipt_root",
        ):
            _validate_root(name, getattr(self, name))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
            "format_version": CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def retirement_root(self) -> str:
        return _canonical_root("retirement", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CSVPublicationRecoveryReport:
    """Content-free deterministic recovery evidence."""

    current_generation_root: str
    current_manifest_root: str
    current_verified: bool
    completed_intent_roots: tuple[str, ...]
    aborted_intent_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_root(
            "current_generation_root", self.current_generation_root, allow_empty=True
        )
        _validate_root(
            "current_manifest_root", self.current_manifest_root, allow_empty=True
        )
        if (self.current_generation_root == "") != (self.current_manifest_root == ""):
            raise CSVGenerationContractError(
                "recovery CURRENT roots must be both empty or both set"
            )
        for values in (self.completed_intent_roots, self.aborted_intent_roots):
            if not isinstance(values, tuple):
                raise CSVGenerationContractError("recovery roots must be tuples")
            for value in values:
                _validate_root("recovery intent root", value)
            if tuple(sorted(values)) != values or len(set(values)) != len(values):
                raise CSVGenerationContractError(
                    "recovery roots must be unique and canonically sorted",
                    fault=CSVGenerationFault.NONCANONICAL,
                )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
            "format_version": CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
            "current_generation_root": self.current_generation_root,
            "current_manifest_root": self.current_manifest_root,
            "current_verified": self.current_verified,
            "completed_intent_roots": list(self.completed_intent_roots),
            "aborted_intent_roots": list(self.aborted_intent_roots),
            "activation_authority": False,
            "semantic_authority": False,
            "model_authority": False,
        }

    @property
    def report_root(self) -> str:
        return _canonical_root("recovery-report", self.canonical_dict())


class _InterprocessPublicationLock:
    """One-byte advisory lock with POSIX and Windows implementations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._descriptor: int | None = None

    def __enter__(self) -> "_InterprocessPublicationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        self._descriptor = descriptor
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\x00")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":  # pragma: no cover - exercised by Windows CI
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":  # pragma: no cover - exercised by Windows CI
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


class DurableAtomicCSVGenerationStore(AtomicCSVGenerationStore):
    """Reference store plus cross-process CAS and recoverable publication intent."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        super().__init__(root)
        self.control_dir = self.root / "control"
        self.intents_dir = self.control_dir / "intents"
        self.commits_dir = self.control_dir / "commits"
        self.aborts_dir = self.control_dir / "aborts"
        self.retirements_dir = self.control_dir / "retirements"
        for directory in (
            self.intents_dir,
            self.commits_dir,
            self.aborts_dir,
            self.retirements_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.publication_lock_path = self.control_dir / "publication.lock"

    @contextmanager
    def _interprocess_lock(self) -> Iterator[None]:
        with _InterprocessPublicationLock(self.publication_lock_path):
            yield

    @staticmethod
    def _record_wrapper(
        kind: str, root_name: str, root: str, value: Mapping[str, Any]
    ) -> bytes:
        return _canonical_json_bytes(
            {
                "contract_id": CSV_DURABLE_PUBLICATION_CONTRACT_ID,
                "format_version": CSV_DURABLE_PUBLICATION_FORMAT_VERSION,
                "kind": kind,
                root_name: root,
                "value": value,
            }
        )

    @staticmethod
    def _decode_record(
        data: bytes,
        *,
        kind: str,
        root_name: str,
    ) -> tuple[str, Mapping[str, Any]]:
        wrapper = _decode_canonical_json(data)
        _require_exact_keys(
            wrapper,
            {"contract_id", "format_version", "kind", root_name, "value"},
            kind,
        )
        if wrapper["contract_id"] != CSV_DURABLE_PUBLICATION_CONTRACT_ID:
            raise CSVGenerationContractError("publication record contract mismatch")
        if wrapper["format_version"] != CSV_DURABLE_PUBLICATION_FORMAT_VERSION:
            raise CSVGenerationContractError("publication record format mismatch")
        if wrapper["kind"] != kind:
            raise CSVGenerationContractError("publication record kind mismatch")
        root = wrapper[root_name]
        _validate_root(root_name, root)
        value = wrapper["value"]
        if not isinstance(value, Mapping):
            raise CSVGenerationContractError("publication record value is malformed")
        return root, value

    def _intent_path(self, intent_root: str) -> Path:
        return self.intents_dir / f"{_root_hex(intent_root)}.json"

    def _commit_path(self, intent_root: str) -> Path:
        return self.commits_dir / f"{_root_hex(intent_root)}.json"

    def _abort_path(self, intent_root: str) -> Path:
        return self.aborts_dir / f"{_root_hex(intent_root)}.json"

    def _retirement_path(self, generation_root: str) -> Path:
        return self.retirements_dir / f"{_root_hex(generation_root)}.json"

    def _write_intent(self, intent: CSVPublicationIntent) -> None:
        _atomic_write_exact(
            self._intent_path(intent.intent_root),
            self._record_wrapper(
                "publication-intent",
                "intent_root",
                intent.intent_root,
                intent.canonical_dict(),
            ),
        )

    def _load_intent(self, path: Path) -> CSVPublicationIntent:
        root, values = self._decode_record(
            path.read_bytes(), kind="publication-intent", root_name="intent_root"
        )
        raw = dict(values)
        raw.pop("contract_id", None)
        raw.pop("format_version", None)
        raw["operation"] = CSVPublicationOperation(raw["operation"])
        intent = CSVPublicationIntent(**raw)
        if intent.intent_root != root or path.stem != _root_hex(root):
            raise CSVGenerationContractError(
                "publication intent identity mismatch",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return intent

    def _write_commit(self, commit: CSVPublicationCommit) -> None:
        _atomic_write_exact(
            self._commit_path(commit.intent_root),
            self._record_wrapper(
                "publication-commit",
                "commit_root",
                commit.commit_root,
                commit.canonical_dict(),
            ),
        )

    def _load_commit(self, path: Path) -> CSVPublicationCommit:
        root, values = self._decode_record(
            path.read_bytes(), kind="publication-commit", root_name="commit_root"
        )
        raw = dict(values)
        raw.pop("contract_id", None)
        raw.pop("format_version", None)
        raw["operation"] = CSVPublicationOperation(raw["operation"])
        commit = CSVPublicationCommit(**raw)
        if commit.commit_root != root or path.stem != _root_hex(commit.intent_root):
            raise CSVGenerationContractError(
                "publication commit identity mismatch",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return commit

    def _write_abort(self, abort: CSVPublicationAbort) -> None:
        _atomic_write_exact(
            self._abort_path(abort.intent_root),
            self._record_wrapper(
                "publication-abort",
                "abort_root",
                abort.abort_root,
                abort.canonical_dict(),
            ),
        )

    def _write_retirement(self, retirement: CSVGenerationRetirement) -> None:
        _atomic_write_exact(
            self._retirement_path(retirement.generation_root),
            self._record_wrapper(
                "generation-retirement",
                "retirement_root",
                retirement.retirement_root,
                retirement.canonical_dict(),
            ),
        )

    def _read_receipt(self, receipt_root: str) -> CSVGenerationReceipt:
        path = self._receipt_path(receipt_root)
        try:
            wrapper = _decode_canonical_json(path.read_bytes())
        except OSError as exc:
            raise CSVGenerationContractError(
                "generation receipt is missing",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            ) from exc
        _require_exact_keys(
            wrapper,
            {"contract_id", "format_version", "receipt_root", "receipt"},
            "generation receipt",
        )
        if wrapper["contract_id"] != CSV_GENERATION_CONTRACT_ID:
            raise CSVGenerationContractError("generation receipt contract mismatch")
        if wrapper["format_version"] != CSV_GENERATION_FORMAT_VERSION:
            raise CSVGenerationContractError("generation receipt format mismatch")
        raw = dict(wrapper["receipt"])
        raw.pop("contract_id", None)
        raw.pop("format_version", None)
        raw["state"] = CSVGenerationState(raw["state"])
        receipt = CSVGenerationReceipt(**raw)
        if wrapper["receipt_root"] != receipt.receipt_root:
            raise CSVGenerationContractError(
                "generation receipt identity mismatch",
                fault=CSVGenerationFault.IDENTITY_MISMATCH,
            )
        return receipt

    @staticmethod
    def _receipt_chain(candidate: StagedCSVGeneration) -> tuple[
        CSVGenerationReceipt,
        CSVGenerationReceipt,
        CSVGenerationReceipt,
        CSVGenerationReceipt,
    ]:
        staging = CSVGenerationReceipt(
            candidate.generation_root,
            candidate.manifest_root,
            CSVGenerationState.STAGING,
        )
        sealed = CSVGenerationReceipt(
            candidate.generation_root,
            candidate.manifest_root,
            CSVGenerationState.SEALED,
            staging.receipt_root,
        )
        verified = CSVGenerationReceipt(
            candidate.generation_root,
            candidate.manifest_root,
            CSVGenerationState.VERIFIED,
            sealed.receipt_root,
        )
        published = CSVGenerationReceipt(
            candidate.generation_root,
            candidate.manifest_root,
            CSVGenerationState.PUBLISHED,
            verified.receipt_root,
        )
        validate_receipt_transition(staging, sealed)
        validate_receipt_transition(sealed, verified)
        validate_receipt_transition(verified, published)
        return staging, sealed, verified, published

    def _current_values(self) -> tuple[CurrentCSVGeneration | None, str, str]:
        current = self.read_current()
        if current is None:
            return None, "", ""
        return current, current.generation_root, current.manifest_root

    def _commit_for_intent(
        self,
        intent: CSVPublicationIntent,
        pointer: CurrentCSVGeneration,
    ) -> CSVPublicationCommit:
        pointer_bytes = self._pointer_bytes(pointer)
        return CSVPublicationCommit(
            intent_root=intent.intent_root,
            operation=intent.operation,
            generation_root=intent.generation_root,
            manifest_root=intent.manifest_root,
            published_receipt_root=intent.published_receipt_root,
            previous_current_generation_root=intent.previous_current_generation_root,
            previous_current_manifest_root=intent.previous_current_manifest_root,
            current_pointer_root=_content_root(pointer_bytes),
        )

    def publish(
        self,
        staged: StagedCSVGeneration | str,
        *,
        expected_current_manifest_root: str | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> CSVGenerationReceipt:
        """Verify, CAS, journal, and atomically publish one complete generation."""

        candidate = self.load_staged(staged) if isinstance(staged, str) else staged
        if not isinstance(candidate, StagedCSVGeneration):
            raise CSVGenerationContractError(
                "publish requires a staged generation or exact manifest root"
            )

        def inject(point: str) -> None:
            if fault_injector is not None:
                fault_injector(point)

        self.verify(candidate)
        inject("after_staged_verify")
        self._write_generation_wrapper(candidate)
        inject("after_manifest_write")
        staging, sealed, verified, published = self._receipt_chain(candidate)
        for receipt in (staging, sealed, verified):
            self._write_receipt(receipt)
        inject("after_verified_receipt")

        with self._publication_lock:
            with self._interprocess_lock():
                _current, previous_generation, previous_manifest = self._current_values()
                expected = (
                    previous_manifest
                    if expected_current_manifest_root is None
                    else expected_current_manifest_root
                )
                _validate_root(
                    "expected_current_manifest_root", expected, allow_empty=True
                )
                if previous_manifest != expected:
                    raise CSVGenerationContractError(
                        "CURRENT changed before durable publication",
                        fault=CSVGenerationFault.PUBLICATION_CONFLICT,
                    )
                intent = CSVPublicationIntent(
                    operation=CSVPublicationOperation.PUBLISH,
                    generation_root=candidate.generation_root,
                    manifest_root=candidate.manifest_root,
                    published_receipt_root=published.receipt_root,
                    published_receipt_previous_root=published.previous_receipt_root,
                    expected_current_manifest_root=expected,
                    previous_current_generation_root=previous_generation,
                    previous_current_manifest_root=previous_manifest,
                )
                self._write_intent(intent)
                inject("after_publication_intent")
                self._write_receipt(published)
                inject("after_published_receipt")
                pointer = CurrentCSVGeneration(
                    generation_root=candidate.generation_root,
                    manifest_root=candidate.manifest_root,
                    published_receipt_root=published.receipt_root,
                )
                inject("before_current_replace")
                _atomic_replace(self.current_path, self._pointer_bytes(pointer))
                inject("after_current_replace")
                self._write_commit(self._commit_for_intent(intent, pointer))
                inject("after_publication_commit")
        return published

    def _iter_record_paths(self, directory: Path) -> tuple[Path, ...]:
        paths = tuple(sorted(directory.glob("*.json"), key=lambda item: item.name))
        if len(paths) > CSV_DURABLE_PUBLICATION_MAX_RECOVERY_RECORDS:
            raise CSVGenerationContractError(
                "publication recovery record bound exceeded",
                fault=CSVGenerationFault.BOUND_EXCEEDED,
            )
        return paths

    @staticmethod
    def _intent_matches_current(
        intent: CSVPublicationIntent,
        current: CurrentCSVGeneration | None,
    ) -> bool:
        return bool(
            current is not None
            and current.generation_root == intent.generation_root
            and current.manifest_root == intent.manifest_root
            and current.published_receipt_root == intent.published_receipt_root
        )

    def recover_publication(self) -> CSVPublicationRecoveryReport:
        """Reconcile interrupted intents without selecting an unverified generation."""

        completed: list[str] = []
        aborted: list[str] = []
        with self._publication_lock:
            with self._interprocess_lock():
                current, current_generation, current_manifest = self._current_values()
                current_verified = False
                if current is not None:
                    staged = self.load_generation(current.generation_root)
                    if staged.manifest_root != current.manifest_root:
                        raise CSVGenerationContractError(
                            "CURRENT mixes generation and manifest identities",
                            fault=CSVGenerationFault.IDENTITY_MISMATCH,
                        )
                    self.verify(staged)
                    receipt = self._read_receipt(current.published_receipt_root)
                    if (
                        receipt.state is not CSVGenerationState.PUBLISHED
                        or receipt.generation_root != current.generation_root
                        or receipt.manifest_root != current.manifest_root
                    ):
                        raise CSVGenerationContractError(
                            "CURRENT references an incompatible published receipt",
                            fault=CSVGenerationFault.IDENTITY_MISMATCH,
                        )
                    current_verified = True

                for path in self._iter_record_paths(self.intents_dir):
                    intent = self._load_intent(path)
                    commit_path = self._commit_path(intent.intent_root)
                    abort_path = self._abort_path(intent.intent_root)
                    if commit_path.exists() and abort_path.exists():
                        raise CSVGenerationContractError(
                            "publication intent is both committed and aborted",
                            fault=CSVGenerationFault.IDENTITY_MISMATCH,
                        )
                    if commit_path.exists():
                        self._load_commit(commit_path)
                        continue
                    if self._intent_matches_current(intent, current):
                        published = CSVGenerationReceipt(
                            generation_root=intent.generation_root,
                            manifest_root=intent.manifest_root,
                            state=CSVGenerationState.PUBLISHED,
                            previous_receipt_root=intent.published_receipt_previous_root,
                        )
                        if published.receipt_root != intent.published_receipt_root:
                            raise CSVGenerationContractError(
                                "publication intent has an invalid receipt chain",
                                fault=CSVGenerationFault.IDENTITY_MISMATCH,
                            )
                        self._write_receipt(published)
                        assert current is not None
                        self._write_commit(self._commit_for_intent(intent, current))
                        completed.append(intent.intent_root)
                    else:
                        abort = CSVPublicationAbort(
                            intent_root=intent.intent_root,
                            disposition=(
                                CSVPublicationRecoveryDisposition.ABORTED_BEFORE_CURRENT
                            ),
                            observed_current_generation_root=current_generation,
                            observed_current_manifest_root=current_manifest,
                        )
                        self._write_abort(abort)
                        aborted.append(intent.intent_root)

        return CSVPublicationRecoveryReport(
            current_generation_root=current_generation,
            current_manifest_root=current_manifest,
            current_verified=current_verified,
            completed_intent_roots=tuple(sorted(completed)),
            aborted_intent_roots=tuple(sorted(aborted)),
        )

    def _commits_for_generation(
        self, generation_root: str
    ) -> tuple[CSVPublicationCommit, ...]:
        _validate_root("generation_root", generation_root)
        commits = []
        for path in self._iter_record_paths(self.commits_dir):
            commit = self._load_commit(path)
            if commit.generation_root == generation_root:
                commits.append(commit)
        return tuple(sorted(commits, key=lambda item: item.commit_root))

    def is_retired(self, generation_root: str) -> bool:
        _validate_root("generation_root", generation_root)
        return self._retirement_path(generation_root).exists()

    def rollback(
        self,
        generation_root: str,
        *,
        expected_current_manifest_root: str | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> CSVPublicationCommit:
        """Atomically restore one previously committed, non-retired generation."""

        if self.is_retired(generation_root):
            raise CSVGenerationContractError(
                "retired generations cannot be restored",
                fault=CSVGenerationFault.AUTHORITY_REJECTED,
            )
        target = self.load_generation(generation_root)
        self.verify(target)
        prior_commits = self._commits_for_generation(generation_root)
        if not prior_commits:
            raise CSVGenerationContractError(
                "rollback target has no committed publication evidence",
                fault=CSVGenerationFault.INCOMPLETE_GENERATION,
            )
        proof = prior_commits[0]
        published = self._read_receipt(proof.published_receipt_root)
        if published.state is not CSVGenerationState.PUBLISHED:
            raise CSVGenerationContractError("rollback proof is not published")

        def inject(point: str) -> None:
            if fault_injector is not None:
                fault_injector(point)

        with self._publication_lock:
            with self._interprocess_lock():
                current, previous_generation, previous_manifest = self._current_values()
                if current is not None and current.generation_root == generation_root:
                    raise CSVGenerationContractError(
                        "rollback target is already CURRENT",
                        fault=CSVGenerationFault.NONCANONICAL,
                    )
                expected = (
                    previous_manifest
                    if expected_current_manifest_root is None
                    else expected_current_manifest_root
                )
                _validate_root(
                    "expected_current_manifest_root", expected, allow_empty=True
                )
                if previous_manifest != expected:
                    raise CSVGenerationContractError(
                        "CURRENT changed before rollback",
                        fault=CSVGenerationFault.PUBLICATION_CONFLICT,
                    )
                intent = CSVPublicationIntent(
                    operation=CSVPublicationOperation.ROLLBACK,
                    generation_root=target.generation_root,
                    manifest_root=target.manifest_root,
                    published_receipt_root=published.receipt_root,
                    published_receipt_previous_root=published.previous_receipt_root,
                    expected_current_manifest_root=expected,
                    previous_current_generation_root=previous_generation,
                    previous_current_manifest_root=previous_manifest,
                )
                self._write_intent(intent)
                inject("after_rollback_intent")
                pointer = CurrentCSVGeneration(
                    generation_root=target.generation_root,
                    manifest_root=target.manifest_root,
                    published_receipt_root=published.receipt_root,
                )
                inject("before_rollback_current_replace")
                _atomic_replace(self.current_path, self._pointer_bytes(pointer))
                inject("after_rollback_current_replace")
                commit = self._commit_for_intent(intent, pointer)
                self._write_commit(commit)
                inject("after_rollback_commit")
                return commit

    def retire_generation(self, generation_root: str) -> CSVGenerationRetirement:
        """Retire a non-current, unpinned generation without deleting its bytes."""

        existing_path = self._retirement_path(generation_root)
        if existing_path.exists():
            root, values = self._decode_record(
                existing_path.read_bytes(),
                kind="generation-retirement",
                root_name="retirement_root",
            )
            raw = dict(values)
            raw.pop("contract_id", None)
            raw.pop("format_version", None)
            retirement = CSVGenerationRetirement(**raw)
            if retirement.retirement_root != root:
                raise CSVGenerationContractError("retirement identity mismatch")
            return retirement

        with self._publication_lock:
            with self._interprocess_lock():
                current = self.read_current()
                if current is not None and current.generation_root == generation_root:
                    raise CSVGenerationContractError(
                        "CURRENT generation cannot be retired",
                        fault=CSVGenerationFault.AUTHORITY_REJECTED,
                    )
                if self.pin_count(generation_root) != 0:
                    raise CSVGenerationContractError(
                        "pinned generation cannot be retired",
                        fault=CSVGenerationFault.AUTHORITY_REJECTED,
                    )
                staged = self.load_generation(generation_root)
                self.verify(staged)
                commits = self._commits_for_generation(generation_root)
                if not commits:
                    raise CSVGenerationContractError(
                        "unpublished generation cannot be retired",
                        fault=CSVGenerationFault.INCOMPLETE_GENERATION,
                    )
                published = self._read_receipt(commits[0].published_receipt_root)
                retired = CSVGenerationReceipt(
                    generation_root=staged.generation_root,
                    manifest_root=staged.manifest_root,
                    state=CSVGenerationState.RETIRED,
                    previous_receipt_root=published.receipt_root,
                )
                validate_receipt_transition(published, retired)
                self._write_receipt(retired)
                retirement = CSVGenerationRetirement(
                    generation_root=staged.generation_root,
                    manifest_root=staged.manifest_root,
                    retired_receipt_root=retired.receipt_root,
                    published_receipt_root=published.receipt_root,
                )
                self._write_retirement(retirement)
                return retirement


__all__ = [
    "CSV_DURABLE_PUBLICATION_AUTHORITY",
    "CSV_DURABLE_PUBLICATION_CONTRACT_ID",
    "CSV_DURABLE_PUBLICATION_FORMAT_VERSION",
    "CSV_DURABLE_PUBLICATION_MAX_RECOVERY_RECORDS",
    "CSVGenerationRetirement",
    "CSVPublicationAbort",
    "CSVPublicationAuthorityBoundary",
    "CSVPublicationCommit",
    "CSVPublicationIntent",
    "CSVPublicationOperation",
    "CSVPublicationRecoveryDisposition",
    "CSVPublicationRecoveryReport",
    "DurableAtomicCSVGenerationStore",
]

"""Immutable, atomically promoted persistence generations for TDS v3.

This module is the v3.5.3-dev2 correctness prototype.  It intentionally keeps
full generation images and is not yet wired into the legacy v2 mount path.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import re
import shutil
import time
import uuid
from typing import Any, Callable, Iterable

from ._binary_io import open_binary_fd
from .persistence_policy import CleanupMode, PersistencePolicy, PersistenceStatus
from .tds_json import dumps_canonical, loads_strict

_GENERATION_RE = re.compile(r"^gen-(\d{20})-([0-9a-f]{12})$")


class GenerationError(RuntimeError):
    """Base error for immutable generation operations."""


class GenerationIntegrityError(GenerationError):
    """A generation or CURRENT pointer failed validation."""


class BufferContractError(GenerationError):
    """The supplied buffer cannot be committed safely under its policy."""


class BufferPolicy(str, Enum):
    """Ownership policy for commit buffers.

    REQUIRE_STABLE preserves the zero-copy path but accepts only read-only,
    C-contiguous buffers. SNAPSHOT deliberately copies mutable or strided
    exporters into immutable bytes before persistence.
    """

    REQUIRE_STABLE = "require_stable"
    SNAPSHOT = "snapshot"


class RecoveryCondition(str, Enum):
    """Stable, machine-readable recovery classifications."""

    CURRENT_VALID = "current_valid"
    CURRENT_MISSING = "current_missing"
    CURRENT_MALFORMED = "current_malformed"
    CURRENT_GENERATION_MISSING = "current_generation_missing"
    GENERATION_INCOMPLETE = "generation_incomplete"
    METADATA_INVALID = "metadata_invalid"
    FORMAT_UNSUPPORTED = "format_unsupported"
    IDENTITY_MISMATCH = "identity_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    NO_VALID_GENERATION = "no_valid_generation"


@dataclass(frozen=True, slots=True)
class RejectedGeneration:
    generation_id: str
    condition: RecoveryCondition
    detail: str


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    requested_generation: str | None
    mounted_generation: str
    condition: RecoveryCondition
    detail: str
    current_repaired: bool
    scanned_candidates: int
    rejected_generations: tuple[RejectedGeneration, ...]


class CleanupError(GenerationError):
    """A retention or cleanup operation could not safely complete."""


@dataclass(frozen=True, slots=True)
class CleanupReport:
    planned_generations: tuple[str, ...]
    removed_generations: tuple[str, ...]
    skipped_protected: tuple[str, ...]
    resumed: bool
    completed: bool


@dataclass(frozen=True, slots=True)
class GenerationInfo:
    generation_id: str
    parent_generation: str | None
    created_ns: int
    data_size: int
    data_sha256: str
    path: Path


class ImmutableGenerationStore:
    """Commit complete immutable images and atomically promote a tiny pointer.

    The foreground commit path writes and verifies a new generation before
    replacing CURRENT.  Cleanup is deliberately separate from promotion.
    """

    DATA_NAME = "data.tds"
    META_NAME = "integrity.json"
    CURRENT_NAME = "CURRENT"
    SCHEMA = "tds.generation.v1"
    MAX_METADATA_BYTES = 1 * 1024 * 1024
    MAX_METADATA_DEPTH = 32
    MAX_METADATA_NODES = 10_000
    IO_CHUNK_BYTES = 1024 * 1024
    MAX_RECOVERY_CANDIDATES = 4096
    PINS_DIR_NAME = "pins"
    CLEANUP_PLAN_NAME = "CLEANUP.json"
    TRASH_DIR_NAME = ".cleanup-trash"

    def __init__(self, root: str | os.PathLike[str], *,
                 policy: PersistencePolicy | None = None,
                 fault_hook: Callable[[str], None] | None = None):
        self.root = Path(root)
        self.generations_dir = self.root / "generations"
        self.current_path = self.root / self.CURRENT_NAME
        self.pins_dir = self.root / self.PINS_DIR_NAME
        self.cleanup_plan_path = self.root / self.CLEANUP_PLAN_NAME
        self.trash_dir = self.root / self.TRASH_DIR_NAME
        self.policy = policy or PersistencePolicy.production_safe()
        self._fault_hook = fault_hook
        self.generations_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.pins_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.trash_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._fsync_dir(self.root)

    def _checkpoint(self, name: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(name)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_file(self, path: Path, chunks: Iterable[bytes | bytearray | memoryview], *, durable: bool,
                    hasher: Any | None = None, checkpoint_prefix: str | None = None) -> int:
        fd = open_binary_fd(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        total = 0
        try:
            for chunk in chunks:
                view = memoryview(chunk)
                try:
                    offset = 0
                    while offset < view.nbytes:
                        remaining = view[offset:]
                        try:
                            written = os.write(fd, remaining)
                        finally:
                            remaining.release()
                        if written <= 0:
                            raise GenerationError(f"write made no forward progress to {path}")
                        piece = view[offset:offset + written]
                        try:
                            if hasher is not None:
                                hasher.update(piece)
                        finally:
                            piece.release()
                        total += written
                        offset += written
                finally:
                    view.release()
            if durable:
                if checkpoint_prefix:
                    self._checkpoint(f"{checkpoint_prefix}_before_fsync")
                os.fsync(fd)
                if checkpoint_prefix:
                    self._checkpoint(f"{checkpoint_prefix}_after_fsync")
        finally:
            os.close(fd)
        return total


    @classmethod
    def _validate_metadata_tree(cls, value: Any, *, label: str = "application_metadata") -> None:
        """Reject pathological metadata before codec recursion or unbounded work.

        Iterative traversal avoids using Python recursion while enforcing a strict
        depth and total-node budget.  Only JSON-compatible value types are allowed.
        """
        stack: list[tuple[Any, int]] = [(value, 0)]
        nodes = 0
        while stack:
            item, depth = stack.pop()
            nodes += 1
            if nodes > cls.MAX_METADATA_NODES:
                raise GenerationIntegrityError(
                    f"{label} exceeds maximum node count {cls.MAX_METADATA_NODES}"
                )
            if depth > cls.MAX_METADATA_DEPTH:
                raise GenerationIntegrityError(
                    f"{label} exceeds maximum nesting depth {cls.MAX_METADATA_DEPTH}"
                )
            if item is None or isinstance(item, (str, int, float, bool)):
                continue
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise GenerationIntegrityError(f"{label} keys must be strings")
                    stack.append((child, depth + 1))
                continue
            if isinstance(item, (list, tuple)):
                stack.extend((child, depth + 1) for child in item)
                continue
            raise GenerationIntegrityError(
                f"{label} contains unsupported value type {type(item).__name__}"
            )

    @classmethod
    def _validate_decoded_metadata(cls, metadata: dict[str, Any]) -> None:
        cls._validate_metadata_tree(metadata, label="generation metadata")
        required = {
            "schema", "generation_id", "parent_generation", "created_ns",
            "data_file", "data_size", "data_sha256", "application_metadata",
        }
        missing = required.difference(metadata)
        if missing:
            raise GenerationIntegrityError(
                "generation metadata is missing required fields: " + ", ".join(sorted(missing))
            )

    def _new_generation_id(self) -> str:
        return f"gen-{time.time_ns():020d}-{uuid.uuid4().hex[:12]}"

    def _read_current_raw(self) -> str | None:
        if not self.current_path.exists():
            return None
        value = self.current_path.read_text(encoding="ascii").strip()
        if not _GENERATION_RE.fullmatch(value):
            raise GenerationIntegrityError("CURRENT contains an invalid generation identifier")
        return value

    @staticmethod
    def _condition_from_error(message: str) -> RecoveryCondition:
        text = message.lower()
        if "current contains" in text:
            return RecoveryCondition.CURRENT_MALFORMED
        if "is incomplete" in text:
            return RecoveryCondition.GENERATION_INCOMPLETE
        if "metadata is invalid" in text:
            return RecoveryCondition.METADATA_INVALID
        if "unsupported generation schema" in text:
            return RecoveryCondition.FORMAT_UNSUPPORTED
        if "identity mismatch" in text:
            return RecoveryCondition.IDENTITY_MISMATCH
        if "size mismatch" in text:
            return RecoveryCondition.SIZE_MISMATCH
        if "checksum mismatch" in text:
            return RecoveryCondition.CHECKSUM_MISMATCH
        if "does not exist" in text:
            return RecoveryCondition.CURRENT_GENERATION_MISSING
        return RecoveryCondition.METADATA_INVALID

    def _candidate_ids_newest_first(self) -> list[str]:
        candidates: list[str] = []
        for path in self.generations_dir.iterdir():
            if path.is_dir() and _GENERATION_RE.fullmatch(path.name):
                candidates.append(path.name)
                if len(candidates) > self.MAX_RECOVERY_CANDIDATES:
                    raise GenerationIntegrityError(
                        f"recovery candidate count exceeds {self.MAX_RECOVERY_CANDIDATES}"
                    )
        candidates.sort(reverse=True)
        return candidates

    def _replace_current(self, generation_id: str, *, checkpoint_prefix: str) -> None:
        durable = self.policy.durability.value != "relaxed"
        pointer_tmp = self.root / f".{self.CURRENT_NAME}.{uuid.uuid4().hex}.tmp"
        try:
            self._write_file(
                pointer_tmp, [(generation_id + "\n").encode("ascii")], durable=durable,
                checkpoint_prefix=f"{checkpoint_prefix}_temp",
            )
            self._checkpoint(f"{checkpoint_prefix}_temp_written")
            os.replace(pointer_tmp, self.current_path)
            self._checkpoint(f"{checkpoint_prefix}_replaced")
            if durable:
                before_name = ("parent_before_fsync" if checkpoint_prefix == "current"
                               else f"{checkpoint_prefix}_parent_before_fsync")
                after_name = ("parent_after_fsync" if checkpoint_prefix == "current"
                              else f"{checkpoint_prefix}_parent_after_fsync")
                self._checkpoint(before_name)
                self._fsync_dir(self.root)
                self._checkpoint(after_name)
        finally:
            try:
                pointer_tmp.unlink()
            except FileNotFoundError:
                pass

    def current_generation(self) -> str | None:
        value = self._read_current_raw()
        if value is not None:
            self.verify(value)
        return value


    @staticmethod
    def _prepare_commit_buffer(
        data: bytes | bytearray | memoryview,
        policy: BufferPolicy,
    ) -> tuple[memoryview, bytes | None]:
        """Return a one-dimensional byte view and optional owned snapshot.

        The default zero-copy path accepts only read-only C-contiguous buffers,
        preventing concurrent mutation from changing bytes while they are being
        written and hashed. SNAPSHOT is the explicit opt-in copy path for mutable
        or non-contiguous exporters.
        """
        try:
            source = memoryview(data)
        except TypeError as exc:
            raise BufferContractError("commit data must support the buffer protocol") from exc

        snapshot: bytes | None = None
        try:
            stable = source.readonly and source.c_contiguous
            if policy is BufferPolicy.REQUIRE_STABLE and not stable:
                reasons: list[str] = []
                if not source.readonly:
                    reasons.append("mutable")
                if not source.c_contiguous:
                    reasons.append("non-contiguous")
                raise BufferContractError(
                    "zero-copy commit requires a read-only C-contiguous buffer; "
                    + ", ".join(reasons)
                    + " input requires buffer_policy='snapshot'"
                )

            if policy is BufferPolicy.SNAPSHOT and not stable:
                snapshot = source.tobytes(order="C")
                source.release()
                source = memoryview(snapshot)

            try:
                byte_view = source.cast("B")
            except TypeError as exc:
                raise BufferContractError(
                    "commit buffer must be C-contiguous and castable to bytes"
                ) from exc
            source.release()
            return byte_view, snapshot
        except Exception:
            try:
                source.release()
            except Exception:
                pass
            raise

    def _commit_chunks(self, chunks: Iterable[bytes | bytearray | memoryview], *,
                       application_metadata: dict[str, Any] | None = None) -> GenerationInfo:
        """Commit a bounded stream without materialising the complete image.

        Callers must supply chunks whose contents remain stable until each
        individual chunk has been consumed.  This is the integration seam used
        by the guaranteed-storage transition bridge; ordinary callers should
        prefer :meth:`commit`, which enforces the stronger buffer policy.
        """
        parent = self._read_current_raw()
        app_metadata = application_metadata or {}
        self._validate_metadata_tree(app_metadata)
        generation_id = self._new_generation_id()
        generation_dir = self.generations_dir / generation_id
        generation_dir.mkdir(mode=0o700)
        durable = self.policy.durability.value != "relaxed"
        try:
            self._checkpoint("generation_created")
            digest = hashlib.sha256()
            data_path = generation_dir / self.DATA_NAME
            size = self._write_file(
                data_path, chunks, durable=durable, hasher=digest, checkpoint_prefix="data"
            )
            self._checkpoint("data_written")
            metadata = {
                "schema": self.SCHEMA,
                "generation_id": generation_id,
                "parent_generation": parent,
                "created_ns": time.time_ns(),
                "data_file": self.DATA_NAME,
                "data_size": size,
                "data_sha256": digest.hexdigest(),
                "application_metadata": app_metadata,
            }
            meta_bytes = dumps_canonical(metadata)[0]
            if len(meta_bytes) > self.MAX_METADATA_BYTES:
                raise GenerationIntegrityError(
                    f"generation metadata exceeds {self.MAX_METADATA_BYTES} bytes"
                )
            self._write_file(
                generation_dir / self.META_NAME, [meta_bytes], durable=durable,
                checkpoint_prefix="metadata",
            )
            self._checkpoint("metadata_written")
            if durable:
                self._checkpoint("generation_dir_before_fsync")
                self._fsync_dir(generation_dir)
                self._checkpoint("generation_dir_after_fsync")
            info = self.verify(generation_id)
            self._checkpoint("generation_verified")
            self._replace_current(generation_id, checkpoint_prefix="current")
            self._checkpoint("parent_synced")
        except Exception:
            raise

        if self.policy.cleanup is CleanupMode.IMMEDIATE:
            self._prune(keep=self.policy.retained_generations, acknowledged=True)
        return info

    def commit_stream(self, chunks: Iterable[bytes | bytearray | memoryview], *,
                      application_metadata: dict[str, Any] | None = None) -> GenerationInfo:
        """Commit a stable chunk stream with bounded memory use.

        Each yielded chunk is consumed fully before the iterator advances.
        Mutable chunks are rejected to prevent concurrent mutation from changing
        the durable image while it is being hashed and written.
        """
        def stable_chunks() -> Iterable[memoryview]:
            for chunk in chunks:
                try:
                    view = memoryview(chunk)
                except TypeError as exc:
                    raise BufferContractError("stream chunks must support the buffer protocol") from exc
                try:
                    if not view.readonly or not view.c_contiguous:
                        raise BufferContractError(
                            "stream chunks must be read-only and C-contiguous"
                        )
                    byte_view = view.cast("B")
                    view.release()
                    view = byte_view
                    yield view
                finally:
                    try:
                        view.release()
                    except Exception:
                        pass

        return self._commit_chunks(stable_chunks(), application_metadata=application_metadata)

    def commit(self, data: bytes | bytearray | memoryview, *,
               application_metadata: dict[str, Any] | None = None,
               buffer_policy: BufferPolicy | str = BufferPolicy.REQUIRE_STABLE) -> GenerationInfo:
        try:
            resolved_buffer_policy = BufferPolicy(buffer_policy)
        except ValueError as exc:
            raise BufferContractError(f"unsupported buffer policy: {buffer_policy!r}") from exc
        view, _snapshot = self._prepare_commit_buffer(data, resolved_buffer_policy)
        try:
            chunks = (view[offset:offset + self.IO_CHUNK_BYTES]
                      for offset in range(0, view.nbytes, self.IO_CHUNK_BYTES))
            return self._commit_chunks(chunks, application_metadata=application_metadata)
        finally:
            view.release()

    def verify(self, generation_id: str) -> GenerationInfo:
        if not _GENERATION_RE.fullmatch(generation_id):
            raise GenerationIntegrityError("invalid generation identifier")
        generation_dir = self.generations_dir / generation_id
        meta_path = generation_dir / self.META_NAME
        data_path = generation_dir / self.DATA_NAME
        if not generation_dir.is_dir():
            raise GenerationIntegrityError(f"generation {generation_id} does not exist")
        if not meta_path.is_file() or not data_path.is_file():
            raise GenerationIntegrityError(f"generation {generation_id} is incomplete")
        try:
            meta_size = meta_path.stat().st_size
            if meta_size > self.MAX_METADATA_BYTES:
                raise GenerationIntegrityError(
                    f"generation metadata exceeds {self.MAX_METADATA_BYTES} bytes"
                )
            metadata, _backend = loads_strict(meta_path.read_bytes(), expected_type=dict)
        except Exception as exc:
            raise GenerationIntegrityError(f"generation metadata is invalid: {exc}") from exc
        self._validate_decoded_metadata(metadata)
        if metadata.get("schema") != self.SCHEMA:
            raise GenerationIntegrityError(
                f"unsupported generation schema: {metadata.get('schema')!r}"
            )
        if metadata.get("generation_id") != generation_id:
            raise GenerationIntegrityError("generation metadata identity mismatch")
        expected_size = int(metadata.get("data_size", -1))
        digest = hashlib.sha256()
        actual_size = 0
        with data_path.open("rb", buffering=0) as handle:
            while True:
                chunk = handle.read(self.IO_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                actual_size += len(chunk)
        if actual_size != expected_size:
            raise GenerationIntegrityError("generation data size mismatch")
        expected_hash = str(metadata.get("data_sha256", ""))
        if digest.hexdigest() != expected_hash:
            raise GenerationIntegrityError("generation data checksum mismatch")
        return GenerationInfo(
            generation_id=generation_id,
            parent_generation=metadata.get("parent_generation"),
            created_ns=int(metadata["created_ns"]),
            data_size=actual_size,
            data_sha256=expected_hash,
            path=generation_dir,
        )

    def read_current(self) -> bytes:
        generation_id = self.current_generation()
        if generation_id is None:
            raise GenerationIntegrityError("no committed generation")
        return (self.generations_dir / generation_id / self.DATA_NAME).read_bytes()

    def list_generations(self, *, valid_only: bool = False) -> list[GenerationInfo]:
        infos: list[GenerationInfo] = []
        for path in sorted(self.generations_dir.iterdir(), reverse=True):
            if not path.is_dir() or not _GENERATION_RE.fullmatch(path.name):
                continue
            try:
                infos.append(self.verify(path.name))
            except GenerationIntegrityError:
                if valid_only:
                    continue
        return infos

    def recover_report(self, *, repair_current: bool = True) -> RecoveryReport:
        """Select one verified generation deterministically and optionally repair CURRENT.

        Rejected generations are preserved. Candidate traversal is bounded and ordered
        newest-to-oldest by the generation identifier's fixed-width timestamp prefix.
        """
        requested: str | None = None
        initial_condition = RecoveryCondition.CURRENT_MISSING
        initial_detail = "CURRENT pointer is missing"
        try:
            requested = self._read_current_raw()
            if requested is not None:
                self.verify(requested)
                return RecoveryReport(
                    requested_generation=requested,
                    mounted_generation=requested,
                    condition=RecoveryCondition.CURRENT_VALID,
                    detail="CURRENT points to a verified generation; recovery was not required",
                    current_repaired=False,
                    scanned_candidates=1,
                    rejected_generations=(),
                )
        except GenerationIntegrityError as exc:
            initial_detail = str(exc)
            initial_condition = self._condition_from_error(initial_detail)

        rejected: list[RejectedGeneration] = []
        scanned = 0
        mounted: str | None = None
        for generation_id in self._candidate_ids_newest_first():
            scanned += 1
            try:
                self.verify(generation_id)
            except GenerationIntegrityError as exc:
                rejected.append(RejectedGeneration(
                    generation_id=generation_id,
                    condition=self._condition_from_error(str(exc)),
                    detail=str(exc),
                ))
                continue
            mounted = generation_id
            break

        if mounted is None:
            raise GenerationIntegrityError(
                f"{RecoveryCondition.NO_VALID_GENERATION.value}: {initial_detail}"
            )

        repaired = False
        if repair_current:
            self._replace_current(mounted, checkpoint_prefix="recovery_current")
            repaired = True

        return RecoveryReport(
            requested_generation=requested,
            mounted_generation=mounted,
            condition=initial_condition,
            detail=initial_detail,
            current_repaired=repaired,
            scanned_candidates=scanned,
            rejected_generations=tuple(rejected),
        )

    def recover(self, *, repair_current: bool = True) -> PersistenceStatus:
        report = self.recover_report(repair_current=repair_current)
        if report.requested_generation == report.mounted_generation:
            return PersistenceStatus(
                durability=self.policy.durability,
                retained_generations=self.policy.retained_generations,
                atomic_generations=True,
                external_backup_configured=False,
                current_generation=report.mounted_generation,
                last_verified_generation=report.mounted_generation,
            )
        requested = report.requested_generation or "CURRENT-missing"
        return PersistenceStatus(
            durability=self.policy.durability,
            retained_generations=self.policy.retained_generations,
            atomic_generations=True,
            external_backup_configured=False,
            current_generation=report.mounted_generation,
            last_verified_generation=report.mounted_generation,
            recovery_fallback_active=True,
            requested_generation=requested,
            mounted_generation=report.mounted_generation,
            recovery_reason=f"{report.condition.value}: {report.detail}",
        )

    def list_pins(self) -> tuple[str, ...]:
        """Return persistently pinned generation identifiers in stable order."""
        return tuple(sorted(
            path.name for path in self.pins_dir.iterdir()
            if path.is_file() and _GENERATION_RE.fullmatch(path.name)
        ))

    def pin(self, generation_id: str) -> None:
        """Persistently protect a verified generation from cleanup."""
        self.verify(generation_id)
        marker = self.pins_dir / generation_id
        if marker.exists():
            return
        self._write_file(marker, [b"pinned\n"], durable=True)
        self._fsync_dir(self.pins_dir)

    def unpin(self, generation_id: str, *, acknowledge_reduced_recovery: bool = False) -> None:
        """Remove persistent protection only after explicit acknowledgement."""
        marker = self.pins_dir / generation_id
        if not marker.exists():
            return
        if not acknowledge_reduced_recovery:
            raise CleanupError(
                "unpin requires acknowledge_reduced_recovery=True because later cleanup may delete the generation"
            )
        marker.unlink()
        self._fsync_dir(self.pins_dir)

    def _write_cleanup_plan(self, candidates: list[str]) -> None:
        payload = dumps_canonical({
            "schema": "tds.cleanup.v1",
            "candidates": candidates,
            "created_ns": time.time_ns(),
        })[0]
        tmp = self.root / f".{self.CLEANUP_PLAN_NAME}.{uuid.uuid4().hex}.tmp"
        try:
            self._write_file(tmp, [payload], durable=True, checkpoint_prefix="cleanup_plan")
            os.replace(tmp, self.cleanup_plan_path)
            self._fsync_dir(self.root)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def _load_cleanup_plan(self) -> list[str]:
        try:
            value, _ = loads_strict(self.cleanup_plan_path.read_bytes(), expected_type=dict)
        except Exception as exc:
            raise CleanupError(f"cleanup plan is invalid: {exc}") from exc
        if value.get("schema") != "tds.cleanup.v1" or not isinstance(value.get("candidates"), list):
            raise CleanupError("cleanup plan has unsupported or incomplete structure")
        candidates = value["candidates"]
        if len(candidates) > self.MAX_RECOVERY_CANDIDATES:
            raise CleanupError("cleanup plan exceeds candidate budget")
        if any(not isinstance(item, str) or not _GENERATION_RE.fullmatch(item) for item in candidates):
            raise CleanupError("cleanup plan contains an invalid generation identifier")
        return candidates

    def _protected_generation_ids(self, *, keep: int) -> set[str]:
        valid = self.list_generations(valid_only=True)
        protected = {info.generation_id for info in valid[:keep]}
        current = self._read_current_raw()
        if current is not None:
            protected.add(current)
        protected.update(self.list_pins())
        return protected

    def _delete_generation_restartable(self, generation_id: str) -> bool:
        source = self.generations_dir / generation_id
        trash = self.trash_dir / generation_id
        if source.exists():
            self._checkpoint("cleanup_before_quarantine")
            os.replace(source, trash)
            self._fsync_dir(self.generations_dir)
            self._checkpoint("cleanup_after_quarantine")
        if trash.exists():
            self._checkpoint("cleanup_before_delete")
            shutil.rmtree(trash)
            self._fsync_dir(self.trash_dir)
            self._checkpoint("cleanup_after_delete")
            return True
        return False

    def _execute_cleanup_plan(self, candidates: list[str], *, resumed: bool) -> CleanupReport:
        removed: list[str] = []
        skipped: list[str] = []
        for generation_id in candidates:
            # Recompute protection immediately before every destructive action.
            if generation_id in self._protected_generation_ids(keep=1):
                skipped.append(generation_id)
                continue
            if self._delete_generation_restartable(generation_id):
                removed.append(generation_id)
        self._checkpoint("cleanup_before_plan_remove")
        try:
            self.cleanup_plan_path.unlink()
        except FileNotFoundError:
            pass
        self._fsync_dir(self.root)
        self._checkpoint("cleanup_after_plan_remove")
        return CleanupReport(tuple(candidates), tuple(removed), tuple(skipped), resumed, True)

    def resume_cleanup(self) -> CleanupReport | None:
        """Resume an interrupted, already-acknowledged cleanup plan."""
        if not self.cleanup_plan_path.exists():
            return None
        return self._execute_cleanup_plan(self._load_cleanup_plan(), resumed=True)

    def _prune(self, *, keep: int, acknowledged: bool) -> CleanupReport:
        if isinstance(keep, bool) or keep < 1:
            raise ValueError("keep must be >= 1")
        valid = self.list_generations(valid_only=True)
        protected = self._protected_generation_ids(keep=keep)
        candidates = [info.generation_id for info in valid if info.generation_id not in protected]
        if candidates and not acknowledged:
            raise CleanupError(
                "prune would permanently delete recovery generations; pass "
                "acknowledge_reduced_recovery=True"
            )
        if not candidates:
            return CleanupReport((), (), (), False, True)
        self._write_cleanup_plan(candidates)
        return self._execute_cleanup_plan(candidates, resumed=False)

    def prune(self, *, keep: int, acknowledge_reduced_recovery: bool = False) -> CleanupReport:
        """Delete eligible generations through a durable restartable plan."""
        return self._prune(keep=keep, acknowledged=acknowledge_reduced_recovery)

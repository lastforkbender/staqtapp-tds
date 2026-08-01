"""Crash-safe reference store for the TDS v3.7 Generation Authority."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import time
from typing import Callable, Iterator, Mapping
import uuid

try:  # POSIX advisory locks are released by the kernel when a process exits.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows fallback for the same persistent lock-file protocol.
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None  # type: ignore[assignment]

from .generation_contract import (
    DEFAULT_GENERATION_LIMITS,
    GenerationContractError,
    GenerationFault,
    GenerationHead,
    GenerationLifecycleReceipt,
    GenerationManifest,
    GenerationPublicationRecord,
    GenerationState,
    PublicationAction,
    QualifiedGenerationLimits,
    build_lifecycle_chain,
    build_manifest,
    bytes_root,
    canonical_json_bytes,
    manifest_from_json,
    publication_record_from_json,
    require_root,
    validate_lifecycle_chain,
    validate_publication_record,
)

FailureInjector = Callable[[str], None]

FAILURE_BOUNDARIES = (
    "before_temporary_write",
    "during_payload_write",
    "after_payload_write",
    "before_file_fsync",
    "after_file_fsync",
    "before_directory_fsync",
    "before_manifest_publication",
    "after_manifest_publication",
    "before_current_head_cas",
    "after_current_head_cas",
    "during_recovery",
)


class GenerationStoreError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        fault: GenerationFault = GenerationFault.IO_FAILURE,
    ) -> None:
        super().__init__(message)
        self.fault = fault


class GenerationPublicationConflict(GenerationStoreError):
    def __init__(self, message: str) -> None:
        super().__init__(message, fault=GenerationFault.PUBLICATION_CONFLICT)


@dataclass(frozen=True, slots=True)
class GenerationCandidate:
    manifest: GenerationManifest
    payloads: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        if tuple(sorted(self.payloads, key=lambda item: item[0])) != self.payloads:
            raise GenerationContractError("candidate payloads must be sorted")
        if tuple(name for name, _ in self.payloads) != tuple(
            item.name for item in self.manifest.payloads
        ):
            raise GenerationContractError(
                "candidate payload names do not match manifest",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        for identity, (_, data) in zip(self.manifest.payloads, self.payloads):
            if not isinstance(data, bytes):
                raise GenerationContractError("candidate payload must be exact bytes")
            if identity.size != len(data) or identity.content_root != bytes_root(data):
                raise GenerationContractError(
                    f"candidate payload identity mismatch: {identity.name}",
                    fault=GenerationFault.IDENTITY_MISMATCH,
                )

    @property
    def generation_root(self) -> str:
        return self.manifest.generation_root

    def payload_map(self) -> dict[str, bytes]:
        return dict(self.payloads)


@dataclass(frozen=True, slots=True)
class PublicationResult:
    head: GenerationHead
    record: GenerationPublicationRecord
    manifest: GenerationManifest
    recovered_before_publish: bool = False


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    namespace: str
    head: GenerationHead | None
    repaired: bool
    valid_records: int
    ignored_torn_tail: bool


class GenerationLease:
    """A read lease pinned to one complete generation root."""

    def __init__(
        self,
        store: "AtomicGenerationStore",
        namespace: str,
        manifest: GenerationManifest,
        publication_sequence: int,
        pin_fd: int,
    ) -> None:
        self._store = store
        self.namespace = namespace
        self.manifest = manifest
        self.publication_sequence = publication_sequence
        self.generation_root = manifest.generation_root
        self._pin_fd = pin_fd
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def read_payload(self, name: str) -> bytes:
        if self._closed:
            raise GenerationStoreError("generation lease is closed")
        return self._store._read_payload(self.manifest, name)

    def close(self) -> None:
        if not self._closed:
            try:
                self._store._release_pin(self.generation_root, self._pin_fd)
            finally:
                self._closed = True

    def __enter__(self) -> "GenerationLease":
        if self._closed:
            raise GenerationStoreError("generation lease is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class AtomicGenerationStore:
    """Reference implementation of immutable generation publication.

    The store is intentionally generic. CSV source bytes are one consumer, but
    Eaglegate epochs, exactness evidence, runtime capability snapshots, and
    observer snapshots can use the same identity/publication protocol.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        limits: QualifiedGenerationLimits = DEFAULT_GENERATION_LIMITS,
        failure_injector: FailureInjector | None = None,
        lock_attempts: int = 500,
        lock_sleep_seconds: float = 0.002,
    ) -> None:
        self.root = Path(root)
        self.limits = limits
        self.failure_injector = failure_injector
        self.lock_attempts = lock_attempts
        self.lock_sleep_seconds = lock_sleep_seconds
        self.objects_dir = self.root / "objects"
        self.generations_dir = self.root / "generations"
        self.namespaces_dir = self.root / "namespaces"
        self.staging_dir = self.root / ".staging"
        self.pins_dir = self.root / "pins"
        self._mutex = threading.RLock()
        self._pins: dict[str, int] = {}
        for directory in (
            self.root,
            self.objects_dir,
            self.generations_dir,
            self.namespaces_dir,
            self.staging_dir,
            self.pins_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _hit(self, boundary: str) -> None:
        if boundary not in FAILURE_BOUNDARIES:
            raise AssertionError(f"unknown failure boundary: {boundary}")
        if self.failure_injector is not None:
            self.failure_injector(boundary)

    @staticmethod
    def _root_hex(root: str) -> str:
        require_root("root", root)
        return root.split(":", 1)[1]

    @staticmethod
    def _namespace_key(namespace: str) -> str:
        if not isinstance(namespace, str) or not namespace:
            raise GenerationContractError("namespace must be non-empty")
        return hashlib.sha256(namespace.encode("utf-8")).hexdigest()

    def _namespace_dir(self, namespace: str) -> Path:
        return self.namespaces_dir / self._namespace_key(namespace)

    def _generation_dir(self, generation_root: str) -> Path:
        return self.generations_dir / self._root_hex(generation_root)

    def _object_path(self, content_root: str) -> Path:
        return self.objects_dir / self._root_hex(content_root)

    def _pin_path(self, generation_root: str) -> Path:
        return self.pins_dir / self._root_hex(generation_root)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            fd = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _open_regular_fd(
        path: Path,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        open_flags = flags
        if hasattr(os, "O_CLOEXEC"):
            open_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        fd = os.open(path, open_flags, mode)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise GenerationStoreError(
                    f"path is not a regular file: {path}",
                    fault=GenerationFault.INTEGRITY_FAILURE,
                )
        except BaseException:
            os.close(fd)
            raise
        return fd

    @classmethod
    def _read_bounded_regular_file(cls, path: Path, max_bytes: int) -> bytes:
        if max_bytes < 0:
            raise AssertionError("file bound must be non-negative")
        try:
            fd = cls._open_regular_fd(path, os.O_RDONLY)
        except OSError as exc:
            raise GenerationStoreError(
                f"cannot safely open regular file: {path}",
                fault=GenerationFault.INTEGRITY_FAILURE,
            ) from exc
        try:
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 1 << 20))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > max_bytes:
                raise GenerationStoreError(
                    f"file exceeds qualified byte bound: {path}",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            return data
        finally:
            os.close(fd)

    @staticmethod
    def _require_real_directory(path: Path) -> None:
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise GenerationStoreError(
                f"directory is missing: {path}",
                fault=GenerationFault.INCOMPLETE_GENERATION,
            ) from exc
        if not stat.S_ISDIR(mode):
            raise GenerationStoreError(
                f"directory path is not a real directory: {path}",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )

    def _canonical_load(
        self,
        path: Path,
        *,
        max_bytes: int | None = None,
    ) -> tuple[object, bytes]:
        data = self._read_bounded_regular_file(
            path,
            self.limits.max_manifest_bytes if max_bytes is None else max_bytes,
        )
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GenerationStoreError(
                f"malformed canonical JSON: {path}",
                fault=GenerationFault.INTEGRITY_FAILURE,
            ) from exc
        if canonical_json_bytes(value) != data:
            raise GenerationStoreError(
                f"noncanonical JSON: {path}",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        return value, data

    def _validate_manifest_limits(
        self,
        manifest: GenerationManifest,
        *,
        encoded_size: int,
    ) -> None:
        for field in (
            "max_payloads",
            "max_payload_bytes",
            "max_single_payload_bytes",
            "max_qualification_roots",
            "max_metadata_entries",
            "max_manifest_bytes",
            "max_publication_records",
            "max_reader_pins",
        ):
            if getattr(manifest.limits, field) > getattr(self.limits, field):
                raise GenerationStoreError(
                    f"manifest {field} exceeds configured store limit",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
        if encoded_size > self.limits.max_manifest_bytes:
            raise GenerationStoreError(
                "manifest exceeds configured byte limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        if len(manifest.payloads) > self.limits.max_payloads:
            raise GenerationStoreError(
                "manifest payload count exceeds configured limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        if len(manifest.qualifications) > self.limits.max_qualification_roots:
            raise GenerationStoreError(
                "manifest qualification count exceeds configured limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        if len(manifest.metadata) > self.limits.max_metadata_entries:
            raise GenerationStoreError(
                "manifest metadata count exceeds configured limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        total = 0
        for payload in manifest.payloads:
            if payload.size > self.limits.max_single_payload_bytes:
                raise GenerationStoreError(
                    "manifest payload exceeds configured single-payload limit",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            if total > self.limits.max_payload_bytes - payload.size:
                raise GenerationStoreError(
                    "manifest payload bytes exceed configured limit",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            total += payload.size

    def _load_manifest(self, path: Path) -> GenerationManifest:
        data = self._read_bounded_regular_file(path, self.limits.max_manifest_bytes)
        manifest = manifest_from_json(data)
        self._validate_manifest_limits(manifest, encoded_size=len(data))
        return manifest

    @staticmethod
    def _lock_fd(fd: int, *, shared: bool, nonblocking: bool) -> None:
        if fcntl is not None:
            operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            if nonblocking:
                operation |= fcntl.LOCK_NB
            fcntl.flock(fd, operation)
            return
        if msvcrt is not None:  # pragma: no cover - Windows only
            os.lseek(fd, 0, os.SEEK_SET)
            mode = (
                msvcrt.LK_NBRLCK
                if shared and nonblocking
                else msvcrt.LK_RLCK
                if shared
                else msvcrt.LK_NBLCK
                if nonblocking
                else msvcrt.LK_LOCK
            )
            msvcrt.locking(fd, mode, 1)
            return
        raise GenerationStoreError("OS advisory file locks are unavailable")

    @staticmethod
    def _unlock_fd(fd: int) -> None:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return
        if msvcrt is not None:  # pragma: no cover - Windows only
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

    def _acquire_advisory_lock(
        self,
        path: Path,
        *,
        shared: bool,
        attempts: int | None = None,
    ) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = self._open_regular_fd(path, os.O_RDWR | os.O_CREAT)
        except OSError as exc:
            raise GenerationStoreError(
                f"cannot safely open advisory lock: {path}",
                fault=GenerationFault.INTEGRITY_FAILURE,
            ) from exc
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\x00")
                os.fsync(fd)
                self._fsync_directory(path.parent)
            lock_attempts = self.lock_attempts if attempts is None else attempts
            for attempt in range(lock_attempts):
                try:
                    self._lock_fd(fd, shared=shared, nonblocking=True)
                    return fd
                except (BlockingIOError, OSError):
                    if attempt + 1 < lock_attempts:
                        time.sleep(self.lock_sleep_seconds)
            raise GenerationPublicationConflict(f"advisory lock is busy: {path}")
        except BaseException:
            os.close(fd)
            raise

    @classmethod
    def _release_advisory_lock(cls, fd: int) -> None:
        try:
            cls._unlock_fd(fd)
        finally:
            os.close(fd)

    def _write_payload_object(self, content_root: str, data: bytes) -> Path:
        final_path = self._object_path(content_root)
        try:
            existing = self._read_bounded_regular_file(final_path, len(data))
        except GenerationStoreError:
            if final_path.exists() or final_path.is_symlink():
                raise
        else:
            if existing != data or bytes_root(existing) != content_root:
                raise GenerationStoreError(
                    "content-addressed object collision or corruption",
                    fault=GenerationFault.INTEGRITY_FAILURE,
                )
            return final_path

        self._hit("before_temporary_write")
        temporary = self.staging_dir / f"object-{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "xb") as handle:
                split = len(data) // 2
                handle.write(data[:split])
                handle.flush()
                self._hit("during_payload_write")
                handle.write(data[split:])
                handle.flush()
                self._hit("after_payload_write")
                self._hit("before_file_fsync")
                os.fsync(handle.fileno())
                self._hit("after_file_fsync")
            try:
                os.link(temporary, final_path)
            except FileExistsError:
                existing = self._read_bounded_regular_file(final_path, len(data))
                if existing != data or bytes_root(existing) != content_root:
                    raise GenerationStoreError(
                        "concurrent object publication mismatch",
                        fault=GenerationFault.INTEGRITY_FAILURE,
                    )
            except OSError:
                if final_path.exists():
                    existing = self._read_bounded_regular_file(final_path, len(data))
                    if existing != data or bytes_root(existing) != content_root:
                        raise
                else:
                    os.replace(temporary, final_path)
            self._hit("before_directory_fsync")
            self._fsync_directory(self.objects_dir)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return final_path

    def _write_small_file(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @contextmanager
    def _namespace_lock(self, namespace: str) -> Iterator[None]:
        namespace_dir = self._namespace_dir(namespace)
        namespace_dir.mkdir(parents=True, exist_ok=True)
        self._require_real_directory(namespace_dir)
        lock_path = namespace_dir / "LOCK"
        with self._mutex:
            fd = self._acquire_advisory_lock(lock_path, shared=False)
            try:
                yield
            finally:
                self._release_advisory_lock(fd)

    def build_candidate(
        self,
        *,
        namespace: str,
        payloads: Mapping[str, bytes],
        media_types: Mapping[str, str] | None = None,
        authoritative_payload: str | None = None,
        parent_generation_root: str | None = None,
        qualifications: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> GenerationCandidate:
        if not isinstance(payloads, Mapping) or not payloads:
            raise GenerationContractError("payloads must be a non-empty mapping")
        media = dict(media_types or {})
        unknown_media = set(media) - set(payloads)
        if unknown_media:
            raise GenerationContractError("media type declared for unknown payload")
        if authoritative_payload is not None and authoritative_payload not in payloads:
            raise GenerationContractError("authoritative payload is not present")
        specs: dict[str, tuple[bytes, str, bool]] = {}
        payload_items: list[tuple[str, bytes]] = []
        for name in sorted(payloads):
            data = payloads[name]
            if not isinstance(data, bytes):
                raise GenerationContractError("payload values must be exact bytes")
            specs[name] = (
                data,
                media.get(name, "application/octet-stream"),
                name == authoritative_payload,
            )
            payload_items.append((name, data))
        manifest = build_manifest(
            namespace=namespace,
            payloads=specs,
            parent_generation_root=parent_generation_root,
            qualifications=qualifications,
            metadata=metadata,
            limits=self.limits,
        )
        return GenerationCandidate(manifest=manifest, payloads=tuple(payload_items))

    def _materialize_generation(
        self,
        candidate: GenerationCandidate,
    ) -> tuple[GenerationManifest, GenerationLifecycleReceipt]:
        manifest = candidate.manifest
        self._validate_manifest_limits(
            manifest,
            encoded_size=len(manifest.canonical_bytes()),
        )
        generation_dir = self._generation_dir(manifest.generation_root)
        if generation_dir.exists():
            loaded, published = self.verify_generation(manifest.generation_root)
            if loaded != manifest:
                raise GenerationStoreError(
                    "existing generation identity mismatch",
                    fault=GenerationFault.INTEGRITY_FAILURE,
                )
            return loaded, published

        for identity, (_, data) in zip(manifest.payloads, candidate.payloads):
            self._write_payload_object(identity.content_root, data)

        stage_dir = self.staging_dir / f"generation-{uuid.uuid4().hex}"
        receipts = build_lifecycle_chain(manifest, through=GenerationState.PUBLISHED)
        try:
            stage_dir.mkdir(parents=False, exist_ok=False)
            receipts_dir = stage_dir / "receipts"
            receipts_dir.mkdir()
            self._write_small_file(stage_dir / "manifest.json", manifest.canonical_bytes())
            for receipt in receipts:
                name = f"{receipt.sequence:03d}-{receipt.state.value}.json"
                self._write_small_file(
                    receipts_dir / name,
                    canonical_json_bytes(receipt.canonical_dict()),
                )
            self.verify_staged_generation(stage_dir, manifest)
            self._hit("before_manifest_publication")
            try:
                os.replace(stage_dir, generation_dir)
            except OSError:
                if not generation_dir.exists():
                    raise
                loaded, published = self.verify_generation(manifest.generation_root)
                if loaded != manifest:
                    raise GenerationStoreError(
                        "concurrent generation publication mismatch",
                        fault=GenerationFault.INTEGRITY_FAILURE,
                    )
                return loaded, published
            self._fsync_directory(self.generations_dir)
            self._hit("after_manifest_publication")
        finally:
            if stage_dir.exists():
                shutil.rmtree(stage_dir, ignore_errors=True)
        return self.verify_generation(manifest.generation_root)

    def verify_staged_generation(
        self,
        directory: Path,
        expected_manifest: GenerationManifest,
    ) -> GenerationLifecycleReceipt:
        self._require_real_directory(directory)
        manifest = self._load_manifest(directory / "manifest.json")
        if manifest != expected_manifest:
            raise GenerationStoreError(
                "staged manifest identity mismatch",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        for payload in manifest.payloads:
            path = self._object_path(payload.content_root)
            data = self._read_bounded_regular_file(path, payload.size)
            if len(data) != payload.size or bytes_root(data) != payload.content_root:
                raise GenerationStoreError(
                    f"payload object failed verification: {payload.name}",
                    fault=GenerationFault.INTEGRITY_FAILURE,
                )
        receipts: list[GenerationLifecycleReceipt] = []
        receipts_dir = directory / "receipts"
        self._require_real_directory(receipts_dir)
        for sequence, state_value in enumerate(
            ("staging", "sealed", "verified", "published")
        ):
            path = receipts_dir / f"{sequence:03d}-{state_value}.json"
            value, data = self._canonical_load(path)
            if not isinstance(value, dict):
                raise GenerationStoreError("receipt must be a JSON object")
            receipt = GenerationLifecycleReceipt.from_dict(value)
            if canonical_json_bytes(receipt.canonical_dict()) != data:
                raise GenerationStoreError("receipt is not canonical")
            receipts.append(receipt)
        return validate_lifecycle_chain(manifest, receipts)

    def verify_generation(
        self,
        generation_root: str,
    ) -> tuple[GenerationManifest, GenerationLifecycleReceipt]:
        directory = self._generation_dir(generation_root)
        self._require_real_directory(directory)
        manifest = self._load_manifest(directory / "manifest.json")
        if manifest.generation_root != generation_root:
            raise GenerationStoreError(
                "generation directory root mismatch",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        published = self.verify_staged_generation(directory, manifest)
        return manifest, published

    def _publication_log_path(self, namespace: str) -> Path:
        return self._namespace_dir(namespace) / "publication.jsonl"

    def _head_path(self, namespace: str) -> Path:
        return self._namespace_dir(namespace) / "CURRENT"

    def _read_publication_records(
        self,
        namespace: str,
        *,
        allow_torn_tail: bool,
    ) -> tuple[list[GenerationPublicationRecord], bool]:
        path = self._publication_log_path(namespace)
        try:
            fd = self._open_regular_fd(path, os.O_RDONLY)
        except FileNotFoundError:
            return [], False
        except OSError as exc:
            raise GenerationStoreError(
                "publication log is not a safe regular file",
                fault=GenerationFault.INTEGRITY_FAILURE,
            ) from exc
        records: list[GenerationPublicationRecord] = []
        previous: GenerationPublicationRecord | None = None
        current_root: str | None = None
        torn_tail = False
        max_line_bytes = self.limits.max_manifest_bytes
        try:
            with os.fdopen(fd, "rb", closefd=True) as handle:
                while True:
                    line = handle.readline(max_line_bytes + 2)
                    if not line:
                        break
                    complete = line.endswith(b"\n")
                    raw = line[:-1] if complete else line
                    if len(raw) > max_line_bytes:
                        raise GenerationStoreError(
                            "publication record exceeds qualified byte bound",
                            fault=GenerationFault.BOUND_EXCEEDED,
                        )
                    if not complete:
                        if handle.read(1):
                            raise GenerationStoreError(
                                "publication record exceeds qualified byte bound",
                                fault=GenerationFault.BOUND_EXCEEDED,
                            )
                        torn_tail = True
                        if not allow_torn_tail:
                            raise GenerationStoreError(
                                "publication log has a torn tail",
                                fault=GenerationFault.RECOVERY_FAILURE,
                            )
                        break
                    if not raw:
                        raise GenerationStoreError(
                            "publication log contains an empty record",
                            fault=GenerationFault.INTEGRITY_FAILURE,
                        )
                    if len(records) >= self.limits.max_publication_records:
                        raise GenerationStoreError(
                            "publication record count exceeds configured limit",
                            fault=GenerationFault.BOUND_EXCEEDED,
                        )
                    record = publication_record_from_json(raw)
                    validate_publication_record(
                        record,
                        previous_record=previous,
                        expected_current_root=current_root,
                    )
                    if record.namespace != namespace:
                        raise GenerationStoreError(
                            "publication log namespace mismatch",
                            fault=GenerationFault.IDENTITY_MISMATCH,
                        )
                    records.append(record)
                    previous = record
                    current_root = record.generation_root
        except BaseException:
            # fdopen owns fd after successful construction; on construction
            # failure it remains ours.
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        return records, torn_tail

    def _append_publication_record(
        self,
        namespace: str,
        record: GenerationPublicationRecord,
    ) -> None:
        path = self._publication_log_path(namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json_bytes(record.canonical_dict()) + b"\n"
        try:
            fd = self._open_regular_fd(
                path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            )
        except OSError as exc:
            raise GenerationStoreError(
                "publication log is not a safe regular file",
                fault=GenerationFault.INTEGRITY_FAILURE,
            ) from exc
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_directory(path.parent)

    @staticmethod
    def _head_envelope(head: GenerationHead) -> bytes:
        return canonical_json_bytes(
            {
                "head": head.canonical_dict(),
                "head_root": head.head_root,
            }
        )

    def _read_head_unverified(self, namespace: str) -> GenerationHead | None:
        path = self._head_path(namespace)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise GenerationStoreError("cannot inspect CURRENT") from exc
        if not stat.S_ISREG(mode):
            raise GenerationStoreError(
                "CURRENT is not a regular file",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        value, _ = self._canonical_load(path)
        if not isinstance(value, dict) or set(value) != {"head", "head_root"}:
            raise GenerationStoreError(
                "CURRENT envelope is malformed",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        if not isinstance(value["head"], dict):
            raise GenerationStoreError("CURRENT head is malformed")
        head = GenerationHead.from_dict(value["head"])
        if head.head_root != value["head_root"] or head.namespace != namespace:
            raise GenerationStoreError(
                "CURRENT identity mismatch",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        return head

    def current_head(self, namespace: str) -> GenerationHead | None:
        head = self._read_head_unverified(namespace)
        if head is None:
            return None
        records, torn = self._read_publication_records(
            namespace,
            allow_torn_tail=False,
        )
        if torn or not records:
            raise GenerationStoreError(
                "CURRENT has no final publication record",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        latest = records[-1]
        expected = GenerationHead(
            namespace=namespace,
            publication_sequence=latest.publication_sequence,
            generation_root=latest.generation_root,
            manifest_root=latest.manifest_root,
            publication_record_root=latest.record_root,
        )
        if head != expected:
            raise GenerationStoreError(
                "CURRENT is not the latest publication head",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        manifest, published = self.verify_generation(head.generation_root)
        if (
            manifest.manifest_root != head.manifest_root
            or published.receipt_root != latest.published_receipt_root
        ):
            raise GenerationStoreError(
                "CURRENT does not bind a verified generation",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        return head

    def _record_by_root(
        self,
        namespace: str,
        record_root: str,
    ) -> GenerationPublicationRecord:
        records, _ = self._read_publication_records(
            namespace,
            allow_torn_tail=False,
        )
        for record in records:
            if record.record_root == record_root:
                return record
        raise GenerationStoreError(
            "publication record root is not present",
            fault=GenerationFault.INTEGRITY_FAILURE,
        )

    def _write_head(self, head: GenerationHead) -> None:
        path = self._head_path(head.namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".CURRENT.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "xb") as handle:
                handle.write(self._head_envelope(head))
                handle.flush()
                os.fsync(handle.fileno())
            self._hit("before_current_head_cas")
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
            self._hit("after_current_head_cas")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _rewrite_publication_log(
        self,
        namespace: str,
        records: list[GenerationPublicationRecord],
    ) -> None:
        path = self._publication_log_path(namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".publication.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "xb") as handle:
                for record in records:
                    handle.write(canonical_json_bytes(record.canonical_dict()) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _recover_locked(self, namespace: str) -> RecoveryResult:
        records, torn_tail = self._read_publication_records(
            namespace,
            allow_torn_tail=True,
        )
        valid: list[GenerationPublicationRecord] = []
        published_roots: set[str] = set()
        for record in records:
            manifest, published = self.verify_generation(record.generation_root)
            if (
                manifest.namespace != namespace
                or manifest.manifest_root != record.manifest_root
                or published.receipt_root != record.published_receipt_root
            ):
                raise GenerationStoreError(
                    "publication record references invalid generation",
                    fault=GenerationFault.RECOVERY_FAILURE,
                )
            if (
                record.action is PublicationAction.PUBLISH
                and manifest.parent_generation_root
                != record.previous_generation_root
            ):
                raise GenerationStoreError(
                    "published manifest parent breaks publication lineage",
                    fault=GenerationFault.RECOVERY_FAILURE,
                )
            if record.action is PublicationAction.PUBLISH:
                published_roots.add(record.generation_root)
            elif record.generation_root not in published_roots:
                raise GenerationStoreError(
                    "rollback record targets a generation never published",
                    fault=GenerationFault.RECOVERY_FAILURE,
                )
            valid.append(record)

        if torn_tail:
            self._rewrite_publication_log(namespace, valid)

        expected: GenerationHead | None = None
        if valid:
            record = valid[-1]
            expected = GenerationHead(
                namespace=namespace,
                publication_sequence=record.publication_sequence,
                generation_root=record.generation_root,
                manifest_root=record.manifest_root,
                publication_record_root=record.record_root,
            )
        repaired = False
        existing_invalid = False
        try:
            existing = self._read_head_unverified(namespace)
        except GenerationStoreError:
            existing = None
            repaired = True
            existing_invalid = True
        if existing_invalid or existing != expected:
            repaired = True
            path = self._head_path(namespace)
            if expected is None:
                removed = False
                try:
                    path.unlink()
                    removed = True
                except FileNotFoundError:
                    pass
                if removed:
                    self._fsync_directory(path.parent)
            else:
                temporary = path.parent / f".CURRENT.recover.{uuid.uuid4().hex}.tmp"
                try:
                    with open(temporary, "xb") as handle:
                        handle.write(self._head_envelope(expected))
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                    self._fsync_directory(path.parent)
                finally:
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass
        return RecoveryResult(
            namespace=namespace,
            head=expected,
            repaired=repaired,
            valid_records=len(valid),
            ignored_torn_tail=torn_tail,
        )

    def recover(self, namespace: str) -> RecoveryResult:
        self._hit("during_recovery")
        with self._namespace_lock(namespace):
            return self._recover_locked(namespace)

    def _ensure_log_head_consistency(self, namespace: str) -> bool:
        result = self.recover(namespace)
        return result.repaired or result.ignored_torn_tail

    def publish(
        self,
        candidate: GenerationCandidate,
        *,
        expected_head_root: str | None,
    ) -> PublicationResult:
        require_root("expected_head_root", expected_head_root, optional=True)
        manifest, published = self._materialize_generation(candidate)
        namespace = manifest.namespace
        with self._namespace_lock(namespace):
            recovery = self._recover_locked(namespace)
            head = recovery.head
            current_root = head.generation_root if head else None
            current_head_root = head.head_root if head else None
            if current_head_root != expected_head_root:
                raise GenerationPublicationConflict(
                    f"CURRENT head changed: expected {expected_head_root!r}, "
                    f"found {current_head_root!r}"
                )
            if manifest.parent_generation_root != current_root:
                raise GenerationPublicationConflict(
                    "candidate parent root does not equal CURRENT"
                )
            records, _ = self._read_publication_records(
                namespace,
                allow_torn_tail=False,
            )
            if len(records) >= self.limits.max_publication_records:
                raise GenerationStoreError(
                    "publication record limit reached",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            previous_record = records[-1] if records else None
            record = GenerationPublicationRecord(
                namespace=namespace,
                publication_sequence=(previous_record.publication_sequence + 1)
                if previous_record
                else 1,
                action=PublicationAction.PUBLISH,
                generation_root=manifest.generation_root,
                manifest_root=manifest.manifest_root,
                published_receipt_root=published.receipt_root,
                previous_generation_root=current_root,
                predecessor_record_root=previous_record.record_root
                if previous_record
                else None,
            )
            validate_publication_record(
                record,
                previous_record=previous_record,
                expected_current_root=current_root,
            )
            self._append_publication_record(namespace, record)
            new_head = GenerationHead(
                namespace=namespace,
                publication_sequence=record.publication_sequence,
                generation_root=record.generation_root,
                manifest_root=record.manifest_root,
                publication_record_root=record.record_root,
            )
            self._write_head(new_head)
            return PublicationResult(
                head=new_head,
                record=record,
                manifest=manifest,
                recovered_before_publish=(
                    recovery.repaired or recovery.ignored_torn_tail
                ),
            )

    def rollback(
        self,
        namespace: str,
        target_generation_root: str,
        *,
        expected_head_root: str,
    ) -> PublicationResult:
        require_root("target_generation_root", target_generation_root)
        require_root("expected_head_root", expected_head_root)
        with self._namespace_lock(namespace):
            recovery = self._recover_locked(namespace)
            head = recovery.head
            current_root = head.generation_root if head else None
            current_head_root = head.head_root if head else None
            if current_head_root != expected_head_root:
                raise GenerationPublicationConflict("rollback CURRENT conflict")
            manifest, published = self.verify_generation(target_generation_root)
            if manifest.namespace != namespace:
                raise GenerationStoreError(
                    "rollback target namespace mismatch",
                    fault=GenerationFault.IDENTITY_MISMATCH,
                )
            if self.is_retired(target_generation_root):
                raise GenerationStoreError("retired generation cannot be rollback target")
            records, _ = self._read_publication_records(
                namespace,
                allow_torn_tail=False,
            )
            if not records or not any(
                item.action is PublicationAction.PUBLISH
                and item.generation_root == target_generation_root
                for item in records
            ):
                raise GenerationPublicationConflict(
                    "rollback target was never published in this namespace"
                )
            if len(records) >= self.limits.max_publication_records:
                raise GenerationStoreError(
                    "publication record limit reached",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            previous_record = records[-1]
            record = GenerationPublicationRecord(
                namespace=namespace,
                publication_sequence=previous_record.publication_sequence + 1,
                action=PublicationAction.ROLLBACK,
                generation_root=target_generation_root,
                manifest_root=manifest.manifest_root,
                published_receipt_root=published.receipt_root,
                previous_generation_root=current_root,
                predecessor_record_root=previous_record.record_root,
            )
            validate_publication_record(
                record,
                previous_record=previous_record,
                expected_current_root=current_root,
            )
            self._append_publication_record(namespace, record)
            new_head = GenerationHead(
                namespace=namespace,
                publication_sequence=record.publication_sequence,
                generation_root=record.generation_root,
                manifest_root=record.manifest_root,
                publication_record_root=record.record_root,
            )
            self._write_head(new_head)
            return PublicationResult(
                head=new_head,
                record=record,
                manifest=manifest,
            )

    def pin(
        self,
        namespace: str,
        generation_root: str | None = None,
    ) -> GenerationLease:
        with self._namespace_lock(namespace):
            if sum(self._pins.values()) >= self.limits.max_reader_pins:
                raise GenerationStoreError(
                    "reader pin limit exceeded",
                    fault=GenerationFault.BOUND_EXCEEDED,
                )
            head = self.current_head(namespace)
            if generation_root is None:
                if head is None:
                    raise GenerationStoreError("namespace has no current generation")
                generation_root = head.generation_root
                publication_sequence = head.publication_sequence
            else:
                require_root("generation_root", generation_root)
                publication_sequence = head.publication_sequence if head else 0
            records, _ = self._read_publication_records(
                namespace,
                allow_torn_tail=False,
            )
            if not any(
                item.action is PublicationAction.PUBLISH
                and item.generation_root == generation_root
                for item in records
            ):
                raise GenerationStoreError(
                    "generation was never published in this namespace",
                    fault=GenerationFault.AUTHORITY_REJECTED,
                )
            manifest, _ = self.verify_generation(generation_root)
            if manifest.namespace != namespace:
                raise GenerationStoreError(
                    "pinned generation namespace mismatch",
                    fault=GenerationFault.IDENTITY_MISMATCH,
                )
            if self.is_retired(generation_root):
                raise GenerationStoreError("retired generation cannot be pinned")
            pin_fd = self._acquire_advisory_lock(
                self._pin_path(generation_root),
                shared=True,
            )
            try:
                if self.is_retired(generation_root):
                    raise GenerationStoreError("retired generation cannot be pinned")
                with self._mutex:
                    self._pins[generation_root] = self._pins.get(generation_root, 0) + 1
                return GenerationLease(
                    self,
                    namespace,
                    manifest,
                    publication_sequence,
                    pin_fd,
                )
            except BaseException:
                self._release_advisory_lock(pin_fd)
                raise

    def _release_pin(self, generation_root: str, pin_fd: int) -> None:
        try:
            self._release_advisory_lock(pin_fd)
        finally:
            with self._mutex:
                count = self._pins.get(generation_root, 0)
                if count <= 1:
                    self._pins.pop(generation_root, None)
                else:
                    self._pins[generation_root] = count - 1

    def pin_count(self, generation_root: str) -> int:
        with self._mutex:
            return self._pins.get(generation_root, 0)

    def _read_payload(self, manifest: GenerationManifest, name: str) -> bytes:
        identity = next((item for item in manifest.payloads if item.name == name), None)
        if identity is None:
            raise KeyError(name)
        if identity.size > self.limits.max_single_payload_bytes:
            raise GenerationStoreError(
                "payload exceeds configured read limit",
                fault=GenerationFault.BOUND_EXCEEDED,
            )
        data = self._read_bounded_regular_file(
            self._object_path(identity.content_root),
            identity.size,
        )
        if len(data) != identity.size or bytes_root(data) != identity.content_root:
            raise GenerationStoreError(
                f"payload integrity failure: {name}",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        return data

    def _load_retired_receipt(
        self,
        generation_root: str,
        *,
        manifest: GenerationManifest,
        published: GenerationLifecycleReceipt,
        allow_missing: bool,
    ) -> GenerationLifecycleReceipt | None:
        path = self._generation_dir(generation_root) / "receipts" / "004-retired.json"
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            if allow_missing:
                return None
            raise GenerationStoreError(
                "retirement receipt is missing",
                fault=GenerationFault.INCOMPLETE_GENERATION,
            )
        except OSError as exc:
            raise GenerationStoreError("cannot inspect retirement receipt") from exc
        if not stat.S_ISREG(mode):
            raise GenerationStoreError(
                "retirement receipt is not a regular file",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        value, data = self._canonical_load(path)
        if not isinstance(value, dict):
            raise GenerationStoreError("retirement receipt malformed")
        try:
            receipt = GenerationLifecycleReceipt.from_dict(value)
        except GenerationContractError as exc:
            raise GenerationStoreError(
                "retirement receipt contract failure",
                fault=GenerationFault.INTEGRITY_FAILURE,
            ) from exc
        if canonical_json_bytes(receipt.canonical_dict()) != data:
            raise GenerationStoreError(
                "retirement receipt noncanonical",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        if (
            receipt.generation_root != generation_root
            or receipt.manifest_root != manifest.manifest_root
            or receipt.state is not GenerationState.RETIRED
            or receipt.sequence != 4
            or receipt.predecessor_receipt_root != published.receipt_root
        ):
            raise GenerationStoreError(
                "retirement receipt breaks terminal lifecycle lineage",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        return receipt

    def retire(self, namespace: str, generation_root: str) -> GenerationLifecycleReceipt:
        require_root("generation_root", generation_root)
        with self._namespace_lock(namespace):
            head = self._recover_locked(namespace).head
            if head is not None and head.generation_root == generation_root:
                raise GenerationStoreError("CURRENT generation cannot be retired")
            manifest, published = self.verify_generation(generation_root)
            if manifest.namespace != namespace:
                raise GenerationStoreError("retirement namespace mismatch")
            path = self._generation_dir(generation_root) / "receipts" / "004-retired.json"
            existing = self._load_retired_receipt(
                generation_root,
                manifest=manifest,
                published=published,
                allow_missing=True,
            )
            if existing is not None:
                return existing
            try:
                pin_fd = self._acquire_advisory_lock(
                    self._pin_path(generation_root),
                    shared=False,
                    attempts=1,
                )
            except GenerationPublicationConflict as exc:
                raise GenerationStoreError("pinned generation cannot be retired") from exc
            try:
                receipt = GenerationLifecycleReceipt(
                    generation_root=generation_root,
                    manifest_root=manifest.manifest_root,
                    state=GenerationState.RETIRED,
                    sequence=4,
                    predecessor_receipt_root=published.receipt_root,
                )
                self._write_small_file(
                    path,
                    canonical_json_bytes(receipt.canonical_dict()),
                )
                return receipt
            finally:
                self._release_advisory_lock(pin_fd)

    def is_retired(self, generation_root: str) -> bool:
        path = self._generation_dir(generation_root) / "receipts" / "004-retired.json"
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise GenerationStoreError("cannot inspect retirement receipt") from exc
        if not stat.S_ISREG(mode):
            raise GenerationStoreError(
                "retirement receipt is not a regular file",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        manifest, published = self.verify_generation(generation_root)
        self._load_retired_receipt(
            generation_root,
            manifest=manifest,
            published=published,
            allow_missing=False,
        )
        return True

    def list_generations(self, namespace: str | None = None) -> tuple[str, ...]:
        result: list[str] = []
        for directory in sorted(self.generations_dir.iterdir()):
            try:
                is_real_directory = stat.S_ISDIR(directory.lstat().st_mode)
            except OSError:
                continue
            if not is_real_directory or len(directory.name) != 64:
                continue
            root = f"sha256:{directory.name}"
            try:
                manifest, _ = self.verify_generation(root)
            except (GenerationStoreError, GenerationContractError, OSError):
                continue
            if namespace is None or manifest.namespace == namespace:
                result.append(root)
        return tuple(result)


__all__ = [
    "FAILURE_BOUNDARIES",
    "AtomicGenerationStore",
    "FailureInjector",
    "GenerationCandidate",
    "GenerationLease",
    "GenerationPublicationConflict",
    "GenerationStoreError",
    "PublicationResult",
    "RecoveryResult",
]

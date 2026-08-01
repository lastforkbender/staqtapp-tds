"""Crash-safe reference store for the TDS v3.7 Generation Authority."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Callable, Iterator, Mapping
import uuid

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
    ) -> None:
        self._store = store
        self.namespace = namespace
        self.manifest = manifest
        self.publication_sequence = publication_sequence
        self.generation_root = manifest.generation_root
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
            self._store._release_pin(self.generation_root)
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
        self._mutex = threading.RLock()
        self._pins: dict[str, int] = {}
        for directory in (
            self.root,
            self.objects_dir,
            self.generations_dir,
            self.namespaces_dir,
            self.staging_dir,
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
    def _canonical_load(path: Path) -> tuple[object, bytes]:
        data = path.read_bytes()
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

    def _write_payload_object(self, content_root: str, data: bytes) -> Path:
        final_path = self._object_path(content_root)
        if final_path.exists():
            existing = final_path.read_bytes()
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
                existing = final_path.read_bytes()
                if existing != data or bytes_root(existing) != content_root:
                    raise GenerationStoreError(
                        "concurrent object publication mismatch",
                        fault=GenerationFault.INTEGRITY_FAILURE,
                    )
            except OSError:
                if final_path.exists():
                    existing = final_path.read_bytes()
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
        lock_path = namespace_dir / "LOCK"
        with self._mutex:
            fd: int | None = None
            for _ in range(self.lock_attempts):
                try:
                    fd = os.open(
                        lock_path,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
                    os.fsync(fd)
                    break
                except FileExistsError:
                    time.sleep(self.lock_sleep_seconds)
            if fd is None:
                raise GenerationStoreError(
                    f"namespace publication lock is busy: {namespace}",
                    fault=GenerationFault.PUBLICATION_CONFLICT,
                )
            try:
                yield
            finally:
                os.close(fd)
                try:
                    lock_path.unlink()
                finally:
                    self._fsync_directory(namespace_dir)

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
        manifest_data = (directory / "manifest.json").read_bytes()
        manifest = manifest_from_json(manifest_data)
        if manifest != expected_manifest:
            raise GenerationStoreError(
                "staged manifest identity mismatch",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        for payload in manifest.payloads:
            path = self._object_path(payload.content_root)
            if not path.is_file():
                raise GenerationStoreError(
                    f"missing immutable payload object: {payload.name}",
                    fault=GenerationFault.INCOMPLETE_GENERATION,
                )
            data = path.read_bytes()
            if len(data) != payload.size or bytes_root(data) != payload.content_root:
                raise GenerationStoreError(
                    f"payload object failed verification: {payload.name}",
                    fault=GenerationFault.INTEGRITY_FAILURE,
                )
        receipts: list[GenerationLifecycleReceipt] = []
        receipts_dir = directory / "receipts"
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
        if not directory.is_dir():
            raise GenerationStoreError(
                "generation directory is missing",
                fault=GenerationFault.INCOMPLETE_GENERATION,
            )
        manifest = manifest_from_json((directory / "manifest.json").read_bytes())
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
        if not path.exists():
            return [], False
        data = path.read_bytes()
        torn_tail = bool(data) and not data.endswith(b"\n")
        lines = data.splitlines()
        if torn_tail:
            if not allow_torn_tail:
                raise GenerationStoreError(
                    "publication log has a torn tail",
                    fault=GenerationFault.RECOVERY_FAILURE,
                )
            lines = lines[:-1]
        records: list[GenerationPublicationRecord] = []
        previous: GenerationPublicationRecord | None = None
        current_root: str | None = None
        for raw in lines:
            if not raw:
                raise GenerationStoreError(
                    "publication log contains an empty record",
                    fault=GenerationFault.INTEGRITY_FAILURE,
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
        return records, torn_tail

    def _append_publication_record(
        self,
        namespace: str,
        record: GenerationPublicationRecord,
    ) -> None:
        path = self._publication_log_path(namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json_bytes(record.canonical_dict()) + b"\n"
        with open(path, "ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
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
        if not path.exists():
            return None
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
        manifest, published = self.verify_generation(head.generation_root)
        if (
            manifest.manifest_root != head.manifest_root
            or published.receipt_root
            != self._record_by_root(namespace, head.publication_record_root).published_receipt_root
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

    def recover(self, namespace: str) -> RecoveryResult:
        self._hit("during_recovery")
        with self._namespace_lock(namespace):
            records, torn_tail = self._read_publication_records(
                namespace,
                allow_torn_tail=True,
            )
            valid: list[GenerationPublicationRecord] = []
            for record in records:
                manifest, published = self.verify_generation(record.generation_root)
                if (
                    manifest.manifest_root != record.manifest_root
                    or published.receipt_root != record.published_receipt_root
                ):
                    raise GenerationStoreError(
                        "publication record references invalid generation",
                        fault=GenerationFault.RECOVERY_FAILURE,
                    )
                valid.append(record)

            if torn_tail:
                path = self._publication_log_path(namespace)
                canonical_log = b"".join(
                    canonical_json_bytes(record.canonical_dict()) + b"\n"
                    for record in valid
                )
                self._write_small_file(path, canonical_log)

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
            try:
                existing = self._read_head_unverified(namespace)
            except GenerationStoreError:
                existing = None
                repaired = True
            if existing != expected:
                repaired = True
                path = self._head_path(namespace)
                if expected is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
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

    def _ensure_log_head_consistency(self, namespace: str) -> bool:
        records, torn = self._read_publication_records(
            namespace,
            allow_torn_tail=True,
        )
        existing = None
        try:
            existing = self._read_head_unverified(namespace)
        except GenerationStoreError:
            pass
        expected_root = records[-1].generation_root if records else None
        existing_root = existing.generation_root if existing else None
        if torn or expected_root != existing_root:
            self.recover(namespace)
            return True
        return False

    def publish(
        self,
        candidate: GenerationCandidate,
        *,
        expected_current_root: str | None,
    ) -> PublicationResult:
        require_root("expected_current_root", expected_current_root, optional=True)
        manifest, published = self._materialize_generation(candidate)
        namespace = manifest.namespace
        recovered = self._ensure_log_head_consistency(namespace)
        with self._namespace_lock(namespace):
            head = self._read_head_unverified(namespace)
            current_root = head.generation_root if head else None
            if current_root != expected_current_root:
                raise GenerationPublicationConflict(
                    f"CURRENT changed: expected {expected_current_root!r}, "
                    f"found {current_root!r}"
                )
            if manifest.parent_generation_root != current_root:
                raise GenerationPublicationConflict(
                    "candidate parent root does not equal CURRENT"
                )
            records, _ = self._read_publication_records(
                namespace,
                allow_torn_tail=False,
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
                recovered_before_publish=recovered,
            )

    def rollback(
        self,
        namespace: str,
        target_generation_root: str,
        *,
        expected_current_root: str,
    ) -> PublicationResult:
        require_root("target_generation_root", target_generation_root)
        require_root("expected_current_root", expected_current_root)
        manifest, published = self.verify_generation(target_generation_root)
        if manifest.namespace != namespace:
            raise GenerationStoreError(
                "rollback target namespace mismatch",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
        if self.is_retired(target_generation_root):
            raise GenerationStoreError("retired generation cannot be rollback target")
        self._ensure_log_head_consistency(namespace)
        with self._namespace_lock(namespace):
            head = self._read_head_unverified(namespace)
            current_root = head.generation_root if head else None
            if current_root != expected_current_root:
                raise GenerationPublicationConflict("rollback CURRENT conflict")
            records, _ = self._read_publication_records(
                namespace,
                allow_torn_tail=False,
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
        with self._mutex:
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
            manifest, _ = self.verify_generation(generation_root)
            if manifest.namespace != namespace:
                raise GenerationStoreError(
                    "pinned generation namespace mismatch",
                    fault=GenerationFault.IDENTITY_MISMATCH,
                )
            self._pins[generation_root] = self._pins.get(generation_root, 0) + 1
            return GenerationLease(
                self,
                namespace,
                manifest,
                publication_sequence,
            )

    def _release_pin(self, generation_root: str) -> None:
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
        data = self._object_path(identity.content_root).read_bytes()
        if len(data) != identity.size or bytes_root(data) != identity.content_root:
            raise GenerationStoreError(
                f"payload integrity failure: {name}",
                fault=GenerationFault.INTEGRITY_FAILURE,
            )
        return data

    def retire(self, namespace: str, generation_root: str) -> GenerationLifecycleReceipt:
        require_root("generation_root", generation_root)
        with self._namespace_lock(namespace):
            head = self._read_head_unverified(namespace)
            if head is not None and head.generation_root == generation_root:
                raise GenerationStoreError("CURRENT generation cannot be retired")
            if self.pin_count(generation_root):
                raise GenerationStoreError("pinned generation cannot be retired")
            manifest, published = self.verify_generation(generation_root)
            if manifest.namespace != namespace:
                raise GenerationStoreError("retirement namespace mismatch")
            path = self._generation_dir(generation_root) / "receipts" / "004-retired.json"
            if path.exists():
                value, data = self._canonical_load(path)
                if not isinstance(value, dict):
                    raise GenerationStoreError("retirement receipt malformed")
                receipt = GenerationLifecycleReceipt.from_dict(value)
                if canonical_json_bytes(receipt.canonical_dict()) != data:
                    raise GenerationStoreError("retirement receipt noncanonical")
                return receipt
            receipt = GenerationLifecycleReceipt(
                generation_root=generation_root,
                manifest_root=manifest.manifest_root,
                state=GenerationState.RETIRED,
                sequence=4,
                predecessor_receipt_root=published.receipt_root,
            )
            self._write_small_file(path, canonical_json_bytes(receipt.canonical_dict()))
            return receipt

    def is_retired(self, generation_root: str) -> bool:
        path = self._generation_dir(generation_root) / "receipts" / "004-retired.json"
        return path.is_file()

    def list_generations(self, namespace: str | None = None) -> tuple[str, ...]:
        result: list[str] = []
        for directory in sorted(self.generations_dir.iterdir()):
            if not directory.is_dir() or len(directory.name) != 64:
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

"""Content-addressed immutable segment generations for TDS v3.5.3-dev9.

Phase 9 deliberately coexists with the proven full-image generation store.
A segment generation is an immutable ordered manifest of immutable SHA-256
addressed byte segments.  Publication is the atomic replacement of
SEGMENT_CURRENT only after every segment and the manifest verify.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import time
import uuid
from typing import Any, Callable, Iterable, Iterator

from .generation_store import BufferContractError, GenerationError, GenerationIntegrityError, ImmutableGenerationStore
from .persistence_policy import PersistencePolicy
from .tds_json import dumps_canonical, loads_strict

_SEGMENT_GENERATION_RE = re.compile(r"^sgen-(\d{20})-([0-9a-f]{12})$")
_SEGMENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class SegmentStoreError(GenerationError):
    """Base error for immutable segment generation operations."""


class SegmentIntegrityError(GenerationIntegrityError, SegmentStoreError):
    """A segment, manifest, or segment pointer failed verification."""


@dataclass(frozen=True, slots=True)
class SegmentReference:
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class SegmentGenerationInfo:
    generation_id: str
    parent_generation: str | None
    created_ns: int
    logical_size: int
    logical_sha256: str
    segment_count: int
    unique_segment_count: int
    reused_segment_count: int
    manifest_sha256: str
    path: Path
    segments: tuple[SegmentReference, ...]
    application_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SegmentCommitReport:
    generation: SegmentGenerationInfo
    segments_created: int
    segments_reused: int
    bytes_written: int
    logical_bytes: int


@dataclass(frozen=True, slots=True)
class SegmentGCReport:
    referenced_segments: int
    removed_segments: tuple[str, ...]
    removed_bytes: int
    retained_unreferenced: tuple[str, ...]
    dry_run: bool
    candidate_segments: tuple[str, ...] = ()
    invalid_generations: tuple[str, ...] = ()
    changed_candidates: tuple[str, ...] = ()
    blocked: bool = False


class ImmutableSegmentStore:
    """Commit ordered immutable segment manifests with content deduplication."""

    SCHEMA = "tds.segment-generation.v1"
    MANIFEST_NAME = "segments.json"
    CURRENT_NAME = "SEGMENT_CURRENT"
    SEGMENT_SUFFIX = ".seg"
    DEFAULT_SEGMENT_BYTES = 1024 * 1024
    MAX_SEGMENT_BYTES = 16 * 1024 * 1024
    MAX_MANIFEST_BYTES = 16 * 1024 * 1024
    MAX_SEGMENTS_PER_GENERATION = 1_000_000
    IO_CHUNK_BYTES = 1024 * 1024

    def __init__(self, root: str | os.PathLike[str], *,
                 policy: PersistencePolicy | None = None,
                 segment_bytes: int = DEFAULT_SEGMENT_BYTES,
                 fault_hook: Callable[[str], None] | None = None):
        if not isinstance(segment_bytes, int) or not (1 <= segment_bytes <= self.MAX_SEGMENT_BYTES):
            raise ValueError(f"segment_bytes must be between 1 and {self.MAX_SEGMENT_BYTES}")
        self.root = Path(root)
        self.generations_dir = self.root / "segment-generations"
        self.segments_dir = self.root / "segments"
        self.current_path = self.root / self.CURRENT_NAME
        self.mutation_lock_path = self.root / ".segment-mutation.lock"
        self.policy = policy or PersistencePolicy.production_safe()
        self.segment_bytes = segment_bytes
        self._fault_hook = fault_hook
        self.generations_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.segments_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        ImmutableGenerationStore._fsync_dir(self.root)

    def _checkpoint(self, name: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(name)

    @contextmanager
    def _mutation_lock(self):
        """Cross-process fail-closed exclusion for commit, deletion, and GC.

        The lock is a directory created atomically. A process crash may leave it
        behind; that intentionally blocks destructive work until an operator has
        established that no mutation is active. Phase 9 never guesses that a
        lock is stale.
        """
        try:
            self.mutation_lock_path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise SegmentStoreError("segment mutation lock is already held") from exc
        try:
            ImmutableGenerationStore._fsync_dir(self.root)
            yield
        finally:
            try:
                self.mutation_lock_path.rmdir()
                ImmutableGenerationStore._fsync_dir(self.root)
            except FileNotFoundError:
                pass

    def _new_generation_id(self) -> str:
        return f"sgen-{time.time_ns():020d}-{uuid.uuid4().hex[:12]}"

    def _segment_path(self, digest: str) -> Path:
        if not _SEGMENT_HASH_RE.fullmatch(digest):
            raise SegmentIntegrityError("invalid segment digest")
        return self.segments_dir / digest[:2] / f"{digest}{self.SEGMENT_SUFFIX}"

    @staticmethod
    def _write_all_exclusive(path: Path, data: bytes, *, durable: bool) -> None:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            view = memoryview(data)
            try:
                offset = 0
                while offset < view.nbytes:
                    written = os.write(fd, view[offset:])
                    if written <= 0:
                        raise SegmentStoreError(f"write made no forward progress to {path}")
                    offset += written
            finally:
                view.release()
            if durable:
                os.fsync(fd)
        finally:
            os.close(fd)

    def _verify_segment_file(self, ref: SegmentReference) -> None:
        path = self._segment_path(ref.sha256)
        if not path.is_file() or path.is_symlink():
            raise SegmentIntegrityError(f"segment is missing: {ref.sha256}")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb", buffering=0) as handle:
            while True:
                chunk = handle.read(self.IO_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        if size != ref.size:
            raise SegmentIntegrityError(f"segment size mismatch: {ref.sha256}")
        if digest.hexdigest() != ref.sha256:
            raise SegmentIntegrityError(f"segment checksum mismatch: {ref.sha256}")

    def _store_segment(self, data: bytes) -> tuple[SegmentReference, bool]:
        digest = hashlib.sha256(data).hexdigest()
        ref = SegmentReference(digest, len(data))
        final = self._segment_path(digest)
        final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if final.exists():
            self._verify_segment_file(ref)
            return ref, False
        temp = final.parent / f".{digest}.{uuid.uuid4().hex}.tmp"
        durable = self.policy.durability.value != "relaxed"
        try:
            self._write_all_exclusive(temp, data, durable=durable)
            self._checkpoint("segment_written")
            # Verify private bytes before publication.
            actual = temp.read_bytes()
            if len(actual) != ref.size or hashlib.sha256(actual).hexdigest() != digest:
                raise SegmentIntegrityError("private segment verification failed")
            try:
                os.link(str(temp), str(final))
                created = True
            except FileExistsError:
                created = False
            temp.unlink(missing_ok=True)
            self._verify_segment_file(ref)
            if durable:
                ImmutableGenerationStore._fsync_dir(final.parent)
            self._checkpoint("segment_published")
            return ref, created
        finally:
            temp.unlink(missing_ok=True)

    def _replace_current(self, generation_id: str) -> None:
        if not _SEGMENT_GENERATION_RE.fullmatch(generation_id):
            raise SegmentIntegrityError("invalid segment generation identifier")
        temp = self.root / f".{self.CURRENT_NAME}.{uuid.uuid4().hex}.tmp"
        durable = self.policy.durability.value != "relaxed"
        try:
            self._write_all_exclusive(temp, (generation_id + "\n").encode("ascii"), durable=durable)
            self._checkpoint("segment_current_before_replace")
            os.replace(str(temp), str(self.current_path))
            self._checkpoint("segment_current_after_replace")
            if durable:
                ImmutableGenerationStore._fsync_dir(self.root)
        finally:
            temp.unlink(missing_ok=True)

    def _read_current_raw(self) -> str | None:
        if not self.current_path.exists():
            return None
        if not self.current_path.is_file() or self.current_path.is_symlink():
            raise SegmentIntegrityError("SEGMENT_CURRENT is not a regular file")
        value = self.current_path.read_text(encoding="ascii").strip()
        if not _SEGMENT_GENERATION_RE.fullmatch(value):
            raise SegmentIntegrityError("SEGMENT_CURRENT contains an invalid generation identifier")
        return value

    @staticmethod
    def _stable_chunks(chunks: Iterable[bytes | bytearray | memoryview]) -> Iterator[memoryview]:
        for chunk in chunks:
            try:
                view = memoryview(chunk)
            except TypeError as exc:
                raise BufferContractError("segment stream chunks must support the buffer protocol") from exc
            try:
                if not view.readonly or not view.c_contiguous:
                    raise BufferContractError("segment stream chunks must be read-only and C-contiguous")
                byte_view = view.cast("B")
                view.release()
                view = byte_view
                yield view
            finally:
                try:
                    view.release()
                except Exception:
                    pass

    def commit_stream(self, chunks: Iterable[bytes | bytearray | memoryview], *,
                      application_metadata: dict[str, Any] | None = None) -> SegmentCommitReport:
        with self._mutation_lock():
            return self._commit_stream_locked(chunks, application_metadata=application_metadata)

    def _commit_stream_locked(self, chunks: Iterable[bytes | bytearray | memoryview], *,
                              application_metadata: dict[str, Any] | None = None) -> SegmentCommitReport:
        app_metadata = application_metadata or {}
        ImmutableGenerationStore._validate_metadata_tree(app_metadata)
        parent = self._read_current_raw()
        generation_id = self._new_generation_id()
        generation_dir = self.generations_dir / generation_id
        generation_dir.mkdir(mode=0o700)
        refs: list[SegmentReference] = []
        pending = bytearray()
        logical_digest = hashlib.sha256()
        logical_size = 0
        created_count = reused_count = bytes_written = 0

        def consume(data: bytes) -> None:
            nonlocal logical_size, created_count, reused_count, bytes_written
            logical_digest.update(data)
            logical_size += len(data)
            ref, created = self._store_segment(data)
            refs.append(ref)
            if len(refs) > self.MAX_SEGMENTS_PER_GENERATION:
                raise SegmentStoreError("segment generation exceeds segment-count budget")
            if created:
                created_count += 1
                bytes_written += len(data)
            else:
                reused_count += 1

        try:
            for view in self._stable_chunks(chunks):
                offset = 0
                while offset < view.nbytes:
                    take = min(self.segment_bytes - len(pending), view.nbytes - offset)
                    pending.extend(view[offset:offset + take])
                    offset += take
                    if len(pending) == self.segment_bytes:
                        consume(bytes(pending))
                        pending.clear()
            if pending or not refs:
                consume(bytes(pending))
            created_ns = time.time_ns()
            manifest = {
                "schema": self.SCHEMA,
                "generation_id": generation_id,
                "parent_generation": parent,
                "created_ns": created_ns,
                "segment_bytes": self.segment_bytes,
                "logical_size": logical_size,
                "logical_sha256": logical_digest.hexdigest(),
                "segments": [{"sha256": ref.sha256, "size": ref.size} for ref in refs],
                "application_metadata": app_metadata,
            }
            manifest_bytes = dumps_canonical(manifest)[0]
            if len(manifest_bytes) > self.MAX_MANIFEST_BYTES:
                raise SegmentStoreError("segment manifest exceeds size budget")
            durable = self.policy.durability.value != "relaxed"
            self._write_all_exclusive(generation_dir / self.MANIFEST_NAME, manifest_bytes, durable=durable)
            if durable:
                ImmutableGenerationStore._fsync_dir(generation_dir)
            info = self.verify(generation_id)
            self._checkpoint("segment_generation_verified")
            self._replace_current(generation_id)
            return SegmentCommitReport(info, created_count, reused_count, bytes_written, logical_size)
        except Exception:
            # An unpublished generation is never authoritative. Segments may remain
            # as harmless unreferenced immutable objects and are reclaimed only by GC.
            raise

    def commit(self, data: bytes | memoryview, *,
               application_metadata: dict[str, Any] | None = None) -> SegmentCommitReport:
        view = memoryview(data)
        try:
            if not view.readonly or not view.c_contiguous:
                raise BufferContractError("segment commit requires a read-only C-contiguous buffer")
            return self.commit_stream((view.cast("B"),), application_metadata=application_metadata)
        finally:
            view.release()

    def verify(self, generation_id: str) -> SegmentGenerationInfo:
        if not _SEGMENT_GENERATION_RE.fullmatch(generation_id):
            raise SegmentIntegrityError("invalid segment generation identifier")
        generation_dir = self.generations_dir / generation_id
        manifest_path = generation_dir / self.MANIFEST_NAME
        if not generation_dir.is_dir() or generation_dir.is_symlink() or not manifest_path.is_file():
            raise SegmentIntegrityError(f"segment generation {generation_id} is incomplete")
        raw = manifest_path.read_bytes()
        if len(raw) > self.MAX_MANIFEST_BYTES:
            raise SegmentIntegrityError("segment manifest exceeds size budget")
        try:
            manifest, _backend = loads_strict(raw, expected_type=dict)
        except Exception as exc:
            raise SegmentIntegrityError(f"segment manifest is invalid: {exc}") from exc
        canonical = dumps_canonical(manifest)[0]
        if raw != canonical:
            raise SegmentIntegrityError("segment manifest is not canonical or was modified")
        ImmutableGenerationStore._validate_metadata_tree(manifest, label="segment manifest")
        required = {"schema", "generation_id", "parent_generation", "created_ns", "segment_bytes",
                    "logical_size", "logical_sha256", "segments", "application_metadata"}
        if set(manifest) != required:
            missing = sorted(required.difference(manifest))
            unexpected = sorted(set(manifest).difference(required))
            detail = []
            if missing:
                detail.append(f"missing={missing}")
            if unexpected:
                detail.append(f"unexpected={unexpected}")
            raise SegmentIntegrityError("invalid segment manifest fields: " + ", ".join(detail))
        if manifest["schema"] != self.SCHEMA:
            raise SegmentIntegrityError("unsupported segment generation schema")
        if manifest["generation_id"] != generation_id:
            raise SegmentIntegrityError("segment generation identity mismatch")
        parent = manifest["parent_generation"]
        if parent is not None and (not isinstance(parent, str) or not _SEGMENT_GENERATION_RE.fullmatch(parent)):
            raise SegmentIntegrityError("invalid parent segment generation")
        created_ns = manifest["created_ns"]
        segment_bytes = manifest["segment_bytes"]
        expected_logical_size = manifest["logical_size"]
        expected_logical_sha256 = manifest["logical_sha256"]
        application_metadata = manifest["application_metadata"]
        if isinstance(created_ns, bool) or not isinstance(created_ns, int) or created_ns < 0:
            raise SegmentIntegrityError("invalid segment generation creation time")
        if (isinstance(segment_bytes, bool) or not isinstance(segment_bytes, int)
                or not (1 <= segment_bytes <= self.MAX_SEGMENT_BYTES)):
            raise SegmentIntegrityError("invalid segment size policy")
        if isinstance(expected_logical_size, bool) or not isinstance(expected_logical_size, int) or expected_logical_size < 0:
            raise SegmentIntegrityError("invalid segment generation logical size")
        if not isinstance(expected_logical_sha256, str) or not _SEGMENT_HASH_RE.fullmatch(expected_logical_sha256):
            raise SegmentIntegrityError("invalid segment generation logical checksum")
        if not isinstance(application_metadata, dict):
            raise SegmentIntegrityError("invalid segment application metadata")
        raw_refs = manifest["segments"]
        if not isinstance(raw_refs, list) or not raw_refs or len(raw_refs) > self.MAX_SEGMENTS_PER_GENERATION:
            raise SegmentIntegrityError("invalid segment reference inventory")
        refs: list[SegmentReference] = []
        logical_digest = hashlib.sha256()
        logical_size = 0
        for item in raw_refs:
            if not isinstance(item, dict) or set(item) != {"sha256", "size"}:
                raise SegmentIntegrityError("invalid segment reference")
            digest = item["sha256"]
            size = item["size"]
            if not isinstance(digest, str) or not _SEGMENT_HASH_RE.fullmatch(digest):
                raise SegmentIntegrityError("invalid segment reference digest")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > segment_bytes:
                raise SegmentIntegrityError("invalid segment reference size")
            ref = SegmentReference(digest, size)
            self._verify_segment_file(ref)
            path = self._segment_path(digest)
            with path.open("rb", buffering=0) as handle:
                while True:
                    chunk = handle.read(self.IO_CHUNK_BYTES)
                    if not chunk:
                        break
                    logical_digest.update(chunk)
            logical_size += size
            refs.append(ref)
        if logical_size != expected_logical_size:
            raise SegmentIntegrityError("segment generation logical size mismatch")
        if logical_digest.hexdigest() != expected_logical_sha256:
            raise SegmentIntegrityError("segment generation logical checksum mismatch")
        return SegmentGenerationInfo(
            generation_id=generation_id,
            parent_generation=parent,
            created_ns=created_ns,
            logical_size=logical_size,
            logical_sha256=logical_digest.hexdigest(),
            segment_count=len(refs),
            unique_segment_count=len({ref.sha256 for ref in refs}),
            reused_segment_count=len(refs) - len({ref.sha256 for ref in refs}),
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            path=generation_dir,
            segments=tuple(refs),
            application_metadata=dict(application_metadata),
        )

    def current_generation(self) -> str | None:
        generation_id = self._read_current_raw()
        if generation_id is not None:
            self.verify(generation_id)
        return generation_id

    def recover_current(self, *, repair_current: bool = True) -> SegmentGenerationInfo:
        """Select the newest fully valid manifest and optionally repair the pointer."""
        requested = None
        try:
            requested = self._read_current_raw()
            if requested is not None:
                return self.verify(requested)
        except SegmentIntegrityError:
            pass
        valid = self.list_generations(valid_only=True)
        if not valid:
            raise SegmentIntegrityError("no valid segment generation")
        selected = max(valid, key=lambda item: (item.created_ns, item.generation_id))
        if repair_current:
            with self._mutation_lock():
                self._replace_current(selected.generation_id)
        return selected

    def iter_generation_bytes(self, generation_id: str | None = None) -> Iterator[bytes]:
        resolved = generation_id or self.current_generation()
        if resolved is None:
            raise SegmentIntegrityError("no current segment generation")
        info = self.verify(resolved)
        for ref in info.segments:
            with self._segment_path(ref.sha256).open("rb", buffering=0) as handle:
                remaining = ref.size
                while remaining:
                    chunk = handle.read(min(self.IO_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise SegmentIntegrityError(f"segment became truncated: {ref.sha256}")
                    remaining -= len(chunk)
                    yield chunk

    def read_current(self) -> bytes:
        return b"".join(self.iter_generation_bytes())

    def list_generations(self, *, valid_only: bool = False) -> list[SegmentGenerationInfo]:
        result: list[SegmentGenerationInfo] = []
        for path in sorted(self.generations_dir.iterdir(), reverse=True):
            if not path.is_dir() or not _SEGMENT_GENERATION_RE.fullmatch(path.name):
                continue
            try:
                result.append(self.verify(path.name))
            except SegmentIntegrityError:
                if not valid_only:
                    raise
        return result

    def reference_counts(self) -> dict[str, int]:
        counts, invalid = self._reference_scan()
        if invalid:
            raise SegmentIntegrityError(
                "reference accounting is incomplete because invalid generations exist: "
                + ", ".join(invalid)
            )
        return counts

    def _reference_scan(self) -> tuple[dict[str, int], tuple[str, ...]]:
        """Return references and the exact invalid-generation inventory.

        Recovery may ignore invalid candidates while selecting the newest valid
        generation. Destructive garbage collection is stricter: an unreadable or
        corrupt generation blocks deletion because reachability is no longer a
        closed-world proof.
        """
        counts: dict[str, int] = {}
        invalid: list[str] = []
        for path in sorted(self.generations_dir.iterdir(), reverse=True):
            if not path.is_dir() or path.is_symlink() or not _SEGMENT_GENERATION_RE.fullmatch(path.name):
                continue
            try:
                info = self.verify(path.name)
            except SegmentIntegrityError:
                invalid.append(path.name)
                continue
            for digest in {ref.sha256 for ref in info.segments}:
                counts[digest] = counts.get(digest, 0) + 1
        return dict(sorted(counts.items())), tuple(sorted(invalid))

    def delete_generation(self, generation_id: str) -> None:
        with self._mutation_lock():
            if generation_id == self._read_current_raw():
                raise SegmentStoreError("cannot delete the current segment generation")
            info = self.verify(generation_id)
            manifest = info.path / self.MANIFEST_NAME
            manifest.unlink()
            ImmutableGenerationStore._fsync_dir(info.path)
            info.path.rmdir()
            ImmutableGenerationStore._fsync_dir(self.generations_dir)

    def collect_unreferenced_segments(self, *, dry_run: bool = True) -> SegmentGCReport:
        with self._mutation_lock():
            return self._collect_unreferenced_segments_locked(dry_run=dry_run)

    def _collect_unreferenced_segments_locked(self, *, dry_run: bool) -> SegmentGCReport:
        counts, invalid_generations = self._reference_scan()
        referenced = set(counts)
        removable: list[tuple[str, Path, int, int, int, int, int, int]] = []
        retained: list[str] = []
        changed: list[str] = []
        for directory in self.segments_dir.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            for path in directory.iterdir():
                name = path.name
                digest = name[:-len(self.SEGMENT_SUFFIX)] if name.endswith(self.SEGMENT_SUFFIX) else ""
                if not path.is_file() or path.is_symlink() or not _SEGMENT_HASH_RE.fullmatch(digest):
                    continue
                if digest in referenced:
                    continue
                observed = path.lstat()
                if not stat.S_ISREG(observed.st_mode):
                    continue
                if dry_run:
                    retained.append(digest)
                else:
                    removable.append((
                        digest,
                        path,
                        observed.st_size,
                        observed.st_dev,
                        observed.st_ino,
                        observed.st_mode,
                        observed.st_mtime_ns,
                        observed.st_ctime_ns,
                    ))
        candidates = tuple(sorted(digest for digest, *_rest in removable))
        if dry_run:
            candidates = tuple(sorted(retained))
        removed: list[str] = []
        removed_bytes = 0
        blocked = bool(invalid_generations)
        if not dry_run and not blocked:
            self._checkpoint("segment_gc_scan_complete")
            for (
                digest,
                path,
                size,
                expected_dev,
                expected_ino,
                expected_mode,
                expected_mtime_ns,
                expected_ctime_ns,
            ) in removable:
                # Recompute the entire closed-world reachability proof for every
                # candidate. A checkpoint then permits fault tests to publish a
                # competing manifest; the proof is repeated after that boundary.
                current_counts, current_invalid = self._reference_scan()
                if current_invalid:
                    invalid_generations = current_invalid
                    blocked = True
                    retained.extend(item[0] for item in removable if item[0] not in removed)
                    break
                if digest in current_counts:
                    retained.append(digest)
                    continue
                self._checkpoint("segment_gc_before_delete")
                final_counts, final_invalid = self._reference_scan()
                if final_invalid:
                    invalid_generations = final_invalid
                    blocked = True
                    retained.extend(item[0] for item in removable if item[0] not in removed)
                    break
                if digest in final_counts:
                    retained.append(digest)
                    continue
                try:
                    observed = path.lstat()
                except FileNotFoundError:
                    changed.append(digest)
                    continue
                if (not stat.S_ISREG(observed.st_mode)
                        or observed.st_dev != expected_dev
                        or observed.st_ino != expected_ino
                        or observed.st_size != size
                        or observed.st_mode != expected_mode
                        or observed.st_mtime_ns != expected_mtime_ns
                        or observed.st_ctime_ns != expected_ctime_ns):
                    changed.append(digest)
                    continue
                path.unlink()
                ImmutableGenerationStore._fsync_dir(path.parent)
                removed.append(digest)
                removed_bytes += size
                self._checkpoint("segment_gc_after_delete")
        elif blocked:
            retained.extend(digest for digest, *_rest in removable)
        return SegmentGCReport(
            referenced_segments=len(referenced),
            removed_segments=tuple(sorted(set(removed))),
            removed_bytes=removed_bytes,
            retained_unreferenced=tuple(sorted(set(retained))),
            dry_run=dry_run,
            candidate_segments=candidates,
            invalid_generations=tuple(sorted(set(invalid_generations))),
            changed_candidates=tuple(sorted(set(changed))),
            blocked=blocked,
        )

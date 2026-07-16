"""Opt-in transition bridge from legacy TDS mounts to guaranteed generations.

The bridge deliberately keeps the stable v2 serializer unchanged.  It flushes a
complete legacy-compatible mount into an isolated staging directory, encodes the
result as a bounded streaming image, and promotes that image through
:class:`ImmutableGenerationStore`.  No partially flushed legacy directory is ever
made authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import tempfile
import uuid
from typing import Any, Callable, Iterable, Iterator

from ._binary_io import open_binary_fd
from .generation_store import GenerationInfo, GenerationIntegrityError, ImmutableGenerationStore
from .segment_store import ImmutableSegmentStore
from .persistence_policy import PersistencePolicy
from .tds_filesystem import TDSFileSystem
from .tds_persistence import TDSPersistence

_MAGIC = b"TDSIMG1\n"
_ENTRY = struct.Struct(">IQ")  # UTF-8 path length, payload size
_DIGEST_BYTES = 32
_END_PATH_LENGTH = 0


class GuaranteedStorageError(RuntimeError):
    """The transition image could not be constructed or materialised safely."""


@dataclass(frozen=True, slots=True)
class TransitionFitAnalysis:
    legacy_serializer_reused: bool
    atomic_mount_boundary: bool
    bounded_memory: bool
    default_path_changed: bool
    image_format: str
    performance_costs: tuple[str, ...]
    guarantees: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuaranteedCommitReport:
    generation: GenerationInfo
    files_archived: int
    source_bytes: int
    transition_mode: str


@dataclass(frozen=True, slots=True)
class SegmentedGuaranteedCommitReport:
    generation: Any
    files_archived: int
    source_bytes: int
    segments_created: int
    segments_reused: int
    physical_bytes_written: int
    transition_mode: str


@dataclass(frozen=True, slots=True)
class MaterializationReport:
    destination: Path
    files_materialized: int
    bytes_materialized: int
    published: bool


@dataclass(frozen=True, slots=True)
class MigrationFileRecord:
    path: str
    byte_length: int
    sha256: str
    metadata_equivalent: bool


@dataclass(frozen=True, slots=True)
class VerifiedMigrationReport:
    generation: GenerationInfo
    legacy_source: Path
    destination: Path
    files_verified: int
    bytes_verified: int
    inventory_equivalent: bool
    lengths_equivalent: bool
    digests_equivalent: bool
    metadata_equivalent: bool
    logical_reopen_equivalent: bool
    source_unchanged: bool
    activation_eligible: bool
    published: bool
    file_records: tuple[MigrationFileRecord, ...]


class _SegmentArchiveReader:
    """Small bounded file-like adapter over verified segment chunks."""

    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self._buffer = bytearray()
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        self._closed = True
        self._buffer.clear()

    def read(self, size: int = -1) -> bytes:
        if self._closed:
            raise ValueError("read from closed segment archive")
        if size == 0:
            return b""
        if size < 0:
            for chunk in self._chunks:
                self._buffer.extend(chunk)
            result = bytes(self._buffer)
            self._buffer.clear()
            return result
        while len(self._buffer) < size:
            try:
                self._buffer.extend(next(self._chunks))
            except StopIteration:
                break
        result = bytes(self._buffer[:size])
        del self._buffer[:size]
        return result


class GuaranteedStorageBridge:
    """Create recovery-qualified generations from complete legacy mount images.

    This is an explicit transition API.  It does not replace ``TDSPersistence``
    by default and therefore cannot silently change established mount behaviour.
    """

    ARCHIVE_CHUNK_BYTES = 1024 * 1024
    MAX_ARCHIVE_FILES = 1_000_000
    MAX_PATH_BYTES = 4096

    def __init__(self, root: str | os.PathLike[str], *,
                 policy: PersistencePolicy | None = None,
                 fault_hook: Callable[[str], None] | None = None):
        self.root = Path(root)
        self._fault_hook = fault_hook
        self.store = ImmutableGenerationStore(self.root, policy=policy, fault_hook=fault_hook)
        self.segment_store = ImmutableSegmentStore(self.root, policy=policy, fault_hook=fault_hook)

    def _checkpoint(self, name: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(name)

    @staticmethod
    def analyze_fit() -> TransitionFitAnalysis:
        return TransitionFitAnalysis(
            legacy_serializer_reused=True,
            atomic_mount_boundary=True,
            bounded_memory=True,
            default_path_changed=False,
            image_format="tds.transition.image.v1",
            performance_costs=(
                "legacy files are written once into isolated staging",
                "the staged image is streamed once into the generation",
                "durable commits wait for generation fsync and pointer promotion",
            ),
            guarantees=(
                "legacy serializer semantics remain unchanged",
                "CURRENT changes only after the complete mount image verifies",
                "failed transition commits preserve the previous generation",
                "materialisation rejects traversal, symlinks, truncation, and digest mismatch",
            ),
        )

    @classmethod
    def _iter_regular_files(cls, root: Path) -> list[Path]:
        files: list[Path] = []
        for path in root.rglob("*"):
            if path.is_symlink():
                raise GuaranteedStorageError(f"staging image contains a symlink: {path}")
            if path.is_file():
                files.append(path)
        files.sort(key=lambda p: p.relative_to(root).as_posix())
        if len(files) > cls.MAX_ARCHIVE_FILES:
            raise GuaranteedStorageError(
                f"staging image exceeds {cls.MAX_ARCHIVE_FILES} files"
            )
        return files

    @classmethod
    def _archive_chunks(cls, staging: Path, files: list[Path]) -> Iterator[bytes]:
        yield _MAGIC
        for path in files:
            relative = path.relative_to(staging).as_posix()
            encoded = relative.encode("utf-8")
            if not encoded or len(encoded) > cls.MAX_PATH_BYTES:
                raise GuaranteedStorageError(f"invalid archive path length: {relative!r}")
            size = path.stat().st_size
            yield _ENTRY.pack(len(encoded), size)
            yield encoded
            digest = hashlib.sha256()
            remaining = size
            with path.open("rb", buffering=0) as handle:
                while remaining:
                    chunk = handle.read(min(cls.ARCHIVE_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise GuaranteedStorageError(f"source file changed while archiving: {path}")
                    remaining -= len(chunk)
                    digest.update(chunk)
                    yield chunk
                if handle.read(1):
                    raise GuaranteedStorageError(f"source file grew while archiving: {path}")
            yield digest.digest()
        yield _ENTRY.pack(_END_PATH_LENGTH, 0)

    def commit_filesystem(self, fs: TDSFileSystem, *,
                          parallel_nodes: bool = True) -> GuaranteedCommitReport:
        staging_parent = self.root / ".transition-staging"
        staging_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="image-", dir=staging_parent) as tmp:
            staging = Path(tmp)
            persistence = TDSPersistence(staging)
            persistence.flush(fs, parallel_nodes=parallel_nodes)
            files = self._iter_regular_files(staging)
            source_bytes = sum(path.stat().st_size for path in files)
            generation = self.store.commit_stream(
                self._archive_chunks(staging, files),
                application_metadata={
                    "payload_schema": "tds.transition.image.v1",
                    "file_count": len(files),
                    "source_bytes": source_bytes,
                },
            )
        try:
            staging_parent.rmdir()
        except OSError:
            pass
        return GuaranteedCommitReport(
            generation=generation,
            files_archived=len(files),
            source_bytes=source_bytes,
            transition_mode="legacy-compatible-full-image",
        )

    def commit_filesystem_segmented(self, fs: TDSFileSystem, *,
                                    parallel_nodes: bool = True) -> SegmentedGuaranteedCommitReport:
        """Commit a legacy-compatible archive as deduplicated immutable segments.

        This Phase 9 path is explicit and opt-in. It does not alter the proven
        full-image commit API or activate Guaranteed Storage automatically.
        """
        staging_parent = self.root / ".segment-transition-staging"
        staging_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="image-", dir=staging_parent) as tmp:
            staging = Path(tmp)
            persistence = TDSPersistence(staging)
            persistence.flush(fs, parallel_nodes=parallel_nodes)
            files = self._iter_regular_files(staging)
            source_bytes = sum(path.stat().st_size for path in files)
            commit = self.segment_store.commit_stream(
                self._archive_chunks(staging, files),
                application_metadata={
                    "payload_schema": "tds.transition.image.v1",
                    "storage_schema": "tds.incremental-segments.v1",
                    "file_count": len(files),
                    "source_bytes": source_bytes,
                },
            )
        try:
            staging_parent.rmdir()
        except OSError:
            pass
        return SegmentedGuaranteedCommitReport(
            generation=commit.generation,
            files_archived=len(files),
            source_bytes=source_bytes,
            segments_created=commit.segments_created,
            segments_reused=commit.segments_reused,
            physical_bytes_written=commit.bytes_written,
            transition_mode="legacy-compatible-incremental-segments",
        )

    def commit_mount_segmented(self, legacy_mount: str | os.PathLike[str]) -> SegmentedGuaranteedCommitReport:
        """Commit an existing legacy mount byte-for-byte as immutable segments.

        Unlike :meth:`commit_filesystem_segmented`, this migration primitive does
        not reserialise a ``TDSFileSystem``.  It snapshots the existing mount,
        streams its exact regular-file inventory into the segment store, and
        proves that the source did not change before allowing the new segment
        pointer to remain authoritative.
        """
        source = Path(legacy_mount)
        before = self._snapshot_mount(source)
        files = self._iter_regular_files(source)
        source_bytes = sum(size for size, _digest in before.values())
        store = self.segment_store
        with store._mutation_lock():
            previous_generation = store._read_current_raw()
            commit = store._commit_stream_locked(
                self._archive_chunks(source, files),
                application_metadata={
                    "payload_schema": "tds.transition.image.v1",
                    "storage_schema": "tds.incremental-segments.v1",
                    "migration_schema": "tds.controlled-activation.v1",
                    "file_count": len(files),
                    "source_bytes": source_bytes,
                },
            )
            after = self._snapshot_mount(source)
            if before != after:
                current = store._read_current_raw()
                if current == commit.generation.generation_id:
                    if previous_generation is None:
                        store.current_path.unlink(missing_ok=True)
                        ImmutableGenerationStore._fsync_dir(store.root)
                    else:
                        store._replace_current(previous_generation)
                raise GuaranteedStorageError(
                    "legacy source changed during segmented activation qualification"
                )
        return SegmentedGuaranteedCommitReport(
            generation=commit.generation,
            files_archived=len(files),
            source_bytes=source_bytes,
            segments_created=commit.segments_created,
            segments_reused=commit.segments_reused,
            physical_bytes_written=commit.bytes_written,
            transition_mode="legacy-mount-exact-incremental-segments",
        )

    @staticmethod
    def _safe_relative_path(raw: bytes) -> Path:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GuaranteedStorageError("archive path is not valid UTF-8") from exc
        pure = PurePosixPath(text)
        if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
            raise GuaranteedStorageError(f"unsafe archive path: {text!r}")
        if any("\\" in part for part in pure.parts):
            raise GuaranteedStorageError(f"unsafe archive path separator: {text!r}")
        return Path(*pure.parts)

    @staticmethod
    def _path_identity(relative: Path) -> tuple[str, str]:
        """Return Unicode-normalized and case-folded identities for collision checks."""
        import unicodedata
        posix = PurePosixPath(*relative.parts).as_posix()
        normalized = unicodedata.normalize("NFC", posix)
        return normalized, normalized.casefold()

    @classmethod
    def _snapshot_mount(cls, root: Path) -> dict[str, tuple[int, str]]:
        if not root.exists() or not root.is_dir() or root.is_symlink():
            raise GuaranteedStorageError("legacy mount must be an existing real directory")
        snapshot: dict[str, tuple[int, str]] = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise GuaranteedStorageError(f"legacy mount contains a symlink: {relative}")
            if path.is_file():
                digest = hashlib.sha256()
                size = 0
                with path.open("rb", buffering=0) as handle:
                    while True:
                        chunk = handle.read(cls.ARCHIVE_CHUNK_BYTES)
                        if not chunk:
                            break
                        size += len(chunk)
                        digest.update(chunk)
                snapshot[relative] = (size, digest.hexdigest())
                if len(snapshot) > cls.MAX_ARCHIVE_FILES:
                    raise GuaranteedStorageError("legacy mount exceeds file-count budget")
            elif not path.is_dir():
                raise GuaranteedStorageError(f"legacy mount contains an unsupported entry: {relative}")
        return dict(sorted(snapshot.items()))

    @classmethod
    def _copy_mount_exact(cls, source: Path, destination: Path) -> None:
        for relative in cls._snapshot_mount(source):
            src = source / Path(*PurePosixPath(relative).parts)
            dst = destination / Path(*PurePosixPath(relative).parts)
            dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = open_binary_fd(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with src.open("rb", buffering=0) as handle:
                    while True:
                        chunk = handle.read(cls.ARCHIVE_CHUNK_BYTES)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        try:
                            offset = 0
                            while offset < len(view):
                                written = os.write(fd, view[offset:])
                                if written <= 0:
                                    raise GuaranteedStorageError("migration copy made no progress")
                                offset += written
                        finally:
                            view.release()
                os.fsync(fd)
            finally:
                os.close(fd)

    @staticmethod
    def _metadata_document(path: Path) -> Any:
        if path.name == "tds.manifest.json" or path.name.endswith(".tds.meta"):
            from .tds_json import loads_strict
            try:
                value, _backend = loads_strict(path.read_bytes())
                return value
            except Exception as exc:
                raise GuaranteedStorageError(f"metadata cannot be reopened: {path.name}") from exc
        return None

    @classmethod
    def _logical_mount_signature(cls, root: Path) -> dict[str, tuple[tuple[str, int, str], ...]]:
        from .tds_persistence import TDSReader
        signatures: dict[str, tuple[tuple[str, int, str], ...]] = {}
        for path in sorted(root.rglob("*.tds")):
            relative = path.relative_to(root).as_posix()
            reader = TDSReader(path)
            try:
                records = []
                for rec in reader._idx.all_records():
                    raw = reader.read_raw(rec.name)
                    # Exercise the normal reopen/deserialisation path as well.
                    reader.read(rec.name)
                    records.append((rec.name, int(rec.fmt_id), hashlib.sha256(raw).hexdigest()))
                signatures[relative] = tuple(records)
            finally:
                reader.close()
        return signatures

    def verify_round_trip(self, legacy_mount: str | os.PathLike[str],
                          destination: str | os.PathLike[str]) -> VerifiedMigrationReport:
        """Prove a legacy mount survives generation and reconstruction unchanged.

        Both the source copy and reconstructed mount remain private until every
        equivalence check passes. The legacy source is read-only from this API's
        perspective and is snapshotted again before publication.
        """
        source = Path(legacy_mount)
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            raise GuaranteedStorageError("verified migration destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        before = self._snapshot_mount(source)
        staging_parent = self.root / ".migration-staging"
        staging_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_materialized = destination.parent / f".{destination.name}.verified-{uuid.uuid4().hex}"
        previous_generation = self.store.current_generation()
        committed_generation: str | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="legacy-", dir=staging_parent) as tmp:
                staging = Path(tmp)
                self._copy_mount_exact(source, staging)
                staged = self._snapshot_mount(staging)
                after_copy = self._snapshot_mount(source)
                if before != after_copy or before != staged:
                    raise GuaranteedStorageError("legacy source changed while migration snapshot was captured")
                files = self._iter_regular_files(staging)
                source_bytes = sum(size for size, _digest in staged.values())
                generation = self.store.commit_stream(
                    self._archive_chunks(staging, files),
                    application_metadata={
                        "payload_schema": "tds.transition.image.v1",
                        "migration_schema": "tds.verified-round-trip.v1",
                        "file_count": len(files),
                        "source_bytes": source_bytes,
                    },
                )
                committed_generation = generation.generation_id
            self.materialize_current_report(private_materialized)
            reconstructed = self._snapshot_mount(private_materialized)
            source_final = self._snapshot_mount(source)
            inventory_ok = set(before) == set(reconstructed)
            lengths_ok = inventory_ok and all(before[p][0] == reconstructed[p][0] for p in before)
            digests_ok = inventory_ok and all(before[p][1] == reconstructed[p][1] for p in before)
            source_unchanged = before == source_final
            metadata_ok = True
            records: list[MigrationFileRecord] = []
            for relative, (size, digest) in before.items():
                src_path = source / Path(*PurePosixPath(relative).parts)
                dst_path = private_materialized / Path(*PurePosixPath(relative).parts)
                equivalent = True
                if relative == "tds.manifest.json" or relative.endswith(".tds.meta"):
                    equivalent = self._metadata_document(src_path) == self._metadata_document(dst_path)
                    metadata_ok = metadata_ok and equivalent
                records.append(MigrationFileRecord(relative, size, digest, equivalent))
            logical_ok = self._logical_mount_signature(source) == self._logical_mount_signature(private_materialized)
            eligible = all((inventory_ok, lengths_ok, digests_ok, metadata_ok, logical_ok, source_unchanged))
            if not eligible:
                raise GuaranteedStorageError(
                    "verified round-trip equivalence failed; activation remains prohibited"
                )
            if destination.exists() or destination.is_symlink():
                raise GuaranteedStorageError("verified migration destination appeared before publication")
            os.replace(str(private_materialized), str(destination))
            ImmutableGenerationStore._fsync_dir(destination.parent)
            return VerifiedMigrationReport(
                generation=generation,
                legacy_source=source,
                destination=destination,
                files_verified=len(records),
                bytes_verified=sum(item.byte_length for item in records),
                inventory_equivalent=inventory_ok,
                lengths_equivalent=lengths_ok,
                digests_equivalent=digests_ok,
                metadata_equivalent=metadata_ok,
                logical_reopen_equivalent=logical_ok,
                source_unchanged=source_unchanged,
                activation_eligible=eligible,
                published=True,
                file_records=tuple(records),
            )
        except Exception:
            if private_materialized.exists():
                shutil.rmtree(private_materialized, ignore_errors=True)
            if committed_generation is not None:
                try:
                    current = self.store._read_current_raw()
                    if current == committed_generation:
                        if previous_generation is None:
                            self.store.current_path.unlink(missing_ok=True)
                            ImmutableGenerationStore._fsync_dir(self.root)
                        else:
                            self.store._replace_current(
                                previous_generation, checkpoint_prefix="migration_rollback"
                            )
                except Exception as rollback_exc:
                    raise GuaranteedStorageError(
                        "migration failed and prior generation could not be restored"
                    ) from rollback_exc
            raise
        finally:
            try:
                staging_parent.rmdir()
            except OSError:
                pass

    def materialize_current(self, destination: str | os.PathLike[str]) -> Path:
        """Verify and atomically publish the current legacy-compatible image.

        The destination must not exist. Extraction occurs in a uniquely-created
        sibling directory. The exact path inventory is validated before any
        directory publication, and failures remove only the private directory
        created by this invocation.
        """
        return self.materialize_current_report(destination).destination

    def materialize_current_report(self, destination: str | os.PathLike[str]) -> MaterializationReport:
        generation_id = self.store.current_generation()
        if generation_id is None:
            raise GuaranteedStorageError("no current generation")
        info = self.store.verify(generation_id)
        return self._materialize_archive_report(
            destination, lambda: (info.path / self.store.DATA_NAME).open("rb", buffering=0)
        )

    def materialize_segmented_current(self, destination: str | os.PathLike[str]) -> Path:
        return self.materialize_segmented_current_report(destination).destination

    def materialize_segmented_current_report(self, destination: str | os.PathLike[str]) -> MaterializationReport:
        generation_id = self.segment_store.current_generation()
        if generation_id is None:
            raise GuaranteedStorageError("no current segment generation")
        return self.materialize_segmented_generation_report(generation_id, destination)

    def materialize_segmented_generation(self, generation_id: str,
                                         destination: str | os.PathLike[str]) -> Path:
        """Verify and materialise one explicitly named segment generation."""
        return self.materialize_segmented_generation_report(generation_id, destination).destination

    def materialize_segmented_generation_report(self, generation_id: str,
                                                destination: str | os.PathLike[str]) -> MaterializationReport:
        self.segment_store.verify(generation_id)
        return self._materialize_archive_report(
            destination, lambda: _SegmentArchiveReader(self.segment_store.iter_generation_bytes(generation_id))
        )

    def _materialize_archive_report(self, destination: str | os.PathLike[str], source_factory) -> MaterializationReport:
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            raise GuaranteedStorageError("materialisation destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = Path(tempfile.mkdtemp(prefix=f".{destination.name}.materializing-", dir=destination.parent))
        count = 0
        total_bytes = 0
        exact_paths: set[str] = set()
        normalized_paths: set[str] = set()
        folded_paths: set[str] = set()
        self._checkpoint("materialize_temp_created")
        try:
            with source_factory() as source:
                if source.read(len(_MAGIC)) != _MAGIC:
                    raise GuaranteedStorageError("unsupported transition image format")
                while True:
                    header = source.read(_ENTRY.size)
                    if len(header) != _ENTRY.size:
                        raise GuaranteedStorageError("transition image is truncated")
                    path_len, size = _ENTRY.unpack(header)
                    if path_len == _END_PATH_LENGTH:
                        if size != 0:
                            raise GuaranteedStorageError("invalid transition end marker")
                        if source.read(1):
                            raise GuaranteedStorageError("transition image contains trailing bytes")
                        break
                    if path_len > self.MAX_PATH_BYTES:
                        raise GuaranteedStorageError("transition image path exceeds limit")
                    raw_path = source.read(path_len)
                    if len(raw_path) != path_len:
                        raise GuaranteedStorageError("transition image path is truncated")
                    relative = self._safe_relative_path(raw_path)
                    exact = PurePosixPath(*relative.parts).as_posix()
                    normalized, folded = self._path_identity(relative)
                    if exact in exact_paths:
                        raise GuaranteedStorageError(f"duplicate transition path: {exact}")
                    if normalized in normalized_paths:
                        raise GuaranteedStorageError(f"Unicode-normalization path collision: {exact}")
                    if folded in folded_paths:
                        raise GuaranteedStorageError(f"case-folding path collision: {exact}")
                    exact_paths.add(exact)
                    normalized_paths.add(normalized)
                    folded_paths.add(folded)
                    self._checkpoint("materialize_before_file")
                    target = temp / relative
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    digest = hashlib.sha256()
                    remaining = size
                    fd = open_binary_fd(
                        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                    try:
                        while remaining:
                            chunk = source.read(min(self.ARCHIVE_CHUNK_BYTES, remaining))
                            if not chunk:
                                raise GuaranteedStorageError("transition file payload is truncated")
                            remaining -= len(chunk)
                            digest.update(chunk)
                            view = memoryview(chunk)
                            try:
                                offset = 0
                                while offset < len(view):
                                    written = os.write(fd, view[offset:])
                                    if written <= 0:
                                        raise GuaranteedStorageError("materialisation write made no progress")
                                    offset += written
                            finally:
                                view.release()
                        self._checkpoint("materialize_file_before_fsync")
                        os.fsync(fd)
                        self._checkpoint("materialize_file_after_fsync")
                    finally:
                        os.close(fd)
                    expected = source.read(_DIGEST_BYTES)
                    if len(expected) != _DIGEST_BYTES or digest.digest() != expected:
                        raise GuaranteedStorageError(f"transition file digest mismatch: {relative}")
                    count += 1
                    total_bytes += size
                    if count > self.MAX_ARCHIVE_FILES:
                        raise GuaranteedStorageError("transition image exceeds file-count budget")
                    self._checkpoint("materialize_after_file")
            def verify_inventory() -> None:
                observed: set[str] = set()
                unexpected_special: list[str] = []
                for item in temp.rglob("*"):
                    relative_item = item.relative_to(temp).as_posix()
                    if item.is_symlink():
                        unexpected_special.append(relative_item)
                    elif item.is_file():
                        observed.add(relative_item)
                    elif not item.is_dir():
                        unexpected_special.append(relative_item)
                if observed != exact_paths or unexpected_special:
                    missing = sorted(exact_paths - observed)
                    unexpected = sorted((observed - exact_paths) | set(unexpected_special))
                    raise GuaranteedStorageError(
                        f"materialised inventory mismatch; missing={missing!r}, unexpected={unexpected!r}"
                    )

            verify_inventory()
            self._checkpoint("materialize_before_directory_fsync")
            ImmutableGenerationStore._fsync_dir(temp)
            self._checkpoint("materialize_after_directory_fsync")
            # Recheck immediately before publication to detect concurrent or
            # injected changes that occurred after the first inventory pass.
            verify_inventory()
            if destination.exists() or destination.is_symlink():
                raise GuaranteedStorageError("materialisation destination appeared before publication")
            self._checkpoint("materialize_before_publish")
            os.replace(str(temp), str(destination))
            self._checkpoint("materialize_after_publish")
            ImmutableGenerationStore._fsync_dir(destination.parent)
            self._checkpoint("materialize_parent_synced")
            return MaterializationReport(destination, count, total_bytes, True)
        except Exception:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
            raise

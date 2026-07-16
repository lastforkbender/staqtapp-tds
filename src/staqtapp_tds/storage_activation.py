"""Explicit Phase 10 activation control for Guaranteed Storage.

The established :class:`TDSPersistence` path remains the default.  This module
adds a separate control plane that can qualify an exact legacy mount, activate
the segmented generation path only after every equivalence gate passes, expose
the selected mode, and materialise the latest guaranteed generation into a new
legacy mount for lossless rollback.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import time
import uuid
from typing import Any, Callable, Iterator

from .generation_store import ImmutableGenerationStore
from .guaranteed_storage import GuaranteedStorageBridge, GuaranteedStorageError
from .tds_filesystem import TDSFileSystem
from .tds_json import dumps_canonical, loads_strict
from .tds_persistence import TDSPersistence


_QUALIFICATION_RE = re.compile(r"^qual-[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StorageMode(str, Enum):
    """Durable operating modes understood by the activation controller."""

    LEGACY = "legacy"
    GUARANTEED_SEGMENTED = "guaranteed-segmented"


class ControlledActivationError(GuaranteedStorageError):
    """A controlled activation, mode read, commit, or rollback failed closed."""


@dataclass(frozen=True, slots=True)
class ActivationQualification:
    qualification_id: str
    created_ns: int
    target_mode: StorageMode
    legacy_mount: Path
    generation_id: str
    source_inventory_sha256: str
    files_verified: int
    bytes_verified: int
    inventory_equivalent: bool
    lengths_equivalent: bool
    digests_equivalent: bool
    metadata_equivalent: bool
    logical_reopen_equivalent: bool
    source_unchanged: bool
    activation_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualification_id": self.qualification_id,
            "created_ns": self.created_ns,
            "target_mode": self.target_mode.value,
            "legacy_mount": str(self.legacy_mount),
            "generation_id": self.generation_id,
            "source_inventory_sha256": self.source_inventory_sha256,
            "files_verified": self.files_verified,
            "bytes_verified": self.bytes_verified,
            "inventory_equivalent": self.inventory_equivalent,
            "lengths_equivalent": self.lengths_equivalent,
            "digests_equivalent": self.digests_equivalent,
            "metadata_equivalent": self.metadata_equivalent,
            "logical_reopen_equivalent": self.logical_reopen_equivalent,
            "source_unchanged": self.source_unchanged,
            "activation_eligible": self.activation_eligible,
        }


@dataclass(frozen=True, slots=True)
class StorageActivationStatus:
    mode: StorageMode
    revision: int
    legacy_mount: Path
    qualification_id: str | None
    qualified_generation: str | None
    current_generation: str | None
    activation_verified: bool
    current_generation_verified: bool
    rollback_available: bool
    state_persisted: bool
    changed_ns: int | None
    previous_mode: StorageMode | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "revision": self.revision,
            "legacy_mount": str(self.legacy_mount),
            "qualification_id": self.qualification_id,
            "qualified_generation": self.qualified_generation,
            "current_generation": self.current_generation,
            "activation_verified": self.activation_verified,
            "current_generation_verified": self.current_generation_verified,
            "rollback_available": self.rollback_available,
            "state_persisted": self.state_persisted,
            "changed_ns": self.changed_ns,
            "previous_mode": self.previous_mode.value if self.previous_mode is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ControlledCommitReport:
    mode: StorageMode
    generation_id: str | None
    files_archived: int
    source_bytes: int
    segments_created: int
    segments_reused: int
    physical_bytes_written: int


class ControlledStorage:
    """Mode-aware persistence facade with explicit activation and rollback.

    Merely constructing the controller never changes the operating mode.  When
    no durable mode record exists, :attr:`StorageMode.LEGACY` is returned and
    ordinary ``TDSPersistence`` remains the commit path.
    """

    STATE_SCHEMA = "tds.storage-activation-state.v1"
    QUALIFICATION_SCHEMA = "tds.storage-activation-qualification.v1"
    STATE_NAME = "STORAGE_MODE.json"
    QUALIFICATION_DIR = "activation-qualifications"
    ROLLBACK_DIR = "legacy-rollbacks"
    MAX_CONTROL_BYTES = 1024 * 1024
    ACTIVATE_ACKNOWLEDGEMENT = "activate-guaranteed-segmented"
    ROLLBACK_ACKNOWLEDGEMENT = "rollback-to-legacy"

    _STATE_FIELDS = {
        "schema", "revision", "mode", "legacy_mount", "qualification_id",
        "qualified_generation", "changed_ns", "previous_mode",
    }
    _QUALIFICATION_FIELDS = {
        "schema", "qualification_id", "created_ns", "target_mode", "legacy_mount",
        "generation_id", "source_inventory_sha256", "files_verified", "bytes_verified",
        "inventory_equivalent", "lengths_equivalent", "digests_equivalent",
        "metadata_equivalent", "logical_reopen_equivalent", "source_unchanged",
        "activation_eligible",
    }

    def __init__(self, root: str | os.PathLike[str], legacy_mount: str | os.PathLike[str], *,
                 fault_hook: Callable[[str], None] | None = None):
        self.root = Path(root).resolve()
        self.default_legacy_mount = Path(legacy_mount).resolve()
        self._fault_hook = fault_hook
        if self.root == self.default_legacy_mount or self.root.is_relative_to(self.default_legacy_mount):
            raise ControlledActivationError("Guaranteed Storage root must not be inside the legacy mount")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ControlledActivationError("Guaranteed Storage root must be a real directory")
        self.state_path = self.root / self.STATE_NAME
        self.qualification_dir = self.root / self.QUALIFICATION_DIR
        self.rollback_dir = self.root / self.ROLLBACK_DIR
        self.qualification_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.bridge = GuaranteedStorageBridge(self.root, fault_hook=fault_hook)

    def _checkpoint(self, name: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(name)

    @staticmethod
    def _require_non_negative_int(value: Any, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ControlledActivationError(f"invalid {label}")
        return value

    @staticmethod
    def _require_optional_string(value: Any, label: str) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ControlledActivationError(f"invalid {label}")
        return value

    @staticmethod
    def _inventory_fingerprint(snapshot: dict[str, tuple[int, str]]) -> str:
        payload = {
            "files": [
                {"path": path, "size": size, "sha256": digest}
                for path, (size, digest) in sorted(snapshot.items())
            ]
        }
        encoded = dumps_canonical(payload)[0]
        return hashlib.sha256(encoded).hexdigest()

    def _validate_legacy_mount(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_dir() or resolved.is_symlink():
            raise ControlledActivationError("legacy mount must be an existing real directory")
        if self.root.is_relative_to(resolved):
            raise ControlledActivationError("Guaranteed Storage root must not be contained by the legacy mount")
        return resolved

    def _read_canonical_mapping(self, path: Path, *, label: str) -> dict[str, Any]:
        if not path.is_file() or path.is_symlink():
            raise ControlledActivationError(f"{label} is not a regular file")
        raw = path.read_bytes()
        if len(raw) > self.MAX_CONTROL_BYTES:
            raise ControlledActivationError(f"{label} exceeds size budget")
        try:
            value, _backend = loads_strict(raw, expected_type=dict)
        except Exception as exc:
            raise ControlledActivationError(f"{label} is invalid") from exc
        if raw != dumps_canonical(value)[0]:
            raise ControlledActivationError(f"{label} is not canonical or was modified")
        return value

    def _atomic_write_mapping(self, path: Path, value: dict[str, Any], *, checkpoint: str) -> None:
        encoded = dumps_canonical(value)[0]
        if len(encoded) > self.MAX_CONTROL_BYTES:
            raise ControlledActivationError("control record exceeds size budget")
        temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        durable = self.bridge.segment_store.policy.durability.value != "relaxed"
        try:
            self.bridge.segment_store._write_all_exclusive(temp, encoded, durable=durable)
            self._checkpoint(checkpoint)
            os.replace(str(temp), str(path))
            if durable:
                ImmutableGenerationStore._fsync_dir(path.parent)
        finally:
            temp.unlink(missing_ok=True)

    def _default_state(self) -> dict[str, Any]:
        return {
            "schema": self.STATE_SCHEMA,
            "revision": 0,
            "mode": StorageMode.LEGACY.value,
            "legacy_mount": str(self.default_legacy_mount),
            "qualification_id": None,
            "qualified_generation": None,
            "changed_ns": None,
            "previous_mode": None,
        }

    def _load_state(self) -> tuple[dict[str, Any], bool]:
        if not self.state_path.exists():
            return self._default_state(), False
        value = self._read_canonical_mapping(self.state_path, label="storage mode record")
        if set(value) != self._STATE_FIELDS or value.get("schema") != self.STATE_SCHEMA:
            raise ControlledActivationError("storage mode record has an unsupported schema")
        self._require_non_negative_int(value["revision"], "storage mode revision")
        try:
            StorageMode(value["mode"])
        except (TypeError, ValueError) as exc:
            raise ControlledActivationError("storage mode record names an unknown mode") from exc
        if not isinstance(value["legacy_mount"], str) or not value["legacy_mount"]:
            raise ControlledActivationError("storage mode record has an invalid legacy mount")
        qualification_id = self._require_optional_string(value["qualification_id"], "qualification id")
        if qualification_id is not None and not _QUALIFICATION_RE.fullmatch(qualification_id):
            raise ControlledActivationError("storage mode record has an invalid qualification id")
        generation = self._require_optional_string(value["qualified_generation"], "qualified generation")
        if value["changed_ns"] is not None:
            self._require_non_negative_int(value["changed_ns"], "mode-change time")
        previous = self._require_optional_string(value["previous_mode"], "previous mode")
        if previous is not None:
            try:
                StorageMode(previous)
            except ValueError as exc:
                raise ControlledActivationError("storage mode record has an invalid previous mode") from exc
        mode = StorageMode(value["mode"])
        if mode is StorageMode.GUARANTEED_SEGMENTED and (qualification_id is None or generation is None):
            raise ControlledActivationError("Guaranteed Storage mode lacks qualification evidence")
        return value, True

    def status(self, *, verify_current: bool = True) -> StorageActivationStatus:
        state, persisted = self._load_state()
        mode = StorageMode(state["mode"])
        current: str | None = None
        verified = mode is StorageMode.LEGACY
        current_verified = False
        if mode is StorageMode.GUARANTEED_SEGMENTED:
            try:
                qualification = self._read_qualification(state["qualification_id"])
                if (qualification.generation_id != state["qualified_generation"]
                        or not qualification.activation_eligible):
                    raise ControlledActivationError("active qualification evidence does not match mode state")
                current = self.bridge.segment_store._read_current_raw()
                if current is not None and verify_current:
                    self.bridge.segment_store.verify(current)
                    current_verified = True
            except Exception as exc:
                raise ControlledActivationError("active Guaranteed Storage generation is invalid") from exc
            if current is None:
                raise ControlledActivationError("Guaranteed Storage mode has no current generation")
            verified = True
        previous = StorageMode(state["previous_mode"]) if state["previous_mode"] is not None else None
        return StorageActivationStatus(
            mode=mode,
            revision=state["revision"],
            legacy_mount=Path(state["legacy_mount"]),
            qualification_id=state["qualification_id"],
            qualified_generation=state["qualified_generation"],
            current_generation=current,
            activation_verified=verified,
            current_generation_verified=current_verified,
            rollback_available=mode is StorageMode.GUARANTEED_SEGMENTED,
            state_persisted=persisted,
            changed_ns=state["changed_ns"],
            previous_mode=previous,
        )

    def storage_status(self) -> dict[str, Any]:
        """Return the JSON-safe mode snapshot used by Browser/admin surfaces."""
        # Browser polling remains an observer path: it reads the tiny pointer and
        # qualification receipt but never rehashes segment payloads.
        return self.status(verify_current=False).to_dict()

    def observation_snapshot(self) -> dict[str, Any]:
        return {"storage_mode": self.storage_status()}

    def _compare_mounts(self, source: Path, reconstructed: Path,
                        before: dict[str, tuple[int, str]]) -> dict[str, bool]:
        observed = self.bridge._snapshot_mount(reconstructed)
        inventory_ok = set(before) == set(observed)
        lengths_ok = inventory_ok and all(before[path][0] == observed[path][0] for path in before)
        digests_ok = inventory_ok and all(before[path][1] == observed[path][1] for path in before)
        metadata_ok = inventory_ok
        if metadata_ok:
            for relative in before:
                if relative == "tds.manifest.json" or relative.endswith(".tds.meta"):
                    src = source / Path(*PurePosixPath(relative).parts)
                    dst = reconstructed / Path(*PurePosixPath(relative).parts)
                    if self.bridge._metadata_document(src) != self.bridge._metadata_document(dst):
                        metadata_ok = False
                        break
        try:
            logical_ok = self.bridge._logical_mount_signature(source) == self.bridge._logical_mount_signature(reconstructed)
        except Exception as exc:
            raise ControlledActivationError("qualified mount could not be logically reopened") from exc
        source_unchanged = before == self.bridge._snapshot_mount(source)
        return {
            "inventory_equivalent": inventory_ok,
            "lengths_equivalent": lengths_ok,
            "digests_equivalent": digests_ok,
            "metadata_equivalent": metadata_ok,
            "logical_reopen_equivalent": logical_ok,
            "source_unchanged": source_unchanged,
        }

    def _restore_segment_pointer(self, candidate: str, previous: str | None) -> None:
        store = self.bridge.segment_store
        with store._mutation_lock():
            current = store._read_current_raw()
            if current != candidate:
                raise ControlledActivationError("activation candidate is no longer current; pointer was not changed")
            if previous is None:
                store.current_path.unlink(missing_ok=True)
                ImmutableGenerationStore._fsync_dir(store.root)
            else:
                store.verify(previous)
                store._replace_current(previous)

    def _qualification_path(self, qualification_id: str) -> Path:
        if not _QUALIFICATION_RE.fullmatch(qualification_id):
            raise ControlledActivationError("invalid activation qualification id")
        return self.qualification_dir / f"{qualification_id}.json"

    def _qualification_mapping(self, report: ActivationQualification) -> dict[str, Any]:
        return {"schema": self.QUALIFICATION_SCHEMA, **report.to_dict()}

    def _read_qualification(self, qualification_id: str) -> ActivationQualification:
        value = self._read_canonical_mapping(
            self._qualification_path(qualification_id), label="activation qualification"
        )
        if set(value) != self._QUALIFICATION_FIELDS or value.get("schema") != self.QUALIFICATION_SCHEMA:
            raise ControlledActivationError("activation qualification has an unsupported schema")
        if value["qualification_id"] != qualification_id:
            raise ControlledActivationError("activation qualification identity mismatch")
        self._require_non_negative_int(value["created_ns"], "qualification creation time")
        self._require_non_negative_int(value["files_verified"], "qualified file count")
        self._require_non_negative_int(value["bytes_verified"], "qualified byte count")
        if not isinstance(value["legacy_mount"], str) or not value["legacy_mount"]:
            raise ControlledActivationError("activation qualification has an invalid legacy mount")
        try:
            target_mode = StorageMode(value["target_mode"])
        except (TypeError, ValueError) as exc:
            raise ControlledActivationError("activation qualification has an invalid target mode") from exc
        if target_mode is not StorageMode.GUARANTEED_SEGMENTED:
            raise ControlledActivationError("activation qualification targets an unsupported mode")
        if not isinstance(value["generation_id"], str):
            raise ControlledActivationError("activation qualification has an invalid generation")
        if not isinstance(value["source_inventory_sha256"], str) or not _SHA256_RE.fullmatch(value["source_inventory_sha256"]):
            raise ControlledActivationError("activation qualification has an invalid inventory fingerprint")
        gate_names = (
            "inventory_equivalent", "lengths_equivalent", "digests_equivalent",
            "metadata_equivalent", "logical_reopen_equivalent", "source_unchanged",
            "activation_eligible",
        )
        if any(not isinstance(value[name], bool) for name in gate_names):
            raise ControlledActivationError("activation qualification contains a non-boolean gate")
        return ActivationQualification(
            qualification_id=qualification_id,
            created_ns=value["created_ns"],
            target_mode=target_mode,
            legacy_mount=Path(value["legacy_mount"]),
            generation_id=value["generation_id"],
            source_inventory_sha256=value["source_inventory_sha256"],
            files_verified=value["files_verified"],
            bytes_verified=value["bytes_verified"],
            inventory_equivalent=value["inventory_equivalent"],
            lengths_equivalent=value["lengths_equivalent"],
            digests_equivalent=value["digests_equivalent"],
            metadata_equivalent=value["metadata_equivalent"],
            logical_reopen_equivalent=value["logical_reopen_equivalent"],
            source_unchanged=value["source_unchanged"],
            activation_eligible=value["activation_eligible"],
        )

    def qualify_activation(self) -> ActivationQualification:
        """Prove a legacy mount is exactly reconstructable through Phase 9 segments.

        Qualification does not change the operating mode.  A durable evidence
        receipt is written only after every gate passes.
        """
        status = self.status()
        if status.mode is not StorageMode.LEGACY:
            raise ControlledActivationError("activation qualification requires legacy mode")
        source = self._validate_legacy_mount(status.legacy_mount)
        before = self.bridge._snapshot_mount(source)
        commit = None
        try:
            commit = self.bridge.commit_mount_segmented(source)
            generation_id = commit.generation.generation_id
            with tempfile.TemporaryDirectory(prefix=".activation-qualification-", dir=self.root) as tmp:
                reconstructed = Path(tmp) / "mount"
                self.bridge.materialize_segmented_generation(generation_id, reconstructed)
                gates = self._compare_mounts(source, reconstructed, before)
            eligible = all(gates.values())
            if not eligible:
                raise ControlledActivationError("activation equivalence gates did not all pass")
            report = ActivationQualification(
                qualification_id=f"qual-{uuid.uuid4().hex}",
                created_ns=time.time_ns(),
                target_mode=StorageMode.GUARANTEED_SEGMENTED,
                legacy_mount=source,
                generation_id=generation_id,
                source_inventory_sha256=self._inventory_fingerprint(before),
                files_verified=len(before),
                bytes_verified=sum(size for size, _digest in before.values()),
                activation_eligible=True,
                **gates,
            )
            path = self._qualification_path(report.qualification_id)
            self._atomic_write_mapping(path, self._qualification_mapping(report), checkpoint="qualification_before_publish")
            return report
        except Exception:
            if commit is not None:
                self._restore_segment_pointer(
                    commit.generation.generation_id, commit.generation.parent_generation
                )
            raise

    def activate(self, qualification: ActivationQualification | str, *,
                 acknowledgement: str) -> StorageActivationStatus:
        """Atomically select Guaranteed Storage after revalidating qualification."""
        if acknowledgement != self.ACTIVATE_ACKNOWLEDGEMENT:
            raise ControlledActivationError("explicit Guaranteed Storage activation acknowledgement is required")
        current_status = self.status()
        if current_status.mode is not StorageMode.LEGACY:
            raise ControlledActivationError("Guaranteed Storage is already active")
        qualification_id = qualification.qualification_id if isinstance(qualification, ActivationQualification) else qualification
        report = self._read_qualification(qualification_id)
        source = self._validate_legacy_mount(current_status.legacy_mount)
        if source != report.legacy_mount.resolve():
            raise ControlledActivationError("qualified legacy mount is not the active legacy mount")
        before = self.bridge._snapshot_mount(source)
        if self._inventory_fingerprint(before) != report.source_inventory_sha256:
            raise ControlledActivationError("legacy mount changed after activation qualification")
        store = self.bridge.segment_store
        with store._mutation_lock():
            if store._read_current_raw() != report.generation_id:
                raise ControlledActivationError("qualified segment generation is no longer current")
            store.verify(report.generation_id)
            with tempfile.TemporaryDirectory(prefix=".activation-final-", dir=self.root) as tmp:
                reconstructed = Path(tmp) / "mount"
                self.bridge.materialize_segmented_generation(report.generation_id, reconstructed)
                gates = self._compare_mounts(source, reconstructed, before)
            if not report.activation_eligible or not all(gates.values()):
                raise ControlledActivationError("activation revalidation failed")
            state = {
                "schema": self.STATE_SCHEMA,
                "revision": current_status.revision + 1,
                "mode": StorageMode.GUARANTEED_SEGMENTED.value,
                "legacy_mount": str(source),
                "qualification_id": report.qualification_id,
                "qualified_generation": report.generation_id,
                "changed_ns": time.time_ns(),
                "previous_mode": StorageMode.LEGACY.value,
            }
            self._atomic_write_mapping(
                self.state_path, state, checkpoint="activation_before_state_publish"
            )
        return self.status()

    def commit_filesystem(self, fs: TDSFileSystem, *,
                          parallel_nodes: bool = True) -> ControlledCommitReport:
        """Commit through the explicitly selected mode without an implicit switch."""
        status = self.status()
        if status.mode is StorageMode.LEGACY:
            mount = self._validate_legacy_mount(status.legacy_mount)
            result = TDSPersistence(mount).flush(fs, parallel_nodes=parallel_nodes)
            return ControlledCommitReport(
                mode=status.mode,
                generation_id=None,
                files_archived=len(result),
                source_bytes=0,
                segments_created=0,
                segments_reused=0,
                physical_bytes_written=0,
            )
        report = self.bridge.commit_filesystem_segmented(fs, parallel_nodes=parallel_nodes)
        return ControlledCommitReport(
            mode=status.mode,
            generation_id=report.generation.generation_id,
            files_archived=report.files_archived,
            source_bytes=report.source_bytes,
            segments_created=report.segments_created,
            segments_reused=report.segments_reused,
            physical_bytes_written=report.physical_bytes_written,
        )

    @contextmanager
    def active_mount(self) -> Iterator[Path]:
        """Yield the selected legacy mount or a private verified reconstruction."""
        status = self.status()
        if status.mode is StorageMode.LEGACY:
            yield self._validate_legacy_mount(status.legacy_mount)
            return
        if status.current_generation is None:
            raise ControlledActivationError("Guaranteed Storage has no current generation")
        with tempfile.TemporaryDirectory(prefix=".active-guaranteed-mount-", dir=self.root) as tmp:
            destination = Path(tmp) / "mount"
            self.bridge.materialize_segmented_generation(status.current_generation, destination)
            yield destination

    def rollback_to_legacy(self, *, acknowledgement: str) -> StorageActivationStatus:
        """Materialise current guaranteed bytes and atomically select them as legacy.

        The pre-activation legacy mount and all segment generations are retained.
        Rollback therefore changes authority without overwriting either copy.
        """
        if acknowledgement != self.ROLLBACK_ACKNOWLEDGEMENT:
            raise ControlledActivationError("explicit legacy rollback acknowledgement is required")
        status = self.status()
        if status.mode is not StorageMode.GUARANTEED_SEGMENTED or status.current_generation is None:
            raise ControlledActivationError("Guaranteed Storage is not active")
        self.rollback_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = self.rollback_dir / f"legacy-r{status.revision + 1:06d}-{uuid.uuid4().hex[:12]}"
        store = self.bridge.segment_store
        published = False
        try:
            with store._mutation_lock():
                if store._read_current_raw() != status.current_generation:
                    raise ControlledActivationError("current generation changed before rollback")
                store.verify(status.current_generation)
                self.bridge.materialize_segmented_generation(status.current_generation, destination)
                # Reopening every .tds file is a mandatory rollback gate.
                self.bridge._logical_mount_signature(destination)
                state = {
                    "schema": self.STATE_SCHEMA,
                    "revision": status.revision + 1,
                    "mode": StorageMode.LEGACY.value,
                    "legacy_mount": str(destination.resolve()),
                    "qualification_id": status.qualification_id,
                    "qualified_generation": status.current_generation,
                    "changed_ns": time.time_ns(),
                    "previous_mode": StorageMode.GUARANTEED_SEGMENTED.value,
                }
                self._atomic_write_mapping(
                    self.state_path, state, checkpoint="rollback_before_state_publish"
                )
                published = True
        finally:
            if not published and destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
        return self.status()

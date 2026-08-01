"""Atomic local project files and Eaglegate candidate compiler."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

from .capability import (
    EAGLEGATE_CONFIG_FILENAME,
    EAGLEGATE_LOCK_FILENAME,
    EaglegateLock,
    lock_to_toml,
)
from .configuration import (
    EaglegateConfiguration,
    configuration_to_toml,
    profile_configuration,
)
from .contract import (
    EAGLEGATE_CAPABILITY_SNAPSHOT_ID,
    EaglegateContractError,
    EaglegateFault,
)
from .plans import EaglegateQualificationSummary, EaglegateSpeculationEpoch

MAX_EAGLEGATE_CONTROL_FILE_BYTES = 1 << 20


def _read_bounded_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise EaglegateContractError(f"could not open {path}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise EaglegateContractError(f"{path} must be a regular file")
        if info.st_size > MAX_EAGLEGATE_CONTROL_FILE_BYTES:
            raise EaglegateContractError(
                f"{path} exceeds the control-file byte bound",
                fault=EaglegateFault.BOUND_EXCEEDED,
            )
        chunks: list[bytes] = []
        remaining = MAX_EAGLEGATE_CONTROL_FILE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 << 10, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_EAGLEGATE_CONTROL_FILE_BYTES:
            raise EaglegateContractError(
                f"{path} exceeds the control-file byte bound",
                fault=EaglegateFault.BOUND_EXCEEDED,
            )
        return data
    finally:
        os.close(fd)


def _atomic_write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


def initialize_project(
    directory: str | os.PathLike[str],
    *,
    profile: str = "conservative",
    force: bool = False,
) -> tuple[Path, Path]:
    root = Path(directory)
    config_path = root / EAGLEGATE_CONFIG_FILENAME
    lock_path = root / EAGLEGATE_LOCK_FILENAME
    if not force and (config_path.exists() or lock_path.exists()):
        raise EaglegateContractError(
            "refusing to overwrite Eaglegate files",
            fault=EaglegateFault.PUBLICATION_CONFLICT,
        )
    _atomic_write(config_path, configuration_to_toml(profile_configuration(profile)), 0o644)
    _atomic_write(lock_path, lock_to_toml(EaglegateLock.unresolved()), 0o600)
    return config_path, lock_path


def _load_toml(path: Path) -> Mapping[str, Any]:
    try:
        return tomllib.loads(_read_bounded_regular_file(path).decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise EaglegateContractError(f"could not read {path}: {exc}") from exc


def load_configuration(path: str | os.PathLike[str]) -> EaglegateConfiguration:
    return EaglegateConfiguration.from_mapping(_load_toml(Path(path)))


def load_lock(path: str | os.PathLike[str]) -> EaglegateLock:
    return EaglegateLock.from_mapping(_load_toml(Path(path)))


def load_project(
    directory: str | os.PathLike[str],
) -> tuple[EaglegateConfiguration, EaglegateLock]:
    root = Path(directory)
    return (
        load_configuration(root / EAGLEGATE_CONFIG_FILENAME),
        load_lock(root / EAGLEGATE_LOCK_FILENAME),
    )


def lock_from_capability_snapshot(data: Mapping[str, Any]) -> EaglegateLock:
    values = dict(data)
    if values.get("snapshot_contract_id") != EAGLEGATE_CAPABILITY_SNAPSHOT_ID:
        raise EaglegateContractError(
            "capability snapshot identity mismatch",
            fault=EaglegateFault.IDENTITY_MISMATCH,
        )
    values["resolved"] = True
    return EaglegateLock.from_mapping(values)


def resolve_lock_from_snapshot(
    directory: str | os.PathLike[str],
    snapshot_path: str | os.PathLike[str],
    *,
    force: bool = False,
) -> Path:
    root = Path(directory)
    lock_path = root / EAGLEGATE_LOCK_FILENAME
    if lock_path.exists() and not force and load_lock(lock_path).resolved:
        raise EaglegateContractError(
            "resolved lock replacement requires --force",
            fault=EaglegateFault.PUBLICATION_CONFLICT,
        )
    try:
        data = json.loads(
            _read_bounded_regular_file(Path(snapshot_path)).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EaglegateContractError(f"could not read capability snapshot: {exc}") from exc
    if not isinstance(data, Mapping):
        raise EaglegateContractError("capability snapshot must be an object")
    _atomic_write(lock_path, lock_to_toml(lock_from_capability_snapshot(data)), 0o600)
    return lock_path


def compile_project(
    directory: str | os.PathLike[str],
    *,
    qualification: EaglegateQualificationSummary | None = None,
) -> EaglegateSpeculationEpoch:
    config, lock = load_project(directory)
    return config.compile(lock, qualification)


def epoch_diff(
    left: EaglegateSpeculationEpoch,
    right: EaglegateSpeculationEpoch,
) -> dict[str, Any]:
    left_plans = {plan.plan_id: plan for plan in left.plans}
    right_plans = {plan.plan_id: plan for plan in right.plans}
    added = sorted(set(right_plans) - set(left_plans))
    removed = sorted(set(left_plans) - set(right_plans))
    changed = sorted(
        key
        for key in set(left_plans) & set(right_plans)
        if left_plans[key].plan_root != right_plans[key].plan_root
    )
    identity_changed = left.identity.identity_root != right.identity.identity_root
    return {
        "left_epoch_root": left.epoch_root,
        "right_epoch_root": right.epoch_root,
        "equal": left.epoch_root == right.epoch_root,
        "identity_changed": identity_changed,
        "policy_changed": left.policy.policy_root != right.policy.policy_root,
        "qualification_changed": left.qualification_root != right.qualification_root,
        "plans_added": added,
        "plans_removed": removed,
        "plans_changed": changed,
        "requires_full_requalification": bool(
            identity_changed or added or removed or changed
        ),
    }


__all__ = [
    "compile_project",
    "epoch_diff",
    "initialize_project",
    "load_configuration",
    "load_lock",
    "load_project",
    "lock_from_capability_snapshot",
    "resolve_lock_from_snapshot",
]

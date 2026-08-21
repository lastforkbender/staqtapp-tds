#!/usr/bin/env python3
"""Fail-closed hierarchical CPU-control evidence for allocator qualification."""

from __future__ import annotations

import hashlib
import re
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any

MOUNTINFO_SOURCE = Path("/proc/self/mountinfo")
SELF_CGROUP_SOURCE = Path("/proc/self/cgroup")
CANONICAL_THROTTLE_KEYS = ("nr_throttled", "throttled_usec")
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


def _decode_mount_field(value: str) -> str:
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _read_text(path: Path, description: str, *, allow_empty: bool = False) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"{description} unavailable: {path}") from exc
    if not value and not allow_empty:
        raise RuntimeError(f"{description} is empty: {path}")
    return value


def _expect_enoent(path: Path, description: str) -> None:
    try:
        path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"cannot prove {description} is absent: {path}") from exc
    raise RuntimeError(f"{description} unexpectedly exists: {path}")


def _optional_control(path: Path, description: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return {"source": str(path), "status": "absent-enoent", "raw": None}
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"cannot read or prove absence of {description}: {path}") from exc
    if not raw:
        raise RuntimeError(f"{description} is empty: {path}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"invalid {description}: {raw!r}") from exc
    if value < 0:
        raise RuntimeError(f"negative {description}: {raw!r}")
    return {"source": str(path), "status": "present", "raw": raw}


def _parse_mountinfo(raw: str) -> tuple[list[dict[str, Any]], int]:
    mounts: list[dict[str, Any]] = []
    record_count = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        record_count += 1
        halves = line.split(" - ", 1)
        if len(halves) != 2:
            raise RuntimeError("invalid /proc/self/mountinfo record")
        left = halves[0].split()
        right = halves[1].split()
        if len(left) < 6 or len(right) < 3:
            raise RuntimeError("invalid /proc/self/mountinfo record")
        filesystem_type = right[0]
        if filesystem_type not in {"cgroup", "cgroup2"}:
            continue
        root = _decode_mount_field(left[3])
        mount_point = _decode_mount_field(left[4])
        if not root.startswith("/") or not mount_point.startswith("/"):
            raise RuntimeError("cgroup mount paths must be absolute")
        mounts.append(
            {
                "raw": line,
                "root": root,
                "mount_point": mount_point,
                "filesystem_type": filesystem_type,
                "mount_source": _decode_mount_field(right[1]),
                "mount_options": sorted(set(left[5].split(","))),
                "super_options": sorted(set(right[2].split(","))),
            }
        )
    if record_count == 0:
        raise RuntimeError("/proc/self/mountinfo has zero valid records")
    return mounts, record_count


def _parse_memberships(raw: str) -> list[dict[str, Any]]:
    memberships: list[dict[str, Any]] = []
    seen_hierarchies: set[int] = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        fields = line.split(":", 2)
        if len(fields) != 3 or not fields[0].isdigit():
            raise RuntimeError("invalid /proc/self/cgroup record")
        hierarchy_id = int(fields[0])
        controller_fields = fields[1].split(",") if fields[1] else []
        if any(not controller for controller in controller_fields) or len(
            controller_fields
        ) != len(set(controller_fields)):
            raise RuntimeError("invalid cgroup controller membership list")
        controllers = sorted(controller_fields)
        if hierarchy_id == 0 and controllers:
            raise RuntimeError("contradictory unified cgroup membership controllers")
        if hierarchy_id != 0 and not controllers:
            raise RuntimeError("contradictory v1 cgroup membership without controllers")
        if hierarchy_id in seen_hierarchies:
            raise RuntimeError("duplicate cgroup hierarchy membership")
        seen_hierarchies.add(hierarchy_id)
        path = fields[2]
        if not path.startswith("/") or ".." in PurePosixPath(path).parts:
            raise RuntimeError("unsafe cgroup membership path")
        memberships.append(
            {
                "raw": line,
                "hierarchy_id": str(hierarchy_id),
                "controllers": controllers,
                "path": path,
            }
        )
    if not memberships:
        raise RuntimeError("/proc/self/cgroup has zero valid records")
    return memberships


def _integer_map(path: Path, description: str = "CPU cgroup stat") -> dict[str, int]:
    raw = _read_text(path, description)
    result: dict[str, int] = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            result[fields[0]] = int(fields[1])
        except ValueError:
            continue
    return result


def _quota_v2(path: Path) -> dict[str, Any]:
    raw = _read_text(path, "cgroup v2 cpu.max")
    fields = raw.split()
    if len(fields) != 2:
        raise RuntimeError(f"invalid cgroup v2 cpu.max: {raw!r}")
    try:
        period_usec = int(fields[1])
        quota_usec = None if fields[0] == "max" else int(fields[0])
    except ValueError as exc:
        raise RuntimeError(f"invalid cgroup v2 cpu.max: {raw!r}") from exc
    if period_usec <= 0 or (quota_usec is not None and quota_usec <= 0):
        raise RuntimeError(f"nonpositive cgroup v2 cpu.max: {raw!r}")
    return {
        "sources": [str(path)],
        "raw": {"cpu.max": raw},
        "quota_usec": quota_usec,
        "period_usec": period_usec,
        "quota_cores": None if quota_usec is None else quota_usec / period_usec,
    }


def _quota_v1(quota_path: Path, period_path: Path) -> dict[str, Any]:
    quota_raw = _read_text(quota_path, "cgroup v1 cpu.cfs_quota_us")
    period_raw = _read_text(period_path, "cgroup v1 cpu.cfs_period_us")
    try:
        quota_value = int(quota_raw)
        period_usec = int(period_raw)
    except ValueError as exc:
        raise RuntimeError("invalid cgroup v1 CPU quota/period") from exc
    if period_usec <= 0 or quota_value == 0 or quota_value < -1:
        raise RuntimeError(
            f"invalid cgroup v1 CPU quota/period: {quota_raw!r}/{period_raw!r}"
        )
    quota_usec = None if quota_value == -1 else quota_value
    return {
        "sources": [str(quota_path), str(period_path)],
        "raw": {
            "cpu.cfs_quota_us": quota_raw,
            "cpu.cfs_period_us": period_raw,
        },
        "quota_usec": quota_usec,
        "period_usec": period_usec,
        "quota_cores": None if quota_usec is None else quota_usec / period_usec,
    }


def _visible_levels(mount: dict[str, Any], membership: dict[str, Any]) -> list[tuple[Path, str]]:
    if mount["root"] != "/":
        raise RuntimeError("hidden cgroup ancestry: mountinfo root is not hierarchy root")
    mount_point = Path(str(mount["mount_point"]))
    membership_path = PurePosixPath(str(membership["path"]))
    leaf = mount_point.joinpath(*membership_path.relative_to("/").parts)
    if not leaf.is_dir():
        raise RuntimeError(f"resolved cgroup membership directory unavailable: {leaf}")
    levels: list[tuple[Path, str]] = []
    current = leaf
    hierarchy = membership_path
    while True:
        levels.append((current, str(hierarchy)))
        if current == mount_point:
            break
        if mount_point not in current.parents:
            raise RuntimeError("resolved cgroup membership escapes mountpoint")
        current = current.parent
        hierarchy = hierarchy.parent
    return levels


def _v2_root_visibility(mount_point: Path) -> dict[str, Any]:
    controllers_path = mount_point / "cgroup.controllers"
    subtree_path = mount_point / "cgroup.subtree_control"
    procs_path = mount_point / "cgroup.procs"
    controllers_raw = _read_text(
        controllers_path, "v2 root cgroup.controllers", allow_empty=True
    )
    subtree_raw = _read_text(
        subtree_path, "v2 root cgroup.subtree_control", allow_empty=True
    )
    _read_text(procs_path, "v2 root cgroup.procs", allow_empty=True)
    for sentinel in ("cgroup.events", "cgroup.type"):
        _expect_enoent(mount_point / sentinel, f"v2 non-root sentinel {sentinel}")
    return {
        "mount_root": "/",
        "controllers": {
            "source": str(controllers_path),
            "raw": controllers_raw,
            "values": sorted(controllers_raw.split()),
        },
        "subtree_control": {
            "source": str(subtree_path),
            "raw": subtree_raw,
            "values": sorted(subtree_raw.split()),
        },
        "cgroup_procs": {"source": str(procs_path), "readable": True},
        "absent_nonroot_sentinels": [
            str(mount_point / "cgroup.events"),
            str(mount_point / "cgroup.type"),
        ],
    }


def _v2_root_level(
    mount_point: Path,
    root_proof: dict[str, Any],
) -> dict[str, Any]:
    """Bind the actual v2 hierarchy root, whose CPU controls are root-inapplicable."""

    cpu_max_path = mount_point / "cpu.max"
    burst_path = mount_point / "cpu.max.burst"
    _expect_enoent(cpu_max_path, "v2 hierarchy-root cpu.max")
    _expect_enoent(burst_path, "v2 hierarchy-root cpu.max.burst")
    root_stat_path = mount_point / "cpu.stat"
    root_stat = _integer_map(root_stat_path, "v2 hierarchy-root cpu.stat")
    required_usage = ["usage_usec", "user_usec", "system_usec"]
    if any(key not in root_stat or root_stat[key] < 0 for key in required_usage):
        raise RuntimeError("v2 hierarchy-root cpu.stat lacks universal usage counters")
    root_proof["absent_nonroot_sentinels"].extend(
        [str(cpu_max_path), str(burst_path)]
    )
    root_proof["cpu_stat"] = {
        "source": str(root_stat_path),
        "required_usage_keys": required_usage,
    }
    return {
        "directory": str(mount_point),
        "hierarchy_path": "/",
        "is_mountpoint": True,
        "quota": None,
        "burst": {
            "source": str(burst_path),
            "status": "absent-enoent",
            "raw": None,
        },
        "stat": {
            "source": str(root_stat_path),
            "raw_throttle_keys": [],
            "canonical_throttle_keys": [],
            "canonical_throttled_time_unit": "microseconds",
            "normalization": "not-applicable-v2-hierarchy-root",
            "throttle_applicable": False,
        },
    }


def _effective_quota(levels: list[dict[str, Any]]) -> dict[str, Any]:
    finite: list[tuple[int, Fraction, dict[str, Any]]] = []
    for index, level in enumerate(levels):
        quota = level.get("quota")
        if isinstance(quota, dict) and quota.get("quota_usec") is not None:
            finite.append(
                (
                    index,
                    Fraction(int(quota["quota_usec"]), int(quota["period_usec"])),
                    level,
                )
            )
    if not finite:
        return {
            "finite": False,
            "quota_usec": None,
            "period_usec": None,
            "quota_cores": None,
            "limiting_level_indices": [],
            "limiting_level_directories": [],
        }
    minimum = min(item[1] for item in finite)
    limiting = [item for item in finite if item[1] == minimum]
    representative = limiting[0][2]["quota"]
    return {
        "finite": True,
        "quota_usec": int(representative["quota_usec"]),
        "period_usec": int(representative["period_usec"]),
        "quota_cores": float(minimum),
        "ratio_numerator": minimum.numerator,
        "ratio_denominator": minimum.denominator,
        "limiting_level_indices": [item[0] for item in limiting],
        "limiting_level_directories": [item[2]["directory"] for item in limiting],
    }


def _v2_identity(
    mount: dict[str, Any],
    membership: dict[str, Any],
    *,
    unified_membership_count: int,
    mountinfo_path: Path,
    self_cgroup_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    visible = _visible_levels(mount, membership)
    mount_point = Path(str(mount["mount_point"]))
    root_proof = _v2_root_visibility(mount_point)
    if "cpu" not in root_proof["controllers"]["values"]:
        absent_cpu_controls: list[str] = []
        for directory, _hierarchy_path in visible:
            for filename in ("cpu.max", "cpu.max.burst"):
                path = directory / filename
                _expect_enoent(path, f"v2 CPU-disabled control {filename}")
                absent_cpu_controls.append(str(path))
        return None, {
            "mode": "cgroup-v2-no-cpu-controller",
            "mount": mount,
            "membership": membership,
            "root_visibility_proof": root_proof,
            "absent_cpu_controls": absent_cpu_controls,
        }

    root_level = _v2_root_level(mount_point, root_proof)
    leaf_is_root = len(visible) == 1 and visible[0][0] == mount_point
    if leaf_is_root:
        if (
            unified_membership_count != 1
            or membership["hierarchy_id"] != "0"
            or membership["controllers"]
            or membership["path"] != "/"
        ):
            raise RuntimeError("contradictory v2 hierarchy-root membership proof")
        levels = [root_level]
        mode = "cgroup-v2-root"
    else:
        levels = []
        for directory, hierarchy_path in visible:
            if directory == mount_point:
                levels.append(root_level)
                continue
            quota_path = directory / "cpu.max"
            if not quota_path.is_file():
                raise RuntimeError(f"non-root v2 cgroup level lacks cpu.max: {directory}")
            stat_path = directory / "cpu.stat"
            quota = _quota_v2(quota_path)
            stat = _integer_map(stat_path)
            raw_keys = ["nr_throttled", "throttled_usec"]
            if any(key not in stat or stat[key] < 0 for key in raw_keys):
                raise RuntimeError(f"v2 cpu.stat lacks throttle counters: {directory}")
            levels.append(
                {
                    "directory": str(directory),
                    "hierarchy_path": hierarchy_path,
                    "is_mountpoint": directory == mount_point,
                    "quota": quota,
                    "burst": _optional_control(
                        directory / "cpu.max.burst", "cgroup v2 cpu.max.burst"
                    ),
                    "stat": {
                        "source": str(stat_path),
                        "raw_throttle_keys": raw_keys,
                        "canonical_throttle_keys": list(CANONICAL_THROTTLE_KEYS),
                        "canonical_throttled_time_unit": "microseconds",
                        "normalization": "identity-microseconds",
                        "throttle_applicable": True,
                    },
                }
            )
        mode = "cgroup-v2"

    return {
        "mode": mode,
        "unconstrained": mode == "cgroup-v2-root",
        "proof_sources": {
            "mountinfo": str(mountinfo_path),
            "self_cgroup": str(self_cgroup_path),
        },
        "mount": mount,
        "membership": membership,
        "control_directory": str(visible[0][0]),
        "root_visibility_proof": root_proof,
        "hierarchy_levels": levels,
        "effective_quota": _effective_quota(levels),
    }, None


def _v1_identity(
    mount: dict[str, Any],
    membership: dict[str, Any],
    *,
    mountinfo_path: Path,
    self_cgroup_path: Path,
) -> dict[str, Any]:
    visible = _visible_levels(mount, membership)
    mount_point = Path(str(mount["mount_point"]))
    release_agent_path = mount_point / "release_agent"
    release_agent_raw = _read_text(
        release_agent_path, "v1 hierarchy-root release_agent", allow_empty=True
    )
    levels: list[dict[str, Any]] = []
    for directory, hierarchy_path in visible:
        quota_path = directory / "cpu.cfs_quota_us"
        period_path = directory / "cpu.cfs_period_us"
        stat_path = directory / "cpu.stat"
        if not quota_path.is_file() or not period_path.is_file():
            raise RuntimeError(f"v1 cgroup level lacks CPU quota files: {directory}")
        quota = _quota_v1(quota_path, period_path)
        stat = _integer_map(stat_path)
        raw_keys = ["nr_throttled", "throttled_time"]
        if any(key not in stat or stat[key] < 0 for key in raw_keys):
            raise RuntimeError(f"v1 cpu.stat lacks throttle counters: {directory}")
        levels.append(
            {
                "directory": str(directory),
                "hierarchy_path": hierarchy_path,
                "is_mountpoint": directory == mount_point,
                "quota": quota,
                "burst": _optional_control(
                    directory / "cpu.cfs_burst_us", "cgroup v1 cpu.cfs_burst_us"
                ),
                "stat": {
                    "source": str(stat_path),
                    "raw_throttle_keys": raw_keys,
                    "canonical_throttle_keys": list(CANONICAL_THROTTLE_KEYS),
                    "canonical_throttled_time_unit": "microseconds",
                    "normalization": "throttled_time-nanoseconds-divided-by-1000",
                    "throttle_applicable": True,
                },
            }
        )
    return {
        "mode": "cgroup-v1",
        "unconstrained": False,
        "proof_sources": {
            "mountinfo": str(mountinfo_path),
            "self_cgroup": str(self_cgroup_path),
        },
        "mount": mount,
        "membership": membership,
        "control_directory": str(visible[0][0]),
        "root_visibility_proof": {
            "mount_root": "/",
            "release_agent": {
                "source": str(release_agent_path),
                "raw": release_agent_raw,
                "readable": True,
            },
        },
        "hierarchy_levels": levels,
        "effective_quota": _effective_quota(levels),
    }


def discover_cpu_control(
    mountinfo_path: Path = MOUNTINFO_SOURCE,
    self_cgroup_path: Path = SELF_CGROUP_SOURCE,
) -> dict[str, Any]:
    """Resolve all visible CPU-control levels, rejecting incomplete evidence."""

    mountinfo_raw = _read_text(mountinfo_path, "mount namespace evidence")
    self_cgroup_raw = _read_text(self_cgroup_path, "cgroup membership evidence")
    mounts, mount_record_count = _parse_mountinfo(mountinfo_raw)
    memberships = _parse_memberships(self_cgroup_raw)
    unified = [item for item in memberships if item["hierarchy_id"] == "0"]
    if len(unified) > 1:
        raise RuntimeError("contradictory multiple unified cgroup memberships")

    valid: list[dict[str, Any]] = []
    no_cpu_v2: list[dict[str, Any]] = []
    v2_mounts = [item for item in mounts if item["filesystem_type"] == "cgroup2"]
    for membership in unified:
        for mount in v2_mounts:
            identity, no_cpu = _v2_identity(
                mount,
                membership,
                unified_membership_count=len(unified),
                mountinfo_path=mountinfo_path,
                self_cgroup_path=self_cgroup_path,
            )
            if identity is not None:
                valid.append(identity)
            if no_cpu is not None:
                no_cpu_v2.append(no_cpu)

    cpu_memberships = [item for item in memberships if "cpu" in item["controllers"]]
    if len(cpu_memberships) > 1:
        raise RuntimeError("contradictory multiple v1 CPU memberships")
    v1_cpu_mounts = [
        item
        for item in mounts
        if item["filesystem_type"] == "cgroup"
        and "cpu"
        in (
            set(item["mount_options"])
            | set(item["super_options"])
            | set(str(item["mount_source"]).split(","))
        )
    ]
    for membership in cpu_memberships:
        if membership["hierarchy_id"] == "0":
            raise RuntimeError("v1 CPU membership must use a nonzero hierarchy")
        for mount in v1_cpu_mounts:
            valid.append(
                _v1_identity(
                    mount,
                    membership,
                    mountinfo_path=mountinfo_path,
                    self_cgroup_path=self_cgroup_path,
                )
            )

    mismatched_cpu_evidence = bool(
        (unified and not v2_mounts)
        or (v2_mounts and not unified)
        or (cpu_memberships and not v1_cpu_mounts)
        or (v1_cpu_mounts and not cpu_memberships)
    )
    if mismatched_cpu_evidence:
        raise RuntimeError("CPU cgroup membership/mount evidence is contradictory")

    if len(valid) == 1:
        return valid[0]
    if len(valid) > 1:
        raise RuntimeError("ambiguous CPU cgroup control paths in current mount namespace")

    return {
        "mode": "none",
        "unconstrained": True,
        "proof_sources": {
            "mountinfo": str(mountinfo_path),
            "self_cgroup": str(self_cgroup_path),
        },
        "mount": None,
        "membership": None,
        "control_directory": None,
        "root_visibility_proof": None,
        "hierarchy_levels": [],
        "effective_quota": {
            "finite": False,
            "quota_usec": None,
            "period_usec": None,
            "quota_cores": None,
            "limiting_level_indices": [],
            "limiting_level_directories": [],
        },
        "no_cpu_cgroup_proof": {
            "proof_kind": "no-visible-linux-cpu-controller",
            "mountinfo_sha256": hashlib.sha256(mountinfo_raw.encode()).hexdigest(),
            "self_cgroup_sha256": hashlib.sha256(self_cgroup_raw.encode()).hexdigest(),
            "mountinfo_record_count": mount_record_count,
            "membership_record_count": len(memberships),
            "v2_no_cpu_controller_hierarchies": no_cpu_v2,
            "v1_cpu_mount_records": [],
            "v1_cpu_membership_records": [],
        },
    }


def read_cpu_stat(cpu_control: dict[str, Any]) -> list[dict[str, Any]]:
    mode = cpu_control.get("mode")
    if mode in {"none", "cgroup-v2-root"}:
        return []
    if mode not in {"cgroup-v1", "cgroup-v2"}:
        raise RuntimeError(f"unknown CPU control mode: {mode!r}")
    snapshots: list[dict[str, Any]] = []
    for level in cpu_control.get("hierarchy_levels", []):
        stat = level.get("stat")
        if not isinstance(stat, dict):
            raise RuntimeError("CPU-control level lacks applicable stat identity")
        if stat.get("throttle_applicable") is False:
            continue
        if stat.get("throttle_applicable") is not True:
            raise RuntimeError("CPU-control level lacks applicable stat identity")
        source = stat.get("source")
        if not isinstance(source, str) or not source:
            raise RuntimeError("CPU-control stat source is missing")
        counters = _integer_map(Path(source))
        expected = stat.get("raw_throttle_keys")
        if not isinstance(expected, list) or any(
            key not in counters or counters[key] < 0 for key in expected
        ):
            raise RuntimeError("CPU cgroup stat lost mandatory throttle counters")
        snapshots.append(
            {
                "directory": level["directory"],
                "source": source,
                "counters": counters,
            }
        )
    if not snapshots:
        raise RuntimeError("CPU-controlled mode has no throttle levels")
    return snapshots


def canonical_cpu_stat_delta(
    cpu_control: dict[str, Any],
    before: list[dict[str, Any]] | None,
    after: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Normalize and retain throttle deltas for every visible hierarchy level."""

    mode = cpu_control.get("mode")
    if mode in {"none", "cgroup-v2-root"}:
        return (
            None,
            [] if before == [] and after == [] else ["unexpected CPU throttle counters"],
        )
    if not isinstance(before, list) or not isinstance(after, list):
        return None, ["CPU cgroup counters unavailable"]
    expected_levels = [
        {
            "directory": level["directory"],
            "source": level["stat"]["source"],
            "raw_keys": level["stat"]["raw_throttle_keys"],
        }
        for level in cpu_control.get("hierarchy_levels", [])
        if level.get("stat", {}).get("throttle_applicable") is True
    ]
    if len(before) != len(expected_levels) or len(after) != len(expected_levels):
        return None, ["CPU throttle level cardinality changed"]
    deltas: list[dict[str, Any]] = []
    for expected, before_level, after_level in zip(expected_levels, before, after):
        identity = {"directory": expected["directory"], "source": expected["source"]}
        if any(
            {"directory": observed.get("directory"), "source": observed.get("source")}
            != identity
            for observed in (before_level, after_level)
        ):
            return None, ["CPU throttle level source/order changed"]
        before_counters = before_level.get("counters")
        after_counters = after_level.get("counters")
        if not isinstance(before_counters, dict) or not isinstance(after_counters, dict):
            return None, ["CPU throttle counters unavailable"]
        keys = expected["raw_keys"]
        if any(key not in before_counters or key not in after_counters for key in keys):
            return None, ["required raw CPU throttle keys missing"]
        raw_delta = {key: after_counters[key] - before_counters[key] for key in keys}
        if any(value < 0 for value in raw_delta.values()):
            return None, ["negative CPU cgroup counter delta"]
        throttled_usec: int | float = (
            raw_delta["throttled_usec"]
            if mode == "cgroup-v2"
            else raw_delta["throttled_time"] / 1000.0
        )
        deltas.append(
            {
                **identity,
                "nr_throttled": raw_delta["nr_throttled"],
                "throttled_usec": throttled_usec,
            }
        )
    return {
        "levels": deltas,
        "nr_throttled": sum(int(level["nr_throttled"]) for level in deltas),
        "throttled_usec": sum(float(level["throttled_usec"]) for level in deltas),
    }, []


def quota_sufficient_for_threads(cpu_control: dict[str, Any], threads: int) -> bool:
    if threads <= 0:
        return False
    mode = cpu_control.get("mode")
    if mode in {"none", "cgroup-v2-root"}:
        return cpu_control.get("unconstrained") is True
    if mode not in {"cgroup-v1", "cgroup-v2"}:
        return False
    levels = cpu_control.get("hierarchy_levels")
    if not isinstance(levels, list) or not levels:
        return False
    for level in levels:
        quota = level.get("quota")
        if quota is None:
            if not (
                mode == "cgroup-v2"
                and level.get("hierarchy_path") == "/"
                and level.get("is_mountpoint") is True
                and level.get("stat", {}).get("throttle_applicable") is False
                and level.get("burst", {}).get("status") == "absent-enoent"
            ):
                return False
            continue
        if not isinstance(quota, dict):
            return False
        quota_usec = quota.get("quota_usec")
        period_usec = quota.get("period_usec")
        if quota_usec is not None and not (
            isinstance(quota_usec, int)
            and isinstance(period_usec, int)
            and period_usec > 0
            and quota_usec >= threads * period_usec
        ):
            return False
    return True

#!/usr/bin/env python3
"""Run and decide the retained v3.8.2 native allocator release gate.

The runner exports immutable baseline/candidate Git trees, builds both with the
same interpreter and compiler environment, and launches every observation in a
fresh process.  It retains warmups, measured AB/BA pairs, build logs, exact
source/extension identities, a machine-readable decision, and a compact report.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import platform
import random
import shlex
import shutil
import statistics
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_BENCHMARK_DIR = Path(__file__).resolve().parent
if str(_BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCHMARK_DIR))

from native_allocator_cpu_control import (  # noqa: E402
    canonical_cpu_stat_delta,
    discover_cpu_control,
    quota_sufficient_for_threads,
)

RUNNER_ID = "native-handle-allocator-release-gate-v2"
RUNNER_PATH = Path(__file__).resolve()
WORKER_PATH = RUNNER_PATH.with_name("native_allocator_release_sample.py")
SENTINEL_PATH = RUNNER_PATH.with_name("native_allocator_release_sentinels.py")
CPU_CONTROL_PATH = RUNNER_PATH.with_name("native_allocator_cpu_control.py")
EXPECTED_BACKEND = "native-c-swiss-entryindex"
BASELINE_VERSION = "3.8.1"
CANDIDATE_VERSION = "3.8.2"
BASELINE_COMMIT = "ddc54f44008352f1f08162e3129a9aad727c91f9"
BASELINE_NATIVE_SOURCE_SHA256 = "55c87f8f153bb661b8292378b46245caa270f6ae429c2883d9d1165b1faef475"
CANDIDATE_NATIVE_SOURCE_SHA256 = "fa24d6b935038e78a9887328df88369d24678c2bd64fea30e5847848e56bb5cc"
NATIVE_SOURCE_DIFF_SHA256 = "383c40f7ff020e872a5f40c71abbe15248e9cfe34be251bb0b722bed1be6bb36"
ACCEPTANCE_ROLES = {
    "release-primary-causal",
    "release-primary-shipped",
    "allocator-wrapper-causal-control",
    "allocator-wrapper-shipped-control",
}
MAX_STEAL_CAPACITY_FRACTION = 0.005
MAX_CPU_PSI_SOME_FRACTION = 0.05
MAX_CPU_PSI_FULL_FRACTION = 0.01
THERMAL_CEILING_C = 90.0
THERMAL_MAX_RISE_C = 10.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_json_bytes(value))


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=text,
    )


def _git(repo: Path, *arguments: str) -> str:
    return _run(["git", *arguments], cwd=repo).stdout.strip()


def _resolve_source(repo: Path, reference: str, label: str) -> dict[str, str]:
    commit = _git(repo, "rev-parse", f"{reference}^{{commit}}")
    tree = _git(repo, "rev-parse", f"{commit}^{{tree}}")
    return {"label": label, "reference": reference, "commit": commit, "tree": tree}


def _safe_extract(archive: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"unsafe archive member {member.name!r}")
        bundle.extractall(destination, filter="data")


def _export_source(repo: Path, source: dict[str, str], destination: Path) -> None:
    archive = _run(
        ["git", "archive", "--format=tar", source["commit"]],
        cwd=repo,
        text=False,
    ).stdout
    _safe_extract(archive, destination)


def _git_blob(repo: Path, commit: str, relative_path: str) -> bytes:
    return _run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repo,
        text=False,
    ).stdout


def _verify_harness_binding(
    repo: Path,
    baseline: dict[str, str],
    candidate: dict[str, str],
) -> dict[str, Any]:
    if baseline["commit"] != BASELINE_COMMIT:
        raise RuntimeError(f"baseline must resolve exactly to {BASELINE_COMMIT}")
    head = _git(repo, "rev-parse", "HEAD^{commit}")
    if candidate["commit"] != head:
        raise RuntimeError("candidate ref must resolve exactly to repository HEAD")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", baseline["commit"], candidate["commit"]],
        cwd=repo,
        check=False,
    ).returncode != 0:
        raise RuntimeError("candidate is not a descendant of the declared baseline")
    tracked_status = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if tracked_status:
        raise RuntimeError(f"tracked worktree must be clean before qualification: {tracked_status}")
    bindings = {}
    for path in (RUNNER_PATH, WORKER_PATH, SENTINEL_PATH, CPU_CONTROL_PATH):
        relative = path.relative_to(repo).as_posix()
        live = path.read_bytes()
        committed = _git_blob(repo, candidate["commit"], relative)
        if live != committed:
            raise RuntimeError(f"live harness does not match candidate Git blob: {relative}")
        bindings[relative] = {
            "sha256": hashlib.sha256(live).hexdigest(),
            "git_blob": _git(repo, "rev-parse", f"{candidate['commit']}:{relative}"),
        }
    native_diff = _run(
        [
            "git",
            "diff",
            "--no-ext-diff",
            baseline["commit"],
            candidate["commit"],
            "--",
            "src/staqtapp_tds/_native_index.c",
        ],
        cwd=repo,
    ).stdout
    deleted_scan = "-    if (handle_in_use_locked(self, handle, -1)) return -4;"
    if native_diff.count(deleted_scan) != 1:
        raise RuntimeError("candidate C diff does not remove exactly one automatic scan")
    native_diff_sha = hashlib.sha256(native_diff.encode()).hexdigest()
    if native_diff_sha != NATIVE_SOURCE_DIFF_SHA256:
        raise RuntimeError(
            "native C diff contains changes outside the exact reviewed comment-and-scan removal"
        )
    baseline_source = _git_blob(repo, baseline["commit"], "src/staqtapp_tds/_native_index.c")
    candidate_source = _git_blob(repo, candidate["commit"], "src/staqtapp_tds/_native_index.c")
    baseline_source_sha = hashlib.sha256(baseline_source).hexdigest()
    candidate_source_sha = hashlib.sha256(candidate_source).hexdigest()
    if baseline_source_sha != BASELINE_NATIVE_SOURCE_SHA256:
        raise RuntimeError("pinned baseline native source hash mismatch")
    if candidate_source_sha != CANDIDATE_NATIVE_SOURCE_SHA256:
        raise RuntimeError("pinned candidate native source hash mismatch")
    return {
        "tracked_worktree_clean": True,
        "candidate_descends_from_baseline": True,
        "harness_blobs": bindings,
        "native_index_diff_sha256": native_diff_sha,
        "expected_native_index_diff_sha256": NATIVE_SOURCE_DIFF_SHA256,
        "native_index_executable_delta": "one automatic handle_in_use_locked call removed",
        "native_index_diff": native_diff,
        "baseline_native_source_sha256": baseline_source_sha,
        "candidate_native_source_sha256": candidate_source_sha,
    }


def _derive_allocator_only_source(
    baseline_root: Path,
    candidate_root: Path,
    destination: Path,
    baseline: dict[str, str],
) -> dict[str, str]:
    shutil.copytree(baseline_root, destination)
    relative = Path("src/staqtapp_tds/_native_index.c")
    candidate_c = (candidate_root / relative).read_bytes()
    (destination / relative).write_bytes(candidate_c)
    source_sha = hashlib.sha256(candidate_c).hexdigest()
    derived_tree = hashlib.sha256(
        f"{baseline['tree']}\n{relative.as_posix()}\n{source_sha}\n".encode()
    ).hexdigest()
    return {
        "label": "allocator-only",
        "reference": "derived:v3.8.1-plus-exact-candidate-native-index-c",
        "commit": baseline["commit"],
        "tree": f"derived-sha256:{derived_tree}",
    }


def _command_identity(command: str | None) -> dict[str, Any]:
    if not command:
        return {"configured": None, "executable": None, "version": None}
    executable_name = command.split()[0]
    executable = shutil.which(executable_name)
    version = None
    if executable:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        version = (completed.stdout or completed.stderr).strip()
    return {
        "configured": command,
        "executable": executable,
        "version": version,
    }


def _select_build_compiler(environment: dict[str, str]) -> str:
    configured = environment.get("CC") or str(sysconfig.get_config_var("CC") or "")
    configured_argv = shlex.split(configured)
    if configured_argv:
        resolved = shutil.which(configured_argv[0])
        if resolved:
            return resolved
    for candidate in ("cc", "gcc", "clang"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError(
        f"no usable C compiler; environment/sysconfig configured {configured!r}"
    )


def _extension_path(source_root: Path) -> Path:
    candidates = sorted((source_root / "src" / "staqtapp_tds").glob("_native_index.*"))
    binary = [
        path
        for path in candidates
        if path.suffix.lower() in {".so", ".pyd", ".dylib"}
        or ".so." in path.name
    ]
    if len(binary) != 1:
        raise RuntimeError(f"expected one built native extension, found {binary!r}")
    return binary[0]


def _build_source(
    source_root: Path,
    source: dict[str, str],
    output_dir: Path,
    build_env: dict[str, str],
) -> dict[str, Any]:
    command = [sys.executable, "setup.py", "build_ext", "--inplace", "--force"]
    started_ns = time.time_ns()
    completed = _run(command, cwd=source_root, env=build_env)
    finished_ns = time.time_ns()
    log_path = output_dir / f"{source['label']}-native-build.log"
    log_text = completed.stdout + completed.stderr
    log_path.write_text(log_text, encoding="utf-8")
    native_compile_commands = [
        line.strip()
        for line in log_text.splitlines()
        if "src/staqtapp_tds/_native_index.c" in line and " -c " in f" {line} "
    ]
    native_link_commands = [
        line.strip()
        for line in log_text.splitlines()
        if "_native_index" in line and " -shared " in f" {line} "
    ]
    if len(native_compile_commands) != 1 or len(native_link_commands) != 1:
        raise RuntimeError(
            "build log did not retain exactly one native compile and link command"
        )
    compiler_argv = shlex.split(native_compile_commands[0])
    extension = _extension_path(source_root)
    native_source = source_root / "src" / "staqtapp_tds" / "_native_index.c"
    wrapper_source = source_root / "src" / "staqtapp_tds" / "backends" / "native_index.py"
    provenance = {
        "schema": 2,
        "source": source,
        "command": command,
        "environment": {
            name: build_env.get(name)
            for name in (
                "CC",
                "CFLAGS",
                "CPPFLAGS",
                "LDFLAGS",
                "STAQTAPP_TDS_BUILD_NATIVE",
                "STAQTAPP_TDS_SANITIZE",
            )
        },
        "compiler": _command_identity(
            build_env.get("CC") or str(sysconfig.get_config_var("CC") or "")
        ),
        "actual_native_compile_command": native_compile_commands[0],
        "actual_native_compile_argv": compiler_argv,
        "actual_native_link_command": native_link_commands[0],
        "compiler_and_flags_recorded": True,
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "sysconfig_cc": sysconfig.get_config_var("CC"),
            "sysconfig_cflags": sysconfig.get_config_var("CFLAGS"),
        },
        "started_ns": started_ns,
        "finished_ns": finished_ns,
        "build_log": log_path.name,
        "build_log_sha256": _sha256(log_path),
        "native_source_sha256": _sha256(native_source),
        "wrapper_source_sha256": _sha256(wrapper_source),
        "extension_name": extension.name,
        "extension_sha256": _sha256(extension),
    }
    path = output_dir / f"{source['label']}-build-provenance.json"
    _write_json(path, provenance)
    provenance["path"] = str(path.resolve())
    provenance["source_root"] = str(source_root.resolve())
    return provenance


def _available_cpus() -> list[int]:
    try:
        return sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError) as exc:
        raise RuntimeError("release qualification requires sched_getaffinity") from exc


def _cpu_control() -> dict[str, Any]:
    return discover_cpu_control()


def _effective_cpu_topology() -> dict[str, Any]:
    """Resolve one logical CPU per allowed physical core, with no fallback."""

    allowed = _available_cpus()
    if not allowed:
        raise RuntimeError("scheduler admitted no CPUs")
    logical: dict[str, dict[str, int]] = {}
    groups: dict[tuple[int, int], list[int]] = {}
    for cpu_id in allowed:
        topology_dir = Path(f"/sys/devices/system/cpu/cpu{cpu_id}/topology")
        try:
            package_id = int((topology_dir / "physical_package_id").read_text().strip())
            core_id = int((topology_dir / "core_id").read_text().strip())
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"physical topology unavailable for allowed CPU {cpu_id}; logical fallback forbidden"
            ) from exc
        logical[str(cpu_id)] = {"package_id": package_id, "core_id": core_id}
        groups.setdefault((package_id, core_id), []).append(cpu_id)
    # Pick the highest admitted sibling for every physical core, then prefer the
    # tail for the declared quiet-core set. No two selected IDs share a core.
    representatives = sorted(max(siblings) for siblings in groups.values())
    cpu_control = _cpu_control()
    effective_quota = cpu_control["effective_quota"]
    quota_floor = (
        len(representatives)
        if effective_quota["finite"] is False
        else int(effective_quota["ratio_numerator"])
        // int(effective_quota["ratio_denominator"])
    )
    effective_count = min(len(representatives), quota_floor)
    if effective_count < 2:
        raise RuntimeError(
            "release qualification requires at least two allowed physical cores "
            "and CPU-control quota for at least two threads"
        )
    multi_threads = min(8, effective_count)
    selected_multi = representatives[-multi_threads:]
    if not quota_sufficient_for_threads(cpu_control, multi_threads):
        raise RuntimeError("CPU-control quota is below the declared thread count")
    topology_payload = {
        "allowed_cpu_ids": allowed,
        "logical_cpu_topology": logical,
        "physical_core_groups": {
            f"package-{package_id}/core-{core_id}": sorted(siblings)
            for (package_id, core_id), siblings in sorted(groups.items())
        },
        "representative_cpu_ids": representatives,
    }
    return {
        **topology_payload,
        "topology_sha256": hashlib.sha256(
            json.dumps(topology_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "allowed_physical_core_count": len(representatives),
        "effective_physical_core_count": effective_count,
        "multi_threads": multi_threads,
        "single_cpu_ids": [selected_multi[-1]],
        "multi_cpu_ids": selected_multi,
        "cpu_control": cpu_control,
    }


def _affinity_for(threads: int, topology: dict[str, Any]) -> str:
    selected = (
        topology["single_cpu_ids"]
        if threads == 1
        else topology["multi_cpu_ids"]
    )
    if len(selected) != threads:
        raise RuntimeError(f"no exact one-physical-core-per-thread affinity for t{threads}")
    return ",".join(str(cpu) for cpu in selected)


def _cells(multi_threads: int) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for comparison_id, target_label, role in (
        ("baseline-vs-allocator-only", "allocator-only", "release-primary-causal"),
        ("baseline-vs-candidate", "candidate", "release-primary-shipped"),
    ):
        comparison_suffix = "causal" if target_label == "allocator-only" else "shipped"
        for threads in (1, multi_threads):
            for entries in (10_000, 50_000, 100_000):
                cells.append({
                    "id": f"full-tds-{comparison_suffix}-normal-{entries}-t{threads}",
                    "comparison_id": comparison_id,
                    "path": "full-tds",
                    "diagnostics": "off",
                    "telemetry": "normal",
                    "entries": entries,
                    "threads": threads,
                    "role": role,
                    "comparison": ["baseline", target_label],
                })
        cells.append({
            "id": f"full-tds-{comparison_suffix}-telemetry-off-100000-t1",
            "comparison_id": comparison_id,
            "path": "full-tds",
            "diagnostics": "off",
            "telemetry": "off",
            "entries": 100_000,
            "threads": 1,
            "role": f"telemetry-off-characterization-{comparison_suffix}",
            "comparison": ["baseline", target_label],
        })
    for comparison_id, target_label, role in (
        ("baseline-vs-allocator-only", "allocator-only", "allocator-wrapper-causal-control"),
        ("baseline-vs-candidate", "candidate", "allocator-wrapper-shipped-control"),
    ):
        comparison_suffix = "causal" if target_label == "allocator-only" else "shipped"
        cells.append({
            "id": f"wrapper-{comparison_suffix}-normal-100000-t1",
            "comparison_id": comparison_id,
            "path": "wrapper",
            "diagnostics": "off",
            "telemetry": "normal",
            "entries": 100_000,
            "threads": 1,
            "role": role,
            "comparison": ["baseline", target_label],
        })
    cells.append({
        "id": "raw-causal-100000-t1",
        "comparison_id": "baseline-vs-allocator-only",
        "path": "raw",
        "diagnostics": "off",
        "telemetry": "off",
        "entries": 100_000,
        "threads": 1,
        "role": "causal-localization-only",
        "comparison": ["baseline", "allocator-only"],
    })
    return cells


def _balanced_orders(count: int, rng: random.Random) -> list[str]:
    orders = ["AB"] * ((count + 1) // 2) + ["BA"] * (count // 2)
    rng.shuffle(orders)
    return orders


def _worker_command(
    *,
    run_id: str,
    source: dict[str, str],
    cell: dict[str, Any],
    phase: str,
    pair_index: int,
    order: str,
    order_position: int,
    lookup_seed: int,
    build: dict[str, Any],
    worker_path: Path,
    topology: dict[str, Any],
) -> list[str]:
    command = [
        sys.executable,
        str(worker_path),
        "--run-id",
        run_id,
        "--source-label",
        source["label"],
        "--source-commit",
        source["commit"],
        "--source-tree",
        source["tree"],
        "--cell-id",
        cell["id"],
        "--comparison-id",
        cell["comparison_id"],
        "--entries",
        str(cell["entries"]),
        "--threads",
        str(cell["threads"]),
        "--path",
        cell["path"],
        "--diagnostics",
        cell["diagnostics"],
        "--telemetry",
        cell["telemetry"],
        "--qualification-role",
        cell["role"],
        "--expected-version",
        BASELINE_VERSION if source["label"] in {"baseline", "allocator-only"} else CANDIDATE_VERSION,
        "--lookup-seed",
        str(lookup_seed),
        "--phase",
        phase,
        "--pair-index",
        str(pair_index),
        "--order",
        order,
        "--order-position",
        str(order_position),
        "--build-provenance",
        build["path"],
        "--expected-backend",
        EXPECTED_BACKEND,
        "--expected-admitted-affinity",
        ",".join(str(cpu) for cpu in topology["allowed_cpu_ids"]),
        "--expected-topology-sha256",
        topology["topology_sha256"],
        "--expected-cpu-control-json",
        json.dumps(topology["cpu_control"], sort_keys=True, separators=(",", ":")),
    ]
    affinity = _affinity_for(int(cell["threads"]), topology)
    command.extend(["--cpu-affinity", affinity])
    return command


def _run_sample(
    *,
    run_id: str,
    source: dict[str, str],
    cell: dict[str, Any],
    phase: str,
    pair_index: int,
    order: str,
    order_position: int,
    lookup_seed: int,
    build: dict[str, Any],
    worker_env: dict[str, str],
    worker_path: Path,
    topology: dict[str, Any],
) -> dict[str, Any]:
    command = _worker_command(
        run_id=run_id,
        source=source,
        cell=cell,
        phase=phase,
        pair_index=pair_index,
        order=order,
        order_position=order_position,
        lookup_seed=lookup_seed,
        build=build,
        worker_path=worker_path,
        topology=topology,
    )
    env = dict(worker_env)
    env["PYTHONPATH"] = str(Path(build["source_root"]) / "src")
    completed = _run(command, cwd=Path(build["source_root"]), env=env)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError(f"sample emitted {len(lines)} JSON lines: {completed.stdout!r}")
    record = json.loads(lines[0])
    record["orchestrator_command"] = command
    if completed.stderr:
        record["worker_stderr"] = completed.stderr
    return record


def _run_sentinel(
    source: dict[str, str],
    build: dict[str, Any],
    *,
    sentinel_path: Path,
    worker_env: dict[str, str],
    output_dir: Path,
) -> dict[str, Any]:
    expected_version = (
        BASELINE_VERSION
        if source["label"] in {"baseline", "allocator-only"}
        else CANDIDATE_VERSION
    )
    command = [
        sys.executable,
        str(sentinel_path),
        "--source-label",
        source["label"],
        "--source-commit",
        source["commit"],
        "--source-tree",
        source["tree"],
        "--expected-version",
        expected_version,
        "--expected-auto-scan",
        "present" if source["label"] == "baseline" else "absent",
    ]
    env = dict(worker_env)
    env["PYTHONPATH"] = str(Path(build["source_root"]) / "src")
    completed = _run(command, cwd=Path(build["source_root"]), env=env)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError(f"sentinel emitted {len(lines)} lines")
    result = json.loads(lines[0])
    result["orchestrator_command"] = command
    expected_identity = {
        "label": source["label"],
        "commit": source["commit"],
        "tree": source["tree"],
        "version": expected_version,
        "native_source_sha256": build["native_source_sha256"],
        "wrapper_source_sha256": build["wrapper_source_sha256"],
        "extension_sha256": build["extension_sha256"],
        "extension_path": str(
            Path(build["source_root"]) / "src" / "staqtapp_tds" / build["extension_name"]
        ),
    }
    if (
        int(result.get("schema", 0)) != 2
        or result.get("sentinel_id") != "native-allocator-release-sentinels-v2"
        or result.get("source_identity") != expected_identity
        or result.get("harness") != {
            "path": str(sentinel_path.resolve()),
            "sha256": _sha256(sentinel_path),
        }
    ):
        raise RuntimeError("sentinel source/build/harness identity is not exact")
    path = output_dir / f"{source['label']}-sentinels.json"
    _write_json(path, result)
    return result


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _bootstrap_median_ci(
    values: list[float],
    *,
    seed: int,
    draws: int = 50_000,
) -> list[float]:
    rng = random.Random(seed)
    count = len(values)
    estimates = [
        statistics.median(values[rng.randrange(count)] for _ in range(count))
        for _ in range(draws)
    ]
    return [_percentile(estimates, 0.025), _percentile(estimates, 0.975)]


def _coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return math.inf
    mean = statistics.mean(values)
    return statistics.stdev(values) / mean if mean else math.inf


def _variation_evidence(values: list[float]) -> dict[str, Any]:
    median = statistics.median(values)
    maximum_relative_deviation = (
        max(abs(value - median) / median for value in values)
        if median > 0
        else math.inf
    )
    coefficient = _coefficient_of_variation(values)
    return {
        "values": values,
        "median": median,
        "coefficient_of_variation": coefficient,
        "maximum_relative_deviation_from_median": maximum_relative_deviation,
        "limit": 0.05,
        "stable": coefficient <= 0.05 and maximum_relative_deviation <= 0.05,
    }


def _measurement(record: dict[str, Any], phase: str, field: str) -> float:
    return float(record["measurements"][phase][field])


def _operation_percentile(record: dict[str, Any], phase: str, percentile: float) -> float:
    samples = record["dedicated_latency"]["operation_samples"][f"{phase}_ns"]
    return _percentile([float(value) for value in samples], percentile)


def _validate_v2_records(records: list[dict[str, Any]]) -> None:
    for record in records:
        if int(record.get("schema", 0)) != 2:
            raise RuntimeError("release qualification rejects non-v2 sample evidence")
        if record.get("benchmark_id") != "native-handle-allocator-release-sample-v2":
            raise RuntimeError("release qualification rejects an unexpected benchmark identity")


def _validate_retained_records(
    records: list[dict[str, Any]],
    *,
    protocol: dict[str, Any],
    builds: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Reject incomplete, mixed, replayed, or misbound evidence before math."""

    _validate_v2_records(records)
    cells = protocol["cells"]
    measured_pairs = int(protocol["measured_pairs"])
    warmup_pairs = int(protocol["warmup_pairs_excluded"])
    if measured_pairs != 7 or warmup_pairs != 2:
        raise RuntimeError("v2 publication evidence requires exactly 7 measured and 2 warmup pairs")
    expected_total = len(cells) * (measured_pairs + warmup_pairs) * 2
    if len(records) != expected_total:
        raise RuntimeError(f"retained record cardinality {len(records)}; expected {expected_total}")
    if expected_total != int(protocol["expected_worker_processes"]):
        raise RuntimeError("protocol worker cardinality is internally inconsistent")

    topology = protocol["effective_cpu_topology"]
    expected_worker_path = Path(protocol["worker_path"]).resolve()
    expected_worker_sha = protocol["worker_sha256"]
    seen: set[tuple[Any, ...]] = set()
    validated_cells: dict[str, dict[str, Any]] = {}
    expected_role = {
        "full-tds": "release-primary-full-tds-32-byte-raw-binary",
        "wrapper": "allocator-wrapper-control-32-byte-values",
        "raw": "raw-allocator-causal-localization-only",
    }
    for cell_index, cell in enumerate(cells):
        current = [
            record for record in records
            if record.get("cell", {}).get("id") == cell["id"]
            and record.get("cell", {}).get("comparison_id") == cell["comparison_id"]
        ]
        expected_cell_total = (measured_pairs + warmup_pairs) * 2
        if len(current) != expected_cell_total:
            raise RuntimeError(
                f"cell {cell['id']} cardinality {len(current)}; expected {expected_cell_total}"
            )
        source_labels = tuple(cell["comparison"])
        for phase, pair_count in (("warmup", warmup_pairs), ("measured", measured_pairs)):
            orders: list[str] = []
            for pair_index in range(pair_count):
                pair = [
                    record for record in current
                    if record["sample"]["phase"] == phase
                    and int(record["sample"]["pair_index"]) == pair_index
                ]
                if len(pair) != 2:
                    raise RuntimeError(
                        f"cell {cell['id']} {phase} pair {pair_index} is incomplete or duplicated"
                    )
                pair.sort(key=lambda record: int(record["sample"]["order_position"]))
                order = pair[0]["sample"]["order"]
                if order not in {"AB", "BA"} or any(
                    record["sample"]["order"] != order for record in pair
                ):
                    raise RuntimeError("paired order label is missing or inconsistent")
                expected_labels = source_labels if order == "AB" else source_labels[::-1]
                if [record["sample"]["source_label"] for record in pair] != list(expected_labels):
                    raise RuntimeError("paired source order does not match AB/BA label")
                if [int(record["sample"]["order_position"]) for record in pair] != [1, 2]:
                    raise RuntimeError("paired order positions are not exactly 1 and 2")
                orders.append(order)
                lookup_seed = int(protocol["seed"]) ^ ((cell_index + 1) << 20) ^ pair_index
                for record in pair:
                    source_label = record["sample"]["source_label"]
                    source = protocol["sources"][source_label]
                    build = builds[source_label]
                    identity = (
                        cell["id"], phase, pair_index, source_label,
                        int(record["sample"]["order_position"]),
                    )
                    if identity in seen:
                        raise RuntimeError(f"duplicate retained record identity: {identity!r}")
                    seen.add(identity)
                    if record.get("run_id") != protocol["run_id"]:
                        raise RuntimeError("foreign run_id in retained evidence")
                    observed_cell = record["cell"]
                    expected_cell = {
                        "id": cell["id"],
                        "comparison_id": cell["comparison_id"],
                        "path": cell["path"],
                        "measurement_role": expected_role[cell["path"]],
                        "entries": int(cell["entries"]),
                        "threads": int(cell["threads"]),
                        "diagnostics": cell["diagnostics"],
                        "telemetry": cell["telemetry"],
                        "qualification_role": cell["role"],
                        "value_bytes": 32 if cell["path"] != "raw" else None,
                        "dataset": (
                            "sequential-string-keys-exact-32-byte-raw-binary-v2"
                            if cell["path"] != "raw"
                            else "sequential-preencoded-keys-allocator-only-v1"
                        ),
                        "lookup": "one-million-or-more-hot-lookups-over-deterministically-shuffled-existing-keys",
                        "lookup_unique_keys": int(cell["entries"]),
                        "lookup_operations": max(1_000_000, int(cell["entries"])),
                        "lookup_seed": lookup_seed,
                    }
                    if observed_cell != expected_cell:
                        raise RuntimeError(
                            f"cell parameters differ from protocol for {cell['id']}: {observed_cell!r}"
                        )
                    expected_version = (
                        BASELINE_VERSION
                        if source_label in {"baseline", "allocator-only"}
                        else CANDIDATE_VERSION
                    )
                    source_identity = record["source_identity"]
                    expected_source_identity = {
                        "label": source_label,
                        "git_commit": source["commit"],
                        "git_tree": source["tree"],
                        "tds_version": expected_version,
                        "package_path": str(
                            Path(build["source_root"]) / "src" / "staqtapp_tds" / "__init__.py"
                        ),
                        "native_source_sha256": build["native_source_sha256"],
                        "wrapper_source_sha256": build["wrapper_source_sha256"],
                        "extension_path": str(
                            Path(build["source_root"])
                            / "src" / "staqtapp_tds" / build["extension_name"]
                        ),
                        "extension_sha256": build["extension_sha256"],
                        "selected_backend": EXPECTED_BACKEND,
                        "expected_backend": EXPECTED_BACKEND,
                    }
                    if source_identity != expected_source_identity:
                        raise RuntimeError("sample source/extension identity differs from exact build")
                    expected_build = {
                        key: value for key, value in build.items()
                        if key not in {"path", "source_root"}
                    }
                    if record.get("build_provenance") != expected_build:
                        raise RuntimeError("sample retained build provenance differs from build artifact")
                    harness = record.get("harness_identity")
                    if harness != {
                        "script_path": str(expected_worker_path),
                        "script_sha256": expected_worker_sha,
                    }:
                        raise RuntimeError("sample worker is not the exact exported candidate blob")
                    runtime = record["runtime_identity"]
                    expected_affinity = [
                        int(value)
                        for value in _affinity_for(int(cell["threads"]), topology).split(",")
                    ]
                    if (
                        runtime.get("admitted_cpu_affinity_before_pin") != topology["allowed_cpu_ids"]
                        or runtime.get("admitted_topology", {}).get("topology_sha256")
                        != topology["topology_sha256"]
                        or runtime.get("cpu_affinity") != expected_affinity
                        or runtime.get("cpu_control") != topology["cpu_control"]
                    ):
                        raise RuntimeError("worker CPU topology/affinity/control differs from protocol")
                    for measurement_set in (
                        record["measurements"],
                        record["dedicated_latency"]["measurements"],
                    ):
                        for phase_name in ("insertion", "lookup_control"):
                            actual_cpu_ids = measurement_set[phase_name].get("actual_cpu_ids")
                            if not actual_cpu_ids or not set(actual_cpu_ids).issubset(expected_affinity):
                                raise RuntimeError("phase actual CPU IDs escape or omit exact affinity evidence")
                    expected_command = _worker_command(
                        run_id=protocol["run_id"],
                        source=source,
                        cell=cell,
                        phase=phase,
                        pair_index=pair_index,
                        order=order,
                        order_position=int(record["sample"]["order_position"]),
                        lookup_seed=lookup_seed,
                        build=build,
                        worker_path=expected_worker_path,
                        topology=topology,
                    )
                    if record.get("orchestrator_command") != expected_command:
                        raise RuntimeError("retained worker command differs from immutable schedule")
            counts = {name: orders.count(name) for name in ("AB", "BA")}
            balanced = (
                counts == {"AB": 1, "BA": 1}
                if phase == "warmup"
                else sorted(counts.values()) == [3, 4]
            )
            if not balanced:
                raise RuntimeError(
                    f"cell {cell['id']} {phase} order balance {counts!r}; expected exact 1/1 or 4/3"
                )
        validated_cells[cell["id"]] = {
            "records": len(current),
            "warmup_order_counts": {
                name: sum(
                    record["sample"]["phase"] == "warmup"
                    and record["sample"]["order_position"] == 1
                    and record["sample"]["order"] == name
                    for record in current
                )
                for name in ("AB", "BA")
            },
            "measured_order_counts": {
                name: sum(
                    record["sample"]["phase"] == "measured"
                    and record["sample"]["order_position"] == 1
                    and record["sample"]["order"] == name
                    for record in current
                )
                for name in ("AB", "BA")
            },
        }
    if len(seen) != expected_total:
        raise RuntimeError("retained evidence contains records outside the exact protocol matrix")
    return {
        "validated": True,
        "records": len(records),
        "expected_records": expected_total,
        "cells": validated_cells,
    }


def _decide_status(failed_checks: list[dict[str, Any]]) -> str:
    if not failed_checks:
        return "PASS"
    return (
        "HOST_REVIEW_PENDING"
        if all(failure.get("kind") == "validity" for failure in failed_checks)
        else "FAIL"
    )


def _interference(record: dict[str, Any]) -> dict[str, Any]:
    throttle_events = 0
    throttled_usec = 0.0
    steal_ticks = 0
    steal_capacity_seconds = 0.0
    pressure_some_usec = 0
    pressure_full_usec = 0
    pressure_wall_usec = 0.0
    pressure_phase_count = 0
    evidence_complete = True
    evidence_errors: list[str] = []
    expected_affinity = record["runtime_identity"].get("cpu_affinity")
    expected_cpu_control = record["runtime_identity"].get("cpu_control") or {}
    cpu_control_mode = expected_cpu_control.get("mode")
    throttle_applicable = cpu_control_mode in {"cgroup-v1", "cgroup-v2"}
    expected_throttle_levels = [
        {
            "directory": level["directory"],
            "source": level["stat"]["source"],
        }
        for level in expected_cpu_control.get("hierarchy_levels", [])
        if level.get("stat", {}).get("throttle_applicable") is True
    ]
    threads = int(record["cell"]["threads"])
    phases = (
        record["measurements"]["insertion"],
        record["measurements"]["lookup_control"],
        record["dedicated_latency"]["measurements"]["insertion"],
        record["dedicated_latency"]["measurements"]["lookup_control"],
    )
    for phase in phases:
        evidence = phase["cpu_interference"]
        reported_cgroup = evidence.get("cgroup_cpu_stat_delta")
        raw_cgroup_before = evidence.get("cgroup_cpu_stat_raw_before")
        raw_cgroup_after = evidence.get("cgroup_cpu_stat_raw_after")
        try:
            recomputed_cgroup, recompute_errors = canonical_cpu_stat_delta(
                expected_cpu_control,
                raw_cgroup_before,
                raw_cgroup_after,
            )
        except Exception as exc:
            recomputed_cgroup = None
            recompute_errors = [
                f"retained raw CPU throttle snapshots are malformed: "
                f"{type(exc).__name__}: {exc}"
            ]
        if recompute_errors:
            evidence_complete = False
            evidence_errors.extend(str(value) for value in recompute_errors)
        if recomputed_cgroup != reported_cgroup:
            evidence_complete = False
            evidence_errors.append(
                "reported CPU throttle delta differs from retained raw snapshots"
            )
        cgroup = (
            recomputed_cgroup
            if not recompute_errors and recomputed_cgroup == reported_cgroup
            else None
        )
        per_cpu = evidence.get("per_cpu_tick_delta")
        pressure = evidence.get("pressure_total_usec_delta")
        ticks_per_second = evidence.get("clock_ticks_per_second")
        phase_wall_seconds = float(phase["wall_ns"]) / 1_000_000_000.0
        phase_errors = evidence.get("evidence_errors")
        if not isinstance(phase_errors, list):
            evidence_complete = False
            evidence_errors.append("phase evidence_errors is missing or malformed")
        elif phase_errors:
            evidence_complete = False
            evidence_errors.extend(str(value) for value in phase_errors)
        expected_cgroup_keys = (
            ["nr_throttled", "throttled_usec"] if throttle_applicable else []
        )
        if (not throttle_applicable and cgroup is not None) or (
            throttle_applicable and not isinstance(cgroup, dict)
        ) or not per_cpu:
            evidence_complete = False
        if (
            evidence.get("affinity_before") != expected_affinity
            or evidence.get("affinity_after") != expected_affinity
            or set((per_cpu or {}).keys()) != {str(cpu) for cpu in (expected_affinity or [])}
        ):
            evidence_complete = False
            evidence_errors.append("phase CPU evidence differs from exact selected affinity")
        if (
            evidence.get("affinity_source") != "os.sched_getaffinity(0)"
            or evidence.get("per_cpu_ticks_source") != "/proc/stat"
            or evidence.get("cpu_control_before") != expected_cpu_control
            or evidence.get("cpu_control_after") != expected_cpu_control
            or evidence.get("cpu_control") != expected_cpu_control
            or evidence.get("required_cgroup_throttle_keys") != expected_cgroup_keys
        ):
            evidence_complete = False
            evidence_errors.append("host counter source/key/CPU-control identity changed")
        if not ticks_per_second or float(ticks_per_second) <= 0:
            evidence_complete = False
        if isinstance(cgroup, dict):
            level_deltas = cgroup.get("levels")
            observed_level_identities = (
                [
                    {
                        "directory": level.get("directory"),
                        "source": level.get("source"),
                    }
                    for level in level_deltas
                ]
                if isinstance(level_deltas, list)
                and all(isinstance(level, dict) for level in level_deltas)
                else None
            )
            if observed_level_identities != expected_throttle_levels:
                evidence_complete = False
                evidence_errors.append("CPU throttle level source/order changed")
            calculated_events = 0
            calculated_usec = 0.0
            valid_level_deltas = level_deltas if isinstance(level_deltas, list) else []
            for level in valid_level_deltas:
                if not isinstance(level, dict):
                    evidence_complete = False
                    evidence_errors.append("invalid per-level throttle delta")
                    continue
                if (
                    "nr_throttled" not in level
                    or "throttled_usec" not in level
                    or int(level["nr_throttled"]) < 0
                    or float(level["throttled_usec"]) < 0
                ):
                    evidence_complete = False
                    evidence_errors.append("missing or negative per-level throttle delta")
                    continue
                calculated_events += int(level["nr_throttled"])
                calculated_usec += float(level["throttled_usec"])
            if (
                cgroup.get("nr_throttled") != calculated_events
                or float(cgroup.get("throttled_usec", -1)) != calculated_usec
            ):
                evidence_complete = False
                evidence_errors.append("aggregate throttle delta differs from hierarchy levels")
            throttle_events += calculated_events
            throttled_usec += calculated_usec
        if pressure:
            pressure_phase_count += 1
            if "some" not in pressure or "full" not in pressure:
                evidence_complete = False
            pressure_some_usec += int(pressure.get("some", 0))
            pressure_full_usec += int(pressure.get("full", 0))
            if any(value < 0 for value in pressure.values()):
                evidence_complete = False
                evidence_errors.append("negative CPU pressure delta")
        else:
            evidence_complete = False
            evidence_errors.append("CPU pressure evidence unavailable")
        pressure_wall_usec += phase_wall_seconds * 1_000_000.0
        steal_capacity_seconds += phase_wall_seconds * max(1, len(per_cpu or {}))
        for counters in (per_cpu or {}).values():
            if counters and "steal" in counters:
                if any(value < 0 for value in counters.values()):
                    evidence_complete = False
                    evidence_errors.append("negative per-CPU tick delta")
                steal_ticks += int(counters.get("steal", 0))
            else:
                evidence_complete = False
    ticks_per_second = next(
        (
            phase["cpu_interference"].get("clock_ticks_per_second")
            for phase in phases
            if phase["cpu_interference"].get("clock_ticks_per_second")
        ),
        None,
    )
    steal_fraction = (
        (steal_ticks / float(ticks_per_second)) / steal_capacity_seconds
        if ticks_per_second and steal_capacity_seconds > 0
        else None
    )
    pressure_some_fraction = (
        pressure_some_usec / pressure_wall_usec if pressure_wall_usec > 0 else None
    )
    pressure_full_fraction = (
        pressure_full_usec / pressure_wall_usec if pressure_wall_usec > 0 else None
    )
    pressure_available = pressure_phase_count == len(phases)
    if pressure_phase_count not in {0, len(phases)}:
        evidence_complete = False
    pressure_clean = (
        pressure_available
        and pressure_some_fraction is not None
        and pressure_some_fraction <= MAX_CPU_PSI_SOME_FRACTION
        and pressure_full_fraction is not None
        and pressure_full_fraction <= MAX_CPU_PSI_FULL_FRACTION
    )
    quota_sufficient = quota_sufficient_for_threads(expected_cpu_control, threads)
    if not quota_sufficient:
        evidence_complete = False
        evidence_errors.append("CPU-control quota is unavailable or below declared threads")
    clean = (
        evidence_complete
        and throttle_events == 0
        and throttled_usec == 0
        and steal_fraction is not None
        and steal_fraction <= MAX_STEAL_CAPACITY_FRACTION
        and pressure_clean
    )
    return {
        "evidence_complete": evidence_complete,
        "evidence_errors": sorted(set(evidence_errors)),
        "exact_selected_cpu_ids": expected_affinity,
        "cpu_control": expected_cpu_control,
        "cpu_control_quota_sufficient_for_threads": quota_sufficient,
        "cgroup_throttle_events": throttle_events,
        "cgroup_throttled_usec": throttled_usec,
        "selected_cpu_steal_ticks": steal_ticks,
        "selected_cpu_steal_capacity_fraction": steal_fraction,
        "selected_cpu_steal_capacity_fraction_limit": MAX_STEAL_CAPACITY_FRACTION,
        "cpu_pressure_some_fraction": pressure_some_fraction,
        "cpu_pressure_some_fraction_limit": MAX_CPU_PSI_SOME_FRACTION,
        "cpu_pressure_full_fraction": pressure_full_fraction,
        "cpu_pressure_full_fraction_limit": MAX_CPU_PSI_FULL_FRACTION,
        "cpu_pressure_available": pressure_available,
        "cpu_pressure_reason": "parsed and gated" if pressure_available else "PSI unavailable; host invalid",
        "clean": clean,
    }


def _thermal_evidence(record: dict[str, Any]) -> dict[str, Any]:
    before = record.get("host_before", {}).get("thermal_celsius")
    after = record.get("host_after", {}).get("thermal_celsius")
    before_source = record.get("host_before", {}).get("thermal_source")
    after_source = record.get("host_after", {}).get("thermal_source")
    if not before and not after:
        return {
            "available": False,
            "clean": True,
            "reason": "thermal sensors unavailable on both sides; no value invented",
            "ceiling_c": THERMAL_CEILING_C,
            "max_rise_c": THERMAL_MAX_RISE_C,
        }
    if not before or not after:
        return {
            "available": False,
            "clean": False,
            "reason": "thermal sensors available on only one side of process",
            "before": before,
            "after": after,
            "ceiling_c": THERMAL_CEILING_C,
        }
    stable_sources = before_source == after_source and set(before) == set(after)
    before_max = max(float(value) for value in before.values())
    after_max = max(float(value) for value in after.values())
    rise = after_max - before_max
    return {
        "available": True,
        "before_max_c": before_max,
        "after_max_c": after_max,
        "rise_c": rise,
        "ceiling_c": THERMAL_CEILING_C,
        "max_rise_c": THERMAL_MAX_RISE_C,
        "stable_sensor_sources": stable_sources,
        "clean": (
            stable_sources
            and max(before_max, after_max) <= THERMAL_CEILING_C
            and rise <= THERMAL_MAX_RISE_C
        ),
    }


def _summarize_cell(
    cell: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    expected_pairs: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    _validate_v2_records(records)
    if any(
        record["cell"].get("id") != cell["id"]
        or record["cell"].get("comparison_id") != cell["comparison_id"]
        for record in records
    ):
        raise RuntimeError(f"cell {cell['id']} contains foreign comparison evidence")
    measured = [record for record in records if record["sample"]["phase"] == "measured"]
    warmups = [record for record in records if record["sample"]["phase"] == "warmup"]
    first_label, second_label = cell["comparison"]
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    orders: list[str] = []
    for pair_index in range(expected_pairs):
        current = [r for r in measured if int(r["sample"]["pair_index"]) == pair_index]
        first = [r for r in current if r["sample"]["source_label"] == first_label]
        second = [r for r in current if r["sample"]["source_label"] == second_label]
        if len(first) != 1 or len(second) != 1:
            raise RuntimeError(f"cell {cell['id']} pair {pair_index} is incomplete")
        pairs.append((first[0], second[0]))
        orders.append(str(current[0]["sample"]["order"]))

    baseline_insert = [_measurement(base, "insertion", "mean_wall_ns_per_operation") for base, _ in pairs]
    candidate_insert = [_measurement(target, "insertion", "mean_wall_ns_per_operation") for _, target in pairs]
    baseline_lookup = [_measurement(base, "lookup_control", "mean_wall_ns_per_operation") for base, _ in pairs]
    candidate_lookup = [_measurement(target, "lookup_control", "mean_wall_ns_per_operation") for _, target in pairs]
    throughput_ratios = [base / cand for base, cand in zip(baseline_insert, candidate_insert)]
    lookup_throughput_ratios = [base / cand for base, cand in zip(baseline_lookup, candidate_lookup)]
    insertion_rss_ratios = [
        float(target["measurements"]["insertion_rss"]["peak_bytes_immediately_after_insertion"])
        / float(base["measurements"]["insertion_rss"]["peak_bytes_immediately_after_insertion"])
        for base, target in pairs
    ]
    whole_workload_rss_ratios = [
        float(target["measurements"]["whole_workload_rss"]["peak_bytes"])
        / float(base["measurements"]["whole_workload_rss"]["peak_bytes"])
        for base, target in pairs
    ]
    final_process_rss_ratios = [
        float(target["measurements"]["final_process_rss"]["peak_bytes"])
        / float(base["measurements"]["final_process_rss"]["peak_bytes"])
        for base, target in pairs
    ]
    dedicated_latency_rss_ratios = [
        float(target["dedicated_latency"]["measurements"]["final_process_rss"]["peak_bytes"])
        / float(base["dedicated_latency"]["measurements"]["final_process_rss"]["peak_bytes"])
        for base, target in pairs
    ]
    semantic_equal = all(
        base["semantic_outcome"] == target["semantic_outcome"]
        and base["real_tds_telemetry"] == target["real_tds_telemetry"]
        for base, target in pairs
    )
    latency: dict[str, Any] = {}
    for phase in ("insertion", "lookup"):
        latency[phase] = {}
        for name, percentile in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
            baseline_values = [_operation_percentile(base, phase, percentile) for base, _ in pairs]
            target_values = [_operation_percentile(target, phase, percentile) for _, target in pairs]
            ratios = [target / base for base, target in zip(baseline_values, target_values)]
            latency[phase][name] = {
                "baseline_process_percentiles_ns": baseline_values,
                "target_process_percentiles_ns": target_values,
                "paired_target_over_baseline": ratios,
                "paired_ratio_median": statistics.median(ratios),
                "paired_ratio_bootstrap_95_ci": _bootstrap_median_ci(
                    ratios,
                    seed=bootstrap_seed ^ {
                        ("insertion", "p50"): 0x150,
                        ("insertion", "p95"): 0x195,
                        ("insertion", "p99"): 0x199,
                        ("lookup", "p50"): 0x250,
                        ("lookup", "p95"): 0x295,
                        ("lookup", "p99"): 0x299,
                    }[(phase, name)],
                ),
            }

    baseline_wall_ns = [_measurement(base, "insertion", "wall_ns") for base, _ in pairs]
    baseline_cpu_ns = [_measurement(base, "insertion", "process_cpu_ns") for base, _ in pairs]
    candidate_cpu_ns = [_measurement(target, "insertion", "process_cpu_ns") for _, target in pairs]
    baseline_cpu_util = [_measurement(base, "insertion", "cpu_utilization_percent") for base, _ in pairs]
    candidate_cpu_util = [_measurement(target, "insertion", "cpu_utilization_percent") for _, target in pairs]

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, observed: Any, required: str) -> None:
        checks.append({
            "name": name,
            "passed": bool(passed),
            "observed": observed,
            "required": required,
        })

    baseline_cv = _coefficient_of_variation(baseline_wall_ns)
    baseline_lookup_wall_ns = [_measurement(base, "lookup_control", "wall_ns") for base, _ in pairs]
    baseline_lookup_cv = _coefficient_of_variation(baseline_lookup_wall_ns)
    baseline_stability = {
        "insertion_wall": _variation_evidence(baseline_wall_ns),
        "lookup_wall": _variation_evidence(baseline_lookup_wall_ns),
        "insertion_peak_rss": _variation_evidence([
            float(base["measurements"]["insertion_rss"]["peak_bytes_immediately_after_insertion"])
            for base, _ in pairs
        ]),
        "whole_workload_peak_rss": _variation_evidence([
            float(base["measurements"]["whole_workload_rss"]["peak_bytes"])
            for base, _ in pairs
        ]),
    }
    for phase in ("insertion", "lookup"):
        for name in ("p50", "p95", "p99"):
            baseline_stability[f"{phase}_{name}_operation_latency"] = _variation_evidence(
                latency[phase][name]["baseline_process_percentiles_ns"]
            )
    interference = [_interference(record) for pair in pairs for record in pair]
    thermal = [_thermal_evidence(record) for pair in pairs for record in pair]
    lookup_operation_counts = {
        int(record["measurements"]["lookup_control"]["operations"])
        for pair in pairs
        for record in pair
    }
    lookup_unique_key_counts = {
        int(record["cell"]["lookup_unique_keys"])
        for pair in pairs
        for record in pair
    }
    diagnostics_off_exact = all(
        snapshot["enabled"] is False
        and all(
            int(snapshot[name]) == 0
            for name in (
                "native_put_calls",
                "native_lookup_calls",
                "python_native_transitions",
                "gil_released_calls",
                "events_emitted",
                "events_dropped",
            )
        )
        for pair in pairs
        for record in pair
        for snapshot in (
            record["final_stats"]["throughput_diagnostics"],
            record["final_stats"]["latency_diagnostics"],
        )
    )
    check("measured_pairs", len(pairs) >= 7, len(pairs), ">= 7")
    check("randomized_ab_ba", "AB" in orders and "BA" in orders, orders, "both AB and BA")
    check("two_excluded_warmup_pairs", len(warmups) == 4, len(warmups) // 2, "2")
    check("semantic_and_telemetry_equality", semantic_equal, semantic_equal, "true")
    check(
        "ordinary_diagnostics_disabled_exact",
        cell["diagnostics"] == "off" and diagnostics_off_exact,
        {"configured": cell["diagnostics"], "exact_zero_counters": diagnostics_off_exact},
        "diagnostics disabled and every intrusive counter exactly zero in throughput and latency workloads",
    )
    for metric, evidence in baseline_stability.items():
        check(
            f"baseline_variation_{metric}",
            bool(evidence["stable"]),
            evidence,
            "CV <=5% and every baseline sample within ±5% of the baseline median",
        )
    check(
        "fixed_hot_lookup_control",
        lookup_operation_counts == {max(1_000_000, int(cell["entries"]))}
        and lookup_unique_key_counts == {int(cell["entries"])},
        {
            "lookup_operations": sorted(lookup_operation_counts),
            "unique_keys": sorted(lookup_unique_key_counts),
        },
        "at least 1,000,000 hot lookups over exactly the declared existing-key set",
    )
    check(
        "host_interference",
        all(item["clean"] for item in interference),
        interference,
        "exact/stable v2, v1, true-root-unlimited, or proven-none CPU-control identity across every visible quota/burst/stat hierarchy level; selected-CPU and PSI evidence; canonical nonnegative per-level throttle deltas; zero throttle at every level; each finite quota >=threads or proven unconstrained; steal <=0.5%; PSI some <=5% and full <=1%",
    )
    check(
        "thermal_host_interference",
        all(item["clean"] for item in thermal),
        thermal,
        "both unavailable is recorded; one-sided unavailable fails; stable sensors max(before,after)<=90C and rise<=10C",
    )

    throughput_median = statistics.median(throughput_ratios)
    throughput_ci = _bootstrap_median_ci(
        throughput_ratios,
        seed=bootstrap_seed,
    )
    if cell["role"] in ACCEPTANCE_ROLES and int(cell["entries"]) in (50_000, 100_000):
        check("insertion_gain", throughput_median >= 1.10, throughput_median, ">= 1.10x")
        check("insertion_gain_ci_lower", throughput_ci[0] > 1.05, throughput_ci, "95% CI lower strictly > 1.05x")
        check(
            "insertion_gain_worst_pair_floor",
            min(throughput_ratios) >= 0.90,
            min(throughput_ratios),
            "every paired insertion throughput ratio >= 0.90x",
        )
    if cell["role"] == "causal-localization-only":
        check("raw_causal_gain", throughput_median >= 1.10, throughput_median, ">= 1.10x")
        check("raw_causal_gain_ci_lower", throughput_ci[0] > 1.05, throughput_ci, "95% CI lower strictly > 1.05x")
        check(
            "raw_causal_gain_worst_pair_floor",
            min(throughput_ratios) >= 0.90,
            min(throughput_ratios),
            "every paired raw insertion throughput ratio >= 0.90x",
        )

    lookup_median = statistics.median(lookup_throughput_ratios)
    lookup_ci = _bootstrap_median_ci(
        lookup_throughput_ratios,
        seed=bootstrap_seed ^ 0xA5A5A5A5,
    )
    if cell["role"] in ACCEPTANCE_ROLES:
        check(
            "lookup_throughput_ci_lower",
            lookup_ci[0] >= 0.97,
            lookup_ci,
            "95% CI lower >= 0.97x",
        )
        check(
            "lookup_throughput_worst_pair_floor",
            min(lookup_throughput_ratios) >= 0.90,
            min(lookup_throughput_ratios),
            "every paired lookup throughput ratio >= 0.90x",
        )
        for phase in ("insertion", "lookup"):
            for name, limit in (("p50", 1.05), ("p95", 1.05), ("p99", 1.10)):
                ci = latency[phase][name]["paired_ratio_bootstrap_95_ci"]
                check(
                    f"{phase}_{name}_latency_ci_upper",
                    ci[1] <= limit,
                    ci,
                    f"95% CI upper <= {limit:.2f}x",
                )
                check(
                    f"{phase}_{name}_latency_worst_pair",
                    max(latency[phase][name]["paired_target_over_baseline"]) <= limit,
                    max(latency[phase][name]["paired_target_over_baseline"]),
                    f"every paired target/baseline ratio <= {limit:.2f}x",
                )
        insertion_rss_ci = _bootstrap_median_ci(
            insertion_rss_ratios, seed=bootstrap_seed ^ 0x525353
        )
        whole_workload_rss_ci = _bootstrap_median_ci(
            whole_workload_rss_ratios, seed=bootstrap_seed ^ 0x57525353
        )
        check("insertion_peak_rss_ci_upper", insertion_rss_ci[1] <= 1.05, insertion_rss_ci, "95% CI upper <= 1.05x")
        check(
            "insertion_peak_rss_worst_pair",
            max(insertion_rss_ratios) <= 1.05,
            max(insertion_rss_ratios),
            "every paired target/baseline insertion peak RSS ratio <= 1.05x",
        )
        check(
            "whole_workload_peak_rss_ci_upper",
            whole_workload_rss_ci[1] <= 1.05,
            whole_workload_rss_ci,
            "uninstrumented post-lookup whole-workload peak RSS 95% CI upper <=1.05x",
        )
        check(
            "whole_workload_peak_rss_worst_pair",
            max(whole_workload_rss_ratios) <= 1.05,
            max(whole_workload_rss_ratios),
            "every uninstrumented post-lookup whole-workload peak RSS ratio <=1.05x",
        )
    else:
        insertion_rss_ci = _bootstrap_median_ci(
            insertion_rss_ratios, seed=bootstrap_seed ^ 0x525353
        )
        whole_workload_rss_ci = _bootstrap_median_ci(
            whole_workload_rss_ratios, seed=bootstrap_seed ^ 0x57525353
        )

    validity_names = {
        "host_interference",
        "thermal_host_interference",
        *(name for name in (item["name"] for item in checks) if name.startswith("baseline_variation_")),
    }
    deterministic_names = {
        "measured_pairs",
        "randomized_ab_ba",
        "two_excluded_warmup_pairs",
        "semantic_and_telemetry_equality",
        "ordinary_diagnostics_disabled_exact",
        "fixed_hot_lookup_control",
    }
    measurement_valid = all(
        item["passed"] for item in checks if item["name"] in validity_names
    )
    for item in checks:
        if item["name"] in validity_names:
            item["kind"] = "validity"
            item["decisional"] = True
        elif item["name"] in deterministic_names:
            item["kind"] = "deterministic"
            item["decisional"] = True
        else:
            item["kind"] = "performance"
            item["decisional"] = measurement_valid

    return {
        "cell": cell,
        "warmup_processes": len(warmups),
        "measured_pairs": len(pairs),
        "measured_order": orders,
        "baseline_wall_time_cv": baseline_cv,
        "baseline_lookup_wall_time_cv": baseline_lookup_cv,
        "baseline_metric_stability": baseline_stability,
        "measurement_valid": measurement_valid,
        "comparison_labels": [first_label, second_label],
        "insertion": {
            "baseline_median_wall_ns": statistics.median(baseline_wall_ns),
            "baseline_median_process_cpu_ns": statistics.median(baseline_cpu_ns),
            "target_median_process_cpu_ns": statistics.median(candidate_cpu_ns),
            "baseline_median_cpu_utilization_percent": statistics.median(baseline_cpu_util),
            "target_median_cpu_utilization_percent": statistics.median(candidate_cpu_util),
            "paired_throughput_ratios_target_over_baseline": throughput_ratios,
            "paired_throughput_ratio_median": throughput_median,
            "paired_throughput_ratio_bootstrap_95_ci": throughput_ci,
        },
        "lookup_control": {
            "unique_keys_per_process": int(cell["entries"]),
            "operations_per_process": max(1_000_000, int(cell["entries"])),
            "paired_throughput_ratios_target_over_baseline": lookup_throughput_ratios,
            "paired_throughput_ratio_median": lookup_median,
            "paired_throughput_ratio_bootstrap_95_ci": lookup_ci,
        },
        "dedicated_operation_latency": latency,
        "rss": {
            "uninstrumented_insertion_peak_ratios_target_over_baseline": insertion_rss_ratios,
            "uninstrumented_insertion_peak_ratio_bootstrap_95_ci": insertion_rss_ci,
            "uninstrumented_whole_workload_post_lookup_peak_ratios_target_over_baseline": whole_workload_rss_ratios,
            "uninstrumented_whole_workload_post_lookup_peak_ratio_bootstrap_95_ci": whole_workload_rss_ci,
            "throughput_final_process_peak_ratios_retained_not_primary": final_process_rss_ratios,
            "dedicated_latency_final_process_peak_ratios_retained_not_primary": dedicated_latency_rss_ratios,
        },
        "host_interference": interference,
        "thermal_host_interference": thermal,
        "semantic_and_telemetry_equality": semantic_equal,
        "checks": checks,
        "passed": all(item["passed"] for item in checks if item["decisional"]),
    }


def _machine_identity(topology: dict[str, Any] | None = None) -> dict[str, Any]:
    topology = topology or _effective_cpu_topology()
    return {
        "platform": platform.platform(),
        "operating_system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "allowed_physical_core_count": topology["allowed_physical_core_count"],
        "effective_physical_core_count": topology["effective_physical_core_count"],
        "logical_cpu_count": os.cpu_count(),
        "available_cpu_affinity": topology["allowed_cpu_ids"],
        "cpu_topology_sha256": topology["topology_sha256"],
        "cpu_control": topology["cpu_control"],
        "storage_device_class": "recorded-per-fixed-persistence-and-generation-sentinel",
    }


def _positive_ratio(candidate: int | float, baseline: int | float) -> float | None:
    if baseline <= 0 or candidate <= 0:
        return None
    return float(candidate) / float(baseline)


def _canonical_file_tree_root(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def _semantic_root_set(records: list[dict[str, Any]]) -> set[tuple[str, str, str | None]]:
    return {
        (
            str(record["semantic_outcome"]["handle_set_sha256"]),
            str(record["association_sha256"]),
            record["semantic_outcome"].get("value_sha256"),
        )
        for record in records
    }


def _independent_roots_equal(
    first_records: list[dict[str, Any]],
    second_records: list[dict[str, Any]],
) -> bool:
    return bool(first_records and second_records) and _semantic_root_set(
        first_records
    ) == _semantic_root_set(second_records)


def _sentinel_global_checks(
    sentinels: dict[str, dict[str, Any]],
    harness_binding: dict[str, Any],
    builds: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, observed: Any, required: str) -> None:
        checks.append({
            "cell": "global",
            "name": name,
            "passed": bool(passed),
            "observed": observed,
            "required": required,
        })

    baseline_persistence = sentinels["baseline"]["persistence"]
    persistence_roots = {
        label: item["persistence"]["value_root"] for label, item in sentinels.items()
    }
    persistence_trees = {
        label: item["persistence"]["file_tree"] for label, item in sentinels.items()
    }
    persistence_paths = {
        label: item["persistence"]["written_paths"] for label, item in sentinels.items()
    }
    check(
        "persistence_semantic_root",
        len(set(persistence_roots.values())) == 1,
        persistence_roots,
        "exact equality across baseline, allocator-only, and candidate",
    )
    check(
        "persistence_file_tree_self_hash",
        all(
            tree["tree_root_sha256"] == _canonical_file_tree_root(tree["records"])
            for tree in persistence_trees.values()
        ),
        persistence_trees,
        "every retained relative file manifest exactly hashes to its declared tree root",
    )
    check(
        "persistence_file_tree_exact",
        len({json.dumps(value, sort_keys=True) for value in persistence_trees.values()}) == 1,
        persistence_trees,
        "exact relative path, SHA-256, size, and allocation manifest equality across all three sources",
    )
    check(
        "persistence_written_paths",
        len({json.dumps(value, sort_keys=True) for value in persistence_paths.values()}) == 1,
        persistence_paths,
        "exact written-path set equality across all three sources",
    )
    persistence_restored = {
        label: item["persistence"]["restored_semantics"]
        for label, item in sentinels.items()
    }
    check(
        "persistence_restored_order_handles_high_water",
        len({json.dumps(value, sort_keys=True) for value in persistence_restored.values()}) == 1,
        persistence_restored,
        "exact serialized order, compact restored handles, and restored next-handle semantics across all three sources",
    )
    for target_label in ("allocator-only", "candidate"):
        target = sentinels[target_label]["persistence"]
        ratios = {
            "allocated_bytes": _positive_ratio(
                target["tree_allocation"]["allocated_bytes_st_blocks_x_512"],
                baseline_persistence["tree_allocation"]["allocated_bytes_st_blocks_x_512"],
            ),
            "process_write_bytes": _positive_ratio(
                (target.get("process_io_delta") or {}).get("write_bytes", 0),
                (baseline_persistence.get("process_io_delta") or {}).get("write_bytes", 0),
            ),
            "rusage_output_blocks": _positive_ratio(
                target.get("rusage_output_blocks_delta", 0),
                baseline_persistence.get("rusage_output_blocks_delta", 0),
            ),
        }
        for metric, ratio in ratios.items():
            check(
                f"persistence_{metric}_{target_label}_over_baseline",
                ratio is not None and ratio <= 1.05,
                ratio,
                f"nonzero physical-write evidence and {target_label}/baseline <= 1.05x",
            )
    storage_classes = {
        label: item["persistence"]["storage_device"]["classification"]
        for label, item in sentinels.items()
    }
    check(
        "persistence_storage_device_class",
        len(set(storage_classes.values())) == 1,
        storage_classes,
        "same recorded storage-device class for all immutable source runs",
    )
    sentinel_build_identity = {
        label: {
            "sentinel_native_source_sha256": item["source_identity"]["native_source_sha256"],
            "build_native_source_sha256": builds[label]["native_source_sha256"],
            "sentinel_extension_sha256": item["source_identity"]["extension_sha256"],
            "build_extension_sha256": builds[label]["extension_sha256"],
        }
        for label, item in sentinels.items()
    }
    check(
        "sentinel_build_identity",
        all(
            value["sentinel_native_source_sha256"] == value["build_native_source_sha256"]
            and value["sentinel_extension_sha256"] == value["build_extension_sha256"]
            for value in sentinel_build_identity.values()
        ),
        sentinel_build_identity,
        "every sentinel source and loaded extension exactly match retained build provenance",
    )
    check(
        "allocator_only_ablation_identity",
        builds["allocator-only"]["native_source_sha256"]
        == builds["candidate"]["native_source_sha256"]
        and builds["allocator-only"]["wrapper_source_sha256"]
        == builds["baseline"]["wrapper_source_sha256"],
        {
            label: {
                "native_source_sha256": build["native_source_sha256"],
                "wrapper_source_sha256": build["wrapper_source_sha256"],
            }
            for label, build in builds.items()
        },
        "allocator-only has exact candidate C source and exact baseline wrapper source",
    )
    compile_commands = {
        label: build.get("actual_native_compile_command") for label, build in builds.items()
    }
    check(
        "identical_compiler_and_flags",
        None not in compile_commands.values() and len(set(compile_commands.values())) == 1,
        compile_commands,
        "one exact retained native compile command shared by all three sources",
    )
    link_commands = {
        label: build.get("actual_native_link_command") for label, build in builds.items()
    }
    check(
        "identical_linker_and_flags",
        None not in link_commands.values() and len(set(link_commands.values())) == 1,
        link_commands,
        "one exact retained native link command and flags shared by all three sources",
    )

    baseline_generation = sentinels["baseline"]["generation"]
    generation_roots = {
        label: item["generation"]["generation_root"] for label, item in sentinels.items()
    }
    head_roots = {
        label: item["generation"]["head_root"] for label, item in sentinels.items()
    }
    check(
        "generation_root_exact",
        len(set(generation_roots.values())) == 1,
        generation_roots,
        "exact published generation root equality across all three sources",
    )
    check(
        "generation_head_root_exact",
        len(set(head_roots.values())) == 1,
        head_roots,
        "exact published head root equality across all three sources",
    )
    within_source_roots: dict[str, Any] = {}
    within_source_exact = True
    for label, item in sentinels.items():
        roots = item["generation"]["roots"]
        generation_values = [value for key, value in roots.items() if key.endswith("generation")]
        head_values = [value for key, value in roots.items() if key.endswith("head")]
        exact = len(generation_values) == 8 and len(set(generation_values)) == 1
        exact = exact and len(head_values) == 5 and len(set(head_values)) == 1
        within_source_exact = within_source_exact and exact
        within_source_roots[label] = roots
    check(
        "generation_published_recovered_identity",
        within_source_exact,
        within_source_roots,
        "within each source candidate/published/CURRENT/recovered/stable/lease generation roots and every head root are exact",
    )
    payload_readbacks = {
        label: item["generation"]["payload_readback"] for label, item in sentinels.items()
    }
    check(
        "generation_source_offsets_readback",
        len({json.dumps(value, sort_keys=True) for value in payload_readbacks.values()}) == 1
        and all(item["generation"]["offsets_value_little_endian"] == 14 for item in sentinels.values()),
        payload_readbacks,
        "exact source and eight-byte little-endian offsets readback equality across all three sources",
    )
    mutation_roots = {
        label: {
            "base": item["generation"]["generation_root"],
            **item["generation"]["mutations"],
        }
        for label, item in sentinels.items()
    }
    mutation_shapes = {
        json.dumps(value, sort_keys=True) for value in mutation_roots.values()
    }
    mutation_sensitive = len(mutation_shapes) == 1 and all(
        len({
            value["base"],
            value["source_generation_root"],
            value["offsets_generation_root"],
        }) == 3
        for value in mutation_roots.values()
    )
    check(
        "generation_mutation_sensitivity",
        mutation_sensitive,
        mutation_roots,
        "source-only and offsets-only mutations independently change the canonical Generation root, identically across sources",
    )
    check(
        "generation_recovery",
        all(
            item["generation"]["first_recovery_repaired"]
            and not item["generation"]["second_recovery_repaired"]
            and item["generation"]["source_sha256"]
            == baseline_generation["source_sha256"]
            for item in sentinels.values()
        ),
        {label: item["generation"] for label, item in sentinels.items()},
        "exact authoritative source and deterministic idempotent recovery",
    )
    for target_label in ("allocator-only", "candidate"):
        target = sentinels[target_label]["generation"]
        ratios = {
            "allocated_bytes": _positive_ratio(
                target["tree_allocation"]["allocated_bytes_st_blocks_x_512"],
                baseline_generation["tree_allocation"]["allocated_bytes_st_blocks_x_512"],
            ),
            "process_write_bytes": _positive_ratio(
                (target.get("process_io_delta") or {}).get("write_bytes", 0),
                (baseline_generation.get("process_io_delta") or {}).get("write_bytes", 0),
            ),
            "rusage_output_blocks": _positive_ratio(
                target.get("rusage_output_blocks_delta", 0),
                baseline_generation.get("rusage_output_blocks_delta", 0),
            ),
        }
        for metric, ratio in ratios.items():
            check(
                f"generation_{metric}_{target_label}_over_baseline",
                ratio is not None and ratio <= 1.05,
                ratio,
                f"nonzero physical-write evidence and {target_label}/baseline <= 1.05x",
            )

    allocator_fields = (
        "first_handles",
        "deleted_handle",
        "after_delete",
        "capacity_before_resize",
        "capacity_after_resize",
        "after_resize",
        "restore_failures",
        "exhaustion",
        "concurrent_handle_set_sha256",
    )
    allocator_semantics = {
        label: {field: item["allocator"][field] for field in allocator_fields}
        for label, item in sentinels.items()
    }
    check(
        "allocator_semantic_sentinels",
        len({json.dumps(value, sort_keys=True) for value in allocator_semantics.values()}) == 1,
        allocator_semantics,
        "exact deletion/explicit/high-water/resize/restore/exhaustion/concurrency equality",
    )
    zero_scan_observed = {
        label: {
            "automatic_scan_present": item["allocator"]["automatic_scan_present"],
            "explicit_scan_present": item["allocator"]["explicit_scan_present"],
        }
        for label, item in sentinels.items()
    }
    check(
        "zero_automatic_scan",
        harness_binding.get("native_index_diff_sha256") == NATIVE_SOURCE_DIFF_SHA256
        and sentinels["baseline"]["allocator"]["automatic_scan_present"]
        and not sentinels["allocator-only"]["allocator"]["automatic_scan_present"]
        and not sentinels["candidate"]["allocator"]["automatic_scan_present"]
        and all(item["allocator"]["explicit_scan_present"] for item in sentinels.values()),
        {
            "native_index_diff_sha256": harness_binding.get("native_index_diff_sha256"),
            "source_scan_proof": zero_scan_observed,
        },
        "exact pinned C diff; baseline automatic scan present; allocator-only/candidate absent; explicit scan present",
    )
    return checks


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Native allocator v3.8.2 retained qualification",
        "",
        f"Status: **{summary['status']}**",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "| Cell | Paired insertion ratio | 95% bootstrap CI | Lookup ratio | Baseline CV | Result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for cell in summary["cells"]:
        insertion = cell["insertion"]
        lookup = cell["lookup_control"]
        ci = insertion["paired_throughput_ratio_bootstrap_95_ci"]
        lines.append(
            "| {id} | {ratio:.3f}x | [{low:.3f}, {high:.3f}]x | {lookup:.3f}x | {cv:.2%} | {result} |".format(
                id=cell["cell"]["id"],
                ratio=insertion["paired_throughput_ratio_median"],
                low=ci[0],
                high=ci[1],
                lookup=lookup["paired_throughput_ratio_median"],
                cv=cell["baseline_wall_time_cv"],
                result=(
                    "PASS"
                    if cell["passed"]
                    else ("HOST/CV INVALID" if not cell["measurement_valid"] else "FAIL")
                ),
            )
        )
    lines.extend(
        [
            "",
            (
                "The release primary is one real `TDSFileSystem` directory using "
                "`root.write_entry(..., FmtID.RAW_BINARY, compress=False)` with an exact "
                "32-byte value and a real `TelemetryManager(NORMAL)` observer. The complete "
                "full-TDS matrix is paired twice: baseline→allocator-only proves the exact C "
                "patch causally, while independent baseline→candidate pairs validate the "
                "shipped package. Two 100K `NativeEntryIndexBackend` cells are allocator "
                "controls, and the 4,096-initial-capacity raw C cell is localization only. "
                "All ordinary acceptance processes keep intrusive native diagnostics OFF. Each cell "
                "used two excluded paired warmups and fresh-process randomized AB/BA "
                "measured pairs. The two telemetry-OFF cells are explicitly characterized "
                "sensitivities, not release-primary performance cells."
            ),
            "",
            (
                "Latency p50/p95/p99 values come from genuine operation timers in a separate "
                "dedicated-latency workload; each process retains up to 8,192 evenly spaced "
                "operation samples. Uninstrumented throughput uses at least 1,000,000 hot "
                "lookups and gates peak RSS captured immediately after that lookup workload; "
                "post-validation and dedicated-latency RSS remain separately retained. Raw JSONL, build logs, "
                "exact harness/source/extension identities, actual compiler commands and "
                "link flags, effective allowed physical-core topology, exact per-process "
                "affinity and observed phase CPUs, process CPU/wall/RSS/I/O, independently executed NORMAL/OFF roots "
                "for both causal and shipped comparisons, and physical persistence/recovery "
                "sentinels are retained beside this report."
            ),
            "",
        ]
    )
    if summary["failed_checks"]:
        lines.append("Failed checks:")
        lines.append("")
        for item in summary["failed_checks"]:
            lines.append(
                f"- `{item['cell']}/{item['name']}`: observed `{item['observed']}`; required {item['required']}."
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=RUNNER_PATH.parent.parent)
    parser.add_argument("--baseline-ref", default="v3.8.1")
    parser.add_argument("--candidate-ref", default="HEAD")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=7)
    parser.add_argument("--warmup-pairs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=3_820_817)
    parser.add_argument("--keep-build-trees", action="store_true")
    args = parser.parse_args()
    if args.pairs != 7:
        parser.error("the v2 publication protocol requires exactly seven measured pairs")
    if args.warmup_pairs != 2:
        parser.error("the release protocol requires exactly two excluded warmup pairs")
    for required in (WORKER_PATH, SENTINEL_PATH, CPU_CONTROL_PATH):
        if not required.is_file():
            parser.error(f"qualification component is missing: {required}")

    repo = args.repository.resolve()
    output = args.output_dir.resolve()
    existing = set(output.iterdir()) if output.exists() else set()
    allowed_workflow_bootstrap = output / "workflow-bootstrap.json"
    if existing - {allowed_workflow_bootstrap}:
        parser.error(
            "output directory must be absent, empty, or contain only workflow-bootstrap.json"
        )
    if allowed_workflow_bootstrap in existing and not allowed_workflow_bootstrap.is_file():
        parser.error("workflow-bootstrap.json must be a regular file")
    output.mkdir(parents=True, exist_ok=True)
    run_id = f"allocator-v382-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    qualifier_bootstrap_path = output / "qualifier-bootstrap.json"
    qualifier_bootstrap = {
        "schema": 2,
        "runner_id": RUNNER_ID,
        "run_id": run_id,
        "status": "BOOTSTRAPPED_BEFORE_CPU_CONTROL_DISCOVERY",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repository": str(repo),
        "baseline_ref": args.baseline_ref,
        "candidate_ref": args.candidate_ref,
        "cpu_control_proof_sources": [
            "/proc/self/mountinfo",
            "/proc/self/cgroup",
        ],
    }
    _write_json(qualifier_bootstrap_path, qualifier_bootstrap)
    baseline = _resolve_source(repo, args.baseline_ref, "baseline")
    candidate = _resolve_source(repo, args.candidate_ref, "candidate")
    if baseline["commit"] == candidate["commit"]:
        parser.error("baseline and candidate resolve to the same commit")
    harness_binding = _verify_harness_binding(repo, baseline, candidate)
    try:
        topology = _effective_cpu_topology()
    except Exception as exc:
        qualifier_bootstrap.update(
            {
                "status": "CPU_CONTROL_DISCOVERY_FAILED",
                "failure": f"{type(exc).__name__}: {exc}",
            }
        )
        _write_json(qualifier_bootstrap_path, qualifier_bootstrap)
        raise
    qualifier_bootstrap.update(
        {
            "status": "CPU_CONTROL_DISCOVERED",
            "cpu_control": topology["cpu_control"],
        }
    )
    _write_json(qualifier_bootstrap_path, qualifier_bootstrap)
    multi_threads = int(topology["multi_threads"])
    cells = _cells(multi_threads)

    temporary = tempfile.TemporaryDirectory(prefix="tds-v382-allocator-")
    temp_root = Path(temporary.name)
    baseline_root = temp_root / "baseline"
    allocator_only_root = temp_root / "allocator-only"
    candidate_root = temp_root / "candidate"
    print(f"[{run_id}] exporting immutable source trees", flush=True)
    _export_source(repo, baseline, baseline_root)
    _export_source(repo, candidate, candidate_root)
    allocator_only = _derive_allocator_only_source(
        baseline_root,
        candidate_root,
        allocator_only_root,
        baseline,
    )
    worker_path = candidate_root / "benchmarks" / WORKER_PATH.name
    sentinel_path = candidate_root / "benchmarks" / SENTINEL_PATH.name
    cpu_control_path = candidate_root / "benchmarks" / CPU_CONTROL_PATH.name
    if (
        _sha256(worker_path) != _sha256(WORKER_PATH)
        or _sha256(sentinel_path) != _sha256(SENTINEL_PATH)
        or _sha256(cpu_control_path) != _sha256(CPU_CONTROL_PATH)
    ):
        raise RuntimeError("exported candidate harness identity changed")

    protocol = {
        "schema": 2,
        "runner_id": RUNNER_ID,
        "runner_path": str(RUNNER_PATH),
        "runner_sha256": _sha256(RUNNER_PATH),
        "worker_path": str(worker_path),
        "worker_sha256": _sha256(worker_path),
        "sentinel_path": str(sentinel_path),
        "sentinel_sha256": _sha256(sentinel_path),
        "cpu_control_path": str(cpu_control_path),
        "cpu_control_sha256": _sha256(cpu_control_path),
        "harness_binding": harness_binding,
        "run_id": run_id,
        "seed": args.seed,
        "warmup_pairs_excluded": args.warmup_pairs,
        "measured_pairs": args.pairs,
        "expected_worker_processes": len(cells) * (args.warmup_pairs + args.pairs) * 2,
        "pair_order": "balanced pseudorandom AB/BA per cell",
        "comparison_design": {
            "causal": "baseline vs v3.8.1 tree plus exact candidate native C source",
            "shipped": "baseline vs exact candidate HEAD",
        },
        "process_isolation": "one fresh process per source/cell/sample; separate throughput and latency workloads",
        "bootstrap": "paired-ratio median, 50000 resamples, percentile 95% CI",
        "acceptance": {
            "insertion_median_gain_50k_100k": ">=1.10x",
            "insertion_gain_bootstrap_95_ci_lower": "strictly >1.05x",
            "lookup_throughput_bootstrap_95_ci_lower": ">=0.97x",
            "operation_latency_bootstrap_95_ci_upper": {"p50": "<=1.05x", "p95": "<=1.05x", "p99": "<=1.10x"},
            "uninstrumented_insertion_and_post_lookup_peak_rss_bootstrap_95_ci_upper": "<=1.05x",
            "worst_pair_bounds": "mandatory for insertion, lookup, p50/p95/p99, and both gated RSS captures",
            "baseline_stability": "CV<=5% and every baseline sample within +/-5% of median for every gated metric",
            "invalid_measurement_policy": "host/thermal/CV invalid cells make performance non-decisional; deterministic failures or clean-cell threshold failures are FAIL",
        },
        "multi_threads": multi_threads,
        "effective_cpu_topology": topology,
        "sources": {
            "baseline": baseline,
            "allocator-only": allocator_only,
            "candidate": candidate,
        },
        "cells": cells,
        "machine": _machine_identity(topology),
    }
    _write_json(output / "protocol.json", protocol)

    build_env = dict(os.environ)
    build_env["STAQTAPP_TDS_BUILD_NATIVE"] = "1"
    build_env.pop("STAQTAPP_TDS_SANITIZE", None)
    build_env["CC"] = _select_build_compiler(build_env)
    build_env.setdefault("PYTHONHASHSEED", "0")
    print(f"[{run_id}] building baseline {baseline['commit'][:12]}", flush=True)
    baseline_build = _build_source(baseline_root, baseline, output, build_env)
    print(f"[{run_id}] building allocator-only ablation", flush=True)
    allocator_only_build = _build_source(
        allocator_only_root,
        allocator_only,
        output,
        build_env,
    )
    print(f"[{run_id}] building candidate {candidate['commit'][:12]}", flush=True)
    candidate_build = _build_source(candidate_root, candidate, output, build_env)
    builds = {
        "baseline": baseline_build,
        "allocator-only": allocator_only_build,
        "candidate": candidate_build,
    }
    sources = {
        "baseline": baseline,
        "allocator-only": allocator_only,
        "candidate": candidate,
    }

    worker_env = dict(os.environ)
    worker_env.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    print(f"[{run_id}] running fixed semantic/durability/recovery sentinels", flush=True)
    sentinels = {
        label: _run_sentinel(
            sources[label],
            builds[label],
            sentinel_path=sentinel_path,
            worker_env=worker_env,
            output_dir=output,
        )
        for label in ("baseline", "allocator-only", "candidate")
    }
    raw_path = output / "raw-samples.jsonl"
    all_records: list[dict[str, Any]] = []
    rng = random.Random(args.seed)
    total_processes = len(cells) * (args.warmup_pairs + args.pairs) * 2
    completed_processes = 0

    with raw_path.open("x", encoding="utf-8") as raw_file:
        for cell_index, cell in enumerate(cells):
            warmup_orders = _balanced_orders(args.warmup_pairs, rng)
            measured_orders = _balanced_orders(args.pairs, rng)
            print(
                f"[{run_id}] cell {cell_index + 1}/{len(cells)} {cell['id']} "
                f"warmup={warmup_orders} measured={measured_orders}",
                flush=True,
            )
            for phase, orders in (("warmup", warmup_orders), ("measured", measured_orders)):
                for pair_index, order in enumerate(orders):
                    lookup_seed = args.seed ^ ((cell_index + 1) << 20) ^ pair_index
                    first_label, second_label = cell["comparison"]
                    labels = (
                        (first_label, second_label)
                        if order == "AB"
                        else (second_label, first_label)
                    )
                    for position, label in enumerate(labels, start=1):
                        started = time.monotonic()
                        record = _run_sample(
                            run_id=run_id,
                            source=sources[label],
                            cell=cell,
                            phase=phase,
                            pair_index=pair_index,
                            order=order,
                            order_position=position,
                            lookup_seed=lookup_seed,
                            build=builds[label],
                            worker_env=worker_env,
                            worker_path=worker_path,
                            topology=topology,
                        )
                        all_records.append(record)
                        raw_file.write(json.dumps(record, sort_keys=True) + "\n")
                        raw_file.flush()
                        os.fsync(raw_file.fileno())
                        completed_processes += 1
                        elapsed = time.monotonic() - started
                        print(
                            f"[{run_id}] {completed_processes}/{total_processes} "
                            f"{cell['id']} {phase} pair={pair_index} {label} "
                            f"wall={elapsed:.2f}s",
                            flush=True,
                        )

    try:
        record_validation = _validate_retained_records(
            all_records,
            protocol=protocol,
            builds=builds,
        )
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        failure = {
            "cell": "global",
            "name": "retained_record_validation",
            "kind": "deterministic",
            "decisional": True,
            "passed": False,
            "observed": f"{type(exc).__name__}: {exc}",
            "required": "exact v2 run/cell/source/build/harness/schedule cardinality and identity before release math",
        }
        summary = {
            "schema": 2,
            "run_id": run_id,
            "status": "FAIL",
            "release_gate_satisfied_on_this_host": False,
            "protocol": protocol,
            "retained_record_validation": {"validated": False, "error": failure["observed"]},
            "raw_samples": {
                "path": raw_path.name,
                "sha256": _sha256(raw_path),
                "records": len(all_records),
            },
            "build_provenance": {
                label: {
                    key: value for key, value in build.items()
                    if key not in {"source_root", "path"}
                }
                for label, build in builds.items()
            },
            "cells": [],
            "sentinels": sentinels,
            "global_checks": [],
            "failed_checks": [failure],
            "nondecisional_performance_checks": [],
        }
        _write_json(output / "summary.json", summary)
        (output / "REPORT.md").write_text(_render_report(summary), encoding="utf-8")
        _write_json(
            output / "MANIFEST.json",
            {
                path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in sorted(output.iterdir())
                if path.is_file()
            },
        )
        temporary.cleanup()
        print(f"[{run_id}] FAIL retained-record-validation evidence={output}", flush=True)
        return 1
    summaries = []
    for cell_index, cell in enumerate(cells):
        records = [record for record in all_records if (
            record["cell"]["id"] == cell["id"]
            and record["cell"]["comparison_id"] == cell["comparison_id"]
        )]
        summaries.append(
            _summarize_cell(
                cell,
                records,
                expected_pairs=args.pairs,
                bootstrap_seed=args.seed ^ ((cell_index + 1) << 8),
            )
        )

    global_checks = _sentinel_global_checks(sentinels, harness_binding, builds)

    def global_check(name: str, passed: bool, observed: Any, required: str) -> None:
        global_checks.append({
            "cell": "global",
            "name": name,
            "passed": bool(passed),
            "observed": observed,
            "required": required,
        })

    for comparison_id, target_label, suffix in (
        ("baseline-vs-allocator-only", "allocator-only", "causal"),
        ("baseline-vs-candidate", "candidate", "shipped"),
    ):
        for source_label in ("baseline", target_label):
            def outcomes(
                cell_id: str,
                *,
                expected_source_label: str = source_label,
                expected_comparison_id: str = comparison_id,
            ) -> list[dict[str, Any]]:
                return [
                    record
                    for record in all_records
                    if record["sample"]["phase"] == "measured"
                    and record["sample"]["source_label"] == expected_source_label
                    and record["cell"]["id"] == cell_id
                    and record["cell"]["comparison_id"] == expected_comparison_id
                ]
            normal_records = outcomes(f"full-tds-{suffix}-normal-100000-t1")
            telemetry_off_records = outcomes(
                f"full-tds-{suffix}-telemetry-off-100000-t1"
            )
            global_check(
                f"independent_telemetry_normal_off_{suffix}_{source_label}",
                _independent_roots_equal(normal_records, telemetry_off_records),
                {
                    "normal_roots": [record["association_sha256"] for record in normal_records],
                    "off_roots": [record["association_sha256"] for record in telemetry_off_records],
                    "normal_snapshots": [record["real_tds_telemetry"] for record in normal_records],
                    "off_snapshots": [record["real_tds_telemetry"] for record in telemetry_off_records],
                },
                "independently executed exact roots equal; NORMAL/OFF public snapshots exact",
            )

    failed_checks = [
        {"cell": cell["cell"]["id"], **check}
        for cell in summaries
        for check in cell["checks"]
        if not check["passed"] and check.get("decisional", True)
    ] + [
        {**check, "kind": check.get("kind", "deterministic"), "decisional": True}
        for check in global_checks
        if not check["passed"]
    ]
    nondecisional_performance = [
        {"cell": cell["cell"]["id"], **check}
        for cell in summaries
        for check in cell["checks"]
        if not check["passed"] and not check.get("decisional", True)
    ]
    status = _decide_status(failed_checks)
    summary = {
        "schema": 2,
        "run_id": run_id,
        "status": status,
        "release_gate_satisfied_on_this_host": status == "PASS",
        "protocol": protocol,
        "retained_record_validation": record_validation,
        "raw_samples": {
            "path": raw_path.name,
            "sha256": _sha256(raw_path),
            "records": len(all_records),
        },
        "build_provenance": {
            label: {
                key: value
                for key, value in build.items()
                if key not in {"source_root", "path"}
            }
            for label, build in builds.items()
        },
        "cells": summaries,
        "sentinels": sentinels,
        "global_checks": global_checks,
        "failed_checks": failed_checks,
        "nondecisional_performance_checks": nondecisional_performance,
    }
    _write_json(output / "summary.json", summary)
    (output / "REPORT.md").write_text(_render_report(summary), encoding="utf-8")
    manifest = {
        path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    _write_json(output / "MANIFEST.json", manifest)

    if args.keep_build_trees:
        retained = output / "built-source-trees"
        shutil.copytree(temp_root, retained)
    temporary.cleanup()
    print(f"[{run_id}] {summary['status']} evidence={output}", flush=True)
    if failed_checks:
        for failure in failed_checks:
            print(
                f"FAIL {failure['cell']}/{failure['name']}: "
                f"{failure['observed']!r} required {failure['required']}",
                flush=True,
            )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

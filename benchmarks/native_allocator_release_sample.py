#!/usr/bin/env python3
"""One process-isolated sample for the v3.8.2 allocator release gate.

This worker deliberately measures exactly one source, cell, and sample.  The
paired AB/BA schedule, warmup exclusion, confidence intervals, and acceptance
decision belong to :mod:`qualify_native_handle_allocator`.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import random
import resource
import subprocess
import sys
import sysconfig
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_BENCHMARK_DIR = Path(__file__).resolve().parent
if str(_BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCHMARK_DIR))

from native_allocator_cpu_control import (  # noqa: E402
    CANONICAL_THROTTLE_KEYS,
    canonical_cpu_stat_delta,
    discover_cpu_control,
    read_cpu_stat,
)

BENCHMARK_ID = "native-handle-allocator-release-sample-v2"
SCRIPT_PATH = Path(__file__).resolve()
VALUE = b"x" * 32
PROC_STAT_PATH = Path("/proc/stat")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command_output(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except Exception:
        return None


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return _command_output(["sysctl", "-n", "machdep.cpu.brand_string"])


def _affinity() -> list[int] | None:
    try:
        return sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return None


def _affinity_topology(cpu_ids: list[int]) -> dict[str, Any]:
    logical: dict[str, dict[str, int]] = {}
    groups: dict[tuple[int, int], list[int]] = {}
    for cpu_id in cpu_ids:
        topology_dir = Path(f"/sys/devices/system/cpu/cpu{cpu_id}/topology")
        try:
            package_id = int((topology_dir / "physical_package_id").read_text().strip())
            core_id = int((topology_dir / "core_id").read_text().strip())
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"physical topology unavailable for admitted CPU {cpu_id}"
            ) from exc
        logical[str(cpu_id)] = {"package_id": package_id, "core_id": core_id}
        groups.setdefault((package_id, core_id), []).append(cpu_id)
    payload = {
        "allowed_cpu_ids": cpu_ids,
        "logical_cpu_topology": logical,
        "physical_core_groups": {
            f"package-{package_id}/core-{core_id}": sorted(siblings)
            for (package_id, core_id), siblings in sorted(groups.items())
        },
        "representative_cpu_ids": sorted(max(siblings) for siblings in groups.values()),
    }
    return {
        **payload,
        "topology_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _set_affinity(specification: str | None) -> list[int]:
    if not specification:
        raise RuntimeError("release samples require an exact CPU affinity")
    cpus = {int(value) for value in specification.split(",") if value.strip()}
    if not cpus:
        raise ValueError("CPU affinity must contain at least one CPU")
    try:
        os.sched_setaffinity(0, cpus)
    except AttributeError as exc:
        raise RuntimeError("sched affinity is required for release samples") from exc
    actual = _affinity()
    if actual != sorted(cpus):
        raise RuntimeError(f"CPU affinity {actual!r}; expected exactly {sorted(cpus)!r}")
    return actual


def _current_cpu_id() -> int | None:
    """Return the calling OS thread's current CPU from procfs."""

    try:
        raw = Path("/proc/thread-self/stat").read_text(encoding="utf-8")
        tail = raw[raw.rfind(")") + 2 :].split()
        return int(tail[36])  # proc(5) field 39, with fields 1-2 removed.
    except Exception:
        return None


def _rss_bytes_from_rusage() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux and the BSDs report KiB; macOS reports bytes.
    return value if sys.platform == "darwin" else value * 1024


def _current_rss_bytes() -> int | None:
    try:
        fields = Path("/proc/self/statm").read_text().split()
        return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:
        return None


def _clock_ticks_per_second() -> int | None:
    try:
        return int(os.sysconf("SC_CLK_TCK"))
    except Exception:
        return None


def _io_counters() -> dict[str, int] | None:
    try:
        result: dict[str, int] = {}
        for line in Path("/proc/self/io").read_text().splitlines():
            key, value = line.split(":", 1)
            result[key.strip()] = int(value.strip())
        return result
    except Exception:
        return None


def _io_delta(
    before: dict[str, int] | None,
    after: dict[str, int] | None,
) -> dict[str, int] | None:
    if before is None or after is None:
        return None
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in sorted(set(before) | set(after))
    }


def _integer_file_map(path: Path) -> dict[str, int] | None:
    try:
        result: dict[str, int] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2:
                try:
                    result[fields[0]] = int(fields[1])
                except ValueError:
                    continue
        return result
    except Exception:
        return None


def _pressure_totals(raw: str | None) -> dict[str, int] | None:
    if raw is None:
        return None
    result: dict[str, int] = {}
    for line in raw.splitlines():
        fields = line.split()
        if not fields:
            continue
        for field in fields[1:]:
            if field.startswith("total="):
                try:
                    result[fields[0]] = int(field.split("=", 1)[1])
                except ValueError:
                    pass
    return result or None


def _cpu_interference_snapshot(cpu_control: dict[str, Any]) -> dict[str, Any]:
    try:
        observed_cpu_control = discover_cpu_control()
        cpu_control_error = None
    except Exception as exc:
        observed_cpu_control = None
        cpu_control_error = f"{type(exc).__name__}: {exc}"
    active_cpu_control = (
        observed_cpu_control
        if isinstance(observed_cpu_control, dict)
        else cpu_control
    )
    affinity = _affinity()
    selected = set(affinity or [])
    per_cpu: dict[str, dict[str, int]] | None = None
    try:
        names = (
            "user",
            "nice",
            "system",
            "idle",
            "iowait",
            "irq",
            "softirq",
            "steal",
            "guest",
            "guest_nice",
        )
        per_cpu = {}
        for line in PROC_STAT_PATH.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if not fields or not fields[0].startswith("cpu") or fields[0] == "cpu":
                continue
            try:
                cpu_id = int(fields[0][3:])
            except ValueError:
                continue
            if selected and cpu_id not in selected:
                continue
            values = [int(value) for value in fields[1:]]
            per_cpu[str(cpu_id)] = {
                name: values[index] if index < len(values) else 0
                for index, name in enumerate(names)
            }
    except Exception:
        per_cpu = None
    pressure = None
    pressure_source = None
    pressure_paths: list[Path] = []
    control_directory = active_cpu_control.get("control_directory")
    if isinstance(control_directory, str) and control_directory:
        pressure_paths.append(Path(control_directory) / "cpu.pressure")
    pressure_paths.append(Path("/proc/pressure/cpu"))
    for pressure_path in dict.fromkeys(pressure_paths):
        try:
            pressure = pressure_path.read_text(encoding="utf-8").strip()
            pressure_source = str(pressure_path)
            break
        except Exception:
            continue
    try:
        cgroup_cpu_stat = (
            read_cpu_stat(active_cpu_control)
            if observed_cpu_control is not None
            else None
        )
        cgroup_stat_error = None
    except Exception as exc:
        cgroup_cpu_stat = None
        cgroup_stat_error = f"{type(exc).__name__}: {exc}"
    return {
        "affinity": affinity,
        "affinity_source": "os.sched_getaffinity(0)",
        "per_cpu_ticks": per_cpu,
        "per_cpu_ticks_source": str(PROC_STAT_PATH),
        "cpu_control": observed_cpu_control,
        "cpu_control_error": cpu_control_error,
        "cgroup_cpu_stat": cgroup_cpu_stat,
        "cgroup_cpu_stat_error": cgroup_stat_error,
        "pressure": pressure,
        "pressure_source": pressure_source,
    }


def _cpu_interference_delta(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    before_cgroup = before.get("cgroup_cpu_stat")
    after_cgroup = after.get("cgroup_cpu_stat")
    cpu_control_before = before.get("cpu_control")
    cpu_control_after = after.get("cpu_control")
    cpu_control = cpu_control_after if isinstance(cpu_control_after, dict) else {}
    cgroup_delta, cgroup_errors = canonical_cpu_stat_delta(
        cpu_control,
        before_cgroup,
        after_cgroup,
    )
    before_cpu = before.get("per_cpu_ticks") or {}
    after_cpu = after.get("per_cpu_ticks") or {}
    per_cpu_delta = {
        cpu: _io_delta(before_cpu.get(cpu), after_cpu.get(cpu))
        for cpu in sorted(set(before_cpu) | set(after_cpu), key=int)
    }
    pressure_delta = _io_delta(
        _pressure_totals(before.get("pressure")),
        _pressure_totals(after.get("pressure")),
    )
    errors: list[str] = []
    selected_before = before.get("affinity")
    selected_after = after.get("affinity")
    if not selected_before or selected_before != selected_after:
        errors.append("selected CPU affinity missing or changed during phase")
    if before.get("affinity_source") != after.get("affinity_source"):
        errors.append("affinity evidence source changed during phase")
    if before.get("per_cpu_ticks_source") != after.get("per_cpu_ticks_source"):
        errors.append("per-CPU tick evidence source changed during phase")
    expected_cpu_keys = {str(cpu) for cpu in (selected_before or [])}
    if set(before_cpu) != expected_cpu_keys or set(after_cpu) != expected_cpu_keys:
        errors.append("per-CPU evidence does not exactly match selected CPU set")
    if cpu_control_before != cpu_control_after:
        errors.append("CPU-control identity changed during phase")
    for snapshot_name, snapshot in (("before", before), ("after", after)):
        if snapshot.get("cpu_control_error"):
            errors.append(
                f"CPU-control discovery failed {snapshot_name} phase: "
                f"{snapshot['cpu_control_error']}"
            )
    errors.extend(cgroup_errors)
    for snapshot_name, snapshot in (("before", before), ("after", after)):
        if snapshot.get("cgroup_cpu_stat_error"):
            errors.append(
                f"CPU cgroup stat read failed {snapshot_name} phase: "
                f"{snapshot['cgroup_cpu_stat_error']}"
            )
    if before.get("pressure_source") != after.get("pressure_source"):
        errors.append("CPU pressure evidence source changed during phase")
    if pressure_delta is not None and any(value < 0 for value in pressure_delta.values()):
        errors.append("negative pressure counter delta")
    for cpu, delta in per_cpu_delta.items():
        if delta is None or any(value < 0 for value in delta.values()):
            errors.append(f"missing or negative per-CPU counter delta for CPU {cpu}")
    return {
        "affinity_before": selected_before,
        "affinity_after": selected_after,
        "affinity_source": after.get("affinity_source"),
        "cgroup_cpu_stat_delta": cgroup_delta,
        "cpu_control_before": cpu_control_before,
        "cpu_control_after": cpu_control_after,
        "cpu_control": cpu_control_after,
        "cgroup_cpu_stat_raw_before": before_cgroup,
        "cgroup_cpu_stat_raw_after": after_cgroup,
        "required_cgroup_throttle_keys": (
            []
            if cpu_control.get("mode") in {"none", "cgroup-v2-root"}
            else list(CANONICAL_THROTTLE_KEYS)
        ),
        "per_cpu_tick_delta": per_cpu_delta,
        "per_cpu_ticks_source": after.get("per_cpu_ticks_source"),
        "pressure_before": before.get("pressure"),
        "pressure_after": after.get("pressure"),
        "pressure_source": after.get("pressure_source"),
        "pressure_total_usec_delta": pressure_delta,
        "clock_ticks_per_second": _clock_ticks_per_second(),
        "evidence_errors": errors,
    }


def _host_snapshot() -> dict[str, Any]:
    temperatures: dict[str, float] = {}
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(path.read_text().strip())
            temperatures[str(path)] = value / 1000.0 if value > 1000.0 else value
        except Exception:
            continue
    try:
        load_average: list[float] | None = list(os.getloadavg())
    except (AttributeError, OSError):
        load_average = None
    return {
        "load_average_1_5_15": load_average,
        "thermal_celsius": temperatures or None,
        "thermal_source": "/sys/class/thermal/thermal_zone*/temp",
        "monotonic_ns": time.monotonic_ns(),
    }


def _partition(total: int, workers: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for worker in range(workers):
        stop = start + (total // workers) + (1 if worker < total % workers else 0)
        ranges.append((start, stop))
        start = stop
    return ranges


def _run_partitioned(
    operation: Callable[[int], None],
    total: int,
    threads: int,
) -> list[int]:
    observed_cpu_ids: set[int] = set()
    lock = threading.Lock()

    def observe_cpu() -> None:
        cpu_id = _current_cpu_id()
        if cpu_id is not None:
            with lock:
                observed_cpu_ids.add(cpu_id)

    if threads == 1:
        observe_cpu()
        for item in range(total):
            operation(item)
        observe_cpu()
        return sorted(observed_cpu_ids)

    def worker(bounds: tuple[int, int]) -> None:
        observe_cpu()
        for item in range(*bounds):
            operation(item)
        observe_cpu()

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, _partition(total, threads)))
    return sorted(observed_cpu_ids)


def _measure_phase(
    operation: Callable[[int], None],
    total: int,
    threads: int,
    cpu_control: dict[str, Any],
) -> dict[str, Any]:
    io_before = _io_counters()
    interference_before = _cpu_interference_snapshot(cpu_control)
    process_started = time.process_time_ns()
    wall_started = time.perf_counter_ns()
    actual_cpu_ids = _run_partitioned(operation, total, threads)
    wall_ns = time.perf_counter_ns() - wall_started
    process_cpu_ns = time.process_time_ns() - process_started
    interference_after = _cpu_interference_snapshot(cpu_control)
    io_after = _io_counters()
    return {
        "operations": total,
        "wall_ns": wall_ns,
        "process_cpu_ns": process_cpu_ns,
        "cpu_utilization_percent": (
            (process_cpu_ns / wall_ns) * 100.0 if wall_ns else None
        ),
        "operations_per_second": total / (wall_ns / 1_000_000_000.0),
        "mean_wall_ns_per_operation": wall_ns / total,
        "actual_cpu_ids": actual_cpu_ids,
        "process_io_delta": _io_delta(io_before, io_after),
        "cpu_interference": _cpu_interference_delta(
            interference_before,
            interference_after,
        ),
    }


def _load_build_provenance(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _diagnostic_semantics(native_module: Any, expected_enabled: bool) -> dict[str, Any]:
    snapshot = dict(native_module.diag_snapshot(event_limit=0))
    if bool(snapshot.get("enabled")) is not expected_enabled:
        raise AssertionError(
            f"diagnostics enabled={snapshot.get('enabled')!r}, expected {expected_enabled}"
        )
    counters = dict(snapshot.get("counters", {}))
    return {
        "enabled": bool(snapshot.get("enabled")),
        "degraded": bool(snapshot.get("degraded")),
        "native_put_calls": int(counters.get("native_put_calls", 0)),
        "native_lookup_calls": int(counters.get("native_lookup_calls", 0)),
        "python_native_transitions": int(counters.get("python_native_transitions", 0)),
        "gil_released_calls": int(counters.get("gil_released_calls", 0)),
        "events_emitted": int(counters.get("events_emitted", 0)),
        "events_dropped": int(counters.get("events_dropped", 0)),
    }


def _semantic_digest(handles: Iterable[int]) -> str:
    digest = hashlib.sha256()
    for handle in handles:
        digest.update(int(handle).to_bytes(8, "little", signed=True))
    return digest.hexdigest()


def _association_digest(
    handles_by_item: list[int],
    keys: list[str],
    *,
    value: bytes | None,
) -> str:
    """Bind every deterministic key to its observed handle and exact value."""
    digest = hashlib.sha256()
    value_hash = hashlib.sha256(value).digest() if value is not None else b""
    for item, (key, handle) in enumerate(zip(keys, handles_by_item, strict=True)):
        encoded_key = key.encode("utf-8")
        digest.update(item.to_bytes(8, "little"))
        digest.update(len(encoded_key).to_bytes(8, "little"))
        digest.update(encoded_key)
        digest.update(int(handle).to_bytes(8, "little", signed=True))
        digest.update(value_hash)
    return digest.hexdigest()


def _sample_slots(total: int, limit: int = 8192) -> tuple[list[int], list[int]]:
    count = min(total, limit)
    positions = (
        list(range(total))
        if count == total
        else [round(index * (total - 1) / (count - 1)) for index in range(count)]
    )
    slots = [-1] * total
    for slot, position in enumerate(positions):
        slots[position] = slot
    return positions, slots


def _telemetry_exact(
    manager: Any,
    mode: str,
    entries: int,
    lookup_operations: int,
) -> dict[str, int | str]:
    snapshot = manager.snapshot(force=True)
    performance = dict(snapshot["performance"])
    storage = dict(snapshot["storage"])
    health = dict(snapshot["health"])
    exact = {
        "write_count": int(performance["write_count"]),
        "read_count": int(performance["read_count"]),
        "lookup_count": int(performance["lookup_count"]),
        "lookup_hits": int(performance["lookup_hits"]),
        "lookup_misses": int(performance["lookup_misses"]),
        "native_backend_ops": int(performance["native_backend_ops"]),
        "gil_released_ops": int(performance["gil_released_ops"]),
        "bytes_raw": int(storage["bytes_raw"]),
        "bytes_stored": int(storage["bytes_stored"]),
        "telemetry_level": str(health["telemetry_level"]),
    }
    expected = (
        {
            "write_count": entries,
            "read_count": lookup_operations,
            "lookup_count": lookup_operations,
            "lookup_hits": lookup_operations,
            "lookup_misses": 0,
            "native_backend_ops": entries + lookup_operations,
            "gil_released_ops": entries + lookup_operations,
            "bytes_raw": entries * 32,
            "bytes_stored": entries * 32,
            "telemetry_level": "normal",
        }
        if mode == "normal"
        else {
            "write_count": 0,
            "read_count": 0,
            "lookup_count": 0,
            "lookup_hits": 0,
            "lookup_misses": 0,
            "native_backend_ops": 0,
            "gil_released_ops": 0,
            "bytes_raw": 0,
            "bytes_stored": 0,
            "telemetry_level": "off",
        }
    )
    if exact != expected:
        raise AssertionError(f"real TDS telemetry changed: {exact!r} != {expected!r}")
    return exact


def _execute_workload(
    args: argparse.Namespace,
    native_module: Any,
    *,
    latency_run: bool,
    cpu_control: dict[str, Any],
) -> dict[str, Any]:
    from staqtapp_tds.telemetry import TelemetryLevel, TelemetryManager

    telemetry_manager = None
    if args.path != "raw":
        telemetry_manager = TelemetryManager(
            level=(TelemetryLevel.NORMAL if args.telemetry == "normal" else TelemetryLevel.OFF)
        )

    keys_text = [f"allocator-{item}" for item in range(args.entries)]
    keys_raw = [key.encode("ascii") for key in keys_text] if args.path == "raw" else None
    lookup_order = list(range(args.entries))
    random.Random(args.lookup_seed).shuffle(lookup_order)
    lookup_operations = max(1_000_000, args.entries)
    put_handles = [-1] * args.entries
    timed_lookup_handles = [-1] * args.entries if args.path == "raw" else None
    expected_content_hash = None

    if args.path == "full-tds":
        from staqtapp_tds import FmtID, TDSFileSystem
        from staqtapp_tds.serializers import content_hash_bytes

        filesystem = TDSFileSystem(telemetry_manager=telemetry_manager)
        index = filesystem.root._entry_index
        initial_stats = index.native_execution_stats()
        expected_content_hash = content_hash_bytes(VALUE)

        def put_base(item: int) -> None:
            entry = filesystem.root.write_entry(
                keys_text[item],
                VALUE,
                fmt_id=FmtID.RAW_BINARY,
                compress=False,
            )
            if entry.name != keys_text[item] or entry.data != VALUE:
                raise AssertionError("full-path write returned the wrong exact entry")

        def lookup_base(position: int) -> None:
            item = lookup_order[position % args.entries]
            if filesystem.root.read_value(keys_text[item]) != VALUE:
                raise AssertionError("full-path lookup returned the wrong value")

    elif args.path == "wrapper":
        from staqtapp_tds.backends.native_index import NativeEntryIndexBackend

        index = NativeEntryIndexBackend(shards=64)
        initial_stats = index.native_execution_stats()

        def put_base(item: int) -> None:
            put_handles[item] = int(index.put(keys_text[item], VALUE))
            telemetry_manager.record_write(
                0,
                raw_size=32,
                stored_size=32,
                backend=args.expected_backend,
            )

        def lookup_base(position: int) -> None:
            item = lookup_order[position % args.entries]
            value = index.get(keys_text[item])
            if value != VALUE:
                raise AssertionError("wrapper lookup returned the wrong value")
            telemetry_manager.record_read(0, hit=True, backend=args.expected_backend)

    else:
        index = native_module.NativeHandleIndex(capacity=4096)
        initial_stats = dict(index.stats())

        def put_base(item: int) -> None:
            put_handles[item] = int(index.put(keys_raw[item]))

        def lookup_base(position: int) -> None:
            item = lookup_order[position % args.entries]
            if position < args.entries:
                timed_lookup_handles[position] = int(index.get_handle(keys_raw[item]))
            else:
                index.get_handle(keys_raw[item])

    initial_backend = str(initial_stats.get("backend", ""))
    if initial_backend != args.expected_backend:
        raise RuntimeError(
            f"exact native backend {args.expected_backend!r} required, got {initial_backend!r}"
        )

    positions, sample_slots = (
        _sample_slots(args.entries) if latency_run else ([], [])
    )
    lookup_positions, lookup_sample_slots = (
        _sample_slots(lookup_operations) if latency_run else ([], [])
    )
    insertion_latency_samples = [0] * len(positions)
    lookup_latency_samples = [0] * len(lookup_positions)

    if latency_run:
        def put_operation(item: int) -> None:
            started = time.perf_counter_ns()
            put_base(item)
            elapsed = time.perf_counter_ns() - started
            slot = sample_slots[item]
            if slot >= 0:
                insertion_latency_samples[slot] = elapsed
    else:
        put_operation = put_base

    rss_before_current = _current_rss_bytes()
    rss_before_peak = _rss_bytes_from_rusage()
    insertion = _measure_phase(put_operation, args.entries, args.threads, cpu_control)
    insertion_current_rss = _current_rss_bytes()
    insertion_peak_rss = _rss_bytes_from_rusage()
    insertion_rss = {
        "current_bytes_immediately_after_insertion": insertion_current_rss,
        "peak_bytes_immediately_after_insertion": max(
            insertion_peak_rss,
            insertion_current_rss or 0,
        ),
        "current_bytes_before_insertion": rss_before_current,
        "peak_bytes_before_insertion": rss_before_peak,
    }

    observed_size = len(index) if args.path != "raw" else int(index.size())
    if observed_size != args.entries:
        raise AssertionError(f"inserted {observed_size}; expected {args.entries}")

    if latency_run:
        def lookup_operation(position: int) -> None:
            started = time.perf_counter_ns()
            lookup_base(position)
            elapsed = time.perf_counter_ns() - started
            slot = lookup_sample_slots[position]
            if slot >= 0:
                lookup_latency_samples[slot] = elapsed
    else:
        lookup_operation = lookup_base

    lookup_measurement = _measure_phase(
        lookup_operation,
        lookup_operations,
        args.threads,
        cpu_control,
    )
    whole_current_rss = _current_rss_bytes()
    whole_peak_rss = _rss_bytes_from_rusage()
    whole_workload_rss = {
        "capture_point": "immediately-after-one-million-or-more-hot-lookups-before-semantic-validation",
        "current_bytes": whole_current_rss,
        "peak_bytes": max(whole_peak_rss, whole_current_rss or 0),
    }

    resolved_handles = [-1] * args.entries
    if args.path == "full-tds":
        for item, key in enumerate(keys_text):
            entry = index.get(key)
            handle = int(index.get_handle(key))
            if (
                entry is None
                or entry.name != key
                or entry.data != VALUE
                or entry.content_hash != expected_content_hash
                or int(entry.raw_size) != 32
                or int(entry.stored_size) != 32
            ):
                raise AssertionError(f"full-path key/entry association changed at {item}")
            resolved_handles[item] = handle
    elif args.path == "wrapper":
        for item, key in enumerate(keys_text):
            resolved = int(index.get_handle(key))
            if resolved != put_handles[item] or index.get_by_handle(resolved) != VALUE:
                raise AssertionError(f"wrapper key/handle/value association changed at {item}")
            resolved_handles[item] = resolved
    else:
        for position, item in enumerate(lookup_order):
            resolved = timed_lookup_handles[position]
            if resolved != put_handles[item]:
                raise AssertionError(f"raw key/handle association changed at {item}")
            resolved_handles[item] = resolved

    if min(resolved_handles) != 1 or max(resolved_handles) != args.entries:
        raise AssertionError("automatic handles did not span the canonical 1..N range")
    if len(set(resolved_handles)) != args.entries:
        raise AssertionError("automatic handles were not unique")
    if args.threads == 1 and resolved_handles != list(range(1, args.entries + 1)):
        raise AssertionError("single-thread key/handle order changed")
    if args.path in {"wrapper", "raw"} and resolved_handles != put_handles:
        raise AssertionError("put-returned handles did not resolve to their exact keys")

    if args.path != "raw":
        telemetry = _telemetry_exact(
            telemetry_manager,
            args.telemetry,
            args.entries,
            lookup_operations,
        )
    else:
        telemetry = {"telemetry_level": "not-applicable-raw-c-control"}

    if args.path == "raw":
        execution_stats = dict(index.stats())
        capacity = int(execution_stats["capacity"])
        next_handle = int(execution_stats["next_handle"])
    else:
        execution_stats = index.native_execution_stats()
        entry_stats = index.stats()
        capacity = int(entry_stats.capacity)
        next_handle = int(entry_stats.next_handle)
    if str(execution_stats.get("backend", "")) != args.expected_backend:
        raise AssertionError("backend identity changed during workload")
    if next_handle != args.entries + 1:
        raise AssertionError("next_handle changed during workload")

    if latency_run and (0 in insertion_latency_samples or 0 in lookup_latency_samples):
        raise AssertionError("dedicated latency sample was incomplete")

    final_current_rss = _current_rss_bytes()
    final_peak_rss = _rss_bytes_from_rusage()
    final_process_rss = {
        "capture_point": "after-untimed-semantic-validation",
        "current_bytes": final_current_rss,
        "peak_bytes": max(final_peak_rss, final_current_rss or 0),
    }

    return {
        "measurements": {
            "insertion": insertion,
            "lookup_control": lookup_measurement,
            "insertion_rss": insertion_rss,
            "whole_workload_rss": whole_workload_rss,
            "final_process_rss": final_process_rss,
        },
        "latency_samples": (
            {
                "method": "every-operation-timed-8192-or-all-evenly-spaced-samples-retained",
                "insertion_sample_positions_sha256": _semantic_digest(positions),
                "lookup_sample_positions_sha256": _semantic_digest(lookup_positions),
                "sample_count": len(positions),
                "lookup_sample_count": len(lookup_positions),
                "insertion_ns": insertion_latency_samples,
                "lookup_ns": lookup_latency_samples,
            }
            if latency_run
            else None
        ),
        "semantic_outcome": {
            "backend": args.expected_backend,
            "size": observed_size,
            "next_handle": next_handle,
            "handle_set_sha256": _semantic_digest(sorted(resolved_handles)),
            "value_bytes": 32 if args.path != "raw" else None,
            "value_sha256": hashlib.sha256(VALUE).hexdigest() if args.path != "raw" else None,
            "content_hash": expected_content_hash if args.path == "full-tds" else None,
            "all_values_exact": True if args.path != "raw" else None,
            "key_handle_value_association_exact": True,
            "key_handle_value_associations_validated": args.entries,
            "single_thread_key_handle_order_exact": args.threads == 1,
            "telemetry_level": args.telemetry if args.path != "raw" else "not-applicable",
        },
        "association_sha256": _association_digest(
            resolved_handles,
            keys_text,
            value=VALUE if args.path != "raw" else None,
        ),
        "telemetry": telemetry,
        "lookup_unique_keys": args.entries,
        "lookup_operations": lookup_operations,
        "capacity": capacity,
        "execution_stats": {
            name: int(execution_stats.get(name, 0))
            for name in ("native_put_calls", "native_lookup_calls", "native_stats_calls")
        },
    }


def _measure_sample(args: argparse.Namespace) -> dict[str, Any]:
    admitted_affinity = _affinity()
    if admitted_affinity is None:
        raise RuntimeError("sched affinity is unavailable")
    expected_admitted = [
        int(value) for value in args.expected_admitted_affinity.split(",") if value
    ]
    if admitted_affinity != expected_admitted:
        raise RuntimeError(
            f"admitted CPU set {admitted_affinity!r}; expected {expected_admitted!r}"
        )
    topology = _affinity_topology(admitted_affinity)
    if topology["topology_sha256"] != args.expected_topology_sha256:
        raise RuntimeError("admitted physical CPU topology differs from protocol")
    try:
        expected_cpu_control = json.loads(args.expected_cpu_control_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid expected CPU-control identity") from exc
    if not isinstance(expected_cpu_control, dict):
        raise RuntimeError("expected CPU-control identity must be an object")
    observed_cpu_control = discover_cpu_control()
    if observed_cpu_control != expected_cpu_control:
        raise RuntimeError("CPU-control mode/source/quota differs from protocol")
    affinity = _set_affinity(args.cpu_affinity)
    host_before = _host_snapshot()
    import staqtapp_tds
    from staqtapp_tds import _native_index

    if staqtapp_tds.__version__ != args.expected_version:
        raise RuntimeError(
            f"TDS version {staqtapp_tds.__version__!r}; expected {args.expected_version!r}"
        )
    diagnostics_enabled = args.diagnostics == "normal"
    _native_index.diag_reset()
    _native_index.diag_set_enabled(diagnostics_enabled)
    throughput = _execute_workload(
        args,
        _native_index,
        latency_run=False,
        cpu_control=observed_cpu_control,
    )
    throughput_diagnostics = _diagnostic_semantics(_native_index, diagnostics_enabled)
    gc.collect()

    _native_index.diag_reset()
    _native_index.diag_set_enabled(diagnostics_enabled)
    latency = _execute_workload(
        args,
        _native_index,
        latency_run=True,
        cpu_control=observed_cpu_control,
    )
    latency_diagnostics = _diagnostic_semantics(_native_index, diagnostics_enabled)

    if throughput["semantic_outcome"] != latency["semantic_outcome"]:
        raise AssertionError("throughput and dedicated-latency semantics differ")
    if throughput["telemetry"] != latency["telemetry"]:
        raise AssertionError("throughput and dedicated-latency telemetry differs")
    if diagnostics_enabled:
        if throughput_diagnostics["degraded"] or latency_diagnostics["degraded"]:
            raise AssertionError("native diagnostics degraded during workload")
        for name, workload, snapshot in (
            ("throughput", throughput, throughput_diagnostics),
            ("dedicated-latency", latency, latency_diagnostics),
        ):
            if snapshot["native_put_calls"] < args.entries:
                raise AssertionError(f"{name} diagnostics lost native put observations")
            expected_native_lookups = (
                workload["lookup_operations"]
                if args.path in {"wrapper", "raw"}
                else args.entries
            )
            if snapshot["native_lookup_calls"] < expected_native_lookups:
                raise AssertionError(f"{name} diagnostics lost native lookup observations")
    else:
        for snapshot in (throughput_diagnostics, latency_diagnostics):
            if any(
                snapshot[name]
                for name in (
                    "native_put_calls",
                    "native_lookup_calls",
                    "python_native_transitions",
                    "gil_released_calls",
                    "events_emitted",
                    "events_dropped",
                )
            ):
                raise AssertionError("diagnostics-off workload changed counters")

    extension_path = Path(_native_index.__file__).resolve()
    package_dir = Path(staqtapp_tds.__file__).resolve().parent
    native_source = package_dir / "_native_index.c"
    wrapper_source = package_dir / "backends" / "native_index.py"
    build_provenance = _load_build_provenance(args.build_provenance)
    if build_provenance is not None:
        if int(build_provenance.get("schema", 0)) != 2:
            raise RuntimeError("runtime rejects non-v2 build provenance")
        expected_source = build_provenance["source"]
        if (
            expected_source["label"] != args.source_label
            or expected_source["commit"] != args.source_commit
            or expected_source["tree"] != args.source_tree
            or build_provenance["native_source_sha256"] != _sha256(native_source)
            or build_provenance["wrapper_source_sha256"] != _sha256(wrapper_source)
            or build_provenance["extension_sha256"] != _sha256(extension_path)
        ):
            raise RuntimeError("runtime source/extension identity differs from build provenance")
    host_after = _host_snapshot()

    return {
        "schema": 2,
        "benchmark_id": BENCHMARK_ID,
        "run_id": args.run_id,
        "sample": {
            "phase": args.phase,
            "pair_index": args.pair_index,
            "order": args.order,
            "order_position": args.order_position,
            "source_label": args.source_label,
        },
        "cell": {
            "id": args.cell_id,
            "comparison_id": args.comparison_id,
            "path": args.path,
            "measurement_role": {
                "full-tds": "release-primary-full-tds-32-byte-raw-binary",
                "wrapper": "allocator-wrapper-control-32-byte-values",
                "raw": "raw-allocator-causal-localization-only",
            }[args.path],
            "entries": args.entries,
            "threads": args.threads,
            "diagnostics": args.diagnostics,
            "telemetry": args.telemetry,
            "qualification_role": args.qualification_role,
            "value_bytes": 32 if args.path != "raw" else None,
            "dataset": (
                "sequential-string-keys-exact-32-byte-raw-binary-v2"
                if args.path != "raw"
                else "sequential-preencoded-keys-allocator-only-v1"
            ),
            "lookup": "one-million-or-more-hot-lookups-over-deterministically-shuffled-existing-keys",
            "lookup_unique_keys": args.entries,
            "lookup_operations": max(1_000_000, args.entries),
            "lookup_seed": args.lookup_seed,
        },
        "source_identity": {
            "label": args.source_label,
            "git_commit": args.source_commit,
            "git_tree": args.source_tree,
            "tds_version": staqtapp_tds.__version__,
            "package_path": str(Path(staqtapp_tds.__file__).resolve()),
            "native_source_sha256": _sha256(native_source),
            "wrapper_source_sha256": _sha256(wrapper_source),
            "extension_path": str(extension_path),
            "extension_sha256": _sha256(extension_path),
            "selected_backend": args.expected_backend,
            "expected_backend": args.expected_backend,
        },
        "harness_identity": {
            "script_path": str(SCRIPT_PATH),
            "script_sha256": _sha256(SCRIPT_PATH),
        },
        "build_provenance": build_provenance,
        "runtime_identity": {
            "python_version": platform.python_version(),
            "python_build": platform.python_build(),
            "python_implementation": platform.python_implementation(),
            "python_executable": sys.executable,
            "python_sysconfig_cc": sysconfig.get_config_var("CC"),
            "python_sysconfig_cflags": sysconfig.get_config_var("CFLAGS"),
            "platform": platform.platform(),
            "operating_system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_model": _cpu_model(),
            "logical_cpu_count": os.cpu_count(),
            "physical_core_count": len(topology["physical_core_groups"]),
            "physical_core_count_scope": "scheduler-admitted-affinity-only",
            "admitted_cpu_affinity_before_pin": admitted_affinity,
            "cpu_affinity": affinity,
            "admitted_topology": topology,
            "cpu_control": observed_cpu_control,
            "storage_device_class": "not-applicable-no-persistence",
        },
        "measurements": throughput["measurements"],
        "dedicated_latency": {
            "measurements": latency["measurements"],
            "operation_samples": latency["latency_samples"],
            "association_sha256": latency["association_sha256"],
            "telemetry": latency["telemetry"],
        },
        "final_stats": {
            "capacity": throughput["capacity"],
            "throughput_execution": throughput["execution_stats"],
            "throughput_diagnostics": throughput_diagnostics,
            "latency_diagnostics": latency_diagnostics,
        },
        "real_tds_telemetry": throughput["telemetry"],
        "semantic_outcome": throughput["semantic_outcome"],
        "association_sha256": throughput["association_sha256"],
        "host_before": host_before,
        "host_after": host_after,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--source-label",
        choices=("baseline", "allocator-only", "candidate"),
        required=True,
    )
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--cell-id", required=True)
    parser.add_argument(
        "--comparison-id",
        choices=("baseline-vs-allocator-only", "baseline-vs-candidate"),
        required=True,
    )
    parser.add_argument("--entries", type=int, required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--path", choices=("full-tds", "wrapper", "raw"), default="full-tds")
    parser.add_argument("--diagnostics", choices=("normal", "off"), default="off")
    parser.add_argument("--telemetry", choices=("normal", "off"), default="normal")
    parser.add_argument("--qualification-role", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--lookup-seed", type=int, required=True)
    parser.add_argument("--phase", choices=("warmup", "measured"), required=True)
    parser.add_argument("--pair-index", type=int, required=True)
    parser.add_argument("--order", choices=("AB", "BA"), required=True)
    parser.add_argument("--order-position", type=int, choices=(1, 2), required=True)
    parser.add_argument("--cpu-affinity")
    parser.add_argument("--expected-admitted-affinity", required=True)
    parser.add_argument("--expected-topology-sha256", required=True)
    parser.add_argument("--expected-cpu-control-json", required=True)
    parser.add_argument("--build-provenance")
    parser.add_argument(
        "--expected-backend",
        default="native-c-swiss-entryindex",
    )
    args = parser.parse_args()
    if args.entries <= 0 or args.threads <= 0:
        parser.error("entries and threads must be positive")
    if args.path == "raw" and args.threads != 1:
        parser.error("raw causal sensitivity is single-thread only")
    if args.path == "raw" and args.telemetry != "off":
        parser.error("raw C causal control has no TDS telemetry and must use off")
    expected_target = (
        "allocator-only"
        if args.comparison_id == "baseline-vs-allocator-only"
        else "candidate"
    )
    if args.source_label not in {"baseline", expected_target}:
        parser.error("source label is not admitted by the immutable comparison id")
    print(json.dumps(_measure_sample(args), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

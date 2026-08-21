#!/usr/bin/env python3
"""Bounded native automatic-handle insertion benchmark.

Build the extension first with::

    STAQTAPP_TDS_BUILD_NATIVE=1 python setup.py build_ext --inplace --force

Run the same command and workload parameters against baseline and candidate
builds.  Each output line is machine-readable JSON and records enough identity
to reject a run that silently fell back to Python.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import sysconfig
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable


BENCHMARK_ID = "native-handle-allocator-v1"
SCRIPT_PATH = Path(__file__).resolve()


def _benchmark_script_sha256() -> str:
    return hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()


def _git_identity(package_dir: Path) -> dict[str, object]:
    try:
        root = subprocess.check_output(
            ["git", "-C", str(package_dir), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        commit = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", root, "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return {
            "commit": commit,
            "dirty": bool(status.strip()),
            "root": root,
        }
    except Exception:
        return {"commit": "unknown", "dirty": None, "root": "unknown"}


def _physical_core_count() -> int | None:
    try:
        pairs: set[tuple[str, str]] = set()
        physical_id = ""
        core_id = ""
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                if physical_id or core_id:
                    pairs.add((physical_id, core_id))
                physical_id = core_id = ""
            elif line.startswith("physical id"):
                physical_id = line.split(":", 1)[1].strip()
            elif line.startswith("core id"):
                core_id = line.split(":", 1)[1].strip()
        if physical_id or core_id:
            pairs.add((physical_id, core_id))
        return len(pairs) or None
    except Exception:
        return None


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _run_single_thread(put: Callable[[int], None], entries: int) -> None:
    for item in range(entries):
        put(item)


def _run_threads(put: Callable[[int], None], entries: int, threads: int) -> None:
    ranges = []
    start = 0
    for worker in range(threads):
        stop = start + (entries // threads) + (1 if worker < entries % threads else 0)
        ranges.append((start, stop))
        start = stop

    def worker(bounds: tuple[int, int]) -> None:
        for item in range(*bounds):
            put(item)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, ranges))


def _measure(
    entries: int,
    threads: int,
    wrapper: bool,
    expected_backend: str,
) -> tuple[float, dict[str, int | str | None]]:
    if wrapper:
        from staqtapp_tds.backends.native_index import NativeEntryIndexBackend

        index = NativeEntryIndexBackend(shards=64)
        keys = [f"allocator-{item}" for item in range(entries)]
        value = b"x" * 32
        put = lambda item: index.put(keys[item], value)
        raw_stats = index.native_execution_stats()
    else:
        from staqtapp_tds import _native_index

        index = _native_index.NativeHandleIndex(capacity=4096)
        keys = [f"allocator-{item}".encode("ascii") for item in range(entries)]
        put = lambda item: index.put(keys[item])
        raw_stats = index.stats()

    backend = str(raw_stats.get("backend", ""))
    if backend != expected_backend:
        raise RuntimeError(
            f"exact native backend {expected_backend!r} required, got {backend!r}"
        )
    started = time.perf_counter_ns()
    if threads == 1:
        _run_single_thread(put, entries)
    else:
        _run_threads(put, entries, threads)
    seconds = (time.perf_counter_ns() - started) / 1_000_000_000.0
    observed_size = len(index) if wrapper else int(index.size())
    if observed_size != entries:
        raise AssertionError(f"inserted {observed_size} entries; expected {entries}")
    if wrapper:
        execution_stats = index.native_execution_stats()
        entry_stats = index.stats()
        final_backend = str(execution_stats.get("backend", ""))
        next_handle = int(entry_stats.next_handle)
        native_put_calls = int(execution_stats.get("native_put_calls", -1))
    else:
        final_stats = dict(index.stats())
        final_backend = str(final_stats.get("backend", ""))
        next_handle_raw = final_stats.get("next_handle")
        next_handle = None if next_handle_raw is None else int(next_handle_raw)
        put_calls_raw = final_stats.get("native_put_calls")
        native_put_calls = None if put_calls_raw is None else int(put_calls_raw)
    if final_backend != expected_backend:
        raise RuntimeError("native backend identity changed during the measurement")
    if next_handle is not None and next_handle != entries + 1:
        raise RuntimeError(
            f"native next_handle changed: got {next_handle}, expected {entries + 1}"
        )
    if native_put_calls is not None and native_put_calls != entries:
        raise RuntimeError(
            "native put-call semantics changed: "
            f"got {native_put_calls}, expected {entries}"
        )
    return seconds, {
        "backend": final_backend,
        "native_put_calls": native_put_calls,
        "next_handle": next_handle,
        "size": observed_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", type=int, nargs="+", default=[10_000, 50_000, 100_000])
    parser.add_argument("--threads", type=int, nargs="+", default=[1])
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--wrapper", action="store_true", help="include Python native-backend orchestration")
    parser.add_argument("--diagnostics", choices=("normal", "off"), default="normal")
    parser.add_argument(
        "--expected-backend",
        default="native-c-swiss-entryindex",
        help="exact C-extension backend string required for every sample",
    )
    parser.add_argument("--label", default="candidate")
    args = parser.parse_args()

    if min(args.entries) <= 0 or min(args.threads) <= 0:
        parser.error("entries and threads must be positive")
    if args.warmups < 0 or args.repetitions < 1:
        parser.error("warmups must be non-negative and repetitions must be positive")
    from staqtapp_tds import _native_index

    if args.diagnostics == "off":
        _native_index.diag_set_enabled(False)

    import staqtapp_tds
    from staqtapp_tds import __version__

    extension_path = Path(_native_index.__file__).resolve()
    package_dir = Path(staqtapp_tds.__file__).resolve().parent
    native_source = package_dir / "_native_index.c"
    wrapper_source = package_dir / "backends" / "native_index.py"

    identity = {
        "benchmark_id": BENCHMARK_ID,
        "benchmark_script_path": str(SCRIPT_PATH),
        "benchmark_script_sha256": _benchmark_script_sha256(),
        "label": args.label,
        "tds_version": __version__,
        "git": _git_identity(package_dir),
        "python": platform.python_version(),
        "python_build": platform.python_build(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "physical_core_count": _physical_core_count(),
        "executable": sys.executable,
        "package_path": str(Path(staqtapp_tds.__file__).resolve()),
        "build_facts": {
            "actual_extension_compiler_recorded": False,
            "CC_override_at_benchmark_time": os.environ.get("CC"),
            "extension_path": str(extension_path),
            "extension_sha256": hashlib.sha256(extension_path.read_bytes()).hexdigest(),
            "python_sysconfig_default_CC": sysconfig.get_config_var("CC"),
            "python_sysconfig_default_CFLAGS": sysconfig.get_config_var("CFLAGS"),
            "source_sha256": {
                "native_index_c": hashlib.sha256(native_source.read_bytes()).hexdigest(),
                "native_index_wrapper": hashlib.sha256(wrapper_source.read_bytes()).hexdigest(),
            },
        },
        "diagnostics": args.diagnostics,
        "path": "native-wrapper" if args.wrapper else "raw-native-index",
        "measurement_role": (
            "primary-wrapper-32-byte-values"
            if args.wrapper
            else "raw-allocator-sensitivity-only"
        ),
        "dataset": (
            "sequential-string-keys-32-byte-values-v1"
            if args.wrapper
            else "sequential-preencoded-keys-allocator-only-v1"
        ),
        "value_bytes": 32 if args.wrapper else None,
        "expected_backend": args.expected_backend,
        "random_seed": None,
    }

    for entries in args.entries:
        for threads in args.threads:
            for _ in range(args.warmups):
                _measure(entries, threads, args.wrapper, args.expected_backend)
            measured = [
                _measure(entries, threads, args.wrapper, args.expected_backend)
                for _ in range(args.repetitions)
            ]
            samples = [sample[0] for sample in measured]
            semantic_outcome = measured[0][1]
            if any(outcome != semantic_outcome for _sample, outcome in measured[1:]):
                raise RuntimeError("native semantic outcome changed across repetitions")
            median = statistics.median(samples)
            result = {
                **identity,
                "entries": entries,
                "threads": threads,
                "warmups": args.warmups,
                "repetitions": args.repetitions,
                "final_stats_semantic_outcome": semantic_outcome,
                "selected_backend": semantic_outcome["backend"],
                "seconds": samples,
                "median_seconds": median,
                "median_entries_per_second": entries / median,
                "p50_seconds": _percentile(samples, 0.50),
                "p95_seconds": _percentile(samples, 0.95),
                "p99_seconds": _percentile(samples, 0.99),
            }
            print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

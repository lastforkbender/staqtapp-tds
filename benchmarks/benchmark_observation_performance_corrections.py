"""Reproducible v3.8.2 JSON/telemetry observation microbenchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

import staqtapp_tds
from staqtapp_tds import RuntimeConfig, TDSFileSystem
from staqtapp_tds.tds_json import (
    codec_stats,
    dumps_canonical,
    loads_fast,
    reset_codec_stats,
)
from staqtapp_tds.telemetry import TelemetryManager


BENCHMARK_ID = "observation-performance-corrections-v1"
SCRIPT_PATH = Path(__file__).resolve()


def _benchmark_script_sha256() -> str:
    return hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()


def _median_ms(operation, repetitions: int) -> float:
    samples = []
    for _ in range(repetitions):
        started = perf_counter()
        operation()
        samples.append((perf_counter() - started) * 1_000.0)
    return median(samples)


def _git_identity() -> dict[str, str | bool | None]:
    package_dir = Path(staqtapp_tds.__file__).resolve().parent
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
        return {"commit": commit, "dirty": bool(status.strip()), "root": root}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unknown", "dirty": None, "root": "unknown"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-iterations", type=int, default=100_000)
    parser.add_argument("--telemetry-iterations", type=int, default=200_000)
    parser.add_argument("--directories", type=int, default=1_000)
    parser.add_argument("--snapshot-repetitions", type=int, default=9)
    parser.add_argument("--index-backend", choices=("auto", "python", "native"), default="python")
    parser.add_argument("--expected-index-backend", default=None)
    parser.add_argument("--label", default="candidate")
    args = parser.parse_args()
    if args.json_iterations < 1:
        parser.error("--json-iterations must be positive")
    if args.telemetry_iterations < 1:
        parser.error("--telemetry-iterations must be positive")
    if args.directories < 1:
        parser.error("--directories must be positive")
    if args.snapshot_repetitions < 1:
        parser.error("--snapshot-repetitions must be positive")
    if args.index_backend == "auto" and not args.expected_index_backend:
        parser.error("--expected-index-backend is required with --index-backend=auto")

    os.environ["STAQTAPP_TDS_INDEX_BACKEND"] = args.index_backend
    payload = {"a": 1, "b": "x", "c": [1, 2, 3]}
    canonical_payload, _backend = dumps_canonical(payload)

    reset_codec_stats()
    started = perf_counter()
    for _ in range(args.json_iterations):
        raw, _backend = dumps_canonical(payload)
    json_dump_seconds = perf_counter() - started
    dump_stats = codec_stats()
    if raw != canonical_payload or dump_stats.dumps_calls != args.json_iterations:
        raise RuntimeError("JSON dump identity or exact count changed")

    reset_codec_stats()
    started = perf_counter()
    for _ in range(args.json_iterations):
        decoded, _backend = loads_fast(canonical_payload)
    json_load_seconds = perf_counter() - started
    load_stats = codec_stats()
    if decoded != payload or load_stats.loads_calls != args.json_iterations:
        raise RuntimeError("JSON load identity or exact count changed")

    telemetry = TelemetryManager(level="engineering")
    started = perf_counter()
    for _ in range(args.telemetry_iterations):
        telemetry.record_read(17, hit=True, backend="python")
    telemetry_seconds = perf_counter() - started
    if (
        telemetry._counters["reads"] != args.telemetry_iterations
        or telemetry._counters["lookups"] != args.telemetry_iterations
        or telemetry._timer_counts["read_ns"] != args.telemetry_iterations
    ):
        raise RuntimeError("telemetry read counters changed")

    config = RuntimeConfig.default().next_generation(telemetry_level="engineering")
    filesystem = TDSFileSystem("benchmark_root", runtime_config=config)
    selected_index_backend = str(filesystem.root._entry_index.backend_name)
    expected_index_backend = args.expected_index_backend or {
        "python": "python-sharded",
        "native": "native-c-swiss",
    }[args.index_backend]
    if selected_index_backend != expected_index_backend:
        raise RuntimeError(
            "filesystem index backend changed: "
            f"selected {selected_index_backend!r}, "
            f"expected {expected_index_backend!r}"
        )
    for index in range(args.directories):
        filesystem.root.mkdir(f"directory-{index}")

    if hasattr(filesystem, "_index_stats_snapshot"):
        index_operation = filesystem._index_stats_snapshot
        index_observation_path = "combined-one-walk"
    else:
        index_operation = lambda: {
            "swiss": filesystem._swiss_stats_snapshot(),
            "radix": filesystem._radix_stats_snapshot(),
        }
        index_observation_path = "legacy-two-walk"
    index_operation()
    index_ms = _median_ms(index_operation, args.snapshot_repetitions)
    engineering_ms = _median_ms(
        lambda: filesystem.telemetry_manager.snapshot(force=True),
        args.snapshot_repetitions,
    )
    filesystem.telemetry_manager.set_level("normal")
    normal_ms = _median_ms(
        lambda: filesystem.telemetry_manager.snapshot(force=True),
        args.snapshot_repetitions,
    )
    print(json.dumps({
        "benchmark_id": BENCHMARK_ID,
        "benchmark_script_path": str(SCRIPT_PATH),
        "benchmark_script_sha256": _benchmark_script_sha256(),
        "directories": args.directories,
        "git": _git_identity(),
        "label": args.label,
        "package_path": str(Path(staqtapp_tds.__file__).resolve()),
        "filesystem_index_backend": {
            "requested": args.index_backend,
            "selected": selected_index_backend,
        },
        "index_observation_path": index_observation_path,
        "json_iterations": args.json_iterations,
        "json_dump_microseconds_per_call": round(
            json_dump_seconds * 1_000_000.0 / args.json_iterations,
            6,
        ),
        "json_load_microseconds_per_call": round(
            json_load_seconds * 1_000_000.0 / args.json_iterations,
            6,
        ),
        "json_stats": {
            "dumps_calls": dump_stats.dumps_calls,
            "loads_calls": load_stats.loads_calls,
            "dump_backend": "orjson" if dump_stats.orjson_writes else "stdlib",
            "load_backend": "simdjson" if load_stats.simdjson_reads else "stdlib",
        },
        "result_identity": {
            "canonical_json": canonical_payload.decode("ascii"),
            "telemetry_lookups": telemetry._counters["lookups"],
            "telemetry_read_timer_count": telemetry._timer_counts["read_ns"],
            "telemetry_reads": telemetry._counters["reads"],
        },
        "telemetry_iterations": args.telemetry_iterations,
        "telemetry_reads_per_second": round(
            args.telemetry_iterations / telemetry_seconds,
            3,
        ),
        "combined_index_observation_median_ms": round(index_ms, 6),
        "engineering_snapshot_median_ms": round(engineering_ms, 6),
        "normal_snapshot_median_ms": round(normal_ms, 6),
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "snapshot_repetitions": args.snapshot_repetitions,
        "tds_version": staqtapp_tds.__version__,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

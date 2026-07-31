#!/usr/bin/env python3
"""Record bounded AArch64 scaling evidence for immutable packed lookups.

The benchmark directly loads the compiled native extension and reports one-,
two-, and four-worker distributions. Hosted-runner evidence is a no-regression
screen only; it is not the named-reference-CPU Phase-2 performance claim.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import platform
from math import ceil
from statistics import median
from struct import calcsize, pack, unpack_from
import subprocess
import sys
from time import perf_counter_ns
from typing import Any, Iterable


FORMAT = "tds.v360.aarch64-frozen-index.performance.v1"


@dataclass(frozen=True)
class SampleSummary:
    samples: int
    p50_lookups_per_second: float
    p95_lookups_per_second: float
    p99_lookups_per_second: float
    minimum_lookups_per_second: float
    maximum_lookups_per_second: float


def canonical_architecture(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"x86_64", "amd64"}:
        return "x86_64"
    if normalized in {"aarch64", "arm64"}:
        return "aarch64"
    return normalized


def load_native_index() -> Any:
    package_dir = Path(__file__).resolve().parents[1] / "src" / "staqtapp_tds"
    candidates: list[Path] = []
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        candidates.extend(package_dir.glob(f"_native_index*{suffix}"))
    candidates = sorted({path.resolve() for path in candidates if path.is_file()})
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one built _native_index extension, found {candidates!r}"
        )
    spec = importlib.util.spec_from_file_location("_native_index", candidates[0])
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {candidates[0]}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_commit() -> str:
    explicit = os.environ.get("GITHUB_SHA", "").strip()
    if explicit:
        return explicit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def pack_keys(keys: Iterable[bytes]) -> tuple[bytes, bytes]:
    materialized = tuple(keys)
    blob = b"".join(materialized)
    offsets = [0]
    total = 0
    for key in materialized:
        total += len(key)
        offsets.append(total)
    return blob, b"".join(pack("<Q", value) for value in offsets)


def run_worker(
    frozen: Any,
    keys: bytes,
    offsets: bytes,
    count: int,
    iterations: int,
) -> int:
    output = bytearray(count * 8)
    start = perf_counter_ns()
    for _ in range(iterations):
        processed = int(frozen.lookup_packed(keys, offsets, output))
        if processed != count:
            raise RuntimeError(f"packed lookup processed {processed}, expected {count}")
    elapsed = perf_counter_ns() - start
    if count:
        first = int(unpack_from("<q", output, 0)[0])
        last = int(unpack_from("<q", output, (count - 1) * 8)[0])
        if first != 1 or last != count:
            raise RuntimeError(
                f"packed result drift: first={first}, last={last}, count={count}"
            )
    return elapsed


def percentile(values: list[float], requested: float) -> float:
    ordered = sorted(values)
    rank = max(1, ceil((requested / 100.0) * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize(rates: list[float]) -> SampleSummary:
    return SampleSummary(
        samples=len(rates),
        p50_lookups_per_second=median(rates),
        p95_lookups_per_second=percentile(rates, 95.0),
        p99_lookups_per_second=percentile(rates, 99.0),
        minimum_lookups_per_second=min(rates),
        maximum_lookups_per_second=max(rates),
    )


def measure_workers(
    frozen: Any,
    keys_blob: bytes,
    offsets: bytes,
    key_count: int,
    iterations: int,
    samples: int,
    workers: int,
) -> SampleSummary:
    lookups_per_worker = key_count * iterations
    rates: list[float] = []
    for _ in range(samples):
        if workers == 1:
            elapsed = run_worker(
                frozen,
                keys_blob,
                offsets,
                key_count,
                iterations,
            )
        else:
            wall_start = perf_counter_ns()
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        run_worker,
                        frozen,
                        keys_blob,
                        offsets,
                        key_count,
                        iterations,
                    )
                    for _worker in range(workers)
                ]
                for future in futures:
                    future.result()
            elapsed = perf_counter_ns() - wall_start
        rates.append(
            (workers * lookups_per_worker) / (elapsed / 1_000_000_000.0)
        )
    return summarize(rates)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-architecture", default="aarch64")
    parser.add_argument("--keys", type=int, default=4096)
    parser.add_argument("--iterations", type=int, default=128)
    parser.add_argument("--samples", type=int, default=9)
    parser.add_argument("--min-two-worker-factor", type=float, default=1.0)
    parser.add_argument("--min-four-worker-factor", type=float, default=1.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if min(args.keys, args.iterations, args.samples) <= 0:
        parser.error("keys, iterations, and samples must be positive")

    architecture = canonical_architecture(platform.machine())
    expected_architecture = canonical_architecture(args.expected_architecture)
    if architecture != expected_architecture:
        raise SystemExit(
            f"architecture mismatch: observed {architecture!r}, expected {expected_architecture!r}"
        )
    if sys.byteorder != "little" or calcsize("P") != 8:
        raise SystemExit("benchmark requires little-endian 64-bit execution")

    native = load_native_index()
    mutable = native.NativeHandleIndex(capacity=max(8192, args.keys * 2))
    key_values = [f"arm-key-{value:08d}".encode("ascii") for value in range(args.keys)]
    for expected, key in enumerate(key_values, start=1):
        actual = int(mutable.put(key))
        if actual != expected:
            raise RuntimeError(f"unexpected handle {actual}, expected {expected}")
    frozen = mutable.freeze()
    keys_blob, offsets = pack_keys(key_values)

    run_worker(frozen, keys_blob, offsets, args.keys, 4)
    one = measure_workers(
        frozen,
        keys_blob,
        offsets,
        args.keys,
        args.iterations,
        args.samples,
        1,
    )
    two = measure_workers(
        frozen,
        keys_blob,
        offsets,
        args.keys,
        args.iterations,
        args.samples,
        2,
    )
    four = measure_workers(
        frozen,
        keys_blob,
        offsets,
        args.keys,
        args.iterations,
        args.samples,
        4,
    )

    two_factor = two.p50_lookups_per_second / one.p50_lookups_per_second
    four_factor = four.p50_lookups_per_second / one.p50_lookups_per_second
    gate_passed = (
        two_factor >= args.min_two_worker_factor
        and four_factor >= args.min_four_worker_factor
    )
    evidence = {
        "format": FORMAT,
        "evidence_class": "shared-runner-no-regression",
        "functional_authority": False,
        "activation_authority": False,
        "source_commit": source_commit(),
        "python": sys.version,
        "platform": platform.platform(),
        "architecture": architecture,
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "keys": args.keys,
        "iterations_per_worker": args.iterations,
        "samples": args.samples,
        "lookups_per_worker_sample": args.keys * args.iterations,
        "frozen_identity": dict(frozen.identity()),
        "one_worker": asdict(one),
        "two_worker_aggregate": asdict(two),
        "four_worker_aggregate": asdict(four),
        "two_worker_factor": two_factor,
        "two_worker_efficiency": two_factor / 2.0,
        "four_worker_factor": four_factor,
        "four_worker_efficiency": four_factor / 4.0,
        "required_two_worker_factor": args.min_two_worker_factor,
        "required_four_worker_factor": args.min_four_worker_factor,
        "gate_passed": gate_passed,
        "named_reference_cpu_claim": False,
    }
    encoded = json.dumps(evidence, sort_keys=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0 if gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

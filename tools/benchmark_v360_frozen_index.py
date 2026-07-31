#!/usr/bin/env python3
"""Produce bounded scaling evidence for the v3.6 frozen packed index.

This tool is performance evidence only.  It cannot qualify, merge, release, or
activate a TDS artifact.  Authoritative gates must bind the output to a named
reference CPU and the exact source/model identities used for the run.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import json
import os
import platform
from math import ceil
from statistics import median
from struct import pack, unpack_from
import sys
from time import perf_counter_ns
from typing import Iterable


@dataclass(frozen=True)
class SampleSummary:
    samples: int
    p50_lookups_per_second: float
    p95_lookups_per_second: float
    p99_lookups_per_second: float
    minimum_lookups_per_second: float
    maximum_lookups_per_second: float


def _pack_keys(keys: Iterable[bytes]) -> tuple[bytes, bytes]:
    materialized = tuple(keys)
    blob = b"".join(materialized)
    offsets = [0]
    total = 0
    for key in materialized:
        total += len(key)
        offsets.append(total)
    return blob, b"".join(pack("<Q", value) for value in offsets)


def _run_worker(frozen, keys: bytes, offsets: bytes, count: int, iterations: int) -> int:
    output = bytearray(count * 8)
    start = perf_counter_ns()
    for _ in range(iterations):
        processed = int(frozen.lookup_packed(keys, offsets, output))
        if processed != count:
            raise RuntimeError(f"packed lookup processed {processed}, expected {count}")
    elapsed = perf_counter_ns() - start
    if count:
        first = unpack_from("<q", output, 0)[0]
        last = unpack_from("<q", output, (count - 1) * 8)[0]
        if first != 1 or last != count:
            raise RuntimeError(
                f"packed lookup parity failed: first={first}, last={last}, count={count}"
            )
    return elapsed


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, ceil((percentile / 100.0) * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _summarize(rates: list[float]) -> SampleSummary:
    return SampleSummary(
        samples=len(rates),
        p50_lookups_per_second=median(rates),
        p95_lookups_per_second=_percentile(rates, 95.0),
        p99_lookups_per_second=_percentile(rates, 99.0),
        minimum_lookups_per_second=min(rates),
        maximum_lookups_per_second=max(rates),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", type=int, default=4096)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--min-two-worker-factor", type=float, default=0.0)
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()
    if args.keys <= 0 or args.iterations <= 0 or args.samples <= 0:
        parser.error("keys, iterations, and samples must be positive")

    from staqtapp_tds import _native_index
    from staqtapp_tds.version import __version__

    mutable = _native_index.NativeHandleIndex(capacity=max(8192, args.keys * 2))
    key_values = [f"key-{value:08d}".encode("ascii") for value in range(args.keys)]
    for expected, key in enumerate(key_values, start=1):
        actual = int(mutable.put(key))
        if actual != expected:
            raise RuntimeError(f"unexpected handle {actual}, expected {expected}")
    frozen = mutable.freeze()
    keys_blob, offsets = _pack_keys(key_values)

    # Warm instruction/data paths before recording distributions.
    _run_worker(frozen, keys_blob, offsets, args.keys, 4)

    one_rates: list[float] = []
    two_rates: list[float] = []
    lookups_per_worker = args.keys * args.iterations
    for _ in range(args.samples):
        one_elapsed = _run_worker(
            frozen,
            keys_blob,
            offsets,
            args.keys,
            args.iterations,
        )
        one_rates.append(lookups_per_worker / (one_elapsed / 1_000_000_000.0))

        with ThreadPoolExecutor(max_workers=2) as executor:
            # Use wall time around both workers, not the sum of worker durations.
            wall_start = perf_counter_ns()
            futures = [
                executor.submit(
                    _run_worker,
                    frozen,
                    keys_blob,
                    offsets,
                    args.keys,
                    args.iterations,
                )
                for _ in range(2)
            ]
            for future in futures:
                future.result()
            wall_elapsed = perf_counter_ns() - wall_start
        two_rates.append((2 * lookups_per_worker) / (wall_elapsed / 1_000_000_000.0))

    one = _summarize(one_rates)
    two = _summarize(two_rates)
    factor = two.p50_lookups_per_second / one.p50_lookups_per_second
    evidence = {
        "format": "tds.v360.frozen-packed-index.performance.v1",
        "functional_authority": False,
        "activation_authority": False,
        "tds_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "keys": args.keys,
        "iterations_per_worker": args.iterations,
        "lookups_per_worker_sample": lookups_per_worker,
        "frozen_identity": frozen.identity(),
        "one_worker": asdict(one),
        "two_worker_aggregate": asdict(two),
        "two_worker_factor": factor,
        "two_worker_efficiency": factor / 2.0,
        "required_factor": args.min_two_worker_factor,
        "gate_passed": factor >= args.min_two_worker_factor,
    }
    encoded = json.dumps(evidence, sort_keys=True, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return 0 if evidence["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Optional parallel test accelerator.

The authoritative release gate is the normal monolithic ``python -m pytest``
execution in CI. This helper partitions test files across subprocesses only to
reduce local wall-clock time; it is not a workaround for process degradation.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _run_shard(index: int, files: list[Path]) -> tuple[int, int, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", "pytest", "-q", "--disable-warnings", *map(str, files)]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return index, completed.returncode, completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()
    if args.shards < 1:
        parser.error("--shards must be at least 1")

    files = sorted((ROOT / "tests").glob("test_*.py"))
    if not files:
        print("release tests failed: no test files found", file=sys.stderr)
        return 2

    shard_count = min(args.shards, len(files))
    shards = [files[index::shard_count] for index in range(shard_count)]
    results: list[tuple[int, int, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=shard_count) as pool:
        futures = [pool.submit(_run_shard, index, shard) for index, shard in enumerate(shards)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    failed = False
    for index, returncode, output in sorted(results):
        print(f"\n=== release test shard {index + 1}/{shard_count} ===")
        print(output.rstrip())
        if returncode != 0:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

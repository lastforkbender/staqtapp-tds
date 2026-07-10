#!/usr/bin/env python3
"""CSV scan reference benchmark for the v3.3.1 performance-shape lane.

This benchmark is intentionally simple and dependency-free. It measures the
Python memoryview scanner over generated CSV bytes and reports rows/second and
MiB/second for local comparison between releases. It is not a release gate by
itself; correctness remains governed by parity tests.
"""

from __future__ import annotations

import argparse
import time

from staqtapp_tds.csv_layer import scan_csv_bytes
from staqtapp_tds.csv_layer.dialect import detect_csv_dialect


def build_payload(rows: int, quoted_every: int) -> bytes:
    lines = ["id,name,note"]
    for idx in range(1, rows + 1):
        if quoted_every > 0 and idx % quoted_every == 0:
            lines.append(f'{idx},name-{idx},"quoted line {idx} with, delimiter and ""quote"""')
        else:
            lines.append(f"{idx},name-{idx},plain note {idx}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the TDS CSV memoryview scanner")
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--quoted-every", type=int, default=17)
    parser.add_argument("--chunk-size", type=int, default=8192)
    parser.add_argument("--loops", type=int, default=5)
    args = parser.parse_args()

    raw = build_payload(args.rows, args.quoted_every)
    dialect = detect_csv_dialect(raw[:65536].decode("utf-8"))
    best = float("inf")
    last_profile = None
    for _ in range(args.loops):
        start = time.perf_counter()
        last_profile = scan_csv_bytes(raw, dialect, chunk_size=args.chunk_size)
        elapsed = time.perf_counter() - start
        best = min(best, elapsed)

    assert last_profile is not None
    mib = len(raw) / (1024 * 1024)
    print(f"rows={last_profile.row_count}")
    print(f"bytes={last_profile.raw_size}")
    print(f"best_seconds={best:.6f}")
    print(f"rows_per_second={last_profile.row_count / best:.2f}")
    print(f"mib_per_second={mib / best:.2f}")
    print(f"scanner={last_profile.scanner}")
    print(f"chunk_size={last_profile.chunk_size}")
    print(f"max_record_span={last_profile.max_record_span}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

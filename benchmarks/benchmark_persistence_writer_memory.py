#!/usr/bin/env python3
"""Reproducible bounded-memory persistence writer benchmark.

Run the same script against the v3.8.1 and candidate source trees. The traced
region contains persistence flush only; the immutable payload and filesystem
fixture are constructed before measurement.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

import staqtapp_tds
from staqtapp_tds import FmtID, TDSFileSystem
from staqtapp_tds.tds_persistence import TDSPersistence, TDSReader


BENCHMARK_ID = "persistence-writer-memory-v1"
SCRIPT_PATH = Path(__file__).resolve()
_FILE_HEADER = struct.Struct(">4sIQQQQI")


def _benchmark_script_sha256() -> str:
    return hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()


def _git_identity() -> dict[str, Any]:
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
        return {
            "commit": commit,
            "dirty": bool(status.strip()),
            "root": root,
        }
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unknown", "dirty": None, "root": "unknown"}


def _assert_fs_index_backend(filesystem: TDSFileSystem, expected: str) -> str:
    selected = str(filesystem.root._entry_index.backend_name)
    if selected != expected:
        raise RuntimeError(
            "filesystem index backend changed: "
            f"selected {selected!r}, expected {expected!r}"
        )
    return selected


def _tds_artifact_identity(tds_path: Path) -> dict[str, Any]:
    """Return exact and timestamp-normalized identities for one TDS artifact."""

    raw = tds_path.read_bytes()
    if len(raw) < _FILE_HEADER.size:
        raise RuntimeError("persistence benchmark emitted a truncated TDS file")
    magic, version, slots, index_offset, data_offset, _timestamp, _crc = (
        _FILE_HEADER.unpack_from(raw)
    )
    if magic != b"TDSX" or not data_offset <= index_offset <= len(raw):
        raise RuntimeError("persistence benchmark emitted an invalid TDS file")
    normalized = bytearray(raw)
    # The snapshot timestamp and its CRC are the only intentionally variable
    # bytes in this one-slot data-file workload.
    normalized[32:44] = b"\x00" * 12
    sidecar_path = tds_path.with_suffix(".tds.meta")
    return {
        "file_bytes": len(raw),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "normalized_file_sha256": hashlib.sha256(normalized).hexdigest(),
        "payload_region_sha256": hashlib.sha256(
            raw[data_offset:index_offset]
        ).hexdigest(),
        "sidecar_sha256": hashlib.sha256(sidecar_path.read_bytes()).hexdigest(),
        "slot_count": slots,
        "tds_version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-mib", type=int, default=64)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--label", default="candidate")
    parser.add_argument(
        "--fs-index-backend",
        choices=("python", "native"),
        default="python",
        help="force the EntryIndex implementation used by the source filesystem",
    )
    parser.add_argument(
        "--expected-fs-index-backend",
        default=None,
        help="exact backend_name required after selection",
    )
    args = parser.parse_args()
    if args.payload_mib < 1 or args.repetitions < 1:
        parser.error("--payload-mib and --repetitions must be positive")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")

    os.environ["STAQTAPP_TDS_INDEX_BACKEND"] = args.fs_index_backend
    expected_fs_index_backend = args.expected_fs_index_backend or {
        "python": "python-sharded",
        "native": "native-c-swiss",
    }[args.fs_index_backend]

    payload = b"x" * (args.payload_mib << 20)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    filesystem = TDSFileSystem("tds_root")
    selected_fs_index_backend = _assert_fs_index_backend(
        filesystem,
        expected_fs_index_backend,
    )
    filesystem.root.write_entry(
        "payload",
        payload,
        fmt_id=FmtID.RAW_BINARY,
        compress=False,
    )

    peak_samples: list[int] = []
    elapsed_samples: list[int] = []
    artifact_samples: list[dict[str, Any]] = []
    normalized_file_sha256: str | None = None
    with tempfile.TemporaryDirectory(prefix="tds-persistence-memory-") as root:
        for ordinal in range(args.warmups + args.repetitions):
            mount = Path(root) / f"run-{ordinal}"
            gc.collect()
            tracemalloc.start()
            started = time.perf_counter_ns()
            try:
                TDSPersistence(mount).flush(filesystem, parallel_nodes=False)
                elapsed = time.perf_counter_ns() - started
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            tds_path = mount / "tds_root.tds"
            artifact_identity = _tds_artifact_identity(tds_path)
            if artifact_identity["payload_region_sha256"] != payload_sha256:
                raise RuntimeError("on-disk TDS payload region identity changed")
            current_normalized = str(
                artifact_identity["normalized_file_sha256"]
            )
            if normalized_file_sha256 is None:
                normalized_file_sha256 = current_normalized
            elif current_normalized != normalized_file_sha256:
                raise RuntimeError("normalized on-disk TDS file identity changed")

            with TDSReader(tds_path) as reader:
                restored = reader.read_raw("/tds_root/payload")
            restored_sha256 = hashlib.sha256(restored).hexdigest()
            if restored_sha256 != payload_sha256:
                raise RuntimeError("persistence payload identity changed")
            if ordinal >= args.warmups:
                peak_samples.append(peak)
                elapsed_samples.append(elapsed)
                artifact_samples.append(
                    {**artifact_identity, "restored_payload_sha256": restored_sha256}
                )

    if normalized_file_sha256 is None:
        raise RuntimeError("persistence benchmark produced no artifact identity")

    print(
        json.dumps(
            {
                "artifact_samples": artifact_samples,
                "benchmark": BENCHMARK_ID,
                "benchmark_id": BENCHMARK_ID,
                "benchmark_script_path": str(SCRIPT_PATH),
                "benchmark_script_sha256": _benchmark_script_sha256(),
                "elapsed_nanoseconds": elapsed_samples,
                "filesystem_index_backend": {
                    "requested": args.fs_index_backend,
                    "selected": selected_fs_index_backend,
                },
                "git": _git_identity(),
                "label": args.label,
                "median_elapsed_nanoseconds": statistics.median(elapsed_samples),
                "median_peak_bytes": statistics.median(peak_samples),
                "package_path": str(Path(staqtapp_tds.__file__).resolve()),
                "payload_bytes": len(payload),
                "payload_sha256": payload_sha256,
                "peak_bytes": peak_samples,
                "platform": platform.platform(),
                "python_executable": sys.executable,
                "python_version": platform.python_version(),
                "repetitions": args.repetitions,
                "result_identity": {
                    "normalized_tds_file_sha256": normalized_file_sha256,
                    "on_disk_payload_region_sha256": payload_sha256,
                    "restored_payload_sha256": payload_sha256,
                },
                "tds_version": staqtapp_tds.__version__,
                "warmups": args.warmups,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reproducible CSV and Generation Authority correction benchmark.

Run this same file with ``PYTHONPATH`` pointed at the checkout under test::

    PYTHONPATH=/path/to/staqtapp-tds/src \
      python benchmarks/benchmark_csv_generation_performance_corrections.py

The workload uses public APIs that are shared by TDS v3.8.1 and the candidate.
It emits exactly one JSON record so baseline and candidate runs can be retained
and compared without parsing human-readable progress output.
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
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable, TypeVar

import staqtapp_tds
from staqtapp_tds import TDSFileSystem
from staqtapp_tds.csv_layer import import_csv_bytes, materialize_csv_scan_artifacts
from staqtapp_tds.generation import (
    AtomicGenerationStore,
    GenerationManifest,
    GenerationPayload,
    build_csv_generation_candidate,
    bytes_root,
    open_csv_generation,
    publish_csv_generation,
)
from staqtapp_tds.generation.csv import pack_row_offsets


T = TypeVar("T")
BENCHMARK_ID = "csv-generation-performance-corrections-v1"
SCRIPT_PATH = Path(__file__).resolve()


def _benchmark_script_sha256() -> str:
    return hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()


def _dataset(data_rows: int) -> tuple[bytes, tuple[int, ...]]:
    """Build deterministic UTF-8 CSV with mixed endings and quoted newlines."""

    rows = [b"id,name,note\r\n"]
    for index in range(data_rows):
        if index % 17 == 0:
            rows.append(
                (
                    f'{index},"user {index}","line {index} alpha\r\n'
                    f'line {index} beta"\r\n'
                ).encode("utf-8")
            )
        else:
            rows.append(
                f'{index},"user {index}","payload {index:08d}"\n'.encode("utf-8")
            )
    offsets: list[int] = []
    position = 0
    for row in rows:
        offsets.append(position)
        position += len(row)
    return b"".join(rows), tuple(offsets)


def _git_identity() -> dict[str, Any]:
    """Identify the checkout from which the imported package was loaded."""

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


def _assert_fs_index_backend(filesystem: TDSFileSystem, expected: str) -> str:
    selected = str(filesystem.root._entry_index.backend_name)
    if selected != expected:
        raise RuntimeError(
            "filesystem index backend changed: "
            f"selected {selected!r}, expected {expected!r}"
        )
    return selected


def _median_ms(
    call: Callable[[], T],
    validate: Callable[[T], None],
    *,
    iterations: int,
    warmups: int,
) -> float:
    samples: list[int] = []
    for ordinal in range(warmups + iterations):
        gc.collect()
        started = time.perf_counter_ns()
        result = call()
        elapsed = time.perf_counter_ns() - started
        validate(result)
        if ordinal >= warmups:
            samples.append(elapsed)
    return statistics.median(samples) / 1_000_000.0


def _median_peak_bytes(
    call: Callable[[], T],
    validate: Callable[[T], None],
    *,
    iterations: int,
    warmups: int,
) -> int:
    for _ in range(warmups):
        validate(call())
    samples: list[int] = []
    for _ in range(iterations):
        gc.collect()
        tracemalloc.start()
        try:
            result = call()
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        validate(result)
        samples.append(peak)
    return int(statistics.median(samples))


def _scan_materialization_median_ms(
    source: bytes,
    *,
    chunk_bytes: int,
    expected_fs_index_backend: str,
    iterations: int,
    warmups: int,
) -> float:
    """Exclude CSV import setup while timing fresh artifact materialization."""

    samples: list[int] = []
    for ordinal in range(warmups + iterations):
        filesystem = TDSFileSystem("benchmark")
        _assert_fs_index_backend(filesystem, expected_fs_index_backend)
        manifest = import_csv_bytes(
            filesystem.root,
            source,
            source_name="performance-corrections.csv",
        )
        gc.collect()
        started = time.perf_counter_ns()
        report = materialize_csv_scan_artifacts(
            filesystem.root,
            manifest.csv_id,
            include_row_anchors=True,
            chunk_size=chunk_bytes,
        )
        elapsed = time.perf_counter_ns() - started
        if not report.ok or not report.wrote_row_anchor_profile:
            raise RuntimeError(f"CSV scan materialization failed: {report.errors!r}")
        if ordinal >= warmups:
            samples.append(elapsed)
    return statistics.median(samples) / 1_000_000.0


def _import_median_ms(
    source: bytes,
    *,
    expected_fs_index_backend: str,
    iterations: int,
    warmups: int,
) -> float:
    def import_once() -> tuple[Any, TDSFileSystem]:
        filesystem = TDSFileSystem("benchmark")
        _assert_fs_index_backend(filesystem, expected_fs_index_backend)
        manifest = import_csv_bytes(
            filesystem.root,
            source,
            source_name="performance-corrections.csv",
        )
        return manifest, filesystem

    expected_hash = hashlib.sha256(source).hexdigest()

    def validate(result: tuple[Any, TDSFileSystem]) -> None:
        manifest, filesystem = result
        stored = filesystem.root.read_value(manifest.artifact_keys["raw"])
        if manifest.raw_sha256 != expected_hash:
            raise RuntimeError("CSV import source identity changed")
        if not isinstance(stored, str) or stored.encode(manifest.encoding) != source:
            raise RuntimeError("CSV import changed authoritative bytes")

    return _median_ms(
        import_once,
        validate,
        iterations=iterations,
        warmups=warmups,
    )


def _manifest(payload_count: int) -> GenerationManifest:
    payloads = tuple(
        GenerationPayload(
            name=f"payload.{ordinal:08d}",
            media_type="application/octet-stream",
            size=32,
            content_root=bytes_root(f"payload-{ordinal:08d}".encode("ascii")),
            authoritative=ordinal == 0,
        )
        for ordinal in range(payload_count)
    )
    return GenerationManifest(
        namespace="benchmark:manifest-roots",
        parent_generation_root=None,
        payloads=payloads,
        metadata=(("benchmark", "csv-generation-performance-v1"),),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--iterations", type=int, default=9)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--scan-chunk-bytes", type=int, default=16 << 10)
    parser.add_argument("--generation-chunk-bytes", type=int, default=16 << 10)
    parser.add_argument("--manifest-payloads", type=int, default=4096)
    parser.add_argument("--root-reads", type=int, default=8)
    parser.add_argument("--label", default="candidate")
    parser.add_argument(
        "--fs-index-backend",
        choices=("python", "native"),
        default="python",
        help="force the EntryIndex implementation used by every CSV filesystem",
    )
    parser.add_argument(
        "--expected-fs-index-backend",
        default=None,
        help="exact backend_name required after selection",
    )
    args = parser.parse_args()

    if args.rows < 1:
        parser.error("--rows must be positive")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")
    if args.scan_chunk_bytes < 1 or args.generation_chunk_bytes < 1:
        parser.error("chunk sizes must be positive")
    if not 1 <= args.manifest_payloads <= 4096:
        parser.error("--manifest-payloads must be between 1 and 4096")
    if args.root_reads < 1:
        parser.error("--root-reads must be positive")

    os.environ["STAQTAPP_TDS_INDEX_BACKEND"] = args.fs_index_backend
    expected_fs_index_backend = args.expected_fs_index_backend or {
        "python": "python-sharded",
        "native": "native-c-swiss",
    }[args.fs_index_backend]
    backend_probe = TDSFileSystem("benchmark-backend-probe")
    selected_fs_index_backend = _assert_fs_index_backend(
        backend_probe,
        expected_fs_index_backend,
    )

    source, offsets = _dataset(args.rows)
    source_root = bytes_root(source)
    generation_chunks = (
        len(source) + args.generation_chunk_bytes - 1
    ) // args.generation_chunk_bytes
    if generation_chunks + 7 > 4096:
        parser.error(
            "generation chunk count plus fixed CSV payloads exceeds the "
            "Generation Authority payload limit"
        )

    def pack_offsets() -> bytes:
        return pack_row_offsets(
            offsets,
            source_size=len(source),
            source_root=source_root,
        )

    expected_packed = (
        struct.pack(
            ">8sHHIQQ32s",
            b"TDSCRO1\x00",
            1,
            0,
            8,
            len(offsets),
            len(source),
            bytes.fromhex(source_root.split(":", 1)[1]),
        )
        + struct.pack(f">{len(offsets)}Q", *offsets)
    )

    def validate_packed(payload: bytes) -> None:
        if payload != expected_packed:
            raise RuntimeError("packed CSV row-offset bytes changed")

    manifest = _manifest(args.manifest_payloads)
    expected_roots = (manifest.manifest_root, manifest.generation_root)

    def repeated_roots() -> tuple[str, str]:
        roots = expected_roots
        for _ in range(args.root_reads):
            roots = (manifest.manifest_root, manifest.generation_root)
        return roots

    def validate_roots(roots: tuple[str, str]) -> None:
        if roots != expected_roots:
            raise RuntimeError("immutable generation roots changed")

    row_offsets_ms = _median_ms(
        pack_offsets,
        validate_packed,
        iterations=args.iterations,
        warmups=args.warmups,
    )
    row_offsets_peak_bytes = _median_peak_bytes(
        pack_offsets,
        validate_packed,
        iterations=args.iterations,
        warmups=args.warmups,
    )
    import_ms = _import_median_ms(
        source,
        expected_fs_index_backend=expected_fs_index_backend,
        iterations=args.iterations,
        warmups=args.warmups,
    )
    scan_materialization_ms = _scan_materialization_median_ms(
        source,
        chunk_bytes=args.scan_chunk_bytes,
        expected_fs_index_backend=expected_fs_index_backend,
        iterations=args.iterations,
        warmups=args.warmups,
    )
    manifest_roots_ms = _median_ms(
        repeated_roots,
        validate_roots,
        iterations=args.iterations,
        warmups=args.warmups,
    )

    with tempfile.TemporaryDirectory(prefix="tds-csv-generation-benchmark-") as root:
        store = AtomicGenerationStore(Path(root) / "authority")
        namespace = "benchmark:chunked-csv-open-load"
        candidate = build_csv_generation_candidate(
            store,
            namespace=namespace,
            source=source,
            closure_root=bytes_root(b"benchmark-closure"),
            evidence_root=bytes_root(b"benchmark-evidence"),
            chunk_bytes=args.generation_chunk_bytes,
            oracle_block_bytes=args.scan_chunk_bytes,
            metadata={"benchmark": "csv-generation-performance-v1"},
        )
        publication = publish_csv_generation(
            store,
            candidate,
            expected_head_root=None,
        )
        if publication.manifest.generation_root != candidate.generation_root:
            raise RuntimeError("CSV generation publication returned another generation")

        expected_open = (
            source,
            offsets,
            generation_chunks,
            candidate.generation_root,
        )

        def open_and_load() -> tuple[bytes, tuple[int, ...], int, str]:
            with open_csv_generation(store, namespace) as lease:
                return (
                    lease.read_source(),
                    lease.row_offsets,
                    lease.binding.chunk_count,
                    lease.generation_root,
                )

        def validate_open(result: tuple[bytes, tuple[int, ...], int, str]) -> None:
            if result != expected_open:
                raise RuntimeError("chunked CSV generation open/load changed data")

        generation_open_load_ms = _median_ms(
            open_and_load,
            validate_open,
            iterations=args.iterations,
            warmups=args.warmups,
        )

    record = {
        "benchmark_id": BENCHMARK_ID,
        "benchmark_script_path": str(SCRIPT_PATH),
        "benchmark_script_sha256": _benchmark_script_sha256(),
        "git": _git_identity(),
        "label": args.label,
        "package_path": str(Path(staqtapp_tds.__file__).resolve()),
        "version": staqtapp_tds.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dataset": {
            "id": "deterministic-mixed-line-ending-csv-v1",
            "data_rows": args.rows,
            "logical_rows": len(offsets),
            "source_bytes": len(source),
            "scan_chunk_bytes": args.scan_chunk_bytes,
            "generation_chunk_bytes": args.generation_chunk_bytes,
            "generation_chunks": generation_chunks,
            "manifest_payloads": args.manifest_payloads,
            "manifest_root_reads_per_sample": args.root_reads,
        },
        "iterations": args.iterations,
        "warmups": args.warmups,
        "filesystem_index_backend": {
            "requested": args.fs_index_backend,
            "selected": selected_fs_index_backend,
        },
        "peak_bytes": {
            "csv_row_offset_pack": row_offsets_peak_bytes,
        },
        "result_identity": {
            "generation_root": candidate.generation_root,
            "manifest_generation_root": expected_roots[1],
            "manifest_root": expected_roots[0],
            "packed_row_offsets_sha256": hashlib.sha256(expected_packed).hexdigest(),
            "source_sha256": hashlib.sha256(source).hexdigest(),
        },
        "median_ms": {
            "csv_import": round(import_ms, 6),
            "csv_row_offset_pack": round(row_offsets_ms, 6),
            "csv_scan_artifact_materialization_with_anchors": round(
                scan_materialization_ms,
                6,
            ),
            "immutable_generation_manifest_repeated_roots": round(
                manifest_roots_ms,
                6,
            ),
            "chunked_csv_generation_open_load": round(
                generation_open_load_ms,
                6,
            ),
        },
    }
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

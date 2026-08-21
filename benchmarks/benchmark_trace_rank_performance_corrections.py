#!/usr/bin/env python3
"""Reproducible Trace Rank admission and materialization benchmark.

Run from the repository root with the checkout under test on ``PYTHONPATH``::

    PYTHONPATH=src python benchmarks/benchmark_trace_rank_performance_corrections.py

The result is one JSON record.  ``materialize_fail_closed`` deliberately uses
the public untrusted-input API; ``materialize_admitted`` uses the proof-bound
seam and therefore measures the whole-graph validation removed from the hot
path without weakening the public API.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import staqtapp_tds
from staqtapp_tds.trace_rank import (
    FeatureBlock,
    ImmutableSourceBinding,
    PackedWaypointGraph,
    ProvenanceRecord,
    VerifiedPackedGraph,
    Waypoint,
)


BENCHMARK_ID = "trace-rank-performance-corrections-v1"
SCRIPT_PATH = Path(__file__).resolve()


def _benchmark_script_sha256() -> str:
    return hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("ascii")).hexdigest()


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


def _workload(
    row_count: int,
) -> tuple[
    PackedWaypointGraph,
    tuple[ImmutableSourceBinding, ...],
    VerifiedPackedGraph,
]:
    rows = tuple(f"row-{index:08d}\n".encode("ascii") for index in range(row_count))
    offsets = [0]
    for row in rows:
        offsets.append(offsets[-1] + len(row))
    source = ImmutableSourceBinding(
        _root(f"benchmark-generation-{row_count}"),
        b"".join(rows),
        tuple(offsets),
    )
    graph = PackedWaypointGraph.build(
        server_namespace_root=_root("benchmark-server"),
        feature_schema_root=_root("benchmark-feature-schema"),
        hard_mask_universe=1,
        source_bindings=(source,),
        provenance=(
            ProvenanceRecord(
                _root("benchmark-provenance"),
                generation_index=0,
                policy_mask=1,
            ),
        ),
        feature_blocks=(FeatureBlock((1,), missing_mask=0),),
        waypoints=tuple(
            Waypoint(
                generation_index=0,
                causal_sequence=index + 1,
                predecessor_index=index - 1,
                byte_start=offsets[index],
                byte_end=offsets[index + 1],
                row_start=index,
                row_end=index + 1,
                feature_index=0,
                provenance_index=0,
            )
            for index in range(row_count)
        ),
        edge_offsets=(0,) * (row_count + 1),
        edges=(),
    )
    sources = (source,)
    verified = VerifiedPackedGraph.from_graph(
        graph,
        sources,
        source_evidence_roots=(_root("benchmark-source-evidence"),),
        edge_catalog_root=_root("benchmark-edge-catalog"),
    )
    return graph, sources, verified


def _measure(
    operation: Callable[[], Any],
    identity: Callable[[Any], Any],
    expected: Any,
    *,
    repetitions: int,
    warmups: int,
) -> dict[str, Any]:
    for _ in range(warmups):
        if identity(operation()) != expected:
            raise RuntimeError("benchmark result identity changed during warmup")
    samples: list[int] = []
    for _ in range(repetitions):
        gc.collect()
        started = time.perf_counter_ns()
        result = operation()
        samples.append(time.perf_counter_ns() - started)
        if identity(result) != expected:
            raise RuntimeError("benchmark result identity changed")
    median = statistics.median(samples)
    return {
        "median_nanoseconds": round(median, 3),
        "samples_nanoseconds": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_600)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--label", default="candidate")
    args = parser.parse_args()
    if args.rows < 1 or args.repetitions < 1:
        parser.error("--rows and --repetitions must be positive")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")

    graph, sources, verified = _workload(args.rows)
    evidence = (_root("benchmark-source-evidence"),)
    edge_catalog = _root("benchmark-edge-catalog")
    expected_bytes = len(sources[0].source_bytes)
    expected_materialization_sha256 = hashlib.sha256(
        sources[0].source_bytes
    ).hexdigest()
    public_materialization_sha256 = hashlib.sha256(
        b"".join(
            graph.materialize_waypoint(index, sources)
            for index in range(args.rows)
        )
    ).hexdigest()
    admitted_materialization_sha256 = None
    if hasattr(verified, "materialize_waypoint"):
        admitted_materialization_sha256 = hashlib.sha256(
            b"".join(
                verified.materialize_waypoint(index) for index in range(args.rows)
            )
        ).hexdigest()
    observed_materialization_digests = {public_materialization_sha256}
    if admitted_materialization_sha256 is not None:
        observed_materialization_digests.add(admitted_materialization_sha256)
    if observed_materialization_digests != {expected_materialization_sha256}:
        raise RuntimeError("materialized waypoint bytes changed")

    def admit_from_graph() -> VerifiedPackedGraph:
        return VerifiedPackedGraph.from_graph(
            graph,
            sources,
            source_evidence_roots=evidence,
            edge_catalog_root=edge_catalog,
        )

    def admit_from_bytes() -> VerifiedPackedGraph:
        return VerifiedPackedGraph.from_bytes(
            verified.packed_bytes,
            sources,
            source_evidence_roots=evidence,
            edge_catalog_root=edge_catalog,
        )

    def materialize_fail_closed() -> int:
        return sum(
            len(graph.materialize_waypoint(index, sources))
            for index in range(args.rows)
        )

    def materialize_admitted() -> int:
        return sum(
            len(verified.materialize_waypoint(index)) for index in range(args.rows)
        )

    measurements: dict[str, Any] = {
        "admit_from_bytes": _measure(
            admit_from_bytes,
            lambda result: result.graph_root,
            verified.graph_root,
            repetitions=args.repetitions,
            warmups=args.warmups,
        ),
        "admit_from_graph": _measure(
            admit_from_graph,
            lambda result: result.graph_root,
            verified.graph_root,
            repetitions=args.repetitions,
            warmups=args.warmups,
        ),
        "materialize_fail_closed": _measure(
            materialize_fail_closed,
            lambda result: result,
            expected_bytes,
            repetitions=args.repetitions,
            warmups=args.warmups,
        ),
    }
    if hasattr(verified, "materialize_waypoint"):
        measurements["materialize_admitted"] = _measure(
            materialize_admitted,
            lambda result: result,
            expected_bytes,
            repetitions=args.repetitions,
            warmups=args.warmups,
        )
        admitted_ns = measurements["materialize_admitted"]["median_nanoseconds"]
        measurements["materialize_admitted"][
            "median_nanoseconds_per_waypoint"
        ] = round(admitted_ns / args.rows, 3)
    fail_closed_ns = measurements["materialize_fail_closed"]["median_nanoseconds"]
    measurements["materialize_fail_closed"][
        "median_nanoseconds_per_waypoint"
    ] = round(fail_closed_ns / args.rows, 3)

    print(
        json.dumps(
            {
                "benchmark": BENCHMARK_ID,
                "benchmark_id": BENCHMARK_ID,
                "benchmark_script_path": str(SCRIPT_PATH),
                "benchmark_script_sha256": _benchmark_script_sha256(),
                "git": _git_identity(),
                "label": args.label,
                "measurements": measurements,
                "package_path": str(Path(staqtapp_tds.__file__).resolve()),
                "packed_bytes": len(verified.packed_bytes),
                "result_identity": {
                    "admitted_materialization_sha256": admitted_materialization_sha256,
                    "expected_materialization_sha256": expected_materialization_sha256,
                    "graph_root": verified.graph_root,
                    "packed_sha256": hashlib.sha256(verified.packed_bytes).hexdigest(),
                    "public_materialization_sha256": public_materialization_sha256,
                },
                "platform": platform.platform(),
                "python": {
                    "executable": sys.executable,
                    "implementation": platform.python_implementation(),
                    "version": platform.python_version(),
                },
                "repetitions": args.repetitions,
                "rows": args.rows,
                "tds_version": staqtapp_tds.__version__,
                "timer": "time.perf_counter_ns",
                "warmups": args.warmups,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

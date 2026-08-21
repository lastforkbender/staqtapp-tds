"""Reproducible Driver VM/Studio correction benchmark.

Run this script with ``PYTHONPATH`` pointed at either a baseline checkout or the
working tree. It reports medians only; it never changes Registry authority or
uses performance evidence as a functional decision.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import staqtapp_tds.drivers.audit as audit_module
import staqtapp_tds.drivers.bytecode as bytecode_module
import staqtapp_tds.drivers.performance as performance_module
import staqtapp_tds
from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    DriverRuntimeManager,
    DriverStudioAdminReviewActions,
    DriverStudioConsoleSnapshot,
    DriverStudioPanelSnapshot,
    DriverStudioQueueItem,
    DriverVMRuntime,
    ReviewAction,
    RuntimeManagerPolicy,
    StudioConsoleStatus,
    StudioPanelKind,
    StudioPanelStatus,
    StudioReviewActionRequest,
    compile_tddl,
)


SOURCE = '''
driver DriverCorrectionBenchmark v1
manifest:
  kind = "search"
  safety = "bounded"
requires:
  capability registry.scan
  capability manifest.read
  capability trace.write
  adapter scorer.trace_rank.v1
limits:
  max_scan = 100000
  max_depth = 8
  timeout_ms = 250
program:
  SCAN scope=".tds" recursive=true limit=100000 depth=8
  READ target="manifest"
  MATCH field="manifest.kind" eq="driver"
  EXTRACT from="manifest" fields=["driver_id", "version", "capabilities", "safety"] limit=100000
  SCORE using="scorer.trace_rank.v1" threshold=0.0
  TRACE event="driver_correction_benchmark"
  EMIT mode="list" limit=10000
  HALT
evolution:
  deny external_io
'''
BENCHMARK_ID = "driver-performance-corrections-v1"
SCRIPT_PATH = Path(__file__).resolve()


def _benchmark_script_sha256() -> str:
    return hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()


def _records(count: int) -> list[dict[str, Any]]:
    return [
        {
            "path": f".tds/drivers/{index}",
            "manifest": {
                "kind": "driver",
                "driver_id": f"D{index}",
                "version": index,
                "capabilities": ["x", "y"],
                "safety": "bounded",
            },
            "semantic_score": 0.9,
        }
        for index in range(count)
    ]


def _median_ms(
    call: Callable[[], Any],
    identity: Callable[[Any], str],
    expected_identity: str,
    iterations: int,
) -> float:
    for _ in range(2):
        result = call()
        if not result.ok or identity(result) != expected_identity:
            raise RuntimeError("benchmark warmup result identity changed")
    samples: list[int] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        result = call()
        samples.append(time.perf_counter_ns() - started)
        if not result.ok:
            raise RuntimeError(getattr(result, "reason", "benchmark execution failed"))
        if identity(result) != expected_identity:
            raise RuntimeError("benchmark result identity changed")
    return statistics.median(samples) / 1_000_000.0


def _git_identity() -> dict[str, Any]:
    package_dir = Path(bytecode_module.__file__).resolve().parent
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


def _probe_counts(package: Any, snapshot: dict[str, Any], policy: RuntimeManagerPolicy) -> dict[str, int]:
    counts = {"package_hash_verifications": 0, "contract_display_rows": 0, "deepcopy_calls": 0}
    original_verify = bytecode_module.BytecodePackage.verify_hash
    original_contract_row = audit_module.VMInstructionContract.to_dict
    original_deepcopy = copy.deepcopy

    def counted_verify(self: Any) -> bool:
        counts["package_hash_verifications"] += 1
        return original_verify(self)

    def counted_contract_row(self: Any) -> dict[str, Any]:
        counts["contract_display_rows"] += 1
        return original_contract_row(self)

    def counted_deepcopy(value: Any, *args: Any, **kwargs: Any) -> Any:
        counts["deepcopy_calls"] += 1
        return original_deepcopy(value, *args, **kwargs)

    bytecode_module.BytecodePackage.verify_hash = counted_verify
    audit_module.VMInstructionContract.to_dict = counted_contract_row
    copy.deepcopy = counted_deepcopy
    try:
        evidence = DriverRuntimeManager(policy=policy).execute_package(package, snapshot)
        if not evidence.ok:
            raise RuntimeError(evidence.reason)
    finally:
        bytecode_module.BytecodePackage.verify_hash = original_verify
        audit_module.VMInstructionContract.to_dict = original_contract_row
        copy.deepcopy = original_deepcopy
    return counts


def _studio_console(row_count: int = 128) -> tuple[DriverStudioConsoleSnapshot, tuple[StudioReviewActionRequest, ...]]:
    queue = tuple(
        DriverStudioQueueItem(
            f"D{index}",
            1,
            "approval_ready",
            "low",
            "approve",
            review_hash=f"sha256:r{index}",
        )
        for index in range(row_count)
    )
    rows = tuple({"driver_id": f"D{index}", "payload": "x" * 200} for index in range(row_count))
    panels = tuple(
        DriverStudioPanelSnapshot(kind, StudioPanelStatus.READY, kind.value, kind.value, rows=rows)
        for kind in StudioPanelKind
    )
    console = DriverStudioConsoleSnapshot(
        True,
        StudioConsoleStatus.READY,
        "ready",
        "benchmark",
        "sha256:benchmark",
        "verified",
        None,
        "sha256:console",
        panels,
        queue,
        (),
        (),
        {},
    )
    actions = tuple(
        StudioReviewActionRequest(f"D{index}", ReviewAction.HOLD, reviewer_id="benchmark")
        for index in range(64)
    )
    return console, actions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=5000)
    parser.add_argument("--iterations", type=int, default=11)
    parser.add_argument("--label", default="candidate")
    args = parser.parse_args()
    if args.records <= 0 or args.iterations <= 0:
        parser.error("--records and --iterations must be positive")
    package = compile_tddl(SOURCE)
    snapshot = {"records": _records(args.records)}
    policy = RuntimeManagerPolicy(max_cost=1_000_000)

    def direct() -> Any:
        vm = DriverVMRuntime(max_cost=1_000_000)
        vm.load(package)
        return vm.execute(snapshot)

    def managed() -> Any:
        return DriverRuntimeManager(policy=policy).execute_package(package, snapshot)

    console, actions = _studio_console()

    def studio_actions() -> Any:
        return DriverStudioAdminReviewActions().submit_actions(console, actions, submitted_at="fixed")

    direct_identity = performance_module._result_hash(direct())
    managed_result = managed()
    if managed_result.evidence_hash is None:
        raise RuntimeError("managed benchmark produced no evidence identity")
    managed_identity = managed_result.evidence_hash
    studio_identity = studio_actions().submission_hash

    result = {
        "benchmark_id": BENCHMARK_ID,
        "benchmark_script_path": str(SCRIPT_PATH),
        "benchmark_script_sha256": _benchmark_script_sha256(),
        "label": args.label,
        "tds_version": __version__,
        "git": _git_identity(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "package_path": str(Path(staqtapp_tds.__file__).resolve()),
        "python_executable": sys.executable,
        "dataset": "deterministic-driver-records-v1",
        "records": args.records,
        "iterations": args.iterations,
        "counts": _probe_counts(package, snapshot, policy),
        "result_identity": {
            "direct_vm_result_hash": direct_identity,
            "managed_evidence_hash": managed_identity,
            "studio_submission_hash": studio_identity,
        },
        "direct_vm_median_ms": round(
            _median_ms(
                direct,
                performance_module._result_hash,
                direct_identity,
                args.iterations,
            ),
            3,
        ),
        "managed_vm_median_ms": round(
            _median_ms(
                managed,
                lambda value: str(value.evidence_hash),
                managed_identity,
                args.iterations,
            ),
            3,
        ),
        "studio_actions_median_ms": round(
            _median_ms(
                studio_actions,
                lambda value: value.submission_hash,
                studio_identity,
                args.iterations,
            ),
            3,
        ),
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

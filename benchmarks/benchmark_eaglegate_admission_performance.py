#!/usr/bin/env python3
"""Reproducible Eaglegate admission performance benchmark.

Run this same file with ``PYTHONPATH`` pointed at the checkout under test::

    PYTHONPATH=/path/to/staqtapp-tds/src \
      python benchmarks/benchmark_eaglegate_admission_performance.py

The workload uses public APIs shared by TDS v3.8.1 and the candidate. It emits
exactly one JSON record containing checkout, runtime, workload, and result
identity so independently captured baseline and candidate runs can be compared.
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
from staqtapp_tds.eaglegate import (
    EaglegateAdmissionPolicy,
    EaglegateDecision,
    EaglegateDecisionKind,
    EaglegateIdentity,
    EaglegateMode,
    EaglegatePlan,
    EaglegateRequestClass,
    EaglegateRuntimeHealth,
    EaglegateSamplerClass,
    EaglegateSpeculationEpoch,
    evaluate_admission,
)


PLAN_COUNTS = (1, 3, 128)
BENCHMARK_ID = "eaglegate-admission-performance-v1"
SCRIPT_PATH = Path(__file__).resolve()


def _benchmark_script_sha256() -> str:
    return hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()


def _root(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("ascii")).hexdigest()


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


def _identity() -> EaglegateIdentity:
    return EaglegateIdentity(
        target_model_root=_root("benchmark-target"),
        tokenizer_root=_root("benchmark-tokenizer"),
        proposer_root=_root("benchmark-proposer"),
        target_runtime_root=_root("benchmark-runtime"),
        sampler_contract_root=_root("benchmark-sampler"),
        logits_processor_root=_root("benchmark-logits"),
        kv_contract_root=_root("benchmark-kv"),
        kernel_capability_root=_root("benchmark-capability"),
        numerical_mode="benchmark-fp16-deterministic",
        tenant_scope="benchmark-tenant",
    )


def _workload(
    plan_count: int,
) -> tuple[
    Callable[[], EaglegateDecision],
    EaglegateSpeculationEpoch,
    EaglegateRequestClass,
    EaglegateDecision,
]:
    identity = _identity()
    plans = tuple(
        EaglegatePlan(
            plan_id=f"benchmark-plan-{index:04d}",
            candidate_tokens=4,
            max_tree_nodes=8,
            workspace_budget_bytes=64 << 20,
            max_batch=1,
            max_concurrency=8,
            max_context_tokens=32_768,
            max_kv_pressure_ppm=700_000,
            sampler_classes=(EaglegateSamplerClass.GREEDY,),
        )
        for index in range(plan_count)
    )
    epoch = EaglegateSpeculationEpoch(
        generation=1,
        identity=identity,
        plans=plans,
        policy=EaglegateAdmissionPolicy(
            policy_id=f"benchmark-policy-{plan_count}",
            mode=EaglegateMode.SHADOW,
            plan_order=tuple(plan.plan_id for plan in plans),
        ),
    )
    request = EaglegateRequestClass(
        identity_root=identity.identity_root,
        sampler_class=EaglegateSamplerClass.GREEDY,
        batch_size=2,
        concurrency=1,
        context_tokens=1_024,
        kv_pressure_ppm=100_000,
        request_bucket=0,
    )
    health = EaglegateRuntimeHealth(
        epoch_root=epoch.epoch_root,
        identity_root=identity.identity_root,
        target_available=True,
        proposer_available=True,
        workspace_available_bytes=1 << 30,
    )

    def operation() -> EaglegateDecision:
        return evaluate_admission(epoch, request, health)

    expected = operation()
    if (
        expected.kind is not EaglegateDecisionKind.FALLBACK
        or expected.reason != "batch_limit"
        or expected.plan_id
    ):
        raise RuntimeError("benchmark admission semantics changed")
    return operation, epoch, request, expected


def _measure(
    operation: Callable[[], EaglegateDecision],
    expected: EaglegateDecision,
    *,
    operations: int,
    repetitions: int,
    warmups: int,
) -> dict[str, Any]:
    for _ in range(warmups):
        for _ in range(operations):
            result = operation()
        if result != expected:
            raise RuntimeError("warmup admission result changed")

    samples_ns_per_operation: list[float] = []
    for _ in range(repetitions):
        gc.collect()
        started = time.perf_counter_ns()
        for _ in range(operations):
            result = operation()
        elapsed = time.perf_counter_ns() - started
        if result != expected:
            raise RuntimeError("measured admission result changed")
        samples_ns_per_operation.append(elapsed / operations)

    median_ns = statistics.median(samples_ns_per_operation)
    return {
        "median_nanoseconds_per_admission": round(median_ns, 3),
        "median_admissions_per_second": round(1_000_000_000.0 / median_ns, 3),
        "samples_nanoseconds_per_admission": [
            round(value, 3) for value in samples_ns_per_operation
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operations", type=int, default=500)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--label", default="candidate")
    args = parser.parse_args()
    if args.operations < 1 or args.repetitions < 1:
        parser.error("--operations and --repetitions must be positive")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")

    workloads: dict[str, Any] = {}
    for plan_count in PLAN_COUNTS:
        operation, epoch, request, expected = _workload(plan_count)
        workloads[str(plan_count)] = {
            "plan_count": plan_count,
            "result": {
                "decision_root": expected.decision_root,
                "epoch_root": epoch.epoch_root,
                "kind": expected.kind.value,
                "plan_id": expected.plan_id,
                "reason": expected.reason,
                "request_class_root": request.request_class_root,
            },
            **_measure(
                operation,
                expected,
                operations=args.operations,
                repetitions=args.repetitions,
                warmups=args.warmups,
            ),
        }

    print(
        json.dumps(
            {
                "benchmark": BENCHMARK_ID,
                "benchmark_id": BENCHMARK_ID,
                "benchmark_script_path": str(SCRIPT_PATH),
                "benchmark_script_sha256": _benchmark_script_sha256(),
                "git": _git_identity(),
                "label": args.label,
                "operations_per_repetition": args.operations,
                "package_path": str(Path(staqtapp_tds.__file__).resolve()),
                "platform": {
                    "machine": platform.machine(),
                    "processor": platform.processor(),
                    "release": platform.release(),
                    "system": platform.system(),
                },
                "python": {
                    "build": platform.python_build(),
                    "executable": sys.executable,
                    "implementation": platform.python_implementation(),
                    "version": platform.python_version(),
                },
                "repetitions": args.repetitions,
                "tds_version": staqtapp_tds.__version__,
                "timer": "time.perf_counter_ns",
                "warmups": args.warmups,
                "workload": "all-plans-rejected-by-batch-limit-v1",
                "workloads": workloads,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

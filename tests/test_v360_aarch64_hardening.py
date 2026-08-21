from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "aarch64_hardening_v360.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "aarch64-hardening.yml"


def load_tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "tds_v360_aarch64_hardening",
        TOOL_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load AArch64 hardening tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_architecture() -> str:
    machine = platform.machine().lower().replace("-", "_")
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    return machine


def in_tree_extensions_are_built() -> bool:
    package_dir = ROOT / "src" / "staqtapp_tds"
    return bool(list(package_dir.glob("_native_index*.so"))) and bool(
        list(package_dir.glob("_csv_scan_kernel*.so"))
    )


def test_aarch64_workflow_has_no_timing_or_scaling_gate() -> None:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "aarch64-performance-evidence" not in source
    assert "tools/aarch64_benchmark_v360.py" not in source
    assert "PERFORMANCE_RESULT" not in source

    aggregate = source.split("  aarch64-hardening-complete:", 1)[1]
    for required in (
        "aarch64-native-soak",
        "aarch64-sanitizers",
        "aarch64-thread-sanitizer",
        "aarch64-deterministic-fuzz",
    ):
        assert f"      - {required}" in aggregate


def test_v360_aarch64_hardening_contract_is_domain_separated() -> None:
    tool = load_tool()
    assert tool.FORMAT == "tds.v360.aarch64-hardening.v1"
    assert tool.EXPECTED_SEMANTIC_ROOT == "9ed03c78b6a99e1229808c764bee6bb0770aeb00c3905f40614665411006270a"
    assert len(bytes.fromhex(tool.EXPECTED_SEMANTIC_ROOT)) == 32
    assert tool.SEMANTIC_DOMAIN == b"TDS-V360-AARCH64-HARDENING-V1\0"

    projection = {
        "format": tool.FORMAT,
        "contracts": {"wire": "little-endian", "integer": 64},
        "results": [0, 1, -1, 2**63 - 1],
    }
    first = tool.semantic_root(projection)
    second = tool.semantic_root(dict(reversed(tuple(projection.items()))))
    assert first == second
    assert len(bytes.fromhex(first)) == 32


def test_v360_aarch64_hardening_rejects_wrong_architecture() -> None:
    wrong = "x86_64" if canonical_architecture() == "aarch64" else "aarch64"
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(TOOL_PATH),
            "--expected-architecture",
            wrong,
            "--loops",
            "1",
            "--keys",
            "1",
            "--workers",
            "1",
            "--iterations",
            "1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "architecture mismatch" in completed.stderr


def test_v360_aarch64_hardening_executes_on_native_arm(tmp_path: Path) -> None:
    if canonical_architecture() != "aarch64":
        pytest.skip("native AArch64 execution is qualified on the ARM runner")
    if not in_tree_extensions_are_built():
        pytest.skip("in-tree native extensions are not built")

    output = tmp_path / "aarch64-hardening.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(TOOL_PATH),
            "--expected-architecture",
            "aarch64",
            "--loops",
            "4",
            "--keys",
            "256",
            "--workers",
            "2",
            "--iterations",
            "4",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

    tool = load_tool()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["format"] == tool.FORMAT
    assert report["semantic_root"] == tool.semantic_root(
        report["semantic_projection"]
    )
    assert report["evidence"]["architecture"] == "aarch64"
    assert report["evidence"]["byteorder"] == "little"
    assert report["evidence"]["pointer_bits"] == 64
    assert report["functional_authority"] is False
    assert report["activation_authority"] is False
    assert report["passed"] is True

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
TOOL_PATH = ROOT / "tools" / "architecture_parity_v360_native.py"
PINNED_ROOT = "d2e839477d432cdf9e328982e6e9a245295dd05c80ddac4937232c0b72bc9d09"


def _load_tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "tds_v360_native_architecture_parity",
        TOOL_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load native architecture parity tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_architecture() -> str:
    machine = platform.machine().lower().replace("-", "_")
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    return machine


def _in_tree_extensions_are_built() -> bool:
    package_dir = ROOT / "src" / "staqtapp_tds"
    return bool(list(package_dir.glob("_native_index*.so"))) and bool(
        list(package_dir.glob("_csv_scan_kernel*.so"))
    )


def _synthetic_report(tool: Any, architecture: str) -> dict[str, Any]:
    projection = {
        "format": tool.FORMAT,
        "contracts": {"integer": 7, "wire": "little-endian"},
        "results": [0, 1, -1, 2**63 - 1],
    }
    return {
        "format": tool.FORMAT,
        "semantic_root": tool.semantic_root(projection),
        "semantic_projection": projection,
        "evidence": {
            "architecture": architecture,
            "source_commit": "a" * 40,
        },
        "functional_authority": False,
        "activation_authority": False,
    }


def test_v360_architecture_parity_contract_and_root_are_pinned() -> None:
    tool = _load_tool()
    assert tool.FORMAT == "tds.v360.native-architecture-parity.v1"
    assert tool.EXPECTED_SEMANTIC_ROOT == PINNED_ROOT
    assert len(bytes.fromhex(PINNED_ROOT)) == 32


def test_v360_report_comparator_requires_x86_arm_and_exact_semantics() -> None:
    tool = _load_tool()
    x86 = _synthetic_report(tool, "x86_64")
    arm = _synthetic_report(tool, "aarch64")

    result = tool.compare_reports(
        x86,
        arm,
        expected_root=x86["semantic_root"],
    )

    assert result["semantic_match"] is True
    assert result["architectures"] == ["aarch64", "x86_64"]
    assert result["source_commit"] == "a" * 40
    assert result["functional_authority"] is False
    assert result["activation_authority"] is False


def test_v360_report_comparator_rejects_semantic_or_source_drift() -> None:
    tool = _load_tool()
    x86 = _synthetic_report(tool, "x86_64")
    arm = _synthetic_report(tool, "aarch64")

    arm["semantic_projection"]["results"][-1] -= 1
    arm["semantic_root"] = tool.semantic_root(arm["semantic_projection"])
    with pytest.raises(ValueError, match="semantic projections differ"):
        tool.compare_reports(x86, arm)

    arm = _synthetic_report(tool, "aarch64")
    arm["evidence"]["source_commit"] = "b" * 40
    with pytest.raises(ValueError, match="one source commit"):
        tool.compare_reports(x86, arm)


def test_v360_native_semantic_projection_matches_the_pinned_root(tmp_path: Path) -> None:
    if not _in_tree_extensions_are_built():
        pytest.skip("in-tree native extensions are not built")
    architecture = _canonical_architecture()
    if architecture not in {"x86_64", "aarch64"}:
        pytest.skip(f"unsupported architecture for parity fixture: {architecture}")

    output = tmp_path / f"native-architecture-{architecture}.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(TOOL_PATH),
            "--expected-architecture",
            architecture,
            "--expected-root",
            PINNED_ROOT,
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["semantic_root"] == PINNED_ROOT
    assert report["root_matches_expected"] is True
    assert report["evidence"]["architecture"] == architecture
    assert report["evidence"]["byteorder"] == "little"
    assert report["evidence"]["pointer_bits"] == 64
    assert report["functional_authority"] is False
    assert report["activation_authority"] is False

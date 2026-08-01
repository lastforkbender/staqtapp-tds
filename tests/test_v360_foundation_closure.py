from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from staqtapp_tds import __version__
from staqtapp_tds.native.foundation import (
    EXPECTED_CSV_SCAN_GLOBALS,
    EXPECTED_NATIVE_INDEX_GLOBALS,
    FOUNDATION_PERFORMANCE_CLAIM,
    FoundationPerformanceClaim,
    NativeProcessStateKind,
    TDS_V360_FOUNDATION_CLOSURE_CONTRACT,
    TDS_V360_RELEASE_IDENTITY,
    audit_native_sources,
    build_foundation_closure_report,
    native_process_state_registry,
    native_process_state_registry_root,
)
from staqtapp_tds.version import VERSION_INFO


ROOT = Path(__file__).resolve().parents[1]


def test_v360_release_identity_and_scope_are_exact() -> None:
    assert __version__ == TDS_V360_RELEASE_IDENTITY == "3.6.0"
    assert VERSION_INFO == (3, 6, 0)
    report = build_foundation_closure_report(ROOT)
    assert report.contract_id == TDS_V360_FOUNDATION_CLOSURE_CONTRACT
    assert report.passed is True
    canonical = report.canonical_dict()
    assert canonical["atomic_generation_plane_included"] is False
    assert canonical["eaglegate_included"] is False
    assert canonical["learned_serving_included"] is False
    for field in (
        "storage_authority",
        "semantic_authority",
        "model_authority",
        "policy_authority",
        "activation_authority",
        "release_authority",
        "browser_authority",
    ):
        assert canonical[field] is False


def test_process_state_registry_is_closed_immutable_and_non_authoritative() -> None:
    entries = native_process_state_registry()
    assert len({item.symbol for item in entries}) == len(entries)
    assert {item.symbol for item in entries} == EXPECTED_NATIVE_INDEX_GLOBALS
    assert len(entries) == len(EXPECTED_NATIVE_INDEX_GLOBALS) == 13
    assert EXPECTED_CSV_SCAN_GLOBALS == frozenset()
    assert {item.kind for item in entries} == {
        NativeProcessStateKind.MONOTONIC_IDENTITY,
        NativeProcessStateKind.LIFECYCLE_GUARD,
        NativeProcessStateKind.OBSERVER_CONTROL,
        NativeProcessStateKind.OBSERVER_COUNTERS,
        NativeProcessStateKind.OBSERVER_RING,
    }
    assert native_process_state_registry_root().startswith("sha256:")
    for item in entries:
        assert item.durable is False
        assert item.storage_authority is False
        assert item.semantic_authority is False
        assert item.model_authority is False
        assert item.policy_authority is False
        assert item.activation_authority is False
    with pytest.raises(FrozenInstanceError):
        entries[0].symbol = "g_changed"  # type: ignore[misc]


def test_native_source_audit_classifies_every_process_global() -> None:
    audit = audit_native_sources(ROOT)
    assert audit.passed is True
    assert set(audit.declared_native_index_globals) == EXPECTED_NATIVE_INDEX_GLOBALS
    assert audit.declared_csv_scan_globals == ()
    assert audit.missing_native_index_globals == ()
    assert audit.unexpected_native_index_globals == ()
    assert audit.unexpected_csv_scan_globals == ()
    assert audit.missing_native_index_markers == ()
    assert audit.missing_csv_scan_markers == ()
    assert audit.native_index_sha256.startswith("sha256:")
    assert audit.csv_scan_sha256.startswith("sha256:")


def _copy_native_sources(destination: Path) -> None:
    target = destination / "src" / "staqtapp_tds"
    target.mkdir(parents=True)
    for filename in ("_native_index.c", "_csv_scan_kernel.c"):
        (target / filename).write_bytes((ROOT / "src" / "staqtapp_tds" / filename).read_bytes())


def test_unclassified_process_global_fails_closed(tmp_path: Path) -> None:
    _copy_native_sources(tmp_path)
    path = tmp_path / "src" / "staqtapp_tds" / "_native_index.c"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nstatic _Atomic uint64_t g_unclassified_state = 0;\n",
        encoding="utf-8",
    )
    audit = audit_native_sources(tmp_path)
    assert audit.passed is False
    assert audit.unexpected_native_index_globals == ("g_unclassified_state",)


def test_missing_process_global_fails_closed(tmp_path: Path) -> None:
    _copy_native_sources(tmp_path)
    path = tmp_path / "src" / "staqtapp_tds" / "_native_index.c"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "static _Atomic uint64_t g_diag_enabled = 1;",
        "static _Atomic uint64_t local_diag_enabled = 1;",
        1,
    )
    path.write_text(source, encoding="utf-8")
    audit = audit_native_sources(tmp_path)
    assert audit.passed is False
    assert audit.missing_native_index_globals == ("g_diag_enabled",)


def test_performance_claim_is_narrow_and_non_widenable() -> None:
    claim = FOUNDATION_PERFORMANCE_CLAIM
    assert claim.shared_runner_no_regression_qualified is True
    assert claim.shared_runner_min_two_worker_factor_ppm == 1_000_000
    assert claim.cross_architecture_semantic_parity_qualified is True
    assert claim.named_reference_cpu_claim is False
    assert claim.universal_scaling_claim is False
    assert claim.named_reference_cpu_release_blocker is False
    assert claim.performance_authority is False
    assert claim.activation_authority is False
    assert claim.claim_root.startswith("sha256:")
    with pytest.raises(ValueError, match="cannot be widened"):
        replace(claim, named_reference_cpu_claim=True)
    with pytest.raises(ValueError, match="cannot be widened"):
        FoundationPerformanceClaim(activation_authority=True)


def test_closure_report_and_cli_are_deterministic_and_content_free() -> None:
    first = build_foundation_closure_report(ROOT)
    second = build_foundation_closure_report(ROOT)
    assert first.report_root == second.report_root
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )
    command = [
        sys.executable,
        "-m",
        "staqtapp_tds.native.foundation",
        "--root",
        str(ROOT),
        "--json",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result_a = subprocess.run(
        command, cwd=ROOT, env=env, check=True, capture_output=True, text=True
    )
    result_b = subprocess.run(
        command, cwd=ROOT, env=env, check=True, capture_output=True, text=True
    )
    assert result_a.stdout == result_b.stdout
    payload = json.loads(result_a.stdout)
    assert payload["passed"] is True
    assert payload["report_root"] == first.report_root
    forbidden = {
        "prompt",
        "tokens",
        "token_sequence",
        "logits",
        "hidden_states",
        "kv_tensor",
        "kv_tensors",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert forbidden.isdisjoint(keys(payload))


def test_foundation_closure_documents_and_workflow_are_present() -> None:
    documentation = (ROOT / "docs" / "129_v360_Foundation_Closure.md").read_text(
        encoding="utf-8"
    )
    status = (ROOT / "DEV19_V360_FOUNDATION_CLOSURE_STATUS.txt").read_text(
        encoding="utf-8"
    )
    workflow = (
        ROOT / ".github" / "workflows" / "foundation-closure.yml"
    ).read_text(encoding="utf-8")
    assert "v3.6.0 Foundation Closure" in documentation
    assert "named-reference-CPU scaling claim:           false" in documentation
    assert "STATUS: SOURCE CANDIDATE IMPLEMENTED; REMOTE RELEASE GATES REQUIRED" in status
    assert "name: Staqtapp-TDS v3.6 Foundation Closure" in workflow
    assert "ubuntu-24.04-arm" in workflow
    assert "windows-2022" in workflow
    assert "macos-14" in workflow
    assert "cmp foundation-a.json foundation-b.json" in workflow
    assert "Eaglegate inclusion" in status
    assert "learned serving" in status

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "eaglegate-adapter-conformance.yml"


def test_adapter_workflow_is_cross_platform_and_aggregate_gated():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Staqtapp-TDS Eaglegate adapter conformance" in source
    assert "      - main" in source
    assert "agent/v380-phase1-phase4-convergence" in source
    assert "ubuntu-24.04" in source
    assert "macos-14" in source
    assert "windows-2022" in source
    assert "python: '3.10'" in source
    assert "python: '3.13'" in source
    assert "tests/test_v380_eaglegate_adapter_conformance.py" in source
    assert "tests/test_v380_eaglegate_generation_authority.py" in source
    assert "tests/test_v380_eaglegate_adapter_workflow_contract.py" in source
    assert "tests/test_v380_eaglegate_exactness_laboratory.py" in source
    assert "tests/test_v380_eaglegate_lossless_foundation.py" in source
    assert "tests/test_install_contract.py" in source
    assert "python -m staqtapp_tds.eaglegate.adapter --json" in source
    assert "cmp adapter-a.json adapter-b.json" in source
    assert "adapter_execution_authority" in source
    assert "real_runtime_qualified" in source
    assert "Eaglegate adapter conformance gates complete" in source
    assert 'test "$ADAPTER_RESULT" = "success"' in source
    assert "agent/eaglegate-exactness-laboratory" not in source
    assert "agent/eaglegate-adapter-conformance" not in source

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "eaglegate-exactness.yml"


def test_exactness_workflow_is_cross_platform_and_aggregate_gated():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Staqtapp-TDS Eaglegate exactness" in source
    assert "agent/eaglegate-lossless-foundation" in source
    assert "agent/eaglegate-exactness-laboratory" in source
    assert "ubuntu-24.04" in source
    assert "macos-14" in source
    assert "windows-2022" in source
    assert "python: '3.10'" in source
    assert "python: '3.13'" in source
    assert "tests/test_v380_eaglegate_exactness_laboratory.py" in source
    assert "tests/test_v380_eaglegate_exactness_workflow_contract.py" in source
    assert "tests/test_v380_eaglegate_lossless_foundation.py" in source
    assert "tests/test_v380_eaglegate_workflow_contract.py" in source
    assert "tests/test_install_contract.py" in source
    assert "python -m staqtapp_tds.eaglegate.exactness --json" in source
    assert "cmp exactness-a.json exactness-b.json" in source
    assert "activation_authority" in source
    assert "Eaglegate exactness gates complete" in source
    assert 'test "$EXACTNESS_RESULT" = "success"' in source

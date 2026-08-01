from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "eaglegate-shadow-sdk.yml"


def test_shadow_workflow_is_cross_platform_and_aggregate_gated():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Staqtapp-TDS Eaglegate shadow SDK" in source
    assert "agent/eaglegate-adapter-conformance" in source
    assert "agent/eaglegate-shadow-sdk" in source
    assert "ubuntu-24.04" in source
    assert "macos-14" in source
    assert "windows-2022" in source
    assert "python: '3.10'" in source
    assert "python: '3.13'" in source
    assert "tests/test_v380_eaglegate_shadow_sdk.py" in source
    assert "tests/test_v380_eaglegate_shadow_workflow_contract.py" in source
    assert "tests/test_v380_eaglegate_adapter_conformance.py" in source
    assert "tests/test_v380_eaglegate_exactness_laboratory.py" in source
    assert "tests/test_v380_eaglegate_lossless_foundation.py" in source
    assert "tests/test_install_contract.py" in source
    assert "python -m staqtapp_tds.eaglegate.shadow inspect" in source
    assert "shadow-a.json" in source
    assert "shadow-b.json" in source
    assert "runtime_imported" in source
    assert "executable_command_emitted" in source
    assert "real_runtime_qualified" in source
    assert "Eaglegate shadow SDK gates complete" in source
    assert 'test "$SHADOW_RESULT" = "success"' in source

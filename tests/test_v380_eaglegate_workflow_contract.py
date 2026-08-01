from pathlib import Path


def test_focused_ci_requires_cross_platform_lossless_contract_lanes():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "eaglegate-foundation.yml"
    ).read_text(encoding="utf-8")
    assert "agent/v370-atomic-csv-reference" in workflow
    assert "ubuntu-24.04" in workflow
    assert "macos-14" in workflow
    assert "windows-2022" in workflow
    assert "tests/test_v380_eaglegate_lossless_foundation.py" in workflow
    assert "tests/test_v380_eaglegate_workflow_contract.py" in workflow
    assert "tests/test_install_contract.py" in workflow
    assert "Eaglegate lossless gates complete" in workflow

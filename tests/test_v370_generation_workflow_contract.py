from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v370_has_one_permanent_generation_workflow_and_no_transfer_artifacts():
    workflows = ROOT / ".github" / "workflows"
    generation = workflows / "generation-authority.yml"
    assert generation.is_file()
    source = generation.read_text(encoding="utf-8")
    assert "Staqtapp-TDS v3.7 Atomic Generation Authority" in source
    assert "tests/test_v370_generation_contract.py" in source
    assert "tests/test_v370_generation_store.py" in source
    assert "tests/test_v370_readme_current_status.py" in source
    assert "TDS v3.7 Generation Authority gates complete" in source

    for forbidden in (
        ROOT / ".github" / "v370-baseline-export.trigger",
        ROOT / ".github" / "v370-readme-status.trigger",
        workflows / "export-v370-baseline.yml",
        workflows / "apply-v370-readme-status.yml",
    ):
        assert not forbidden.exists()


def test_generation_workflow_preserves_no_authority_boundary():
    source = (
        ROOT / ".github" / "workflows" / "generation-authority.yml"
    ).read_text(encoding="utf-8")
    for forbidden_import in (
        "staqtapp_tds.admin",
        "staqtapp_tds.studio_pyqt5",
        "staqtapp_tds.spiral",
        "staqtapp_tds.trace_rank",
        "staqtapp_tds.eaglegate",
        "torch",
        "vllm",
    ):
        assert forbidden_import in source

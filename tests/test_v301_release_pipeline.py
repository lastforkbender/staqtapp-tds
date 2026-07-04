from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_pipeline_files_exist():
    assert (ROOT / ".github" / "workflows" / "release.yml").exists()
    assert (ROOT / "scripts" / "check_release.py").exists()
    assert (ROOT / "docs" / "44_v301_Native_Engine_Manager.md").exists()
    assert (ROOT / "docs" / "RELEASE_PIPELINE.md").exists()


def test_release_checker_enforces_clean_source_artifacts():
    checker = (ROOT / "scripts" / "check_release.py").read_text()
    assert ".so" in checker
    assert ".pyd" in checker
    assert "__pycache__" in checker
    assert ".pytest_cache" in checker

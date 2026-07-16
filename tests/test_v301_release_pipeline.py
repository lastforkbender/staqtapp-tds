import os
from pathlib import Path
import subprocess
import sys

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


def test_release_checker_supports_dynamic_version_metadata():
    checker = (ROOT / "scripts" / "check_release.py").read_text()
    assert "tomllib.loads" in checker
    assert '"version" not in dynamic' in checker
    assert 'staqtapp_tds.version.__version__' in checker


def test_release_hygiene_runs_before_install_and_tests():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    hygiene = workflow.index("Check source release hygiene")
    install = workflow.index("Install package for tests", hygiene)
    tests = workflow.index("Run authoritative monolithic test suite", install)
    assert hygiene < install < tests

    generated = (
        ROOT / "docs" / "TDS_RESULT_CODES.json",
        ROOT / "docs" / "TDS_RESULT_CODES.md",
    )
    before = tuple(path.read_bytes() for path in generated)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, "-S", "tools/generate_result_code_docs.py"],
        cwd=ROOT,
        check=True,
        env=env,
    )
    assert tuple(path.read_bytes() for path in generated) == before


def test_release_pipeline_uses_authoritative_monolithic_pytest():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "python -m pytest -q --disable-warnings" in workflow
    assert "run_release_tests.py" not in workflow


def test_release_pipeline_gates_all_supported_pythons_and_platforms():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
        assert f"'{version}'" in workflow
    assert "windows-latest" in workflow
    assert "macos-latest" in workflow
    assert "ubuntu-latest" in workflow
    assert "STAQTAPP_TDS_BUILD_NATIVE: '1'" in workflow
    assert "_native_index, _csv_scan_kernel" in workflow
    assert "-c /dev/null tests" in workflow


def test_publishing_is_single_gated_trusted_publishing_job():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert not (ROOT / ".github" / "workflows" / "publish.yml").exists()
    aggregate = workflow.split("  release-gates-complete:", 1)[1].split(
        "\n  publish-pypi:", 1
    )[0]
    for required_job in (
        "source-release-checks",
        "python-compatibility",
        "platform-compatibility",
        "native-extension-qualification",
        "build-distributions",
    ):
        assert f"- {required_job}" in aggregate
    assert "needs: release-gates-complete" in workflow
    assert "github.ref_name == 'v3.5.3.post1'" in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish@v1.14.0" in workflow
    assert "PYPI_TOKEN" not in workflow
    assert "twine upload" not in workflow


def test_parallel_runner_is_documented_as_optional_acceleration_only():
    runner = (ROOT / "scripts" / "run_release_tests.py").read_text()
    assert "Optional parallel test accelerator" in runner
    assert "authoritative release gate" in runner
    assert "not a workaround for process degradation" in runner
    assert "subprocess.run" in runner

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_foundation_has_one_permanent_closure_workflow() -> None:
    workflow = ROOT / ".github" / "workflows" / "foundation-closure.yml"
    assert workflow.is_file()
    source = workflow.read_text(encoding="utf-8")
    assert "Staqtapp-TDS v3.6 Foundation Closure" in source
    assert "tests/test_v360_foundation_closure.py" in source
    assert "TDS v3.6 Foundation Closure gates complete" in source


def test_native_lane_uses_isolated_audit_and_only_core_runtime_dependency() -> None:
    source = (
        ROOT / ".github" / "workflows" / "foundation-closure.yml"
    ).read_text(encoding="utf-8")
    native = source.split("  native-source-contract:", 1)[1].split(
        "\n  foundation-gates-complete:", 1
    )[0]
    assert "python -m pip install setuptools wheel pytest numpy" in native
    assert (
        "python tools/foundation_closure_v360.py --root . --json "
        "> foundation-native.json"
    ) in native
    assert "python -m staqtapp_tds.native.foundation" not in native
    assert "PyQt5" not in native


def test_foundation_clean_tree_has_no_transfer_or_materialization_artifacts() -> None:
    forbidden = (
        ".github/v360-foundation-closure.patch.gz.b64",
        ".github/v360-foundation-closure.trigger",
        ".github/workflows/apply-v360-foundation-closure.yml",
        ".github/workflows/materialize-v360-foundation-closure.yml",
        ".github/native-repair-patch.part-00",
        ".github/workflows/apply-v360-native-repair.yml",
        ".github/workflows/native-repair.yml",
    )
    for relative in forbidden:
        assert not (ROOT / relative).exists(), relative

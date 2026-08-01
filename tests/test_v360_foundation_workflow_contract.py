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


def test_complete_phase1_process_global_audit_is_present() -> None:
    audit_path = ROOT / "docs" / "130_v360_Process_Global_Native_State_Audit.md"
    assert audit_path.is_file()
    audit = audit_path.read_text(encoding="utf-8")
    required = (
        "immutable after initialization",
        "atomic observer state",
        "guarded lifecycle state",
        "compatibility-only state",
        "must be migrated",
        "| **Total** | **29** | **closed** |",
        "| must be migrated | 0 | none remaining |",
        "`g_native_module_instance_active`",
        "`g_index_namespace_sequence`",
        "`g_frozen_snapshot_sequence`",
        "`crc32_ieee_nogil::table`",
        "`csv_scan_kernel_module`",
        "named-reference-CPU claim:                    false",
        "universal scaling claim:                      false",
    )
    for marker in required:
        assert marker in audit, marker


def test_foundation_clean_tree_has_no_transfer_materialization_or_future_release_artifacts() -> None:
    forbidden = (
        ".github/v360-foundation-closure.patch.gz.b64",
        ".github/v360-foundation-closure.trigger",
        ".github/workflows/apply-v360-foundation-closure.yml",
        ".github/workflows/materialize-v360-foundation-closure.yml",
        ".github/native-repair-patch.part-00",
        ".github/workflows/apply-v360-native-repair.yml",
        ".github/workflows/native-repair.yml",
        ".github/workflows/fix-v360-semantic-ir-compat.yml",
        "tools/update_v360_readme_status.py",
        ".github/RELEASE_ACTION_REQUIRED",
        ".github/V370_RELEASE_NOTES.md",
        ".github/V370_TAG_READY",
        ".github/workflows/publish-v370-github-release-once.yml",
        ".github/workflows/tag-v370-once.yml",
        "RELEASE_V370_PENDING.txt",
    )
    for relative in forbidden:
        assert not (ROOT / relative).exists(), relative

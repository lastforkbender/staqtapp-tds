from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "fixed-point-path-reference.yml"
DESIGN_NOTE = ROOT / "docs" / "133_v381_Fixed_Point_Path_Reference_Oracle.md"
PHASE4_NOTE = ROOT / "docs" / "132_v380_Packed_Waypoint_CSR_Graph.md"


def test_phase5_reference_workflow_is_cross_platform_and_complete() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "Staqtapp-TDS v3.8.1 Phase 5 fixed-point path reference oracle"
        in source
    )
    assert "      - main" in source
    assert "      - agent/v381-fixed-point-path-planner" in source
    assert source.count("          - os: ubuntu-24.04") == 2
    assert source.count("          - os: macos-14") == 1
    assert source.count("          - os: windows-2022") == 1
    assert source.count("            python: '3.10'") == 1
    assert source.count("            python: '3.13'") == 3

    for test_path in (
        "tests/test_v360_trace_rank_contract.py",
        "tests/test_v370_csv_generation.py",
        "tests/test_v380_packed_waypoint_graph.py",
        "tests/test_v381_fixed_point_path_planner.py",
        "tests/test_v381_fixed_point_path_workflow_contract.py",
        "tests/test_install_contract.py",
    ):
        assert test_path in source

    assert "src/staqtapp_tds/generation" in source
    assert "src/staqtapp_tds/trace_rank" in source
    assert "TDS v3.8.1 Phase 5 fixed-point path gates complete" in source


def test_phase5_workflow_has_read_only_evidence_authority() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in source
    for forbidden in (
        "contents: write",
        "id-token: write",
        "packages: write",
        "${{ secrets.",
        "twine upload",
        "docker push",
    ):
        assert forbidden not in source


def test_phase5_note_preserves_reference_only_claim_boundary() -> None:
    source = DESIGN_NOTE.read_text(encoding="utf-8")

    for required in (
        "off-path Python reference oracle",
        "included in the `v3.8.1` package identity",
        "not a native hot path or production-serving completion",
        "does not implement a legal-edge generator",
        "no fixed scratch-byte bound",
        "fixed-dimensional learned forest",
        "sentinel generation",
        "native executor",
        "trainer",
        "controller",
        "activation",
        "any claim that Frontier Fabric or its production-serving path is complete",
    ):
        assert required in source


def test_phase4_note_describes_unsigned_delta_and_phase5_handoff_exactly() -> None:
    source = PHASE4_NOTE.read_text(encoding="utf-8")

    assert "signed bounded learned delta" not in source
    assert "non-negative bounded learned delta (`uint32`)" in source
    assert "Phase 5 adds an off-path Python reference oracle" in source
    assert "Legal-edge generation" in source
    assert "bounded scratch-byte contract" in source

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_packed_waypoint_graph_workflow_is_canonical_and_cross_platform() -> None:
    source = (
        ROOT / ".github" / "workflows" / "packed-waypoint-graph.yml"
    ).read_text(encoding="utf-8")
    assert "Staqtapp-TDS v3.8 packed waypoint graph" in source
    assert "      - main" in source
    assert "agent/v380-phase1-phase4-convergence" in source
    assert "ubuntu-24.04" in source
    assert "macos-14" in source
    assert "windows-2022" in source
    assert "tests/test_v360_trace_rank_contract.py" in source
    assert "tests/test_v370_csv_generation.py" in source
    assert "tests/test_v380_packed_waypoint_graph.py" in source
    assert "tests/test_v380_packed_waypoint_graph_workflow_contract.py" in source
    assert "TDS v3.8 packed waypoint graph gates complete" in source


def test_phase4_graph_surface_has_no_search_or_execution_command() -> None:
    source = (ROOT / "src" / "staqtapp_tds" / "trace_rank" / "graph.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("def dijkstra", "def search", "def execute", "def commit"):
        assert forbidden not in source

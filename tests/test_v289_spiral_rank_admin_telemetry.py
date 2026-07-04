from staqtapp_tds import __version__
from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.admin.spiral_rank import SpiralRankTelemetry
from staqtapp_tds.spiral.rank import NativeSpiralRankEngine


def test_v289_version():
    assert __version__ == "2.9.4"


def test_spiral_rank_telemetry_observes_run():
    run = NativeSpiralRankEngine(prefer_native=False).rank_run(
        ["trace-a", "trace-b", "trace-c"],
        [0.4, 0.9, 0.7],
        confidences=[0.9, 0.6, 0.8],
        depths=[2, 1, 3],
        ages_ns=[10, 20, 30],
        limit=2,
    )
    telemetry = SpiralRankTelemetry()
    telemetry.observe_run(run)
    snap = telemetry.snapshot()
    assert snap["enabled"] is True
    assert snap["observer_only"] is True
    assert snap["runs_total"] == 1
    assert snap["fallback_runs"] == 1
    assert snap["last_stats"]["dropped_by_limit"] == 1
    assert len(snap["top_results"]) == 2
    assert snap["top_results"][0]["rank"] == 1


def test_admin_status_exposes_spiral_rank_snapshot():
    control = AdminControl()
    run = NativeSpiralRankEngine(prefer_native=False).rank_run(["trace-a"], [1.0])
    control.spiral_rank_telemetry.observe_run(run)
    status = control.status()
    assert "spiral_rank" in status
    assert status["spiral_rank"]["runs_total"] == 1
    assert status["spiral_rank"]["last_stats"]["ranked_count"] == 1


def test_dashboard_contains_spiral_rank_page():
    html = open("src/staqtapp_tds/admin/templates/dashboard.html", encoding="utf-8").read()
    js = open("src/staqtapp_tds/admin/static/js/dashboard.js", encoding="utf-8").read()
    assert "#spiral-rank" in html
    assert "Analytics · Spiral Rank" in html
    assert "Ranking feedback telemetry" in html
    assert "spiral_rank" in js
    assert "renderSpiralRank" in js


def test_spiral_rank_browser_layout_guards():
    css = open("src/staqtapp_tds/admin/static/css/dashboard.css", encoding="utf-8").read()
    assert ".spiral-rank-page,.spiral-rank-page *{min-width:0}" in css
    assert "overflow-wrap:anywhere" in css
    assert ".spiral-rank-list{max-height:420px;overflow:auto" in css
    assert "@media(max-width:680px)" in css

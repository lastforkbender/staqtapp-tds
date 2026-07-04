from staqtapp_tds.spiral import NativeSpiralRankEngine, SpiralRankConfig, rank_trace_run, SpiralRankStats


def test_v288_rank_run_exposes_observer_stats():
    engine = NativeSpiralRankEngine(SpiralRankConfig(), prefer_native=False)
    run = engine.rank_run(
        ["a", "b", "c"],
        [0.2, 0.9, 0.5],
        confidences=[1.0, 0.5, 0.8],
        depths=[0, 1, 2],
        ages_ns=[0, 10, 20],
        limit=2,
    )
    assert isinstance(run.stats, SpiralRankStats)
    assert len(run.results) == 2
    assert run.stats.input_count == 3
    assert run.stats.ranked_count == 3
    assert run.stats.limited_count == 2
    assert run.stats.dropped_by_limit == 1
    assert run.stats.limit_applied is True
    assert run.stats.native is False
    assert run.stats.engine == "python"
    assert run.stats.min_score <= run.stats.mean_score <= run.stats.max_score
    assert run.stats.elapsed_ns >= run.stats.scoring_ns
    assert run.stats.to_dict()["limit_applied"] is True
    assert engine.last_stats == run.stats


def test_v288_rank_trace_run_helper_exports_results_and_stats():
    run = rank_trace_run(["x", "y"], [0.1, 0.8], limit=1)
    data = run.to_dict()
    assert data["results"][0]["trace_id"] == "y"
    assert data["stats"]["input_count"] == 2
    assert data["stats"]["dropped_by_limit"] == 1
    assert data["stats"]["config_id"] == "tds-native-spiral-rank-v288"


def test_v288_empty_rank_stats_are_safe():
    run = NativeSpiralRankEngine(prefer_native=False).rank_run([], [])
    assert run.results == ()
    assert run.stats.input_count == 0
    assert run.stats.min_score is None
    assert run.stats.max_score is None
    assert run.stats.mean_score is None

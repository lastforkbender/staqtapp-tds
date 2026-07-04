from staqtapp_tds.spiral import NativeSpiralRankEngine, SpiralRankConfig, rank_traces


def test_v288_spiral_rank_is_deterministic_and_ordered():
    engine = NativeSpiralRankEngine(prefer_native=False)
    ranked = engine.rank(
        ["trace_b", "trace_a", "trace_c"],
        [0.80, 0.91, 0.91],
        confidences=[0.90, 0.95, 0.95],
        depths=[1, 3, 1],
        ages_ns=[0, 0, 0],
    )
    assert [r.trace_id for r in ranked] == ["trace_c", "trace_a", "trace_b"]
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert all(r.config_id == "tds-native-spiral-rank-v288" for r in ranked)


def test_v288_native_and_python_score_paths_match_when_native_available():
    py_engine = NativeSpiralRankEngine(prefer_native=False)
    native_engine = NativeSpiralRankEngine(prefer_native=True)
    scores = [0.2, 0.7, 1.4, -0.2]
    confidences = [1.0, 0.5, 2.0, -1.0]
    depths = [0, 2, 1, 4]
    ages = [0, 10, 20, 30]
    assert native_engine.score_many(scores, confidences, depths, ages) == py_engine.score_many(scores, confidences, depths, ages)


def test_v288_limit_and_dict_shape():
    result = rank_traces(["x", "y"], [0.1, 0.9], limit=1)[0].to_dict()
    assert result["trace_id"] == "y"
    assert result["rank"] == 1
    assert "native" in result


def test_v288_length_validation():
    engine = NativeSpiralRankEngine(SpiralRankConfig())
    try:
        engine.rank(["x"], [0.1, 0.2])
    except ValueError as exc:
        assert "same length" in str(exc)
    else:
        raise AssertionError("expected ValueError")

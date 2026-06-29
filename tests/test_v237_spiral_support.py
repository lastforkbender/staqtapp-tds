from staqtapp_tds import TDSFileSystem, RuntimeConfig, TraceRecord, TraceSetManifest, AggregationRecord, create_spiral_run, __version__


def test_version_and_runtime_config_spiral_flag():
    assert __version__ == "2.3.7"
    cfg = RuntimeConfig.default().next_generation(spiral_support_enabled=True)
    assert cfg.spiral_support_enabled is True
    assert RuntimeConfig.from_mapping(cfg.to_dict()).spiral_support_enabled is True


def test_spiral_run_directory_first_layout_and_records():
    fs = TDSFileSystem("root")
    run = create_spiral_run(fs.root, "run_001", problem={"prompt": "x"}, problem_id="p1")

    trace = run.store_search_trace("trace_0001", "candidate", rank_score=0.7, rank_source="verifier")
    assert isinstance(trace, TraceRecord)
    assert trace.rank_score == 0.7
    assert run.traces.read("trace_0001.tds") == "candidate"

    tset = run.create_trace_set("set_0001", ["trace_0001"], metadata={"n": 1})
    assert isinstance(tset, TraceSetManifest)
    assert run.sets.read("set_0001.json")["trace_ids"] == ["trace_0001"]

    agg = run.store_aggregation("agg_0001", "answer", derived_from=["trace_0001"], rank_score=0.9)
    assert isinstance(agg, AggregationRecord)
    assert run.aggregations.read("agg_0001.tds") == "answer"

    run.store_final("answer.tds", "final", derived_from=["agg_0001"])
    assert run.final.read("answer.tds") == "final"

    snap = run.snapshot()
    assert snap["layout"] == "directory-first"
    assert snap["reasoning_owned_by"] == "caller"
    assert snap["search_traces"] == 1
    assert snap["trace_sets"] == 1
    assert snap["aggregations"] == 1
    assert snap["final_outputs"] == 1


def test_spiral_telemetry_is_snapshot_only_storage_behavior():
    fs = TDSFileSystem("root")
    run = create_spiral_run(fs.root, "run_telemetry")
    run.store_search_trace("t1", "a")
    run.create_trace_set("s1", ["t1"])
    run.store_aggregation("a1", "b", derived_from=["t1"])
    run.store_final("f1", "c", derived_from=["a1"])

    snap = fs.root.telemetry_manager.snapshot(force=True)
    spiral = snap["storage"]["spiral"]
    assert spiral["mode"] == "neutral-trace-storage"
    assert spiral["ranking_owner"] == "external"
    assert spiral["runs"] >= 1
    assert spiral["search_traces"] >= 1
    assert snap["behavior"]["current_operation"] == "trace_pipeline"

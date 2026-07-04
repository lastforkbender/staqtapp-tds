import pytest

from staqtapp_tds.result import TDSResult, TDS_RESULT_CODES, known_result_codes, is_known_result_code
from staqtapp_tds.spiral.rank import NativeSpiralRankEngine, SpiralRankRecord, SpiralRankRun, rank_trace_result


def test_public_result_code_catalog_is_available():
    assert "READ_OK" in known_result_codes()
    assert "PAYLOAD_DESERIALIZE_ERROR" in TDS_RESULT_CODES
    assert is_known_result_code("WRITE_ERROR") is True
    assert is_known_result_code("NOT_A_TDS_CODE") is False
    assert TDSResult.success("READ_OK").known_code is True


def test_spiral_rank_ai_safe_surface_returns_tds_result_on_success():
    result = NativeSpiralRankEngine(prefer_native=False).rank_result(["trace-a"], [1.0])
    assert isinstance(result, TDSResult)
    assert result.ok is True
    assert result.code == "SPIRAL_RANK_OK"
    assert result.value["records"][0]["trace_id"] == "trace-a"
    assert result.meta["record_count"] == 1


def test_spiral_rank_ai_safe_surface_returns_tds_result_on_input_error():
    result = NativeSpiralRankEngine(prefer_native=False).rank_result(["trace-a", "trace-b"], [1.0])
    assert isinstance(result, TDSResult)
    assert result.ok is False
    assert result.code == "SPIRAL_RANK_ERROR"
    assert result.value is None
    assert result.meta["exception_type"] == "ValueError"


def test_spiral_rank_row_is_record_not_result_envelope():
    run = NativeSpiralRankEngine(prefer_native=False).rank_run(["trace-a"], [0.5])
    assert isinstance(run.records[0], SpiralRankRecord)
    assert run.results == run.records  # legacy alias only
    assert "records" in run.to_dict()


def test_legacy_spiral_run_results_keyword_still_maps_to_records():
    stats = NativeSpiralRankEngine(prefer_native=False).rank_run([], []).stats
    row = SpiralRankRecord("trace-a", 1.0, 1.0, 1.0, 0, 0, 1, False, "cfg")
    run = SpiralRankRun(results=(row,), stats=stats)
    assert run.records == (row,)


def test_old_spiral_rank_result_name_is_not_public():
    with pytest.raises(ImportError):
        exec("from staqtapp_tds.spiral.rank import SpiralRankResult", {})


def test_all_literal_tds_result_codes_are_registered():
    import pathlib, re
    source_root = pathlib.Path(__file__).resolve().parents[1] / "src"
    emitted = set()
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        emitted.update(re.findall(r"TDSResult\.(?:success|fail|error|from_exception)\(\s*[\"']([A-Z0-9_]+)[\"']", text))
    missing = sorted(code for code in emitted if code not in TDS_RESULT_CODES)
    assert missing == []

from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import FmtID, TDSFileSystem, _deserialize_payload


def test_deserialize_pickle_failure_returns_error_code_not_raw_bytes():
    raw = b"not a valid pickle payload"
    result = _deserialize_payload(raw, FmtID.PICKLE_OBJ)
    assert isinstance(result, TDSResult)
    assert result.ok is False
    assert result.code == "PAYLOAD_DESERIALIZE_ERROR"
    assert result.value is None
    assert result.meta["raw_size"] == len(raw)


def test_read_result_missing_does_not_raise(tmp_path):
    fs = TDSFileSystem(str(tmp_path / "tds"))
    result = fs.root.read_result("missing")
    assert isinstance(result, TDSResult)
    assert result.ok is False
    assert result.code == "READ_MISSING"


def test_write_and_read_result_standard_surface(tmp_path):
    fs = TDSFileSystem(str(tmp_path / "tds"))
    written = fs.root.write_result("alpha", {"x": 1}, fmt_id=FmtID.JSON_UTF8)
    assert written.ok is True
    assert written.code == "WRITE_OK"
    read = fs.root.read_result("alpha")
    assert read.ok is True
    assert read.code == "READ_OK"
    assert read.value == {"x": 1}

from staqtapp_tds import TDSFileSystem, TDSResult, known_result_codes


def test_public_read_write_delete_return_tdsresult(tmp_path):
    fs = TDSFileSystem(str(tmp_path / "tds"))
    w = fs.root.write("state", {"n": 1})
    assert isinstance(w, TDSResult)
    assert w.ok and w.code == "WRITE_OK"

    r = fs.root.read("state")
    assert isinstance(r, TDSResult)
    assert r.ok and r.code == "READ_OK"
    assert r.value == {"n": 1}

    d = fs.root.delete("state")
    assert isinstance(d, TDSResult)
    assert d.ok and d.code == "DELETE_OK"

    missing = fs.root.read("state")
    assert isinstance(missing, TDSResult)
    assert not missing.ok and missing.code == "READ_MISSING"


def test_legacy_raw_surfaces_remain_explicit(tmp_path):
    fs = TDSFileSystem(str(tmp_path / "tds"))
    entry = fs.root.write_entry("state", 7)
    assert entry.name == "state"
    assert fs.root.read_value("state") == 7
    fs.root.delete_entry("state")
    assert fs.root.read("state").code == "READ_MISSING"


def test_known_result_codes_include_public_api_codes():
    codes = set(known_result_codes())
    for code in ["WRITE_OK", "READ_OK", "READ_MISSING", "DELETE_OK", "PERSIST_READ_OK"]:
        assert code in codes

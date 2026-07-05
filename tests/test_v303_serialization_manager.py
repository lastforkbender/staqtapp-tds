import pickle

from staqtapp_tds import FmtID, TDSFileSystem, SerializationManager, get_default_serialization_manager
from staqtapp_tds.result import TDSResult
from staqtapp_tds.tds_filesystem import _deserialize_payload
from staqtapp_tds.tds_pickle import ENVELOPE_MAGIC


def test_v303_serialization_manager_infers_common_variable_formats():
    manager = SerializationManager()
    assert manager.choose_fmt_id({"a": [1, 2], "b": True}) == int(FmtID.JSON_UTF8)
    assert manager.choose_fmt_id(b"abc") == int(FmtID.RAW_BINARY)
    assert manager.choose_fmt_id(({"tuple": True}, {"set"})) == int(FmtID.PICKLE_OBJ)


def test_v303_addvar_loadvar_findvar_read_flow_through_manager(tmp_path):
    fs = TDSFileSystem(str(tmp_path / "tds"))
    d = fs.root

    assert d.addvar("json_state", {"a": [1, 2], "ok": True}).ok
    assert d.entry_metadata("json_state")["payload_kind"] == "JSON_UTF8"
    assert d.loadvar("json_state") == {"a": [1, 2], "ok": True}
    found = d.findvar("json_state")
    assert found.ok and found.value == {"a": [1, 2], "ok": True}
    read = d.read("json_state")
    assert read.ok and read.value == {"a": [1, 2], "ok": True}

    complex_value = ({"tuple": True}, 7, {"a", "b"})
    assert d.addvar("py_state", complex_value).ok
    assert d.entry_metadata("py_state")["payload_kind"] == "PICKLE_OBJ"
    assert d.loadvar("py_state") == complex_value
    assert d.findvar("py_state").value == complex_value
    assert d.read("py_state").value == complex_value


def test_v303_stalkvar_uses_loadvar_serialization_manager_path(tmp_path):
    fs = TDSFileSystem(str(tmp_path / "tds"))
    d = fs.root

    assert d.addvar("state", {"base": True}).ok
    stalked = d.stalkvar("~state", {"next": 1})
    assert stalked.ok
    assert d.entry_metadata("state_0001")["payload_kind"] == "JSON_UTF8"
    assert d.loadvar("state_0001") == {"base": True, "next": 1}


def test_v303_legacy_unenveloped_pickle_payload_reads_through_manager():
    raw = pickle.dumps(("legacy", {"safe": True}), protocol=5)
    assert get_default_serialization_manager().deserialize(raw, int(FmtID.PICKLE_OBJ)) == ("legacy", {"safe": True})


def test_v303_unsafe_legacy_pickle_payload_is_blocked_through_manager():
    class Exploit:
        def __reduce__(self):
            return (eval, ("1 + 1",))

    raw = ENVELOPE_MAGIC + pickle.dumps(Exploit(), protocol=5)
    result = _deserialize_payload(raw, FmtID.PICKLE_OBJ)
    assert isinstance(result, TDSResult)
    assert not result.ok
    assert result.code == "PAYLOAD_DESERIALIZE_ERROR"
    assert result.meta["exception_type"] == "PicklePolicyError"
    assert "serialization_manager" in result.meta

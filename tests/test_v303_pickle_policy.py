import pickle

from staqtapp_tds import FmtID
from staqtapp_tds.tds_filesystem import _deserialize_payload, _serialize_payload
from staqtapp_tds.tds_pickle import ENVELOPE_MAGIC, PicklePolicyError, dumps_pickle, loads_pickle, pickle_policy_snapshot


def test_v303_pickle_roundtrip_uses_tds_envelope_and_restricted_reader():
    value = ({"tuple": True}, 7, {"a", "b"})
    raw = _serialize_payload(value, FmtID.PICKLE_OBJ)
    assert raw.startswith(ENVELOPE_MAGIC)
    assert _deserialize_payload(raw, FmtID.PICKLE_OBJ) == value


def test_v303_restricted_reader_rejects_unsafe_global():
    class Exploit:
        def __reduce__(self):
            return (eval, ("1 + 1",))

    raw = ENVELOPE_MAGIC + pickle.dumps(Exploit(), protocol=5)
    result = _deserialize_payload(raw, FmtID.PICKLE_OBJ)
    assert not result.ok
    assert result.code == "PAYLOAD_DESERIALIZE_ERROR"
    assert result.meta["exception_type"] == "PicklePolicyError"
    assert result.meta["pickle_policy"]["mode"] == "restricted"


def test_v303_custom_objects_fail_at_write_boundary():
    class CustomObject:
        pass

    try:
        dumps_pickle(CustomObject())
    except PicklePolicyError as exc:
        assert "not allowed" in str(exc) or "pickle" in str(exc)
    else:
        raise AssertionError("custom object unexpectedly passed restricted pickle validation")


def test_v303_legacy_unenveloped_safe_pickle_still_reads_for_compatibility():
    raw = pickle.dumps(("legacy", {"safe": True}), protocol=5)
    assert loads_pickle(raw) == ("legacy", {"safe": True})
    snap = pickle_policy_snapshot()
    assert snap["mode"] == "restricted"
    assert snap["require_envelope"] is False

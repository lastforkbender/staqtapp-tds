from staqtapp_tds import (
    EntryIndex,
    TDSResult,
    TDSResultCode,
    TDS_NATIVE_ABI_VERSION,
    get_native_manager,
    native_capabilities_result,
    native_status_result,
    __version__,
)


def test_v301_version():
    assert __version__ == "3.1.23"


def test_native_manager_status_is_tdsresult():
    result = native_status_result()
    assert isinstance(result, TDSResult)
    assert result.ok
    assert result.code == TDSResultCode.NATIVE_MANAGER_OK.value
    assert result.meta["expected_abi"] == TDS_NATIVE_ABI_VERSION


def test_native_capabilities_are_non_halting_result():
    result = native_capabilities_result()
    assert isinstance(result, TDSResult)
    assert result.ok
    assert result.code == TDSResultCode.NATIVE_CAPABILITY_OK.value
    assert "platform" in result.value
    assert "expected_abi" in result.value


def test_entry_index_native_status_result_is_structured():
    idx = EntryIndex(backend="auto")
    idx.put("alpha", {"v": 1})
    status = idx.native_status_result()
    assert isinstance(status, TDSResult)
    assert status.code in {TDSResultCode.NATIVE_ENGINE_LOADED.value, TDSResultCode.NATIVE_ENGINE_FALLBACK.value}
    assert idx.get("alpha") == {"v": 1}


def test_native_manager_contains_platform_details():
    manager = get_native_manager()
    platform = manager.platform.as_dict()
    assert platform["system"]
    assert platform["machine"]
    assert platform["python_tag"]

"""Native engine management for Staqtapp-TDS."""
from staqtapp_tds.native.manager import (
    NativeEngineManager,
    NativeLoadReport,
    NativeRuntimePlatform,
    TDS_NATIVE_ABI_VERSION,
    get_native_manager,
    native_status_result,
    native_capabilities_result,
)

from staqtapp_tds.native.checksums import (
    CHECKSUM32_ALGORITHMS,
    CRC32_IEEE_V1,
    DEFAULT_CHECKSUM32_ALGORITHM,
    FNV1A32_LEGACY_V1,
    ChecksumAlgorithmError,
    checksum32,
    checksum32_many,
    checksum32_python,
    manifest_checksum32_algorithm,
)
from staqtapp_tds.native.utf8 import (
    UTF8_CHUNK_CONTRACT,
    utf8_chunk_bounds,
    utf8_chunk_bounds_python,
)

__all__ = [
    "NativeEngineManager",
    "NativeLoadReport",
    "NativeRuntimePlatform",
    "TDS_NATIVE_ABI_VERSION",
    "get_native_manager",
    "native_status_result",
    "native_capabilities_result",
    "CHECKSUM32_ALGORITHMS",
    "CRC32_IEEE_V1",
    "DEFAULT_CHECKSUM32_ALGORITHM",
    "FNV1A32_LEGACY_V1",
    "ChecksumAlgorithmError",
    "checksum32",
    "checksum32_many",
    "checksum32_python",
    "manifest_checksum32_algorithm",
    "UTF8_CHUNK_CONTRACT",
    "utf8_chunk_bounds",
    "utf8_chunk_bounds_python",
]

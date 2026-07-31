#!/usr/bin/env python3
"""Verify explicit compatibility-GIL admission on free-threaded CPython."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from struct import pack, unpack_from
import sys
import sysconfig


def _load_extension():
    root = Path(__file__).resolve().parents[1] / "src" / "staqtapp_tds"
    candidates = sorted(root.glob("_native_index*.so"))
    if len(candidates) != 1:
        raise RuntimeError(
            "expected exactly one free-threaded native extension, "
            f"found {[str(path) for path in candidates]!r}"
        )
    spec = importlib.util.spec_from_file_location("_native_index", candidates[0])
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot construct native extension spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if sysconfig.get_config_var("Py_GIL_DISABLED") != 1:
        raise RuntimeError("qualification requires a free-threaded CPython build")
    if not hasattr(sys, "_is_gil_enabled"):
        raise RuntimeError("free-threaded GIL status API is unavailable")
    if sys._is_gil_enabled():
        raise RuntimeError("qualification must begin with the GIL disabled")

    module = _load_extension()

    if not sys._is_gil_enabled():
        raise RuntimeError("compatibility-GIL native policy was not enforced")
    if module.TDS_NATIVE_GIL_POLICY != "compatibility-gil-required-v1":
        raise RuntimeError("unexpected native GIL policy")
    if module.TDS_NATIVE_MODULE_INIT != "multiphase-pep489-v1":
        raise RuntimeError("unexpected native initialization policy")
    if module.TDS_NATIVE_REINITIALIZATION_POLICY != (
        "process-restart-required-v1"
    ):
        raise RuntimeError("unexpected native reinitialization policy")

    # Admission must preserve a minimal qualified request-path operation.
    mutable = module.NativeHandleIndex(capacity=16)
    first = int(mutable.put(b"first"))
    second = int(mutable.put(b"second"))
    frozen = mutable.freeze()
    keys = b"firstsecondmissing"
    offsets = pack("<QQQQ", 0, 5, 11, len(keys))
    output = bytearray(24)
    if int(frozen.lookup_packed(keys, offsets, output)) != 3:
        raise RuntimeError("free-threaded packed lookup did not process all keys")
    values = tuple(unpack_from("<q", output, index * 8)[0] for index in range(3))
    if values != (first, second, -1):
        raise RuntimeError(f"free-threaded packed lookup parity failed: {values!r}")

    print("v3.6 free-threaded compatibility admission passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

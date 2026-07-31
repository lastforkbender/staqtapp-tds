#!/usr/bin/env python3
"""Fail-closed admission check for the native index on free-threaded CPython."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import sysconfig


def main() -> int:
    if int(sysconfig.get_config_var("Py_GIL_DISABLED") or 0) != 1:
        raise RuntimeError("this qualification requires a free-threaded CPython build")
    is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if not callable(is_gil_enabled):
        raise RuntimeError("free-threaded runtime does not expose sys._is_gil_enabled")
    if is_gil_enabled():
        raise RuntimeError("qualification must start with -X gil=0")

    candidates = sorted(Path("src/staqtapp_tds").glob("_native_index*.so"))
    if len(candidates) != 1:
        raise RuntimeError(
            "expected exactly one free-threaded native extension, "
            f"found {[str(path) for path in candidates]!r}"
        )
    spec = importlib.util.spec_from_file_location("_native_index", candidates[0])
    if spec is None or spec.loader is None:
        raise RuntimeError("could not create extension loader")
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except ImportError as exc:
        if "rejects free-threaded CPython" not in str(exc):
            raise
    else:
        raise RuntimeError("free-threaded native module import was not rejected")

    if is_gil_enabled():
        raise RuntimeError("rejected import unexpectedly enabled the compatibility GIL")
    print("free-threaded native admission rejected safely")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

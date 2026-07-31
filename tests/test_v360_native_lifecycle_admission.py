from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


MODULE_INIT = "multiphase-pep489-v1"
MULTI_INTERPRETER_POLICY = "reject-subinterpreters-v1"
GIL_POLICY = "compatibility-gil-required-v1"
REINITIALIZATION_POLICY = "process-restart-required-v1"
FROZEN_CONTRACT = "immutable-rehash-copy;lock-free-read-v1"
PACKED_CONTRACT = (
    "keys-bytes;offsets-le64;handles-le-i64;caller-owned-output-v1"
)


def require_native():
    try:
        from staqtapp_tds import _native_index
    except Exception:
        pytest.skip("native index extension is not built")
    return _native_index


def _direct_extension_code(body: str) -> str:
    return f"""
import importlib.util
from pathlib import Path

candidates = sorted(Path('src/staqtapp_tds').glob('_native_index*.so'))
if len(candidates) != 1:
    raise RuntimeError(f'expected one native extension, found {{candidates!r}}')
path = candidates[0]
{body}
"""


def test_v360_native_lifecycle_policies_are_explicit_and_reported() -> None:
    native = require_native()
    from staqtapp_tds.native.manager import NativeEngineManager

    assert native.TDS_NATIVE_MODULE_INIT == MODULE_INIT
    assert native.TDS_NATIVE_MULTI_INTERPRETER_POLICY == (
        MULTI_INTERPRETER_POLICY
    )
    assert native.TDS_NATIVE_GIL_POLICY == GIL_POLICY
    assert native.TDS_NATIVE_REINITIALIZATION_POLICY == (
        REINITIALIZATION_POLICY
    )
    assert "lifecycle_fail_closed" in native.TDS_NATIVE_CAPABILITIES.split(",")

    # The lifecycle rebase must not silently change the already-qualified frozen
    # request-path contracts.
    assert native.TDS_NATIVE_FROZEN_INDEX_CONTRACT == FROZEN_CONTRACT
    assert native.TDS_NATIVE_PACKED_LOOKUP_CONTRACT == PACKED_CONTRACT

    module, report = NativeEngineManager().inspect_module(
        "staqtapp_tds._native_index"
    )
    assert module is native
    assert report.compatible is True
    assert report.capabilities["module_init"] == MODULE_INIT
    assert report.capabilities["multi_interpreter_policy"] == (
        MULTI_INTERPRETER_POLICY
    )
    assert report.capabilities["gil_policy"] == GIL_POLICY
    assert report.capabilities["reinitialization_policy"] == (
        REINITIALIZATION_POLICY
    )


def test_v360_normal_import_reuses_the_admitted_module() -> None:
    native = require_native()
    again = importlib.import_module("staqtapp_tds._native_index")
    assert again is native


def test_v360_duplicate_live_native_module_import_fails_closed() -> None:
    require_native()
    root = Path(__file__).resolve().parents[1]
    code = _direct_extension_code(
        """
spec = importlib.util.spec_from_file_location('_native_index', path)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
try:
    duplicate_spec = importlib.util.spec_from_file_location('_native_index', path)
    duplicate = importlib.util.module_from_spec(duplicate_spec)
    duplicate_spec.loader.exec_module(duplicate)
except ImportError as exc:
    if 'one process-lifetime module' not in str(exc):
        raise
else:
    raise AssertionError('duplicate live native module import was accepted')
assert native.TDS_NATIVE_MODULE_INIT == 'multiphase-pep489-v1'
"""
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        completed.stdout + "\n" + completed.stderr
    )


def test_v360_module_reinitialization_requires_process_restart() -> None:
    require_native()
    root = Path(__file__).resolve().parents[1]
    code = _direct_extension_code(
        """
import gc

spec = importlib.util.spec_from_file_location('_native_index', path)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
del native, spec
gc.collect()
try:
    second_spec = importlib.util.spec_from_file_location('_native_index', path)
    second = importlib.util.module_from_spec(second_spec)
    second_spec.loader.exec_module(second)
except ImportError as exc:
    if 'one process-lifetime module' not in str(exc):
        raise
else:
    raise AssertionError('repeat process initialization was accepted')
"""
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        completed.stdout + "\n" + completed.stderr
    )


def test_v360_module_source_declares_guarded_interpreter_and_gil_slots() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "staqtapp_tds"
        / "_native_index.c"
    ).read_text(encoding="utf-8")
    assert "PyModuleDef_Init(&moduledef)" in source
    assert "PyModule_Create(&moduledef)" not in source
    assert ".m_size = sizeof(NativeModuleState)" in source
    assert "Py_mod_multiple_interpreters" in source
    assert "Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED" in source
    assert "Py_mod_gil" in source
    assert "Py_MOD_GIL_USED" in source
    assert "g_native_module_instance_active" in source

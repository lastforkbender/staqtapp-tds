#!/usr/bin/env python3
"""Run the v3.6 Foundation Closure audit without importing the full package."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "staqtapp_tds"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_foundation_module():
    package = types.ModuleType("staqtapp_tds")
    package.__path__ = [str(PACKAGE_ROOT)]  # type: ignore[attr-defined]
    sys.modules.setdefault("staqtapp_tds", package)
    native_package = types.ModuleType("staqtapp_tds.native")
    native_package.__path__ = [str(PACKAGE_ROOT / "native")]  # type: ignore[attr-defined]
    sys.modules.setdefault("staqtapp_tds.native", native_package)
    _load("staqtapp_tds.version", PACKAGE_ROOT / "version.py")
    return _load(
        "staqtapp_tds.native.foundation",
        PACKAGE_ROOT / "native" / "foundation.py",
    )


def main() -> int:
    return int(_load_foundation_module().main())


if __name__ == "__main__":
    raise SystemExit(main())

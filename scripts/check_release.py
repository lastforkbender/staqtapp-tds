#!/usr/bin/env python3
"""Release sanity checks for Staqtapp-TDS source archives."""
from __future__ import annotations

import pathlib
import os
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "3.1.2"
BANNED_SUFFIXES = {".so", ".pyd", ".dll", ".dylib", ".pyc"}
BANNED_DIRS = {"__pycache__", ".pytest_cache"}


def fail(message: str) -> int:
    print(f"release check failed: {message}", file=sys.stderr)
    return 1


def main() -> int:
    version_py = ROOT / "src" / "staqtapp_tds" / "version.py"
    if f'__version__ = "{EXPECTED_VERSION}"' not in version_py.read_text():
        return fail("src/staqtapp_tds/version.py has an unexpected version")

    pyproject = ROOT / "pyproject.toml"
    if f'version = "{EXPECTED_VERSION}"' not in pyproject.read_text():
        return fail("pyproject.toml has an unexpected version")

    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in BANNED_DIRS for part in rel.parts):
            offenders.append(str(rel))
        elif path.is_file() and path.suffix in BANNED_SUFFIXES:
            offenders.append(str(rel))
    if offenders:
        return fail("source archive contains banned artifacts: " + ", ".join(offenders[:20]))

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run([sys.executable, "tools/generate_result_code_docs.py"], cwd=ROOT, check=True, env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

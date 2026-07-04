"""Generate TDSResult code documentation from the runtime registry.

The source of truth is ``src/staqtapp_tds/result.py``. This tool writes the
machine-readable JSON and human-readable Markdown references from that registry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from staqtapp_tds.result import TDS_RESULT_CODES  # noqa: E402

JSON_PATH = ROOT / "docs" / "TDS_RESULT_CODES.json"
MD_PATH = ROOT / "docs" / "TDS_RESULT_CODES.md"


def sorted_codes() -> dict[str, dict[str, object]]:
    return {code: TDS_RESULT_CODES[code] for code in sorted(TDS_RESULT_CODES)}


def write_json() -> None:
    JSON_PATH.write_text(json.dumps(sorted_codes(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown() -> None:
    rows = []
    for code, info in sorted_codes().items():
        rows.append(
            "| `{code}` | `{ok}` | {surface} | {value} | {category} | {severity} | `{retryable}` | {description} |".format(
                code=code,
                ok=info.get("ok"),
                surface=info.get("surface") or "",
                value="None" if info.get("value") is None else info.get("value"),
                category=info.get("category") or "",
                severity=info.get("severity") or "",
                retryable=info.get("retryable"),
                description=info.get("description") or "",
            )
        )
    MD_PATH.write_text(
        "\n".join([
            "# TDSResult Return Code Reference",
            "",
            "This file is generated from `src/staqtapp_tds/result.py`.",
            "The runtime source of truth is `TDSResultCode` plus `TDS_RESULT_REGISTRY`; this Markdown file and `TDS_RESULT_CODES.json` must not be hand-edited.",
            "",
            "Public non-halting APIs return `TDSResult`. Callers should branch on `result.ok` and `result.code`, then read `result.value` and optional `result.meta`.",
            "",
            "## Envelope",
            "",
            "```python",
            'TDSResult(ok: bool, code: str, message: str, name: str = "", path: str = "", value: Any = None, meta: dict = {})',
            "```",
            "",
            "## Runtime parsing",
            "",
            "```python",
            "from staqtapp_tds import TDSResultCode, result_info",
            "",
            "result = directory.read(\"agent_state\")",
            "if result.ok:",
            "    value = result.value",
            "elif result.code == TDSResultCode.READ_MISSING.value:",
            "    ...",
            "else:",
            "    info = result_info(result.code)",
            "```",
            "",
            "## Compatibility rule",
            "",
            "`read()`, `write()`, and `delete()` are result-first public APIs. Explicit raw/legacy migration surfaces are named `read_value()`, `write_entry()`, and `delete_entry()` so non-halting public code does not confuse raw objects with operation status.",
            "",
            "## Codes",
            "",
            "| Code | ok | Surface | value | Category | Severity | Retryable | Description |",
            "|---|---:|---|---|---|---|---:|---|",
            *rows,
            "",
        ]),
        encoding="utf-8",
    )


def main() -> int:
    write_json()
    write_markdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

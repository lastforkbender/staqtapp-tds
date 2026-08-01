#!/usr/bin/env python3
"""Update v3.6 candidate status without changing README media or links."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact source block, found {count}")
    return text.replace(old, new, 1)


def _images(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', text, re.IGNORECASE))


def _links(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"(?<!!)\[[^]]+\]\(([^)\s]+)", text))


def _write_preserving_surfaces(path: Path, transform) -> None:
    before = path.read_text(encoding="utf-8")
    before_images = _images(before)
    before_links = _links(before)
    if len(before_images) != 19:
        raise SystemExit(f"{path.name}: expected 19 Browser screenshots")

    after = transform(before)
    if _images(after) != before_images:
        raise SystemExit(f"{path.name}: screenshot targets or order changed")
    if _links(after) != before_links:
        raise SystemExit(f"{path.name}: important Markdown links changed")
    path.write_text(after, encoding="utf-8", newline="\n")


def _english(text: str) -> str:
    text = _replace_once(
        text,
        "> **v3.6.0 Foundation Closure**\n>\n> This release closes",
        "> **v3.6.0 Foundation Closure source candidate**\n>\n> This source candidate closes",
        label="English candidate heading",
    )
    text = _replace_once(
        text,
        "# Staqtapp-TDS v3.6.0\n\n**Temporal Directory System",
        "# Staqtapp-TDS v3.6.0\n\n> **Repository status:** `3.6.0` is the qualified Foundation source candidate. "
        "The current production PyPI release remains `3.5.3.post2` until the exact "
        "merged and tagged release matrix passes and publication completes.\n\n"
        "**Temporal Directory System",
        label="English repository status",
    )
    text = _replace_once(
        text,
        "# Published release from production PyPI; includes both UIs\n"
        "python -m pip install staqtapp-tds==3.6.0\n\n"
        "# Launch the main TDS telemetry UI",
        "# Current production PyPI release; includes both UIs\n"
        "python -m pip install staqtapp-tds==3.5.3.post2\n\n"
        "# Candidate package identity; use this command only after 3.6.0 publication\n"
        "python -m pip install staqtapp-tds==3.6.0\n\n"
        "# Launch the main TDS telemetry UI",
        label="English install status",
    )
    return text


def _japanese(text: str) -> str:
    text = _replace_once(
        text,
        "# Staqtapp-TDS v3.6.0\n\n> **v3.6.0 Foundation Closure:**",
        "# Staqtapp-TDS v3.6.0\n\n"
        "> **Repository status:** `3.6.0` は qualified Foundation source candidate です。"
        "Exact merged/tagged release matrix と publication が完了するまで、production PyPI "
        "release は `3.5.3.post2` のままです。\n\n"
        "> **v3.6.0 Foundation Closure source candidate:**",
        label="Japanese repository status",
    )
    text = _replace_once(
        text,
        "# Production PyPI corrective release（両方の UI を含む）\n"
        "python -m pip install staqtapp-tds==3.6.0\n\n"
        "# main TDS telemetry UI を起動",
        "# Current production PyPI release（両方の UI を含む）\n"
        "python -m pip install staqtapp-tds==3.5.3.post2\n\n"
        "# Candidate package identity（3.6.0 publication 完了後に使用）\n"
        "python -m pip install staqtapp-tds==3.6.0\n\n"
        "# main TDS telemetry UI を起動",
        label="Japanese install status",
    )
    return text


def main() -> int:
    _write_preserving_surfaces(ROOT / "README.md", _english)
    _write_preserving_surfaces(ROOT / "README_ja.md", _japanese)
    print("README status updated; 19 screenshots and all Markdown links preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

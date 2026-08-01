#!/usr/bin/env python3
"""Apply and verify additive v3.7 README current-status blocks.

The updater is preservation-first. It records the complete ordered image and
Markdown-link targets before the first update and refuses any later README state
that removes, changes, reorders, or silently replaces them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs" / "readme_targets_v370.json"
ENGLISH_PATH = ROOT / "README.md"
JAPANESE_PATH = ROOT / "README_ja.md"
FORMAT = "tds.v370.readme-target-manifest.v1"

BEGIN = "<!-- TDS-V370-CURRENT-STATUS:BEGIN -->"
END = "<!-- TDS-V370-CURRENT-STATUS:END -->"

ENGLISH_STATUS = f"""{BEGIN}
> **Current development status — v3.7 Atomic Generation convergence**
>
> The published package remains `3.5.3.post2` while the v3.6 Foundation Closure
> and v3.7 release trains complete their exact merge and tag gates. This branch
> now contains real Atomic Generation code: authoritative original bytes,
> content-addressed chunks, packed row offsets and anchors, rooted closure
> evidence, append-only receipts, cross-process compare-and-swap publication,
> crash recovery, generation-pinned leases, deterministic rollback, and
> non-destructive retirement. Eaglegate remains separate, unmerged, and inactive.
>
> The 19 Browser screenshots and every existing programmer, API, changelog,
> language, license, and release link below are preserved unchanged.
{END}
"""

JAPANESE_STATUS = f"""{BEGIN}
> **現在の development status — v3.7 Atomic Generation convergence**
>
> 公開 package は、v3.6 Foundation Closure と v3.7 の正確な merge / tag gate が
> 完了するまで `3.5.3.post2` のままです。この branch には、authoritative original
> bytes、content-addressed chunk、packed row offset / anchor、rooted closure evidence、
> append-only receipt、cross-process compare-and-swap publication、crash recovery、
> generation-pinned lease、deterministic rollback、non-destructive retirement を含む
> 実際の Atomic Generation code が追加されています。Eaglegate は分離されたままで、
> 未 merge・inactive です。
>
> 以下の Browser screenshot 19 枚と、既存の programmer / API / changelog / language /
> license / release link はすべて変更せず保持します。
{END}
"""

BROWSER_FILES = (
    "01-dashboard-1280x800.png",
    "02-engine-health-1280x800.png",
    "03-real-time-metrics-1280x800.png",
    "04-transition-timeline-1280x800.png",
    "05-event-ring-monitor-1280x800.png",
    "06-pressure-diagnostics-1280x800.png",
    "07-csv-interpole-1280x800.png",
    "08-snapshot-explorer-1280x800.png",
    "09-lock-contention-1280x800.png",
    "10-workload-analytics-1280x800.png",
    "11-spiral-rank-1280x800.png",
    "12-index-analytics-1280x800.png",
    "13-storage-analytics-1280x800.png",
    "14-comparative-views-1280x800.png",
    "15-recovery-planner-1280x800.png",
    "16-policy-proposals-1280x800.png",
    "17-alerts-events-1280x800.png",
    "18-security-1280x800.png",
    "19-settings-1280x800.png",
)

IMPORTANT_LINK_FRAGMENTS = (
    "README_ja.md",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "Programmers_API_Reference.md",
    "Staqtapp_TDS_API_Surface_Reference.pdf",
    "Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
)


def _targets(text: str) -> dict[str, list[str]]:
    return {
        "images": re.findall(
            r'<img\b[^>]*?\bsrc="([^"]+)"', text, flags=re.IGNORECASE
        ),
        "markdown_links": re.findall(r"(?<!!)\[[^]]+\]\(([^)\s]+)", text),
    }


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_status(text: str) -> str:
    if BEGIN not in text and END not in text:
        return text
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("README has a malformed v3.7 current-status marker")
    start = text.index(BEGIN)
    end = text.index(END, start) + len(END)
    while end < len(text) and text[end] in "\r\n":
        end += 1
    return text[:start] + text[end:]


def _apply_block(text: str, block: str) -> str:
    base = _strip_status(text).lstrip("\r\n")
    return block.rstrip() + "\n\n" + base


def _manifest_for(english: str, japanese: str) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "english": _targets(english),
        "japanese": _targets(japanese),
        "original_english_sha256": _sha256_text(english),
        "original_japanese_sha256": _sha256_text(japanese),
    }


def _write_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load_manifest() -> dict[str, Any]:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("missing or malformed v3.7 README target manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ValueError("README target manifest has the wrong format")
    return manifest


def _verify_one(
    *,
    label: str,
    text: str,
    expected_block: str,
    expected_targets: dict[str, list[str]],
) -> None:
    if not text.startswith(expected_block.rstrip() + "\n\n"):
        raise ValueError(f"{label} README is missing the exact current-status block")
    observed = _targets(text)
    if observed != expected_targets:
        raise ValueError(f"{label} README image/link targets changed")
    if len(observed["images"]) != 19:
        raise ValueError(f"{label} README must preserve exactly 19 Browser images")
    for filename in BROWSER_FILES:
        if not any(filename in target for target in observed["images"]):
            raise ValueError(f"{label} README lost Browser image {filename}")
    combined_links = "\n".join(observed["markdown_links"])
    for fragment in IMPORTANT_LINK_FRAGMENTS:
        if fragment in {"README.md", "README_ja.md"}:
            continue
        if fragment not in combined_links:
            raise ValueError(f"{label} README lost important link {fragment}")


def _verify_pair_links(manifest: dict[str, Any]) -> None:
    pair_links = "\n".join(
        [
            *manifest["english"]["markdown_links"],
            *manifest["japanese"]["markdown_links"],
        ]
    )
    for fragment in IMPORTANT_LINK_FRAGMENTS:
        if fragment not in pair_links:
            raise ValueError(f"README pair lost important link {fragment}")


def apply() -> None:
    english = ENGLISH_PATH.read_text(encoding="utf-8")
    japanese = JAPANESE_PATH.read_text(encoding="utf-8")
    if MANIFEST_PATH.exists():
        manifest = _load_manifest()
    else:
        manifest = _manifest_for(_strip_status(english), _strip_status(japanese))
        _write_manifest(manifest)

    updated_english = _apply_block(english, ENGLISH_STATUS)
    updated_japanese = _apply_block(japanese, JAPANESE_STATUS)
    _verify_one(
        label="English",
        text=updated_english,
        expected_block=ENGLISH_STATUS,
        expected_targets=manifest["english"],
    )
    _verify_one(
        label="Japanese",
        text=updated_japanese,
        expected_block=JAPANESE_STATUS,
        expected_targets=manifest["japanese"],
    )
    _verify_pair_links(manifest)
    ENGLISH_PATH.write_text(updated_english, encoding="utf-8", newline="\n")
    JAPANESE_PATH.write_text(updated_japanese, encoding="utf-8", newline="\n")


def check() -> None:
    manifest = _load_manifest()
    english = ENGLISH_PATH.read_text(encoding="utf-8")
    japanese = JAPANESE_PATH.read_text(encoding="utf-8")
    _verify_one(
        label="English",
        text=english,
        expected_block=ENGLISH_STATUS,
        expected_targets=manifest["english"],
    )
    _verify_one(
        label="Japanese",
        text=japanese,
        expected_block=JAPANESE_STATUS,
        expected_targets=manifest["japanese"],
    )
    _verify_pair_links(manifest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="update_readme_status_v370.py")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.apply:
            apply()
        else:
            check()
    except (OSError, ValueError, TypeError) as exc:
        print(f"v3.7 README contract failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

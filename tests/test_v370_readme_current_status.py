from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

SCREENSHOTS = tuple(
    f"{index:02d}-{name}-1280x800.png"
    for index, name in enumerate(
        (
            "dashboard",
            "engine-health",
            "real-time-metrics",
            "transition-timeline",
            "event-ring-monitor",
            "pressure-diagnostics",
            "csv-interpole",
            "snapshot-explorer",
            "lock-contention",
            "workload-analytics",
            "spiral-rank",
            "index-analytics",
            "storage-analytics",
            "comparative-views",
            "recovery-planner",
            "policy-proposals",
            "alerts-events",
            "security",
            "settings",
        ),
        start=1,
    )
)

ENGLISH_LINKS = (
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/README_ja.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/CHANGELOG.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/LICENSE",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/docs/reference/Programmers_API_Reference.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
)

JAPANESE_LINKS = (
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "docs/reference/Programmers_API_Reference.md",
    "tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
)

ENGLISH_LINK_SEQUENCE = (
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/README_ja.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/CHANGELOG.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/docs/reference/Programmers_API_Reference.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/tree/v3.5.3",
    "https://pypi.org/project/staqtapp-tds/3.5.3/",
    "https://github.com/lastforkbender/staqtapp-tds/actions/runs/29500270923",
    "https://github.com/lastforkbender/staqtapp-tds/releases/tag/v3.5.3",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/LICENSE",
)

JAPANESE_LINK_SEQUENCE = (
    "tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
    "README.md",
    "tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "CHANGELOG.md",
    "tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
    "docs/reference/Programmers_API_Reference.md",
    "tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "LICENSE",
)


def sources(text: str):
    return re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', text, flags=re.IGNORECASE)


def links(text: str):
    return tuple(re.findall(r"(?<!!)\[[^]]+\]\(([^)\s]+)", text))


def test_english_readme_reports_exact_current_release_status():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "# Staqtapp-TDS v3.8.2" in text.splitlines()
    assert "# Staqtapp-TDS v3.8.2 release candidate" not in text
    assert "source candidate under review, not a published package" not in text
    assert "NON-RELEASEABLE" not in text
    assert "v3.8.2 is the production release" in text
    assert "python -m pip install staqtapp-tds==3.6.0" not in text
    assert "python -m pip install staqtapp-tds==3.8.1" not in text
    assert "python -m pip install staqtapp-tds==3.8.2" in text
    assert "`docs/130_v370_Atomic_Generation_Authority.md`" in text
    assert "src/staqtapp_tds/generation/" in text
    assert "src/staqtapp_tds/eaglegate/" in text
    assert "src/staqtapp_tds/trace_rank/" in text
    assert "`docs/131_v380_Eaglegate_Real_vLLM_Shadow.md`" in text
    assert "`docs/132_v380_Packed_Waypoint_CSR_Graph.md`" in text
    assert "manual credentialed H100 workflow has not been executed" in text
    assert "Eaglegate remains shadow/target-only" in text


def test_japanese_readme_reports_exact_current_release_status():
    text = (ROOT / "README_ja.md").read_text(encoding="utf-8")
    normalized = " ".join(text.replace(">", " ").split())
    assert "# Staqtapp-TDS v3.8.2" in text.splitlines()
    assert "# Staqtapp-TDS v3.8.2 release candidate" not in text
    assert "published package ではありません" not in text
    assert "NON-RELEASEABLE" not in text
    assert "v3.8.2 は production release" in text
    assert "python -m pip install staqtapp-tds==3.6.0" not in text
    assert "python -m pip install staqtapp-tds==3.8.1" not in text
    assert "python -m pip install staqtapp-tds==3.8.2" in text
    assert "`docs/130_v370_Atomic_Generation_Authority.md`" in text
    assert "src/staqtapp_tds/generation/" in text
    assert "src/staqtapp_tds/eaglegate/" in text
    assert "src/staqtapp_tds/trace_rank/" in text
    assert "`docs/131_v380_Eaglegate_Real_vLLM_Shadow.md`" in text
    assert "`docs/132_v380_Packed_Waypoint_CSR_Graph.md`" in text
    assert "Manual credentialed H100 workflow は未実行" in text
    assert "Eaglegate は shadow / target-only のまま" in normalized


def test_all_19_english_screenshots_and_important_links_are_preserved():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    image_sources = sources(text)
    assert len(image_sources) == 19
    for filename in SCREENSHOTS:
        assert any(source.endswith("/" + filename) for source in image_sources)
    assert image_sources == [
        "https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/"
        f"v3.5.3/docs/screenshots/browser_pages/{filename}"
        for filename in SCREENSHOTS
    ]
    for link in ENGLISH_LINKS:
        assert link in text
    assert links(text) == ENGLISH_LINK_SEQUENCE


def test_all_19_japanese_screenshots_and_important_links_are_preserved():
    text = (ROOT / "README_ja.md").read_text(encoding="utf-8")
    image_sources = sources(text)
    assert len(image_sources) == 19
    for filename in SCREENSHOTS:
        assert any(source.endswith("/" + filename) for source in image_sources)
    assert image_sources == [
        f"docs/screenshots/browser_pages/{filename}" for filename in SCREENSHOTS
    ]
    for link in JAPANESE_LINKS:
        assert link in text
    assert links(text) == JAPANESE_LINK_SEQUENCE

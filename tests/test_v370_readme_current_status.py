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


def sources(text: str):
    return re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', text, flags=re.IGNORECASE)


def test_english_readme_reports_exact_current_candidate_status():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "# Staqtapp-TDS v3.7.0 Atomic Generation Authority candidate" in text
    assert "current production PyPI release remains `3.5.3.post2`" in text
    assert "python -m pip install staqtapp-tds==3.5.3.post2" in text
    assert "python -m pip install staqtapp-tds==3.6.0" not in text
    assert "python -m pip install staqtapp-tds==3.7.0" not in text
    assert "`docs/130_v370_Atomic_Generation_Authority.md`" in text
    assert "src/staqtapp_tds/generation/" in text


def test_japanese_readme_reports_exact_current_candidate_status():
    text = (ROOT / "README_ja.md").read_text(encoding="utf-8")
    assert "# Staqtapp-TDS v3.7.0 Atomic Generation Authority candidate" in text
    assert "Current production PyPI release は `3.5.3.post2`" in text
    assert "python -m pip install staqtapp-tds==3.5.3.post2" in text
    assert "python -m pip install staqtapp-tds==3.6.0" not in text
    assert "python -m pip install staqtapp-tds==3.7.0" not in text
    assert "`docs/130_v370_Atomic_Generation_Authority.md`" in text
    assert "src/staqtapp_tds/generation/" in text


def test_all_19_english_screenshots_and_important_links_are_preserved():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    image_sources = sources(text)
    assert len(image_sources) == 19
    for filename in SCREENSHOTS:
        assert any(source.endswith("/" + filename) for source in image_sources)
    for link in ENGLISH_LINKS:
        assert link in text


def test_all_19_japanese_screenshots_and_important_links_are_preserved():
    text = (ROOT / "README_ja.md").read_text(encoding="utf-8")
    image_sources = sources(text)
    assert len(image_sources) == 19
    for filename in SCREENSHOTS:
        assert any(source.endswith("/" + filename) for source in image_sources)
    for link in JAPANESE_LINKS:
        assert link in text


def test_readme_updater_contains_pre_and_post_preservation_checks():
    source = (ROOT / "tools" / "update_v370_readme_status.py").read_text(
        encoding="utf-8"
    )
    assert "before_images = image_sources(original)" in source
    assert "if after_images != before_images" in source
    assert "important link removed" in source

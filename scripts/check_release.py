#!/usr/bin/env python3
"""Release sanity checks for Staqtapp-TDS source archives."""
from __future__ import annotations

import pathlib
import hashlib
import os
import re
import struct
import tomllib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "3.5.3.post1"
BANNED_SUFFIXES = {".so", ".pyd", ".dll", ".dylib", ".pyc"}
BANNED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"}
BROWSER_CAPTURES = (
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
PYPI_README_IMAGE_PREFIX = (
    "https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/"
    "v3.5.3/docs/screenshots/browser_pages/"
)
PYPI_README_REQUIRED_LINKS = (
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/README_ja.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/CHANGELOG.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/LICENSE",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/docs/reference/Programmers_API_Reference.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
)


def fail(message: str) -> int:
    print(f"release check failed: {message}", file=sys.stderr)
    return 1


def main() -> int:
    version_py = ROOT / "src" / "staqtapp_tds" / "version.py"
    if f'__version__ = "{EXPECTED_VERSION}"' not in version_py.read_text():
        return fail("src/staqtapp_tds/version.py has an unexpected version")

    pyproject = ROOT / "pyproject.toml"
    project_data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = project_data.get("project", {})
    dynamic = project.get("dynamic", [])
    dynamic_version = (
        project_data.get("tool", {})
        .get("setuptools", {})
        .get("dynamic", {})
        .get("version", {})
        .get("attr")
    )
    if "version" not in dynamic:
        return fail("pyproject.toml must declare version as dynamic")
    if dynamic_version != "staqtapp_tds.version.__version__":
        return fail("pyproject.toml has an unexpected dynamic version source")
    urls = project.get("urls", {})
    if any("lastforkbender/staqtapp-tds" not in str(url) for url in urls.values()):
        return fail("project URLs do not target the release repository")

    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        expected_tag = f"v{EXPECTED_VERSION}"
        if os.environ.get("GITHUB_REF_NAME") != expected_tag:
            return fail(f"release tag must be exactly {expected_tag}")

    required_evidence = (
        ROOT / "DEV6_GUARANTEED_STORAGE_TRANSITION_STATUS.txt",
        ROOT / "DEV7_MATERIALIZATION_FAULT_QUALIFICATION_STATUS.txt",
        ROOT / "DEV8_VERIFIED_ROUND_TRIP_MIGRATION_STATUS.txt",
        ROOT / "DEV9_INCREMENTAL_IMMUTABLE_SEGMENTS_STATUS.txt",
        ROOT / "DEV10_CONTROLLED_ACTIVATION_STATUS.txt",
        ROOT / "DEV11_RELEASE_QUALIFICATION_STATUS.txt",
        ROOT / "V353_POST1_PYPI_PRESENTATION_STATUS.txt",
        ROOT / "docs" / "118_v353_dev10_Controlled_Activation.md",
        ROOT / "docs" / "119_v353_dev11_Release_Qualification.md",
    )
    missing_evidence = [str(path.relative_to(ROOT)) for path in required_evidence if not path.is_file()]
    if missing_evidence:
        return fail("missing Guaranteed Storage phase evidence: " + ", ".join(missing_evidence))
    phase11 = (ROOT / "DEV11_RELEASE_QUALIFICATION_STATUS.txt").read_text(encoding="utf-8")
    if "STATUS: LOCAL QUALIFICATION COMPLETE" not in phase11:
        return fail("Phase 11 local qualification is not recorded as complete")
    if "REMOTE REVIEW GATES REQUIRED" in phase11:
        return fail("Phase 11 still reports completed remote gates as pending")
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    if "include AUDIT_REMEDIATION_STATUS.txt DEV*_STATUS.txt" not in manifest:
        return fail("source distribution does not include immediate-root phase evidence")
    if "include V353_POST1_PYPI_PRESENTATION_STATUS.txt" not in manifest:
        return fail("source distribution does not include the post-release correction record")

    programmer_pdf = ROOT / "tds_api_docs" / "Staqtapp_TDS_Programmer_Core_API_Guide.pdf"
    if not programmer_pdf.is_file():
        return fail("missing Programmer Core API Guide")
    programmer_pdf_bytes = programmer_pdf.read_bytes()
    if b"/TDSV353SupplementPages (3)" not in programmer_pdf_bytes:
        return fail("Programmer Core API Guide is missing the v3.5.3 release supplement")
    if b"/TDSLightBlueLabelSpacing (v1)" not in programmer_pdf_bytes:
        return fail("Programmer Core API Guide is missing the corrected label-spacing marker")

    if (ROOT / ".github" / "workflows" / "publish.yml").exists():
        return fail("unsafe independent publish workflow still exists")

    capture_root = ROOT / "docs" / "screenshots" / "browser_pages"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    image_targets = re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', readme, flags=re.IGNORECASE)
    markdown_targets = re.findall(r"(?<!!)\[[^]]+\]\(([^)\s]+)", readme)
    relative_targets = [
        target
        for target in (*image_targets, *markdown_targets)
        if not target.startswith(("https://", "#", "mailto:"))
    ]
    if relative_targets:
        return fail(
            "PyPI README contains repository-relative targets: "
            + ", ".join(relative_targets)
        )
    if len(image_targets) != len(BROWSER_CAPTURES):
        return fail("PyPI README does not contain exactly 19 Browser images")
    if any(not target.startswith(PYPI_README_IMAGE_PREFIX) for target in image_targets):
        return fail("PyPI README Browser images are not pinned absolute HTTPS targets")
    missing_links = [target for target in PYPI_README_REQUIRED_LINKS if target not in readme]
    if missing_links:
        return fail("PyPI README is missing absolute document targets: " + ", ".join(missing_links))
    if "tag remains prohibited" in readme or "REMOTE REVIEW GATES REQUIRED" in readme:
        return fail("PyPI README contains obsolete pre-publication status wording")
    japanese_readme = (ROOT / "README_ja.md").read_text(encoding="utf-8")
    if "tag を作成できません" in japanese_readme:
        return fail("Japanese README contains obsolete pre-publication status wording")
    capture_digests: set[str] = set()
    for filename in BROWSER_CAPTURES:
        path = capture_root / filename
        if not path.is_file():
            return fail(f"missing Browser page capture: {filename}")
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
            return fail(f"invalid Browser page PNG: {filename}")
        if struct.unpack(">II", data[16:24]) != (1280, 800):
            return fail(f"Browser page capture is not 1280x800: {filename}")
        capture_digests.add(hashlib.sha256(data).hexdigest())
        if f"docs/screenshots/browser_pages/{filename}" not in readme:
            return fail(f"README does not embed Browser page capture: {filename}")
    if len(capture_digests) != len(BROWSER_CAPTURES):
        return fail("Browser page captures are not all distinct")
    false_capture = ROOT / "docs" / "screenshots" / "tds_browser_telemetry_overview_1280x800.png"
    if false_capture.exists() or false_capture.name in readme:
        return fail("retired misleading Browser overview is still present")

    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if ".git" in rel.parts:
            continue
        if any(part in BANNED_DIRS or part.endswith(".egg-info") for part in rel.parts):
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

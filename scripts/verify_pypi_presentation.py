#!/usr/bin/env python3
"""Verify the published PyPI description and every linked presentation asset."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT = "staqtapp-tds"
EXPECTED_IMAGE_COUNT = 19
IMAGE_PREFIX = (
    "https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/"
    "v3.5.3/docs/screenshots/browser_pages/"
)
REQUIRED_TARGETS = (
    IMAGE_PREFIX + "07-csv-interpole-1280x800.png",
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/README_ja.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/CHANGELOG.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/LICENSE",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/docs/reference/Programmers_API_Reference.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
)
STALE_WORDING = (
    "tag remains prohibited",
    "REMOTE REVIEW GATES REQUIRED",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
USER_AGENT = "staqtapp-tds-release-verifier/3.5.3.post1"


def presentation_targets(description: str) -> tuple[list[str], list[str]]:
    """Return HTML image targets and ordinary Markdown link targets."""
    images = re.findall(
        r'<img\b[^>]*?\bsrc="([^"]+)"', description, flags=re.IGNORECASE
    )
    links = re.findall(r"(?<!!)\[[^]]+\]\(([^)\s]+)", description)
    return images, links


def validate_description(description: str) -> tuple[list[str], list[str]]:
    """Validate the exact guarantees required for the public PyPI page."""
    images, links = presentation_targets(description)
    targets = [*images, *links]
    relative = [
        target
        for target in targets
        if not target.startswith(("https://", "#", "mailto:"))
    ]
    if relative:
        raise ValueError(
            "published description contains repository-relative targets: "
            + ", ".join(relative)
        )
    if len(images) != EXPECTED_IMAGE_COUNT:
        raise ValueError(
            f"published description has {len(images)} Browser images; "
            f"expected {EXPECTED_IMAGE_COUNT}"
        )
    if any(not target.startswith(IMAGE_PREFIX) for target in images):
        raise ValueError("published Browser images are not pinned absolute targets")
    missing = [target for target in REQUIRED_TARGETS if target not in targets]
    if missing:
        raise ValueError(
            "published description is missing required targets: " + ", ".join(missing)
        )
    stale = [phrase for phrase in STALE_WORDING if phrase in description]
    if stale:
        raise ValueError(
            "published description contains obsolete release wording: "
            + ", ".join(stale)
        )
    return images, links


def fetch_bytes(url: str, byte_count: int, attempts: int = 4) -> bytes:
    """Fetch enough bytes to prove a public target resolves, with brief retries."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return response.read(byte_count)
        except (HTTPError, URLError, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"public target did not resolve: {url}: {last_error}")


def load_pypi_description(version: str, attempts: int = 12) -> str:
    """Load the exact version's long description after PyPI propagation."""
    url = f"https://pypi.org/pypi/{PROJECT}/{version}/json"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            payload = json.loads(fetch_bytes(url, 8_000_000, attempts=1))
            info = payload["info"]
            if info["version"] != version:
                raise ValueError(
                    f"PyPI returned version {info['version']!r}, expected {version!r}"
                )
            if info.get("description_content_type") != "text/markdown":
                raise ValueError("PyPI long description is not Markdown")
            return str(info["description"])
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(5)
    raise RuntimeError(f"PyPI version did not become readable: {url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    version = args.version.removeprefix("v")

    try:
        description = load_pypi_description(version)
        images, links = validate_description(description)
        for image_url in images:
            if fetch_bytes(image_url, len(PNG_SIGNATURE)) != PNG_SIGNATURE:
                raise RuntimeError(f"published image target is not a PNG: {image_url}")
            print(f"verified image: {image_url}")
        for link_url in sorted(set(links)):
            if link_url.startswith(("https://",)):
                fetch_bytes(link_url, 1)
                print(f"verified link: {link_url}")
    except (ValueError, RuntimeError) as exc:
        print(f"PyPI presentation verification failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"{PROJECT} {version}: live PyPI description, "
        f"{len(images)} images, and {len(set(links))} linked targets passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

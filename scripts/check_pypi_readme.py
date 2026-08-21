#!/usr/bin/env python3
"""Validate the README screenshot contract used by package metadata."""
from __future__ import annotations

import argparse
from email import policy
from email.parser import BytesParser
from pathlib import Path
import re
import struct
import sys
from typing import Sequence
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_DIRECTORY = Path("docs/screenshots/browser_pages")
CAPTURE_FILENAMES = (
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
IMAGE_PREFIX = (
    "https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/"
    "v3.5.3/docs/screenshots/browser_pages/"
)
EXPECTED_IMAGE_URLS = tuple(f"{IMAGE_PREFIX}{name}" for name in CAPTURE_FILENAMES)
IMAGE_PATTERN = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*([\"'])(.*?)\1",
    flags=re.IGNORECASE | re.DOTALL,
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXPECTED_DIMENSIONS = (1280, 800)


class VerificationError(ValueError):
    """Raised when package presentation would be incomplete."""


def image_targets(description: str) -> tuple[str, ...]:
    """Return HTML image targets in source order."""

    return tuple(match.group(2) for match in IMAGE_PATTERN.finditer(description))


def validate_description(description: str, *, source: str) -> None:
    """Require the maintained screenshot set in its intended order."""

    actual = image_targets(description)
    if actual != EXPECTED_IMAGE_URLS:
        raise VerificationError(
            f"{source} has {len(actual)} Browser images in an unexpected order; "
            f"expected {len(EXPECTED_IMAGE_URLS)}"
        )


def validate_png(path: Path) -> None:
    """Require a readable 1280x800 PNG with an IHDR header."""

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE):
        raise VerificationError(f"{path} is not a valid PNG")
    if data[8:16] != b"\x00\x00\x00\rIHDR":
        raise VerificationError(f"{path} does not begin with IHDR")
    if struct.unpack(">II", data[16:24]) != EXPECTED_DIMENSIONS:
        raise VerificationError(f"{path} is not 1280x800")


def validate_local_captures(root: Path) -> None:
    """Require a local source image for every package-description target."""

    capture_root = root / CAPTURE_DIRECTORY
    for filename in CAPTURE_FILENAMES:
        validate_png(capture_root / filename)


def wheel_description(wheel: Path) -> str:
    """Read the Markdown long description from wheel metadata."""

    try:
        with ZipFile(wheel) as archive:
            metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise VerificationError(
                    f"{wheel} contains {len(metadata_names)} METADATA files; expected one"
                )
            metadata = BytesParser(policy=policy.default).parsebytes(
                archive.read(metadata_names[0])
            )
    except (OSError, BadZipFile, KeyError) as exc:
        raise VerificationError(f"cannot inspect {wheel}: {exc}") from exc

    content_type = str(metadata.get("Description-Content-Type", ""))
    if content_type.split(";", 1)[0].strip().lower() != "text/markdown":
        raise VerificationError(f"{wheel} does not contain a Markdown description")
    description = metadata.get_payload()
    if not isinstance(description, str):
        raise VerificationError(f"{wheel} description is not text")
    return description


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--wheel", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        validate_description(
            (root / "README.md").read_text(encoding="utf-8"),
            source=str(root / "README.md"),
        )
        validate_local_captures(root)
        if args.wheel is not None:
            wheel = args.wheel.resolve()
            validate_description(wheel_description(wheel), source=str(wheel))
    except (OSError, VerificationError) as exc:
        print(f"README verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified README and {len(CAPTURE_FILENAMES)} Browser screenshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

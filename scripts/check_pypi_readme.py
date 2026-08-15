#!/usr/bin/env python3
"""Prove that PyPI will receive the intended Browser screenshots.

The default check is fully offline: it validates the English README image
targets and the corresponding repository PNGs. ``--network`` additionally
proves that every immutable URL serves the exact local bytes. ``--wheel``
checks the long description embedded in a built wheel.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
import hashlib
from pathlib import Path
import re
import struct
import sys
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
IMMUTABLE_IMAGE_PREFIX = (
    "https://raw.githubusercontent.com/lastforkbender/staqtapp-tds/"
    "v3.5.3/docs/screenshots/browser_pages/"
)
EXPECTED_IMAGE_URLS = tuple(
    f"{IMMUTABLE_IMAGE_PREFIX}{filename}" for filename in CAPTURE_FILENAMES
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXPECTED_DIMENSIONS = (1280, 800)
USER_AGENT = "staqtapp-tds-pypi-readme-check/3.8.1"
IMAGE_PATTERN = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*([\"'])(.*?)\1",
    flags=re.IGNORECASE | re.DOTALL,
)


class VerificationError(ValueError):
    """Raised when the pre-publication presentation contract is broken."""


@dataclass(frozen=True)
class CaptureEvidence:
    """Validated evidence for one repository screenshot."""

    path: Path
    digest: str
    byte_count: int


def image_targets(description: str) -> tuple[str, ...]:
    """Return HTML image ``src`` targets in their source order."""

    return tuple(match.group(2) for match in IMAGE_PATTERN.finditer(description))


def validate_description(description: str, *, source: str) -> tuple[str, ...]:
    """Require the exact immutable screenshot URL list, including order."""

    actual = image_targets(description)
    if actual == EXPECTED_IMAGE_URLS:
        return actual

    if len(actual) != len(EXPECTED_IMAGE_URLS):
        raise VerificationError(
            f"{source} contains {len(actual)} image targets; "
            f"expected exactly {len(EXPECTED_IMAGE_URLS)}"
        )

    mismatch = next(
        index
        for index, (found, expected) in enumerate(
            zip(actual, EXPECTED_IMAGE_URLS, strict=True), start=1
        )
        if found != expected
    )
    raise VerificationError(
        f"{source} does not preserve the exact immutable image URL order: "
        f"position {mismatch} is {actual[mismatch - 1]!r}, "
        f"expected {EXPECTED_IMAGE_URLS[mismatch - 1]!r}"
    )


def validate_png_bytes(data: bytes, *, source: str) -> tuple[int, int]:
    """Validate the PNG signature, IHDR placement, and required dimensions."""

    if len(data) < 24 or not data.startswith(PNG_SIGNATURE):
        raise VerificationError(f"{source} does not have a valid PNG signature")
    if data[8:16] != b"\x00\x00\x00\rIHDR":
        raise VerificationError(f"{source} does not begin with a PNG IHDR chunk")
    dimensions = struct.unpack(">II", data[16:24])
    if dimensions != EXPECTED_DIMENSIONS:
        raise VerificationError(
            f"{source} is {dimensions[0]}x{dimensions[1]}; "
            f"expected {EXPECTED_DIMENSIONS[0]}x{EXPECTED_DIMENSIONS[1]}"
        )
    return dimensions


def validate_local_captures(root: Path) -> dict[str, CaptureEvidence]:
    """Validate every local screenshot and bind it to its immutable URL."""

    captures: dict[str, CaptureEvidence] = {}
    capture_root = root / CAPTURE_DIRECTORY
    for filename, url in zip(CAPTURE_FILENAMES, EXPECTED_IMAGE_URLS, strict=True):
        if not url.endswith(f"/{filename}"):
            raise VerificationError(
                f"immutable image target does not match local filename {filename}"
            )
        path = capture_root / filename
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise VerificationError(f"cannot read local screenshot {path}: {exc}") from exc
        validate_png_bytes(data, source=str(path))
        captures[url] = CaptureEvidence(
            path=path,
            digest=hashlib.sha256(data).hexdigest(),
            byte_count=len(data),
        )
    return captures


def _content_type(response: object) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    get_content_type = getattr(headers, "get_content_type", None)
    if callable(get_content_type):
        return str(get_content_type()).lower()
    value = headers.get("Content-Type", "")
    return str(value).split(";", 1)[0].strip().lower()


def fetch_remote_png(
    url: str,
    *,
    opener: Callable[..., object] | None = None,
    timeout: float = 30.0,
) -> bytes:
    """Fetch one public PNG and require a successful PNG HTTP response."""

    request = Request(
        url,
        headers={"Accept": "image/png", "User-Agent": USER_AGENT},
    )
    open_url = urlopen if opener is None else opener
    try:
        with open_url(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None:
                getcode = getattr(response, "getcode", None)
                status = getcode() if callable(getcode) else None
            if status != 200:
                raise VerificationError(f"{url} returned HTTP {status}, expected 200")
            content_type = _content_type(response)
            if content_type != "image/png":
                raise VerificationError(
                    f"{url} returned Content-Type {content_type!r}, expected 'image/png'"
                )
            return response.read()
    except VerificationError:
        raise
    except (HTTPError, URLError, OSError) as exc:
        raise VerificationError(f"could not fetch {url}: {exc}") from exc


def validate_network_captures(
    captures: Mapping[str, CaptureEvidence],
    *,
    opener: Callable[..., object] | None = None,
    timeout: float = 30.0,
) -> None:
    """Require every public URL to serve the exact validated local PNG."""

    if tuple(captures) != EXPECTED_IMAGE_URLS:
        raise VerificationError("local capture evidence is incomplete or out of order")
    for url in EXPECTED_IMAGE_URLS:
        evidence = captures[url]
        data = fetch_remote_png(url, opener=opener, timeout=timeout)
        validate_png_bytes(data, source=url)
        remote_digest = hashlib.sha256(data).hexdigest()
        if len(data) != evidence.byte_count or remote_digest != evidence.digest:
            raise VerificationError(
                f"{url} does not match local screenshot {evidence.path} "
                f"(remote sha256 {remote_digest}, local sha256 {evidence.digest})"
            )


def wheel_description(wheel: Path) -> str:
    """Read the Markdown long description from one wheel's core metadata."""

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
        raise VerificationError(f"cannot inspect wheel {wheel}: {exc}") from exc

    content_type = str(metadata.get("Description-Content-Type", ""))
    if content_type.split(";", 1)[0].strip().lower() != "text/markdown":
        raise VerificationError(
            f"{wheel} Description-Content-Type is {content_type!r}, expected text/markdown"
        )
    description = metadata.get_payload()
    if not isinstance(description, str):
        raise VerificationError(f"{wheel} METADATA Description is not text")
    return description


def validate_wheel(wheel: Path) -> tuple[str, ...]:
    """Require wheel METADATA to retain the exact README screenshot targets."""

    return validate_description(
        wheel_description(wheel),
        source=f"{wheel} METADATA Description",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify PyPI README screenshot presentation before publication."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root (defaults to the script's repository)",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="fetch all immutable image URLs and compare them byte-for-byte",
    )
    parser.add_argument(
        "--wheel",
        type=Path,
        help="wheel whose METADATA Description must preserve the image URLs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
        validate_description(readme, source=str(root / "README.md"))
        captures = validate_local_captures(root)
        print(
            f"verified README and {len(captures)} local "
            f"{EXPECTED_DIMENSIONS[0]}x{EXPECTED_DIMENSIONS[1]} PNGs"
        )
        if args.wheel is not None:
            validate_wheel(args.wheel.resolve())
            print(f"verified wheel METADATA Description: {args.wheel}")
        if args.network:
            validate_network_captures(captures)
            print(f"verified {len(captures)} immutable public PNG targets")
    except (OSError, VerificationError) as exc:
        print(f"PyPI README verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

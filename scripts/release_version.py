#!/usr/bin/env python3
"""Canonical Staqtapp-TDS public release-version contract.

The two already-published PEP 440 post releases remain valid historical
identities. Every release after them must use exactly ``MAJOR.MINOR.PATCH``,
with corrections expressed as patch increments rather than another ``.postN``
suffix.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path
import re
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "staqtapp-tds"

# Immutable historical exceptions. This set is closed: adding another
# post-release identity is a policy violation, not a routine version update.
LEGACY_POST_RELEASES = frozenset({"3.5.3.post1", "3.5.3.post2"})
STRICT_RELEASE_PATTERN = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
VERSION_ASSIGNMENT_PATTERN = re.compile(
    r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE
)


class ReleaseVersionError(ValueError):
    """Raised when a public release identity violates the version contract."""


def _require_exact_text(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise ReleaseVersionError(f"{label} must be a string")
    if not value:
        raise ReleaseVersionError(f"{label} must not be empty")
    if value != value.strip():
        raise ReleaseVersionError(f"{label} must not contain surrounding whitespace")
    return value


def validate_public_release_version(
    value: str,
    *,
    allow_legacy: bool = True,
) -> str:
    """Validate an exact package version and return it unchanged.

    Package metadata and ``src/staqtapp_tds/version.py`` never include the tag
    prefix. Use :func:`normalize_release_ref` for an operator input that may be
    either a package version or an exact ``v``-prefixed tag.
    """

    version = _require_exact_text(value, label="public release version")
    if version.startswith("v"):
        raise ReleaseVersionError("package versions must not begin with 'v'")
    if allow_legacy and version in LEGACY_POST_RELEASES:
        return version
    if not STRICT_RELEASE_PATTERN.fullmatch(version):
        raise ReleaseVersionError(
            "public releases after 3.5.3.post2 must use exactly "
            "MAJOR.MINOR.PATCH; corrective releases increment PATCH"
        )
    return version


def normalize_release_ref(value: str) -> str:
    """Return a canonical package version from a package version or exact tag."""

    release_ref = _require_exact_text(value, label="release identity")
    version = release_ref[1:] if release_ref.startswith("v") else release_ref
    return validate_public_release_version(version)


def read_source_version(root: Path = ROOT) -> str:
    """Read the single exact package-version assignment without importing TDS."""

    version_file = root / "src" / "staqtapp_tds" / "version.py"
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseVersionError(f"cannot read {version_file}") from exc
    assignments = VERSION_ASSIGNMENT_PATTERN.findall(text)
    if len(assignments) != 1:
        raise ReleaseVersionError(
            "src/staqtapp_tds/version.py must contain exactly one __version__ assignment"
        )
    return validate_public_release_version(assignments[0])


def expected_tag(version: str) -> str:
    """Return the only production tag permitted for an exact package version."""

    return f"v{validate_public_release_version(version)}"


def validate_tag(tag: str, *, source_version: str | None = None) -> str:
    """Validate a production tag and optionally bind it to the source version."""

    exact_tag = _require_exact_text(tag, label="production tag")
    if not exact_tag.startswith("v"):
        raise ReleaseVersionError("production tags must begin with 'v'")
    version = normalize_release_ref(exact_tag)
    if exact_tag != expected_tag(version):
        raise ReleaseVersionError("production tag is not canonical")
    if source_version is not None:
        source = validate_public_release_version(source_version)
        if version != source:
            raise ReleaseVersionError(
                f"release tag {exact_tag} does not match source version {source}"
            )
    return version


def verify_installed_distribution(root: Path = ROOT) -> str:
    """Require source, installed metadata, and imported package identity to match."""

    source_version = read_source_version(root)
    try:
        metadata_version = importlib.metadata.version(PROJECT_NAME)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ReleaseVersionError(f"{PROJECT_NAME} is not installed") from exc

    from staqtapp_tds import __version__ as imported_version

    identities = {
        "source": source_version,
        "metadata": validate_public_release_version(metadata_version),
        "imported": validate_public_release_version(imported_version),
    }
    if len(set(identities.values())) != 1:
        raise ReleaseVersionError(f"release identity mismatch: {identities}")
    return source_version


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="release_version.py")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--check",
        metavar="VERSION_OR_TAG",
        help="validate an exact public package version or v-prefixed tag",
    )
    actions.add_argument(
        "--check-env",
        metavar="ENV_NAME",
        help="validate a public package version or tag stored in an environment variable",
    )
    actions.add_argument(
        "--check-tag",
        metavar="TAG",
        help="validate an exact v-prefixed tag against the source version",
    )
    actions.add_argument(
        "--verify-installed",
        action="store_true",
        help="compare source, installed metadata, and imported package versions",
    )
    actions.add_argument(
        "--print-tag",
        action="store_true",
        help="print the canonical tag for the source version",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.check is not None:
            print(normalize_release_ref(args.check))
        elif args.check_env is not None:
            value = os.environ.get(args.check_env)
            if value is None:
                raise ReleaseVersionError(
                    f"environment variable {args.check_env!r} is not set"
                )
            print(normalize_release_ref(value))
        elif args.check_tag is not None:
            print(validate_tag(args.check_tag, source_version=read_source_version()))
        elif args.verify_installed:
            print(verify_installed_distribution())
        elif args.print_tag:
            print(expected_tag(read_source_version()))
        else:
            print(read_source_version())
    except ReleaseVersionError as exc:
        print(f"release version check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

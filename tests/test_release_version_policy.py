from __future__ import annotations

from pathlib import Path

import pytest

from scripts.release_version import (
    LEGACY_POST_RELEASES,
    ReleaseVersionError,
    expected_tag,
    normalize_release_ref,
    read_source_version,
    validate_public_release_version,
    validate_tag,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "version",
    ("3.6.0", "3.6.1", "3.10.0", "4.0.0", "10.2.17"),
)
def test_clean_three_component_public_versions_are_accepted(version: str) -> None:
    assert validate_public_release_version(version) == version
    assert expected_tag(version) == f"v{version}"


@pytest.mark.parametrize("version", tuple(sorted(LEGACY_POST_RELEASES)))
def test_only_the_two_immutable_historical_post_releases_are_accepted(
    version: str,
) -> None:
    assert validate_public_release_version(version) == version


@pytest.mark.parametrize(
    "version",
    (
        "3.5.3.post3",
        "3.6.0.post1",
        "v3.6.0",
        " 3.6.0",
        "3.6.0 ",
        "3.6.0rc1",
        "3.6.0.dev1",
        "3.6.0+local",
        "03.6.0",
        "3.06.0",
        "3.6",
        "3.6.0.1",
        "latest",
        "",
    ),
)
def test_new_post_prerelease_local_and_noncanonical_versions_are_rejected(
    version: str,
) -> None:
    with pytest.raises(ReleaseVersionError):
        validate_public_release_version(version)


def test_tag_contract_is_exact_and_bound_to_source_version() -> None:
    source = read_source_version(ROOT)
    assert validate_tag(f"v{source}", source_version=source) == source
    assert normalize_release_ref(source) == source
    assert normalize_release_ref(f"v{source}") == source
    with pytest.raises(ReleaseVersionError):
        validate_tag(source, source_version=source)
    with pytest.raises(ReleaseVersionError):
        validate_tag("v3.6.0", source_version="3.6.1")


def test_release_workflows_have_no_hard_coded_post_release_identity() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    smoke = (ROOT / ".github" / "workflows" / "pypi-smoke.yml").read_text(
        encoding="utf-8"
    )
    assert ".post" not in release
    assert ".post" not in smoke
    assert "python scripts/release_version.py --verify-installed" in release
    assert "name: staqtapp-tds-distributions" in release
    assert "if: github.ref_type == 'tag'" in release
    assert "--check-env RELEASE_VERSION" in smoke
    assert "default:" not in smoke.split("inputs:", 1)[1].split("permissions:", 1)[0]


def test_versioning_policy_requires_patch_increments_after_v353_post2() -> None:
    policy = (ROOT / "docs" / "VERSIONING.md").read_text(encoding="utf-8")
    normalized = " ".join(policy.split())
    assert "The completed Foundation source identity is **v3.6.0**" in normalized
    assert "current published architecture line is **v3.8.0**" in normalized
    assert "current production PyPI identity is `3.8.0`" in normalized
    assert "publication grants no Eaglegate canary" in normalized
    assert "Staqtapp-TDS will not publish another `.postN` release" in normalized
    assert "v3.6.0 -> v3.6.1 -> v3.6.2" in normalized

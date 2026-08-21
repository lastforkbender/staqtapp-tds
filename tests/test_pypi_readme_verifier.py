from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import sys
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_pypi_readme as verifier  # noqa: E402
import check_release as release_checker  # noqa: E402
import verify_pypi_presentation as live_verifier  # noqa: E402


def _png(width: int = 1280, height: int = 800, *, marker: bytes = b"") -> bytes:
    return (
        verifier.PNG_SIGNATURE
        + b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + marker
    )


def test_v382_release_identity_and_future_candidate_sentinels_are_current() -> None:
    assert release_checker.CURRENT_PRODUCTION_VERSION == "3.8.2"
    assert release_checker.SOURCE_CANDIDATE_MARKER in live_verifier.STALE_WORDING
    assert (
        release_checker.V370_JAPANESE_CANDIDATE_MARKER
        in live_verifier.STALE_WORDING
    )
    assert verifier.USER_AGENT.endswith("/3.8.2")
    assert live_verifier.USER_AGENT.endswith("/3.8.2")


def _description(urls: tuple[str, ...] = verifier.EXPECTED_IMAGE_URLS) -> str:
    return "\n".join(f'<img src="{url}" alt="capture">' for url in urls)


def _fixture_repository(root: Path) -> dict[str, bytes]:
    capture_root = root / verifier.CAPTURE_DIRECTORY
    capture_root.mkdir(parents=True)
    payloads: dict[str, bytes] = {}
    for index, (filename, url) in enumerate(
        zip(verifier.CAPTURE_FILENAMES, verifier.EXPECTED_IMAGE_URLS, strict=True),
        start=1,
    ):
        data = _png(marker=index.to_bytes(2, "big"))
        (capture_root / filename).write_bytes(data)
        payloads[url] = data
    (root / "README.md").write_text(_description(), encoding="utf-8")
    return payloads


class _Response:
    def __init__(
        self,
        data: bytes,
        *,
        status: int = 200,
        content_type: str = "image/png",
    ) -> None:
        self.data = data
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.data


def _opener(payloads: dict[str, bytes], **overrides: object):
    def open_url(request, *, timeout: float):
        assert timeout > 0
        return _Response(payloads[request.full_url], **overrides)

    return open_url


def _write_wheel(path: Path, description: str) -> None:
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: staqtapp-tds\n"
        "Version: 3.8.2\n"
        "Description-Content-Type: text/markdown\n"
        "\n"
        f"{description}\n"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("staqtapp_tds-3.8.2.dist-info/METADATA", metadata)


def test_repository_readme_and_local_captures_match_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert verifier.validate_description(readme, source="README.md") == (
        verifier.EXPECTED_IMAGE_URLS
    )
    captures = verifier.validate_local_captures(ROOT)
    assert tuple(captures) == verifier.EXPECTED_IMAGE_URLS
    assert all(len(evidence.digest) == 64 for evidence in captures.values())


def test_description_rejects_changed_order_and_missing_image() -> None:
    reversed_urls = tuple(reversed(verifier.EXPECTED_IMAGE_URLS))
    with pytest.raises(verifier.VerificationError, match="exact immutable image URL order"):
        verifier.validate_description(_description(reversed_urls), source="test README")

    with pytest.raises(verifier.VerificationError, match="expected exactly 19"):
        verifier.validate_description(
            _description(verifier.EXPECTED_IMAGE_URLS[:-1]), source="test README"
        )


def test_local_captures_require_png_signature_and_dimensions(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    first = tmp_path / verifier.CAPTURE_DIRECTORY / verifier.CAPTURE_FILENAMES[0]
    first.write_bytes(b"not a PNG")
    with pytest.raises(verifier.VerificationError, match="PNG signature"):
        verifier.validate_local_captures(tmp_path)

    first.write_bytes(_png(width=1279))
    with pytest.raises(verifier.VerificationError, match="1279x800"):
        verifier.validate_local_captures(tmp_path)


def test_network_check_requires_exact_remote_bytes(tmp_path: Path) -> None:
    payloads = _fixture_repository(tmp_path)
    captures = verifier.validate_local_captures(tmp_path)
    verifier.validate_network_captures(captures, opener=_opener(payloads))

    changed = dict(payloads)
    changed[verifier.EXPECTED_IMAGE_URLS[-1]] = _png(marker=b"changed")
    with pytest.raises(verifier.VerificationError, match="does not match local screenshot"):
        verifier.validate_network_captures(captures, opener=_opener(changed))


@pytest.mark.parametrize(
    ("remote_bytes", "message"),
    [
        (b"not a PNG", "PNG signature"),
        (_png(height=799), "1280x799"),
    ],
)
def test_network_check_validates_remote_png_structure(
    tmp_path: Path,
    remote_bytes: bytes,
    message: str,
) -> None:
    payloads = _fixture_repository(tmp_path)
    captures = verifier.validate_local_captures(tmp_path)
    payloads[verifier.EXPECTED_IMAGE_URLS[0]] = remote_bytes
    with pytest.raises(verifier.VerificationError, match=message):
        verifier.validate_network_captures(captures, opener=_opener(payloads))


@pytest.mark.parametrize(
    ("response_options", "message"),
    [
        ({"status": 404}, "returned HTTP 404"),
        ({"content_type": "text/plain"}, "expected 'image/png'"),
    ],
)
def test_network_check_requires_http_200_and_png_content_type(
    tmp_path: Path,
    response_options: dict[str, object],
    message: str,
) -> None:
    payloads = _fixture_repository(tmp_path)
    captures = verifier.validate_local_captures(tmp_path)
    with pytest.raises(verifier.VerificationError, match=message):
        verifier.validate_network_captures(
            captures,
            opener=_opener(payloads, **response_options),
        )


def test_wheel_metadata_preserves_exact_urls_and_order(tmp_path: Path) -> None:
    wheel = tmp_path / "staqtapp_tds-3.8.2-py3-none-any.whl"
    _write_wheel(wheel, _description())
    assert verifier.validate_wheel(wheel) == verifier.EXPECTED_IMAGE_URLS

    _write_wheel(wheel, _description(tuple(reversed(verifier.EXPECTED_IMAGE_URLS))))
    with pytest.raises(verifier.VerificationError, match="exact immutable image URL order"):
        verifier.validate_wheel(wheel)


def test_capture_evidence_hashes_complete_local_files(tmp_path: Path) -> None:
    payloads = _fixture_repository(tmp_path)
    captures = verifier.validate_local_captures(tmp_path)
    first_url = verifier.EXPECTED_IMAGE_URLS[0]
    assert captures[first_url].digest == hashlib.sha256(payloads[first_url]).hexdigest()
    assert captures[first_url].byte_count == len(payloads[first_url])


def _live_description(*, version: str = "3.8.2") -> str:
    links = "\n".join(
        f"[required target]({target})" for target in live_verifier.REQUIRED_TARGETS[1:]
    )
    return (
        f"# Staqtapp-TDS v{version}\n\n"
        f"python -m pip install staqtapp-tds=={version}\n\n"
        f"{_description()}\n{links}\n"
    )


def test_live_pypi_description_requires_exact_version_heading_and_install() -> None:
    images, _links = live_verifier.validate_description(
        _live_description(), version="3.8.2"
    )
    assert len(images) == 19

    with pytest.raises(ValueError, match="exact release identity"):
        live_verifier.validate_description(
            _live_description(version="3.5.3.post2"), version="3.8.2"
        )


@pytest.mark.parametrize("marker", live_verifier.STALE_WORDING)
def test_live_pypi_description_rejects_obsolete_status_markers(marker: str) -> None:
    with pytest.raises(ValueError, match="obsolete release wording"):
        live_verifier.validate_description(
            _live_description() + marker, version="3.8.2"
        )

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_readme_current_status_preserves_every_recorded_target() -> None:
    subprocess.run(
        [sys.executable, "tools/update_readme_status_v370.py", "--check"],
        cwd=ROOT,
        check=True,
    )
    manifest = json.loads(
        (ROOT / "docs" / "readme_targets_v370.json").read_text(encoding="utf-8")
    )
    assert manifest["format"] == "tds.v370.readme-target-manifest.v1"
    assert len(manifest["english"]["images"]) == 19
    assert len(manifest["japanese"]["images"]) == 19
    assert manifest["original_english_sha256"].startswith("sha256:")
    assert manifest["original_japanese_sha256"].startswith("sha256:")


def test_readmes_describe_real_v370_scope_without_false_release_claims() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    japanese = (ROOT / "README_ja.md").read_text(encoding="utf-8")
    for text in (english, japanese):
        assert "TDS-V370-CURRENT-STATUS:BEGIN" in text
        assert "Atomic Generation" in text
        assert "cross-process" in text
        assert "rollback" in text
        assert "retirement" in text
        assert "3.5.3.post2" in text
        assert "Eaglegate" in text
        assert "inactive" in text
    assert "published package remains `3.5.3.post2`" in english
    assert "v3.7.0 is published" not in english
    assert "Eaglegate is active" not in english

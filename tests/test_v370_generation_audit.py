from __future__ import annotations

import json
from pathlib import Path

from staqtapp_tds.generation.audit import main, run_generation_authority_audit


def test_generation_authority_audit_is_deterministic_and_complete(
    tmp_path: Path,
) -> None:
    first = run_generation_authority_audit(tmp_path / "first")
    second = run_generation_authority_audit(tmp_path / "second")
    assert first == second
    assert first["status"] == "pass"
    assert first["source_content_in_report"] is False
    assert first["publication_records"] == 3
    assert all(first["gates"].values())
    assert set(first["roots"]) == {
        "first_generation",
        "final_head",
        "second_generation",
        "stale_unpublished_generation",
    }


def test_generation_authority_audit_cli_emits_canonical_json(capsys: object) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert parsed["audit"] == "tds-v370-generation-authority-audit-v1"
    assert output == json.dumps(
        parsed,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"

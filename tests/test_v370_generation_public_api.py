from __future__ import annotations

import json
from pathlib import Path

from staqtapp_tds import generation
from staqtapp_tds.csv_layer.generation_runtime import (
    CSV_DURABLE_PUBLICATION_CONTRACT_ID,
)


def test_reference_audit_is_deterministic_and_content_free() -> None:
    first = generation.run_reference_generation_audit()
    second = generation.run_reference_generation_audit()
    assert first == second
    assert first.report_root == second.report_root
    payload = first.canonical_dict()
    assert payload["csv_generation_contract_id"] == "tds-csv-generation-v1"
    assert payload["durable_publication_contract_id"] == (
        CSV_DURABLE_PUBLICATION_CONTRACT_ID
    )
    assert payload["old_reader_stable"] is True
    assert payload["exact_source_round_trip"] is True
    assert payload["cas_enforced"] is True
    assert payload["retired_generation_blocked_from_rollback"] is True
    assert payload["final_current_generation_root"] == payload["old_generation_root"]
    assert payload["activation_authority"] is False
    material = json.dumps(payload, sort_keys=True).lower()
    for forbidden in ("prompt", "logits", "hidden_state", "kv_tensor"):
        assert forbidden not in material


def test_status_is_read_only_and_missing_store_is_canonical(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    status = generation.inspect_generation_store(root)
    assert status.store_exists is False
    assert status.current_generation_root == ""
    assert status.object_count == 0
    assert status.status_root.startswith("sha256:")
    assert not root.exists()


def test_generation_cli_reference_and_status(capsys, tmp_path: Path) -> None:
    assert generation.main(["reference"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["ok"] is True
    assert first["report_root"].startswith("sha256:")

    assert generation.main(["status", "--root", str(tmp_path / "absent")]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["ok"] is True
    assert status["store_exists"] is False
    assert status["activation_authority"] is False

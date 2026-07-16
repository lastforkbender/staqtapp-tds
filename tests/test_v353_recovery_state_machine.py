from __future__ import annotations

import json
from pathlib import Path

import pytest

from staqtapp_tds import (
    GenerationIntegrityError,
    ImmutableGenerationStore,
    RecoveryCondition,
)


def _corrupt_data(info, payload=b"corrupt"):
    (info.path / "data.tds").write_bytes(payload)


def test_compound_failure_selects_newest_valid_and_repairs_current(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    oldest = store.commit(b"oldest")
    middle = store.commit(b"middle")
    newest = store.commit(b"newest")
    _corrupt_data(newest, b"NEWEST")
    (middle.path / "integrity.json").write_bytes(b"{")

    report = store.recover_report()

    assert report.requested_generation == newest.generation_id
    assert report.mounted_generation == oldest.generation_id
    assert report.condition is RecoveryCondition.CHECKSUM_MISMATCH
    assert report.current_repaired is True
    assert report.scanned_candidates == 3
    assert [item.generation_id for item in report.rejected_generations] == [
        newest.generation_id, middle.generation_id
    ]
    assert store.current_generation() == oldest.generation_id
    assert store.read_current() == b"oldest"


def test_malformed_current_is_classified_and_repaired(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"state")
    store.current_path.write_text("../../escape\n", encoding="ascii")

    report = store.recover_report()

    assert report.condition is RecoveryCondition.CURRENT_MALFORMED
    assert report.mounted_generation == info.generation_id
    assert store.current_path.read_text(encoding="ascii").strip() == info.generation_id


def test_missing_current_can_be_inspected_without_repair(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"state")
    store.current_path.unlink()

    report = store.recover_report(repair_current=False)

    assert report.condition is RecoveryCondition.CURRENT_MISSING
    assert report.mounted_generation == info.generation_id
    assert report.current_repaired is False
    assert not store.current_path.exists()


def test_unsupported_schema_is_rejected_not_silently_mounted(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    old = store.commit(b"old")
    new = store.commit(b"new")
    meta_path = new.path / "integrity.json"
    metadata = json.loads(meta_path.read_text())
    metadata["schema"] = "tds.generation.v999"
    meta_path.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")))

    report = store.recover_report()

    assert report.mounted_generation == old.generation_id
    assert report.condition is RecoveryCondition.FORMAT_UNSUPPORTED
    assert report.rejected_generations[0].condition is RecoveryCondition.FORMAT_UNSUPPORTED


def test_recovery_repair_interruption_never_changes_selected_data(tmp_path: Path):
    base = ImmutableGenerationStore(tmp_path)
    old = base.commit(b"old")
    new = base.commit(b"new")
    _corrupt_data(new)

    def fail(name: str) -> None:
        if name == "recovery_current_temp_written":
            raise RuntimeError("repair interrupted")

    interrupted = ImmutableGenerationStore(tmp_path, fault_hook=fail)
    with pytest.raises(RuntimeError, match="repair interrupted"):
        interrupted.recover_report()

    clean = ImmutableGenerationStore(tmp_path)
    report = clean.recover_report()
    assert report.mounted_generation == old.generation_id
    assert clean.read_current() == b"old"


def test_no_valid_generation_fails_closed_and_preserves_evidence(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"only")
    _corrupt_data(info)

    with pytest.raises(GenerationIntegrityError, match="no_valid_generation"):
        store.recover_report()

    assert info.path.exists()
    assert store.current_path.exists()


def test_candidate_scan_is_bounded(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ImmutableGenerationStore, "MAX_RECOVERY_CANDIDATES", 2)
    store = ImmutableGenerationStore(tmp_path)
    for index in range(3):
        generation_id = f"gen-{index:020d}-aaaaaaaaaaaa"
        (store.generations_dir / generation_id).mkdir()

    with pytest.raises(GenerationIntegrityError, match="candidate count exceeds 2"):
        store.recover_report()

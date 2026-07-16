from __future__ import annotations

import pytest

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    begin_csv_artifact_transaction,
    commit_csv_artifact_transaction,
    csv_artifact_transaction_keys,
    detect_partial_csv_artifacts,
    import_csv_bytes,
    load_csv_artifact_transaction_report,
    recover_csv_artifact_transaction,
    validate_csv_artifact_transaction,
    validate_csv_artifacts,
    validate_csv_transaction_id,
)


def test_version_335_csv_artifact_transaction_recovery_envelope():
    assert __version__ == "3.5.3.post1"


def test_csv_transaction_id_validation_rejects_path_and_control_values():
    assert validate_csv_transaction_id("tx-01_ok") == "tx-01_ok"
    for tx_id in ("", "../bad", "nested/name", ".hidden", "bad\nline", "x" * 65):
        with pytest.raises(ValueError):
            validate_csv_transaction_id(tx_id)


def test_csv_artifact_transaction_stages_then_commits_core_artifacts():
    fs = TDSFileSystem("root")

    staged = begin_csv_artifact_transaction(
        fs.root,
        b"id,note\n1,alpha\n2,beta\n",
        source_name="transaction.csv",
        transaction_id="tx001",
    )
    before_final = detect_partial_csv_artifacts(fs.root, staged.csv_id)
    validation = validate_csv_artifact_transaction(fs.root, staged.csv_id, staged.transaction_id)
    committed = commit_csv_artifact_transaction(fs.root, staged.csv_id, staged.transaction_id)
    after_final = detect_partial_csv_artifacts(fs.root, staged.csv_id)
    artifact_validation = validate_csv_artifacts(fs.root, staged.csv_id)
    loaded_report = load_csv_artifact_transaction_report(fs.root, staged.csv_id)

    assert staged.ok is True
    assert staged.status == "staged"
    assert staged.staged_count == 6
    assert before_final.status == "empty"
    assert validation.ok is True
    assert validation.status == "valid"
    assert committed.ok is True
    assert committed.status == "committed"
    assert committed.committed_count == 6
    assert committed.cleaned_staged_count >= 6
    assert after_final.status == "complete"
    assert artifact_validation.ok is True
    assert loaded_report.status == "committed"
    assert loaded_report.per_row_writes is False
    assert loaded_report.per_cell_writes is False
    assert loaded_report.native_storage_hot_path_touched is False
    assert loaded_report.semantic_reasoning is False


def test_csv_transaction_does_not_change_normal_import_artifact_shape():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="normal.csv")

    report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.checked_artifacts == (
        "manifest",
        "raw",
        "dialect",
        "row_offsets",
        "content_hashes",
        "import_report",
    )
    assert report.per_cell_writes is False


def test_csv_transaction_fails_closed_when_staged_artifact_is_missing():
    fs = TDSFileSystem("root")
    staged = begin_csv_artifact_transaction(
        fs.root,
        b"a,b\n1,2\n",
        source_name="partial-stage.csv",
        transaction_id="txmissing",
    )
    tx_keys = csv_artifact_transaction_keys(staged.csv_id, staged.transaction_id)
    fs.root.delete_entry(tx_keys["row_offsets"])

    validation = validate_csv_artifact_transaction(fs.root, staged.csv_id, staged.transaction_id)
    committed = commit_csv_artifact_transaction(fs.root, staged.csv_id, staged.transaction_id)

    assert validation.ok is False
    assert validation.status == "partial_staged"
    assert "row_offsets" in validation.missing_staged_artifacts
    assert "staged_artifacts_missing" in validation.errors
    assert committed.ok is False
    assert committed.status == "invalid"


def test_csv_partial_final_detection_catches_interrupted_core_write():
    fs = TDSFileSystem("root")
    staged = begin_csv_artifact_transaction(
        fs.root,
        b"a,b\n1,2\n",
        source_name="partial-final.csv",
        transaction_id="txpartial",
    )
    tx_keys = csv_artifact_transaction_keys(staged.csv_id, staged.transaction_id)
    final_keys = artifact_keys(staged.csv_id)

    fs.root.write_text(final_keys["raw"], fs.root.read_value(tx_keys["raw"]), overwrite=True, provenance="REAL")
    fs.root.write_json(final_keys["dialect"], fs.root.read_value(tx_keys["dialect"]), overwrite=True, provenance="DERIVED")

    report = detect_partial_csv_artifacts(fs.root, staged.csv_id)

    assert report.ok is False
    assert report.partial is True
    assert report.status == "partial"
    assert report.final_count == 2
    assert set(report.missing_final_artifacts) == {
        "row_offsets",
        "content_hashes",
        "manifest",
        "import_report",
    }


def test_csv_recovery_can_commit_valid_stage_over_partial_final_state():
    fs = TDSFileSystem("root")
    staged = begin_csv_artifact_transaction(
        fs.root,
        b"a,b\n1,2\n3,4\n",
        source_name="recover.csv",
        transaction_id="txrecover",
    )
    tx_keys = csv_artifact_transaction_keys(staged.csv_id, staged.transaction_id)
    final_keys = artifact_keys(staged.csv_id)
    fs.root.write_text(final_keys["raw"], fs.root.read_value(tx_keys["raw"]), overwrite=True, provenance="REAL")

    dry_run = recover_csv_artifact_transaction(fs.root, staged.csv_id, staged.transaction_id)
    recovered = recover_csv_artifact_transaction(
        fs.root,
        staged.csv_id,
        staged.transaction_id,
        commit_staged=True,
    )
    final_state = detect_partial_csv_artifacts(fs.root, staged.csv_id)

    assert dry_run.ok is True
    assert dry_run.status == "recoverable_staged"
    assert dry_run.final_count == 1
    assert recovered.ok is True
    assert recovered.status == "committed"
    assert recovered.committed_count == 6
    assert final_state.status == "complete"
    assert validate_csv_artifacts(fs.root, staged.csv_id).ok is True


def test_csv_transaction_rejects_existing_final_artifacts_without_overwrite():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="existing.csv", csv_id="existing_csv")

    staged = begin_csv_artifact_transaction(
        fs.root,
        b"a,b\n3,4\n",
        source_name="existing.csv",
        csv_id=manifest.csv_id,
        transaction_id="txexists",
    )

    assert staged.ok is False
    assert staged.status == "invalid"
    assert "final_artifacts_exist" in staged.errors
    assert set(staged.existing_final_artifacts) == {
        "raw",
        "dialect",
        "row_offsets",
        "content_hashes",
        "manifest",
        "import_report",
    }

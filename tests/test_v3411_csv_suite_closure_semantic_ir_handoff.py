from __future__ import annotations

from copy import deepcopy

from staqtapp_tds import __version__
from staqtapp_tds.tds_filesystem import TDSFileSystem
from staqtapp_tds.csv_layer import (
    CSV_SEMANTIC_IR_HANDOFF_CONTRACT_KEYS,
    CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT,
    CSV_SEMANTIC_IR_HANDOFF_VERSION,
    CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES,
    artifact_keys,
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_interpole_timeline_ring_report,
    commit_csv_kernel_performance_gate_report,
    commit_csv_kernel_readiness_contract_report,
    commit_csv_native_row_anchor_kernel_report,
    commit_csv_native_scan_kernel_prototype_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_kernel_performance_gate_report_key,
    csv_semantic_ir_handoff_fingerprint,
    csv_semantic_ir_handoff_summary,
    import_csv_bytes,
    prepare_csv_interpole_browser_monitor_snapshot,
    prepare_csv_semantic_ir_handoff,
    replay_csv_interpole_browser_monitor_snapshot,
    validate_csv_interpole_browser_monitor_snapshot,
    validate_csv_semantic_ir_handoff,
)


def _ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,name,score\n1,Ada,99\n2,Grace,98\n3,Katherine,97\n',
    *,
    chunk_size: int | None = 7,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="csv_suite_closure.csv")
    reports = (
        commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id),
        commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id),
        commit_csv_native_storage_artifacts(fs.root, manifest.csv_id),
        commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id),
        commit_csv_interpole_timeline_report(fs.root, manifest.csv_id),
        commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id),
        commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id),
        commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id, chunk_size=chunk_size),
        commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id, chunk_size=chunk_size),
        commit_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id, chunk_size=chunk_size),
        commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id),
    )
    assert all(report.ok for report in reports)
    return manifest


def test_version_3411_csv_suite_closure_semantic_ir_handoff():
    assert __version__ == "3.5.2"
    assert CSV_SEMANTIC_IR_HANDOFF_VERSION == "1.0"
    assert CSV_SEMANTIC_IR_HANDOFF_PAYLOAD_BYTE_LIMIT >= 131_072
    assert len(CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES) == 19
    assert "semantic_ir_candidate_ready" in CSV_SEMANTIC_IR_HANDOFF_CONTRACT_KEYS
    assert "formal_ir_committed" in CSV_SEMANTIC_IR_HANDOFF_CONTRACT_KEYS


def test_csv_semantic_ir_handoff_closes_complete_suite_without_writes():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id)
    after_keys = set(fs.root._entries.keys())
    summary = csv_semantic_ir_handoff_summary(report)

    assert report.ok is True
    assert report.status == "ir_handoff_ready"
    assert report.semantic_ir_candidate_ready is True
    assert report.artifact_chain_status == "ready"
    assert report.storage_chain_status == "ready"
    assert report.interpole_chain_status == "ready"
    assert report.kernel_chain_status == "ready"
    assert report.monitor_chain_status == "ready"
    assert tuple(item.evidence_name for item in report.evidence) == CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES
    assert all(item.ok for item in report.evidence)
    assert report.directory_state_unchanged is True
    assert report.directory_state_fingerprint_before == report.directory_state_fingerprint_after
    assert report.tds_artifact_writes == 0
    assert report.payload_bytes <= report.payload_byte_limit
    assert summary["ready_evidence_count"] == len(CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES)
    assert summary["blocked_evidence_count"] == 0
    assert after_keys == before_keys


def test_csv_semantic_ir_handoff_is_deterministic_and_serialization_validates():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)

    first = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id)
    second = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id)
    validation = validate_csv_semantic_ir_handoff(first.to_dict())

    assert first.ok is True
    assert second.ok is True
    assert first.closure_fingerprint == second.closure_fingerprint
    assert first.payload_bytes == second.payload_bytes
    assert first.closure_fingerprint == csv_semantic_ir_handoff_fingerprint(first)
    assert validation.ok is True
    assert validation.status == "handoff_valid"
    assert validation.source_closure_fingerprint == validation.recomputed_closure_fingerprint


def test_csv_semantic_ir_handoff_serialized_contract_rejects_missing_field():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    payload = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id).to_dict()
    payload.pop("schema_inference")

    validation = validate_csv_semantic_ir_handoff(payload)

    assert validation.ok is False
    assert validation.status == "handoff_blocked"
    assert "schema_inference" in validation.missing_contract_keys
    assert "handoff_contract_missing:schema_inference" in validation.errors


def test_csv_semantic_ir_handoff_serialized_contract_rejects_evidence_tamper():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    payload = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id).to_dict()
    payload["evidence"][0]["fingerprint"] = "0" * 64

    validation = validate_csv_semantic_ir_handoff(payload)

    assert validation.ok is False
    assert "closure_fingerprint_mismatch" in validation.errors


def test_csv_semantic_ir_handoff_blocks_missing_committed_evidence_without_new_writes():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    fs.root.delete(csv_kernel_performance_gate_report_key(manifest.csv_id))
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is False
    assert report.status == "ir_handoff_blocked"
    assert report.semantic_ir_candidate_ready is False
    assert report.kernel_chain_status == "blocked"
    assert any(item.evidence_name == "kernel_performance_gates" and not item.ok for item in report.evidence)
    assert report.directory_state_unchanged is True
    assert report.tds_artifact_writes == 0
    assert after_keys == before_keys


def test_csv_semantic_ir_handoff_blocks_source_drift_but_remains_read_only():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    fs.root.write_text(
        artifact_keys(manifest.csv_id)["raw"],
        "id,name,score\n1,Tampered,0\n",
        overwrite=True,
        provenance="REAL",
    )
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is False
    assert report.status == "ir_handoff_blocked"
    assert report.artifact_chain_status == "blocked"
    assert any(item.evidence_name == "core_artifact_integrity" and not item.ok for item in report.evidence)
    assert report.directory_state_unchanged is True
    assert report.source_artifact_mutation is False
    assert after_keys == before_keys


def test_browser_monitor_missing_contract_field_now_fails_closed():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id).to_dict()
    snapshot.pop("schema_inference")

    validation = validate_csv_interpole_browser_monitor_snapshot(snapshot)

    assert validation.ok is False
    assert validation.status == "snapshot_blocked"
    assert "display_contract_missing:schema_inference" in validation.errors


def test_browser_monitor_nested_display_tamper_now_fails_replay():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id).to_dict()
    snapshot["cards"] = [dict(card) for card in snapshot["cards"]]
    snapshot["cards"][0]["detail"] = "tampered display text with unchanged card count"

    replay = replay_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id, snapshot)

    assert replay.ok is False
    assert replay.status == "replay_blocked"
    assert "cards" in replay.mismatched_fields
    assert "display_projection" in replay.mismatched_fields
    assert "snapshot_mismatch:cards" in replay.errors


def test_csv_semantic_ir_handoff_blocks_supplied_tampered_monitor_snapshot():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id).to_dict()
    snapshot["event_rows"] = [dict(row) for row in snapshot["event_rows"]]
    snapshot["event_rows"][0]["message"] = "tampered timeline event"

    report = prepare_csv_semantic_ir_handoff(
        fs.root,
        manifest.csv_id,
        source_monitor_snapshot=snapshot,
    )

    assert report.ok is False
    assert report.monitor_chain_status == "blocked"
    assert any(item.evidence_name == "browser_monitor_replay" and not item.ok for item in report.evidence)
    assert any(error.startswith("browser_monitor_replay:snapshot_mismatch:event_rows") for error in report.errors)
    assert report.formal_ir_committed is False


def test_csv_semantic_ir_handoff_payload_bound_fails_closed():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)

    report = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id, payload_byte_limit=512)

    assert report.ok is False
    assert report.status == "ir_handoff_blocked"
    assert report.semantic_ir_candidate_ready is False
    assert report.payload_bytes > report.payload_byte_limit
    assert any(error.startswith("handoff_payload_too_large:") for error in report.errors)


def test_csv_semantic_ir_handoff_invalid_id_and_semantic_exclusion_fail_closed():
    fs = TDSFileSystem("root")

    report = prepare_csv_semantic_ir_handoff(fs.root, "../unsafe")

    assert report.ok is False
    assert report.status == "ir_handoff_blocked"
    assert any(error.startswith("csv_id_unsafe:") for error in report.errors)
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.schema_inference is False
    assert report.type_inference is False
    assert report.entity_inference is False
    assert report.row_identity_inference is False
    assert report.cell_meaning_inference is False
    assert report.formal_ir_committed is False
    assert report.native_storage_hot_path_touched is False

from __future__ import annotations

from dataclasses import replace

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    CSV_KERNEL_PERFORMANCE_GATE_VERSION,
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
    csv_kernel_performance_gate_summary,
    import_csv_bytes,
    load_csv_kernel_performance_gate_report,
    prepare_csv_kernel_performance_gates,
    validate_csv_kernel_performance_gate_report,
)


def _performance_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,note\n1,"line\none"\n2,"quote "" kept"\n',
    *,
    commit_row_anchor: bool = True,
    chunk_size: int | None = 3,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="kernel_performance_gates.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    timeline = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    determinants = commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    ring = commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)
    readiness = commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id)
    scan = commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id, chunk_size=chunk_size)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    assert revalidation.ok is True
    assert timeline.ok is True
    assert determinants.ok is True
    assert ring.ok is True
    assert readiness.ok is True
    assert scan.ok is True
    row_anchor = None
    if commit_row_anchor:
        row_anchor = commit_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id, chunk_size=chunk_size)
        assert row_anchor.ok is True
    return manifest, scan, row_anchor


def test_version_348_csv_kernel_performance_gates():
    assert __version__ == "3.5.3"
    assert CSV_KERNEL_PERFORMANCE_GATE_VERSION == "1.0"


def test_csv_kernel_performance_gates_prepare_default_no_write():
    fs = TDSFileSystem("root")
    manifest, scan, row_anchor = _performance_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id)
    summary = csv_kernel_performance_gate_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "performance_gates_ready"
    assert report.mode == "performance_gate_prepare"
    assert report.report_key == csv_kernel_performance_gate_report_key(manifest.csv_id)
    assert report.source_anchor_fingerprint == row_anchor.anchor_fingerprint
    assert report.source_reference_anchor_fingerprint == row_anchor.reference_anchor_fingerprint
    assert report.source_scan_fingerprint == scan.scan_fingerprint
    assert report.source_reference_scan_fingerprint == scan.reference_scan_fingerprint
    assert report.row_anchor_validation_status == "valid"
    assert report.native_scan_validation_status == "valid"
    assert report.scan_parity_status == "valid"
    assert report.row_anchor_parity_status == "valid"
    assert report.gate_count == 13
    assert report.required_count == 13
    assert report.passed_count == 13
    assert report.blocked_count == 0
    assert report.estimated_linear_scan_work_units <= report.max_linear_scan_work_units
    assert report.estimated_anchor_digest_work_units <= report.max_anchor_digest_work_units
    assert report.estimated_gate_json_bytes <= report.max_report_json_bytes
    assert report.tds_artifact_writes == 0
    assert report.native_storage_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.native_storage_locks_controlled is False
    assert report.native_c_storage_engine_changed is False
    assert report.interpole_mutation is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False
    assert summary["performance_gate_fingerprint"] == report.performance_gate_fingerprint
    assert summary["gates"][0]["gate_name"] == "source_reports_committed"
    assert after_keys == before_keys


def test_csv_kernel_performance_gates_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)
    loaded = load_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)
    validation = validate_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert committed.status == "performance_gates_committed"
    assert committed.mode == "performance_gate_commit"
    assert committed.tds_artifact_writes == 1
    assert loaded.report_key == csv_kernel_performance_gate_report_key(manifest.csv_id)
    assert loaded.performance_gate_fingerprint == committed.performance_gate_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_kernel_performance_gates_require_committed_row_anchor_report():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n", commit_row_anchor=False)

    report = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert any("performance_gate_sources_unreadable" in error for error in report.errors)
    assert report.native_storage_hot_path_touched is False
    assert report.formal_ir_committed is False


def test_csv_kernel_performance_gates_block_on_fresh_row_anchor_drift():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n3,4\n")
    key = artifact_keys(manifest.csv_id)["row_offsets"]
    row_offsets = fs.root.read_value(key)
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(key, row_offsets, overwrite=True, provenance="DERIVED")

    report = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "blocked"
    assert report.row_anchor_validation_status == "drifted"
    assert any("fresh_kernel_validation_not_valid" in error for error in report.errors)
    assert any("native_row_anchor" in error or "scan_row_offsets_mismatch" in error for error in report.errors)
    assert report.native_storage_hot_path_touched is False
    assert report.interpole_mutation is False


def test_csv_kernel_performance_gates_block_on_tiny_report_budget():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id, max_report_json_bytes=8)

    assert report.ok is False
    assert report.status == "blocked"
    assert report.estimated_gate_json_bytes > report.max_report_json_bytes
    assert any("performance_gate_report_size_exceeded" in error for error in report.errors)
    assert report.tds_artifact_writes == 0


def test_csv_kernel_performance_gates_reject_invalid_budget_parameters():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n")

    bad_size = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id, max_report_json_bytes=0)
    bad_amp = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id, max_work_amplification=0)

    assert bad_size.ok is False
    assert "max_report_json_bytes_must_be_positive" in bad_size.errors
    assert bad_amp.ok is False
    assert "max_work_amplification_must_be_positive" in bad_amp.errors


def test_csv_kernel_performance_gates_validation_detects_stored_gate_drift():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)
    key = csv_kernel_performance_gate_report_key(manifest.csv_id)
    stored = fs.root.read_value(key)
    stored["performance_gate_fingerprint"] = "0" * 64
    fs.root.write_json(key, stored, overwrite=True, provenance="DERIVED")

    validation = validate_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert "performance_gate_fingerprint_drift" in validation.errors


def test_csv_kernel_performance_gates_block_on_source_report_not_committed():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n")
    key = csv_kernel_performance_gate_report_key(manifest.csv_id)
    _ = key  # keep the report key symbol exercised before source mutation
    row_key = "csv__{}__native_row_anchor_kernel_report.json".format(manifest.csv_id)
    stored = fs.root.read_value(row_key)
    stored["status"] = "native_row_anchor_ready"
    fs.root.write_json(row_key, stored, overwrite=True, provenance="DERIVED")

    report = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "blocked"
    assert any("source_kernel_reports_not_committed" in error for error in report.errors)


def test_csv_kernel_performance_gates_summary_is_compact_and_sorted_by_gate_index():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id)
    summary = csv_kernel_performance_gate_summary(report)

    assert list(summary.keys())[0:4] == ["csv_id", "status", "ok", "version"]
    assert [gate["gate_index"] for gate in summary["gates"]] == list(range(1, 14))
    assert all("evidence_hashes" not in gate for gate in summary["gates"])
    assert summary["native_storage_hot_path_touched"] is False
    assert summary["formal_ir_committed"] is False


def test_csv_kernel_performance_gates_roundtrip_from_mapping_preserves_gate_metrics():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)

    loaded = load_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)

    assert loaded.ok is True
    assert loaded.to_dict() == committed.to_dict()
    assert loaded.gates[4].metric_name == "estimated_linear_scan_work_units"
    assert loaded.gates[4].metric_value == committed.estimated_linear_scan_work_units
    assert loaded.gates[4].metric_limit == committed.max_linear_scan_work_units


def test_csv_kernel_performance_gates_handle_single_chunk_shape():
    fs = TDSFileSystem("root")
    manifest, _, _ = _performance_ready_csv(fs, b"a,b\r\n1,2\r\n", chunk_size=None)

    report = prepare_csv_kernel_performance_gates(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.raw_size > 0
    assert report.row_count == 2
    assert report.chunk_size is None
    assert report.chunk_count == 1
    assert report.estimated_linear_scan_work_units <= report.max_linear_scan_work_units
    assert report.estimated_anchor_digest_work_units <= report.max_anchor_digest_work_units

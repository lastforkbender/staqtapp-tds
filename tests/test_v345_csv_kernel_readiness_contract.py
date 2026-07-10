from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_interpole_timeline_ring_report,
    commit_csv_kernel_readiness_contract_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_kernel_readiness_contract_summary,
    csv_kernel_readiness_report_key,
    import_csv_bytes,
    load_csv_kernel_readiness_contract_report,
    prepare_csv_kernel_readiness_contract,
    validate_csv_kernel_readiness_contract,
)


def _kernel_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,note\n1,"line\none"\n2,"quote "" kept"\n',
):
    manifest = import_csv_bytes(fs.root, payload, source_name="kernel_ready.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    timeline = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    determinants = commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    ring = commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    assert revalidation.ok is True
    assert timeline.ok is True
    assert determinants.ok is True
    assert ring.ok is True
    return manifest, ring


def test_version_345_csv_kernel_readiness_contract():
    assert __version__ == "3.5.2"


def test_csv_kernel_readiness_prepare_builds_contract_without_native_kernel():
    fs = TDSFileSystem("root")
    manifest, ring = _kernel_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_kernel_readiness_contract(fs.root, manifest.csv_id, chunk_size=3)
    summary = csv_kernel_readiness_contract_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "kernel_contract_ready"
    assert report.mode == "kernel_readiness_prepare"
    assert report.report_key == csv_kernel_readiness_report_key(manifest.csv_id)
    assert report.source_ring_fingerprint == ring.ring_fingerprint
    assert report.source_mirror_fingerprint == ring.mirror_fingerprint
    assert report.timeline_ring_validation_status == "valid"
    assert report.scan_parity_status == "valid"
    assert report.row_anchor_parity_status == "valid"
    assert report.requirement_count == 13
    assert report.required_count == report.ready_count
    assert report.blocked_count == 0
    assert report.contract_fingerprint
    assert report.input_contract_sha256
    assert report.output_contract_sha256
    assert report.failure_contract_sha256
    assert report.benchmark_contract_sha256
    assert report.tds_artifact_writes == 0
    assert report.native_storage_writes is False
    assert report.native_c_engine_changed is False
    assert report.native_csv_kernel_implemented is False
    assert report.native_csv_kernel_used is False
    assert report.native_storage_hot_path_touched is False
    assert report.python_reference_fallback_available is True
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False
    assert summary["contract_fingerprint"] == report.contract_fingerprint
    assert summary["native_csv_kernel_implemented"] is False
    assert after_keys == before_keys


def test_csv_kernel_readiness_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _ = _kernel_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id, chunk_size=2)
    loaded = load_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id)
    validation = validate_csv_kernel_readiness_contract(fs.root, manifest.csv_id, chunk_size=2)

    assert committed.ok is True
    assert committed.status == "kernel_contract_committed"
    assert committed.mode == "kernel_readiness_commit"
    assert committed.tds_artifact_writes == 1
    assert loaded.report_key == csv_kernel_readiness_report_key(manifest.csv_id)
    assert loaded.contract_fingerprint == committed.contract_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_kernel_readiness_requires_committed_interpole_timeline_ring():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="missing_ring.csv")
    commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)

    report = prepare_csv_kernel_readiness_contract(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert any("interpole_timeline_ring_report_unreadable" in error for error in report.errors)
    assert report.native_csv_kernel_used is False
    assert report.formal_ir_committed is False


def test_csv_kernel_readiness_blocks_on_row_offset_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _kernel_ready_csv(fs, b"a,b\n1,2\n3,4\n")
    key = artifact_keys(manifest.csv_id)["row_offsets"]
    row_offsets = fs.root.read_value(key)
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(key, row_offsets, overwrite=True, provenance="DERIVED")

    report = prepare_csv_kernel_readiness_contract(fs.root, manifest.csv_id, chunk_size=2)

    assert report.ok is False
    assert report.status == "blocked"
    assert report.scan_parity_status == "invalid"
    assert report.row_anchor_parity_status == "invalid"
    assert any("scan_row_offsets_mismatch" in error for error in report.errors)
    assert any("anchor_row_offsets_mismatch" in error for error in report.errors)
    assert any(req.requirement_name == "row_offset_parity_contract" and req.status == "blocked" for req in report.requirements)
    assert any(req.requirement_name == "row_anchor_output_contract" and req.status == "blocked" for req in report.requirements)
    assert report.native_storage_writes is False
    assert report.native_csv_kernel_implemented is False


def test_csv_kernel_readiness_validation_detects_persisted_contract_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _kernel_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id)
    key = csv_kernel_readiness_report_key(manifest.csv_id)
    stored = fs.root.read_value(key)
    stored["contract_fingerprint"] = "0" * 64
    fs.root.write_json(key, stored, overwrite=True, provenance="DERIVED")

    validation = validate_csv_kernel_readiness_contract(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert "kernel_readiness_contract_fingerprint_drift" in validation.errors
    assert validation.native_storage_writes is False


def test_csv_kernel_readiness_contract_is_deterministic():
    fs = TDSFileSystem("root")
    manifest, _ = _kernel_ready_csv(fs, b"a,b,c\n1,2,3\n4,5,6\n")

    first = prepare_csv_kernel_readiness_contract(fs.root, manifest.csv_id, chunk_size=4)
    second = prepare_csv_kernel_readiness_contract(fs.root, manifest.csv_id, chunk_size=4)

    assert first.ok is True
    assert second.ok is True
    assert first.contract_fingerprint == second.contract_fingerprint
    assert [(r.requirement_name, r.status, r.evidence_hashes, r.metrics) for r in first.requirements] == [
        (r.requirement_name, r.status, r.evidence_hashes, r.metrics) for r in second.requirements
    ]


def test_csv_kernel_readiness_requirements_are_evidence_mechanical_only():
    fs = TDSFileSystem("root")
    manifest, _ = _kernel_ready_csv(fs)

    report = prepare_csv_kernel_readiness_contract(fs.root, manifest.csv_id)

    assert report.ok is True
    names = {req.requirement_name for req in report.requirements}
    assert "semantic_exclusion_contract" in names
    assert "python_reference_fallback_contract" in names
    assert "benchmark_gate_shape_contract" in names
    for req in report.requirements:
        assert req.ok is True
        assert req.native_kernel_required is False
        assert req.native_kernel_used is False
        assert req.native_storage_hot_path_touched is False
        assert req.semantic_reasoning is False
        assert req.semantic_conclusion is False
        assert req.schema_inference is False
        assert req.type_inference is False
        assert req.entity_inference is False
        assert req.ir_candidate is False
        assert req.per_row_writes is False
        assert req.per_cell_writes is False


def test_csv_kernel_readiness_safe_id_fail_closed():
    fs = TDSFileSystem("root")

    report = prepare_csv_kernel_readiness_contract(fs.root, "../bad")

    assert report.ok is False
    assert report.status == "invalid"
    assert any("csv_id_unsafe" in error for error in report.errors)
    assert report.native_csv_kernel_used is False
    assert report.native_storage_hot_path_touched is False


def test_csv_kernel_readiness_default_chunk_shape_is_guarded():
    fs = TDSFileSystem("root")
    manifest, _ = _kernel_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_kernel_readiness_contract(fs.root, manifest.csv_id, chunk_size=None)

    assert report.ok is True
    chunk_req = next(req for req in report.requirements if req.requirement_name == "chunk_boundary_state_contract")
    assert chunk_req.status == "guarded"
    assert chunk_req.warning == "chunk_boundary_checked_as_single_chunk"
    assert report.warning_count >= 1
    assert any("chunk_boundary_checked_as_single_chunk" in warning for warning in report.warnings)

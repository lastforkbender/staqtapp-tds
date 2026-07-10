from __future__ import annotations

from dataclasses import replace

import pytest

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    CSV_NATIVE_ROW_ANCHOR_KERNEL_VERSION,
    artifact_keys,
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_interpole_timeline_ring_report,
    commit_csv_kernel_readiness_contract_report,
    commit_csv_native_row_anchor_kernel_report,
    commit_csv_native_scan_kernel_prototype_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_native_row_anchor_kernel_report_key,
    csv_native_row_anchor_kernel_summary,
    csv_native_scan_kernel_report_key,
    import_csv_bytes,
    load_csv_native_row_anchor_kernel_report,
    prepare_csv_native_row_anchor_kernel,
    scan_csv_row_anchors,
    validate_csv_native_row_anchor_kernel,
)


def _row_anchor_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,note\n1,"line\none"\n2,"quote "" kept"\n',
    *,
    commit_scan: bool = True,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="native_row_anchor_kernel.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    timeline = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    determinants = commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    ring = commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)
    readiness = commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    assert revalidation.ok is True
    assert timeline.ok is True
    assert determinants.ok is True
    assert ring.ok is True
    assert readiness.ok is True
    scan = None
    if commit_scan:
        scan = commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id, chunk_size=3)
        assert scan.ok is True
    return manifest, scan


def test_version_347_csv_native_row_anchor_kernel():
    assert __version__ == "3.5.2"
    assert CSV_NATIVE_ROW_ANCHOR_KERNEL_VERSION == "1.0"


def test_csv_native_row_anchor_kernel_prepare_default_safe_python_no_write():
    fs = TDSFileSystem("root")
    manifest, scan = _row_anchor_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_native_row_anchor_kernel(fs.root, manifest.csv_id, chunk_size=3)
    summary = csv_native_row_anchor_kernel_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "native_row_anchor_ready"
    assert report.mode == "native_row_anchor_prepare"
    assert report.report_key == csv_native_row_anchor_kernel_report_key(manifest.csv_id)
    assert report.source_native_scan_report_key == csv_native_scan_kernel_report_key(manifest.csv_id)
    assert report.source_native_scan_fingerprint == scan.scan_fingerprint
    assert report.anchor_fingerprint == report.reference_anchor_fingerprint
    assert report.native_scan_validation_status == "valid"
    assert report.scan_parity_status == "valid"
    assert report.row_anchor_parity_status == "valid"
    assert report.requested_native is False
    assert report.native_backend_used is False
    assert report.python_reference_fallback_available is True
    assert report.python_reference_fallback_used is False
    assert report.native_offsets_match_reference is True
    assert report.native_spans_match_reference is True
    assert report.native_anchor_hashes_match_reference is True
    assert report.native_anchor_fingerprint_match_reference is True
    assert report.raw_sha256_verified is True
    assert report.row_count_match is True
    assert report.max_record_span_match is True
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
    assert summary["anchor_fingerprint"] == report.anchor_fingerprint
    assert summary["native_storage_hot_path_touched"] is False
    assert after_keys == before_keys


def test_csv_native_row_anchor_kernel_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id, chunk_size=2)
    loaded = load_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id)
    validation = validate_csv_native_row_anchor_kernel(fs.root, manifest.csv_id, chunk_size=2)

    assert committed.ok is True
    assert committed.status == "native_row_anchor_committed"
    assert committed.mode == "native_row_anchor_commit"
    assert committed.tds_artifact_writes == 1
    assert loaded.report_key == csv_native_row_anchor_kernel_report_key(manifest.csv_id)
    assert loaded.anchor_fingerprint == committed.anchor_fingerprint
    assert loaded.row_offsets_packed_sha256 == committed.row_offsets_packed_sha256
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_native_row_anchor_kernel_requires_committed_native_scan_report():
    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b\n1,2\n", commit_scan=False)

    report = prepare_csv_native_row_anchor_kernel(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert any("native_scan_kernel_report_unreadable" in error for error in report.errors)
    assert report.native_backend_used is False
    assert report.native_storage_hot_path_touched is False
    assert report.formal_ir_committed is False


def test_csv_native_row_anchor_kernel_blocks_on_fresh_scan_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b\n1,2\n3,4\n")
    key = artifact_keys(manifest.csv_id)["row_offsets"]
    row_offsets = fs.root.read_value(key)
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(key, row_offsets, overwrite=True, provenance="DERIVED")

    report = prepare_csv_native_row_anchor_kernel(fs.root, manifest.csv_id, chunk_size=2)

    assert report.ok is False
    assert report.status == "blocked"
    assert report.scan_parity_status == "invalid"
    assert report.row_anchor_parity_status == "invalid"
    assert any("native_scan_kernel_validation_not_valid" in error for error in report.errors)
    assert any("scan_row_offsets_mismatch" in error for error in report.errors)
    assert report.native_storage_writes is False
    assert report.interpole_mutation is False


def test_csv_native_row_anchor_kernel_optional_native_request_uses_sidecar_or_clean_fallback():
    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_native_row_anchor_kernel(fs.root, manifest.csv_id, chunk_size=2, use_native=True)

    assert report.ok is True
    assert report.requested_native is True
    assert report.force_native is False
    assert report.anchor_fingerprint == report.reference_anchor_fingerprint
    assert report.native_offsets_match_reference is True
    assert report.native_spans_match_reference is True
    assert report.native_anchor_hashes_match_reference is True
    assert report.native_storage_hot_path_touched is False
    if report.native_backend_available:
        assert report.native_backend_used is True
        assert report.python_reference_fallback_used is False
        assert "row_offsets" in report.native_backend_name
    else:
        assert report.native_backend_used is False
        assert report.python_reference_fallback_used is True
        assert any("python_reference_fallback_used" in warning for warning in report.warnings)


def test_csv_native_row_anchor_kernel_force_native_fails_closed_when_backend_missing(monkeypatch: pytest.MonkeyPatch):
    import staqtapp_tds.csv_layer.native_row_anchor as native_row_anchor

    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b\n1,2\n")
    monkeypatch.setattr(native_row_anchor, "_load_native_backend", lambda: (None, "", ("synthetic_row_anchor_native_unavailable",)))

    report = prepare_csv_native_row_anchor_kernel(
        fs.root,
        manifest.csv_id,
        chunk_size=2,
        use_native=True,
        force_native=True,
    )

    assert report.ok is False
    assert report.status == "blocked"
    assert report.requested_native is True
    assert report.force_native is True
    assert report.native_backend_used is False
    assert report.python_reference_fallback_used is False
    assert "synthetic_row_anchor_native_unavailable" in report.errors


def test_csv_native_row_anchor_kernel_native_mismatch_blocks_before_commit(monkeypatch: pytest.MonkeyPatch):
    import staqtapp_tds.csv_layer.native_row_anchor as native_row_anchor

    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b\n1,2\n3,4\n")

    class FakeBackend:
        pass

    def fake_profile(raw, dialect, *, encoding, chunk_size, backend, backend_name):
        reference = scan_csv_row_anchors(raw, dialect, encoding=encoding, chunk_size=chunk_size)
        return replace(
            reference,
            row_offsets=(0, 1),
            row_spans=(1, 1),
            row_anchor_hashes=("a", "b"),
            row_count=2,
            scanner="fake.native.row_anchor",
        )

    monkeypatch.setattr(native_row_anchor, "_load_native_backend", lambda: (FakeBackend(), "fake.native.row_anchor", tuple()))
    monkeypatch.setattr(native_row_anchor, "_native_row_anchor_profile", fake_profile)

    report = prepare_csv_native_row_anchor_kernel(
        fs.root,
        manifest.csv_id,
        chunk_size=2,
        use_native=True,
        force_native=True,
    )

    assert report.ok is False
    assert report.status == "blocked"
    assert report.native_backend_available is True
    assert report.native_backend_used is True
    assert "native_row_anchor_offsets_mismatch_reference" in report.errors
    assert "native_row_anchor_spans_mismatch_reference" in report.errors
    assert "native_row_anchor_hashes_mismatch_reference" in report.errors
    assert "native_row_anchor_fingerprint_mismatch_reference" in report.errors
    assert "native_row_anchor_row_count_mismatch" in report.errors
    assert report.native_storage_writes is False


def test_csv_native_row_anchor_kernel_validation_detects_stored_anchor_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id)
    key = csv_native_row_anchor_kernel_report_key(manifest.csv_id)
    stored = fs.root.read_value(key)
    stored["anchor_fingerprint"] = "0" * 64
    stored["row_anchor_hashes_sha256"] = "1" * 64
    fs.root.write_json(key, stored, overwrite=True, provenance="DERIVED")

    validation = validate_csv_native_row_anchor_kernel(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert "native_row_anchor_fingerprint_drift" in validation.errors
    assert "native_row_anchor_hash_list_drift" in validation.errors
    assert validation.native_storage_writes is False


def test_csv_native_row_anchor_kernel_is_deterministic():
    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs, b"a,b,c\n1,2,3\n4,5,6\n")

    first = prepare_csv_native_row_anchor_kernel(fs.root, manifest.csv_id, chunk_size=4)
    second = prepare_csv_native_row_anchor_kernel(fs.root, manifest.csv_id, chunk_size=4)

    assert first.ok is True
    assert second.ok is True
    assert first.anchor_fingerprint == second.anchor_fingerprint
    assert first.reference_anchor_fingerprint == second.reference_anchor_fingerprint
    assert first.row_offsets_packed_sha256 == second.row_offsets_packed_sha256
    assert first.row_spans_sha256 == second.row_spans_sha256
    assert first.row_anchor_hashes_sha256 == second.row_anchor_hashes_sha256
    assert csv_native_row_anchor_kernel_summary(first) == csv_native_row_anchor_kernel_summary(second)


def test_csv_native_row_anchor_kernel_preserves_evidence_neutral_boundaries():
    fs = TDSFileSystem("root")
    manifest, _ = _row_anchor_ready_csv(fs)

    report = prepare_csv_native_row_anchor_kernel(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.native_storage_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.native_storage_locks_controlled is False
    assert report.native_c_storage_engine_changed is False
    assert report.interpole_mutation is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.schema_inference is False
    assert report.type_inference is False
    assert report.entity_inference is False
    assert report.formal_ir_committed is False


def test_csv_native_row_anchor_kernel_safe_id_fail_closed():
    fs = TDSFileSystem("root")

    report = prepare_csv_native_row_anchor_kernel(fs.root, "../bad")

    assert report.ok is False
    assert report.status == "invalid"
    assert any("csv_id_unsafe" in error for error in report.errors)
    assert report.native_backend_used is False
    assert report.native_storage_hot_path_touched is False

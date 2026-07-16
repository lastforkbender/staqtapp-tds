from __future__ import annotations

from dataclasses import replace

import pytest

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.csv_layer import (
    CSV_NATIVE_SCAN_KERNEL_VERSION,
    artifact_keys,
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_interpole_timeline_ring_report,
    commit_csv_kernel_readiness_contract_report,
    commit_csv_native_scan_kernel_prototype_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_native_scan_kernel_report_key,
    csv_native_scan_kernel_summary,
    import_csv_bytes,
    load_csv_native_scan_kernel_prototype_report,
    prepare_csv_native_scan_kernel_prototype,
    scan_csv_bytes,
    validate_csv_native_scan_kernel_prototype,
)


def _native_scan_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,note\n1,"line\none"\n2,"quote "" kept"\n',
    *,
    commit_readiness: bool = True,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="native_scan_kernel.csv")
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
    readiness = None
    if commit_readiness:
        readiness = commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id)
        assert readiness.ok is True
    return manifest, readiness


def test_version_346_csv_native_scan_kernel_prototype():
    assert __version__ == "3.5.3.post1"
    assert CSV_NATIVE_SCAN_KERNEL_VERSION == "1.0"


def test_csv_native_scan_kernel_prepare_default_safe_python_no_write():
    fs = TDSFileSystem("root")
    manifest, readiness = _native_scan_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    report = prepare_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id, chunk_size=3)
    summary = csv_native_scan_kernel_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "native_scan_ready"
    assert report.mode == "native_scan_prepare"
    assert report.report_key == csv_native_scan_kernel_report_key(manifest.csv_id)
    assert report.source_contract_fingerprint == readiness.contract_fingerprint
    assert report.scan_fingerprint == report.reference_scan_fingerprint
    assert report.scan_parity_status == "valid"
    assert report.row_anchor_parity_status == "valid"
    assert report.readiness_validation_status == "valid"
    assert report.requested_native is False
    assert report.native_backend_used is False
    assert report.python_reference_fallback_available is True
    assert report.python_reference_fallback_used is False
    assert report.kernel_row_offsets_match_reference is True
    assert report.kernel_counts_match_reference is True
    assert report.raw_sha256_verified is True
    assert report.row_count_match is True
    assert report.tds_artifact_writes == 0
    assert report.native_storage_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.native_storage_locks_controlled is False
    assert report.native_c_storage_engine_changed is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False
    assert summary["scan_fingerprint"] == report.scan_fingerprint
    assert summary["native_storage_hot_path_touched"] is False
    assert after_keys == before_keys


def test_csv_native_scan_kernel_can_be_committed_loaded_and_validated():
    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b\n1,2\n")

    committed = commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id, chunk_size=2)
    loaded = load_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id)
    validation = validate_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id, chunk_size=2)

    assert committed.ok is True
    assert committed.status == "native_scan_committed"
    assert committed.mode == "native_scan_commit"
    assert committed.tds_artifact_writes == 1
    assert loaded.report_key == csv_native_scan_kernel_report_key(manifest.csv_id)
    assert loaded.scan_fingerprint == committed.scan_fingerprint
    assert validation.ok is True
    assert validation.status == "valid"
    assert validation.mode == "validation"


def test_csv_native_scan_kernel_requires_committed_kernel_readiness_contract():
    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b\n1,2\n", commit_readiness=False)

    report = prepare_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.status == "invalid"
    assert any("kernel_readiness_contract_report_unreadable" in error for error in report.errors)
    assert report.native_backend_used is False
    assert report.native_storage_hot_path_touched is False
    assert report.formal_ir_committed is False


def test_csv_native_scan_kernel_blocks_on_fresh_readiness_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b\n1,2\n3,4\n")
    key = artifact_keys(manifest.csv_id)["row_offsets"]
    row_offsets = fs.root.read_value(key)
    row_offsets["row_offsets"] = [0, 1, 2]
    fs.root.write_json(key, row_offsets, overwrite=True, provenance="DERIVED")

    report = prepare_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id, chunk_size=2)

    assert report.ok is False
    assert report.status == "blocked"
    assert report.scan_parity_status == "invalid"
    assert report.row_anchor_parity_status == "invalid"
    assert any("kernel_readiness_contract_validation_not_valid" in error for error in report.errors)
    assert any("scan_row_offsets_mismatch" in error for error in report.errors)
    assert report.native_storage_writes is False
    assert report.native_storage_hot_path_touched is False


def test_csv_native_scan_kernel_optional_native_request_uses_sidecar_or_clean_fallback():
    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b\n1,2\n")

    report = prepare_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id, chunk_size=2, use_native=True)

    assert report.ok is True
    assert report.requested_native is True
    assert report.force_native is False
    assert report.scan_fingerprint == report.reference_scan_fingerprint
    assert report.native_storage_hot_path_touched is False
    if report.native_backend_available:
        assert report.native_backend_used is True
        assert report.python_reference_fallback_used is False
        assert report.native_backend_name
    else:
        assert report.native_backend_used is False
        assert report.python_reference_fallback_used is True
        assert any("python_reference_fallback_used" in warning for warning in report.warnings)


def test_csv_native_scan_kernel_force_native_fails_closed_when_backend_missing(monkeypatch: pytest.MonkeyPatch):
    import staqtapp_tds.csv_layer.native_scan as native_scan

    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b\n1,2\n")
    monkeypatch.setattr(native_scan, "_load_native_backend", lambda: (None, "", ("synthetic_native_unavailable",)))

    report = prepare_csv_native_scan_kernel_prototype(
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
    assert "synthetic_native_unavailable" in report.errors


def test_csv_native_scan_kernel_native_mismatch_blocks_before_commit(monkeypatch: pytest.MonkeyPatch):
    import staqtapp_tds.csv_layer.native_scan as native_scan

    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b\n1,2\n3,4\n")

    class FakeBackend:
        pass

    def fake_profile(raw, dialect, *, encoding, chunk_size, backend, backend_name):
        reference = scan_csv_bytes(raw, dialect, encoding=encoding, chunk_size=chunk_size)
        return replace(reference, row_offsets=(0, 1), row_count=2, scanner="fake.native.csv")

    monkeypatch.setattr(native_scan, "_load_native_backend", lambda: (FakeBackend(), "fake.native.csv", tuple()))
    monkeypatch.setattr(native_scan, "_native_scan_profile", fake_profile)

    report = prepare_csv_native_scan_kernel_prototype(
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
    assert "native_scan_row_offsets_mismatch_reference" in report.errors
    assert "native_scan_counts_mismatch_reference" in report.errors
    assert "native_scan_fingerprint_mismatch_reference" in report.errors
    assert report.native_storage_writes is False


def test_csv_native_scan_kernel_validation_detects_stored_scan_drift():
    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b\n1,2\n")
    committed = commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id)
    key = csv_native_scan_kernel_report_key(manifest.csv_id)
    stored = fs.root.read_value(key)
    stored["scan_fingerprint"] = "0" * 64
    fs.root.write_json(key, stored, overwrite=True, provenance="DERIVED")

    validation = validate_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id)

    assert committed.ok is True
    assert validation.ok is False
    assert validation.status == "drifted"
    assert "native_scan_profile_fingerprint_drift" in validation.errors
    assert validation.native_storage_writes is False


def test_csv_native_scan_kernel_is_deterministic():
    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs, b"a,b,c\n1,2,3\n4,5,6\n")

    first = prepare_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id, chunk_size=4)
    second = prepare_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id, chunk_size=4)

    assert first.ok is True
    assert second.ok is True
    assert first.scan_fingerprint == second.scan_fingerprint
    assert first.reference_scan_fingerprint == second.reference_scan_fingerprint
    assert csv_native_scan_kernel_summary(first) == csv_native_scan_kernel_summary(second)


def test_csv_native_scan_kernel_preserves_evidence_neutral_boundaries():
    fs = TDSFileSystem("root")
    manifest, _ = _native_scan_ready_csv(fs)

    report = prepare_csv_native_scan_kernel_prototype(fs.root, manifest.csv_id)

    assert report.ok is True
    assert report.native_storage_writes is False
    assert report.native_storage_hot_path_touched is False
    assert report.native_storage_locks_controlled is False
    assert report.native_c_storage_engine_changed is False
    assert report.per_row_writes is False
    assert report.per_cell_writes is False
    assert report.semantic_reasoning is False
    assert report.semantic_conclusions is False
    assert report.schema_inference is False
    assert report.type_inference is False
    assert report.entity_inference is False
    assert report.formal_ir_committed is False


def test_csv_native_scan_kernel_safe_id_fail_closed():
    fs = TDSFileSystem("root")

    report = prepare_csv_native_scan_kernel_prototype(fs.root, "../bad")

    assert report.ok is False
    assert report.status == "invalid"
    assert any("csv_id_unsafe" in error for error in report.errors)
    assert report.native_backend_used is False
    assert report.native_storage_hot_path_touched is False

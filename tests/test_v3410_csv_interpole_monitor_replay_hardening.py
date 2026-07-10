from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.admin.panel import AdminPanelServer
from staqtapp_tds.csv_layer import (
    CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS,
    CSV_INTERPOLE_MONITOR_ICON_NAMES,
    CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT,
    CSV_INTERPOLE_MONITOR_REPLAY_VERSION,
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
    csv_interpole_browser_monitor_display_contract,
    csv_interpole_browser_monitor_display_contract_fingerprint,
    csv_interpole_browser_monitor_replay_summary,
    csv_interpole_browser_monitor_snapshot_fingerprint,
    csv_interpole_browser_monitor_summary,
    csv_interpole_monitor_delivery_manifest,
    csv_interpole_monitor_icon_registry,
    import_csv_bytes,
    prepare_csv_interpole_browser_monitor_snapshot,
    replay_csv_interpole_browser_monitor_snapshot,
    validate_csv_interpole_browser_monitor_snapshot,
    validate_csv_interpole_monitor_icon_registry,
)


def _monitor_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,name,score\n1,Ada,99\n2,Grace,98\n3,Katherine,97\n',
    *,
    chunk_size: int | None = 7,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="browser_csv_interpole_replay.csv")
    bridge = commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)
    replay = commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)
    native_commit = commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)
    revalidation = commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)
    timeline = commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)
    determinants = commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)
    ring = commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)
    readiness = commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id, chunk_size=chunk_size)
    scan = commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id, chunk_size=chunk_size)
    anchor = commit_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id, chunk_size=chunk_size)
    performance = commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)
    assert bridge.ok is True
    assert replay.ok is True
    assert native_commit.ok is True
    assert revalidation.ok is True
    assert timeline.ok is True
    assert determinants.ok is True
    assert ring.ok is True
    assert readiness.ok is True
    assert scan.ok is True
    assert anchor.ok is True
    assert performance.ok is True
    return manifest


def test_version_3410_csv_interpole_monitor_replay_hardening():
    assert __version__ == "3.5.2"
    assert CSV_INTERPOLE_MONITOR_REPLAY_VERSION == "1.0"
    assert CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT >= 65536
    assert "status" in CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS
    assert "formal_ir_committed" in CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS


def test_csv_interpole_monitor_display_contract_is_stable_and_complete():
    contract = csv_interpole_browser_monitor_display_contract()
    fingerprint = csv_interpole_browser_monitor_display_contract_fingerprint()

    assert len(fingerprint) == 64
    assert contract["replay_version"] == CSV_INTERPOLE_MONITOR_REPLAY_VERSION
    assert contract["display_contract_keys"] == list(CSV_INTERPOLE_MONITOR_DISPLAY_CONTRACT_KEYS)
    assert contract["icon_names"] == list(CSV_INTERPOLE_MONITOR_ICON_NAMES)
    assert "semantic_conclusions" in contract["semantic_exclusion_fields"]
    assert "native_storage_hot_path_touched" in contract["mutation_exclusion_fields"]


def test_csv_interpole_monitor_snapshot_validation_is_bounded_and_read_only():
    fs = TDSFileSystem("root")
    manifest = _monitor_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)
    report = validate_csv_interpole_browser_monitor_snapshot(snapshot)
    summary = csv_interpole_browser_monitor_summary(snapshot)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "snapshot_valid"
    assert report.source_snapshot_fingerprint == csv_interpole_browser_monitor_snapshot_fingerprint(snapshot)
    assert report.source_payload_bytes <= CSV_INTERPOLE_MONITOR_PAYLOAD_BYTE_LIMIT
    assert summary["display_contract_fingerprint"] == csv_interpole_browser_monitor_display_contract_fingerprint()
    assert summary["payload_bytes"] == report.source_payload_bytes
    assert report.tds_artifact_writes == 0
    assert report.native_storage_writes is False
    assert report.formal_ir_committed is False
    assert after_keys == before_keys


def test_csv_interpole_monitor_replay_reconstructs_same_display_payload_without_writes():
    fs = TDSFileSystem("root")
    manifest = _monitor_ready_csv(fs)
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)
    before_keys = set(fs.root._entries.keys())

    report = replay_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id, snapshot.to_dict())
    summary = csv_interpole_browser_monitor_replay_summary(report)
    after_keys = set(fs.root._entries.keys())

    assert report.ok is True
    assert report.status == "replay_valid"
    assert report.source_snapshot_fingerprint == report.reconstructed_snapshot_fingerprint
    assert not report.mismatched_fields
    assert "ring_fingerprint" in report.matching_fields
    assert summary["display_contract_status"] == "valid"
    assert report.tds_artifact_writes == 0
    assert report.native_storage_hot_path_touched is False
    assert report.interpole_mutation is False
    assert report.semantic_conclusions is False
    assert report.formal_ir_committed is False
    assert after_keys == before_keys


def test_csv_interpole_monitor_replay_blocks_tampered_snapshot():
    fs = TDSFileSystem("root")
    manifest = _monitor_ready_csv(fs)
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id).to_dict()
    snapshot["performance_gate_fingerprint"] = "0" * 64

    report = replay_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id, snapshot)

    assert report.ok is False
    assert report.status == "replay_blocked"
    assert "performance_gate_fingerprint" in report.mismatched_fields
    assert any(error == "snapshot_mismatch:performance_gate_fingerprint" for error in report.errors)
    assert report.native_storage_writes is False
    assert report.formal_ir_committed is False


def test_csv_interpole_monitor_snapshot_validation_blocks_corruption_and_oversize():
    fs = TDSFileSystem("root")
    manifest = _monitor_ready_csv(fs)
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id).to_dict()
    snapshot["icon_names"] = list(snapshot["icon_names"])[:-1]
    snapshot["cards"] = [card for card in snapshot["cards"] if card["card_name"] != "Semantic Boundary"]

    report = validate_csv_interpole_browser_monitor_snapshot(snapshot)
    small_limit_report = validate_csv_interpole_browser_monitor_snapshot(
        prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id),
        payload_byte_limit=128,
    )

    assert report.ok is False
    assert report.status == "snapshot_blocked"
    assert "icon_registry_mismatch" in report.errors
    assert "required_card_missing:Semantic Boundary" in report.errors
    assert small_limit_report.ok is False
    assert small_limit_report.payload_status == "oversized"
    assert any(error.startswith("payload_too_large:") for error in small_limit_report.errors)


def test_csv_interpole_monitor_icon_registry_validates_packaged_svg_payloads():
    registry = csv_interpole_monitor_icon_registry()
    panel = AdminPanelServer()
    payloads: dict[str, bytes] = {}
    for name in CSV_INTERPOLE_MONITOR_ICON_NAMES:
        asset = panel._static_asset(registry[name])
        assert asset is not None
        payloads[name] = asset[0]

    report = validate_csv_interpole_monitor_icon_registry(registry, svg_payloads=payloads)

    assert report.ok is True
    assert report.status == "valid"
    assert report.icon_count == len(CSV_INTERPOLE_MONITOR_ICON_NAMES)
    assert len(report.registry_fingerprint) == 64
    assert not report.missing_icons
    assert not report.unsafe_svg_names
    assert not report.unbounded_svg_names


def test_csv_interpole_monitor_icon_registry_fails_closed_on_missing_or_unsafe_svg():
    registry = dict(csv_interpole_monitor_icon_registry())
    registry.pop("csv-drift-flag")
    payloads = {name: b"<svg viewBox='0 0 10 10'></svg>" for name in CSV_INTERPOLE_MONITOR_ICON_NAMES if name != "csv-drift-flag"}
    payloads["csv-interpole"] = b"<svg><script>alert(1)</script></svg>"

    report = validate_csv_interpole_monitor_icon_registry(registry, svg_payloads=payloads)

    assert report.ok is False
    assert "csv-drift-flag" in report.missing_icons
    assert "csv-interpole" in report.unsafe_svg_names
    assert any(error.startswith("missing_icon:") for error in report.errors)
    assert any(error.startswith("unsafe_svg:") for error in report.errors)


def test_csv_interpole_monitor_delivery_manifest_freezes_bundle_shape():
    manifest = csv_interpole_monitor_delivery_manifest()

    assert manifest.ok is True
    assert manifest.release_version == "3.4.10"
    assert manifest.package_name.endswith("csv_interpole_monitor_replay_hardening.zip")
    assert manifest.state_packet_name == "TDS_v3_4_10_CSV_State_Packet.txt"
    assert manifest.sha256sums_name == "SHA256SUMS.txt"
    assert manifest.validation_name == "RELEASE_VALIDATION.txt"
    assert manifest.to_dict()["required_member_names"] == list(manifest.required_member_names)


def test_csv_interpole_monitor_replay_invalid_id_fails_closed():
    fs = TDSFileSystem("root")
    report = replay_csv_interpole_browser_monitor_snapshot(fs.root, "../bad", {})

    assert report.ok is False
    assert report.status == "replay_blocked"
    assert report.payload_status == "invalid"
    assert any(error.startswith("csv_id_unsafe:") for error in report.errors)
    assert report.native_storage_writes is False
    assert report.formal_ir_committed is False

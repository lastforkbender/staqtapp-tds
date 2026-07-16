from __future__ import annotations

from staqtapp_tds import TDSFileSystem, __version__
from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.admin.panel import AdminPanelServer, render_dashboard_html
from staqtapp_tds.csv_layer import (
    CSV_INTERPOLE_BROWSER_MONITOR_VERSION,
    CSV_INTERPOLE_MONITOR_ICON_NAMES,
    CSVInterpoleBrowserMonitorSnapshot,
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
    csv_interpole_browser_monitor_summary,
    csv_interpole_monitor_icon_registry,
    import_csv_bytes,
    prepare_csv_interpole_browser_monitor_snapshot,
)


def _monitor_ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,name,score\n1,Ada,99\n2,Grace,98\n3,Katherine,97\n',
    *,
    chunk_size: int | None = 7,
    include_performance: bool = True,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="browser_csv_interpole_monitor.csv")
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
    performance = None
    if include_performance:
        performance = commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)
        assert performance.ok is True
    return manifest, ring, readiness, scan, anchor, performance


def test_version_349_csv_interpole_browser_monitor():
    assert __version__ == "3.5.3.post1"
    assert CSV_INTERPOLE_BROWSER_MONITOR_VERSION == "1.0"
    assert "csv-interpole" in CSV_INTERPOLE_MONITOR_ICON_NAMES
    assert "csv-performance-gate" in CSV_INTERPOLE_MONITOR_ICON_NAMES


def test_csv_interpole_browser_monitor_snapshot_is_read_only_and_complete():
    fs = TDSFileSystem("root")
    manifest, ring, readiness, scan, anchor, performance = _monitor_ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)
    summary = csv_interpole_browser_monitor_summary(snapshot)
    after_keys = set(fs.root._entries.keys())

    assert snapshot.ok is True
    assert snapshot.status == "monitor_ready"
    assert snapshot.mode == "browser_monitor_snapshot"
    assert snapshot.ring_state in {"stable", "watch"}
    assert snapshot.mirror_state == "coherent"
    assert snapshot.kernel_readiness_state == "ready"
    assert snapshot.performance_gate_state == "passed"
    assert snapshot.ring_fingerprint == ring.ring_fingerprint
    assert snapshot.mirror_fingerprint == ring.mirror_fingerprint
    assert snapshot.kernel_contract_fingerprint == readiness.contract_fingerprint
    assert snapshot.performance_gate_fingerprint == performance.performance_gate_fingerprint
    assert snapshot.ring_nodes and len(snapshot.ring_nodes) == 6
    assert snapshot.signal_lanes
    assert snapshot.gate_rows
    assert snapshot.cards
    assert snapshot.event_rows
    assert snapshot.icon_names == CSV_INTERPOLE_MONITOR_ICON_NAMES
    assert summary["card_count"] == len(snapshot.cards)
    assert summary["ring_node_count"] == len(snapshot.ring_nodes)
    assert summary["signal_lane_count"] == len(snapshot.signal_lanes)
    assert summary["event_row_count"] == len(snapshot.event_rows)
    assert snapshot.tds_artifact_writes == 0
    assert snapshot.native_storage_writes is False
    assert snapshot.native_storage_hot_path_touched is False
    assert snapshot.native_storage_locks_controlled is False
    assert snapshot.native_c_storage_engine_changed is False
    assert snapshot.interpole_mutation is False
    assert snapshot.per_row_writes is False
    assert snapshot.per_cell_writes is False
    assert snapshot.semantic_reasoning is False
    assert snapshot.semantic_conclusions is False
    assert snapshot.schema_inference is False
    assert snapshot.type_inference is False
    assert snapshot.entity_inference is False
    assert snapshot.formal_ir_committed is False
    assert after_keys == before_keys


def test_csv_interpole_browser_monitor_blocks_without_performance_gate_report():
    fs = TDSFileSystem("root")
    manifest, *_ = _monitor_ready_csv(fs, b'a,b\n1,2\n', include_performance=False)

    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)

    assert snapshot.ok is False
    assert snapshot.status == "invalid"
    assert snapshot.native_storage_hot_path_touched is False
    assert snapshot.formal_ir_committed is False
    assert any("csv_interpole_monitor_sources_unreadable" in error for error in snapshot.errors)


def test_csv_interpole_browser_monitor_detects_source_drift():
    fs = TDSFileSystem("root")
    manifest, *_ = _monitor_ready_csv(fs, b'a,b\n1,2\n3,4\n')
    fs.root.write_text(f"csv__{manifest.csv_id}__raw.csv", "a,b\n9,9\n", overwrite=True, provenance="REAL")

    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)

    assert snapshot.ok is False
    assert snapshot.status == "blocked"
    assert snapshot.ring_state == "drifted"
    assert snapshot.kernel_readiness_state == "blocked"
    assert snapshot.performance_gate_state == "failed"
    assert snapshot.native_storage_writes is False
    assert snapshot.semantic_conclusions is False


def test_csv_interpole_browser_monitor_round_trips_as_mapping():
    fs = TDSFileSystem("root")
    manifest, *_ = _monitor_ready_csv(fs, b'a,b\n1,2\n')
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)

    restored = CSVInterpoleBrowserMonitorSnapshot.from_mapping(snapshot.to_dict())

    assert restored.ok is True
    assert restored.ring_fingerprint == snapshot.ring_fingerprint
    assert restored.cards[0].card_name == snapshot.cards[0].card_name
    assert restored.ring_nodes[0].stage_name == snapshot.ring_nodes[0].stage_name
    assert restored.signal_lanes[0].lane_name == snapshot.signal_lanes[0].lane_name
    assert restored.icon_names == CSV_INTERPOLE_MONITOR_ICON_NAMES


def test_csv_interpole_browser_monitor_icon_registry_matches_packaged_assets():
    registry = csv_interpole_monitor_icon_registry()
    panel = AdminPanelServer()

    assert set(registry) == set(CSV_INTERPOLE_MONITOR_ICON_NAMES)
    for name, path in registry.items():
        assert path == f"/static/icons/{name}.svg"
        asset = panel._static_asset(path)
        assert asset is not None
        data, ctype = asset
        assert ctype == "image/svg+xml"
        assert b"<svg" in data
        assert b"linearGradient" in data


def test_csv_interpole_browser_monitor_page_is_packaged_in_existing_browser():
    html = render_dashboard_html(version="3.4.10")

    assert "CSV Interpole Monitor" in html
    assert "csv-interpole-page" in html
    assert "csv-monitor-strip" in html
    assert "csv-ring-nodes" in html
    assert "csv-gate-stack" in html
    assert "csv-signal-lanes" in html
    assert "csv-event-log" in html
    assert "csv-timeline-ring.svg" in html
    assert "no schema" in html.lower()


def test_csv_interpole_browser_monitor_js_and_css_are_packaged():
    panel = AdminPanelServer()
    js = panel._static_asset("/static/js/dashboard.js")
    css = panel._static_asset("/static/css/dashboard.css")

    assert js is not None
    js_data, js_ctype = js
    assert js_ctype == "application/javascript"
    assert b"renderCSVInterpoleMonitor" in js_data
    assert b"csv_interpole_monitor" in js_data
    assert b"csv-monitor-cards" in js_data
    assert b"csv-gate-stack" in js_data

    assert css is not None
    css_data, css_ctype = css
    assert css_ctype == "text/css"
    assert b"v3.4.10 CSV Interpole Monitor page" in css_data
    assert b"csv-interpole-page" in css_data
    assert b"csv-monitor-card" in css_data
    assert b"csv-ring-visual" in css_data


def test_admin_control_can_surface_csv_interpole_monitor_snapshot():
    fs = TDSFileSystem("root")
    manifest, *_ = _monitor_ready_csv(fs, b'a,b\n1,2\n')
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)

    class Source:
        def observation_snapshot(self):
            return {"health": {"state": "healthy"}}

        def csv_interpole_monitor_snapshot(self):
            return snapshot

    status = AdminControl(observation_source=Source()).status()

    assert "csv_interpole_monitor" in status
    assert status["csv_interpole_monitor"]["status"] == "monitor_ready"
    assert status["csv_interpole_monitor"]["formal_ir_committed"] is False


def test_csv_interpole_browser_monitor_caps_lanes_and_events():
    fs = TDSFileSystem("root")
    manifest, *_ = _monitor_ready_csv(fs)

    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id, max_signal_lanes=3, max_event_rows=2)

    assert snapshot.ok is True
    assert len(snapshot.signal_lanes) == 3
    assert len(snapshot.event_rows) == 2


def test_csv_interpole_browser_monitor_invalid_id_fails_closed():
    fs = TDSFileSystem("root")

    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, "../bad")

    assert snapshot.ok is False
    assert snapshot.status == "invalid"
    assert snapshot.ring_state == "blocked"
    assert snapshot.tds_artifact_writes == 0
    assert snapshot.native_storage_writes is False
    assert snapshot.formal_ir_committed is False

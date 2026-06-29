from __future__ import annotations

from staqtapp_tds.admin.panel import AdminPanelServer, HTML, render_dashboard_html


def test_v235_professional_dashboard_has_polished_sections_and_assets():
    html = render_dashboard_html(version="2.3.5")
    assert "Professional Observability Dashboard" in html
    assert "LIVE ARCHITECTURE" in html
    assert "Timeline" in html
    assert "hero-orbit" in html
    assert "/static/icons/swiss.svg" in html
    assert "/static/icons/radix.svg" in html
    assert "/static/icons/timeline.svg" in html
    assert "window.STAQTAPP_REFRESH_MS" in html
    assert "Snapshot-only" in html
    assert "<table" not in html.lower()


def test_v235_professional_dashboard_assets_are_packaged():
    panel = AdminPanelServer()
    for path in [
        "/static/icons/swiss.svg",
        "/static/icons/radix.svg",
        "/static/icons/chunks.svg",
        "/static/icons/compression.svg",
        "/static/icons/persistence.svg",
        "/static/icons/timeline.svg",
    ]:
        asset = panel._static_asset(path)
        assert asset is not None
        body, ctype = asset
        assert ctype == "image/svg+xml"
        assert b"<svg" in body


def test_v235_panel_status_reports_professional_observer_ui():
    panel = AdminPanelServer()
    snap = panel._status_snapshot()
    assert snap["panel"]["ui"] == "professional-observability-dashboard"
    assert snap["panel"]["snapshot_only"] is True
    assert snap["panel"]["deep_diagnostics_manual_only"] is True


def test_v235_html_compatibility_tokens_preserved_for_existing_tests():
    assert "Telemetry Cache" in HTML
    assert "WORKLOAD" in HTML
    assert "Reads/sec" in HTML
    assert "Writes/sec" in HTML
    assert "--blue" in HTML
    assert "--purple" in HTML
    assert "--orange" in HTML

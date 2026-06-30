from __future__ import annotations

from staqtapp_tds.admin.panel import AdminPanelServer, HTML, render_dashboard_html


def test_v231_dashboard_is_packaged_asset_driven():
    html = render_dashboard_html(version="2.4.2")
    assert "Telemetry &amp; Observability Dashboard" in html
    assert "/static/css/dashboard.css" in html
    assert "/static/js/dashboard.js" in html
    assert "/static/icons/overview.svg" in html
    assert "Current Workload" in html
    assert "Top Namespaces" in html
    assert "Persistence Queue" in html
    assert "Recommendations" in html
    assert "<table" not in html.lower()
    assert HTML.startswith("<!doctype html>")


def test_v231_static_asset_loader_serves_real_icons_and_css():
    panel = AdminPanelServer()
    css = panel._static_asset("/static/css/dashboard.css")
    icon = panel._static_asset("/static/icons/logo.svg")
    js = panel._static_asset("/static/js/dashboard.js")
    assert css is not None and css[1] == "text/css" and b"--purple" in css[0]
    assert icon is not None and icon[1] == "image/svg+xml" and b"<svg" in icon[0]
    assert js is not None and js[1] == "application/javascript" and b"refreshDashboard" in js[0]


def test_v231_static_asset_loader_rejects_traversal():
    panel = AdminPanelServer()
    assert panel._static_asset("/static/../panel.py") is None

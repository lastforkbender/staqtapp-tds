from __future__ import annotations

from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import AdminPanelServer, render_dashboard_html


def test_v273_version():
    assert __version__ == "3.1.26"


def test_v273_dashboard_has_categorized_engineering_navigation():
    html = render_dashboard_html(version="2.8.1")
    assert "Pressure Diagnostics" in html
    assert "Snapshot Explorer" in html
    assert "Lock Contention" in html
    assert "Recovery Planner" in html
    assert "Policy Proposals" in html
    assert "Alerts &amp; Events" in html
    assert "diagnostic-nav" in html
    assert "console-page-grid" in html
    assert "pressure-diagnostics-page" in html
    assert "<table" not in html.lower()


def test_v273_dashboard_css_contains_console_redesign_tokens():
    panel = AdminPanelServer()
    asset = panel._static_asset("/static/css/dashboard.css")
    assert asset is not None
    css, ctype = asset
    assert ctype == "text/css"
    assert b"v2.7.3 console redesign" in css
    assert b"diagnostic-nav" in css
    assert b"console-page-grid" in css
    assert b"pressure-diagnostics-page" in css

from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import AdminPanelServer, render_dashboard_html


def test_v279_version():
    assert __version__ == "2.9.4"


def test_v279_completed_telemetry_pages_render():
    html = render_dashboard_html(version="2.8.1")
    assert "telemetry-snapshots-page" in html
    assert "lock-contention-chip" in html
    assert "comparison-grid" in html
    assert "alerts-list" in html
    assert "page-placeholder" not in html


def test_v279_dashboard_js_renders_completed_pages():
    panel = AdminPanelServer()
    asset = panel._static_asset("/static/js/dashboard.js")
    assert asset is not None
    data, ctype = asset
    assert ctype == "application/javascript"
    assert b"renderCompletedTelemetryPages" in data
    assert b"renderAlertsPage" in data
    assert b"snapshot-ring-fill" in data
    assert b"compare-native-exec" in data


def test_v279_telemetry_css_is_packaged():
    panel = AdminPanelServer()
    asset = panel._static_asset("/static/css/dashboard.css")
    assert asset is not None
    data, ctype = asset
    assert ctype == "text/css"
    assert b"v2.8.1 completed browser telemetry pages" in data
    assert b"telemetry-summary-grid" in data
    assert b"comparison-tile" in data
    assert b"alert-row" in data

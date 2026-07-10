from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import HTML, AdminPanelServer


def test_v275_version():
    assert __version__ == "3.5.2"


def test_v275_status_json_serializer_imported():
    snap = AdminPanelServer()._status_snapshot()
    assert snap["panel"]["snapshot_only"] is True


def test_v275_dashboard_hotfix_markup():
    assert "diagnostics-grid" in HTML
    assert "maintenance-pct" in HTML
    assert "health-ring" in HTML
    assert 'aria-label="Dashboard"' in HTML
    assert 'class="js-json"' not in HTML

from __future__ import annotations

from staqtapp_tds.admin.panel import AdminPanelServer, HTML, PANEL_REFRESH_SECONDS


def test_admin_panel_uses_dark_staqtapp_theme_tokens():
    assert "STAQTAPP-TDS" in HTML
    assert "--blue" in HTML
    assert "--purple" in HTML
    assert "--orange" in HTML
    assert "linear-gradient" in HTML
    assert "LIVE ARCHITECTURE" in HTML


def test_admin_panel_status_snapshot_is_observer_only():
    panel = AdminPanelServer()
    snap = panel._status_snapshot()
    assert snap["system_health"] == "HEALTHY"
    assert snap["panel"]["snapshot_only"] is True
    assert snap["panel"]["deep_diagnostics_manual_only"] is True
    assert snap["panel"]["refresh_seconds"] == PANEL_REFRESH_SECONDS


def test_admin_panel_refresh_interval_is_not_aggressive():
    assert PANEL_REFRESH_SECONDS >= 2.0

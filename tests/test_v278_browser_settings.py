from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import AdminPanelServer, render_dashboard_html


def test_v278_version():
    assert __version__ == "2.8.0"


def test_v278_settings_page_and_about_dialog_render():
    html = render_dashboard_html(version="2.8.0")
    assert "settings-page" in html
    assert "tds-language-select" in html
    assert "tds-startup-select" in html
    assert "tds-refresh-select" in html
    assert "tds-about-dialog" in html
    assert "Stage next generation" not in html


def test_v278_browser_localization_assets_are_packaged():
    panel = AdminPanelServer()
    asset = panel._static_asset("/static/js/i18n.js")
    assert asset is not None
    data, ctype = asset
    assert ctype == "application/javascript"
    assert b"PACK_BASE" in data
    assert b"static/i18n" in data
    assert b"getRefreshMS" in data


def test_v278_layout_safe_localization_css_present():
    panel = AdminPanelServer()
    asset = panel._static_asset("/static/css/dashboard.css")
    assert asset is not None
    data, ctype = asset
    assert ctype == "text/css"
    assert b"overflow-wrap:anywhere" in data
    assert b"min-width:0" in data
    assert b"settings-form" in data

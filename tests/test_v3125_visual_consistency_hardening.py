from pathlib import Path

from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import AdminPanelServer
from staqtapp_tds.studio_pyqt5 import DEFAULT_STUDIO_QT_THEME, studio_pyqt5_shell_capability_matrix


ROOT = Path(__file__).resolve().parents[1]


def test_v3125_version():
    assert __version__ == "3.1.25"


def test_browser_visual_consistency_css_is_packaged():
    panel = AdminPanelServer()
    asset = panel._static_asset("/static/css/dashboard.css")
    assert asset is not None
    css, ctype = asset
    assert ctype == "text/css"
    assert b"v3.1.25 browser visual consistency hardening" in css
    assert b".sidebar{display:flex;flex-direction:column;height:100vh;overflow:hidden" in css
    assert b".diagnostic-nav{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden" in css
    assert b".side-card{position:static;left:auto;right:auto;bottom:auto" in css
    assert b"@media(max-width:1440px){.dashboard-grid,.quad-grid,.lower-grid{grid-template-columns:repeat(2,minmax(0,1fr))}" in css
    assert b".workload-wrap{grid-template-columns:minmax(128px,156px) minmax(0,1fr)" in css


def test_readme_embeds_browser_telemetry_overview_screenshot():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    screenshot = ROOT / "docs" / "screenshots" / "tds_browser_telemetry_overview_1280x800.png"
    assert screenshot.exists()
    assert screenshot.stat().st_size < 10 * 1024 * 1024
    assert "docs/screenshots/tds_browser_telemetry_overview_1280x800.png" in readme
    assert "width=\"100%\"" in readme
    assert "Browser Operations Console" in readme


def test_studio_pyqt5_visual_styles_are_static_and_observe_only():
    stylesheet = DEFAULT_STUDIO_QT_THEME.stylesheet()
    assert "QFrame#ManualBuilderPanel" in stylesheet
    assert "QGroupBox" in stylesheet
    assert "QScrollArea" in stylesheet
    assert "QPlainTextEdit#ManualBuilderPreview" in stylesheet
    assert "min-height: 30px" in stylesheet

    source = (ROOT / "src" / "staqtapp_tds" / "studio_pyqt5" / "main_window.py").read_text(encoding="utf-8")
    assert "self.setMinimumSize(1280, 800)" in source
    assert "self.setDockOptions(" in source
    assert "AllowNestedDocks" in source
    assert "AllowTabbedDocks" in source
    assert "dock.setMinimumHeight(220)" in source
    assert "ManualBuilderPreview" in source
    assert "splitter.setStretchFactor(0, 1)" in source
    assert "splitter.setStretchFactor(1, 2)" in source

    matrix = studio_pyqt5_shell_capability_matrix()
    assert matrix["render_cockpit"] is True
    assert matrix["write_storage"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["activate_driver"] is False
    assert matrix["store_private_keys"] is False

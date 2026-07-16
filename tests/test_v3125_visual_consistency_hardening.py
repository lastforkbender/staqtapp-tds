from pathlib import Path
import hashlib
import struct

from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import AdminPanelServer
from staqtapp_tds.studio_pyqt5 import DEFAULT_STUDIO_QT_THEME, studio_pyqt5_shell_capability_matrix


ROOT = Path(__file__).resolve().parents[1]


def test_v3125_version():
    assert __version__ == "3.5.3.post1"


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


CAPTURE_FILES = (
    "01-dashboard-1280x800.png",
    "02-engine-health-1280x800.png",
    "03-real-time-metrics-1280x800.png",
    "04-transition-timeline-1280x800.png",
    "05-event-ring-monitor-1280x800.png",
    "06-pressure-diagnostics-1280x800.png",
    "07-csv-interpole-1280x800.png",
    "08-snapshot-explorer-1280x800.png",
    "09-lock-contention-1280x800.png",
    "10-workload-analytics-1280x800.png",
    "11-spiral-rank-1280x800.png",
    "12-index-analytics-1280x800.png",
    "13-storage-analytics-1280x800.png",
    "14-comparative-views-1280x800.png",
    "15-recovery-planner-1280x800.png",
    "16-policy-proposals-1280x800.png",
    "17-alerts-events-1280x800.png",
    "18-security-1280x800.png",
    "19-settings-1280x800.png",
)


def test_readmes_embed_all_genuine_browser_pages_vertically():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_ja = (ROOT / "README_ja.md").read_text(encoding="utf-8")
    capture_root = ROOT / "docs" / "screenshots" / "browser_pages"
    positions = []
    positions_ja = []
    digests = set()

    for filename in CAPTURE_FILES:
        screenshot = capture_root / filename
        assert screenshot.exists()
        data = screenshot.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", data[16:24]) == (1280, 800)
        assert screenshot.stat().st_size < 10 * 1024 * 1024
        digests.add(hashlib.sha256(data).hexdigest())
        relative = f"docs/screenshots/browser_pages/{filename}"
        positions.append(readme.index(relative))
        positions_ja.append(readme_ja.index(relative))

    assert len(digests) == len(CAPTURE_FILES)
    assert positions == sorted(positions)
    assert positions_ja == sorted(positions_ja)
    assert "Page 07 is the actual CSV Interpole Monitor" in readme
    assert "not a stitched Dashboard image or a UI mock" in readme
    assert "width=\"100%\"" in readme
    assert "tds_browser_telemetry_overview_1280x800.png" not in readme
    assert "tds_browser_telemetry_overview_1280x800.png" not in readme_ja
    assert not (ROOT / "docs" / "screenshots" / "tds_browser_telemetry_overview_1280x800.png").exists()


def test_browser_page_capture_driver_enforces_real_selected_pages():
    driver = (ROOT / "scripts" / "capture_browser_pages.cjs").read_text(encoding="utf-8")
    fixture = (ROOT / "scripts" / "serve_browser_release_snapshot.py").read_text(encoding="utf-8")

    assert 'navCount !== pages.length' in driver
    assert 'classList.contains("active")' in driver
    assert 'state.hash !== hash' in driver
    assert '"Monitor Ready"' in driver
    assert "prepare_csv_interpole_browser_monitor_snapshot" in fixture
    assert 'getattr(report, "ok", False)' in fixture


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

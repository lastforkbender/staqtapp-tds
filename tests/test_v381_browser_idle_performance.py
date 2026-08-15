from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "src" / "staqtapp_tds" / "admin"
TEMPLATE = ADMIN / "templates" / "dashboard.html"
MIRROR = ADMIN / "dashboard.html"
JS = ADMIN / "static" / "js" / "dashboard.js"
I18N_JS = ADMIN / "static" / "js" / "i18n.js"
CSS = ADMIN / "static" / "css" / "dashboard.css"

PAGES = (
    "overview",
    "architecture",
    "performance",
    "timeline",
    "diagnostics",
    "pressure",
    "csv-interpole",
    "snapshots",
    "locks",
    "behavior",
    "spiral-rank",
    "indexes",
    "storage",
    "comparison",
    "recovery",
    "recommendations",
    "alerts",
    "security",
    "configuration",
)


class _DashboardContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.nav_targets: list[str] = []
        self.page_owners: set[str] = set()
        self.hidden_owners: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        element_id = values.get("id")
        if element_id:
            self.ids.add(element_id)
        if tag == "a" and "nav-pill" in classes:
            href = values.get("href") or ""
            if href.startswith("#"):
                self.nav_targets.append(href[1:])
        owned = set((values.get("data-dashboard-page") or "").split())
        owned.update((values.get("data-dashboard-page-shell") or "").split())
        self.page_owners.update(owned)
        if "hidden" in values:
            self.hidden_owners.update(owned)


def _parse(html: str) -> _DashboardContractParser:
    parser = _DashboardContractParser()
    parser.feed(html)
    return parser


def test_browser_templates_define_exact_single_page_contract_for_all_19_targets() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    mirror = MIRROR.read_text(encoding="utf-8")
    assert template == mirror

    parsed = _parse(template)
    assert tuple(parsed.nav_targets) == PAGES
    assert set(PAGES) <= parsed.ids
    assert parsed.page_owners == set(PAGES)
    assert parsed.hidden_owners == set(PAGES) - {"overview"}
    assert 'aria-current="page"' in template


def test_navigation_uses_hash_history_and_immediate_single_page_switching() -> None:
    js = JS.read_text(encoding="utf-8")
    i18n_js = I18N_JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "const DASHBOARD_PAGES = Object.freeze([" in js
    assert "activateDashboardPage" in js
    assert "event.preventDefault()" in js
    assert "window.history.pushState" in js
    assert "window.history.replaceState" in js
    assert "window.addEventListener('hashchange'" in js
    assert "link.setAttribute('aria-current', 'page')" in js
    assert "window.scrollTo({ top: 0, left: 0, behavior: 'auto' })" in js
    assert "scrollIntoView" not in js
    assert "behavior: 'smooth'" not in i18n_js
    assert "window.TDSDashboardNavigation.activate" in i18n_js
    assert "scroll-behavior:auto" in css
    assert ".dashboard-page[hidden],.dashboard-page-shell[hidden]{display:none!important}" in css


def test_refresh_is_serialized_change_only_and_visibility_aware() -> None:
    js = JS.read_text(encoding="utf-8")

    assert "setInterval" not in js
    assert "clearInterval" not in js
    assert "setTimeout" in js
    assert "await refreshDashboard(this.controller.signal)" in js
    assert "this.running" in js
    assert "new AbortController()" in js
    assert "document.addEventListener('visibilitychange'" in js
    assert "if(document.hidden) window.TDSDashboardRefresh.pause()" in js
    assert "else window.TDSDashboardRefresh.resume()" in js
    assert "window.TDSBrowserSettings.getRefreshMS()" in js
    assert "if (el.textContent === next) return false" in js
    assert "el.style[property] === value" in js
    assert "const renderSignatures = new WeakMap()" in js
    assert "host.replaceChildren(fragment)" in js
    assert "renderActiveDashboardPage(data" in js
    assert "applyTranslations(document.getElementById('spiral-rank'))" not in js


def test_all_rendered_refresh_choices_survive_settings_sanitization() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    i18n_js = I18N_JS.read_text(encoding="utf-8")

    rendered_values = {0}
    for value in ("1000", "2000", "5000", "10000"):
        assert f'<option value="{value}">' in html
        rendered_values.add(int(value))

    assert "new Set([0,250,500,1000,2000,5000,10000])" in i18n_js
    assert rendered_values <= {0, 250, 500, 1000, 2000, 5000, 10000}


def test_idle_css_avoids_continuous_blur_and_motion_compositing() -> None:
    css = CSS.read_text(encoding="utf-8")

    assert "backdrop-filter" not in css
    assert "filter:blur" not in css
    assert "animation:pulse" not in css
    assert "animation:spin" not in css
    assert ".aurora{position:absolute" in css
    assert "--blue:#1685ff" in css
    assert "--purple:#b35cff" in css
    assert "--orange:#ff980e" in css


def test_workspace_mount_status_chip_is_optional_and_change_only() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")

    assert 'id="workspace-mount-chip" aria-live="polite" hidden' in html
    assert "const mount=data && data.workspace_mount" in js
    assert "setHidden(chip, true)" in js
    assert "['ready','stale','unavailable','invalid']" in js

import json

from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import AdminPanelServer, render_dashboard_html


def _asset(path: str):
    panel = AdminPanelServer()
    asset = panel._static_asset(path)
    assert asset is not None, path
    data, ctype = asset
    return data.decode("utf-8"), ctype


def test_v280_version():
    assert __version__ == "2.9.0"


def test_v280_language_pack_manifest_is_packaged():
    text, ctype = _asset("/static/i18n/manifest.json")
    assert ctype == "application/json"
    manifest = json.loads(text)
    assert manifest["default"] == "en"
    assert [item["code"] for item in manifest["languages"]] == ["en", "es", "pt", "ja", "de", "fr", "it"]


def test_v280_each_language_pack_has_complete_browser_strings():
    manifest = json.loads(_asset("/static/i18n/manifest.json")[0])
    english = json.loads(_asset("/static/i18n/en.json")[0])
    required = {
        "Telemetry & Observability Dashboard",
        "Snapshot Explorer",
        "Lock Contention",
        "Comparative Views",
        "Alerts & Events",
        "Recovery Planner is observing pressure snapshots and no action is currently required.",
        "Staqtapp-TDS Browser is a professional, language-ready operations console for observing TDS without mutating the storage hot path.",
    }
    assert required.issubset(english)
    for lang in manifest["languages"]:
        pack = json.loads(_asset(f"/static/i18n/{lang['code']}.json")[0])
        assert set(english) == set(pack)
        assert all(pack[key] for key in english)


def test_v280_dashboard_uses_external_language_packs():
    html = render_dashboard_html(version="2.8.1")
    assert "/static/js/i18n.js" in html
    assert "tds-language-select" in html
    assert "2.8.1" in html
    js, ctype = _asset("/static/js/i18n.js")
    assert ctype == "application/javascript"
    assert "PACK_BASE = '/static/i18n/'" in js
    assert "applyTranslations" in js
    assert "getRefreshMS" in js


def test_v280_translation_quality_terms_present():
    pt = json.loads(_asset("/static/i18n/pt.json")[0])
    de = json.loads(_asset("/static/i18n/de.json")[0])
    ja = json.loads(_asset("/static/i18n/ja.json")[0])
    assert pt["Telemetry & Observability Dashboard"] == "Painel de telemetria e observabilidade"
    assert pt["Refresh Interval"] == "Intervalo de atualização"
    assert de["Lock Contention"] == "Lock-Contention"
    assert ja["Snapshot Explorer"] == "スナップショット表示"

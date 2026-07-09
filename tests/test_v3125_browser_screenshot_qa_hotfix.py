from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_namespace_labels_have_24_char_budget_and_shifted_bars():
    js = (ROOT / "src" / "staqtapp_tds" / "admin" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "src" / "staqtapp_tds" / "admin" / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert "truncateText(fullName, 24)" in js
    assert "label.title=fullName" in js
    assert "grid-template-columns:minmax(154px,170px) minmax(70px,1fr) minmax(38px,max-content)" in css
    assert ".namespace-row span{max-width:24ch}" in css


def test_browser_comparative_storage_entries_use_compact_count():
    js = (ROOT / "src" / "staqtapp_tds" / "admin" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "src" / "staqtapp_tds" / "admin" / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert "const compactCount = (value, fallback = 0)" in js
    assert "setCompactText('compare-storage-entries', storage.entries,0)" in js
    assert ".comparison-tile b{white-space:nowrap" in css


def test_browser_language_select_cannot_render_blank_current_language():
    js = (ROOT / "src" / "staqtapp_tds" / "admin" / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "function languageChoices()" in js
    assert "function defaultLanguageCode()" in js
    assert "if (!select.value && select.options.length) select.selectedIndex = 0" in js
    assert "select.dataset.currentLanguage = select.value || defaultLanguageCode()" in js

# v2.8.0 Browser Language Packs

Staqtapp-TDS v2.8.0 completes the first full Browser Operations Console localization pass.

## Scope

The localization layer covers browser presentation text only:

- left navigation
- telemetry page headings and labels
- Snapshot Explorer
- Lock Contention
- Comparative Views
- Alerts & Events
- Recovery Planner labels and guardrails
- Security and recommendation panel labels
- Settings page
- About dialog

Native storage behavior, internal metric keys, `/status.json` payload names, and telemetry counter names remain language-neutral and unchanged.

## Official browser languages

- English (`en`)
- Spanish (`es`)
- Portuguese (`pt`)
- Japanese (`ja`)
- German (`de`)
- French (`fr`)
- Italian (`it`)

## File layout

```text
src/staqtapp_tds/admin/static/i18n/
    manifest.json
    en.json
    es.json
    pt.json
    ja.json
    de.json
    fr.json
    it.json
```

The manifest registers available languages. Each pack contains the same complete key set so missing strings are caught during tests.

## Design rules

- English is a language pack, not hardcoded application text.
- Native telemetry keys are never translated.
- The browser translates presentation text only.
- Cards keep fixed layout widths; translated text wraps inside panels.
- Portuguese and German are treated as layout stress languages.
- Japanese receives normal browser line-breaking through the document language tag.
- The custom SVG icon set remains unchanged across languages.

## Runtime behavior

The language manager loads `manifest.json`, then the selected pack and English fallback pack. The selected language is stored in browser `localStorage` with the other browser-only Settings preferences. Changing language updates the browser presentation without altering TDS storage, telemetry, or native engine behavior.

# v2.7.8 Browser Settings and Localization Foundation

TDS v2.7.8 adds the first dedicated TDS Browser Settings page. This release intentionally focuses on browser configuration only and does not change native storage-engine behavior.

## General Settings

The Settings page contains:

- Language selection
- Startup page selection
- Refresh interval selection
- About TDS Browser dialog

Settings are stored locally by the browser and do not mutate RuntimeConfig, storage files, indexes, or diagnostic hot paths.

## Official Browser Languages

The initial language set is:

- English
- Spanish
- Portuguese
- Japanese
- German
- French
- Italian

The native engine remains language-neutral. Metric identifiers and telemetry keys remain stable and untranslated.

## Layout-Safe Localization

Dashboard cards keep their layout width. Translated labels are allowed to wrap vertically inside each card. The browser CSS uses `min-width: 0`, `overflow-wrap`, normal wrapping, and language-specific Japanese line-breaking support to prevent long labels from overhanging horizontally into neighboring panels.

The rule is:

```text
text may wrap
cards may grow vertically
cards do not grow horizontally because of translated text
```

## About Dialog

About information is shown in a dialog rather than expanded directly on the Settings page so version/build details can grow later without crowding the General settings surface.

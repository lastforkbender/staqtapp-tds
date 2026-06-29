# Staqtapp-TDS v2.3.5 Professional Dashboard

The v2.3.5 admin panel is a packaged, asset-driven observability interface under `src/staqtapp_tds/admin/`. It keeps the browser outside the hot TDS path by polling `/status.json` every two seconds and rendering cached telemetry snapshots only.

## Included pages/regions

- Overview
- Live Architecture
- Performance
- Storage
- Indexes
- Behavior
- Security
- Recommendations
- Configuration
- Timeline

## Non-interference rule

The dashboard must never walk the Swiss table, radix router, manifest, or persistence structures directly. It reads snapshots produced by the control/observation layer. Deep diagnostics and benchmarks remain manual operations.

## Assets

The dashboard uses separate template, CSS, JavaScript, and SVG icon assets:

```text
src/staqtapp_tds/admin/templates/dashboard.html
src/staqtapp_tds/admin/static/css/dashboard.css
src/staqtapp_tds/admin/static/js/dashboard.js
src/staqtapp_tds/admin/static/icons/*.svg
```

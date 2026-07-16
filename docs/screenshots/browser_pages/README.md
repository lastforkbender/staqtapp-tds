# TDS Browser 19-page release capture

This directory contains one genuine 1280×800 viewport capture for every navigation page in the packaged TDS Browser. The files are ordered exactly as the Browser navigation is ordered. They are not crops from one Dashboard screenshot.

The capture source is `scripts/serve_browser_release_snapshot.py`. It creates a real in-memory TDS workload, commits the CSV storage/replay/native/timeline/ring/readiness/scan/anchor/performance evidence chain, verifies that the CSV Interpole Browser snapshot is `monitor_ready`, records real Spiral Rank runs, and serves those observer snapshots through the real localhost-only `AdminPanelServer`.

The capture driver is `scripts/capture_browser_pages.cjs`. It refuses to proceed unless all 19 navigation controls exist and CSV Interpole displays `Monitor Ready`. For every output file it clicks the matching navigation control and verifies that the control is active, the URL hash is correct, and the target page is visible.

To reproduce, first make Python package imports and Playwright with Chromium available. Then run the server and capture driver in separate terminals:

```bash
PYTHONPATH=src python scripts/serve_browser_release_snapshot.py --port 8765
```

```bash
node scripts/capture_browser_pages.cjs \
  http://127.0.0.1:8765 \
  docs/screenshots/browser_pages
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE` may point to an explicit Chromium executable when Playwright does not manage the browser binary itself.

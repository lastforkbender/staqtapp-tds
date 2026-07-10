# v3.1.25 Browser Screenshot QA Hotfix

This hotfix closes three screenshot-review findings in the TDS Browser dashboard without changing Driver Studio authority, storage mutation behavior, or the storage hot path.

## Fixes

1. **Top Namespaces panel readability**
   - Namespace labels now use an explicit 24-character display budget.
   - Full namespace names remain available through the browser title tooltip.
   - The bar graph column is shifted right by widening the left label column.

2. **Comparative Views storage value containment**
   - The Storage tile now uses compact count formatting for large entry totals, such as `1.24M` rather than a vertically wrapped full integer.
   - The full raw value is preserved in the element tooltip.
   - Comparative tile numerals are forced to remain on one line.

3. **Browser Settings language fallback**
   - The language selector now has a fail-closed fallback path.
   - Invalid, missing, or empty language manifests fall back to English or the first available manifest language.
   - The current selected language is never allowed to render as a blank select value.

## Regression coverage

Added focused Browser QA regression checks in:

```text
 tests/test_v3125_browser_screenshot_qa_hotfix.py
```


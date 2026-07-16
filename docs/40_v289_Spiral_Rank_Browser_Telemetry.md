# v2.8.9 Spiral Rank Browser Telemetry

v2.8.9 connects the Native Spiral Rank Engine statistics layer to the browser Operations Console through the admin telemetry path.

## Boundary

The implementation is observer-only:

- Spiral Rank produces immutable `SpiralRankRun` and `SpiralRankStats` objects.
- `staqtapp_tds.admin.spiral_rank.SpiralRankTelemetry` caches completed runs.
- `AdminControl.status()` exports a JSON-safe `spiral_rank` snapshot.
- The dashboard renders the snapshot on the dedicated **Spiral Rank** analytics page.
- No storage lock, payload read, policy mutation, ranking control loop, or hot-path write is performed by admin telemetry.

## Browser fields

The dashboard displays:

- total rank runs
- native versus Python fallback percentage
- last elapsed time and rolling average
- input, ranked, limited, and dropped-by-limit counts
- min, max, and mean score
- scoring, sorting, and shaping timings
- config ID
- latest Top-N ranked traces
- last 24 run timing trend

## Source layout

```text
src/staqtapp_tds/admin/spiral_rank.py
src/staqtapp_tds/admin/control.py
src/staqtapp_tds/admin/templates/dashboard.html
src/staqtapp_tds/admin/static/js/dashboard.js
src/staqtapp_tds/admin/static/css/dashboard.css
src/staqtapp_tds/admin/static/icons/spiral-rank.svg
```

## Intended use

A caller that owns Spiral-compatible trace metadata can publish each completed ranking run to the admin telemetry cache:

```python
from staqtapp_tds.admin.spiral_rank import SpiralRankTelemetry
from staqtapp_tds.spiral.rank import NativeSpiralRankEngine

engine = NativeSpiralRankEngine()
telemetry = SpiralRankTelemetry()

run = engine.rank_run(["trace-a", "trace-b"], [0.95, 0.82], limit=8)
telemetry.observe_run(run)

snapshot = telemetry.snapshot()
```

The browser can then render the snapshot through `status.json` without contacting the ranking engine directly.

## Browser layout safeguards

The Analytics → Spiral Rank view is constrained for operational readability:

- long trace IDs and configuration labels wrap instead of overflowing panels;
- metric rows use bounded responsive columns so bars and values do not collide;
- Top-N trace feedback is scroll-bounded;
- timing history bars are clipped inside the history card;
- below narrow breakpoints, the Spiral Rank analytics grid collapses to a single column.

These safeguards keep telemetry visual-only and observer-safe while avoiding text overhang, object overlap, and accidental horizontal page growth.

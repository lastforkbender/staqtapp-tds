# v2.9.0 JSON Performance Codec

v2.9.0 upgrades the centralized `staqtapp_tds.tds_json` boundary from a simple helper into a performance-grade codec layer.

## Design

- JSON calls remain centralized in `tds_json.py`.
- Optional backends are imported once at module import time.
- `simdjson` is preferred for parsing when installed.
- `orjson` is preferred for compact and pretty emission when installed.
- stdlib `json` remains the safe fallback.
- Browser `status.json` now uses compact `dumps_status(...)` instead of pretty JSON.
- Codec-level stats expose loads/dumps calls, backend counts, elapsed nanoseconds, and failovers.

## Hot-path rule

Storage, telemetry, admin, persistence, and browser code should call the centralized API only:

```python
from staqtapp_tds.tds_json import loads_fast, dumps_canonical, dumps_status
```

Do not scatter direct `json.loads` or `json.dumps` calls into engine or admin code unless a test is intentionally parsing a fixture.

## Safety

The accelerator dependencies are optional. TDS remains fully functional with stdlib-only Python installations.

# v3.0.4 Admin Origin Fail-Closed Patch

TDS v3.0.4 hardens the local admin control panel origin boundary.

Previously, `_same_origin_request()` rejected mismatched `Origin` or `Referer` headers, but accepted requests that omitted both headers. The CSRF token check still protected privileged routes, but the origin gate was fail-open for missing-header requests.

v3.0.4 changes the admin POST policy for `/stage`, `/promote`, and `/rollback`:

- A same-origin `Origin` or `Referer` header must be present.
- Mismatched `Origin` or `Referer` headers are rejected.
- Missing both headers is rejected, even when the CSRF token is valid.
- The explicit CSRF token check remains required.

This keeps the admin panel defense-in-depth posture aligned with Class A safety expectations.

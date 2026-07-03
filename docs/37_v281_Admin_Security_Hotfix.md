# v2.8.1 Admin Browser Security Hotfix

Staqtapp-TDS v2.8.1 hardens the browser/admin control plane before the Native Spiral Rank Engine work.

## Fixed

- State-changing admin POST routes now require a server-generated CSRF token.
- POST routes reject mismatched `Origin`/`Referer` values before mutating runtime config.
- Dashboard renderers no longer inject dynamic telemetry strings through `innerHTML`.
- Dynamic browser rows are built with DOM nodes and `textContent`.
- Malformed `Content-Length` headers receive a clean `400` response.
- Browser settings sanitize refresh intervals and language codes.
- Language-pack fallback status is exposed on the document element for diagnostics.

## Not changed

- Native storage engine behavior.
- Storage hot-path dynamics.
- RuntimeConfig semantics, except that browser/admin HTTP mutation now requires CSRF validation.

## Deferred

Serialization and cryptography hardening should be handled separately because those touch storage compatibility and data-format expectations.

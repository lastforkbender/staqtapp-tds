# TDS API Docs

This folder intentionally contains one canonical Staqtapp-TDS API surface reference PDF for repository consumers, AI integration planning, stress testing, and authority-boundary review.

Current PDF:

```text
Staqtapp_TDS_API_Surface_Reference.pdf
```

The PDF filename and first cover page omit a release version so README-only or storage-hardening version bumps do not create duplicate API PDFs. Regenerate this document only when the public API surface itself changes.

The v3.1.26 storage-engine hardening release does not regenerate the API surface content because it promotes the hardened storage baseline through version metadata and README documentation only.

The PDF separates AI-safe public proposal/testing calls, Runtime Manager evidence calls, controlled Driver VM runtime calls, Browser/Admin telemetry calls, Driver Studio cockpit calls, storage/.tds calls, and stress-harness calls.

# 46 — v3.0.4 Class A Pickle Boundary

Pickle remains a Python compatibility lane only. It is not treated as a general interchange format or a trust boundary.

## Architecture

All pickle behavior is centralized in `staqtapp_tds.tds_pickle`:

- `dumps_pickle(value)` writes a TDS pickle envelope and validates that the restricted reader can read the payload.
- `loads_pickle(raw)` reads TDS-enveloped payloads and safe legacy unenveloped payloads.
- `PicklePolicy` records mode, envelope requirements, maximum payload size, and write-time validation.
- `pickle_policy_snapshot()` exposes non-secret policy metadata for failure diagnostics.

The storage engine no longer calls `pickle.loads()` directly. `_deserialize_payload(...)` delegates to the policy boundary and returns `TDSResult.fail(PAYLOAD_DESERIALIZE_ERROR, ...)` on failure.

## Default posture

Default mode is `restricted`. The restricted unpickler allows ordinary value containers and a small set of stable standard-library value classes. Arbitrary globals, custom classes, and code-capable reductions are rejected.

For controlled migrations only, setting `TDS_ALLOW_UNSAFE_PICKLE=1` switches the policy to `unsafe_legacy`, which uses normal Python pickle loading. This should not be enabled for untrusted files, shared directories, or network-exposed workflows.

## Format compatibility

New `PICKLE_OBJ` writes start with the envelope magic `TDSPKL\x01`. Legacy safe pickle payloads without the envelope continue to read in restricted mode unless `PicklePolicy(require_envelope=True)` is selected by a future registry/driver layer.

## Driver/registry preparation

This release deliberately separates pickle compatibility from the future driver language/registry/builder system. The future registry can choose serializer lanes without inheriting scattered pickle calls or unsafe decode behavior.

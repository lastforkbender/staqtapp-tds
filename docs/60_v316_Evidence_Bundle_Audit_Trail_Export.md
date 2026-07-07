# v3.1.6 Evidence Bundle + Audit Trail Export

v3.1.6 adds the read-only export layer that should exist before a full PyQt5
Driver Studio begins rendering driver trust internals. The layer consumes
`DriverBatchReviewReport` objects from v3.1.5 and optional
`DriverRegressionReport` objects from v3.1.4, then freezes the review chain into
a deterministic `DriverEvidenceBundle`.

The export layer explains trust. It does not create trust.

```text
Regression Harness produces fixture evidence
Admin Batch Review records decisions
EvidenceBundleExporter freezes the chain for read-only display/export
Driver Studio renders the bundle
Registry still owns approval, signing and activation authority
```

## Public API

The new public types are exported from `staqtapp_tds.drivers`:

- `EvidenceBundleExporter`
- `DriverEvidenceBundle`
- `EvidenceBundleManifest`
- `DriverEvidenceRecord`
- `DriverAuditTrail`
- `DriverAuditEvent`
- `DriverAuditEventType`
- `EvidenceExportFormat`
- `EvidenceIntegrityStatus`
- `EvidenceBundleStatus`
- `AuditTrailStatus`
- `evidence_export_capability_matrix()`

## Authority Boundary

`EvidenceBundleExporter.capability_matrix()` is intended for future Driver
Studio display. It can consume review/regression reports, create evidence
bundles, create audit trails, export deterministic JSON, verify export integrity,
and record public signature metadata.

It cannot:

- approve drivers
- call registry approval
- sign drivers
- attach signatures
- activate drivers
- run the Driver VM
- write storage
- execute Python
- mutate registry state
- bypass policy
- include private keys

This keeps the Studio path rich in feedback while preserving the existing trust
boundaries.

## Evidence Bundle Contents

A `DriverEvidenceBundle` contains:

- top-level bundle id and deterministic `bundle_hash`
- `EvidenceBundleManifest`
- `DriverAuditTrail`
- one `DriverEvidenceRecord` per review decision
- capability matrix for GUI authority display
- integrity status

Each evidence record includes:

- driver id and version
- package hash
- regression report hash
- review hash
- requested/final admin action
- decision status
- reviewer id and rationale
- risk level
- registry state before/after when observed
- evidence summary
- optional fixture replay summaries
- review faults and tags

When the exporter receives the original regression reports, the bundle also
carries fixture-level read-only details:

- case id
- pass/fail status
- fixture hash
- runtime evidence hash
- mismatches
- Runtime Manager status
- runtime recommendation
- trace completeness
- runtime fault codes
- runtime metrics

This is the material that a future Driver Studio can show in panels such as
Fixture Replay, Evidence Bundle Viewer, Risk Card, Review Timeline and Audit
Trail.

## Audit Trail

The audit trail is a chain-of-custody view. It records events such as:

- `regression_attached`
- `admin_reviewed`
- `registry_state_observed`
- `export_created`
- `export_verified`

Each `DriverAuditEvent` may include:

- event id
- event type
- driver id and version
- actor id and role
- action
- reason
- timestamp supplied by the caller
- previous/resulting status
- regression report hash
- runtime evidence hash
- review hash
- batch hash
- policy hash
- public key fingerprint
- signature status
- safe metadata

Private keys, tokens and secrets are not included. Public signature metadata is
for display and verification context only; signing authority remains outside the
export layer.

## Deterministic Integrity

`DriverEvidenceBundle.to_json()` returns a canonical JSON string. The exporter
can verify bundles through:

```python
from staqtapp_tds.drivers import EvidenceBundleExporter, EvidenceIntegrityStatus

status = EvidenceBundleExporter().verify_bundle(bundle)
assert status is EvidenceIntegrityStatus.VERIFIED
```

Bundle hashes are computed over canonical JSON-compatible payloads with the
bundle hash field blanked and integrity status set to incomplete during hashing.
Tampering with exported fields changes the recomputed hash and returns
`EvidenceIntegrityStatus.MISMATCHED`.

## Studio Readiness

v3.1.6 gives the future PyQt5 Driver Studio a clean read-only internal feed. The
Studio can display:

- Evidence Bundle Viewer
- Audit Trail Panel
- Fixture Replay Summary
- Risk Card Inspector
- Registry State Observer
- Review Timeline
- JSON Export/Verify panels

The Studio should still submit review intents through the batch review layer and
observe registry state. It should not carry private keys, own signer authority,
or directly activate drivers.

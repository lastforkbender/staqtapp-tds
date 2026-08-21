# Staqtapp-TDS Versioning

The current production identity is `3.8.3`. The authoritative source is
`src/staqtapp_tds/version.py`. This patch is the PCSDQR repository and
release-process correction; it changes no stored format or public API and
widens no authority boundary.

## Format

Published releases use three numeric components:

```text
MAJOR.MINOR.PATCH
```

- `MAJOR` changes for an intentionally incompatible public contract.
- `MINOR` changes for a compatible architecture or capability release.
- `PATCH` changes for compatible corrections, hardening, or performance work.

Historical `.postN` releases remain immutable history. New corrections use a
new patch version rather than another post-release suffix.

## Tags and artifacts

A production tag is exactly `vMAJOR.MINOR.PATCH` and must resolve to the source
commit used to build the published artifacts. The package version, README
heading, installation pin, artifact metadata, and tag must agree.

Once published, a tag, wheel, and source distribution are not replaced. A
follow-up correction increments `PATCH` and produces a new release.

## Candidate state

Candidate state belongs to branches and pull requests, not to a production
version string. Documentation must distinguish the currently installable
release from unreleased source without inventing a second package identity.

## Compatibility statements

Release notes should state compatibility in terms users can verify:

- public API additions or removals;
- stored-format changes;
- minimum Python or dependency changes;
- migration or rollback requirements; and
- security or authority-boundary changes.

Test counts, workflow run IDs, and temporary qualification status belong in CI
logs, not in the version policy.

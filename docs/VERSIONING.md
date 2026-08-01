# Staqtapp-TDS release version policy

## Decision

`v3.5.3.post2` remains an immutable historical release identity. It is not
renamed or rewritten.

Beginning with the Frontier Foundation Repair train, every published
Staqtapp-TDS release uses exactly three numeric components:

```text
MAJOR.MINOR.PATCH
```

The completed Foundation source identity is **v3.6.0**. Corrective releases increment the patch number:

```text
v3.6.0 -> v3.6.1 -> v3.6.2
```

Staqtapp-TDS will not publish another `.postN` release.

The current source-candidate architecture line is **v3.8.0**, the packed
Waypoint Graph Foundation and qualification-only Eaglegate convergence. The
current production PyPI identity remains `v3.5.3.post2` until a separate
release-controller run completes.

## Operational rules

1. A production tag is exactly `vMAJOR.MINOR.PATCH`.
2. The package version is exactly `MAJOR.MINOR.PATCH`.
3. A correction after publication receives a new patch version; the prior tag
   and artifacts remain immutable.
4. Candidate state belongs to branches, pull requests, qualification evidence,
   and release-controller state—not to a `.postN` package suffix.
5. Release workflows must derive artifact and tag checks from the package's
   single authoritative version source before v3.6.0 publication.
6. Historical `3.5.3.post1` and `3.5.3.post2` references may remain only where
   they describe those immutable releases.

## Upgrade sequence

The architecture labels in the Frontier Evidence Fabric proposal map to clean
release identities:

| Architecture label | Clean release identity |
|---|---|
| v3.6 Foundation Repair | `3.6.0` |
| corrective Foundation Repair | `3.6.1`, `3.6.2`, ... |
| v3.7 Dataset Generation Plane | `3.7.0` |
| v3.8 Waypoint Graph Foundation | `3.8.0` |
| v3.9 Sentinel Shadow | `3.9.0` |
| v3.10 Ranked Evidence Reads | `3.10.0` |
| v3.11 Adaptive Server | `3.11.0` |
| v4.0 Frontier Evidence Fabric | `4.0.0` |

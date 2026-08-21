# Automated Release Pipeline

Staqtapp-TDS release automation began in v3.0.1. The v3.8.2 production
pipeline builds and validates one source distribution and one universal Python
wheel, then publishes them only from the exact annotated version tag through
PyPI Trusted Publishing.

## Current release target

The release contains a clean source distribution and a universal wheel. Source
hygiene excludes compiled platform binaries such as `.so`, `.pyd`, `.dll`,
`.dylib`, `.pyc`, `__pycache__`, and `.pytest_cache`. Optional native modules
remain an explicit source-build choice; the published wheel retains the
deterministic Python paths.

## Future platform wheel target

If TDS later publishes compiled wheels, the same pipeline structure can build
artifacts for the main operating systems:

- Linux x86_64 / aarch64
- Windows AMD64 / ARM64
- macOS Apple Silicon / Intel

The Native Engine Manager remains required even when wheels are used, because it verifies ABI and capability safety at runtime.

## Release checks

`scripts/check_release.py` verifies:

- source, package, and exact-tag version consistency;
- current English and Japanese release status and installation pins;
- the 19 preserved Browser captures and PyPI-safe absolute targets;
- no compiled binaries or generated cache/build artifacts in source;
- required release evidence and versioned documentation; and
- deterministic Foundation Closure and result-code documentation.

`scripts/check_pypi_readme.py` independently binds the exact ordered screenshot
URLs to the 19 local 1280×800 PNGs. Before upload, it fetches each immutable URL
and requires byte-identical PNG content, then inspects the built wheel's
`METADATA` description to prove those URLs survived packaging.

The GitHub Actions workflow in `.github/workflows/release.yml` uses ordinary,
bounded release testing as publication authority:

- the full monolithic suite on Python 3.10 through 3.14;
- pure-Python validation on Linux, macOS, and Windows;
- native-extension builds and the native test suite;
- address, undefined-behavior, and thread sanitizers;
- native lifecycle and free-threaded admission checks;
- deterministic frozen-format fuzzing and exact x86-64/AArch64 semantic
  parity; and
- distribution building, `twine check`, installed-version verification, and
  PyPI README/asset verification.

There is no timing or performance benchmark publication gate. The performance
figures in the v3.8.2 release notes are bounded engineering measurements, not
release authority. Correctness regressions for the affected components remain
covered by the normal semantic suites above.

## Exact-source release controller

A successful `release.yml` push run on `main` triggers the one-time
`.github/workflows/v382-release-controller.yml`. The controller fails closed
unless the run is successful, its `Release gates complete` aggregate succeeded,
the run's head is still the exact tip of `main`, PyPI 3.8.2 is absent, and the
`v3.8.2` tag does not exist. It then creates an annotated tag that peels to that
exact qualified main commit and dispatches the tag workflow once.

The controller writes an exact, run-bound attestation containing the repository,
controller run and attempt, qualified run and commit SHA, dispatched release run,
tag, and annotated tag-object SHA. The tag workflow accepts no defaults and
revalidates that attestation, all three workflow identities, the successful
main aggregate, the unchanged main tip, the annotated tag object, and PyPI
absence before publication can proceed.

## Trusted publication and public verification

The `publish-pypi` job is protected by the `pypi` environment. After its approval
and immediately before requesting an OIDC credential,
`scripts/v382_release_provenance.py` repeats the complete controller, run, main,
tag, artifact, and PyPI-absence proof. Publication has no `skip-existing` or
credential-token fallback.

After upload, the workflow requires PyPI to expose exactly the expected wheel
and source archive with the validated filenames, package types, metadata,
sizes, and SHA-256 hashes. It downloads the public `files.pythonhosted.org`
objects and compares their bytes with the workflow artifacts.

The parent release run then dispatches `.github/workflows/pypi-smoke.yml` with
the exact version, qualified main SHA and run, parent release run, and annotated
tag-object SHA. That workflow installs the exact production wheel on Linux,
macOS, and Windows, performs a core round trip, and checks the live PyPI
description and every public presentation target. The GitHub Release is created
only after the parent-bound production smoke aggregate succeeds and all release
and tag identities are revalidated. Workflow permissions are job-scoped and all
third-party actions in the publication path are pinned to full commit SHAs.

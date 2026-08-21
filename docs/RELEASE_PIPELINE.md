# Release Pipeline

TDS uses one bounded release path. A release proves the source, package, and
installation being published; it does not re-run historical phase ceremonies or
require old status ledgers.

The v3.8.3 PCSDQR scope retains direct behavior, declared-dependency,
supported-platform, package-build, and installed-artifact checks. Documentation
wording, historical journals, aggregate pass counts, and repeated validation
wrappers are not release gates. The source distribution carries maintained
runtime, build, documentation, example, and public-asset inputs rather than
obsolete validation debris.

## Release authority

The authoritative package version is
`src/staqtapp_tds/version.py`. A production tag is the exact annotated
`vMAJOR.MINOR.PATCH` tag for that source version, and its commit must belong to
`main`. Publication must use artifacts built from the tagged commit.

## Required checks

Before a tag can publish, the release path should establish:

- source version, package metadata, and tag identity agree;
- the tagged commit belongs to `main`, whose ordinary CI owns the supported
  Python, operating-system, and optional native behavior checks;
- the source distribution and wheel build cleanly and pass metadata checks;
- an isolated install imports the expected version and completes a core
  persistence round trip;
- the package description retains the intended Browser image targets and all
  19 preserved local captures remain valid PNGs; and
- no compiled binaries, bytecode, caches, or local build output leaked into the
  source tree or source archive.

Each maintained check owns one concrete contract. Source/package/tag identity,
package-description rendering, behavior, package construction, and
installed-package smoke are checked directly instead of being wrapped in a
second documentation or aggregate-status decision.

## Sequence

1. Update the version and `CHANGELOG.md`.
2. Run the bounded source, test, native, and package checks.
3. Build one wheel and one source distribution from the qualified source.
4. Create the annotated version tag only for that exact commit.
5. Publish through PyPI Trusted Publishing after the direct checks pass.
6. Install the public artifact and run a small production smoke test.
7. Create the GitHub Release from the same tag and artifact identity.

Published tags and artifacts are immutable. A correction receives a new patch
version; it does not rewrite the prior release.

## Performance evidence

Benchmarks are engineering evidence, not publication authority. Performance
claims must name the workload, environment, baseline, repetitions, and output
equivalence rule. Reproducible commands and current measurements live in
`benchmarks/README.md`.

## Local preparation

Typical local preparation is intentionally short:

```bash
python scripts/release_version.py
python scripts/release_version.py --print-tag
python scripts/check_pypi_readme.py
python -m pytest -q
python -m build
python -m twine check dist/*
```

After installing the built artifact into an isolated environment, run
`python scripts/release_version.py --verify-installed` and a core persistence
smoke test. Optional native checks use a clean build with
`STAQTAPP_TDS_BUILD_NATIVE=1`; sanitizer and compatibility checks report their
own results directly.

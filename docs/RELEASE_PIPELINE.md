# Automated Release Pipeline

Staqtapp-TDS release automation began in v3.0.1. The current v3.8.1 pipeline
builds and validates a source distribution and a universal Python wheel, then
publishes only from the exact version tag through PyPI Trusted Publishing.

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

The GitHub Actions workflow in `.github/workflows/release.yml` gates the build
behind the complete Python, platform, native, sanitizer, fuzz, performance, and
architecture matrix. `twine check`, wheel installation, metadata inspection,
and screenshot verification must succeed before the tag-only Trusted Publisher
job can upload. The separate production PyPI smoke workflow installs the exact
published wheel on Linux, macOS, and Windows and verifies the live description
and public presentation targets.

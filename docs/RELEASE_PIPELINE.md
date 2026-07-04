# Automated Release Pipeline

Staqtapp-TDS v3.0.1 introduces release automation scaffolding for professional source and future binary releases.

## Current release target

The current archive is a clean source distribution. It intentionally excludes compiled platform binaries such as `.so`, `.pyd`, `.dll`, `.dylib`, `.pyc`, `__pycache__`, and `.pytest_cache`.

## Future binary release target

When TDS is ready for platform binary distribution, the same pipeline structure can build wheels for main operating systems:

- Linux x86_64 / aarch64
- Windows AMD64 / ARM64
- macOS Apple Silicon / Intel

The Native Engine Manager remains required even when wheels are used, because it verifies ABI and capability safety at runtime.

## Release checks

`scripts/check_release.py` verifies:

- package version consistency
- no stale version references in key metadata
- no compiled binaries in source releases
- no `__pycache__` / `.pytest_cache`
- result-code documentation can be regenerated from the registry

The GitHub Actions workflow is stored in `.github/workflows/release.yml` and is intentionally ready for wheel-building expansion when binary releases begin.

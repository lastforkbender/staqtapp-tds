# Changelog

## v1.7.1

Documentation and stabilization release.

### Added

- Full engineering documentation under `docs/`.
- Rewritten root `README.md`.
- Reserved namespace support via `ReservedNamespaces`.
- Manifest `reserved_namespaces` block.
- `TDSDirectory.is_reserved_namespace()`.
- `TDSDirectory.reserved_namespace_names()`.
- `mkdir(..., allow_reserved=True)` escape hatch for explicit creation.
- Reserved namespace unit test.

### Changed

- Version bumped to `1.7.1`.
- Metadata sidecar now includes reserved namespace policy snapshot.

### Not changed

- No C/C++ backend yet.
- No new telemetry algorithm.
- No expanded manifest hot-path work.
- No change to SRZ cognitive boundary.

## v1.7.0

Semantic infrastructure release.

- Inherited read-once manifest policy.
- Optional Semantic Routing Zones.
- Directory telemetry modes.
- Latency buckets.
- Capability registry.
- Persistence of SRZ and telemetry snapshots.

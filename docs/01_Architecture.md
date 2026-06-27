# 01 — Architecture

Staqtapp-TDS is organized around a simple boundary: the VFS manages storage facts, not reasoning.

```text
Client / AI interface
        │
        ▼
TDSFileSystem
        │
        ├── TDSDirectory
        │       ├── EntryIndex
        │       ├── HybridRegistry
        │       ├── SRZMetadata
        │       ├── DirectoryTelemetry
        │       └── CapabilityRegistry
        │
        ├── ManifestPolicy
        └── TDSPersistence
```

The core path is intentionally Python-facing. Native acceleration is planned as an optional backend, not as a replacement for the public API.

## Cold path vs hot path

Cold path:

- parse manifest,
- validate policies,
- build compiled objects,
- write snapshots,
- load sidecar metadata.

Hot path:

- resolve directory,
- lookup entry,
- read cached registry entry,
- update lightweight telemetry if enabled.

The manifest is never meant to be parsed on every access.

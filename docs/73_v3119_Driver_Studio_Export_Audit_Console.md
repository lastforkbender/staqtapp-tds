# v3.1.19 Driver Studio Export / Audit Console

v3.1.19 adds a selected-driver Export / Audit Console to the optional Driver Studio PyQt5 subsystem.

The console prepares reviewable, hash-backed export packet previews. It joins already-visible Studio evidence surfaces instead of creating trust authority.

## Adds

- `staqtapp_tds.studio_pyqt5.export_audit`
- `StudioExportAuditConsole`
- `StudioExportAuditConsoleState`
- `StudioExportAuditPacketPreview`
- `StudioExportAuditManifest`
- `StudioExportAuditChecklist`
- `StudioExportAuditReadinessCard`
- `StudioExportAuditIntegrityItem`
- `studio_export_audit_capability_matrix()`

## Evidence joins

The console maps:

- selected driver identity
- evidence bundle hash
- compiled bytecode/package hash
- fixture regression report hash
- review hash and review history
- Evidence Timeline lifecycle rows
- Risk Intelligence factors
- Registry observation rows
- optional Driver VM performance evidence hash
- deterministic manifest hash
- deterministic packet preview hash

## Authority boundary

The Export / Audit Console is `prepare_only`. It does not approve, reject, quarantine, sign, activate, mutate Registry state, execute trusted drivers, write storage, store private keys, or bypass Runtime Manager / Foundry / Review Board / Registry policy.

## Design role

The console turns trust history into export-ready administrative context. Registry remains the trust authority; Studio makes the trust path visible, chronological, explainable, auditable, and ready for external export tooling.

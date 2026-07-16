# v3.5.3-dev10 — Controlled Activation

Phase 10 converts the earlier Guaranteed Storage primitives into an explicit,
auditable operating-mode transition. It does not alter the established
`TDSPersistence` constructor or silently replace the legacy persistence path.

## Operating modes

`StorageMode` defines two modes:

- `legacy` — the unchanged `TDSPersistence` path and the default when no durable
  mode record exists;
- `guaranteed-segmented` — the Phase 9 immutable segment-generation path.

The selected mode is stored in canonical `STORAGE_MODE.json`. A missing record
means legacy mode. A malformed, non-canonical, incomplete, or unknown record is
an integrity failure; it never causes a silent fallback.

## Qualification before activation

`ControlledStorage.qualify_activation()` commits the exact existing legacy mount
through immutable segments and reconstructs it privately. It proves:

1. identical path inventory;
2. identical byte lengths;
3. identical SHA-256 digests;
4. structured metadata equivalence;
5. logical reopen equivalence for every `.tds` file;
6. an unchanged legacy source throughout qualification.

The method writes a canonical qualification receipt only after every gate
passes. Qualification deliberately leaves the operating mode at `legacy`.

## Explicit atomic activation

`ControlledStorage.activate(...)` requires the literal acknowledgement
`activate-guaranteed-segmented`. Before publishing the mode record, it reloads
the persisted qualification, verifies the named segment generation, proves the
source inventory has not changed, reconstructs the candidate again, and repeats
all equivalence gates while segment mutation exclusion is held.

The atomic mode-record replacement is the authority boundary. A failure before
replacement leaves legacy mode authoritative.

## Mode-aware commit and observer visibility

`ControlledStorage.commit_filesystem(...)` follows the selected mode but never
changes it. Browser/admin status exposes the explicit mode, revision,
qualification identity, current segment-generation identity, rollback
availability, and whether a full integrity verification was performed.

Browser polling reads only the small canonical mode record, qualification
receipt, and `SEGMENT_CURRENT` pointer. It does not traverse or hash segment
payloads and therefore remains outside the storage hot path.

## Lossless rollback

`rollback_to_legacy(...)` requires the literal acknowledgement
`rollback-to-legacy`. It verifies and materialises the current segment generation
into a newly named legacy mount, logically reopens every `.tds` file, and only
then atomically selects that mount as the legacy authority.

Rollback does not overwrite the original legacy source and does not remove any
immutable generation. Changes committed after activation are therefore retained
in the rollback mount.

## Qualification evidence

- `tests/test_v353_controlled_activation.py`: 10 passed.
- Complete `tests/test_v353_*.py` qualification after the Phase 11 GC hardening
  additions: 133 passed.

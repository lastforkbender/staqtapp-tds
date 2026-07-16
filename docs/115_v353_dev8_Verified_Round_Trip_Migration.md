# v3.5.3-dev8 — Verified Round-Trip Migration

Phase 8 adds a qualification boundary between legacy persistence and any future
Guaranteed Storage activation.

`GuaranteedStorageBridge.verify_round_trip()` reads an existing legacy mount
without modifying it, captures an exact private snapshot, commits that snapshot
as an immutable generation, reconstructs it into a private materialisation
directory, and publishes the requested destination only after all equivalence
gates pass.

## Required equivalence gates

1. Exact relative-path inventory.
2. Identical file lengths.
3. Identical SHA-256 for every file.
4. Parsed metadata equivalence for the mount manifest and `.tds.meta` files.
5. Logical reopen equivalence for every `.tds` file, including successful
   deserialisation and matching slot names, format identifiers, and raw payload
   digests.
6. An unchanged legacy source across pre-copy, post-copy, and pre-publication
   snapshots.

## Failure semantics

- The requested destination remains absent.
- Private materialisation is removed.
- If a generation was committed before a later equivalence failure, `CURRENT`
  is restored to the generation that was authoritative before migration.
- The failed candidate may remain as an unreferenced immutable generation for
  later retention cleanup; it is never accepted by the migration report.

## Structured evidence

`VerifiedMigrationReport` records all global gates, publication state,
activation eligibility, byte and file totals, generation identity, and one
`MigrationFileRecord` per source path.

Guaranteed Storage activation remains a later Phase 10 concern. Phase 8 only
establishes whether a specific legacy-to-generation-to-mount transition is
eligible for activation.

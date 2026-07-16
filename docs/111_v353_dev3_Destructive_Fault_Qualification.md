# TDS v3.5.3-dev3 — Destructive Fault Qualification

This milestone qualifies the immutable-generation prototype with real subprocess termination and bounded integrity-metadata validation.

## Commit-boundary crash matrix

A child Python process is terminated with `os._exit(77)` at each named checkpoint. After every termination, a clean process reopens the store and verifies the authoritative generation.

Before atomic pointer promotion, the previous committed generation must remain authoritative. After pointer promotion, the newly promoted generation must be complete and self-verifying.

Covered checkpoints include data and metadata fsync boundaries, generation-directory synchronization, pointer-file synchronization, atomic `CURRENT` replacement, and parent-directory synchronization.

## Deep metadata hardening

Generation metadata is bounded before encoding and after decoding:

- maximum encoded metadata size: 1 MiB;
- maximum nesting depth: 32;
- maximum aggregate node count: 10,000;
- string-only mapping keys;
- JSON-compatible scalar/container values only.

Traversal is iterative so rejection does not itself depend on Python recursion depth. Oversized metadata is rejected before parsing. Deeply nested or malformed persisted metadata fails closed as a generation-integrity error.

## Performance-preserving changes

- Data is streamed to the generation file in 1 MiB memoryview slices rather than copied into one additional full-size `bytes` object.
- SHA-256 remains incremental during the same write pass.
- Verification remains bounded to 1 MiB reads.
- No generation management enters the existing v2 read hot path.

## Qualification status

The focused persistence, policy, crash-injection, and deep-metadata suite passes 34 tests. Full-suite execution in this hosted command wrapper did not return a trustworthy final exit record, although no explicit test failure was reported; therefore this milestone does not claim a new full-suite count. Normal CI must remain the authoritative full-suite gate.

# v3.5.3-dev6 Guaranteed Storage Transition Fit

## Decision

The stable multi-file TDS serializer remains the semantic authority during the
transition. Guaranteed storage wraps one complete legacy-compatible mount image
inside an immutable generation; it does not partially retrofit atomicity into
individual legacy files.

## Transition invariant

A mount image is either absent from `CURRENT` or complete, verified, and
recoverable. No set of partially updated `.tds` and `.tds.meta` files can become
the authoritative generation.

## Commit path

1. Flush the filesystem into a private staging mount.
2. Enumerate only regular non-symlink files in deterministic path order.
3. Stream a versioned image directly into the new generation.
4. Hash the complete generation while writing and each contained file while
   archiving.
5. Verify the generation.
6. Atomically promote `CURRENT`.
7. Remove temporary staging only after the commit call completes.

## Materialisation path

1. Verify the outer generation.
2. Require the exact image magic and bounded record structure.
3. Reject absolute paths, traversal, alternate separators, invalid UTF-8,
   duplicate-file creation, truncation, trailing bytes, and digest mismatch.
4. Write into a private sibling directory and fsync every file.
5. fsync the completed directory.
6. Atomically rename it into a previously absent destination.

## Performance analysis

This correctness bridge writes data twice: once through the proven legacy
serializer and once into the generation image. It remains bounded-memory and
keeps the established serializer unchanged. This cost is accepted only for the
transition proof. A later immutable-segment phase may remove duplicated writes
by reusing unchanged physical segments without altering the recovery contract.

## Non-goals

- No default-path switch.
- No in-place conversion of existing mounts.
- No automatic deletion of a legacy mount.
- No segment sharing or garbage collection in this phase.
- No claim that internal generations replace external backup.

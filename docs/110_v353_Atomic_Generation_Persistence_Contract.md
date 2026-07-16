# TDS v3.5.3-dev1 - Atomic Generation Persistence Contract

## Status

This milestone freezes the public data-survival contract. It does **not** yet
change the v2 on-disk persistence format and therefore does not close release
blocker R5 by itself.

## Non-negotiable invariant

A persistent TDS commit is always constructed as a new generation. Atomic
generation construction cannot be disabled. A failed commit may lose the new
write, but it must never destroy the previous committed generation.

## Public policy

`PersistencePolicy` separates three independent decisions:

- durability: when a commit may be acknowledged;
- retention: how many completed generations remain after cleanup;
- cleanup timing: when unpinned obsolete generations may be reclaimed.

The production-safe default is durable acknowledgement, two retained
generations, background cleanup, and protection of the last known-good state.

`retained_generations=1` is valid and still uses atomic promotion. It reduces
disk use but removes historical rollback depth after cleanup. Zero retention is
invalid.

## Durability meanings

- `durable`: acknowledgement follows the required data, metadata, pointer, and
  directory durability barriers. Expected acknowledged-loss window: zero under
  the documented storage assumptions.
- `group_durable`: commits may share a durability barrier. The configured window
  is exposed as the maximum intended acknowledgement risk window.
- `relaxed`: atomic visibility remains required, but recently acknowledged
  writes may be lost after abrupt process, operating-system, or power failure.

## Backup boundary

Internal generations are local recovery states. They do not protect against
loss of the device, destruction of the host, filesystem-wide corruption,
theft, ransomware with filesystem access, or deletion of the whole mount.
Off-device backup status is reported separately.

## Recovery observability

Fallback is never silent. `PersistenceStatus` must report the requested
generation, mounted generation, reason, and active fallback flag. An incomplete
fallback status is invalid.

## Performance constraints frozen now

- generation policy is resolved at open/mount time, not on each read;
- the active manifest will be cached in memory;
- `CURRENT` will remain a minimal pointer file;
- checksums will be calculated while bytes are written, avoiding a second pass;
- cleanup will normally remain outside the foreground commit path;
- future segment reuse may optimize physical writes without changing these
  logical guarantees.

## Next milestone

v3.5.3-dev2 implements the simplest complete immutable-generation writer and
startup reader using full generations. Optimization through shared immutable
segments is intentionally deferred until fault-injected correctness is proven.

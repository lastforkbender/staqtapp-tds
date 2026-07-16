# TDS Architecture Reference

## Immutable generation commit protocol

A new full generation is written, durably flushed, independently verified, and
only then made authoritative by atomic replacement of the small `CURRENT`
pointer. The previous authoritative generation is never modified in place.

The dev2 prototype intentionally uses full images. Immutable segment sharing is
a later optimization after fault-injection proves this state machine.

## Explicit recovery state machine (v3.5.3-dev4)

Recovery has no heuristic branch and no recursive behavior:

1. Parse `CURRENT` under the strict generation-ID grammar.
2. Verify the requested generation completely.
3. On failure, enumerate at most `MAX_RECOVERY_CANDIDATES` recognized generation directories.
4. Sort by the fixed-width timestamp-bearing generation identifier, newest first.
5. Verify candidates one at a time; retain typed rejection records.
6. Select the first fully verified generation or fail closed.
7. Optionally repair `CURRENT` atomically and durably.
8. Preserve every rejected generation for diagnosis and later explicit maintenance.

Normal reads do not execute this scan. Recovery is an explicit mount/recovery operation.

## v3.5.3-dev5 restartable cleanup state machine

Cleanup is maintenance, never recovery. Recovery does not delete evidence. A manual destructive operation first writes and durably promotes `CLEANUP.json`, then processes the immutable candidate list. Before each deletion, TDS recomputes the current and pin protection set. Eligible generation directories are atomically renamed into `.cleanup-trash` before recursive removal. If interruption occurs at any boundary, `resume_cleanup()` repeats the plan safely: already absent candidates are skipped and newly protected candidates are preserved. The plan is removed only after the complete bounded pass.

## Materialisation Publication Invariant (v3.5.3-dev7)

Guaranteed-storage images are reconstructed only into a unique private sibling
directory. TDS verifies every file digest and performs a closed-world inventory
comparison. The inventory is checked twice, including immediately before atomic
publication, so a file introduced during the publication window cannot gain
authority. A pre-publication failure never creates the requested destination.

# v3.5.3-dev5 Retention, Pinning, and Restartable Cleanup

## Invariants

1. The current generation is never deleted.
2. A pinned generation is never deleted.
3. Cleanup candidates are derived only from verified generations.
4. Manual destructive cleanup requires explicit acknowledgement.
5. The cleanup plan is durable before any generation is removed.
6. Protection is recomputed immediately before every deletion.
7. A generation is atomically quarantined before recursive deletion.
8. Interrupted cleanup is idempotently resumable.
9. Recovery never invokes cleanup and never deletes rejected evidence.

## Performance

Pin lookup uses bounded directory markers. Cleanup remains outside reads and commit promotion. Atomic quarantine makes the foreground filesystem mutation small; recursive deletion occurs only after the generation is no longer visible to normal enumeration.

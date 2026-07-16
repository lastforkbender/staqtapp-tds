# TDS Programmer's API Reference - v3.5.3 storage supplement

This is the canonical lookup source for the Guaranteed Storage APIs added in
the v3.5.3 development sequence. The Programmer Core API Guide covers the
broader pre-existing TDS surface; its first three pages provide the matching
v3.5.3 release supplement. Entries here are organized by public module, class,
method, return type, exception, risk note, and concise example.

## PersistencePolicy

See `staqtapp_tds.persistence_policy`. Atomic generations cannot be disabled.
Retention changes rollback depth; relaxed durability can lose acknowledged data.
Internal generations are not off-device backups.

## ImmutableGenerationStore (development API)

Introduced in v3.5.3-dev2 as the full-image correctness prototype. It is not yet
wired into the legacy v2 mount path and is not a stable public API.

## ImmutableGenerationStore integrity limits (development API)

`ImmutableGenerationStore` rejects application or persisted generation metadata that exceeds its structural safety budgets. Current development limits are 1 MiB encoded metadata, nesting depth 32, and 10,000 aggregate nodes. Violations raise `GenerationIntegrityError` before commit promotion or mount. These limits are part of the untrusted-input safety contract and may become configurable only through a future explicitly bounded policy API.

## Recovery API (development)

### `ImmutableGenerationStore.recover_report(*, repair_current=True) -> RecoveryReport`

Deterministically verifies the generation named by `CURRENT`; when it cannot be mounted, verifies candidate generations newest-to-oldest under a bounded scan limit. A successful fallback optionally repairs `CURRENT` through the same durable atomic-pointer protocol used by commit promotion.

`RecoveryReport` exposes `requested_generation`, `mounted_generation`, typed `condition`, human-readable `detail`, `current_repaired`, `scanned_candidates`, and all `rejected_generations` examined before the selected generation.

Recovery never deletes rejected generations. `repair_current=False` performs an inspection-only selection and leaves the filesystem pointer unchanged.

## Generation retention and cleanup (development API)

### `ImmutableGenerationStore.pin(generation_id) -> None`
Persistently protects a verified generation from cleanup. Pins survive process restarts and are stored independently of generation metadata.

### `ImmutableGenerationStore.unpin(generation_id, *, acknowledge_reduced_recovery=False) -> None`
Removes persistent protection. The acknowledgement flag is mandatory because a later cleanup may permanently delete the generation.

### `ImmutableGenerationStore.list_pins() -> tuple[str, ...]`
Returns pinned generation identifiers in stable order.

### `ImmutableGenerationStore.prune(*, keep, acknowledge_reduced_recovery=False) -> CleanupReport`
Creates a durable cleanup plan and then removes only verified, unpinned, non-current generations outside the protected retention set. Any destructive plan requires explicit acknowledgement. Cleanup quarantines a generation directory by atomic rename before recursive deletion.

### `ImmutableGenerationStore.resume_cleanup() -> CleanupReport | None`
Resumes an interrupted, already-acknowledged cleanup plan. Missing candidates are treated as previously completed work; protection is recomputed immediately before every deletion.

### `CleanupReport`
Reports the planned, removed, and newly protected/skipped generation identifiers together with whether the operation resumed and completed.

**Risk:** pruning and unpinning can permanently remove rollback history. Internal generations remain local recovery states and are not off-device backups.

## Commit buffer ownership (development API)

### `BufferPolicy.REQUIRE_STABLE`
Default zero-copy policy. `ImmutableGenerationStore.commit()` accepts only read-only, C-contiguous buffer exporters. Immutable `bytes` and read-only contiguous `memoryview` objects stream directly without a full payload copy. Mutable or non-contiguous exporters raise `BufferContractError` before `CURRENT` can be promoted.

### `BufferPolicy.SNAPSHOT`
Explicit copy policy for mutable or non-contiguous exporters. TDS materializes an immutable byte snapshot before persistence, then applies the normal bounded streaming, incremental SHA-256, verification, and atomic promotion sequence.

### `ImmutableGenerationStore.commit(..., buffer_policy=...)`
The default is `BufferPolicy.REQUIRE_STABLE`. Use `SNAPSHOT` only when the caller intentionally accepts the allocation cost in exchange for stable commit bytes. Unknown policy names fail closed.

The low-level writer retries partial `os.write()` progress until each slice is complete. A zero-progress write raises `GenerationError`; the incomplete generation is preserved and `CURRENT` remains unchanged. All temporary views are explicitly released on success and failure.

## GuaranteedStorageBridge (development transition API)

`GuaranteedStorageBridge` is the opt-in compatibility seam between the established
multi-file `TDSPersistence` serializer and immutable guaranteed generations. It
does not change the default persistence path.

### `GuaranteedStorageBridge.analyze_fit() -> TransitionFitAnalysis`

Returns a machine-readable statement of the transition architecture, including
which legacy behavior is reused, whether the default path changes, the bounded-
memory property, guaranteed outcomes, and unavoidable performance costs.

### `GuaranteedStorageBridge.commit_filesystem(fs, *, parallel_nodes=True) -> GuaranteedCommitReport`

Flushes the complete filesystem into an isolated legacy-compatible staging mount,
then streams that mount into one atomically promoted generation. The staged image
uses a bounded record stream with per-file SHA-256 digests. A failed transition
commit cannot replace `CURRENT`.

### `GuaranteedStorageBridge.materialize_current(destination) -> Path`

Verifies the current generation, extracts it into a private sibling directory,
validates every path and per-file digest, fsyncs the completed image, and only then
publishes the destination by atomic rename. The destination must not already exist.

**Transition status:** this API proves compatibility and recovery fit. It is not
yet the default `TDSPersistence` mount path. The full-image bridge deliberately
pays an extra legacy staging write and generation-stream write to preserve a clear
correctness proof before incremental segment reuse is introduced.

## `GuaranteedStorageBridge.materialize_current_report(destination)`

Materialises the current transition image into a unique private sibling
directory, verifies exact file inventory and per-file digests, and atomically
publishes the requested destination. Returns `MaterializationReport` containing
`destination`, `files_materialized`, `bytes_materialized`, and `published`.
Pre-publication failures never create the requested destination.

## Verified migration and incremental segments

### `GuaranteedStorageBridge.verify_round_trip(legacy_mount, destination) -> VerifiedMigrationReport`

Creates a private segmented representation of an existing legacy mount,
reconstructs it to a new destination, and proves exact path inventory, file
lengths, SHA-256 digests, structured metadata, logical reopen behavior, and
unchanged source bytes. The destination must not already exist. A report is not
activation authority; Phase 10 performs a separate qualification under the
mode-mutation lock.

### `GuaranteedStorageBridge.commit_filesystem_segmented(fs, *, parallel_nodes=True) -> SegmentedGuaranteedCommitReport`

Serializes a complete `TDSFileSystem` through the established legacy writer,
then commits an ordered immutable segment generation. Unchanged fixed-size
segments are content addressed and reused. The report distinguishes logical
source bytes, segments created/reused, and physical bytes written.

### `GuaranteedStorageBridge.commit_mount_segmented(legacy_mount) -> SegmentedGuaranteedCommitReport`

Commits an existing verified legacy mount into the segmented generation store.
The source must be a real directory outside the Guaranteed Storage root.

### `GuaranteedStorageBridge.materialize_segmented_current_report(destination) -> MaterializationReport`

Reconstructs the current segmented generation through the hardened private
materialization path. It verifies all segment hashes, the complete logical hash,
archive paths, exact output inventory, and durability boundaries before atomic
destination publication.

### `GuaranteedStorageBridge.materialize_segmented_generation_report(generation_id, destination) -> MaterializationReport`

Performs the same verified reconstruction for a named retained segmented
generation. It never changes `SEGMENT_CURRENT`.

## `ImmutableSegmentStore`

Public module: `staqtapp_tds.segment_store`; re-exported from `staqtapp_tds`.
This opt-in store publishes immutable ordered manifests of SHA-256-addressed
segments. It does not change the legacy persistence path by construction.

### `ImmutableSegmentStore(root, *, policy=None, segment_bytes=1048576, fault_hook=None)`

Creates or opens a segmented store. `segment_bytes` must be from 1 byte through
16 MiB. The mutation lock excludes commit, generation deletion, and garbage
collection across processes. A crash-retained lock fails closed until an
operator has established that no mutation is active.

### `commit(data, *, application_metadata=None) -> SegmentCommitReport`

### `commit_stream(chunks, *, application_metadata=None) -> SegmentCommitReport`

Commits a complete logical byte stream and atomically publishes its manifest
only after all segments and the manifest verify. The report contains the new
`SegmentGenerationInfo`, created/reused segment counts, physical bytes written,
and logical bytes committed.

### `read_current() -> bytes`

### `verify(generation_id) -> SegmentGenerationInfo`

`read_current` reconstructs and verifies the currently named segmented
generation. `verify` checks a named manifest, every referenced segment, logical
length, logical SHA-256, and manifest identity without changing authority.

### `reference_counts() -> dict[str, int]`

Returns manifest-derived reference counts only when the complete recognized
generation universe is valid. If any generation is malformed, unreadable, or
references damaged segments, it raises `SegmentIntegrityError`; it never
silently omits the invalid generation from accounting.

### `collect_unreferenced_segments(*, dry_run=True) -> SegmentGCReport`

Dry-run mode inventories candidates without deleting. Destructive mode first
fails closed if any recognized generation is invalid. For every candidate it
recomputes reachability, crosses the final injectable boundary, recomputes
reachability again, and revalidates regular-file type, device, inode, size,
mode, modification time, and change time immediately before unlink.

`SegmentGCReport` exposes `referenced_segments`, `candidate_segments`,
`invalid_generations`, `changed_candidates`, `removed_segments`,
`removed_bytes`, `retained_unreferenced`, `dry_run`, and `blocked`. Only files
actually unlinked contribute to removed counts. A changed or newly referenced
candidate is retained and reported.

```python
preview = segments.collect_unreferenced_segments(dry_run=True)
if preview.blocked:
    raise SegmentIntegrityError(preview.invalid_generations)

# Explicit destructive call; protection is recomputed instead of trusting the preview.
removed = segments.collect_unreferenced_segments(dry_run=False)
assert not removed.blocked
```

**Risk:** the second call is destructive and can permanently remove segment
bytes not referenced by any retained valid manifest. Preserve off-device
backups and review the dry-run inventory, but do not assume the preview freezes
the reference universe.

## Controlled activation

Public module: `staqtapp_tds.storage_activation`; all types below are re-exported
from `staqtapp_tds`.

### `StorageMode`

`StorageMode.LEGACY` and `StorageMode.GUARANTEED_SEGMENTED` are the only
recognized authoritative modes. Absence of a mode record means `LEGACY`.

### `ControlledStorage(root, legacy_mount, *, fault_hook=None)`

Creates a mode-aware persistence facade. `root` must be a real directory and
must not equal, or be contained by, `legacy_mount`. Construction never changes
the mode.

### `status(*, verify_current=True) -> StorageActivationStatus`

Returns mode, revision, authoritative legacy mount, qualification and generation
identifiers, activation/current verification, rollback availability, persisted
state, change time, and previous mode. Non-canonical or corrupt control records
raise `ControlledActivationError`.

### `qualify_activation() -> ActivationQualification`

Creates a segmented generation and a canonical immutable receipt proving exact
inventory, lengths, SHA-256 digests, structured metadata, logical reopen
equivalence, and unchanged source bytes. Qualification does not activate.

### `activate(qualification, *, acknowledgement) -> StorageActivationStatus`

Requires `acknowledgement == "activate-guaranteed-segmented"`. It reloads the
canonical receipt and repeats every proof under the mutation lock immediately
before atomic mode publication. A stale qualification or changed source fails
closed and leaves legacy authority unchanged.

```python
from staqtapp_tds import ControlledStorage, StorageMode

store = ControlledStorage(guaranteed_root, legacy_mount)
assert store.status().mode is StorageMode.LEGACY
qualification = store.qualify_activation()
active = store.activate(
    qualification,
    acknowledgement=store.ACTIVATE_ACKNOWLEDGEMENT,
)
assert active.mode is StorageMode.GUARANTEED_SEGMENTED
```

### `commit_filesystem(fs, *, parallel_nodes=True) -> ControlledCommitReport`

Commits through the currently authorized mode without switching paths. Legacy
mode uses a new verified legacy mount; guaranteed mode publishes an incremental
segment generation. The report exposes mode, optional generation ID, archived
files, logical source bytes, segment reuse/creation, and physical bytes written.

### `active_mount() -> Iterator[Path]`

Context manager yielding the current authoritative mount. In guaranteed mode it
returns a verified private reconstruction and removes that temporary view on
exit; it never exposes segment internals as a writable legacy mount.

### `rollback_to_legacy(*, acknowledgement) -> StorageActivationStatus`

Requires `acknowledgement == "rollback-to-legacy"`. It reconstructs the current
guaranteed generation into a new legacy-compatible mount, verifies its complete
bytes and logical reopen behavior, and only then atomically publishes legacy
authority. The original pre-activation mount and all immutable generations are
left untouched.

### Browser/admin observation

`AdminControl(observation_source=controlled).status()["storage_mode"]` provides
a bounded JSON-safe status snapshot. This surface is observational: Browser
polling cannot qualify, activate, commit, roll back, delete generations, or run
GC.

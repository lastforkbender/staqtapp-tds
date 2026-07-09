# Storage Engine Hardening Pre-CVS Patch

Scope: storage engine only. Driver Studio, Driver VM, browser UI, admin review authority, and policy layers remain outside this patch.

This patch closes the deep storage-analysis gaps found before the planned unique CVS feature work. The storage engine now treats malformed `.tds` geometry as a fail-closed integrity condition instead of exposing partial keys or silently ignoring malformed records.

## Hardened areas

### Slot-index parsing

`SlotIndex.from_bytes()` now validates the full declared slot index:

- incomplete fixed slot headers are rejected
- incomplete variable name bytes are rejected
- parsed slot count must match the file header slot count
- trailing bytes after the declared index are rejected
- UTF-8 slot names must decode cleanly
- slot `name_hash` is recomputed and verified
- duplicate slot names are rejected

### File and slot geometry

`TDSReader.open()` now validates file layout before any key is exposed:

- file must be at least `FILE_HDR_SIZE`
- `data_offset` cannot point inside the fixed header
- `index_offset` cannot precede `data_offset`
- `index_offset` cannot point past EOF
- every slot payload range must stay inside the data block

### Payload content-hash enforcement

When sidecar metadata provides `content_hash`, `TDSReader.read()` validates the decoded raw payload bytes before returning data. A mismatch returns a non-halting typed integrity result with code `PERSIST_PAYLOAD_HASH_MISMATCH`.

Compressed entries are decompressed with the persisted sidecar codec before hashing. If the required codec is unavailable or fails, the reader returns `PERSIST_CODEC_UNAVAILABLE` instead of guessing from the current process default.

### Codec-stable compressed persistence

`TDSWriter._serialize_entry()` now serializes compressed entries with `entry.codec`. Lazy entries pass the stored codec back into `TDSReader.read()`. Compressed persisted data no longer depends on the process-wide default codec at load time.

### Snapshot-coupled sidecar generation

`TDSWriter` now builds the data block, slot index, and sidecar entry metadata from the same frozen entry snapshot. The sidecar records hardening fields including:

- `schema`
- `snapshot_epoch`
- `tds_header_ts`
- `tds_file_size`
- `tds_slot_count`
- `tds_index_offset`
- `tds_data_offset`

`TDSReader` enforces epoch and file-size equality when those fields are present.

### Sidecar durability symmetry

Sidecar writes now use the same durability style as `.tds` data writes:

1. write temp file through a file descriptor
2. write all bytes with short-write detection
3. `fsync()` the temp sidecar
4. `os.replace()` into place
5. best-effort parent directory `fsync()`

### Stable value snapshot for mutable JSON/text/raw writes

JSON, text, and raw-binary write lanes now freeze their durable value at write time. Mutating a caller-owned JSON object after `write_json()` but before `flush()` no longer changes the persisted snapshot.

## New result codes

The result-code registry now includes typed persistence integrity codes:

- `PERSIST_HEADER_CORRUPT`
- `PERSIST_INDEX_CORRUPT`
- `PERSIST_SLOT_BOUNDS_ERROR`
- `PERSIST_PAYLOAD_HASH_MISMATCH`
- `PERSIST_CODEC_UNAVAILABLE`
- `PERSIST_SIDECAR_STALE`
- `PERSIST_SIDECAR_CORRUPT`
- `PERSIST_SNAPSHOT_EPOCH_MISMATCH`
- `PERSIST_WRITE_ERROR`

## Regression coverage

Added `tests/test_storage_engine_hardening_pre_cvs.py`, covering:

- truncated index tails fail closed
- overstated slot counts fail closed
- index offsets past EOF fail closed
- payload bit-flips produce `PERSIST_PAYLOAD_HASH_MISMATCH`
- compressed payloads use the persisted codec instead of the current default
- mutable JSON values are frozen at write time

Validation performed after patch:

```text
storage hardening probes: 7 passed
selected native/storage tests: 21 passed
full suite after native build: 414 passed
```

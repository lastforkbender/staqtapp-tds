# v3.8.1 Browser Performance and Workspace Telemetry Mount

Status: released in v3.8.1. The Browser remains a read-only observer, and the
workspace mount does not expand storage or execution authority.

## What changed

The packaged Browser now behaves as a page-based console instead of keeping all
19 telemetry surfaces visible in one long scrolling document. Navigation keeps
the existing element IDs and URL hashes, but displays only the selected page.
The refresh loop is serialized, stops while the document is hidden, resumes
immediately when visible, and writes text, styles, and dynamic lists only when
their values change. Expensive continuous backdrop blur and decorative motion
were removed while retaining the existing dark visual system.

The packaged launcher previously constructed `AdminControl()` without an
observation source. A separately launched Browser therefore had no live TDS
process to observe. The workspace telemetry mount supplies that missing,
observer-only cross-process boundary.

## Producer: attach the application process

```python
from pathlib import Path

from staqtapp_tds import TDSFileSystem
from staqtapp_tds.admin import attach_workspace_telemetry

fs = TDSFileSystem("application")
mount = Path.home() / ".local" / "share" / "staqtapp-tds" / "live"
mount.parent.mkdir(parents=True, exist_ok=True)
telemetry = attach_workspace_telemetry(
    fs,
    mount,
)
telemetry.start(interval_seconds=2.0)

try:
    # Run the application that uses fs.
    ...
finally:
    telemetry.stop()
```

Construction and attachment have no side effects. `start()` is explicit and
starts the manager's single snapshot-assembly cadence, with the workspace file
writer attached as a post-publication sink. The file writer receives the exact
already-published snapshot; it never initiates a second sampler pass.

If the application already owns a `TelemetryPublisherThread`, attach the mount
to that publisher instead of calling `telemetry.start()`:

```python
workspace_sink = telemetry.publish
application_publisher.add_sink(workspace_sink)
try:
    ...
finally:
    application_publisher.remove_sink(workspace_sink)
```

Only one `TelemetryPublisherThread` may own a manager at a time. A competing
start fails explicitly instead of silently doubling directory walks and lock
sampling. Manual `telemetry.publish()` is also available after the manager has
an already-published snapshot; it never force-builds one on the caller thread.

## Consumer: launch the Browser process

```bash
staqtapp-tds \
  --workspace-mount "$HOME/.local/share/staqtapp-tds/live"
```

The older admin entry point accepts the same source:

```bash
staqtapp-tds-admin serve-panel \
  --host 127.0.0.1 \
  --port 8765 \
  --workspace-mount "$HOME/.local/share/staqtapp-tds/live"
```

The Browser shows `ready`, `stale`, `unavailable`, or `invalid` in its top
status strip. Missing producer snapshots do not crash the server.

## Boundary and failure behavior

- The mount is a telemetry exchange directory, not a `.tds` persistence mount.
- The producer writes one canonical, bounded JSON snapshot through an atomic
  temporary-file, file-`fsync`, `os.replace`, and directory-`fsync` sequence.
- The consumer opens only the fixed snapshot filename. It never walks TDS
  directories, Swiss tables, radix routers, native indexes, or storage locks.
- Every path component and snapshot file is checked against traversal,
  symlinks, reparse points, and non-regular file types at access time. The mount
  is a local application boundary and must live in a directory not writable by
  an adversarial local user; these portable path checks are not a substitute
  for OS sandboxing or handle-relative traversal in a hostile shared directory.
- Snapshot payloads are limited to 1 MiB and bounded for JSON depth and node
  count. Malformed and noncanonical bytes fail closed into `invalid` status.
- Publisher PID, start identity, sequence, and publication time distinguish
  producer lifetimes. A snapshot older than 10 seconds is visible but `stale`.
- Multiple producers are intentionally not arbitrated; the last atomic writer
  wins and is identified by the owner metadata.
- The workspace wrapper resets its own synchronization state after a POSIX
  fork. An inherited live `TelemetryManager` or `TDSFileSystem` may contain
  parent-owned locks and publisher identity; construct and attach those objects
  in the child after a multithreaded fork.

The exchange is diagnostic and non-authoritative. Its contents cannot promote
configuration, mutate storage, activate Eaglegate, or authorize Frontier Fabric
execution.

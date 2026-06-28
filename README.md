# 🟦🟪🟧 Staqtapp-TDS v2.1.0

**Temporal Directory System** — a Python-first virtual storage layer for named Python variables, UTF-8 text payloads, semantic routing metadata, provenance tags, and high-throughput lookup paths.

> v2.1.0 is the extended speed-target release: **optional native Swiss-table-inspired EntryIndex**, **GIL-released native reads**, and a **radix directory router**. The public Python API remains intact.

---

## Upfront performance statement

Staqtapp-TDS v2.1.0 avoids the GIL only in the specific native lookup primitive:

```text
EntryIndex.get_handle(key)
EntryIndex.contains(key)
```

When the optional native extension is built, these methods execute the native table lookup inside `Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS`. This means concurrent read-heavy lookup workloads can proceed without holding the Python GIL during the native key-to-handle search.

The GIL is **not** avoided for:

```text
pickle serialization/deserialization
JSON parsing
text decoding
compression/decompression
stalkvar merge/copy behavior
Python object return from handles
persistence flush/load orchestration
manifest parsing
Python directory object traversal
```

So the speed increase is strongest where TDS is repeatedly resolving names, route IDs, filenames, and variable keys into stable `int64` handles.

---

## What changed in v2.1.0

### 1. Native Swiss-table-inspired EntryIndex

The optional C backend now uses:

```text
bytes key -> int64 handle
```

with:

- open addressing,
- Swiss-table-style hash fingerprints/control bytes,
- triangular probing,
- tombstones,
- resize on load pressure,
- native read/write lock,
- GIL-released `get_handle()` and `contains()`.

This backend is conservative by design. It is **read-concurrent**, not fully lock-free. Writes and resizes are protected by the native lock.

### 2. Radix directory router

Directory children no longer depend directly on a raw dictionary as the only structural routing layer. v2.1.0 adds a compressed-prefix radix router for directory child names and path routing.

This helps prepare TDS for:

```text
deep paths
prefix-heavy semantic zones
cluster layouts
future native radix acceleration
```

The radix router is Python-side in v2.1.0. It is a safe structural step before considering a native radix backend.

### 3. EntryIndex seam remains clean

The native backend still does **not** know about:

```text
variables
stalkvar
lockvar
SRZ
manifest policy
telemetry
provenance
Python objects
```

It only maps keys to handles. This preserves the architecture:

```text
Python semantics
    ↓
EntryIndex facade
    ↓
Python backend or native Swiss backend
    ↓
int64 handle
```

---

## Current storage lanes

```text
Python variables      -> serializer-selected payload kind, pickle fallback
UTF-8 text files      -> TEXT_UTF8, optional chunking
JSON payloads         -> JSON_UTF8, optional orjson/simdjson when available
NumPy arrays          -> ndarray path
Stalk variables       -> controlled variable chains
Lock variables        -> internal access control table
Provenance metadata   -> compact numeric records
Cluster identity      -> lightweight feedback layer
```

---

## Native backend usage

Default behavior:

```python
from staqtapp_tds import EntryIndex

idx = EntryIndex(backend="auto")
```

`auto` attempts native loading and falls back to Python.

Force native:

```python
idx = EntryIndex(backend="native")
```

Force Python:

```python
idx = EntryIndex(backend="python")
```

Inspect backend:

```python
print(idx.backend_name)
print(idx.stats())
```

Native stats include:

```text
backend = native-c-swiss-entryindex
gil_released_get_handle = True
swiss_control_bytes = True
probing = triangular
```

---

## Radix path routing

```python
from staqtapp_tds import TDSFileSystem

fs = TDSFileSystem()
node = fs.makedirs("/models/language/tokenizers")
node.write_text("notes.md", "radix path works")

same = fs.resolve_radix("/models/language/tokenizers")
print(same.read_text("notes.md"))
```

Standard `resolve()` still works. `resolve_radix()` exposes the radix path seam directly.

---

## Design boundary

TDS remains an infrastructure layer:

```text
TDS provides:
  structure
  identity
  lookup speed
  deterministic variable controls
  telemetry
  provenance tagging
  invariant feedback

TDS does not provide:
  reasoning
  semantic interpretation
  AI planning
```

This boundary matters because native code should accelerate mechanics, not absorb the higher-level Python design.

---

## Testing status

v2.1.0 validation included:

```text
34 pytest tests passed
native extension build smoke test passed
Swiss backend stats verified
GIL-release flags verified
radix prefix/delete/path tests passed
concurrent native read test passed
variable/text semantics regression tests passed
```

---

## Remaining bottlenecks

After v2.1.0, the next bottlenecks are not the same as the EntryIndex bottleneck:

```text
payload serialization
pickle-heavy Python objects
compression/decompression
large text scanning
chunk index search
persistence batching
arena lifecycle
cluster-scale indexes
```

The next major design target should be index-first large text/cluster querying, not further expanding the native backend prematurely.

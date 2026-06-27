<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=185&text=Staqtapp-TDS%20v1.6&fontAlign=50&fontAlignY=35&desc=Python-first%20VFS%20%7C%20Native-ready%20EntryIndex%20%7C%20Arena%20Handles&descAlign=50&descAlignY=58&color=gradient" alt="Staqtapp-TDS v1.6 banner" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Staqtapp--TDS-v1.6.0-7c3aed?style=for-the-badge" alt="version" />
  <img src="https://img.shields.io/badge/src--layout-clean%20repo-00bcd4?style=for-the-badge" alt="src layout" />
  <img src="https://img.shields.io/badge/EntryIndex-backend%20facade-ff6b00?style=for-the-badge" alt="entry index facade" />
  <img src="https://img.shields.io/badge/Python--first-native%20ready-14b8a6?style=for-the-badge" alt="python first native ready" />
</p>

# Staqtapp-TDS — Temporal Directory System

**Staqtapp-TDS v1.6.0** is a Python-first VFS package with a cleaner repo structure and a formal native-extension seam for the future high-throughput EntryIndex.

This release does **not** force C/C++ on the project. It keeps Python as the main implementation while separating the hot index boundary so native backends can be added later without rewriting the VFS.

## Repository layout

```text
staqtapp_tds_v1_6_0/
├── pyproject.toml
├── README.md
├── src/
│   └── staqtapp_tds/
│       ├── __init__.py
│       ├── arena.py
│       ├── index.py
│       ├── tds_filesystem.py
│       ├── tds_persistence.py
│       └── backends/
│           ├── __init__.py
│           ├── python_index.py
│           └── native.py
└── tests/
    └── test_vfs_core.py
```

## v1.6.0 upgrade target

The formal step in this version is **repo architecture**, not premature C conversion.

### What changed

1. **EntryIndex facade**
   - `staqtapp_tds.index.EntryIndex` is now the only VFS-facing index surface.
   - It supports `backend="auto"`, `backend="python"`, and future `backend="native"`.
   - Current default is pure Python and portable.

2. **Backend package**
   - `backends/python_index.py` contains the current sharded Python backend.
   - `backends/native.py` defines the optional future native import seam.
   - Future compiled module target: `staqtapp_tds_native.EntryIndexBackend`.

3. **Arena module split**
   - `SharedMemoryArena` moved to `arena.py`.
   - It preserves the `int64` offset-handle ABI for later mmap/shared-memory/native allocators.

4. **src-layout packaging**
   - Package code now lives under `src/staqtapp_tds`.
   - `pyproject.toml` supports modern editable installs and test discovery.

5. **No forced native dependency**
   - Runs on older devices and normal Python environments.
   - Optional native backend can be introduced later without changing public VFS calls.

## Install locally

```bash
tar -xzf staqtapp_tds_v1_6_0.tar.gz
cd staqtapp_tds_v1_6_0
python -m pip install -e .
```

Optional fast mode:

```bash
python -m pip install -e ".[fast,test]"
```

## Quick start

```python
from staqtapp_tds import TDSFileSystem, FmtID, TDSPersistence
import numpy as np

fs = TDSFileSystem("asi_root")
vecs = fs.makedirs("vectors/live", fmt_id=FmtID.NUMPY_MATRIX)
vecs.write("embed_0001", np.arange(16, dtype=np.float32), fmt_id=FmtID.NUMPY_MATRIX)

assert vecs.read("embed_0001").shape == (16,)
print(vecs._entries.backend_name)  # python-sharded today; native-ready later
```

## Native backend contract

A future native backend should provide:

```python
put(key: str, entry: object) -> int
get(key: str, default=None) -> object | None
get_handle(key: str) -> int
get_by_handle(handle: int) -> object | None
pop(key: str, default=None) -> object | None
keys() -> list[str]
values() -> list[object]
items() -> list[tuple[str, object]]
contains(key: str) -> bool
stats() -> object
```

For true GIL avoidance, native `get_handle()` and read-side lookup should run without the GIL and return `int64` handles. Python object hydration should happen only at the edge.

## Honest performance status

- v1.6.0 is **not** a complete GIL-free VFS.
- It is a clean, Python-first repo structure with the correct native boundary.
- The next true performance jump is implementing `staqtapp_tds_native.EntryIndexBackend` in Cython/pybind11 and releasing the GIL for hot handle lookups.

## Test

```bash
python -m pytest
```


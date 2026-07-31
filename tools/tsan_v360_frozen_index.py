#!/usr/bin/env python3
"""Direct concurrent-read smoke for a thread-sanitized frozen native index.

The harness loads the compiled extension directly instead of importing the full
``staqtapp_tds`` package.  That keeps the ThreadSanitizer lane focused on the C
extension and its caller-owned packed buffers rather than unrelated optional
Python dependencies.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
from struct import pack, unpack_from


def _load_native_index():
    candidates = sorted(Path("src/staqtapp_tds").glob("_native_index*.so"))
    if len(candidates) != 1:
        raise RuntimeError(
            "expected exactly one built _native_index extension, "
            f"found {[str(path) for path in candidates]!r}"
        )
    spec = importlib.util.spec_from_file_location("_native_index", candidates[0])
    if spec is None or spec.loader is None:
        raise RuntimeError("could not create an extension loader for _native_index")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    _native_index = _load_native_index()

    count = 2048
    mutable = _native_index.NativeHandleIndex(capacity=4096)
    keys = [f"key-{value:04d}".encode("ascii") for value in range(count)]
    for expected, key in enumerate(keys, start=1):
        actual = int(mutable.put(key))
        if actual != expected:
            raise RuntimeError(f"unexpected handle {actual}, expected {expected}")
    frozen = mutable.freeze()
    blob = b"".join(keys)
    offsets = [0]
    for key in keys:
        offsets.append(offsets[-1] + len(key))
    packed_offsets = b"".join(pack("<Q", value) for value in offsets)

    def worker() -> tuple[int, int]:
        output = bytearray(count * 8)
        for _ in range(100):
            processed = int(frozen.lookup_packed(blob, packed_offsets, output))
            if processed != count:
                raise RuntimeError("incomplete packed lookup")
        return (
            unpack_from("<q", output, 0)[0],
            unpack_from("<q", output, (count - 1) * 8)[0],
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: worker(), range(4)))
    if results != [(1, count)] * 4:
        raise RuntimeError(f"concurrent frozen lookup parity failed: {results!r}")
    print("direct TSan frozen packed-index smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

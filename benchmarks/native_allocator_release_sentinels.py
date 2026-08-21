#!/usr/bin/env python3
"""Fixed semantic, durability, recovery, and zero-scan release sentinels."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import stat
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock

SCRIPT_PATH = Path(__file__).resolve()
INT64_MAX = (1 << 63) - 1


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _io_counters() -> dict[str, int] | None:
    try:
        result = {}
        for line in Path("/proc/self/io").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            result[key.strip()] = int(value.strip())
        return result
    except Exception:
        return None


def _delta(before: dict[str, int] | None, after: dict[str, int] | None) -> dict[str, int] | None:
    if before is None or after is None:
        return None
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in sorted(set(before) | set(after))
    }


def _canonical_file_tree(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError(f"sentinel tree contains symlink: {path}")
        metadata = path.stat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise AssertionError(f"sentinel tree contains non-regular leaf: {path}")
        records.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256_bytes(path.read_bytes()),
            "size_bytes": int(metadata.st_size),
            "st_blocks": int(metadata.st_blocks),
            "allocated_bytes_st_blocks_x_512": int(metadata.st_blocks) * 512,
        })
    canonical = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return {
        "records": records,
        "tree_root_sha256": _sha256_bytes(canonical),
        "files": len(records),
        "logical_bytes": sum(item["size_bytes"] for item in records),
        "allocated_bytes_st_blocks_x_512": sum(
            item["allocated_bytes_st_blocks_x_512"] for item in records
        ),
    }


def _storage_device_class(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path.resolve()),
        "device_id": int(path.stat().st_dev),
        "mount_source": None,
        "mount_point": None,
        "rotational": None,
        "classification": "unknown-block-or-virtual-filesystem",
    }
    try:
        resolved = str(path.resolve())
        candidates = []
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            before, after = line.split(" - ", 1)
            fields = before.split()
            mount_point = fields[4].replace("\\040", " ")
            source = after.split()[1]
            if resolved == mount_point or resolved.startswith(mount_point.rstrip("/") + "/"):
                candidates.append((len(mount_point), mount_point, source))
        if candidates:
            _length, mount_point, source = max(candidates)
            result["mount_point"] = mount_point
            result["mount_source"] = source
            device = Path(source).name
            rotational_path = Path("/sys/class/block") / device / "queue" / "rotational"
            if rotational_path.is_file():
                rotational = int(rotational_path.read_text().strip())
                result["rotational"] = bool(rotational)
                result["classification"] = "rotational-block" if rotational else "non-rotational-block"
            elif source in {"overlay", "tmpfs"}:
                result["classification"] = source
    except Exception:
        pass
    return result


def _function_body(source: str, name: str) -> str:
    start = source.index(name)
    brace = source.index("{", start)
    depth = 0
    for position in range(brace, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : position]
    raise AssertionError(f"unterminated C function {name}")


def _allocator_sentinel(native: Any, source_path: Path, expected_auto_scan: str) -> dict[str, Any]:
    source = source_path.read_text(encoding="utf-8")
    automatic_body = _function_body(source, "allocate_monotonic_handle_locked")
    put_body = _function_body(source, "put_handle_locked")
    automatic_scan_present = "handle_in_use_locked(self, handle, -1)" in automatic_body
    explicit_scan_present = "handle_in_use_locked(self, handle, -1)" in put_body
    if automatic_scan_present != (expected_auto_scan == "present"):
        raise AssertionError("automatic uniqueness-scan source proof mismatch")
    if not explicit_scan_present:
        raise AssertionError("explicit requested-handle collision scan disappeared")

    index = native.NativeHandleIndex(capacity=16)
    first = [int(index.put(f"first-{item}".encode())) for item in range(12)]
    deleted = int(index.pop(b"first-3"))
    after_delete = int(index.put(b"after-delete"))
    capacity_before = int(index.stats()["capacity"])
    for item in range(32):
        index.put(f"resize-{item}".encode())
    capacity_after = int(index.stats()["capacity"])
    after_resize = int(index.put(b"after-resize"))
    if first != list(range(1, 13)) or deleted != 4 or after_delete != 13:
        raise AssertionError("automatic deletion/high-water semantics changed")
    if capacity_after <= capacity_before or after_resize != 46:
        raise AssertionError("automatic resize/high-water semantics changed")

    restored = native.NativeHandleIndex(capacity=16)
    if restored.put(b"restored-low", 4) != 4 or restored.put(b"restored-high", 46) != 46:
        raise AssertionError("explicit restore handles changed")
    if restored.put(b"restored-auto") != 47:
        raise AssertionError("restored automatic high-water changed")
    failures = []
    for key, requested in ((b"duplicate", 46), (b"reuse", 12)):
        try:
            restored.put(key, requested)
        except ValueError as exc:
            failures.append(type(exc).__name__ + ":" + str(exc))
        else:
            raise AssertionError("invalid explicit handle was accepted")

    exhausted = native.NativeHandleIndex(capacity=16)
    if exhausted.put(b"last", INT64_MAX) != INT64_MAX:
        raise AssertionError("INT64_MAX explicit handle changed")
    exhausted.pop(b"last")
    try:
        exhausted.put(b"no-reuse")
    except OverflowError as exc:
        exhaustion = type(exc).__name__ + ":" + str(exc)
    else:
        raise AssertionError("exhausted allocator reused a deleted handle")

    concurrent = native.NativeHandleIndex(capacity=16)
    workers = 8
    per_worker = 250

    def insert(worker: int) -> list[int]:
        return [
            int(concurrent.put(f"worker-{worker}-{item}".encode()))
            for item in range(per_worker)
        ]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        handles = [handle for batch in pool.map(insert, range(workers)) for handle in batch]
    if sorted(handles) != list(range(1, workers * per_worker + 1)):
        raise AssertionError("concurrent automatic handles changed")

    return {
        "automatic_scan_present": automatic_scan_present,
        "explicit_scan_present": explicit_scan_present,
        "automatic_function_sha256": _sha256_bytes(automatic_body.encode()),
        "explicit_put_function_sha256": _sha256_bytes(put_body.encode()),
        "first_handles": first,
        "deleted_handle": deleted,
        "after_delete": after_delete,
        "capacity_before_resize": capacity_before,
        "capacity_after_resize": capacity_after,
        "after_resize": after_resize,
        "restore_failures": failures,
        "exhaustion": exhaustion,
        "concurrent_handle_set_sha256": _sha256_bytes(
            b"".join(handle.to_bytes(8, "little", signed=True) for handle in sorted(handles))
        ),
    }


def _persistence_sentinel(root: Path) -> dict[str, Any]:
    from staqtapp_tds import FmtID, TDSFileSystem
    from staqtapp_tds.tds_persistence import TDSPersistence, TDSReader

    target = root / "persistence"
    target.mkdir()
    filesystem = TDSFileSystem()
    values = {
        "alpha": b"a" * 32,
        "discard": b"x" * 32,
        "beta": b"b" * 32,
        "gamma": b"g" * 32,
    }
    entries = {
        name: filesystem.root.write_entry(
            name, value, fmt_id=FmtID.RAW_BINARY, compress=False
        )
        for name, value in values.items()
    }
    filesystem.root.delete_entry("discard")
    index = filesystem.root._entry_index
    live_names = ["alpha", "beta", "gamma"]
    preflush = {
        "keys": index.keys(),
        "handles": [int(index.get_handle(name)) for name in live_names],
        "next_handle": int(index.stats().next_handle),
    }
    expected_preflush = {"keys": live_names, "handles": [1, 3, 4], "next_handle": 5}
    if preflush != expected_preflush:
        raise AssertionError(f"preflush deletion/high-water semantics changed: {preflush!r}")
    # File headers and directory/entry metadata normally carry observation
    # timestamps and UUIDs. Freeze only this fixed fixture so the retained file
    # SHA is a meaningful cross-source semantic sentinel rather than a clock
    # comparison.
    fixed_time_ns = 1_700_000_000_000_000_000
    filesystem.root.dir_id = "allocator-release-sentinel-directory"
    filesystem.root._ts_create = fixed_time_ns
    filesystem.root._ts_mod = fixed_time_ns
    for name, entry in entries.items():
        if name == "discard":
            continue
        entry.ts_written = fixed_time_ns
        entry.entry_id = f"sentinel-{name}"
    before_io = _io_counters()
    before_blocks = int(resource.getrusage(resource.RUSAGE_SELF).ru_oublock)
    persistence = TDSPersistence(target)
    with mock.patch(
        "staqtapp_tds.tds_persistence.time.time_ns",
        return_value=fixed_time_ns,
    ):
        paths = persistence.flush(filesystem, parallel_nodes=False)
    after_blocks = int(resource.getrusage(resource.RUSAGE_SELF).ru_oublock)
    after_io = _io_counters()
    data_path = target / "tds_root.tds"
    with TDSReader(data_path) as reader:
        reader_keys = reader.keys()
        first = {name: reader.read(f"/tds_root/{name}") for name in live_names}
    with TDSReader(data_path) as reopened:
        reopened_keys = reopened.keys()
        second = {name: reopened.read(f"/tds_root/{name}") for name in live_names}
    restored = persistence.load_node(data_path)
    third = {name: restored.read_value(name) for name in live_names}
    expected = {name: values[name] for name in live_names}
    expected_reader_keys = [f"/tds_root/{name}" for name in live_names]
    restored_index = restored._entry_index
    restored_before_insert = {
        "keys": restored_index.keys(),
        "handles": [int(restored_index.get_handle(name)) for name in live_names],
        "next_handle": int(restored_index.stats().next_handle),
    }
    restored.write_entry(
        "delta", b"d" * 32, fmt_id=FmtID.RAW_BINARY, compress=False
    )
    restored_after_insert = {
        "delta_handle": int(restored_index.get_handle("delta")),
        "next_handle": int(restored_index.stats().next_handle),
    }
    restored_semantics = {
        "preflush": preflush,
        "serialized_keys": reader_keys,
        "reopened_keys": reopened_keys,
        "restored_before_insert": restored_before_insert,
        "restored_after_insert": restored_after_insert,
    }
    expected_restored_semantics = {
        "preflush": expected_preflush,
        "serialized_keys": expected_reader_keys,
        "reopened_keys": expected_reader_keys,
        "restored_before_insert": {
            "keys": live_names,
            "handles": [1, 2, 3],
            "next_handle": 4,
        },
        "restored_after_insert": {"delta_handle": 4, "next_handle": 5},
    }
    if first != expected or second != expected or third != expected:
        raise AssertionError("persistence save/reopen/restore changed values")
    if restored_semantics != expected_restored_semantics:
        raise AssertionError(
            f"persistence order/compact-handle/high-water semantics changed: {restored_semantics!r}"
        )
    file_tree = _canonical_file_tree(target)
    expected_inventory = {".tds_manifest", "tds_root.tds", "tds_root.tds.meta"}
    if {item["path"] for item in file_tree["records"]} != expected_inventory:
        raise AssertionError("persistence file inventory changed or omitted a sidecar")
    written_paths = sorted(
        Path(path).resolve().relative_to(target.resolve()).as_posix() for path in paths
    )
    return {
        "written_paths": written_paths,
        "value_root": _sha256_bytes(b"".join(expected[name] for name in live_names)),
        "named_value_sha256": {
            name: _sha256_bytes(expected[name]) for name in live_names
        },
        "restored_semantics": restored_semantics,
        "process_io_delta": _delta(before_io, after_io),
        "rusage_output_blocks_delta": after_blocks - before_blocks,
        "file_tree": file_tree,
        "tree_allocation": {
            key: file_tree[key]
            for key in ("files", "logical_bytes", "allocated_bytes_st_blocks_x_512")
        },
        "storage_device": _storage_device_class(target),
    }


def _generation_sentinel(root: Path) -> dict[str, Any]:
    from staqtapp_tds.generation.generation_store import AtomicGenerationStore

    target = root / "generation"
    store = AtomicGenerationStore(target)
    namespace = "dataset:allocator-release-sentinel"
    source = b"id,name\n1,Ada\n"
    offsets = len(source).to_bytes(8, "little")

    def build(candidate_source: bytes, candidate_offsets: bytes):
        return store.build_candidate(
            namespace=namespace,
            payloads={"source": candidate_source, "offsets": candidate_offsets},
            media_types={
                "source": "application/octet-stream",
                "offsets": "application/vnd.staqtapp.offsets",
            },
            authoritative_payload="source",
            parent_generation_root=None,
            qualifications={"source-roundtrip": "sha256:" + "1" * 64},
            metadata={"consumer": "allocator-release-sentinel"},
        )

    candidate = build(source, offsets)
    source_mutant = build(b"id,name\n1,Eve\n", offsets)
    offsets_mutant = build(source, (len(source) + 1).to_bytes(8, "little"))
    if len({
        candidate.generation_root,
        source_mutant.generation_root,
        offsets_mutant.generation_root,
    }) != 3:
        raise AssertionError("Generation roots are not sensitive to source/offset mutations")
    payload_roots = {
        name: {item.name: item.content_root for item in value.manifest.payloads}
        for name, value in (
            ("base", candidate),
            ("source_mutant", source_mutant),
            ("offsets_mutant", offsets_mutant),
        )
    }
    if not (
        payload_roots["base"]["source"] != payload_roots["source_mutant"]["source"]
        and payload_roots["base"]["offsets"] == payload_roots["source_mutant"]["offsets"]
        and payload_roots["base"]["source"] == payload_roots["offsets_mutant"]["source"]
        and payload_roots["base"]["offsets"] != payload_roots["offsets_mutant"]["offsets"]
    ):
        raise AssertionError("Generation payload mutation changed the wrong content root")
    before_io = _io_counters()
    before_blocks = int(resource.getrusage(resource.RUSAGE_SELF).ru_oublock)
    published = store.publish(candidate, expected_head_root=None)
    current_before = store.current_head(namespace)
    if current_before is None:
        raise AssertionError("published Generation has no CURRENT head")
    current = store._head_path(namespace)
    current.write_bytes(b'{"torn":')
    recovered = store.recover(namespace)
    stable = store.recover(namespace)
    current_after = store.current_head(namespace)
    if current_after is None or recovered.head is None or stable.head is None:
        raise AssertionError("recovered Generation has no CURRENT head")
    with store.pin(namespace) as lease:
        recovered_source = lease.read_payload("source")
        recovered_offsets = lease.read_payload("offsets")
        lease_generation_root = lease.generation_root
    after_blocks = int(resource.getrusage(resource.RUSAGE_SELF).ru_oublock)
    after_io = _io_counters()
    if recovered_source != source or recovered_offsets != offsets:
        raise AssertionError("Generation recovery changed source or offsets bytes")
    if len(recovered_offsets) != 8 or int.from_bytes(recovered_offsets, "little") != len(source):
        raise AssertionError("Generation offsets readback changed")
    if not recovered.repaired or stable.repaired or recovered.head != stable.head:
        raise AssertionError("Generation recovery was not deterministic/idempotent")
    generation_roots = {
        "candidate_generation": candidate.generation_root,
        "published_manifest_generation": published.manifest.generation_root,
        "published_head_generation": published.head.generation_root,
        "current_before_generation": current_before.generation_root,
        "recovered_generation": recovered.head.generation_root,
        "stable_generation": stable.head.generation_root,
        "current_after_generation": current_after.generation_root,
        "lease_generation": lease_generation_root,
    }
    head_roots = {
        "published_head": published.head.head_root,
        "current_before_head": current_before.head_root,
        "recovered_head": recovered.head.head_root,
        "stable_head": stable.head.head_root,
        "current_after_head": current_after.head_root,
    }
    if len(set(generation_roots.values())) != 1 or len(set(head_roots.values())) != 1:
        raise AssertionError("Generation published/recovered roots differ within one source")
    readback_records = [
        {"name": name, "size": len(value), "sha256": _sha256_bytes(value)}
        for name, value in (("offsets", recovered_offsets), ("source", recovered_source))
    ]
    readback_root = _sha256_bytes(
        json.dumps(readback_records, sort_keys=True, separators=(",", ":")).encode()
    )
    file_tree = _canonical_file_tree(target)
    return {
        "generation_root": published.manifest.generation_root,
        "head_root": published.head.head_root,
        "roots": {**generation_roots, **head_roots},
        "source_sha256": _sha256_bytes(recovered_source),
        "offsets_sha256": _sha256_bytes(recovered_offsets),
        "offsets_value_little_endian": int.from_bytes(recovered_offsets, "little"),
        "payload_readback": {
            "records": readback_records,
            "root_sha256": readback_root,
        },
        "mutations": {
            "source_generation_root": source_mutant.generation_root,
            "offsets_generation_root": offsets_mutant.generation_root,
            "payload_content_roots": payload_roots,
        },
        "first_recovery_repaired": bool(recovered.repaired),
        "second_recovery_repaired": bool(stable.repaired),
        "first_recovery_valid_records": int(recovered.valid_records),
        "second_recovery_valid_records": int(stable.valid_records),
        "process_io_delta": _delta(before_io, after_io),
        "rusage_output_blocks_delta": after_blocks - before_blocks,
        "file_tree": file_tree,
        "tree_allocation": {
            key: file_tree[key]
            for key in ("files", "logical_bytes", "allocated_bytes_st_blocks_x_512")
        },
        "storage_device": _storage_device_class(target),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-label", choices=("baseline", "allocator-only", "candidate"), required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-auto-scan", choices=("present", "absent"), required=True)
    args = parser.parse_args()

    import staqtapp_tds
    from staqtapp_tds import _native_index

    if staqtapp_tds.__version__ != args.expected_version:
        raise AssertionError("sentinel TDS version mismatch")
    package = Path(staqtapp_tds.__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="tds-allocator-sentinels-") as temporary:
        root = Path(temporary)
        allocator = _allocator_sentinel(
            _native_index,
            package / "_native_index.c",
            args.expected_auto_scan,
        )
        persistence = _persistence_sentinel(root)
        generation = _generation_sentinel(root)

    result = {
        "schema": 2,
        "sentinel_id": "native-allocator-release-sentinels-v2",
        "source_identity": {
            "label": args.source_label,
            "commit": args.source_commit,
            "tree": args.source_tree,
            "version": staqtapp_tds.__version__,
            "native_source_sha256": _sha256_bytes((package / "_native_index.c").read_bytes()),
            "wrapper_source_sha256": _sha256_bytes(
                (package / "backends" / "native_index.py").read_bytes()
            ),
            "extension_sha256": _sha256_bytes(Path(_native_index.__file__).read_bytes()),
            "extension_path": str(Path(_native_index.__file__).resolve()),
        },
        "harness": {"path": str(SCRIPT_PATH), "sha256": _sha256_bytes(SCRIPT_PATH.read_bytes())},
        "platform": {"platform": platform.platform(), "python": sys.version},
        "allocator": allocator,
        "persistence": persistence,
        "generation": generation,
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

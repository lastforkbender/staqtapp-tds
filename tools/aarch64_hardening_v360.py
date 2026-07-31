#!/usr/bin/env python3
"""Produce bounded AArch64 hardening evidence for the v3.6 native engine.

The tool loads the two compiled extensions directly, repeats deterministic byte
and parser fixtures, stresses the immutable packed-index path concurrently, and
emits one JSON-safe evidence record. It is qualification evidence only: it has
no storage, semantic, release, promotion, or activation authority.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import platform
from struct import calcsize, pack, unpack_from
import subprocess
import sys
from typing import Any, Iterable


FORMAT = "tds.v360.aarch64-hardening.v1"
SEMANTIC_DOMAIN = b"TDS-V360-AARCH64-HARDENING-V1\0"
EXPECTED_SEMANTIC_ROOT = "9ed03c78b6a99e1229808c764bee6bb0770aeb00c3905f40614665411006270a"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_root(value: dict[str, Any]) -> str:
    return hashlib.sha256(SEMANTIC_DOMAIN + canonical_json(value)).hexdigest()


def canonical_architecture(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"x86_64", "amd64"}:
        return "x86_64"
    if normalized in {"aarch64", "arm64"}:
        return "aarch64"
    return normalized


def load_extension(module_name: str) -> Any:
    package_dir = Path(__file__).resolve().parents[1] / "src" / "staqtapp_tds"
    candidates: list[Path] = []
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        candidates.extend(package_dir.glob(f"{module_name}*{suffix}"))
    candidates = sorted({path.resolve() for path in candidates if path.is_file()})
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one built {module_name} extension, found {candidates!r}"
        )
    path = candidates[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to create extension spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_commit() -> str:
    explicit = os.environ.get("GITHUB_SHA", "").strip()
    if explicit:
        return explicit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def pack_keys(keys: Iterable[bytes]) -> tuple[bytes, bytes]:
    materialized = tuple(keys)
    blob = b"".join(materialized)
    offsets = [0]
    total = 0
    for key in materialized:
        total += len(key)
        offsets.append(total)
    return blob, b"".join(pack("<Q", value) for value in offsets)


def checksum_fixture(native: Any) -> dict[str, Any]:
    payloads = (
        ("empty", b""),
        ("check-vector", b"123456789"),
        ("utf8", "β😀𝄞日本語".encode("utf-8")),
        ("all-bytes", bytes(range(256))),
    )
    algorithms = ("crc32-ieee-v1", "fnv1a32-legacy-v1")
    results: dict[str, list[int]] = {}
    raw = [payload for _name, payload in payloads]
    for algorithm in algorithms:
        scalar = [
            int(native.checksum32_for_algorithm(payload, algorithm))
            for payload in raw
        ]
        batch = [
            int(value)
            for value in native.checksum32_many_for_algorithm(raw, algorithm)
        ]
        if scalar != batch:
            raise RuntimeError(f"checksum scalar/batch drift for {algorithm}")
        results[algorithm] = scalar
    if results["crc32-ieee-v1"][1] != 0xCBF43926:
        raise RuntimeError("CRC32 IEEE check vector drift")
    return {
        "payloads": [
            {"id": name, "sha256": hashlib.sha256(payload).hexdigest()}
            for name, payload in payloads
        ],
        "results": results,
    }


def utf8_fixture(native: Any) -> dict[str, Any]:
    payload = "a😀bé𝄞日本語".encode("utf-8")
    chunk_sizes = (1, 2, 3, 4, 5, 7, 13, 64)
    bounds: dict[str, list[int]] = {}
    for chunk_size in chunk_sizes:
        values = [int(value) for value in native.utf8_chunk_bounds(payload, chunk_size)]
        previous = 0
        for boundary in values:
            if not previous < boundary <= len(payload):
                raise RuntimeError("invalid UTF-8 boundary order")
            payload[previous:boundary].decode("utf-8", errors="strict")
            previous = boundary
        if previous != len(payload):
            raise RuntimeError("UTF-8 boundaries did not cover the complete payload")
        bounds[str(chunk_size)] = values

    invalid = (
        b"\xc0\x80",
        b"\x80",
        b"\xe2\x28\xa1",
        b"\xed\xa0\x80",
        b"\xf4\x90\x80\x80",
        b"\xf0\x9f\x92",
    )
    faults: list[dict[str, Any]] = []
    for item in invalid:
        try:
            native.utf8_chunk_bounds(item, 2)
        except UnicodeDecodeError as exc:
            faults.append(
                {
                    "hex": item.hex(),
                    "type": type(exc).__name__,
                    "start": int(exc.start),
                    "end": int(exc.end),
                    "reason": str(exc.reason),
                }
            )
        else:
            raise RuntimeError(f"invalid UTF-8 accepted: {item.hex()}")
    return {"payload_sha256": hashlib.sha256(payload).hexdigest(), "bounds": bounds, "faults": faults}


def normalize_csv_result(mapping: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in sorted(mapping.items()):
        if key in {"row_offsets", "row_spans"}:
            result[key] = [int(item) for item in value]
        elif key in {"terminal_newline", "ended_in_open_quote"}:
            result[key] = bool(value)
        else:
            result[key] = int(value)
    return result


def csv_fixture(csv_native: Any) -> dict[str, Any]:
    raw = (
        b'id,text\r\n1,"two\nlines"\r\n2,"quote ""inside"""\n'
        + "3,β😀\r".encode("utf-8")
    )
    variants: dict[str, Any] = {}
    baseline: dict[str, Any] | None = None
    for chunk_size in (0, 1, 2, 3, 7, 31):
        scan = normalize_csv_result(
            csv_native.scan_bytes(
                raw,
                delimiter=ord(","),
                quote=ord('"'),
                escape=ord("\\"),
                doublequote=1,
                chunk_size=chunk_size,
            )
        )
        rows = normalize_csv_result(
            csv_native.row_offsets(
                raw,
                quote=ord('"'),
                escape=ord("\\"),
                doublequote=1,
                chunk_size=chunk_size,
            )
        )
        if scan["row_offsets"] != rows["row_offsets"]:
            raise RuntimeError("CSV scan and row-offset drift")
        semantic = {
            "scan": {key: value for key, value in scan.items() if key != "chunk_count"},
            "rows": {key: value for key, value in rows.items() if key != "chunk_count"},
        }
        if baseline is None:
            baseline = semantic
        elif semantic != baseline:
            raise RuntimeError(f"CSV semantics changed at chunk size {chunk_size}")
        variants[str(chunk_size)] = {"scan": scan, "rows": rows}
    return {
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "variants": variants,
    }


def packed_index_fixture(
    native: Any,
    *,
    key_count: int,
    workers: int,
    iterations: int,
) -> dict[str, Any]:
    mutable = native.NativeHandleIndex(capacity=max(16, key_count * 2))
    keys = [f"arm-key-{value:08d}".encode("ascii") for value in range(key_count)]
    for expected, key in enumerate(keys, start=1):
        actual = int(mutable.put(key))
        if actual != expected:
            raise RuntimeError(f"unexpected handle {actual}, expected {expected}")
    frozen = mutable.freeze()
    blob, offsets = pack_keys(keys)
    expected_bytes = b"".join(pack("<q", value) for value in range(1, key_count + 1))
    expected_digest = hashlib.sha256(expected_bytes).hexdigest()

    def worker() -> str:
        output = bytearray(key_count * 8)
        for _ in range(iterations):
            processed = int(frozen.lookup_packed(blob, offsets, output))
            if processed != key_count:
                raise RuntimeError(
                    f"packed lookup processed {processed}, expected {key_count}"
                )
            if bytes(output) != expected_bytes:
                raise RuntimeError("packed lookup byte parity drift")
        return hashlib.sha256(output).hexdigest()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        digests = list(executor.map(lambda _value: worker(), range(workers)))
    if digests != [expected_digest] * workers:
        raise RuntimeError(f"concurrent packed lookup drift: {digests!r}")

    if key_count:
        removed = int(mutable.pop(keys[0]))
        if removed != 1:
            raise RuntimeError("unexpected mutable removal handle")
        mutable.put(b"source-mutated-after-freeze")
        preserved = bytearray(key_count * 8)
        frozen.lookup_packed(blob, offsets, preserved)
        if bytes(preserved) != expected_bytes:
            raise RuntimeError("frozen snapshot changed after source mutation")

    identity = dict(frozen.identity())
    return {
        "key_count": key_count,
        "workers": workers,
        "iterations_per_worker": iterations,
        "output_sha256": expected_digest,
        "capacity": int(identity["capacity"]),
        "size": int(identity["size"]),
        "frozen_index_contract": str(identity["frozen_index_contract"]),
        "packed_lookup_contract": str(identity["packed_lookup_contract"]),
    }


def diagnostic_fixture(native: Any) -> dict[str, Any]:
    native.diag_reset()
    native.diag_set_enabled(True)
    native.diag_set_sampling(interval=1, burst=0)
    for value in range(16):
        native.diag_emit(60, value, value + 1)
    snapshot = dict(native.diag_snapshot(event_limit=32))
    counters = {
        str(key): int(value)
        for key, value in dict(snapshot.get("counters", {})).items()
    }
    events = [
        {
            "code": int(item.get("code", 0)),
            "value_a": int(item.get("value_a", 0)),
            "value_b": int(item.get("value_b", 0)),
        }
        for item in list(snapshot.get("recent_events", []))
        if isinstance(item, dict)
    ]
    if len(events) < 16 or events[-16:] != [
        {"code": 60, "value_a": value, "value_b": value + 1}
        for value in range(16)
    ]:
        raise RuntimeError("manual diagnostic events were not preserved")
    return {
        "manual_events": events[-16:],
        "events_emitted": int(counters.get("events_emitted", 0)),
        "event_attempts": int(counters.get("event_attempts", 0)),
        "sampling_interval": int(counters.get("sampling_interval", 0)),
        "sampling_burst": int(counters.get("sampling_burst", 0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-architecture", default="aarch64")
    parser.add_argument("--loops", type=int, default=128)
    parser.add_argument("--keys", type=int, default=4096)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--iterations", type=int, default=128)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if min(args.loops, args.keys, args.workers, args.iterations) <= 0:
        parser.error("loops, keys, workers, and iterations must be positive")

    architecture = canonical_architecture(platform.machine())
    expected_architecture = canonical_architecture(args.expected_architecture)
    if architecture != expected_architecture:
        raise SystemExit(
            f"architecture mismatch: observed {architecture!r}, expected {expected_architecture!r}"
        )
    if sys.byteorder != "little" or calcsize("P") != 8:
        raise SystemExit("hardening fixture requires little-endian 64-bit execution")

    native = load_extension("_native_index")
    csv_native = load_extension("_csv_scan_kernel")

    contracts = {
        "native_abi": int(native.TDS_NATIVE_ABI_VERSION),
        "native_engine": str(native.TDS_NATIVE_ENGINE),
        "checksum_algorithms": str(native.TDS_NATIVE_CHECKSUM_ALGORITHMS),
        "utf8_contract": str(native.TDS_NATIVE_UTF8_CHUNK_CONTRACT),
        "diagnostic_protocol": str(native.TDS_NATIVE_DIAG_PROTOCOL),
        "diagnostic_sampling": str(native.TDS_NATIVE_DIAG_SAMPLING),
        "handle_contract": str(native.TDS_NATIVE_HANDLE_REF_CONTRACT),
        "frozen_contract": str(native.TDS_NATIVE_FROZEN_INDEX_CONTRACT),
        "packed_contract": str(native.TDS_NATIVE_PACKED_LOOKUP_CONTRACT),
        "module_init": str(native.TDS_NATIVE_MODULE_INIT),
        "multi_interpreter_policy": str(native.TDS_NATIVE_MULTI_INTERPRETER_POLICY),
        "gil_policy": str(native.TDS_NATIVE_GIL_POLICY),
        "reinitialization_policy": str(native.TDS_NATIVE_REINITIALIZATION_POLICY),
        "csv_abi": str(csv_native.CSV_NATIVE_SCAN_KERNEL_ABI),
        "csv_input_ownership": str(csv_native.CSV_NATIVE_SCAN_INPUT_OWNERSHIP),
    }

    checksum = checksum_fixture(native)
    utf8 = utf8_fixture(native)
    csv = csv_fixture(csv_native)
    stable_fixture = {"checksum": checksum, "utf8": utf8, "csv": csv}
    for _ in range(args.loops - 1):
        repeated = {
            "checksum": checksum_fixture(native),
            "utf8": utf8_fixture(native),
            "csv": csv_fixture(csv_native),
        }
        if repeated != stable_fixture:
            raise RuntimeError("repeated native semantic fixture drift")

    packed = packed_index_fixture(
        native,
        key_count=args.keys,
        workers=args.workers,
        iterations=args.iterations,
    )
    diagnostics = diagnostic_fixture(native)

    projection = {
        "format": FORMAT,
        "contracts": contracts,
        "stable_fixture": stable_fixture,
        "packed_index": packed,
        "diagnostics": diagnostics,
        "parameters": {
            "loops": args.loops,
            "keys": args.keys,
            "workers": args.workers,
            "iterations": args.iterations,
        },
    }
    root = semantic_root(projection)
    official_profile = (
        architecture == "aarch64"
        and args.loops == 256
        and args.keys == 8192
        and args.workers == 4
        and args.iterations == 128
    )
    expected_root = EXPECTED_SEMANTIC_ROOT if official_profile else ""
    root_matches_expected = not expected_root or root == expected_root
    report = {
        "format": FORMAT,
        "semantic_root": root,
        "expected_semantic_root": expected_root,
        "root_matches_expected": root_matches_expected,
        "semantic_projection": projection,
        "evidence": {
            "architecture": architecture,
            "machine": platform.machine(),
            "processor": platform.processor(),
            "platform": platform.platform(),
            "python": sys.version,
            "byteorder": sys.byteorder,
            "pointer_bits": calcsize("P") * 8,
            "logical_cpu_count": os.cpu_count(),
            "source_commit": source_commit(),
        },
        "functional_authority": False,
        "activation_authority": False,
        "passed": root_matches_expected,
    }
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0 if root_matches_expected else 2


if __name__ == "__main__":
    raise SystemExit(main())

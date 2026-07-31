#!/usr/bin/env python3
"""Direct-extension AArch64 portability probe for the v3.6 native engine.

This probe deliberately avoids importing the broad ``staqtapp_tds`` package.
It verifies one fresh process against the native index and CSV extension,
including their declared lifecycle, checksum, UTF-8, immutable snapshot,
packed lookup, diagnostics, and CSV contracts. The emitted record is
qualification evidence only and has no functional or activation authority.
"""
from __future__ import annotations

import argparse
import binascii
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
import sysconfig
from typing import Any, Iterable


FORMAT = "tds.v360.aarch64-version-probe.v1"
SEMANTIC_DOMAIN = b"TDS-V360-AARCH64-VERSION-PROBE-V1\0"
EXPECTED_ARCHITECTURE = "aarch64"


def canonical_architecture(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"arm64", "aarch64"}:
        return "aarch64"
    if normalized in {"amd64", "x86_64"}:
        return "x86_64"
    return normalized


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_root(value: Any) -> str:
    return hashlib.sha256(SEMANTIC_DOMAIN + canonical_json(value)).hexdigest()


def _source_commit() -> str:
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


def _extension_path(module_name: str) -> Path:
    package_dir = Path(__file__).resolve().parents[1] / "src" / "staqtapp_tds"
    candidates = []
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        candidates.extend(package_dir.glob(f"{module_name}*{suffix}"))
    resolved = sorted({path.resolve() for path in candidates if path.is_file()})
    if len(resolved) != 1:
        raise RuntimeError(
            f"expected one built {module_name} extension, found {resolved!r}"
        )
    return resolved[0]


def _load_extension(module_name: str, path: Path | None = None) -> Any:
    selected = _extension_path(module_name) if path is None else path
    spec = importlib.util.spec_from_file_location(module_name, selected)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to create extension spec for {selected}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fnv1a32(payload: bytes) -> int:
    value = 0x811C9DC5
    for byte in payload:
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value


def pack_keys(keys: Iterable[bytes]) -> tuple[bytes, bytes]:
    materialized = tuple(keys)
    blob = b"".join(materialized)
    offsets = [0]
    total = 0
    for key in materialized:
        total += len(key)
        offsets.append(total)
    return blob, b"".join(pack("<Q", value) for value in offsets)


def decode_handles(output: bytes | bytearray | memoryview) -> list[int]:
    view = memoryview(output).cast("B")
    return [
        unpack_from("<q", view, offset)[0]
        for offset in range(0, len(view), 8)
    ]


def _duplicate_import_fault(path: Path) -> dict[str, str]:
    try:
        _load_extension("_native_index", path)
    except ImportError as exc:
        message = str(exc)
        if "one process-lifetime module" not in message:
            raise
        return {"type": type(exc).__name__, "message": message}
    raise AssertionError("duplicate live native module import was accepted")


def build_report(expected_architecture: str) -> dict[str, Any]:
    architecture = canonical_architecture(platform.machine())
    if architecture != expected_architecture:
        raise RuntimeError(
            f"expected architecture {expected_architecture!r}, observed {architecture!r}"
        )
    if sys.byteorder != "little" or calcsize("P") * 8 != 64:
        raise RuntimeError("AArch64 qualification requires little-endian 64-bit execution")

    native_path = _extension_path("_native_index")
    csv_path = _extension_path("_csv_scan_kernel")
    native = _load_extension("_native_index", native_path)
    csv_native = _load_extension("_csv_scan_kernel", csv_path)

    payloads = (
        b"",
        b"123456789",
        "AArch64-β😀-TDS".encode("utf-8"),
        bytes(range(256)),
    )
    checksums = []
    for payload in payloads:
        crc = int(native.checksum32_for_algorithm(payload, "crc32-ieee-v1"))
        fnv = int(native.checksum32_for_algorithm(payload, "fnv1a32-legacy-v1"))
        expected_crc = binascii.crc32(payload) & 0xFFFFFFFF
        expected_fnv = _fnv1a32(payload)
        if (crc, fnv) != (expected_crc, expected_fnv):
            raise AssertionError("native checksum contract drift")
        checksums.append(
            {
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "crc32": crc,
                "fnv1a32": fnv,
            }
        )

    utf8_payload = "a😀bé𝄞日本語".encode("utf-8")
    utf8_bounds: dict[str, list[int]] = {}
    for chunk_size in (1, 2, 3, 4, 5, 7, 13, 64):
        bounds = [
            int(value)
            for value in native.utf8_chunk_bounds(utf8_payload, chunk_size)
        ]
        start = 0
        for end in bounds:
            if not start < end <= len(utf8_payload):
                raise AssertionError("invalid UTF-8 boundary ordering")
            utf8_payload[start:end].decode("utf-8", errors="strict")
            start = end
        if start != len(utf8_payload):
            raise AssertionError("UTF-8 boundaries did not cover the payload")
        utf8_bounds[str(chunk_size)] = bounds

    source = native.NativeHandleIndex(capacity=1024)
    keys = [f"arm-version-key-{value:04d}".encode("ascii") for value in range(512)]
    handles = [int(source.put(key)) for key in keys]
    for position in range(7, len(keys), 17):
        if int(source.pop(keys[position])) != handles[position]:
            raise AssertionError("unexpected handle removal")
        handles[position] = int(source.put(keys[position]))
    frozen = source.freeze()
    query = [keys[0], b"missing", keys[-1], keys[117], keys[255]]
    expected_handles = [handles[0], -1, handles[-1], handles[117], handles[255]]
    blob, offsets = pack_keys(query)
    output = bytearray(len(query) * 8)
    if int(frozen.lookup_packed(blob, offsets, output)) != len(query):
        raise AssertionError("packed lookup returned an incomplete count")
    if decode_handles(output) != expected_handles:
        raise AssertionError("packed lookup result drift")
    frozen_identity = frozen.identity()
    frozen_stats = frozen.stats()
    if frozen_stats["request_path_lock"] != "none":
        raise AssertionError("frozen request path unexpectedly reports a lock")
    if int(frozen_stats["shared_hot_path_state_writes"]) != 0:
        raise AssertionError("frozen request path reports shared state writes")

    native.diag_reset()
    native.diag_set_sampling(interval=1, burst=0)
    for value in range(16):
        if not native.diag_emit(10, value, value + 1):
            raise AssertionError("manual diagnostic event was not emitted")
    diagnostic = native.diag_snapshot(event_limit=64)
    events = list(diagnostic["recent_events"])
    counters = {
        str(key): int(value)
        for key, value in diagnostic["counters"].items()
    }
    sequences = [int(event["seq"]) for event in events]
    if sequences != sorted(set(sequences)):
        raise AssertionError("diagnostic event sequence drift")
    if counters["manual_event_attempts"] != 16:
        raise AssertionError("manual diagnostic events were not preserved")
    stable_events = [
        {
            "seq": int(event["seq"]),
            "code": int(event["code"]),
            "flags": int(event["flags"]),
            "subsystem": int(event["subsystem"]),
            "object_id": int(event["object_id"]),
            "value_a": int(event["value_a"]),
            "value_b": int(event["value_b"]),
        }
        for event in events
    ]

    csv_payload = (
        b'id,text\r\n1,"two\nlines"\r\n2,"quote ""inside"""\n'
        + "3,β😀\r".encode("utf-8")
    )
    scan = csv_native.scan_bytes(
        csv_payload,
        delimiter=ord(","),
        quote=ord('"'),
        escape=ord("\\"),
        doublequote=1,
        chunk_size=3,
    )
    rows = csv_native.row_offsets(
        csv_payload,
        quote=ord('"'),
        escape=ord("\\"),
        doublequote=1,
        chunk_size=3,
    )
    scan_offsets = [int(value) for value in scan["row_offsets"]]
    row_offsets = [int(value) for value in rows["row_offsets"]]
    if scan_offsets != row_offsets:
        raise AssertionError("CSV scan and row-offset contracts diverged")

    duplicate_fault = _duplicate_import_fault(native_path)

    projection = {
        "format": FORMAT,
        "contracts": {
            "native_abi": int(native.TDS_NATIVE_ABI_VERSION),
            "native_engine": str(native.TDS_NATIVE_ENGINE),
            "checksum_algorithms": str(native.TDS_NATIVE_CHECKSUM_ALGORITHMS),
            "utf8": str(native.TDS_NATIVE_UTF8_CHUNK_CONTRACT),
            "diagnostics": str(native.TDS_NATIVE_DIAG_PROTOCOL),
            "handle_reference": str(native.TDS_NATIVE_HANDLE_REF_CONTRACT),
            "frozen_index": str(native.TDS_NATIVE_FROZEN_INDEX_CONTRACT),
            "packed_lookup": str(native.TDS_NATIVE_PACKED_LOOKUP_CONTRACT),
            "module_init": str(native.TDS_NATIVE_MODULE_INIT),
            "multi_interpreter": str(native.TDS_NATIVE_MULTI_INTERPRETER_POLICY),
            "gil": str(native.TDS_NATIVE_GIL_POLICY),
            "reinitialization": str(native.TDS_NATIVE_REINITIALIZATION_POLICY),
            "csv_kernel_abi": str(csv_native.CSV_NATIVE_SCAN_KERNEL_ABI),
            "csv_input_ownership": str(csv_native.CSV_NATIVE_SCAN_INPUT_OWNERSHIP),
        },
        "checksums": checksums,
        "utf8_bounds": utf8_bounds,
        "frozen": {
            "capacity": int(frozen_identity["capacity"]),
            "size": int(frozen_identity["size"]),
            "lookup_sha256": hashlib.sha256(output).hexdigest(),
            "request_path_lock": str(frozen_stats["request_path_lock"]),
            "shared_hot_path_state_writes": int(
                frozen_stats["shared_hot_path_state_writes"]
            ),
        },
        "diagnostics": {
            "manual_event_attempts": counters["manual_event_attempts"],
            "events": stable_events,
        },
        "csv": {
            "raw_sha256": hashlib.sha256(csv_payload).hexdigest(),
            "row_offsets": scan_offsets,
            "row_count": int(scan["row_count"]),
            "quoted_newline_count": int(scan["quoted_newline_count"]),
            "escaped_quote_count": int(scan["escaped_quote_count"]),
        },
        "duplicate_import_fault": duplicate_fault,
    }
    return {
        "format": FORMAT,
        "semantic_root": semantic_root(projection),
        "semantic_projection": projection,
        "evidence": {
            "architecture": architecture,
            "machine": platform.machine(),
            "platform": platform.platform(),
            "byteorder": sys.byteorder,
            "pointer_bits": calcsize("P") * 8,
            "python": sys.version,
            "python_implementation": platform.python_implementation(),
            "python_compiler": platform.python_compiler(),
            "configured_cc": sysconfig.get_config_var("CC"),
            "native_extension": native_path.name,
            "csv_extension": csv_path.name,
            "source_commit": _source_commit(),
        },
        "functional_authority": False,
        "activation_authority": False,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-architecture", default=EXPECTED_ARCHITECTURE)
    parser.add_argument("--output", default="")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    expected = canonical_architecture(args.expected_architecture)
    report = build_report(expected)
    if args.compact:
        encoded = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
    else:
        encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

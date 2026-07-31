#!/usr/bin/env python3
"""Deterministic AArch64 hardening soak for the v3.6 native truth surfaces.

The tool loads the two compiled extensions directly and deliberately avoids the
broader package surface.  It emits qualification evidence only; it has no
functional, release, storage, semantic, policy, or activation authority.
"""
from __future__ import annotations

import argparse
import binascii
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import random
from struct import calcsize, pack, unpack_from
import subprocess
import sys
import sysconfig
from typing import Any, Callable, Iterable


FORMAT = "tds.v360.aarch64-hardening.v1"
SEMANTIC_DOMAIN = b"TDS-V360-AARCH64-HARDENING-V1\0"
EXPECTED_ARCHITECTURE = "aarch64"
DEFAULT_SEED = 3_606_401


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_root(projection: dict[str, Any]) -> str:
    return hashlib.sha256(SEMANTIC_DOMAIN + canonical_json(projection)).hexdigest()


def canonical_architecture(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"arm64", "aarch64"}:
        return "aarch64"
    if normalized in {"amd64", "x86_64"}:
        return "x86_64"
    return normalized


def _load_extension(module_name: str) -> Any:
    package_dir = Path(__file__).resolve().parents[1] / "src" / "staqtapp_tds"
    candidates: list[Path] = []
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        candidates.extend(package_dir.glob(f"{module_name}*{suffix}"))
    candidates = sorted({path.resolve() for path in candidates if path.is_file()})
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one built {module_name} extension, found {candidates!r}"
        )
    spec = importlib.util.spec_from_file_location(module_name, candidates[0])
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to create extension spec for {candidates[0]}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _normalized_error(call: Callable[[], Any]) -> dict[str, Any]:
    try:
        call()
    except Exception as exc:  # qualification records the exact public fault
        result: dict[str, Any] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        if isinstance(exc, UnicodeDecodeError):
            result.update(
                {
                    "encoding": exc.encoding,
                    "start": exc.start,
                    "end": exc.end,
                    "reason": exc.reason,
                }
            )
        return result
    raise AssertionError("expected operation to fail closed")


def _fnv1a32(payload: bytes) -> int:
    value = 0x811C9DC5
    for byte in payload:
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value


def _digest_update(digest: Any, *parts: bytes | str | int) -> None:
    for part in parts:
        if isinstance(part, int):
            encoded = part.to_bytes(8, "little", signed=True)
        elif isinstance(part, str):
            encoded = part.encode("utf-8")
        else:
            encoded = part
        digest.update(len(encoded).to_bytes(8, "little"))
        digest.update(encoded)


def _checksum_stress(native: Any, rng: random.Random, cases: int) -> dict[str, Any]:
    digest = hashlib.sha256()
    batch_payloads: list[bytes] = []
    maximum_length = 0
    for case in range(cases):
        length = rng.randrange(0, 2049)
        payload = rng.randbytes(length)
        maximum_length = max(maximum_length, length)
        expected_crc = binascii.crc32(payload) & 0xFFFFFFFF
        expected_fnv = _fnv1a32(payload)
        actual_crc = int(native.checksum32_for_algorithm(payload, "crc32-ieee-v1"))
        actual_fnv = int(
            native.checksum32_for_algorithm(payload, "fnv1a32-legacy-v1")
        )
        if (actual_crc, actual_fnv) != (expected_crc, expected_fnv):
            raise AssertionError(
                f"checksum drift at case {case}: "
                f"crc={actual_crc}/{expected_crc} fnv={actual_fnv}/{expected_fnv}"
            )
        _digest_update(
            digest,
            case,
            hashlib.sha256(payload).digest(),
            actual_crc,
            actual_fnv,
        )
        batch_payloads.append(payload)
        if len(batch_payloads) == 32 or case + 1 == cases:
            for algorithm, expected in (
                ("crc32-ieee-v1", [binascii.crc32(p) & 0xFFFFFFFF for p in batch_payloads]),
                ("fnv1a32-legacy-v1", [_fnv1a32(p) for p in batch_payloads]),
            ):
                actual = [
                    int(value)
                    for value in native.checksum32_many_for_algorithm(
                        batch_payloads,
                        algorithm,
                    )
                ]
                if actual != expected:
                    raise AssertionError(f"batch checksum drift for {algorithm}")
            batch_payloads.clear()
    return {
        "cases": cases,
        "maximum_payload_bytes": maximum_length,
        "case_digest": digest.hexdigest(),
    }


def _random_scalar(rng: random.Random) -> int:
    ranges = (
        (0x00, 0x7F),
        (0x80, 0x7FF),
        (0x800, 0xD7FF),
        (0xE000, 0xFFFF),
        (0x10000, 0x10FFFF),
    )
    lower, upper = ranges[rng.randrange(len(ranges))]
    return rng.randrange(lower, upper + 1)


def _utf8_stress(native: Any, rng: random.Random, cases: int) -> dict[str, Any]:
    digest = hashlib.sha256()
    maximum_payload = 0
    for case in range(cases):
        text = "".join(chr(_random_scalar(rng)) for _ in range(rng.randrange(0, 65)))
        payload = text.encode("utf-8")
        maximum_payload = max(maximum_payload, len(payload))
        requested = rng.randrange(1, 18)
        bounds = [int(value) for value in native.utf8_chunk_bounds(payload, requested)]
        if not payload:
            if bounds:
                raise AssertionError("empty UTF-8 payload produced boundaries")
        else:
            if not bounds or bounds[-1] != len(payload):
                raise AssertionError("UTF-8 bounds do not cover the payload")
            if bounds != sorted(set(bounds)):
                raise AssertionError("UTF-8 bounds are not strictly increasing")
            start = 0
            recovered: list[str] = []
            for end in bounds:
                if not (start < end <= len(payload)):
                    raise AssertionError("invalid UTF-8 boundary")
                recovered.append(payload[start:end].decode("utf-8", errors="strict"))
                start = end
            if "".join(recovered) != text:
                raise AssertionError("UTF-8 boundary reconstruction drift")
        _digest_update(
            digest,
            case,
            requested,
            hashlib.sha256(payload).digest(),
            b"".join(value.to_bytes(8, "little") for value in bounds),
        )

    invalid_payloads = (
        b"\x80",
        b"\xc0\x80",
        b"\xe0\x80\x80",
        b"\xed\xa0\x80",
        b"\xf4\x90\x80\x80",
        b"\xe2\x28\xa1",
        b"\xf0\x9f\x92",
    )
    invalid_faults = []
    for payload in invalid_payloads:
        fault = _normalized_error(lambda payload=payload: native.utf8_chunk_bounds(payload, 2))
        if fault["type"] != "UnicodeDecodeError":
            raise AssertionError(f"unexpected UTF-8 fault: {fault}")
        invalid_faults.append(fault)
    return {
        "valid_cases": cases,
        "invalid_cases": len(invalid_payloads),
        "maximum_payload_bytes": maximum_payload,
        "valid_case_digest": digest.hexdigest(),
        "invalid_faults": invalid_faults,
    }


def _csv_bytes(rng: random.Random, row_count: int) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(
        stream,
        delimiter=",",
        quotechar='"',
        escapechar="\\",
        doublequote=True,
        lineterminator="\r\n",
    )
    writer.writerow(["id", "text", "value"])
    atoms = (
        "plain",
        "comma,value",
        "quote \"inside\"",
        "two\nlines",
        "cr\rvalue",
        "β😀𝄞日本語",
        "",
    )
    for row in range(row_count):
        writer.writerow(
            [
                row,
                atoms[rng.randrange(len(atoms))],
                f"{rng.randrange(-(1 << 31), 1 << 31)}",
            ]
        )
    return stream.getvalue().encode("utf-8")


def _normalize_csv(mapping: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in sorted(mapping.items()):
        if isinstance(value, list):
            result[key] = [int(item) for item in value]
        elif isinstance(value, bool):
            result[key] = value
        else:
            result[key] = int(value)
    return result


def _csv_stress(csv_native: Any, rng: random.Random, cases: int) -> dict[str, Any]:
    digest = hashlib.sha256()
    maximum_bytes = 0
    maximum_rows = 0
    chunk_sizes = (0, 1, 2, 3, 5, 7, 13, 31, 127)
    for case in range(cases):
        rows = rng.randrange(0, 65)
        raw = _csv_bytes(rng, rows)
        maximum_bytes = max(maximum_bytes, len(raw))
        maximum_rows = max(maximum_rows, rows + 1)
        baseline_scan = _normalize_csv(
            csv_native.scan_bytes(
                raw,
                delimiter=ord(","),
                quote=ord('"'),
                escape=ord("\\"),
                doublequote=1,
                chunk_size=0,
            )
        )
        baseline_rows = _normalize_csv(
            csv_native.row_offsets(
                raw,
                quote=ord('"'),
                escape=ord("\\"),
                doublequote=1,
                chunk_size=0,
            )
        )
        if baseline_scan["row_offsets"] != baseline_rows["row_offsets"]:
            raise AssertionError("CSV scan/row-offset baseline drift")
        for chunk_size in chunk_sizes:
            scan = _normalize_csv(
                csv_native.scan_bytes(
                    raw,
                    delimiter=ord(","),
                    quote=ord('"'),
                    escape=ord("\\"),
                    doublequote=1,
                    chunk_size=chunk_size,
                )
            )
            row_view = _normalize_csv(
                csv_native.row_offsets(
                    raw,
                    quote=ord('"'),
                    escape=ord("\\"),
                    doublequote=1,
                    chunk_size=chunk_size,
                )
            )
            for key, expected in baseline_scan.items():
                if key != "chunk_count" and scan[key] != expected:
                    raise AssertionError(
                        f"CSV scan drift at case {case}, chunk={chunk_size}, key={key}"
                    )
            for key, expected in baseline_rows.items():
                if key != "chunk_count" and row_view[key] != expected:
                    raise AssertionError(
                        f"CSV row drift at case {case}, chunk={chunk_size}, key={key}"
                    )
        _digest_update(
            digest,
            case,
            hashlib.sha256(raw).digest(),
            canonical_json(baseline_scan),
            canonical_json(baseline_rows),
        )
    return {
        "cases": cases,
        "maximum_raw_bytes": maximum_bytes,
        "maximum_logical_rows": maximum_rows,
        "case_digest": digest.hexdigest(),
    }


def _pack_keys(keys: Iterable[bytes]) -> tuple[bytes, bytes]:
    materialized = tuple(keys)
    blob = b"".join(materialized)
    offsets = [0]
    total = 0
    for key in materialized:
        total += len(key)
        offsets.append(total)
    return blob, b"".join(pack("<Q", value) for value in offsets)


def _decode_handles(output: bytes | bytearray | memoryview) -> list[int]:
    view = memoryview(output).cast("B")
    return [
        unpack_from("<q", view, offset)[0]
        for offset in range(0, len(view), 8)
    ]


def _packed_stress(
    native: Any,
    rng: random.Random,
    cases: int,
    key_count: int,
) -> tuple[dict[str, Any], Any, list[bytes], list[int]]:
    mutable = native.NativeHandleIndex(capacity=max(16, key_count * 2))
    keys = [f"arm-key-{value:08d}".encode("ascii") for value in range(key_count)]
    expected = [int(mutable.put(key)) for key in keys]
    for position in range(5, key_count, 11):
        removed = int(mutable.pop(keys[position]))
        if removed != expected[position]:
            raise AssertionError("unexpected handle removed before freeze")
        expected[position] = int(mutable.put(keys[position]))
    frozen = mutable.freeze()
    digest = hashlib.sha256()

    for case in range(cases):
        count = rng.randrange(0, 65)
        query: list[bytes] = []
        wanted: list[int] = []
        for item in range(count):
            if rng.randrange(5):
                position = rng.randrange(key_count)
                query.append(keys[position])
                wanted.append(expected[position])
            else:
                missing = f"arm-missing-{case:06d}-{item:03d}".encode("ascii")
                query.append(missing)
                wanted.append(-1)
        blob, offsets = _pack_keys(query)
        output = bytearray(count * 8)
        processed = int(frozen.lookup_packed(blob, offsets, output))
        actual = _decode_handles(output)
        if processed != count or actual != wanted:
            raise AssertionError(f"packed lookup drift at case {case}")
        _digest_update(
            digest,
            case,
            hashlib.sha256(blob).digest(),
            hashlib.sha256(offsets).digest(),
            hashlib.sha256(output).digest(),
        )

        sentinel = bytearray([0xA5]) * (count * 8)
        before = bytes(sentinel)
        mode = case % 5
        if mode == 0:
            malformed = b""
        elif mode == 1:
            malformed = pack("<Q", 1) + offsets[8:]
        elif mode == 2 and count >= 2:
            values = [
                unpack_from("<Q", offsets, offset)[0]
                for offset in range(0, len(offsets), 8)
            ]
            values[1] = min(len(blob), values[1] + 1)
            values[2] = 0
            malformed = b"".join(pack("<Q", value) for value in values)
        elif mode == 3:
            values = [
                unpack_from("<Q", offsets, offset)[0]
                for offset in range(0, len(offsets), 8)
            ]
            values[-1] = len(blob) + 1
            malformed = b"".join(pack("<Q", value) for value in values)
        else:
            malformed = offsets + b"\x00"
        try:
            frozen.lookup_packed(blob, malformed, sentinel)
        except ValueError:
            pass
        else:
            raise AssertionError(f"malformed packed offsets accepted at case {case}")
        if bytes(sentinel) != before:
            raise AssertionError("malformed packed request changed caller output")

    identity = frozen.identity()
    stats = frozen.stats()
    if stats["request_path_lock"] != "none":
        raise AssertionError("frozen request path unexpectedly reports a lock")
    if int(stats["shared_hot_path_state_writes"]) != 0:
        raise AssertionError("frozen request path reports shared state writes")
    return (
        {
            "valid_cases": cases,
            "malformed_cases": cases,
            "key_count": key_count,
            "case_digest": digest.hexdigest(),
            "frozen_contract": str(identity["frozen_index_contract"]),
            "packed_contract": str(identity["packed_lookup_contract"]),
            "request_path_lock": str(stats["request_path_lock"]),
            "shared_hot_path_state_writes": int(
                stats["shared_hot_path_state_writes"]
            ),
        },
        mutable,
        keys,
        expected,
    )


def _concurrency_stress(
    frozen: Any,
    mutable: Any,
    keys: list[bytes],
    expected: list[int],
    workers: int,
    iterations: int,
) -> dict[str, Any]:
    blob, offsets = _pack_keys(keys)
    expected_tuple = tuple(expected)

    def reader() -> str:
        output = bytearray(len(keys) * 8)
        for _ in range(iterations):
            processed = int(frozen.lookup_packed(blob, offsets, output))
            if processed != len(keys):
                raise AssertionError("concurrent frozen lookup was incomplete")
        if tuple(_decode_handles(output)) != expected_tuple:
            raise AssertionError("concurrent frozen lookup changed its snapshot")
        return hashlib.sha256(output).hexdigest()

    def writer() -> int:
        mutations = 0
        for iteration in range(iterations):
            key = f"arm-live-{iteration:08d}".encode("ascii")
            mutable.put(key)
            mutations += 1
            if iteration % 3 == 0:
                mutable.pop(key)
                mutations += 1
        return mutations

    with ThreadPoolExecutor(max_workers=workers + 1) as executor:
        reader_futures = [executor.submit(reader) for _ in range(workers)]
        writer_future = executor.submit(writer)
        digests = [future.result() for future in reader_futures]
        mutations = int(writer_future.result())
    if len(set(digests)) != 1:
        raise AssertionError("concurrent frozen readers produced different bytes")
    if frozen.get_handle(b"arm-live-00000000") != -1:
        raise AssertionError("frozen snapshot observed later mutable-index content")
    return {
        "workers": workers,
        "iterations_per_reader": iterations,
        "lookups": workers * iterations * len(keys),
        "source_mutations": mutations,
        "output_digest": digests[0],
    }


def _diagnostic_stress(native: Any, workers: int, iterations: int) -> dict[str, Any]:
    native.diag_reset()
    native.diag_set_sampling(interval=32, burst=8)
    index = native.NativeHandleIndex(capacity=512)
    keys = [f"diag-arm-{value:04d}".encode("ascii") for value in range(256)]
    handles = [int(index.put(key)) for key in keys]

    def worker(offset: int) -> None:
        for _ in range(iterations):
            for position in range(offset, len(keys), workers):
                if int(index.get_handle(keys[position])) != handles[position]:
                    raise AssertionError("diagnostic lookup drift")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, offset) for offset in range(workers)]
        for _ in range(8):
            native.diag_reset()
            native.diag_set_sampling(interval=32, burst=8)
        for future in futures:
            future.result()

    for value in range(16):
        native.diag_emit(10, value, value + 1)
    snapshot = native.diag_snapshot(event_limit=4096)
    counters = {str(key): int(value) for key, value in snapshot["counters"].items()}
    events = list(snapshot["recent_events"])
    sequences = [int(event["seq"]) for event in events]
    if sequences != sorted(set(sequences)):
        raise AssertionError("diagnostic event sequences are not stable and unique")
    if counters["active_event_writers"] != 0 or counters["resetting"] != 0:
        raise AssertionError("diagnostic writers or reset remained active")
    if counters["manual_event_attempts"] != 16:
        raise AssertionError("manual diagnostic events were not preserved")
    stable_event_digest = hashlib.sha256()
    for event in events:
        _digest_update(
            stable_event_digest,
            int(event["seq"]),
            int(event["code"]),
            int(event["flags"]),
            int(event["subsystem"]),
            int(event["object_id"]),
            int(event["value_a"]),
            int(event["value_b"]),
        )
    return {
        "workers": workers,
        "iterations": iterations,
        "event_count": len(events),
        "event_digest_without_timestamps": stable_event_digest.hexdigest(),
        "counters": counters,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    architecture = canonical_architecture(platform.machine())
    if architecture != args.expected_architecture:
        raise RuntimeError(
            f"expected architecture {args.expected_architecture}, observed {architecture}"
        )
    if sys.byteorder != "little" or calcsize("P") * 8 != 64:
        raise RuntimeError("AArch64 qualification requires little-endian 64-bit execution")

    native = _load_extension("_native_index")
    csv_native = _load_extension("_csv_scan_kernel")
    rng = random.Random(args.seed)

    packed, mutable, keys, expected = _packed_stress(
        native,
        rng,
        args.packed_cases,
        args.keys,
    )
    projection = {
        "format": FORMAT,
        "seed": args.seed,
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
        "checksums": _checksum_stress(native, rng, args.checksum_cases),
        "utf8": _utf8_stress(native, rng, args.utf8_cases),
        "csv": _csv_stress(csv_native, rng, args.csv_cases),
        "packed_index": packed,
    }
    report = {
        "format": FORMAT,
        "semantic_root": semantic_root(projection),
        "semantic_projection": projection,
        "stress_evidence": {
            "concurrency": _concurrency_stress(
                mutable.freeze(),
                mutable,
                keys,
                [int(mutable.get_handle(key)) for key in keys],
                args.workers,
                args.iterations,
            ),
            "diagnostics": _diagnostic_stress(
                native,
                args.workers,
                max(4, args.iterations // 4),
            ),
        },
        "evidence": {
            "architecture": architecture,
            "machine": platform.machine(),
            "platform": platform.platform(),
            "byteorder": sys.byteorder,
            "pointer_bits": calcsize("P") * 8,
            "python": sys.version,
            "compiler": platform.python_compiler(),
            "configured_cc": sysconfig.get_config_var("CC"),
            "source_commit": _source_commit(),
        },
        "functional_authority": False,
        "activation_authority": False,
        "passed": True,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-architecture", default=EXPECTED_ARCHITECTURE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--checksum-cases", type=int, default=2_000)
    parser.add_argument("--utf8-cases", type=int, default=1_000)
    parser.add_argument("--csv-cases", type=int, default=256)
    parser.add_argument("--packed-cases", type=int, default=2_000)
    parser.add_argument("--keys", type=int, default=4_096)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--iterations", type=int, default=128)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    args.expected_architecture = canonical_architecture(args.expected_architecture)
    positive = (
        "checksum_cases",
        "utf8_cases",
        "csv_cases",
        "packed_cases",
        "keys",
        "workers",
        "iterations",
    )
    for name in positive:
        if int(getattr(args, name)) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")

    report = build_report(args)
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

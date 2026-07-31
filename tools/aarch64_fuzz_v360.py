#!/usr/bin/env python3
"""Deterministically fuzz bounded native formats on an AArch64 runner.

The harness directly loads the compiled C extensions. It exercises valid and
malformed packed lookups, checksum scalar/batch parity, strict UTF-8 boundaries,
and CSV chunk-shape invariance without importing the broader TDS package.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
from struct import calcsize, pack, unpack_from
import subprocess
import sys
from typing import Any


FORMAT = "tds.v360.aarch64-native-fuzz.v1"


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
    spec = importlib.util.spec_from_file_location(module_name, candidates[0])
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {candidates[0]}")
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


def pack_keys(keys: list[bytes]) -> tuple[bytes, bytes]:
    blob = b"".join(keys)
    offsets = [0]
    for key in keys:
        offsets.append(offsets[-1] + len(key))
    return blob, b"".join(pack("<Q", value) for value in offsets)


def decode_handles(output: bytearray) -> list[int]:
    return [
        int(unpack_from("<q", output, offset)[0])
        for offset in range(0, len(output), 8)
    ]


def malformed_offsets(
    offsets: bytes,
    blob_size: int,
    count: int,
    mode: int,
) -> bytes:
    if mode == 0:
        return b""
    if mode == 1:
        return pack("<Q", 1) + offsets[8:]
    if mode == 2:
        return offsets[:-1]
    values = [
        int(unpack_from("<Q", offsets, offset)[0])
        for offset in range(0, len(offsets), 8)
    ]
    if mode == 3:
        values[-1] = blob_size + 1
        return b"".join(pack("<Q", value) for value in values)
    if count >= 2:
        values[1] = min(blob_size, values[1] + 1)
        values[2] = max(0, values[1] - 1)
        return b"".join(pack("<Q", value) for value in values)
    return offsets + b"\x00"


def semantic_csv(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in mapping.items()
        if str(key) != "chunk_count"
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-architecture", default="aarch64")
    parser.add_argument("--seed", type=int, default=36018)
    parser.add_argument("--cases", type=int, default=10_000)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.cases <= 0:
        parser.error("cases must be positive")

    architecture = canonical_architecture(platform.machine())
    expected_architecture = canonical_architecture(args.expected_architecture)
    if architecture != expected_architecture:
        raise SystemExit(
            f"architecture mismatch: observed {architecture!r}, expected {expected_architecture!r}"
        )
    if sys.byteorder != "little" or calcsize("P") != 8:
        raise SystemExit("fuzz qualification requires little-endian 64-bit execution")

    native = load_extension("_native_index")
    csv_native = load_extension("_csv_scan_kernel")
    rng = random.Random(args.seed)

    mutable = native.NativeHandleIndex(capacity=2048)
    corpus = [f"known-{value:04d}".encode("ascii") for value in range(512)]
    expected = {key: int(mutable.put(key)) for key in corpus}
    frozen = mutable.freeze()

    packed_digest = hashlib.sha256()
    checksum_digest = hashlib.sha256()
    utf8_digest = hashlib.sha256()
    csv_digest = hashlib.sha256()
    malformed_rejections = 0
    utf8_faults = 0

    scalar_tokens = (
        "a",
        "β",
        "😀",
        "𝄞",
        "日",
        "\u007f",
        "\u0080",
        "\u07ff",
        "\u0800",
        "\uffff",
        "\U00010000",
        "\U0010ffff",
    )
    invalid_utf8 = (
        b"\xc0\x80",
        b"\x80",
        b"\xe2\x28\xa1",
        b"\xe0\x80\x80",
        b"\xed\xa0\x80",
        b"\xf4\x90\x80\x80",
        b"\xf0\x9f\x92",
    )

    for case in range(args.cases):
        count = rng.randrange(0, 65)
        keys: list[bytes] = []
        wanted: list[int] = []
        for _ in range(count):
            if rng.randrange(4) != 0:
                key = corpus[rng.randrange(len(corpus))]
            else:
                key = f"missing-{case:05d}-{rng.randrange(1 << 24):06x}".encode(
                    "ascii"
                )
            keys.append(key)
            wanted.append(expected.get(key, -1))
        blob, offsets = pack_keys(keys)
        output = bytearray(count * 8)
        processed = int(frozen.lookup_packed(blob, offsets, output))
        if processed != count or decode_handles(output) != wanted:
            raise RuntimeError(f"valid packed lookup drift at case {case}")
        packed_digest.update(output)

        sentinel = bytearray([0xA5]) * (count * 8)
        before = bytes(sentinel)
        malformed = malformed_offsets(
            offsets,
            len(blob),
            count,
            case % 5,
        )
        try:
            frozen.lookup_packed(blob, malformed, sentinel)
        except (BufferError, TypeError, ValueError):
            malformed_rejections += 1
        else:
            raise RuntimeError(f"malformed packed offsets accepted at case {case}")
        if bytes(sentinel) != before:
            raise RuntimeError(f"malformed packed input mutated output at case {case}")

        payload = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 257)))
        for algorithm in ("crc32-ieee-v1", "fnv1a32-legacy-v1"):
            scalar = int(native.checksum32_for_algorithm(payload, algorithm))
            batch = int(
                native.checksum32_many_for_algorithm([payload], algorithm)[0]
            )
            if scalar != batch:
                raise RuntimeError(
                    f"checksum scalar/batch drift at case {case} for {algorithm}"
                )
            checksum_digest.update(algorithm.encode("ascii"))
            checksum_digest.update(pack("<I", scalar))

        text = "".join(
            scalar_tokens[rng.randrange(len(scalar_tokens))]
            for _ in range(rng.randrange(0, 25))
        )
        encoded = text.encode("utf-8")
        chunk_size = rng.randrange(1, 18)
        bounds = [
            int(value) for value in native.utf8_chunk_bounds(encoded, chunk_size)
        ]
        previous = 0
        for boundary in bounds:
            encoded[previous:boundary].decode("utf-8", errors="strict")
            previous = boundary
        if previous != len(encoded):
            raise RuntimeError(f"UTF-8 coverage drift at case {case}")
        utf8_digest.update(encoded)
        utf8_digest.update(b"".join(pack("<Q", value) for value in bounds))

        malformed_utf8 = invalid_utf8[case % len(invalid_utf8)]
        try:
            native.utf8_chunk_bounds(malformed_utf8, chunk_size)
        except UnicodeDecodeError:
            utf8_faults += 1
        else:
            raise RuntimeError(f"invalid UTF-8 accepted at case {case}")

        text_field = f"value-{case},β😀"
        if case % 3 == 0:
            text_field += "\nline"
        if case % 5 == 0:
            text_field += ' "quoted"'
        escaped_field = text_field.replace('"', '""')
        raw = (
            "id,text\r\n"
            + str(case)
            + ',"'
            + escaped_field
            + '"\r\n'
        ).encode("utf-8")
        random_chunk = rng.randrange(1, max(2, len(raw) + 1))
        scan_zero = csv_native.scan_bytes(
            raw,
            delimiter=ord(","),
            quote=ord('"'),
            escape=ord("\\"),
            doublequote=1,
            chunk_size=0,
        )
        scan_chunked = csv_native.scan_bytes(
            raw,
            delimiter=ord(","),
            quote=ord('"'),
            escape=ord("\\"),
            doublequote=1,
            chunk_size=random_chunk,
        )
        rows_zero = csv_native.row_offsets(
            raw,
            quote=ord('"'),
            escape=ord("\\"),
            doublequote=1,
            chunk_size=0,
        )
        rows_chunked = csv_native.row_offsets(
            raw,
            quote=ord('"'),
            escape=ord("\\"),
            doublequote=1,
            chunk_size=random_chunk,
        )
        if semantic_csv(scan_zero) != semantic_csv(scan_chunked):
            raise RuntimeError(f"CSV scan semantic drift at case {case}")
        if semantic_csv(rows_zero) != semantic_csv(rows_chunked):
            raise RuntimeError(f"CSV row-offset semantic drift at case {case}")
        csv_digest.update(raw)
        for value in rows_zero["row_offsets"]:
            csv_digest.update(pack("<Q", int(value)))

    evidence = {
        "format": FORMAT,
        "architecture": architecture,
        "machine": platform.machine(),
        "python": sys.version,
        "source_commit": source_commit(),
        "seed": args.seed,
        "cases": args.cases,
        "valid_packed_cases": args.cases,
        "malformed_packed_rejections": malformed_rejections,
        "utf8_fault_rejections": utf8_faults,
        "packed_result_sha256": packed_digest.hexdigest(),
        "checksum_result_sha256": checksum_digest.hexdigest(),
        "utf8_result_sha256": utf8_digest.hexdigest(),
        "csv_result_sha256": csv_digest.hexdigest(),
        "functional_authority": False,
        "activation_authority": False,
        "passed": True,
    }
    encoded_evidence = json.dumps(evidence, sort_keys=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(
            encoded_evidence,
            encoding="utf-8",
            newline="\n",
        )
    print(encoded_evidence, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

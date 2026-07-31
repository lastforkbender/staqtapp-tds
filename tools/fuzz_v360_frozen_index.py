#!/usr/bin/env python3
"""Deterministic format fuzzing for the frozen packed-index ABI."""
from __future__ import annotations

import argparse
import json
import random
from struct import pack, unpack_from


def pack_keys(keys: list[bytes]) -> tuple[bytes, bytes]:
    blob = b"".join(keys)
    offsets = [0]
    for key in keys:
        offsets.append(offsets[-1] + len(key))
    return blob, b"".join(pack("<Q", value) for value in offsets)


def decode(output: bytearray) -> list[int]:
    return [
        unpack_from("<q", output, offset)[0]
        for offset in range(0, len(output), 8)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=36015)
    parser.add_argument("--cases", type=int, default=5000)
    args = parser.parse_args()
    if args.cases <= 0:
        parser.error("cases must be positive")

    from staqtapp_tds import _native_index

    rng = random.Random(args.seed)
    mutable = _native_index.NativeHandleIndex(capacity=2048)
    corpus = [f"known-{value:04d}".encode("ascii") for value in range(512)]
    expected = {key: int(mutable.put(key)) for key in corpus}
    frozen = mutable.freeze()
    valid_cases = 0
    malformed_cases = 0

    for case in range(args.cases):
        count = rng.randrange(0, 65)
        keys: list[bytes] = []
        wanted: list[int] = []
        for _ in range(count):
            if rng.randrange(4) != 0:
                key = corpus[rng.randrange(len(corpus))]
            else:
                key = f"missing-{case:05d}-{rng.randrange(1 << 20):06x}".encode(
                    "ascii"
                )
            keys.append(key)
            wanted.append(expected.get(key, -1))
        blob, offsets = pack_keys(keys)
        output = bytearray(count * 8)
        processed = int(frozen.lookup_packed(blob, offsets, output))
        if processed != count or decode(output) != wanted:
            raise RuntimeError(
                f"valid packed parity failure at case {case}: "
                f"processed={processed}, count={count}"
            )
        valid_cases += 1

        # Exercise one malformed representation and require failure before any
        # caller-owned output byte is modified.
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
            values[2] = values[0]
            values[1] = min(len(blob), values[1] + 1)
            if values[2] >= values[1]:
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
            raise RuntimeError(f"malformed offsets accepted at case {case}")
        if bytes(sentinel) != before:
            raise RuntimeError(f"malformed case mutated output at case {case}")
        malformed_cases += 1

    evidence = {
        "format": "tds.v360.frozen-packed-index.fuzz.v1",
        "seed": args.seed,
        "cases": args.cases,
        "valid_cases": valid_cases,
        "malformed_cases": malformed_cases,
        "functional_authority": False,
        "activation_authority": False,
        "passed": True,
    }
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

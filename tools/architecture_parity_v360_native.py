#!/usr/bin/env python3
"""Produce deterministic x86-64/AArch64 semantic evidence for TDS native truth.

The projection intentionally excludes process-local namespace/snapshot identities,
wall-clock data, filesystem paths, and performance.  It binds only native contracts
and observable byte/integer/floating-point semantics that must agree across supported
architectures.
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
from struct import calcsize, pack, unpack_from
import subprocess
import sys
import sysconfig
from typing import Any, Callable, Iterable

FORMAT = "tds.v360.native-architecture-parity.v1"
SEMANTIC_DOMAIN = b"TDS-V360-NATIVE-ARCHITECTURE-PARITY-V1\0"
EXPECTED_SEMANTIC_ROOT = (
    "d2e839477d432cdf9e328982e6e9a245295dd05c80ddac4937232c0b72bc9d09"
)


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
    if normalized in {"x86_64", "amd64"}:
        return "x86_64"
    if normalized in {"aarch64", "arm64"}:
        return "aarch64"
    return normalized


def _load_extension(module_name: str) -> Any:
    """Load one in-tree extension without importing the package surface.

    ARM qualification must not depend on optional GUI, NumPy, or application
    imports.  The extension-only loader also prevents unrelated package startup
    behavior from entering the semantic parity root.
    """
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
    except Exception as exc:  # qualification intentionally records exact public fault
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


def _float64_bits(value: float) -> str:
    return pack(">d", float(value)).hex()


def _contract_projection(native: Any, csv_native: Any) -> dict[str, Any]:
    return {
        "native_abi_version": int(native.TDS_NATIVE_ABI_VERSION),
        "native_engine": str(native.TDS_NATIVE_ENGINE),
        "native_capabilities": sorted(
            item for item in str(native.TDS_NATIVE_CAPABILITIES).split(",") if item
        ),
        "checksum_algorithms": sorted(
            item
            for item in str(native.TDS_NATIVE_CHECKSUM_ALGORITHMS).split(",")
            if item
        ),
        "utf8_chunk_contract": str(native.TDS_NATIVE_UTF8_CHUNK_CONTRACT),
        "diagnostic_protocol": str(native.TDS_NATIVE_DIAG_PROTOCOL),
        "diagnostic_sampling": str(native.TDS_NATIVE_DIAG_SAMPLING),
        "handle_reference_contract": str(native.TDS_NATIVE_HANDLE_REF_CONTRACT),
        "frozen_index_contract": str(native.TDS_NATIVE_FROZEN_INDEX_CONTRACT),
        "packed_lookup_contract": str(native.TDS_NATIVE_PACKED_LOOKUP_CONTRACT),
        "packed_lookup_max_keys": int(native.TDS_NATIVE_PACKED_LOOKUP_MAX_KEYS),
        "module_init": str(native.TDS_NATIVE_MODULE_INIT),
        "multi_interpreter_policy": str(
            native.TDS_NATIVE_MULTI_INTERPRETER_POLICY
        ),
        "gil_policy": str(native.TDS_NATIVE_GIL_POLICY),
        "reinitialization_policy": str(native.TDS_NATIVE_REINITIALIZATION_POLICY),
        "csv_scan_kernel_abi": str(csv_native.CSV_NATIVE_SCAN_KERNEL_ABI),
        "csv_scan_kernel_backend": str(csv_native.CSV_NATIVE_SCAN_KERNEL_BACKEND),
        "csv_scan_input_ownership": str(csv_native.CSV_NATIVE_SCAN_INPUT_OWNERSHIP),
    }


def _checksum_projection(native: Any) -> dict[str, Any]:
    payloads = [
        ("empty", b""),
        ("check-vector", b"123456789"),
        ("ascii", b"frontier-native-truth"),
        ("utf8", "β😀𝄞日本語".encode("utf-8")),
        ("all-bytes", bytes(range(256))),
    ]
    algorithms = ("crc32-ieee-v1", "fnv1a32-legacy-v1")
    projection: dict[str, Any] = {
        "payloads": [
            {"id": name, "hex": payload.hex()} for name, payload in payloads
        ],
        "algorithms": {},
    }
    raw_payloads = [payload for _name, payload in payloads]
    for algorithm in algorithms:
        scalar = [
            int(native.checksum32_for_algorithm(payload, algorithm))
            for payload in raw_payloads
        ]
        batch = [
            int(value)
            for value in native.checksum32_many_for_algorithm(
                raw_payloads,
                algorithm,
            )
        ]
        if scalar != batch:
            raise AssertionError(f"native checksum scalar/batch drift for {algorithm}")
        projection["algorithms"][algorithm] = scalar
    if projection["algorithms"]["crc32-ieee-v1"][1] != 0xCBF43926:
        raise AssertionError("CRC32 IEEE check vector drift")
    if projection["algorithms"]["fnv1a32-legacy-v1"][2] != 0x0EE933F4:
        # This value is pinned to the exact ASCII fixture above, not a published
        # universal FNV check vector.
        raise AssertionError("FNV-1a fixture drift")
    return projection


def _utf8_projection(native: Any) -> dict[str, Any]:
    valid_payloads = [
        ("empty", b""),
        ("mixed", "a😀bé𝄞日本語".encode("utf-8")),
        (
            "boundary-scalars",
            "A\u007f\u0080\u07ff\u0800\uffff\U00010000\U0010ffffZ".encode(
                "utf-8"
            ),
        ),
    ]
    chunk_sizes = (1, 2, 3, 4, 5, 7, 13, 64)
    valid = []
    for name, payload in valid_payloads:
        valid.append(
            {
                "id": name,
                "hex": payload.hex(),
                "bounds": {
                    str(size): [
                        int(value)
                        for value in native.utf8_chunk_bounds(payload, size)
                    ]
                    for size in chunk_sizes
                },
            }
        )

    invalid_payloads = [
        ("invalid-start-overlong", b"\xc0\x80"),
        ("bare-continuation", b"\x80"),
        ("invalid-continuation", b"\xe2\x28\xa1"),
        ("overlong-three-byte", b"\xe0\x80\x80"),
        ("surrogate", b"\xed\xa0\x80"),
        ("above-unicode", b"\xf4\x90\x80\x80"),
        ("truncated", b"\xf0\x9f\x92"),
    ]
    invalid = [
        {
            "id": name,
            "hex": payload.hex(),
            "fault": _normalized_error(
                lambda payload=payload: native.utf8_chunk_bounds(payload, 2)
            ),
        }
        for name, payload in invalid_payloads
    ]
    return {"valid": valid, "invalid": invalid}


def _normalize_csv_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        key: [int(item) for item in value]
        if key in {"row_offsets", "row_spans"}
        else bool(value)
        if key in {"terminal_newline", "ended_in_open_quote"}
        else int(value)
        for key, value in sorted(mapping.items())
    }


def _csv_projection(csv_native: Any) -> dict[str, Any]:
    cases = [
        ("empty", b""),
        (
            "quoted-crlf-utf8",
            b'id,text\r\n1,"two\nlines"\r\n2,"quote ""inside"""\n'
            + "3,β😀\r".encode("utf-8"),
        ),
        ("escape-and-cr", b"a,b\r1,one\\,two\r2,three\n"),
    ]
    chunk_sizes = (0, 1, 2, 3, 7, 31)
    result = []
    for name, raw in cases:
        variants = []
        for chunk_size in chunk_sizes:
            scan = _normalize_csv_mapping(
                csv_native.scan_bytes(
                    raw,
                    delimiter=ord(","),
                    quote=ord('"'),
                    escape=ord("\\"),
                    doublequote=1,
                    chunk_size=chunk_size,
                )
            )
            rows = _normalize_csv_mapping(
                csv_native.row_offsets(
                    raw,
                    quote=ord('"'),
                    escape=ord("\\"),
                    doublequote=1,
                    chunk_size=chunk_size,
                )
            )
            if scan["row_offsets"] != rows["row_offsets"]:
                raise AssertionError("CSV scan/row-offset native drift")
            row_hashes = []
            for start, span in zip(
                rows["row_offsets"],
                rows["row_spans"],
                strict=True,
            ):
                row_hashes.append(hashlib.sha256(raw[start : start + span]).hexdigest())
            variants.append(
                {
                    "chunk_size": chunk_size,
                    "scan": scan,
                    "rows": rows,
                    "row_sha256": row_hashes,
                }
            )
        result.append(
            {
                "id": name,
                "raw_hex": raw.hex(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "variants": variants,
            }
        )
    return {"cases": result}


def _handle_projection(native: Any) -> dict[str, Any]:
    index = native.NativeHandleIndex(capacity=16)
    other = native.NativeHandleIndex(capacity=16)
    namespace, initial_epoch = (int(value) for value in index.identity())
    other_namespace, other_epoch = (int(value) for value in other.identity())

    alpha = int(index.put(b"alpha"))
    explicit = int(index.put(b"explicit", 10))
    after_explicit = int(index.put(b"after-explicit"))
    alpha_ref = tuple(int(value) for value in index.get_handle_ref(b"alpha"))
    cross_index = int(other.resolve_handle_ref(*alpha_ref))
    forged_generation = list(alpha_ref)
    forged_generation[3] += 1
    forged_generation_result = int(index.resolve_handle_ref(*forged_generation))

    removed = int(index.pop(b"alpha"))
    stale_after_delete = int(index.resolve_handle_ref(*alpha_ref))
    alpha_reinserted = int(index.put(b"alpha"))
    alpha_ref_2 = tuple(int(value) for value in index.get_handle_ref(b"alpha"))

    pre_resize_ref = tuple(
        int(value) for value in index.get_handle_ref(b"explicit")
    )
    pre_resize_epoch = int(index.identity()[1])
    added = 0
    while int(index.identity()[1]) == pre_resize_epoch:
        index.put(f"grow-{added:03d}".encode("ascii"))
        added += 1
        if added > 256:
            raise AssertionError("native index did not resize within bounded fixture")
    post_resize_epoch = int(index.identity()[1])
    stale_after_resize = int(index.resolve_handle_ref(*pre_resize_ref))
    refreshed_ref = tuple(
        int(value) for value in index.get_handle_ref(b"explicit")
    )
    refreshed_result = int(index.resolve_handle_ref(*refreshed_ref))

    collision_fault = _normalized_error(lambda: index.put(b"collision", 10))

    exhausted = native.NativeHandleIndex(capacity=16)
    maximum = (1 << 63) - 1
    maximum_insert = int(exhausted.put(b"maximum", maximum))
    exhaustion_fault = _normalized_error(lambda: exhausted.put(b"overflow"))

    return {
        "identity": {
            "namespace_positive": namespace > 0,
            "other_namespace_positive": other_namespace > 0,
            "namespaces_unique": namespace != other_namespace,
            "initial_epoch": initial_epoch,
            "other_initial_epoch": other_epoch,
        },
        "handles": {
            "alpha": alpha,
            "explicit": explicit,
            "after_explicit": after_explicit,
            "removed": removed,
            "alpha_reinserted": alpha_reinserted,
            "maximum_insert": maximum_insert,
            "exhausted_next_handle": int(exhausted.stats()["next_handle"]),
        },
        "reference_validation": {
            "initial_generation": alpha_ref[3],
            "reinserted_generation": alpha_ref_2[3],
            "slot_reused": alpha_ref[2] == alpha_ref_2[2],
            "generation_advanced": alpha_ref_2[3] > alpha_ref[3],
            "cross_index_result": cross_index,
            "forged_generation_result": forged_generation_result,
            "stale_after_delete": stale_after_delete,
            "stale_after_resize": stale_after_resize,
            "refreshed_result": refreshed_result,
            "refreshed_epoch": refreshed_ref[1],
        },
        "resize": {
            "before_epoch": pre_resize_epoch,
            "after_epoch": post_resize_epoch,
            "keys_added_to_trigger": added,
            "epoch_advanced_once": post_resize_epoch == pre_resize_epoch + 1,
        },
        "faults": {
            "collision": collision_fault,
            "exhaustion": exhaustion_fault,
        },
    }


def _pack_keys(keys: Iterable[bytes]) -> tuple[bytes, bytes]:
    key_list = list(keys)
    blob = b"".join(key_list)
    offsets = [0]
    for key in key_list:
        offsets.append(offsets[-1] + len(key))
    return blob, b"".join(pack("<Q", value) for value in offsets)


def _decode_handles(payload: bytes | bytearray) -> list[int]:
    return [
        int(unpack_from("<q", payload, offset)[0])
        for offset in range(0, len(payload), 8)
    ]


def _frozen_projection(native: Any) -> dict[str, Any]:
    source = native.NativeHandleIndex(capacity=64)
    inserted = {
        f"key-{value:02d}".encode("ascii"): int(
            source.put(f"key-{value:02d}".encode("ascii"))
        )
        for value in range(12)
    }
    removed_key = b"key-03"
    removed_handle = int(source.pop(removed_key))
    frozen = source.freeze()
    identity = dict(frozen.identity())
    stats = dict(frozen.stats())

    query = [b"key-00", removed_key, b"missing", b"key-11"]
    blob, offsets = _pack_keys(query)
    output = bytearray(len(query) * 8)
    processed = int(frozen.lookup_packed(blob, offsets, output))
    decoded = _decode_handles(output)

    malformed_output = bytearray(b"\xa5" * 16)
    malformed_before = bytes(malformed_output)
    malformed_fault = _normalized_error(
        lambda: frozen.lookup_packed(
            b"abc",
            pack("<QQQ", 0, 3, 2),
            malformed_output,
        )
    )

    source.put(b"post-freeze")
    source.pop(b"key-00")

    return {
        "source": {
            "inserted_handles": [inserted[key] for key in sorted(inserted)],
            "removed_handle": removed_handle,
        },
        "identity": {
            "snapshot_positive": int(identity["snapshot_id"]) > 0,
            "source_namespace_positive": int(identity["source_namespace_id"]) > 0,
            "source_index_epoch": int(identity["source_index_epoch"]),
            "size": int(identity["size"]),
            "capacity": int(identity["capacity"]),
            "frozen_index_contract": str(identity["frozen_index_contract"]),
            "packed_lookup_contract": str(identity["packed_lookup_contract"]),
        },
        "stats": {
            "size": int(stats["size"]),
            "capacity": int(stats["capacity"]),
            "key_bytes": int(stats["key_bytes"]),
            "request_path_lock": str(stats["request_path_lock"]),
            "shared_hot_path_state_writes": int(
                stats["shared_hot_path_state_writes"]
            ),
            "general_heap_allocations_per_lookup": int(
                stats["general_heap_allocations_per_lookup"]
            ),
            "caller_owned_output": bool(stats["caller_owned_output"]),
        },
        "packed": {
            "query_hex": [key.hex() for key in query],
            "offsets_hex": offsets.hex(),
            "processed": processed,
            "output_hex": bytes(output).hex(),
            "decoded": decoded,
            "expected": [inserted[b"key-00"], -1, -1, inserted[b"key-11"]],
        },
        "snapshot_independence": {
            "key_00": int(frozen.get_handle(b"key-00")),
            "removed_key": int(frozen.get_handle(removed_key)),
            "post_freeze": int(frozen.get_handle(b"post-freeze")),
        },
        "malformed": {
            "fault": malformed_fault,
            "output_unchanged": bytes(malformed_output) == malformed_before,
        },
    }


def _spiral_reference(
    scores: list[float],
    confidences: list[float],
    depths: list[int],
    ages: list[int],
    score_weight: float,
    confidence_weight: float,
    depth_penalty: float,
    age_penalty: float,
) -> list[float]:
    result = []
    for score, confidence, depth, age in zip(
        scores,
        confidences,
        depths,
        ages,
        strict=True,
    ):
        base = min(1.0, max(0.0, float(score)))
        certainty = min(1.0, max(0.0, float(confidence)))
        nonnegative_depth = max(0.0, float(depth))
        nonnegative_age = max(0.0, float(age))
        depth_cost = depth_penalty * nonnegative_depth
        age_cost = age_penalty * nonnegative_age
        weighted_score = base * score_weight
        weighted_confidence = certainty * confidence_weight
        weighted_total = weighted_score + weighted_confidence
        after_depth = weighted_total - depth_cost
        result.append(after_depth - age_cost)
    return result


def _spiral_projection(native: Any) -> dict[str, Any]:
    scores = [-1.0, -0.0, 0.0, 0.125, 0.5, 1.0, 2.0, 1e-300]
    confidences = [2.0, -1.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1e-300]
    depths = [-1, 0, 1, 2, 3, 7, 31, 255]
    ages = [-1, 0, 1, 1000, 1_000_000, 1_000_000_000, 7, 99]
    score_weight = 0.72
    confidence_weight = 0.18
    depth_penalty = 0.035
    age_penalty = 0.000001
    native_values = [
        float(value)
        for value in native.spiral_rank_scores(
            scores,
            confidences,
            depths,
            ages,
            score_weight,
            confidence_weight,
            depth_penalty,
            age_penalty,
        )
    ]
    reference_values = _spiral_reference(
        scores,
        confidences,
        depths,
        ages,
        score_weight,
        confidence_weight,
        depth_penalty,
        age_penalty,
    )
    native_bits = [_float64_bits(value) for value in native_values]
    reference_bits = [_float64_bits(value) for value in reference_values]
    if native_bits != reference_bits:
        raise AssertionError(
            f"native Spiral bit parity drift: native={native_bits} reference={reference_bits}"
        )
    mismatch_fault = _normalized_error(
        lambda: native.spiral_rank_scores(
            [1.0, 2.0],
            [1.0],
            [0, 0],
            [0, 0],
        )
    )
    return {
        "inputs": {
            "scores_bits": [_float64_bits(value) for value in scores],
            "confidences_bits": [_float64_bits(value) for value in confidences],
            "depths": depths,
            "ages": ages,
            "weights_bits": {
                "score": _float64_bits(score_weight),
                "confidence": _float64_bits(confidence_weight),
                "depth": _float64_bits(depth_penalty),
                "age": _float64_bits(age_penalty),
            },
        },
        "output_bits": native_bits,
        "reference_bits": reference_bits,
        "native_reference_equal": native_bits == reference_bits,
        "mismatch_fault": mismatch_fault,
    }


def _diagnostic_projection(native: Any) -> dict[str, Any]:
    native.diag_reset()
    native.diag_set_sampling(interval=4, burst=2)
    native.diag_emit(10, 11, 12)
    native.diag_emit(60, 21, 22)
    snapshot = dict(native.diag_snapshot(event_limit=16))
    counters = dict(snapshot["counters"])
    events = []
    for event in snapshot["recent_events"]:
        events.append(
            {
                "code": int(event["code"]),
                "flags": int(event["flags"]),
                "subsystem": int(event["subsystem"]),
                "object_id": int(event["object_id"]),
                "value_a": int(event["value_a"]),
                "value_b": int(event["value_b"]),
            }
        )
    selected_counter_names = (
        "event_attempts",
        "events_emitted",
        "events_dropped",
        "events_sampled_out",
        "events_slot_busy",
        "automatic_event_attempts",
        "manual_event_attempts",
        "ring_capacity",
        "ring_occupancy",
        "sampling_interval",
        "sampling_burst",
        "reset_requests",
        "resetting",
        "active_event_writers",
        "snapshot_requests",
        "snapshot_built",
    )
    return {
        "schema_version": int(snapshot["schema_version"]),
        "subsystem": str(snapshot["subsystem"]),
        "enabled": bool(snapshot["enabled"]),
        "degraded": bool(snapshot["degraded"]),
        "sequence": int(snapshot["sequence"]),
        "counters": {
            name: int(counters[name]) for name in selected_counter_names
        },
        "events": events,
    }


def build_semantic_projection() -> dict[str, Any]:
    native = _load_extension("_native_index")
    csv_native = _load_extension("_csv_scan_kernel")

    return {
        "format": FORMAT,
        "contracts": _contract_projection(native, csv_native),
        "checksums": _checksum_projection(native),
        "utf8": _utf8_projection(native),
        "csv": _csv_projection(csv_native),
        "handles": _handle_projection(native),
        "frozen_index": _frozen_projection(native),
        "spiral_baseline": _spiral_projection(native),
        "diagnostics": _diagnostic_projection(native),
    }


def build_report(*, expected_architecture: str | None = None) -> dict[str, Any]:
    machine = canonical_architecture(platform.machine())
    if expected_architecture is not None:
        expected = canonical_architecture(expected_architecture)
        if machine != expected:
            raise SystemExit(
                f"architecture mismatch: expected {expected!r}, observed {machine!r}"
            )
    projection = build_semantic_projection()
    root = semantic_root(projection)
    return {
        "format": FORMAT,
        "semantic_root": root,
        "semantic_projection": projection,
        "evidence": {
            "architecture": machine,
            "machine_reported": platform.machine(),
            "byteorder": sys.byteorder,
            "pointer_bits": calcsize("P") * 8,
            "platform": platform.platform(),
            "python": sys.version,
            "python_implementation": platform.python_implementation(),
            "python_soabi": str(sysconfig.get_config_var("SOABI") or ""),
            "compiler": str(sysconfig.get_config_var("CC") or ""),
            "source_commit": _source_commit(),
            "runner_name": os.environ.get("RUNNER_NAME", ""),
            "runner_arch": os.environ.get("RUNNER_ARCH", ""),
            "runner_os": os.environ.get("RUNNER_OS", ""),
            "runner_image_os": os.environ.get("ImageOS", ""),
            "runner_image_version": os.environ.get("ImageVersion", ""),
        },
        "expected_semantic_root": EXPECTED_SEMANTIC_ROOT,
        "root_matches_expected": root == EXPECTED_SEMANTIC_ROOT,
        "functional_authority": False,
        "activation_authority": False,
    }


def compare_reports(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    expected_root: str | None = None,
) -> dict[str, Any]:
    for label, report in (("left", left), ("right", right)):
        if report.get("format") != FORMAT:
            raise ValueError(f"{label} report has an unexpected format")
        if report.get("functional_authority") is not False:
            raise ValueError(f"{label} report gained functional authority")
        if report.get("activation_authority") is not False:
            raise ValueError(f"{label} report gained activation authority")
        projection = report.get("semantic_projection")
        if not isinstance(projection, dict):
            raise ValueError(f"{label} report lacks semantic projection")
        computed = semantic_root(projection)
        if report.get("semantic_root") != computed:
            raise ValueError(f"{label} semantic root does not verify")

    architectures = {
        canonical_architecture(str(left["evidence"]["architecture"])),
        canonical_architecture(str(right["evidence"]["architecture"])),
    }
    if architectures != {"x86_64", "aarch64"}:
        raise ValueError(f"expected x86_64 and aarch64 evidence, got {architectures}")
    if left["semantic_projection"] != right["semantic_projection"]:
        raise ValueError("x86-64 and AArch64 semantic projections differ")
    if left["semantic_root"] != right["semantic_root"]:
        raise ValueError("x86-64 and AArch64 semantic roots differ")
    if expected_root and left["semantic_root"] != expected_root:
        raise ValueError(
            f"semantic root drift: expected {expected_root}, got {left['semantic_root']}"
        )
    source_commits = {
        str(left["evidence"].get("source_commit", "")),
        str(right["evidence"].get("source_commit", "")),
    }
    if "" in source_commits or len(source_commits) != 1:
        raise ValueError(
            f"architecture reports do not bind one source commit: {source_commits}"
        )
    return {
        "format": "tds.v360.native-architecture-parity-comparison.v1",
        "semantic_root": left["semantic_root"],
        "architectures": sorted(architectures),
        "source_commit": next(iter(source_commits)),
        "semantic_match": True,
        "functional_authority": False,
        "activation_authority": False,
    }


def _load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-architecture")
    parser.add_argument("--expected-root", default=EXPECTED_SEMANTIC_ROOT)
    parser.add_argument("--compare", nargs=2, metavar=("LEFT", "RIGHT"))
    args = parser.parse_args(argv)

    if args.compare:
        comparison = compare_reports(
            _load_json(args.compare[0]),
            _load_json(args.compare[1]),
            expected_root=args.expected_root,
        )
        text = json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    else:
        report = build_report(expected_architecture=args.expected_architecture)
        text = json.dumps(report, indent=2, sort_keys=True) + "\n"

    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if not args.compare and args.expected_root:
        if report["semantic_root"] != args.expected_root:
            raise SystemExit(
                "semantic root drift: "
                f"expected {args.expected_root}, got {report['semantic_root']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

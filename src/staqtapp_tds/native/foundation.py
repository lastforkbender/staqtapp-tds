"""Machine-checkable v3.6 Foundation Closure contracts.

The closure report is intentionally source-audit and evidence-plane code.  It
cannot load a native module, mutate storage, publish a release, or widen model,
semantic, policy, Browser, or activation authority.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from staqtapp_tds.version import __version__

TDS_V360_FOUNDATION_CLOSURE_CONTRACT = "tds.v360.foundation-closure.v1"
TDS_V360_PROCESS_STATE_CONTRACT = "tds.v360.native-process-state.v1"
TDS_V360_PERFORMANCE_CLAIM_CONTRACT = "tds.v360.performance-claim.v1"
TDS_V360_RELEASE_IDENTITY = "3.6.0"
TDS_V360_SHARED_RUNNER_MIN_FACTOR_PPM = 1_000_000

_ROOT_PREFIX = "sha256:"
_GLOBAL_DECLARATION = re.compile(
    r"(?m)^\s*static\s+[^();\n]*\b(g_[A-Za-z0-9_]+)\b[^();\n]*;\s*$"
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _canonical_root(domain: str, value: Any) -> str:
    payload = domain.encode("ascii") + b"\x00" + _canonical_bytes(value)
    return _ROOT_PREFIX + hashlib.sha256(payload).hexdigest()


def _source_sha256(data: bytes) -> str:
    return _ROOT_PREFIX + hashlib.sha256(data).hexdigest()


class NativeProcessStateKind(str, Enum):
    MONOTONIC_IDENTITY = "monotonic_identity"
    LIFECYCLE_GUARD = "lifecycle_guard"
    OBSERVER_CONTROL = "observer_control"
    OBSERVER_COUNTERS = "observer_counters"
    OBSERVER_RING = "observer_ring"


@dataclass(frozen=True, slots=True)
class NativeProcessStateEntry:
    symbol: str
    kind: NativeProcessStateKind
    ownership: str
    synchronization: str
    reset_policy: str
    durable: bool = False
    storage_authority: bool = False
    semantic_authority: bool = False
    model_authority: bool = False
    policy_authority: bool = False
    activation_authority: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"g_[a-z0-9_]+", self.symbol):
            raise ValueError("native process-state symbols must use the g_ contract")
        if not isinstance(self.kind, NativeProcessStateKind):
            raise TypeError("kind must be NativeProcessStateKind")
        for name in ("ownership", "synchronization", "reset_policy"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be non-empty canonical text")
        if any(
            (
                self.durable,
                self.storage_authority,
                self.semantic_authority,
                self.model_authority,
                self.policy_authority,
                self.activation_authority,
            )
        ):
            raise ValueError("v3.6 process state is non-durable and non-authoritative")

    def canonical_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["kind"] = self.kind.value
        return result


_STATE_REGISTRY = (
    NativeProcessStateEntry(
        "g_index_namespace_sequence",
        NativeProcessStateKind.MONOTONIC_IDENTITY,
        "process-local native index namespace allocator",
        "lock-free C11 atomic uint64",
        "never reset; exhaustion fails closed",
    ),
    NativeProcessStateEntry(
        "g_frozen_snapshot_sequence",
        NativeProcessStateKind.MONOTONIC_IDENTITY,
        "process-local immutable snapshot allocator",
        "lock-free C11 atomic uint64",
        "never reset; exhaustion fails closed",
    ),
    NativeProcessStateEntry(
        "g_native_module_instance_active",
        NativeProcessStateKind.LIFECYCLE_GUARD,
        "single process-lifetime native module admission",
        "lock-free C11 compare-exchange",
        "process restart required after successful admission",
    ),
    NativeProcessStateEntry(
        "g_diag_enabled",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic observer enable flag",
        "lock-free C11 atomic uint64",
        "explicit diagnostic control only",
    ),
    NativeProcessStateEntry(
        "g_diag_degraded",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic observer degradation flag",
        "lock-free C11 atomic uint64",
        "diagnostic reset only",
    ),
    NativeProcessStateEntry(
        "g_diag_sequence",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic event sequence allocator",
        "lock-free C11 atomic uint64",
        "diagnostic reset only",
    ),
    NativeProcessStateEntry(
        "g_diag_sample_burst",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic automatic-event burst bound",
        "lock-free C11 atomic uint64",
        "explicit diagnostic sampling control",
    ),
    NativeProcessStateEntry(
        "g_diag_sample_interval",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic automatic-event sampling interval",
        "lock-free C11 atomic uint64",
        "explicit diagnostic sampling control",
    ),
    NativeProcessStateEntry(
        "g_diag_automatic_attempts",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic automatic-event attempt sequence",
        "lock-free C11 atomic uint64",
        "diagnostic reset only",
    ),
    NativeProcessStateEntry(
        "g_diag_active_event_writers",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic reset publication barrier",
        "lock-free C11 atomic uint64",
        "must reach zero before diagnostic reset",
    ),
    NativeProcessStateEntry(
        "g_diag_resetting",
        NativeProcessStateKind.OBSERVER_CONTROL,
        "diagnostic reset publication gate",
        "lock-free C11 atomic uint64",
        "set only for bounded diagnostic reset",
    ),
    NativeProcessStateEntry(
        "g_diag_counters",
        NativeProcessStateKind.OBSERVER_COUNTERS,
        "bounded exact diagnostic counters",
        "lock-free C11 atomic uint64 array",
        "diagnostic reset only",
    ),
    NativeProcessStateEntry(
        "g_diag_ring",
        NativeProcessStateKind.OBSERVER_RING,
        "bounded lossy diagnostic event copies",
        "per-slot C11 atomic publication protocol",
        "diagnostic reset after active publishers drain",
    ),
)

EXPECTED_NATIVE_INDEX_GLOBALS = frozenset(item.symbol for item in _STATE_REGISTRY)
EXPECTED_CSV_SCAN_GLOBALS = frozenset()

_NATIVE_INDEX_REQUIRED_MARKERS = (
    "multiphase-pep489-v1",
    "reject-subinterpreters-v1",
    "free-threaded-build-rejected-v1",
    "process-restart-required-v1",
    "Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED",
    "Py_MOD_GIL_USED",
    "native index rejects free-threaded CPython",
    "native diagnostics requires lock-free C11 atomics",
    "c11-atomic-slot-seqlock-mpsc-v1",
    "immutable-rehash-copy;lock-free-read-v1",
    "keys-bytes;offsets-le64;handles-le-i64;caller-owned-output-v1",
)
_CSV_SCAN_REQUIRED_MARKERS = (
    "bytes-zero-copy;other-contiguous-buffers-snapshot",
    "csv_stable_input_acquire",
    "Py_BEGIN_ALLOW_THREADS",
    "Optional native CSV scan prototype sidecar for Staqtapp-TDS.",
    "    -1,",
)


def native_process_state_registry() -> tuple[NativeProcessStateEntry, ...]:
    return _STATE_REGISTRY


def native_process_state_registry_root() -> str:
    return _canonical_root(
        "native-process-state-registry",
        {
            "contract_id": TDS_V360_PROCESS_STATE_CONTRACT,
            "entries": [item.canonical_dict() for item in _STATE_REGISTRY],
        },
    )


@dataclass(frozen=True, slots=True)
class FoundationPerformanceClaim:
    contract_id: str = TDS_V360_PERFORMANCE_CLAIM_CONTRACT
    shared_runner_no_regression_qualified: bool = True
    shared_runner_min_two_worker_factor_ppm: int = (
        TDS_V360_SHARED_RUNNER_MIN_FACTOR_PPM
    )
    cross_architecture_semantic_parity_qualified: bool = True
    named_reference_cpu_claim: bool = False
    universal_scaling_claim: bool = False
    named_reference_cpu_release_blocker: bool = False
    performance_authority: bool = False
    activation_authority: bool = False

    def __post_init__(self) -> None:
        if self.contract_id != TDS_V360_PERFORMANCE_CLAIM_CONTRACT:
            raise ValueError("unexpected performance-claim contract")
        if self.shared_runner_no_regression_qualified is not True:
            raise ValueError("v3.6 requires shared-runner no-regression evidence")
        if self.shared_runner_min_two_worker_factor_ppm != 1_000_000:
            raise ValueError("v3.6 shared-runner floor is exactly 1.00x")
        if self.cross_architecture_semantic_parity_qualified is not True:
            raise ValueError("v3.6 requires x86-64/AArch64 semantic parity")
        if any(
            (
                self.named_reference_cpu_claim,
                self.universal_scaling_claim,
                self.named_reference_cpu_release_blocker,
                self.performance_authority,
                self.activation_authority,
            )
        ):
            raise ValueError("v3.6 performance evidence cannot be widened")

    def canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def claim_root(self) -> str:
        return _canonical_root("foundation-performance-claim", self.canonical_dict())


FOUNDATION_PERFORMANCE_CLAIM = FoundationPerformanceClaim()


@dataclass(frozen=True, slots=True)
class NativeSourceAudit:
    contract_id: str
    native_index_sha256: str
    csv_scan_sha256: str
    registry_root: str
    declared_native_index_globals: tuple[str, ...]
    declared_csv_scan_globals: tuple[str, ...]
    missing_native_index_globals: tuple[str, ...]
    unexpected_native_index_globals: tuple[str, ...]
    unexpected_csv_scan_globals: tuple[str, ...]
    missing_native_index_markers: tuple[str, ...]
    missing_csv_scan_markers: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.missing_native_index_globals,
                self.unexpected_native_index_globals,
                self.unexpected_csv_scan_globals,
                self.missing_native_index_markers,
                self.missing_csv_scan_markers,
            )
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "passed": self.passed,
            "storage_authority": False,
            "semantic_authority": False,
            "model_authority": False,
            "policy_authority": False,
            "activation_authority": False,
            "release_authority": False,
        }

    @property
    def audit_root(self) -> str:
        return _canonical_root("native-source-audit", self.canonical_dict())


def _declared_globals(source: str) -> frozenset[str]:
    return frozenset(_GLOBAL_DECLARATION.findall(source))


def _missing_markers(source: str, markers: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(marker for marker in markers if marker not in source))


def audit_native_sources(root: str | Path) -> NativeSourceAudit:
    root_path = Path(root)
    index_path = root_path / "src" / "staqtapp_tds" / "_native_index.c"
    csv_path = root_path / "src" / "staqtapp_tds" / "_csv_scan_kernel.c"
    index_bytes = index_path.read_bytes()
    csv_bytes = csv_path.read_bytes()
    index_source = index_bytes.decode("utf-8")
    csv_source = csv_bytes.decode("utf-8")
    index_globals = _declared_globals(index_source)
    csv_globals = _declared_globals(csv_source)
    return NativeSourceAudit(
        contract_id=TDS_V360_FOUNDATION_CLOSURE_CONTRACT,
        native_index_sha256=_source_sha256(index_bytes),
        csv_scan_sha256=_source_sha256(csv_bytes),
        registry_root=native_process_state_registry_root(),
        declared_native_index_globals=tuple(sorted(index_globals)),
        declared_csv_scan_globals=tuple(sorted(csv_globals)),
        missing_native_index_globals=tuple(
            sorted(EXPECTED_NATIVE_INDEX_GLOBALS - index_globals)
        ),
        unexpected_native_index_globals=tuple(
            sorted(index_globals - EXPECTED_NATIVE_INDEX_GLOBALS)
        ),
        unexpected_csv_scan_globals=tuple(
            sorted(csv_globals - EXPECTED_CSV_SCAN_GLOBALS)
        ),
        missing_native_index_markers=_missing_markers(
            index_source, _NATIVE_INDEX_REQUIRED_MARKERS
        ),
        missing_csv_scan_markers=_missing_markers(
            csv_source, _CSV_SCAN_REQUIRED_MARKERS
        ),
    )


@dataclass(frozen=True, slots=True)
class FoundationClosureReport:
    release_identity: str
    source_audit: NativeSourceAudit
    performance_claim: FoundationPerformanceClaim = FOUNDATION_PERFORMANCE_CLAIM
    contract_id: str = TDS_V360_FOUNDATION_CLOSURE_CONTRACT

    def __post_init__(self) -> None:
        if self.release_identity != TDS_V360_RELEASE_IDENTITY:
            raise ValueError("foundation closure requires release identity 3.6.0")
        if self.contract_id != TDS_V360_FOUNDATION_CLOSURE_CONTRACT:
            raise ValueError("unexpected foundation-closure contract")
        if not isinstance(self.source_audit, NativeSourceAudit):
            raise TypeError("source_audit must be NativeSourceAudit")
        if not isinstance(self.performance_claim, FoundationPerformanceClaim):
            raise TypeError("performance_claim must be FoundationPerformanceClaim")

    @property
    def passed(self) -> bool:
        return (
            self.release_identity == __version__
            and self.source_audit.passed
            and self.performance_claim.shared_runner_no_regression_qualified
            and self.performance_claim.cross_architecture_semantic_parity_qualified
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "release_identity": self.release_identity,
            "source_version": __version__,
            "passed": self.passed,
            "process_state_registry_root": native_process_state_registry_root(),
            "source_audit": self.source_audit.canonical_dict(),
            "source_audit_root": self.source_audit.audit_root,
            "performance_claim": self.performance_claim.canonical_dict(),
            "performance_claim_root": self.performance_claim.claim_root,
            "atomic_generation_plane_included": False,
            "eaglegate_included": False,
            "learned_serving_included": False,
            "storage_authority": False,
            "semantic_authority": False,
            "model_authority": False,
            "policy_authority": False,
            "activation_authority": False,
            "release_authority": False,
            "browser_authority": False,
        }

    @property
    def report_root(self) -> str:
        return _canonical_root("foundation-closure-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def build_foundation_closure_report(root: str | Path) -> FoundationClosureReport:
    return FoundationClosureReport(
        release_identity=TDS_V360_RELEASE_IDENTITY,
        source_audit=audit_native_sources(root),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-foundation-closure")
    parser.add_argument("--root", default=".", help="repository source root")
    parser.add_argument("--json", action="store_true", help="emit canonical JSON")
    args = parser.parse_args(argv)
    report = build_foundation_closure_report(args.root)
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    else:
        print("TDS v3.6 Foundation Closure: " + ("PASS" if report.passed else "FAIL"))
        print(f"release_identity: {report.release_identity}")
        print(f"process_state_registry_root: {native_process_state_registry_root()}")
        print(f"performance_claim_root: {report.performance_claim.claim_root}")
        print(f"source_audit_root: {report.source_audit.audit_root}")
        print(f"report_root: {report.report_root}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_CSV_SCAN_GLOBALS",
    "EXPECTED_NATIVE_INDEX_GLOBALS",
    "FOUNDATION_PERFORMANCE_CLAIM",
    "FoundationClosureReport",
    "FoundationPerformanceClaim",
    "NativeProcessStateEntry",
    "NativeProcessStateKind",
    "NativeSourceAudit",
    "TDS_V360_FOUNDATION_CLOSURE_CONTRACT",
    "TDS_V360_PERFORMANCE_CLAIM_CONTRACT",
    "TDS_V360_PROCESS_STATE_CONTRACT",
    "TDS_V360_RELEASE_IDENTITY",
    "TDS_V360_SHARED_RUNNER_MIN_FACTOR_PPM",
    "audit_native_sources",
    "build_foundation_closure_report",
    "main",
    "native_process_state_registry",
    "native_process_state_registry_root",
]

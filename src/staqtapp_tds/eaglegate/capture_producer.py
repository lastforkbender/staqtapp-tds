"""Isolated, non-importing producer for Eaglegate capability bundles.

The producer may inspect installed distribution metadata and hash bounded package
files. It never imports the provider runtime, loads model artifacts, probes an
accelerator, uses the network, spawns a subprocess, executes inference, accepts
tokens, mutates KV state, or activates Eaglegate.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import struct
import sys
import tempfile
from typing import Any, Mapping, Sequence

from .exactness_common import (
    EaglegateExactnessError,
    UINT32_MAX,
    UINT63_MAX,
    canonical_root,
    require_ascii,
    require_int,
    require_root,
)
from .offline_capture import (
    EAGLEGATE_VLLM_EAGLE_PROVIDER_ID,
    OfflineCapabilityCaptureEnvelope,
    OfflineCaptureDecision,
    provider_snapshot_payload_root,
    validate_offline_capability_capture,
)
from .offline_capture_suite import capture_bundle_to_mapping
from .vllm_shadow import VllmEagleCapabilitySnapshot

EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID = (
    "tds-eaglegate-isolated-capture-producer-v1"
)
EAGLEGATE_CAPTURE_PRODUCER_FORMAT_VERSION = 1
EAGLEGATE_CAPTURE_PRODUCER_PROFILE_ID = "vllm-wheel-metadata-only-v1"
EAGLEGATE_CAPTURE_PRODUCER_DISTRIBUTION = "vllm"

_NAME_NORMALIZER = re.compile(r"[-_.]+")
_FORBIDDEN_MODEL_SUFFIXES = frozenset(
    {
        ".bin",
        ".ckpt",
        ".gguf",
        ".onnx",
        ".ot",
        ".pt",
        ".pth",
        ".safetensors",
        ".tflite",
    }
)
_REQUIRED_METADATA_FILES = ("METADATA", "WHEEL", "RECORD")
_HASH_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class CaptureProducerAuthorityBoundary:
    may_inspect_distribution_metadata: bool = True
    may_hash_distribution_files: bool = True
    may_import_provider_runtime: bool = False
    may_load_model: bool = False
    may_read_model_artifact: bool = False
    may_probe_accelerator: bool = False
    may_use_network: bool = False
    may_spawn_subprocess: bool = False
    may_execute_dynamic_code: bool = False
    may_execute_inference: bool = False
    may_accept_tokens: bool = False
    may_commit_kv: bool = False
    may_verify_source_commit: bool = False
    may_activate: bool = False
    target_only_execution_required: bool = True

    def __post_init__(self) -> None:
        expected = {
            "may_inspect_distribution_metadata": True,
            "may_hash_distribution_files": True,
            "may_import_provider_runtime": False,
            "may_load_model": False,
            "may_read_model_artifact": False,
            "may_probe_accelerator": False,
            "may_use_network": False,
            "may_spawn_subprocess": False,
            "may_execute_dynamic_code": False,
            "may_execute_inference": False,
            "may_accept_tokens": False,
            "may_commit_kv": False,
            "may_verify_source_commit": False,
            "may_activate": False,
            "target_only_execution_required": True,
        }
        if asdict(self) != expected:
            raise EaglegateExactnessError(
                "capture producer authority cannot be widened"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            "producer_format_version": EAGLEGATE_CAPTURE_PRODUCER_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return canonical_root(
            "capture-producer-authority", self.canonical_dict()
        )


EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY = CaptureProducerAuthorityBoundary()


@dataclass(frozen=True, slots=True)
class CaptureProducerLimits:
    max_files: int = 200_000
    max_file_bytes: int = 512 << 20
    max_total_bytes: int = 8 << 30
    max_metadata_bytes: int = 16 << 20

    def __post_init__(self) -> None:
        require_int("max_files", self.max_files, 1, UINT32_MAX)
        require_int("max_file_bytes", self.max_file_bytes, 1, UINT63_MAX)
        require_int("max_total_bytes", self.max_total_bytes, 1, UINT63_MAX)
        require_int("max_metadata_bytes", self.max_metadata_bytes, 1, UINT32_MAX)
        if self.max_file_bytes > self.max_total_bytes:
            raise EaglegateExactnessError(
                "max_file_bytes cannot exceed max_total_bytes"
            )

    def canonical_dict(self) -> dict[str, int | str]:
        return {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def limits_root(self) -> str:
        return canonical_root("capture-producer-limits", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class DistributionFileDigest:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        normalized = validate_distribution_member_path(self.path)
        if normalized != self.path:
            raise EaglegateExactnessError(
                "distribution file path must already be canonical"
            )
        require_int("size", self.size, 0, UINT63_MAX)
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise EaglegateExactnessError(
                "distribution file sha256 must be lowercase hex"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def file_root(self) -> str:
        return canonical_root("distribution-file", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class InstalledDistributionInspection:
    normalized_name: str
    version: str
    metadata_root: str
    file_manifest_root: str
    file_count: int
    total_bytes: int
    limits_root: str

    def __post_init__(self) -> None:
        require_ascii("normalized_name", self.normalized_name)
        if normalize_distribution_name(self.normalized_name) != self.normalized_name:
            raise EaglegateExactnessError(
                "distribution name must already be normalized"
            )
        require_ascii("version", self.version)
        for name in ("metadata_root", "file_manifest_root", "limits_root"):
            require_root(name, getattr(self, name))
        require_int("file_count", self.file_count, 1, UINT32_MAX)
        require_int("total_bytes", self.total_bytes, 0, UINT63_MAX)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def distribution_root(self) -> str:
        return canonical_root(
            "installed-distribution", self.canonical_dict()
        )


@dataclass(frozen=True, slots=True)
class CaptureProducerProfile:
    source_commit_root: str
    capture_sequence: int = 1
    previous_capture_root: str = ""
    provider_id: str = EAGLEGATE_VLLM_EAGLE_PROVIDER_ID
    distribution_name: str = EAGLEGATE_CAPTURE_PRODUCER_DISTRIBUTION
    profile_id: str = EAGLEGATE_CAPTURE_PRODUCER_PROFILE_ID

    def __post_init__(self) -> None:
        require_root("source_commit_root", self.source_commit_root)
        require_int("capture_sequence", self.capture_sequence, 1, UINT32_MAX)
        if self.previous_capture_root:
            require_root("previous_capture_root", self.previous_capture_root)
        if self.provider_id != EAGLEGATE_VLLM_EAGLE_PROVIDER_ID:
            raise EaglegateExactnessError("unsupported capture provider")
        if normalize_distribution_name(self.distribution_name) != "vllm":
            raise EaglegateExactnessError(
                "producer v1 supports only the vllm distribution"
            )
        if self.profile_id != EAGLEGATE_CAPTURE_PRODUCER_PROFILE_ID:
            raise EaglegateExactnessError("unsupported producer profile")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def profile_root(self) -> str:
        return canonical_root("capture-producer-profile", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CaptureProducerResult:
    profile_root: str
    producer_tool_root: str
    environment_root: str
    inspection: InstalledDistributionInspection
    envelope: OfflineCapabilityCaptureEnvelope
    decision: OfflineCaptureDecision
    provider_snapshot: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("profile_root", "producer_tool_root", "environment_root"):
            require_root(name, getattr(self, name))
        if not isinstance(self.inspection, InstalledDistributionInspection):
            raise EaglegateExactnessError("inspection has wrong type")
        if not isinstance(self.envelope, OfflineCapabilityCaptureEnvelope):
            raise EaglegateExactnessError("envelope has wrong type")
        if not isinstance(self.decision, OfflineCaptureDecision):
            raise EaglegateExactnessError("decision has wrong type")
        if not isinstance(self.provider_snapshot, Mapping):
            raise EaglegateExactnessError("provider_snapshot must be an object")
        if not self.decision.compatible:
            raise EaglegateExactnessError(
                "producer result requires a compatible offline capture"
            )

    def bundle_dict(self) -> dict[str, Any]:
        return capture_bundle_to_mapping(self.envelope, self.provider_snapshot)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            "producer_format_version": EAGLEGATE_CAPTURE_PRODUCER_FORMAT_VERSION,
            "authority_root": EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY.authority_root,
            "profile_root": self.profile_root,
            "producer_tool_root": self.producer_tool_root,
            "environment_root": self.environment_root,
            "distribution_root": self.inspection.distribution_root,
            "metadata_root": self.inspection.metadata_root,
            "file_manifest_root": self.inspection.file_manifest_root,
            "file_count": self.inspection.file_count,
            "total_bytes": self.inspection.total_bytes,
            "capture_root": self.envelope.capture_root,
            "offline_decision_root": self.decision.decision_root,
            "source_commit_verified": False,
            "provider_runtime_imported": False,
            "model_artifact_read": False,
            "model_loaded": False,
            "accelerator_probed": False,
            "network_used": False,
            "subprocess_used": False,
            "dynamic_code_executed": False,
            "inference_performed": False,
            "token_acceptance_authority": False,
            "kv_commit_authority": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
            "serving_effect": "shadow_metadata_only",
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
        }

    @property
    def result_root(self) -> str:
        return canonical_root("capture-producer-result", self.canonical_dict())

    def to_dict(self, *, include_bundle: bool = False) -> dict[str, Any]:
        result = {**self.canonical_dict(), "result_root": self.result_root}
        if include_bundle:
            result["bundle"] = self.bundle_dict()
        return result


def normalize_distribution_name(value: str) -> str:
    require_ascii("distribution name", value)
    return _NAME_NORMALIZER.sub("-", value).lower()


def validate_distribution_member_path(value: str) -> str:
    require_ascii("distribution file path", value)
    normalized_text = value.replace("\\", "/")
    path = PurePosixPath(normalized_text)
    if path.is_absolute() or not path.parts:
        raise EaglegateExactnessError(
            "distribution file path must be relative"
        )
    if any(part in {"", ".", ".."} for part in path.parts):
        raise EaglegateExactnessError(
            "distribution file path contains traversal"
        )
    canonical = path.as_posix()
    if PurePosixPath(canonical).suffix.lower() in _FORBIDDEN_MODEL_SUFFIXES:
        raise EaglegateExactnessError(
            "model artifact files are outside capture producer authority"
        )
    return canonical


def _sha256_file(path: Path, *, max_bytes: int) -> tuple[int, str]:
    if path.is_symlink():
        raise EaglegateExactnessError(
            "symlinked distribution files are not qualified"
        )
    if not path.is_file():
        raise EaglegateExactnessError(
            "distribution manifest contains a missing or non-regular file"
        )
    size = path.stat().st_size
    if size > max_bytes:
        raise EaglegateExactnessError(
            "distribution file exceeds qualified byte limit"
        )
    digest = hashlib.sha256()
    observed = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(_HASH_CHUNK_BYTES)
            if not block:
                break
            observed += len(block)
            if observed > max_bytes:
                raise EaglegateExactnessError(
                    "distribution file exceeded qualified byte limit while reading"
                )
            digest.update(block)
    if observed != size:
        raise EaglegateExactnessError(
            "distribution file changed while being captured"
        )
    return size, digest.hexdigest()


def inspect_distribution_object(
    distribution: Any,
    *,
    expected_name: str,
    limits: CaptureProducerLimits | None = None,
) -> InstalledDistributionInspection:
    active_limits = limits or CaptureProducerLimits()
    if not isinstance(active_limits, CaptureProducerLimits):
        raise EaglegateExactnessError("limits have wrong type")
    metadata_name = distribution.metadata.get("Name")
    if not isinstance(metadata_name, str):
        raise EaglegateExactnessError(
            "distribution metadata lacks an exact Name"
        )
    normalized_name = normalize_distribution_name(metadata_name)
    if normalized_name != normalize_distribution_name(expected_name):
        raise EaglegateExactnessError("installed distribution name mismatch")
    version = distribution.version
    require_ascii("distribution version", version)

    metadata_roots: list[dict[str, str]] = []
    for name in _REQUIRED_METADATA_FILES:
        value = distribution.read_text(name)
        if not isinstance(value, str):
            raise EaglegateExactnessError(
                f"installed distribution lacks required {name} metadata"
            )
        encoded = value.encode("utf-8")
        if len(encoded) > active_limits.max_metadata_bytes:
            raise EaglegateExactnessError(
                f"{name} exceeds qualified metadata byte limit"
            )
        metadata_roots.append(
            {"name": name, "sha256": hashlib.sha256(encoded).hexdigest()}
        )

    files = distribution.files
    if files is None:
        raise EaglegateExactnessError(
            "installed distribution does not expose a file manifest"
        )
    values = tuple(files)
    if not values:
        raise EaglegateExactnessError(
            "installed distribution file manifest is empty"
        )
    if len(values) > active_limits.max_files:
        raise EaglegateExactnessError(
            "installed distribution exceeds qualified file-count limit"
        )

    root = Path(distribution.locate_file("")).resolve(strict=True)
    records: list[DistributionFileDigest] = []
    seen: set[str] = set()
    total_bytes = 0
    for member in values:
        relative = validate_distribution_member_path(str(member))
        if relative in seen:
            raise EaglegateExactnessError(
                "installed distribution contains duplicate file paths"
            )
        seen.add(relative)
        raw_path = Path(distribution.locate_file(member))
        if raw_path.is_symlink():
            raise EaglegateExactnessError(
                "symlinked distribution files are not qualified"
            )
        resolved = raw_path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise EaglegateExactnessError(
                "distribution file escaped the installed distribution root"
            ) from exc
        size, digest = _sha256_file(
            resolved, max_bytes=active_limits.max_file_bytes
        )
        total_bytes += size
        if total_bytes > active_limits.max_total_bytes:
            raise EaglegateExactnessError(
                "installed distribution exceeds qualified total-byte limit"
            )
        records.append(DistributionFileDigest(relative, size, digest))

    records.sort(key=lambda item: item.path)
    metadata_root = canonical_root(
        "distribution-package-metadata",
        {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            "normalized_name": normalized_name,
            "version": version,
            "metadata_files": metadata_roots,
        },
    )
    file_manifest_root = canonical_root(
        "distribution-file-manifest",
        {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            "files": [item.canonical_dict() for item in records],
        },
    )
    return InstalledDistributionInspection(
        normalized_name=normalized_name,
        version=version,
        metadata_root=metadata_root,
        file_manifest_root=file_manifest_root,
        file_count=len(records),
        total_bytes=total_bytes,
        limits_root=active_limits.limits_root,
    )


def inspect_installed_distribution(
    name: str = EAGLEGATE_CAPTURE_PRODUCER_DISTRIBUTION,
    *,
    limits: CaptureProducerLimits | None = None,
) -> InstalledDistributionInspection:
    normalized = normalize_distribution_name(name)
    if normalized != EAGLEGATE_CAPTURE_PRODUCER_DISTRIBUTION:
        raise EaglegateExactnessError(
            "capture producer v1 supports only the vllm distribution"
        )
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise EaglegateExactnessError(
            "the exact vllm distribution is not installed"
        ) from exc
    return inspect_distribution_object(
        distribution, expected_name=name, limits=limits
    )


def capture_environment_root() -> str:
    value = {
        "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_cache_tag": sys.implementation.cache_tag or "",
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "pointer_bits": struct.calcsize("P") * 8,
        "byteorder": sys.byteorder,
        "accelerator_probed": False,
        "network_used": False,
        "subprocess_used": False,
    }
    return canonical_root("capture-producer-environment", value)


def capture_producer_tool_root() -> str:
    source = Path(__file__).read_bytes()
    return canonical_root(
        "capture-producer-tool",
        {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            "producer_format_version": EAGLEGATE_CAPTURE_PRODUCER_FORMAT_VERSION,
            "source_sha256": hashlib.sha256(source).hexdigest(),
        },
    )


def produce_offline_capture(
    provider_snapshot: Mapping[str, Any],
    inspection: InstalledDistributionInspection,
    profile: CaptureProducerProfile,
) -> CaptureProducerResult:
    if not isinstance(provider_snapshot, Mapping):
        raise EaglegateExactnessError("provider_snapshot must be an object")
    if not isinstance(inspection, InstalledDistributionInspection):
        raise EaglegateExactnessError("inspection has wrong type")
    if not isinstance(profile, CaptureProducerProfile):
        raise EaglegateExactnessError("profile has wrong type")
    snapshot = VllmEagleCapabilitySnapshot.from_mapping(provider_snapshot)
    if inspection.normalized_name != normalize_distribution_name(
        profile.distribution_name
    ):
        raise EaglegateExactnessError(
            "distribution inspection does not match producer profile"
        )
    if inspection.version != snapshot.runtime_version:
        raise EaglegateExactnessError(
            "installed distribution version does not match provider snapshot"
        )
    environment_root = capture_environment_root()
    tool_root = capture_producer_tool_root()
    envelope = OfflineCapabilityCaptureEnvelope(
        provider_id=profile.provider_id,
        capture_sequence=profile.capture_sequence,
        capture_tool_root=tool_root,
        runtime_distribution_root=inspection.distribution_root,
        package_metadata_root=inspection.metadata_root,
        source_commit_root=profile.source_commit_root,
        environment_root=environment_root,
        adapter_conformance_root=snapshot.adapter_conformance_root,
        provider_snapshot_payload_root=provider_snapshot_payload_root(
            provider_snapshot
        ),
        previous_capture_root=profile.previous_capture_root,
    )
    decision = validate_offline_capability_capture(
        envelope, provider_snapshot
    )
    if not decision.compatible:
        raise EaglegateExactnessError(
            "produced bundle failed offline capture validation"
        )
    return CaptureProducerResult(
        profile_root=profile.profile_root,
        producer_tool_root=tool_root,
        environment_root=environment_root,
        inspection=inspection,
        envelope=envelope,
        decision=decision,
        provider_snapshot=dict(provider_snapshot),
    )


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True)
        + "\n"
    )
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EaglegateExactnessError(f"could not read {source}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise EaglegateExactnessError(f"{source} must contain one JSON object")
    return dict(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="staqtapp-tds-eaglegate-capture-produce"
    )
    parser.add_argument("--provider-snapshot", required=True)
    parser.add_argument("--source-commit-root", required=True)
    parser.add_argument("--capture-sequence", type=int, default=1)
    parser.add_argument("--previous-capture-root", default="")
    parser.add_argument("--distribution", default="vllm")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        provider_snapshot = _read_object(args.provider_snapshot)
        inspection = inspect_installed_distribution(args.distribution)
        profile = CaptureProducerProfile(
            source_commit_root=args.source_commit_root,
            capture_sequence=args.capture_sequence,
            previous_capture_root=args.previous_capture_root,
            distribution_name=args.distribution,
        )
        result = produce_offline_capture(
            provider_snapshot, inspection, profile
        )
        if args.output:
            _atomic_json_write(Path(args.output), result.bundle_dict())
        payload = result.to_dict(include_bundle=not bool(args.output))
        payload["output"] = str(Path(args.output).resolve()) if args.output else ""
        code = 0
    except EaglegateExactnessError as exc:
        payload = {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            "ok": False,
            "fault": "capture_producer_rejected",
            "message": str(exc),
            "serving_effect": "target_only",
            "provider_runtime_imported": False,
            "model_artifact_read": False,
            "model_loaded": False,
            "accelerator_probed": False,
            "network_used": False,
            "subprocess_used": False,
            "dynamic_code_executed": False,
            "inference_performed": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
        }
        code = 2
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        state = "CAPTURED" if code == 0 else "TARGET-ONLY"
        print(f"Eaglegate isolated capture producer: {state}")
        print(json.dumps(payload, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY",
    "EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID",
    "EAGLEGATE_CAPTURE_PRODUCER_DISTRIBUTION",
    "EAGLEGATE_CAPTURE_PRODUCER_FORMAT_VERSION",
    "EAGLEGATE_CAPTURE_PRODUCER_PROFILE_ID",
    "CaptureProducerAuthorityBoundary",
    "CaptureProducerLimits",
    "CaptureProducerProfile",
    "CaptureProducerResult",
    "DistributionFileDigest",
    "InstalledDistributionInspection",
    "capture_environment_root",
    "capture_producer_tool_root",
    "inspect_distribution_object",
    "inspect_installed_distribution",
    "main",
    "normalize_distribution_name",
    "produce_offline_capture",
    "validate_distribution_member_path",
]

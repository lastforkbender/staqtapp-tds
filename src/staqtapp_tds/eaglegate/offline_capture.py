"""Runtime-neutral importer for externally produced, metadata-only captures.

TDS validates an immutable envelope and provider snapshot. It never imports the
provider runtime, loads a model, executes inference, accepts tokens, or mutates
KV state.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapter_contract import EaglegateAdapterIdentity
from .exactness_common import (
    EaglegateExactnessError,
    UINT32_MAX,
    canonical_root,
    require_ascii,
    require_int,
    require_root,
)
from .vllm_shadow import VllmEagleCapabilitySnapshot

EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID = "tds-eaglegate-offline-capture-v1"
EAGLEGATE_OFFLINE_CAPTURE_BUNDLE_ID = "tds-eaglegate-offline-capture-bundle-v1"
EAGLEGATE_VLLM_EAGLE_PROVIDER_ID = "vllm-eagle-v1"

_FORBIDDEN_CONTENT_KEYS = frozenset(
    {
        "prompt",
        "prompt_text",
        "tokens",
        "token_sequence",
        "logits",
        "logits_payload",
        "hidden_states",
        "kv_tensor",
        "kv_tensors",
    }
)


class OfflineCaptureFault(str, Enum):
    NONE = "none"
    INVALID_BUNDLE = "invalid_bundle"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    PAYLOAD_MISMATCH = "payload_mismatch"
    ADAPTER_MISMATCH = "adapter_mismatch"
    CONTENT_REJECTED = "content_rejected"
    AUTHORITY_REJECTED = "authority_rejected"


@dataclass(frozen=True, slots=True)
class OfflineCaptureAuthorityBoundary:
    metadata_import_only: bool = True
    tds_runtime_import_allowed: bool = False
    model_loading_allowed: bool = False
    inference_allowed: bool = False
    network_io_allowed: bool = False
    subprocess_allowed: bool = False
    token_acceptance_authority: bool = False
    target_rng_authority: bool = False
    kv_commit_authority: bool = False
    activation_authority: bool = False
    raw_content_persistence_allowed: bool = False
    target_only_execution_required: bool = True

    def __post_init__(self) -> None:
        expected = {
            "metadata_import_only": True,
            "tds_runtime_import_allowed": False,
            "model_loading_allowed": False,
            "inference_allowed": False,
            "network_io_allowed": False,
            "subprocess_allowed": False,
            "token_acceptance_authority": False,
            "target_rng_authority": False,
            "kv_commit_authority": False,
            "activation_authority": False,
            "raw_content_persistence_allowed": False,
            "target_only_execution_required": True,
        }
        if asdict(self) != expected:
            raise EaglegateExactnessError(
                "offline capture authority cannot be widened"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "capture_contract_id": EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return canonical_root("offline-capture-authority", self.canonical_dict())


EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY = OfflineCaptureAuthorityBoundary()


def provider_snapshot_payload_root(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise EaglegateExactnessError("provider snapshot must be an object")
    return canonical_root(
        "offline-provider-snapshot-payload",
        {"provider_snapshot": dict(value)},
    )


def _contains_forbidden_content(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in _FORBIDDEN_CONTENT_KEYS or _contains_forbidden_content(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_content(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class OfflineCapabilityCaptureEnvelope:
    provider_id: str
    capture_sequence: int
    capture_tool_root: str
    runtime_distribution_root: str
    package_metadata_root: str
    source_commit_root: str
    environment_root: str
    adapter_conformance_root: str
    provider_snapshot_payload_root: str
    previous_capture_root: str = ""
    metadata_only: bool = True
    model_loaded: bool = False
    inference_performed: bool = False
    network_used: bool = False
    subprocess_used: bool = False
    bundle_id: str = EAGLEGATE_OFFLINE_CAPTURE_BUNDLE_ID

    def __post_init__(self) -> None:
        if self.bundle_id != EAGLEGATE_OFFLINE_CAPTURE_BUNDLE_ID:
            raise EaglegateExactnessError("unsupported offline capture bundle")
        require_ascii("provider_id", self.provider_id)
        require_int("capture_sequence", self.capture_sequence, 1, UINT32_MAX)
        for name in (
            "capture_tool_root",
            "runtime_distribution_root",
            "package_metadata_root",
            "source_commit_root",
            "environment_root",
            "adapter_conformance_root",
            "provider_snapshot_payload_root",
        ):
            require_root(name, getattr(self, name))
        if self.previous_capture_root:
            require_root("previous_capture_root", self.previous_capture_root)
        fixed = {
            "metadata_only": True,
            "model_loaded": False,
            "inference_performed": False,
            "network_used": False,
            "subprocess_used": False,
        }
        observed = {name: getattr(self, name) for name in fixed}
        if observed != fixed:
            raise EaglegateExactnessError(
                "offline capture declared forbidden runtime activity"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "capture_contract_id": EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID,
            "authority_root": EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY.authority_root,
            **asdict(self),
        }

    @property
    def capture_root(self) -> str:
        return canonical_root("offline-capability-capture", self.canonical_dict())

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "OfflineCapabilityCaptureEnvelope":
        if not isinstance(value, Mapping):
            raise EaglegateExactnessError("capture envelope must be an object")
        fields = dict(value)
        unknown = sorted(set(fields) - set(cls.__dataclass_fields__))
        if unknown:
            raise EaglegateExactnessError(
                f"unknown offline capture fields: {unknown}"
            )
        try:
            return cls(**fields)
        except TypeError as exc:
            raise EaglegateExactnessError(
                f"invalid offline capture fields: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class OfflineCaptureDecision:
    capture_root: str
    provider_snapshot_payload_root: str
    adapter_identity_root: str
    compatible: bool
    fault: OfflineCaptureFault
    reason: str

    def __post_init__(self) -> None:
        require_root("capture_root", self.capture_root)
        require_root(
            "provider_snapshot_payload_root", self.provider_snapshot_payload_root
        )
        require_root("adapter_identity_root", self.adapter_identity_root)
        if not isinstance(self.compatible, bool):
            raise EaglegateExactnessError("compatible must be boolean")
        if not isinstance(self.fault, OfflineCaptureFault):
            raise EaglegateExactnessError("fault must be OfflineCaptureFault")
        require_ascii("reason", self.reason, allow_empty=True)
        if self.compatible != (self.fault is OfflineCaptureFault.NONE):
            raise EaglegateExactnessError("capture decision fault is inconsistent")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "capture_contract_id": EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID,
            "authority_root": EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY.authority_root,
            "capture_root": self.capture_root,
            "provider_snapshot_payload_root": self.provider_snapshot_payload_root,
            "adapter_identity_root": self.adapter_identity_root,
            "compatible": self.compatible,
            "fault": self.fault.value,
            "reason": self.reason,
            "serving_effect": "shadow_metadata_only" if self.compatible else "target_only",
            "runtime_imported_by_tds": False,
            "model_invoked": False,
            "inference_performed": False,
            "token_acceptance_authority": False,
            "kv_commit_authority": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
        }

    @property
    def decision_root(self) -> str:
        return canonical_root("offline-capture-decision", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "decision_root": self.decision_root}


def _fallback(
    envelope: OfflineCapabilityCaptureEnvelope,
    payload_root: str,
    fault: OfflineCaptureFault,
    reason: str,
    adapter_identity_root: str,
) -> OfflineCaptureDecision:
    return OfflineCaptureDecision(
        envelope.capture_root,
        payload_root,
        adapter_identity_root,
        False,
        fault,
        reason,
    )


def validate_offline_capability_capture(
    envelope: OfflineCapabilityCaptureEnvelope,
    provider_snapshot: Mapping[str, Any],
) -> OfflineCaptureDecision:
    if not isinstance(envelope, OfflineCapabilityCaptureEnvelope):
        raise EaglegateExactnessError("envelope has wrong type")
    if not isinstance(provider_snapshot, Mapping):
        raise EaglegateExactnessError("provider snapshot must be an object")
    payload_root = provider_snapshot_payload_root(provider_snapshot)
    placeholder_identity = canonical_root(
        "unresolved-adapter-identity",
        {"adapter_conformance_root": envelope.adapter_conformance_root},
    )
    if _contains_forbidden_content(provider_snapshot):
        return _fallback(
            envelope,
            payload_root,
            OfflineCaptureFault.CONTENT_REJECTED,
            "content_rejected",
            placeholder_identity,
        )
    if payload_root != envelope.provider_snapshot_payload_root:
        return _fallback(
            envelope,
            payload_root,
            OfflineCaptureFault.PAYLOAD_MISMATCH,
            "payload_mismatch",
            placeholder_identity,
        )
    if envelope.provider_id != EAGLEGATE_VLLM_EAGLE_PROVIDER_ID:
        return _fallback(
            envelope,
            payload_root,
            OfflineCaptureFault.UNSUPPORTED_PROVIDER,
            "unsupported_provider",
            placeholder_identity,
        )
    try:
        snapshot = VllmEagleCapabilitySnapshot.from_mapping(provider_snapshot)
    except EaglegateExactnessError:
        return _fallback(
            envelope,
            payload_root,
            OfflineCaptureFault.INVALID_BUNDLE,
            "invalid_provider_snapshot",
            placeholder_identity,
        )
    identity: EaglegateAdapterIdentity = snapshot.adapter_identity()
    if snapshot.adapter_conformance_root != envelope.adapter_conformance_root:
        return _fallback(
            envelope,
            payload_root,
            OfflineCaptureFault.ADAPTER_MISMATCH,
            "adapter_conformance_mismatch",
            identity.adapter_identity_root,
        )
    return OfflineCaptureDecision(
        envelope.capture_root,
        payload_root,
        identity.adapter_identity_root,
        True,
        OfflineCaptureFault.NONE,
        "offline_metadata_capture_ready",
    )


def capture_envelope_to_mapping(
    envelope: OfflineCapabilityCaptureEnvelope,
) -> dict[str, Any]:
    return asdict(envelope)


def _read_bundle(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EaglegateExactnessError(f"could not read {source}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise EaglegateExactnessError("capture bundle must be an object")
    unknown = sorted(set(value) - {"envelope", "provider_snapshot"})
    if unknown:
        raise EaglegateExactnessError(f"unknown capture bundle fields: {unknown}")
    envelope = value.get("envelope")
    snapshot = value.get("provider_snapshot")
    if not isinstance(envelope, Mapping) or not isinstance(snapshot, Mapping):
        raise EaglegateExactnessError(
            "capture bundle requires envelope and provider_snapshot objects"
        )
    return dict(envelope), dict(snapshot)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-capture")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        envelope_data, snapshot = _read_bundle(args.bundle)
        envelope = OfflineCapabilityCaptureEnvelope.from_mapping(envelope_data)
        decision = validate_offline_capability_capture(envelope, snapshot)
        payload = decision.to_dict()
        code = 0 if decision.compatible else 2
    except EaglegateExactnessError as exc:
        payload = {
            "capture_contract_id": EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID,
            "ok": False,
            "fault": "invalid_bundle",
            "message": str(exc),
            "serving_effect": "target_only",
            "runtime_imported_by_tds": False,
            "model_invoked": False,
            "inference_performed": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
        }
        code = 2
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        state = "READY" if payload.get("compatible") else "TARGET-ONLY"
        print(f"Eaglegate offline capture: {state}")
        print(json.dumps(payload, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY",
    "EAGLEGATE_OFFLINE_CAPTURE_BUNDLE_ID",
    "EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID",
    "EAGLEGATE_VLLM_EAGLE_PROVIDER_ID",
    "OfflineCapabilityCaptureEnvelope",
    "OfflineCaptureAuthorityBoundary",
    "OfflineCaptureDecision",
    "OfflineCaptureFault",
    "capture_envelope_to_mapping",
    "main",
    "provider_snapshot_payload_root",
    "validate_offline_capability_capture",
]

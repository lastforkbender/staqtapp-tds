"""Mechanical witness corroboration for immutable offline capability captures.

TDS compares supplied, content-free artifacts only. It does not import a runtime,
connect to a service, verify a cryptographic signature, prove witness
independence, claim metadata truth, or acquire execution authority.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .exactness_common import (
    EaglegateExactnessError,
    UINT32_MAX,
    canonical_root,
    require_ascii,
    require_int,
    require_root,
)
from .offline_capture import (
    OfflineCapabilityCaptureEnvelope,
    OfflineCaptureDecision,
    validate_offline_capability_capture,
)

EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID = (
    "tds-eaglegate-capture-attestation-v1"
)
EAGLEGATE_CAPTURE_ATTESTATION_FORMAT_VERSION = 1
EAGLEGATE_CAPTURE_ATTESTATION_MIN_WITNESSES = 2


class CaptureAttestationDecision(str, Enum):
    CORROBORATED = "corroborated"
    TARGET_ONLY = "target_only"


class CaptureObservationState(str, Enum):
    RECEIVED = "received"
    CORROBORATED = "corroborated"
    RECORDED = "recorded"
    RETIRED = "retired"
    QUARANTINED = "quarantined"


_ALLOWED_RECEIPT_TRANSITIONS: Mapping[
    CaptureObservationState, frozenset[CaptureObservationState]
] = {
    CaptureObservationState.RECEIVED: frozenset(
        {
            CaptureObservationState.CORROBORATED,
            CaptureObservationState.QUARANTINED,
        }
    ),
    CaptureObservationState.CORROBORATED: frozenset(
        {CaptureObservationState.RECORDED}
    ),
    CaptureObservationState.RECORDED: frozenset(
        {CaptureObservationState.RETIRED}
    ),
    CaptureObservationState.RETIRED: frozenset(),
    CaptureObservationState.QUARANTINED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class CaptureAttestationAuthorityBoundary:
    may_import_runtime: bool = False
    may_connect_network: bool = False
    may_submit_request: bool = False
    may_load_model: bool = False
    may_allocate_kv: bool = False
    may_generate_tokens: bool = False
    may_verify_tokens: bool = False
    may_commit_tokens: bool = False
    may_verify_cryptographic_signature: bool = False
    may_claim_witness_independence: bool = False
    may_claim_metadata_truth: bool = False
    may_record_mechanical_corroboration: bool = True
    may_activate: bool = False
    target_only_default: bool = True

    def __post_init__(self) -> None:
        expected = {
            "may_import_runtime": False,
            "may_connect_network": False,
            "may_submit_request": False,
            "may_load_model": False,
            "may_allocate_kv": False,
            "may_generate_tokens": False,
            "may_verify_tokens": False,
            "may_commit_tokens": False,
            "may_verify_cryptographic_signature": False,
            "may_claim_witness_independence": False,
            "may_claim_metadata_truth": False,
            "may_record_mechanical_corroboration": True,
            "may_activate": False,
            "target_only_default": True,
        }
        if asdict(self) != expected:
            raise EaglegateExactnessError(
                "capture attestation authority cannot be widened"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": (
                EAGLEGATE_CAPTURE_ATTESTATION_FORMAT_VERSION
            ),
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return canonical_root(
            "capture-attestation-authority", self.canonical_dict()
        )


EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY = (
    CaptureAttestationAuthorityBoundary()
)


@dataclass(frozen=True, slots=True)
class CaptureReadOnlyStatusSnapshot:
    provider_id: str
    capture_root: str
    provider_snapshot_payload_root: str
    adapter_identity_root: str
    runtime_distribution_root: str
    package_metadata_root: str
    source_commit_root: str
    environment_root: str
    service_instance_root: str
    status_exporter_root: str
    snapshot_generation: int
    read_only_export: bool = True
    metadata_only: bool = True
    model_loaded: bool = False
    inference_performed: bool = False

    def __post_init__(self) -> None:
        require_ascii("provider_id", self.provider_id)
        for name in (
            "capture_root",
            "provider_snapshot_payload_root",
            "adapter_identity_root",
            "runtime_distribution_root",
            "package_metadata_root",
            "source_commit_root",
            "environment_root",
            "service_instance_root",
            "status_exporter_root",
        ):
            require_root(name, getattr(self, name))
        require_int(
            "snapshot_generation", self.snapshot_generation, 0, UINT32_MAX
        )
        fixed = {
            "read_only_export": True,
            "metadata_only": True,
            "model_loaded": False,
            "inference_performed": False,
        }
        observed = {name: getattr(self, name) for name in fixed}
        if observed != fixed:
            raise EaglegateExactnessError(
                "status snapshot must remain read-only metadata"
            )

    def comparable_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capture_root": self.capture_root,
            "provider_snapshot_payload_root": (
                self.provider_snapshot_payload_root
            ),
            "adapter_identity_root": self.adapter_identity_root,
            "runtime_distribution_root": self.runtime_distribution_root,
            "package_metadata_root": self.package_metadata_root,
            "source_commit_root": self.source_commit_root,
            "environment_root": self.environment_root,
        }

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": (
                EAGLEGATE_CAPTURE_ATTESTATION_FORMAT_VERSION
            ),
            **self.comparable_dict(),
            "service_instance_root": self.service_instance_root,
            "status_exporter_root": self.status_exporter_root,
            "snapshot_generation": self.snapshot_generation,
            "read_only_export": True,
            "metadata_only": True,
            "model_loaded": False,
            "inference_performed": False,
            "runtime_imported_by_tds": False,
            "network_connection_created_by_tds": False,
        }

    @property
    def snapshot_root(self) -> str:
        return canonical_root("capture-read-only-status", self.canonical_dict())

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "CaptureReadOnlyStatusSnapshot":
        if not isinstance(value, Mapping):
            raise EaglegateExactnessError("status snapshot must be an object")
        fields = dict(value)
        unknown = sorted(set(fields) - set(cls.__dataclass_fields__))
        if unknown:
            raise EaglegateExactnessError(
                f"unknown status snapshot fields: {unknown}"
            )
        try:
            return cls(**fields)
        except TypeError as exc:
            raise EaglegateExactnessError(
                f"invalid status snapshot fields: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class CaptureWitnessObservation:
    witness_id: str
    witness_tool_root: str
    capture_root: str
    provider_snapshot_payload_root: str
    adapter_identity_root: str
    status_snapshot_root: str
    matched: bool
    mismatch_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        require_ascii("witness_id", self.witness_id)
        for name in (
            "witness_tool_root",
            "capture_root",
            "provider_snapshot_payload_root",
            "adapter_identity_root",
            "status_snapshot_root",
        ):
            require_root(name, getattr(self, name))
        if not isinstance(self.matched, bool):
            raise EaglegateExactnessError("matched must be a boolean")
        if not isinstance(self.mismatch_fields, tuple):
            raise EaglegateExactnessError("mismatch_fields must be a tuple")
        normalized = tuple(sorted(self.mismatch_fields))
        if normalized != self.mismatch_fields or len(set(normalized)) != len(
            normalized
        ):
            raise EaglegateExactnessError(
                "mismatch_fields must be unique and sorted"
            )
        for field in self.mismatch_fields:
            require_ascii("mismatch field", field)
        if self.matched != (not self.mismatch_fields):
            raise EaglegateExactnessError(
                "matched must agree with mismatch_fields"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": (
                EAGLEGATE_CAPTURE_ATTESTATION_FORMAT_VERSION
            ),
            "witness_id": self.witness_id,
            "witness_tool_root": self.witness_tool_root,
            "capture_root": self.capture_root,
            "provider_snapshot_payload_root": (
                self.provider_snapshot_payload_root
            ),
            "adapter_identity_root": self.adapter_identity_root,
            "status_snapshot_root": self.status_snapshot_root,
            "matched": self.matched,
            "mismatch_fields": list(self.mismatch_fields),
            "runtime_imported_by_tds": False,
            "network_connection_created_by_tds": False,
            "cryptographic_signature_verified": False,
            "witness_independence_proven": False,
            "metadata_truth_claimed": False,
        }

    @property
    def observation_root(self) -> str:
        return canonical_root("capture-witness", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CaptureAttestationBundle:
    capture_root: str
    provider_snapshot_payload_root: str
    adapter_identity_root: str
    observations: tuple[CaptureWitnessObservation, ...]
    required_witnesses: int = EAGLEGATE_CAPTURE_ATTESTATION_MIN_WITNESSES

    def __post_init__(self) -> None:
        for name in (
            "capture_root",
            "provider_snapshot_payload_root",
            "adapter_identity_root",
        ):
            require_root(name, getattr(self, name))
        require_int("required_witnesses", self.required_witnesses, 2, 32)
        if not isinstance(self.observations, tuple):
            raise EaglegateExactnessError("observations must be a tuple")
        if len(self.observations) < self.required_witnesses:
            raise EaglegateExactnessError(
                "capture attestation requires witness quorum"
            )
        if any(
            not isinstance(observation, CaptureWitnessObservation)
            for observation in self.observations
        ):
            raise EaglegateExactnessError("invalid witness observation")
        witness_ids = [item.witness_id for item in self.observations]
        tool_roots = [item.witness_tool_root for item in self.observations]
        if len(set(witness_ids)) != len(witness_ids):
            raise EaglegateExactnessError("duplicate witness identity")
        if len(set(tool_roots)) != len(tool_roots):
            raise EaglegateExactnessError("duplicate witness tool identity")
        roots = [item.observation_root for item in self.observations]
        if roots != sorted(roots):
            raise EaglegateExactnessError(
                "observations must be sorted by observation root"
            )
        for item in self.observations:
            if item.capture_root != self.capture_root:
                raise EaglegateExactnessError("witness capture root mismatch")
            if (
                item.provider_snapshot_payload_root
                != self.provider_snapshot_payload_root
            ):
                raise EaglegateExactnessError(
                    "witness provider payload root mismatch"
                )
            if item.adapter_identity_root != self.adapter_identity_root:
                raise EaglegateExactnessError(
                    "witness adapter identity root mismatch"
                )

    @property
    def decision(self) -> CaptureAttestationDecision:
        return (
            CaptureAttestationDecision.CORROBORATED
            if all(item.matched for item in self.observations)
            else CaptureAttestationDecision.TARGET_ONLY
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": (
                EAGLEGATE_CAPTURE_ATTESTATION_FORMAT_VERSION
            ),
            "capture_root": self.capture_root,
            "provider_snapshot_payload_root": (
                self.provider_snapshot_payload_root
            ),
            "adapter_identity_root": self.adapter_identity_root,
            "required_witnesses": self.required_witnesses,
            "witness_count": len(self.observations),
            "decision": self.decision.value,
            "observation_roots": [
                item.observation_root for item in self.observations
            ],
            "authority_root": (
                EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY.authority_root
            ),
            "cryptographic_signature_verified": False,
            "witness_independence_proven": False,
            "metadata_truth_claimed": False,
            "real_runtime_qualified": False,
            "activation_authority": False,
        }

    @property
    def attestation_root(self) -> str:
        return canonical_root("capture-attestation", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CaptureObservationReceipt:
    sequence: int
    state: CaptureObservationState
    capture_root: str
    provider_snapshot_payload_root: str
    adapter_identity_root: str
    attestation_root: str
    previous_receipt_root: str = ""

    def __post_init__(self) -> None:
        require_int("sequence", self.sequence, 0, UINT32_MAX)
        if not isinstance(self.state, CaptureObservationState):
            raise EaglegateExactnessError(
                "state must be CaptureObservationState"
            )
        for name in (
            "capture_root",
            "provider_snapshot_payload_root",
            "adapter_identity_root",
            "attestation_root",
        ):
            require_root(name, getattr(self, name))
        if self.previous_receipt_root:
            require_root("previous_receipt_root", self.previous_receipt_root)
        if self.sequence == 0:
            if self.state is not CaptureObservationState.RECEIVED:
                raise EaglegateExactnessError(
                    "initial receipt must be received"
                )
            if self.previous_receipt_root:
                raise EaglegateExactnessError(
                    "initial receipt cannot have predecessor"
                )
        elif not self.previous_receipt_root:
            raise EaglegateExactnessError(
                "non-initial receipt requires predecessor root"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": (
                EAGLEGATE_CAPTURE_ATTESTATION_FORMAT_VERSION
            ),
            "sequence": self.sequence,
            "state": self.state.value,
            "capture_root": self.capture_root,
            "provider_snapshot_payload_root": (
                self.provider_snapshot_payload_root
            ),
            "adapter_identity_root": self.adapter_identity_root,
            "attestation_root": self.attestation_root,
            "previous_receipt_root": self.previous_receipt_root,
            "activation_authority": False,
            "production_execution_authority": False,
        }

    @property
    def receipt_root(self) -> str:
        return canonical_root("capture-observation-receipt", self.canonical_dict())


def compare_capture_status(
    envelope: OfflineCapabilityCaptureEnvelope,
    decision: OfflineCaptureDecision,
    status: CaptureReadOnlyStatusSnapshot,
    *,
    witness_id: str,
    witness_tool_root: str,
) -> CaptureWitnessObservation:
    if not isinstance(envelope, OfflineCapabilityCaptureEnvelope):
        raise EaglegateExactnessError("envelope has wrong type")
    if not isinstance(decision, OfflineCaptureDecision):
        raise EaglegateExactnessError("capture decision has wrong type")
    if not isinstance(status, CaptureReadOnlyStatusSnapshot):
        raise EaglegateExactnessError("status has wrong type")
    require_ascii("witness_id", witness_id)
    require_root("witness_tool_root", witness_tool_root)
    expected = {
        "provider_id": envelope.provider_id,
        "capture_root": envelope.capture_root,
        "provider_snapshot_payload_root": (
            decision.provider_snapshot_payload_root
        ),
        "adapter_identity_root": decision.adapter_identity_root,
        "runtime_distribution_root": envelope.runtime_distribution_root,
        "package_metadata_root": envelope.package_metadata_root,
        "source_commit_root": envelope.source_commit_root,
        "environment_root": envelope.environment_root,
    }
    observed = status.comparable_dict()
    mismatch_fields = tuple(
        sorted(
            field
            for field in expected
            if expected[field] != observed[field]
        )
    )
    return CaptureWitnessObservation(
        witness_id=witness_id,
        witness_tool_root=witness_tool_root,
        capture_root=envelope.capture_root,
        provider_snapshot_payload_root=decision.provider_snapshot_payload_root,
        adapter_identity_root=decision.adapter_identity_root,
        status_snapshot_root=status.snapshot_root,
        matched=not mismatch_fields,
        mismatch_fields=mismatch_fields,
    )


def canonicalize_observations(
    observations: Sequence[CaptureWitnessObservation],
) -> tuple[CaptureWitnessObservation, ...]:
    values = tuple(observations)
    if any(not isinstance(item, CaptureWitnessObservation) for item in values):
        raise EaglegateExactnessError("invalid witness observation")
    return tuple(sorted(values, key=lambda item: item.observation_root))


def initial_observation_receipt(
    bundle: CaptureAttestationBundle,
) -> CaptureObservationReceipt:
    if not isinstance(bundle, CaptureAttestationBundle):
        raise EaglegateExactnessError("bundle has wrong type")
    return CaptureObservationReceipt(
        sequence=0,
        state=CaptureObservationState.RECEIVED,
        capture_root=bundle.capture_root,
        provider_snapshot_payload_root=bundle.provider_snapshot_payload_root,
        adapter_identity_root=bundle.adapter_identity_root,
        attestation_root=bundle.attestation_root,
    )


def next_observation_receipt(
    previous: CaptureObservationReceipt,
    state: CaptureObservationState,
) -> CaptureObservationReceipt:
    if not isinstance(previous, CaptureObservationReceipt):
        raise EaglegateExactnessError(
            "previous must be CaptureObservationReceipt"
        )
    if not isinstance(state, CaptureObservationState):
        raise EaglegateExactnessError("state has wrong type")
    if state not in _ALLOWED_RECEIPT_TRANSITIONS[previous.state]:
        raise EaglegateExactnessError(
            "illegal capture observation transition"
        )
    return CaptureObservationReceipt(
        sequence=previous.sequence + 1,
        state=state,
        capture_root=previous.capture_root,
        provider_snapshot_payload_root=(
            previous.provider_snapshot_payload_root
        ),
        adapter_identity_root=previous.adapter_identity_root,
        attestation_root=previous.attestation_root,
        previous_receipt_root=previous.receipt_root,
    )


def validate_observation_chain(
    receipts: Sequence[CaptureObservationReceipt],
) -> tuple[CaptureObservationReceipt, ...]:
    chain = tuple(receipts)
    if not chain:
        raise EaglegateExactnessError("observation chain cannot be empty")
    if any(not isinstance(item, CaptureObservationReceipt) for item in chain):
        raise EaglegateExactnessError("observation chain contains invalid receipt")
    first = chain[0]
    if first.sequence != 0 or first.state is not CaptureObservationState.RECEIVED:
        raise EaglegateExactnessError("observation chain must start received")
    for expected_sequence, receipt in enumerate(chain):
        if receipt.sequence != expected_sequence:
            raise EaglegateExactnessError("observation sequence is not contiguous")
        if (
            receipt.capture_root != first.capture_root
            or receipt.provider_snapshot_payload_root
            != first.provider_snapshot_payload_root
            or receipt.adapter_identity_root != first.adapter_identity_root
            or receipt.attestation_root != first.attestation_root
        ):
            raise EaglegateExactnessError(
                "observation receipt identity changed"
            )
        if expected_sequence:
            previous = chain[expected_sequence - 1]
            if receipt.previous_receipt_root != previous.receipt_root:
                raise EaglegateExactnessError(
                    "observation predecessor root mismatch"
                )
            if receipt.state not in _ALLOWED_RECEIPT_TRANSITIONS[previous.state]:
                raise EaglegateExactnessError(
                    "illegal capture observation transition"
                )
    return chain


def record_attestation_bundle(
    bundle: CaptureAttestationBundle,
) -> tuple[CaptureObservationReceipt, ...]:
    received = initial_observation_receipt(bundle)
    if bundle.decision is CaptureAttestationDecision.TARGET_ONLY:
        quarantined = next_observation_receipt(
            received, CaptureObservationState.QUARANTINED
        )
        return validate_observation_chain((received, quarantined))
    corroborated = next_observation_receipt(
        received, CaptureObservationState.CORROBORATED
    )
    recorded = next_observation_receipt(
        corroborated, CaptureObservationState.RECORDED
    )
    return validate_observation_chain((received, corroborated, recorded))


def _read_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EaglegateExactnessError(f"could not read {source}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise EaglegateExactnessError(f"{source} must contain one object")
    return dict(value)


def _load_capture_bundle(path: str | Path) -> tuple[
    OfflineCapabilityCaptureEnvelope, Mapping[str, Any], OfflineCaptureDecision
]:
    value = _read_object(path)
    unknown = sorted(set(value) - {"envelope", "provider_snapshot"})
    if unknown:
        raise EaglegateExactnessError(
            f"unknown capture bundle fields: {unknown}"
        )
    envelope_value = value.get("envelope")
    snapshot_value = value.get("provider_snapshot")
    if not isinstance(envelope_value, Mapping) or not isinstance(
        snapshot_value, Mapping
    ):
        raise EaglegateExactnessError(
            "capture bundle requires envelope and provider_snapshot"
        )
    envelope = OfflineCapabilityCaptureEnvelope.from_mapping(envelope_value)
    decision = validate_offline_capability_capture(envelope, snapshot_value)
    return envelope, snapshot_value, decision


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="staqtapp-tds-eaglegate-capture-witness"
    )
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--witness-id", required=True)
    parser.add_argument("--witness-tool-root", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        envelope, _, decision = _load_capture_bundle(args.bundle)
        if not decision.compatible:
            raise EaglegateExactnessError(
                "capture bundle is not compatible for witness comparison"
            )
        status = CaptureReadOnlyStatusSnapshot.from_mapping(
            _read_object(args.status)
        )
        observation = compare_capture_status(
            envelope,
            decision,
            status,
            witness_id=args.witness_id,
            witness_tool_root=args.witness_tool_root,
        )
        payload = {
            **observation.canonical_dict(),
            "observation_root": observation.observation_root,
            "serving_effect": "target_only",
            "single_witness_only": True,
            "quorum_satisfied": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
        }
        code = 0 if observation.matched else 2
    except EaglegateExactnessError as exc:
        payload = {
            "attestation_contract_id": (
                EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID
            ),
            "ok": False,
            "fault": "invalid_observation",
            "message": str(exc),
            "serving_effect": "target_only",
            "single_witness_only": True,
            "quorum_satisfied": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
        }
        code = 2
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        state = "MATCH" if payload.get("matched") else "TARGET-ONLY"
        print(f"Eaglegate capture witness: {state}")
        print(json.dumps(payload, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY",
    "EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID",
    "EAGLEGATE_CAPTURE_ATTESTATION_FORMAT_VERSION",
    "EAGLEGATE_CAPTURE_ATTESTATION_MIN_WITNESSES",
    "CaptureAttestationAuthorityBoundary",
    "CaptureAttestationBundle",
    "CaptureAttestationDecision",
    "CaptureObservationReceipt",
    "CaptureObservationState",
    "CaptureReadOnlyStatusSnapshot",
    "CaptureWitnessObservation",
    "canonicalize_observations",
    "compare_capture_status",
    "initial_observation_receipt",
    "main",
    "next_observation_receipt",
    "record_attestation_bundle",
    "validate_observation_chain",
]

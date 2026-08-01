"""Off-path witness corroboration and append-only shadow observation receipts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Sequence

from .exactness_common import (
    EaglegateExactnessError,
    UINT32_MAX,
    canonical_root,
    require_ascii,
    require_int,
    require_root,
)

EAGLEGATE_ATTESTATION_CONTRACT_ID = "tds-eaglegate-shadow-attestation-v1"
EAGLEGATE_ATTESTATION_FORMAT_VERSION = 1
EAGLEGATE_ATTESTATION_MIN_WITNESSES = 2


class AttestationDecision(str, Enum):
    CORROBORATED = "corroborated"
    TARGET_ONLY = "target_only"


class ObservationState(str, Enum):
    RECEIVED = "received"
    CORROBORATED = "corroborated"
    RECORDED = "recorded"
    RETIRED = "retired"
    QUARANTINED = "quarantined"


_ALLOWED_RECEIPT_TRANSITIONS = {
    ObservationState.RECEIVED: {
        ObservationState.CORROBORATED,
        ObservationState.QUARANTINED,
    },
    ObservationState.CORROBORATED: {ObservationState.RECORDED},
    ObservationState.RECORDED: {ObservationState.RETIRED},
    ObservationState.RETIRED: set(),
    ObservationState.QUARANTINED: set(),
}


@dataclass(frozen=True, slots=True)
class EaglegateAttestationAuthorityBoundary:
    may_import_runtime: bool = False
    may_connect_network: bool = False
    may_submit_request: bool = False
    may_load_model: bool = False
    may_allocate_kv: bool = False
    may_generate_tokens: bool = False
    may_verify_tokens: bool = False
    may_commit_tokens: bool = False
    may_activate: bool = False
    may_verify_cryptographic_signature: bool = False
    may_claim_witness_independence: bool = False
    may_claim_metadata_truth: bool = False
    may_record_mechanical_corroboration: bool = True
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
            "may_activate": False,
            "may_verify_cryptographic_signature": False,
            "may_claim_witness_independence": False,
            "may_claim_metadata_truth": False,
            "may_record_mechanical_corroboration": True,
            "target_only_default": True,
        }
        if asdict(self) != expected:
            raise EaglegateExactnessError(
                "attestation authority cannot be widened"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": EAGLEGATE_ATTESTATION_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def authority_root(self) -> str:
        return canonical_root("attestation-authority", self.canonical_dict())


EAGLEGATE_ATTESTATION_AUTHORITY = EaglegateAttestationAuthorityBoundary()


@dataclass(frozen=True, slots=True)
class VLLMReadOnlyStatusSnapshot:
    runtime_version: str
    method: str
    foundation_identity_root: str
    target_model_root: str
    tokenizer_root: str
    draft_model_root: str
    adapter_build_root: str
    target_verifier_root: str
    rng_contract_root: str
    sampler_order_root: str
    logits_processor_order_root: str
    termination_contract_root: str
    kv_allocator_root: str
    numerical_kernel_root: str
    deadline_contract_root: str
    num_speculative_tokens: int
    draft_tensor_parallel_size: int
    target_tensor_parallel_size: int
    max_model_len: int
    parallel_drafting: bool
    rejection_sample_method: str
    service_instance_root: str
    status_exporter_root: str
    snapshot_generation: int
    runtime_name: str = "vllm"
    read_only_export: bool = True

    def __post_init__(self) -> None:
        if self.runtime_name != "vllm":
            raise EaglegateExactnessError("status fixture accepts only vllm")
        require_ascii("runtime_version", self.runtime_version)
        if self.method not in ("eagle", "eagle3"):
            raise EaglegateExactnessError("status method must be eagle or eagle3")
        if self.rejection_sample_method not in (
            "strict",
            "probabilistic",
            "synthetic",
        ):
            raise EaglegateExactnessError("unsupported status rejection method")
        for name in (
            "foundation_identity_root",
            "target_model_root",
            "tokenizer_root",
            "draft_model_root",
            "adapter_build_root",
            "target_verifier_root",
            "rng_contract_root",
            "sampler_order_root",
            "logits_processor_order_root",
            "termination_contract_root",
            "kv_allocator_root",
            "numerical_kernel_root",
            "deadline_contract_root",
            "service_instance_root",
            "status_exporter_root",
        ):
            require_root(name, getattr(self, name))
        require_int("num_speculative_tokens", self.num_speculative_tokens, 1, 64)
        require_int(
            "draft_tensor_parallel_size",
            self.draft_tensor_parallel_size,
            1,
            1024,
        )
        require_int(
            "target_tensor_parallel_size",
            self.target_tensor_parallel_size,
            1,
            1024,
        )
        require_int("max_model_len", self.max_model_len, 1, UINT32_MAX)
        require_int("snapshot_generation", self.snapshot_generation, 0, UINT32_MAX)
        if not isinstance(self.parallel_drafting, bool):
            raise EaglegateExactnessError("parallel_drafting must be boolean")
        if self.read_only_export is not True:
            raise EaglegateExactnessError("status snapshot must be read-only")

    def comparable_dict(self) -> dict[str, Any]:
        return {
            "runtime_name": self.runtime_name,
            "runtime_version": self.runtime_version,
            "method": self.method,
            "foundation_identity_root": self.foundation_identity_root,
            "target_model_root": self.target_model_root,
            "tokenizer_root": self.tokenizer_root,
            "draft_model_root": self.draft_model_root,
            "adapter_build_root": self.adapter_build_root,
            "target_verifier_root": self.target_verifier_root,
            "rng_contract_root": self.rng_contract_root,
            "sampler_order_root": self.sampler_order_root,
            "logits_processor_order_root": self.logits_processor_order_root,
            "termination_contract_root": self.termination_contract_root,
            "kv_allocator_root": self.kv_allocator_root,
            "numerical_kernel_root": self.numerical_kernel_root,
            "deadline_contract_root": self.deadline_contract_root,
            "num_speculative_tokens": self.num_speculative_tokens,
            "draft_tensor_parallel_size": self.draft_tensor_parallel_size,
            "target_tensor_parallel_size": self.target_tensor_parallel_size,
            "max_model_len": self.max_model_len,
            "parallel_drafting": self.parallel_drafting,
            "rejection_sample_method": self.rejection_sample_method,
        }

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": EAGLEGATE_ATTESTATION_FORMAT_VERSION,
            **self.comparable_dict(),
            "service_instance_root": self.service_instance_root,
            "status_exporter_root": self.status_exporter_root,
            "snapshot_generation": self.snapshot_generation,
            "read_only_export": True,
            "runtime_imported_by_tds": False,
            "network_connection_created_by_tds": False,
        }

    @property
    def snapshot_root(self) -> str:
        return canonical_root("vllm-read-only-status", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CapabilityWitnessObservation:
    witness_id: str
    witness_tool_root: str
    metadata_root: str
    shadow_report_root: str
    status_snapshot_root: str
    service_instance_root: str
    status_exporter_root: str
    snapshot_generation: int
    matched: bool
    mismatch_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        require_ascii("witness_id", self.witness_id)
        for name in (
            "witness_tool_root",
            "metadata_root",
            "shadow_report_root",
            "status_snapshot_root",
            "service_instance_root",
            "status_exporter_root",
        ):
            require_root(name, getattr(self, name))
        require_int("snapshot_generation", self.snapshot_generation, 0, UINT32_MAX)
        if not isinstance(self.matched, bool):
            raise EaglegateExactnessError("matched must be boolean")
        if not isinstance(self.mismatch_fields, tuple):
            raise EaglegateExactnessError("mismatch_fields must be a tuple")
        normalized = tuple(sorted(self.mismatch_fields))
        if normalized != self.mismatch_fields or len(set(normalized)) != len(normalized):
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
            "attestation_contract_id": EAGLEGATE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": EAGLEGATE_ATTESTATION_FORMAT_VERSION,
            "witness_id": self.witness_id,
            "witness_tool_root": self.witness_tool_root,
            "metadata_root": self.metadata_root,
            "shadow_report_root": self.shadow_report_root,
            "status_snapshot_root": self.status_snapshot_root,
            "service_instance_root": self.service_instance_root,
            "status_exporter_root": self.status_exporter_root,
            "snapshot_generation": self.snapshot_generation,
            "matched": self.matched,
            "mismatch_fields": list(self.mismatch_fields),
            "runtime_imported_by_tds": False,
            "network_connection_created_by_tds": False,
            "cryptographic_signature_verified": False,
            "witness_independence_proven": False,
            "snapshot_freshness_proven": False,
        }

    @property
    def observation_root(self) -> str:
        return canonical_root("capability-witness", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CapabilityAttestationBundle:
    metadata_root: str
    shadow_report_root: str
    observations: tuple[CapabilityWitnessObservation, ...]
    required_witnesses: int = EAGLEGATE_ATTESTATION_MIN_WITNESSES

    def __post_init__(self) -> None:
        require_root("metadata_root", self.metadata_root)
        require_root("shadow_report_root", self.shadow_report_root)
        require_int("required_witnesses", self.required_witnesses, 2, 32)
        if not isinstance(self.observations, tuple):
            raise EaglegateExactnessError("observations must be a tuple")
        if len(self.observations) < self.required_witnesses:
            raise EaglegateExactnessError("attestation requires witness quorum")
        if any(
            not isinstance(observation, CapabilityWitnessObservation)
            for observation in self.observations
        ):
            raise EaglegateExactnessError("invalid witness observation")
        witness_ids = [observation.witness_id for observation in self.observations]
        tool_roots = [observation.witness_tool_root for observation in self.observations]
        if len(set(witness_ids)) != len(witness_ids):
            raise EaglegateExactnessError("duplicate witness identity")
        if len(set(tool_roots)) != len(tool_roots):
            raise EaglegateExactnessError("duplicate witness tool identity")
        observation_roots = [
            observation.observation_root for observation in self.observations
        ]
        if observation_roots != sorted(observation_roots):
            raise EaglegateExactnessError(
                "observations must be canonically sorted by root"
            )
        for observation in self.observations:
            if observation.metadata_root != self.metadata_root:
                raise EaglegateExactnessError("witness metadata root mismatch")
            if observation.shadow_report_root != self.shadow_report_root:
                raise EaglegateExactnessError("witness shadow root mismatch")
        service_roots = {
            observation.service_instance_root for observation in self.observations
        }
        generations = {
            observation.snapshot_generation for observation in self.observations
        }
        if len(service_roots) != 1:
            raise EaglegateExactnessError("witness service instance mismatch")
        if len(generations) != 1:
            raise EaglegateExactnessError("witness snapshot generation mismatch")

    @property
    def decision(self) -> AttestationDecision:
        return (
            AttestationDecision.CORROBORATED
            if all(observation.matched for observation in self.observations)
            else AttestationDecision.TARGET_ONLY
        )

    @property
    def service_instance_root(self) -> str:
        return self.observations[0].service_instance_root

    @property
    def snapshot_generation(self) -> int:
        return self.observations[0].snapshot_generation

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": EAGLEGATE_ATTESTATION_FORMAT_VERSION,
            "metadata_root": self.metadata_root,
            "shadow_report_root": self.shadow_report_root,
            "service_instance_root": self.service_instance_root,
            "snapshot_generation": self.snapshot_generation,
            "required_witnesses": self.required_witnesses,
            "witness_count": len(self.observations),
            "decision": self.decision.value,
            "observation_roots": [
                observation.observation_root for observation in self.observations
            ],
            "authority_root": EAGLEGATE_ATTESTATION_AUTHORITY.authority_root,
            "cryptographic_signature_verified": False,
            "witness_independence_proven": False,
            "snapshot_freshness_proven": False,
            "metadata_truth_claimed": False,
            "real_runtime_qualified": False,
            "activation_authority": False,
        }

    @property
    def attestation_root(self) -> str:
        return canonical_root("capability-attestation", self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ShadowObservationReceipt:
    sequence: int
    state: ObservationState
    metadata_root: str
    shadow_report_root: str
    attestation_root: str
    previous_receipt_root: str = ""

    def __post_init__(self) -> None:
        require_int("sequence", self.sequence, 0, UINT32_MAX)
        if not isinstance(self.state, ObservationState):
            raise EaglegateExactnessError("state must be ObservationState")
        for name in ("metadata_root", "shadow_report_root", "attestation_root"):
            require_root(name, getattr(self, name))
        if self.previous_receipt_root:
            require_root("previous_receipt_root", self.previous_receipt_root)
        if self.sequence == 0:
            if self.state is not ObservationState.RECEIVED:
                raise EaglegateExactnessError("initial receipt must be received")
            if self.previous_receipt_root:
                raise EaglegateExactnessError(
                    "initial receipt cannot have a predecessor"
                )
        elif not self.previous_receipt_root:
            raise EaglegateExactnessError(
                "non-initial receipt requires predecessor root"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": EAGLEGATE_ATTESTATION_CONTRACT_ID,
            "attestation_format_version": EAGLEGATE_ATTESTATION_FORMAT_VERSION,
            "sequence": self.sequence,
            "state": self.state.value,
            "metadata_root": self.metadata_root,
            "shadow_report_root": self.shadow_report_root,
            "attestation_root": self.attestation_root,
            "previous_receipt_root": self.previous_receipt_root,
            "activation_authority": False,
            "production_execution_authority": False,
        }

    @property
    def receipt_root(self) -> str:
        return canonical_root("shadow-observation-receipt", self.canonical_dict())


def next_observation_receipt(
    previous: ShadowObservationReceipt,
    state: ObservationState,
) -> ShadowObservationReceipt:
    if not isinstance(previous, ShadowObservationReceipt):
        raise EaglegateExactnessError("previous must be ShadowObservationReceipt")
    if not isinstance(state, ObservationState):
        raise EaglegateExactnessError("state must be ObservationState")
    if state not in _ALLOWED_RECEIPT_TRANSITIONS[previous.state]:
        raise EaglegateExactnessError("illegal observation receipt transition")
    return ShadowObservationReceipt(
        sequence=previous.sequence + 1,
        state=state,
        metadata_root=previous.metadata_root,
        shadow_report_root=previous.shadow_report_root,
        attestation_root=previous.attestation_root,
        previous_receipt_root=previous.receipt_root,
    )


def validate_observation_chain(
    receipts: Sequence[ShadowObservationReceipt],
) -> tuple[ShadowObservationReceipt, ...]:
    chain = tuple(receipts)
    if not chain:
        raise EaglegateExactnessError("observation chain cannot be empty")
    if any(not isinstance(receipt, ShadowObservationReceipt) for receipt in chain):
        raise EaglegateExactnessError("observation chain contains invalid receipt")
    if chain[0].sequence != 0 or chain[0].state is not ObservationState.RECEIVED:
        raise EaglegateExactnessError("observation chain has invalid initial receipt")
    for previous, current in zip(chain, chain[1:]):
        if current.sequence != previous.sequence + 1:
            raise EaglegateExactnessError("observation sequence is not contiguous")
        if current.previous_receipt_root != previous.receipt_root:
            raise EaglegateExactnessError("observation predecessor root mismatch")
        if current.state not in _ALLOWED_RECEIPT_TRANSITIONS[previous.state]:
            raise EaglegateExactnessError("illegal observation chain transition")
        if (
            current.metadata_root != previous.metadata_root
            or current.shadow_report_root != previous.shadow_report_root
            or current.attestation_root != previous.attestation_root
        ):
            raise EaglegateExactnessError("observation identity changed in chain")
    return chain


__all__ = [
    "AttestationDecision",
    "CapabilityAttestationBundle",
    "CapabilityWitnessObservation",
    "EAGLEGATE_ATTESTATION_AUTHORITY",
    "EAGLEGATE_ATTESTATION_CONTRACT_ID",
    "EAGLEGATE_ATTESTATION_FORMAT_VERSION",
    "EAGLEGATE_ATTESTATION_MIN_WITNESSES",
    "EaglegateAttestationAuthorityBoundary",
    "ObservationState",
    "ShadowObservationReceipt",
    "VLLMReadOnlyStatusSnapshot",
    "next_observation_receipt",
    "validate_observation_chain",
]

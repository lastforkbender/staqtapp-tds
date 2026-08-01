"""Generation Authority integration for Eaglegate ServingEpoch candidates.

The generic Generation Authority is the only durable publication authority.
Eaglegate's local TOML files express intent and its receipts express bounded
content-free evidence; neither creates a second ``CURRENT`` pointer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from typing import Any, Mapping

from staqtapp_tds.generation import (
    AtomicGenerationStore,
    GenerationCandidate,
    GenerationContractError,
    GenerationFault,
    GenerationLease,
    PublicationResult,
    bytes_root,
    canonical_json_bytes,
    canonical_root,
    require_root,
)

from .adapter_suite import (
    EaglegateAdapterConformanceReport,
    run_reference_adapter_conformance_suite,
)
from .contract import (
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
    EaglegateContractError,
    EaglegateEpochState,
    EaglegateFault,
    EaglegateMode,
    _canonical_root as _eaglegate_root,
)
from .evidence import EaglegateEpochReceipt, validate_epoch_transition
from .exactness_common import canonical_root as _exactness_root
from .exactness_suite import (
    EaglegateExactnessReport,
    run_reference_exactness_suite,
)
from .plans import (
    EaglegateQualificationSummary,
    EaglegateSpeculationEpoch,
    validate_qualification_for_epoch,
)

EAGLEGATE_SERVING_GENERATION_CONTRACT_ID = "tds-eaglegate-serving-generation-v1"
EAGLEGATE_SERVING_GENERATION_FORMAT_VERSION = 1
EAGLEGATE_SERVING_BINDING_PAYLOAD = "eaglegate.serving-binding"
EAGLEGATE_EPOCH_PAYLOAD = "eaglegate.epoch"
EAGLEGATE_QUALIFICATION_PAYLOAD = "eaglegate.exactness-qualification"
EAGLEGATE_EXACTNESS_REPORT_PAYLOAD = "eaglegate.exactness-report"
EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD = "eaglegate.qualification-bridge"
EAGLEGATE_ADAPTER_REPORT_PAYLOAD = "eaglegate.adapter-conformance"
EAGLEGATE_RECEIPTS_PAYLOAD = "eaglegate.epoch-receipts"

_PAYLOAD_NAMES = frozenset(
    {
        EAGLEGATE_SERVING_BINDING_PAYLOAD,
        EAGLEGATE_EPOCH_PAYLOAD,
        EAGLEGATE_QUALIFICATION_PAYLOAD,
        EAGLEGATE_EXACTNESS_REPORT_PAYLOAD,
        EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD,
        EAGLEGATE_ADAPTER_REPORT_PAYLOAD,
        EAGLEGATE_RECEIPTS_PAYLOAD,
    }
)
_ALLOWED_MODES = frozenset({EaglegateMode.TARGET_ONLY, EaglegateMode.SHADOW})


def _required_root(name: str, value: str) -> str:
    validated = require_root(name, value)
    assert validated is not None
    return validated


def _canonical_mapping(data: bytes, description: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationContractError(f"{description} is malformed") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != data:
        raise GenerationContractError(
            f"{description} is not canonical",
            fault=GenerationFault.NONCANONICAL,
        )
    return value


def _canonical_sequence(data: bytes, description: str) -> list[Any]:
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationContractError(f"{description} is malformed") from exc
    if not isinstance(value, list) or canonical_json_bytes(value) != data:
        raise GenerationContractError(
            f"{description} is not canonical",
            fault=GenerationFault.NONCANONICAL,
        )
    return value


@dataclass(frozen=True, slots=True)
class EaglegateServingEpochBinding:
    namespace: str
    storage_namespace: str
    storage_generation_root: str
    eaglegate_epoch_root: str
    eaglegate_policy_root: str
    target_runtime_identity_root: str
    exactness_qualification_root: str
    qualification_summary_root: str
    exactness_report_root: str
    adapter_conformance_root: str
    receipt_chain_root: str
    serving_mode: str
    parent_authority_generation_root: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not self.namespace:
            raise GenerationContractError("serving namespace is required")
        if not isinstance(self.storage_namespace, str) or not self.storage_namespace:
            raise GenerationContractError("storage namespace is required")
        if self.namespace == self.storage_namespace:
            raise GenerationContractError("serving and storage namespaces must differ")
        for name in (
            "storage_generation_root",
            "eaglegate_epoch_root",
            "eaglegate_policy_root",
            "target_runtime_identity_root",
            "exactness_qualification_root",
            "qualification_summary_root",
            "exactness_report_root",
            "adapter_conformance_root",
            "receipt_chain_root",
        ):
            _required_root(name, getattr(self, name))
        require_root(
            "parent_authority_generation_root",
            self.parent_authority_generation_root,
            optional=True,
        )
        if self.serving_mode not in {item.value for item in _ALLOWED_MODES}:
            raise GenerationContractError(
                "only target-only and qualification shadow modes are publishable",
                fault=GenerationFault.AUTHORITY_REJECTED,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_SERVING_GENERATION_CONTRACT_ID,
            "format_version": EAGLEGATE_SERVING_GENERATION_FORMAT_VERSION,
            **asdict(self),
        }

    @property
    def binding_root(self) -> str:
        return canonical_root("eaglegate-serving-binding", self.canonical_dict())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @classmethod
    def from_bytes(cls, data: bytes) -> "EaglegateServingEpochBinding":
        value = dict(_canonical_mapping(data, "Eaglegate serving binding"))
        if value.pop("contract_id", None) != EAGLEGATE_SERVING_GENERATION_CONTRACT_ID:
            raise GenerationContractError("Eaglegate serving contract mismatch")
        if value.pop("format_version", None) != EAGLEGATE_SERVING_GENERATION_FORMAT_VERSION:
            raise GenerationContractError("Eaglegate serving format mismatch")
        if set(value) != set(cls.__dataclass_fields__):
            raise GenerationContractError(
                "Eaglegate serving binding fields are not canonical",
                fault=GenerationFault.NONCANONICAL,
            )
        return cls(**value)


@dataclass(frozen=True, slots=True)
class EaglegateQualificationBridge:
    """Binds fixed core reports to one concrete identity and ordered plan set."""

    eaglegate_epoch_root: str
    identity_root: str
    plan_roots: tuple[str, ...]
    qualification_summary_root: str
    exactness_report_root: str
    adapter_conformance_root: str
    real_runtime_qualified: bool = False

    def __post_init__(self) -> None:
        for name in (
            "eaglegate_epoch_root",
            "identity_root",
            "qualification_summary_root",
            "exactness_report_root",
            "adapter_conformance_root",
        ):
            _required_root(name, getattr(self, name))
        if not isinstance(self.plan_roots, tuple) or not self.plan_roots:
            raise GenerationContractError("qualification bridge needs plan roots")
        for root in self.plan_roots:
            _required_root("plan_root", root)
        if len(set(self.plan_roots)) != len(self.plan_roots):
            raise GenerationContractError("qualification bridge plan roots repeat")
        if self.real_runtime_qualified is not False:
            raise GenerationContractError(
                "core reference reports cannot claim real-runtime qualification",
                fault=GenerationFault.AUTHORITY_REJECTED,
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_SERVING_GENERATION_CONTRACT_ID,
            "format_version": EAGLEGATE_SERVING_GENERATION_FORMAT_VERSION,
            "eaglegate_epoch_root": self.eaglegate_epoch_root,
            "identity_root": self.identity_root,
            "plan_roots": list(self.plan_roots),
            "qualification_summary_root": self.qualification_summary_root,
            "exactness_report_root": self.exactness_report_root,
            "adapter_conformance_root": self.adapter_conformance_root,
            "real_runtime_qualified": False,
        }

    @property
    def bridge_root(self) -> str:
        return canonical_root("eaglegate-qualification-bridge", self.canonical_dict())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @classmethod
    def from_bytes(cls, data: bytes) -> "EaglegateQualificationBridge":
        value = dict(_canonical_mapping(data, "Eaglegate qualification bridge"))
        if value.pop("contract_id", None) != EAGLEGATE_SERVING_GENERATION_CONTRACT_ID:
            raise GenerationContractError("qualification bridge contract mismatch")
        if value.pop("format_version", None) != EAGLEGATE_SERVING_GENERATION_FORMAT_VERSION:
            raise GenerationContractError("qualification bridge format mismatch")
        if set(value) != set(cls.__dataclass_fields__):
            raise GenerationContractError("qualification bridge fields are noncanonical")
        plans = value.get("plan_roots")
        if not isinstance(plans, list):
            raise GenerationContractError("qualification bridge plan roots malformed")
        value["plan_roots"] = tuple(plans)
        return cls(**value)


def _policy_plan_root(epoch: EaglegateSpeculationEpoch) -> str:
    return canonical_root(
        "eaglegate-policy-plans",
        {
            "policy_root": epoch.policy.policy_root,
            "plan_roots": [item.plan_root for item in epoch.plans],
        },
    )


def derive_core_qualification(
    epoch: EaglegateSpeculationEpoch,
    exactness_report: EaglegateExactnessReport,
    adapter_report: EaglegateAdapterConformanceReport,
) -> EaglegateQualificationSummary:
    """Derive, rather than accept, the v3.8 core qualification summary."""

    reference_exactness = run_reference_exactness_suite()
    reference_adapter = run_reference_adapter_conformance_suite()
    if exactness_report.report_root != reference_exactness.report_root:
        raise EaglegateContractError(
            "exactness report is not the fixed v3.8 core suite",
            fault=EaglegateFault.QUALIFICATION_REQUIRED,
        )
    if adapter_report.report_root != reference_adapter.report_root:
        raise EaglegateContractError(
            "adapter report is not the fixed v3.8 core suite",
            fault=EaglegateFault.QUALIFICATION_REQUIRED,
        )
    passed = exactness_report.passed and adapter_report.passed
    return EaglegateQualificationSummary(
        suite_id="eaglegate-v380-core-qualification-v1",
        identity_root=epoch.identity.identity_root,
        plan_roots=tuple(item.plan_root for item in epoch.plans),
        sampling_required=any(
            "lossless_sampling" in {value.value for value in item.sampler_classes}
            for item in epoch.plans
        ),
        greedy_exact_cases=len(exactness_report.checks),
        sampled_distribution_cases=1,
        kv_lifecycle_cases=len(adapter_report.checks),
        failure_containment_cases=len(adapter_report.checks),
        greedy_exact=passed,
        sampled_distribution_preserved=passed,
        kv_state_equivalent=passed,
        failure_fallback_preserved=passed,
    )


def qualify_eaglegate_core_epoch(
    epoch: EaglegateSpeculationEpoch,
) -> tuple[
    EaglegateSpeculationEpoch,
    EaglegateQualificationSummary,
    EaglegateExactnessReport,
    EaglegateAdapterConformanceReport,
]:
    """Run fixed core suites and return an epoch bound to their qualification."""

    if epoch.qualification_root:
        raise EaglegateContractError("core qualification requires an unqualified epoch")
    exactness = run_reference_exactness_suite()
    adapter = run_reference_adapter_conformance_suite()
    qualification = derive_core_qualification(epoch, exactness, adapter)
    return (
        replace(epoch, qualification_root=qualification.qualification_root),
        qualification,
        exactness,
        adapter,
    )


def _receipt_chain(
    epoch: EaglegateSpeculationEpoch,
    qualification_root: str,
) -> tuple[EaglegateEpochReceipt, ...]:
    receipts = [EaglegateEpochReceipt(epoch.epoch_root, EaglegateEpochState.DRAFT)]
    for state in (EaglegateEpochState.QUALIFIED, EaglegateEpochState.STAGED):
        receipts.append(
            EaglegateEpochReceipt(
                epoch.epoch_root,
                state,
                qualification_root,
                receipts[-1].receipt_root,
            )
        )
    if epoch.policy.mode is EaglegateMode.SHADOW:
        receipts.append(
            EaglegateEpochReceipt(
                epoch.epoch_root,
                EaglegateEpochState.SHADOW,
                qualification_root,
                receipts[-1].receipt_root,
            )
        )
    return tuple(receipts)


def _qualification_roots(
    binding: EaglegateServingEpochBinding,
) -> dict[str, str]:
    return {
        "adapter-conformance": binding.adapter_conformance_root,
        "eaglegate-policy": binding.eaglegate_policy_root,
        "exactness-qualification": binding.exactness_qualification_root,
        "exactness-report": binding.exactness_report_root,
        "qualification-summary": binding.qualification_summary_root,
        "receipt-chain": binding.receipt_chain_root,
        "serving-epoch": binding.eaglegate_epoch_root,
        "storage-generation": binding.storage_generation_root,
        "target-runtime-identity": binding.target_runtime_identity_root,
    }


def build_eaglegate_serving_candidate(
    store: AtomicGenerationStore,
    *,
    namespace: str,
    storage_namespace: str,
    storage_generation_root: str,
    epoch: EaglegateSpeculationEpoch,
    qualification: EaglegateQualificationSummary,
    exactness_report: EaglegateExactnessReport,
    adapter_report: EaglegateAdapterConformanceReport,
    parent_authority_generation_root: str | None = None,
) -> GenerationCandidate:
    """Build a content-free target-only/shadow ServingEpoch generation."""

    if not isinstance(store, AtomicGenerationStore):
        raise GenerationContractError("store must be an AtomicGenerationStore")
    if not isinstance(epoch, EaglegateSpeculationEpoch):
        raise EaglegateContractError("epoch must be an EaglegateSpeculationEpoch")
    if epoch.policy.mode not in _ALLOWED_MODES:
        raise EaglegateContractError(
            "canary and active publication are not implemented",
            fault=EaglegateFault.AUTHORITY_REJECTED,
        )
    if not isinstance(qualification, EaglegateQualificationSummary):
        raise EaglegateContractError("qualification has the wrong type")
    if not isinstance(exactness_report, EaglegateExactnessReport):
        raise EaglegateContractError("exactness report has the wrong type")
    if not isinstance(adapter_report, EaglegateAdapterConformanceReport):
        raise EaglegateContractError("adapter report has the wrong type")
    expected_qualification = derive_core_qualification(
        replace(epoch, qualification_root=""),
        exactness_report,
        adapter_report,
    )
    if qualification != expected_qualification:
        raise EaglegateContractError(
            "qualification was not derived from the fixed core reports",
            fault=EaglegateFault.QUALIFICATION_REQUIRED,
        )
    validate_qualification_for_epoch(epoch, qualification)
    if epoch.qualification_root != qualification.qualification_root:
        raise EaglegateContractError("epoch does not bind the exact qualification")
    if not adapter_report.passed:
        raise EaglegateContractError("adapter conformance did not pass")

    with store.pin(storage_namespace, _required_root(
        "storage_generation_root", storage_generation_root
    )):
        pass

    if parent_authority_generation_root is None:
        if epoch.previous_epoch_root:
            raise EaglegateContractError(
                "first authority generation cannot cite a previous Eaglegate epoch"
            )
    else:
        with store.pin(namespace, parent_authority_generation_root) as prior_lease:
            prior = load_eaglegate_serving_generation(prior_lease)
        if epoch.previous_epoch_root != prior.binding.eaglegate_epoch_root:
            raise EaglegateContractError(
                "Eaglegate epoch predecessor does not match authority lineage"
            )

    receipts = _receipt_chain(epoch, qualification.qualification_root)
    receipt_values = [item.canonical_dict() for item in receipts]
    receipt_data = canonical_json_bytes(receipt_values)
    bridge = EaglegateQualificationBridge(
        eaglegate_epoch_root=epoch.epoch_root,
        identity_root=epoch.identity.identity_root,
        plan_roots=tuple(item.plan_root for item in epoch.plans),
        qualification_summary_root=qualification.qualification_root,
        exactness_report_root=exactness_report.report_root,
        adapter_conformance_root=adapter_report.report_root,
    )
    binding = EaglegateServingEpochBinding(
        namespace=namespace,
        storage_namespace=storage_namespace,
        storage_generation_root=storage_generation_root,
        eaglegate_epoch_root=epoch.epoch_root,
        eaglegate_policy_root=_policy_plan_root(epoch),
        target_runtime_identity_root=epoch.identity.identity_root,
        exactness_qualification_root=bridge.bridge_root,
        qualification_summary_root=qualification.qualification_root,
        exactness_report_root=exactness_report.report_root,
        adapter_conformance_root=adapter_report.report_root,
        receipt_chain_root=canonical_root(
            "eaglegate-epoch-receipts", receipt_values
        ),
        serving_mode=epoch.policy.mode.value,
        parent_authority_generation_root=parent_authority_generation_root,
    )
    payloads = {
        EAGLEGATE_ADAPTER_REPORT_PAYLOAD: canonical_json_bytes(
            adapter_report.canonical_dict()
        ),
        EAGLEGATE_EPOCH_PAYLOAD: canonical_json_bytes(epoch.canonical_dict()),
        EAGLEGATE_EXACTNESS_REPORT_PAYLOAD: canonical_json_bytes(
            exactness_report.canonical_dict()
        ),
        EAGLEGATE_QUALIFICATION_PAYLOAD: canonical_json_bytes(
            qualification.canonical_dict()
        ),
        EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD: bridge.canonical_bytes(),
        EAGLEGATE_RECEIPTS_PAYLOAD: receipt_data,
        EAGLEGATE_SERVING_BINDING_PAYLOAD: binding.canonical_bytes(),
    }
    return store.build_candidate(
        namespace=namespace,
        payloads=payloads,
        media_types={name: "application/json" for name in payloads},
        authoritative_payload=None,
        parent_generation_root=parent_authority_generation_root,
        qualifications=_qualification_roots(binding),
        metadata={
            "consumer": EAGLEGATE_SERVING_GENERATION_CONTRACT_ID,
            "serving-effect": (
                "shadow-only"
                if epoch.policy.mode is EaglegateMode.SHADOW
                else "target-only"
            ),
        },
    )


def publish_eaglegate_serving_candidate(
    store: AtomicGenerationStore,
    candidate: GenerationCandidate,
    *,
    expected_head_root: str | None,
) -> PublicationResult:
    return store.publish(candidate, expected_head_root=expected_head_root)


@dataclass(frozen=True, slots=True)
class LoadedEaglegateServingGeneration:
    generation_root: str
    binding: EaglegateServingEpochBinding
    epoch: Mapping[str, Any]
    qualification: Mapping[str, Any]
    exactness_report: Mapping[str, Any]
    adapter_report: Mapping[str, Any]
    qualification_bridge: EaglegateQualificationBridge
    receipts: tuple[EaglegateEpochReceipt, ...]


def load_eaglegate_serving_generation(
    lease: GenerationLease,
) -> LoadedEaglegateServingGeneration:
    if not isinstance(lease, GenerationLease):
        raise GenerationContractError("lease must be a GenerationLease")
    identities = {item.name: item for item in lease.manifest.payloads}
    if set(identities) != _PAYLOAD_NAMES or any(
        item.authoritative for item in lease.manifest.payloads
    ):
        raise GenerationContractError(
            "Eaglegate generation payload set is not canonical",
            fault=GenerationFault.NONCANONICAL,
        )
    metadata = dict(lease.manifest.metadata)
    if metadata.get("consumer") != EAGLEGATE_SERVING_GENERATION_CONTRACT_ID:
        raise GenerationContractError("generation is not an Eaglegate ServingEpoch")

    raw = {name: lease.read_payload(name) for name in _PAYLOAD_NAMES}
    for name, data in raw.items():
        if identities[name].content_root != bytes_root(data):
            raise GenerationContractError(
                f"Eaglegate payload identity mismatch: {name}",
                fault=GenerationFault.IDENTITY_MISMATCH,
            )
    binding = EaglegateServingEpochBinding.from_bytes(
        raw[EAGLEGATE_SERVING_BINDING_PAYLOAD]
    )
    if (
        binding.namespace != lease.namespace
        or binding.parent_authority_generation_root
        != lease.manifest.parent_generation_root
    ):
        raise GenerationContractError(
            "Eaglegate binding belongs to another authority lineage",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    qualifications = {
        item.name: item.evidence_root for item in lease.manifest.qualifications
    }
    if qualifications != _qualification_roots(binding):
        raise GenerationContractError(
            "Eaglegate qualification roots are mixed",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )

    epoch = _canonical_mapping(raw[EAGLEGATE_EPOCH_PAYLOAD], "Eaglegate epoch")
    qualification = _canonical_mapping(
        raw[EAGLEGATE_QUALIFICATION_PAYLOAD], "Eaglegate qualification"
    )
    exactness = _canonical_mapping(
        raw[EAGLEGATE_EXACTNESS_REPORT_PAYLOAD], "Eaglegate exactness report"
    )
    adapter = _canonical_mapping(
        raw[EAGLEGATE_ADAPTER_REPORT_PAYLOAD], "Eaglegate adapter report"
    )
    bridge = EaglegateQualificationBridge.from_bytes(
        raw[EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD]
    )
    receipt_values = _canonical_sequence(
        raw[EAGLEGATE_RECEIPTS_PAYLOAD], "Eaglegate receipts"
    )
    if (
        epoch.get("contract_id") != EAGLEGATE_CONTRACT_ID
        or epoch.get("format_version") != EAGLEGATE_FORMAT_VERSION
        or _eaglegate_root("epoch", epoch) != binding.eaglegate_epoch_root
        or canonical_root(
            "eaglegate-policy-plans",
            {
                "policy_root": epoch.get("policy_root"),
                "plan_roots": epoch.get("plan_roots"),
            },
        )
        != binding.eaglegate_policy_root
        or epoch.get("identity_root") != binding.target_runtime_identity_root
        or epoch.get("qualification_root") != binding.qualification_summary_root
    ):
        raise GenerationContractError(
            "Eaglegate epoch binding mismatch",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    if (
        qualification.get("qualified") is not True
        or _eaglegate_root("qualification", qualification)
        != binding.qualification_summary_root
    ):
        raise GenerationContractError(
            "Eaglegate exactness qualification mismatch",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    if _exactness_root("exactness-report", exactness) != binding.exactness_report_root:
        raise GenerationContractError(
            "Eaglegate exactness report mismatch",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    if binding.exactness_report_root != run_reference_exactness_suite().report_root:
        raise GenerationContractError("Eaglegate exactness suite is not the fixed core suite")
    if (
        adapter.get("passed") is not True
        or _exactness_root("adapter-conformance-report", adapter)
        != binding.adapter_conformance_root
    ):
        raise GenerationContractError(
            "Eaglegate adapter conformance mismatch",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    if binding.adapter_conformance_root != (
        run_reference_adapter_conformance_suite().report_root
    ):
        raise GenerationContractError("Eaglegate adapter suite is not the fixed core suite")
    if (
        bridge.bridge_root != binding.exactness_qualification_root
        or bridge.eaglegate_epoch_root != binding.eaglegate_epoch_root
        or bridge.identity_root != binding.target_runtime_identity_root
        or bridge.plan_roots != tuple(epoch.get("plan_roots", ()))
        or bridge.qualification_summary_root != binding.qualification_summary_root
        or bridge.exactness_report_root != binding.exactness_report_root
        or bridge.adapter_conformance_root != binding.adapter_conformance_root
    ):
        raise GenerationContractError(
            "Eaglegate qualification bridge mismatch",
            fault=GenerationFault.IDENTITY_MISMATCH,
        )
    if canonical_root("eaglegate-epoch-receipts", receipt_values) != (
        binding.receipt_chain_root
    ):
        raise GenerationContractError("Eaglegate receipt chain root mismatch")

    receipts: list[EaglegateEpochReceipt] = []
    for value in receipt_values:
        if not isinstance(value, Mapping) or set(value) != {
            "contract_id",
            "format_version",
            "epoch_root",
            "state",
            "qualification_root",
            "previous_receipt_root",
            "reason_code",
        }:
            raise GenerationContractError("Eaglegate receipt is malformed")
        try:
            receipt = EaglegateEpochReceipt(
                epoch_root=value["epoch_root"],
                state=EaglegateEpochState(value["state"]),
                qualification_root=value["qualification_root"],
                previous_receipt_root=value["previous_receipt_root"],
                reason_code=value["reason_code"],
            )
        except (ValueError, EaglegateContractError) as exc:
            raise GenerationContractError("Eaglegate receipt is invalid") from exc
        if receipt.canonical_dict() != value or receipt.epoch_root != binding.eaglegate_epoch_root:
            raise GenerationContractError("Eaglegate receipt identity mismatch")
        if receipt.reason_code:
            raise GenerationContractError("persisted core receipts cannot carry free text")
        if receipts:
            validate_epoch_transition(receipts[-1], receipt)
        elif receipt.state is not EaglegateEpochState.DRAFT:
            raise GenerationContractError("Eaglegate receipt chain must start draft")
        receipts.append(receipt)
    expected_terminal = (
        EaglegateEpochState.SHADOW
        if binding.serving_mode == EaglegateMode.SHADOW.value
        else EaglegateEpochState.STAGED
    )
    if not receipts or receipts[-1].state is not expected_terminal:
        raise GenerationContractError("Eaglegate receipt terminal state mismatch")

    return LoadedEaglegateServingGeneration(
        generation_root=lease.generation_root,
        binding=binding,
        epoch=epoch,
        qualification=qualification,
        exactness_report=exactness,
        adapter_report=adapter,
        qualification_bridge=bridge,
        receipts=tuple(receipts),
    )


class EaglegateServingGenerationLease:
    """Pins both the ServingEpoch generation and its storage dependency."""

    def __init__(
        self,
        serving_lease: GenerationLease,
        storage_lease: GenerationLease,
        loaded: LoadedEaglegateServingGeneration,
    ) -> None:
        self._serving_lease = serving_lease
        self._storage_lease = storage_lease
        self.loaded = loaded

    @property
    def generation_root(self) -> str:
        return self.loaded.generation_root

    @property
    def binding(self) -> EaglegateServingEpochBinding:
        return self.loaded.binding

    @property
    def closed(self) -> bool:
        return self._serving_lease.closed

    def close(self) -> None:
        try:
            self._storage_lease.close()
        finally:
            self._serving_lease.close()

    def __enter__(self) -> "EaglegateServingGenerationLease":
        if self.closed:
            raise GenerationContractError("Eaglegate ServingEpoch lease is closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def open_eaglegate_serving_generation(
    store: AtomicGenerationStore,
    namespace: str,
    generation_root: str | None = None,
) -> EaglegateServingGenerationLease:
    serving = store.pin(namespace, generation_root)
    storage: GenerationLease | None = None
    try:
        loaded = load_eaglegate_serving_generation(serving)
        storage = store.pin(
            loaded.binding.storage_namespace,
            loaded.binding.storage_generation_root,
        )
        return EaglegateServingGenerationLease(serving, storage, loaded)
    except BaseException:
        if storage is not None:
            storage.close()
        serving.close()
        raise


__all__ = [
    "EAGLEGATE_ADAPTER_REPORT_PAYLOAD",
    "EAGLEGATE_EPOCH_PAYLOAD",
    "EAGLEGATE_EXACTNESS_REPORT_PAYLOAD",
    "EAGLEGATE_QUALIFICATION_PAYLOAD",
    "EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD",
    "EAGLEGATE_RECEIPTS_PAYLOAD",
    "EAGLEGATE_SERVING_BINDING_PAYLOAD",
    "EAGLEGATE_SERVING_GENERATION_CONTRACT_ID",
    "EaglegateServingEpochBinding",
    "EaglegateQualificationBridge",
    "EaglegateServingGenerationLease",
    "LoadedEaglegateServingGeneration",
    "build_eaglegate_serving_candidate",
    "derive_core_qualification",
    "load_eaglegate_serving_generation",
    "open_eaglegate_serving_generation",
    "publish_eaglegate_serving_candidate",
    "qualify_eaglegate_core_epoch",
]

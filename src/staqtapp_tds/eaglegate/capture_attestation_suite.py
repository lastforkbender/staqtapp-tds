"""Deterministic qualification suite for capture witness corroboration."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any, Mapping, Sequence

from .capture_attestation import (
    EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY,
    EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID,
    CaptureAttestationAuthorityBoundary,
    CaptureAttestationBundle,
    CaptureAttestationDecision,
    CaptureObservationState,
    CaptureReadOnlyStatusSnapshot,
    CaptureWitnessObservation,
    canonicalize_observations,
    compare_capture_status,
    next_observation_receipt,
    record_attestation_bundle,
    validate_observation_chain,
)
from .exactness_common import (
    EaglegateExactnessError,
    canonical_root,
    require_ascii,
    require_root,
)
from .offline_capture import validate_offline_capability_capture
from .offline_capture_suite import reference_offline_capture_bundle

EAGLEGATE_CAPTURE_ATTESTATION_SUITE_ID = (
    "eaglegate-capture-attestation-reference-v1"
)


def _root(label: str) -> str:
    return canonical_root("capture-attestation-fixture", {"label": label})


def reference_capture_status() -> CaptureReadOnlyStatusSnapshot:
    envelope, snapshot = reference_offline_capture_bundle()
    decision = validate_offline_capability_capture(envelope, snapshot)
    if not decision.compatible:
        raise EaglegateExactnessError("reference capture is not compatible")
    return CaptureReadOnlyStatusSnapshot(
        provider_id=envelope.provider_id,
        capture_root=envelope.capture_root,
        provider_snapshot_payload_root=decision.provider_snapshot_payload_root,
        adapter_identity_root=decision.adapter_identity_root,
        runtime_distribution_root=envelope.runtime_distribution_root,
        package_metadata_root=envelope.package_metadata_root,
        source_commit_root=envelope.source_commit_root,
        environment_root=envelope.environment_root,
        service_instance_root=_root("service-instance"),
        status_exporter_root=_root("status-exporter"),
        snapshot_generation=1,
    )


def reference_capture_observations() -> tuple[CaptureWitnessObservation, ...]:
    envelope, snapshot = reference_offline_capture_bundle()
    decision = validate_offline_capability_capture(envelope, snapshot)
    status = reference_capture_status()
    observations = (
        compare_capture_status(
            envelope,
            decision,
            status,
            witness_id="witness-a",
            witness_tool_root=_root("witness-tool-a"),
        ),
        compare_capture_status(
            envelope,
            decision,
            status,
            witness_id="witness-b",
            witness_tool_root=_root("witness-tool-b"),
        ),
    )
    return canonicalize_observations(observations)


def reference_capture_attestation_bundle() -> CaptureAttestationBundle:
    observations = reference_capture_observations()
    first = observations[0]
    return CaptureAttestationBundle(
        capture_root=first.capture_root,
        provider_snapshot_payload_root=first.provider_snapshot_payload_root,
        adapter_identity_root=first.adapter_identity_root,
        observations=observations,
    )


@dataclass(frozen=True, slots=True)
class CaptureAttestationCheck:
    name: str
    passed: bool
    evidence_root: str
    detail: str

    def __post_init__(self) -> None:
        require_ascii("name", self.name)
        if not isinstance(self.passed, bool):
            raise EaglegateExactnessError("passed must be boolean")
        require_root("evidence_root", self.evidence_root)
        require_ascii("detail", self.detail, allow_spaces=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence_root": self.evidence_root,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class CaptureAttestationReport:
    checks: tuple[CaptureAttestationCheck, ...]
    reference_attestation_root: str

    def __post_init__(self) -> None:
        if not self.checks or any(
            not isinstance(item, CaptureAttestationCheck) for item in self.checks
        ):
            raise EaglegateExactnessError(
                "checks must contain CaptureAttestationCheck"
            )
        require_root(
            "reference_attestation_root", self.reference_attestation_root
        )

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.checks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attestation_contract_id": (
                EAGLEGATE_CAPTURE_ATTESTATION_CONTRACT_ID
            ),
            "suite_id": EAGLEGATE_CAPTURE_ATTESTATION_SUITE_ID,
            "authority_root": (
                EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY.authority_root
            ),
            "reference_attestation_root": self.reference_attestation_root,
            "passed": self.passed,
            "check_count": len(self.checks),
            "checks": [item.canonical_dict() for item in self.checks],
            "runtime_imported_by_tds": False,
            "network_connection_created_by_tds": False,
            "request_submitted_by_tds": False,
            "model_invoked": False,
            "inference_performed": False,
            "token_acceptance_authority": False,
            "kv_commit_authority": False,
            "cryptographic_signature_verified": False,
            "witness_independence_proven": False,
            "metadata_truth_claimed": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
            "contains_private_keys": False,
        }

    @property
    def report_root(self) -> str:
        return canonical_root(
            "capture-attestation-report", self.canonical_dict()
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def _content_free(value: Any) -> bool:
    forbidden = {
        "prompt",
        "prompt_text",
        "tokens",
        "token_sequence",
        "logits",
        "logits_payload",
        "hidden_states",
        "kv_tensor",
        "kv_tensors",
        "private_key",
        "secret_key",
    }
    if isinstance(value, Mapping):
        return all(
            key not in forbidden and _content_free(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(_content_free(item) for item in value)
    return True


def run_reference_capture_attestation_suite() -> CaptureAttestationReport:
    bundle = reference_capture_attestation_bundle()
    checks: list[CaptureAttestationCheck] = []

    chain = record_attestation_bundle(bundle)
    checks.append(
        CaptureAttestationCheck(
            "two_witness_corroboration",
            bundle.decision is CaptureAttestationDecision.CORROBORATED
            and tuple(item.state for item in chain)
            == (
                CaptureObservationState.RECEIVED,
                CaptureObservationState.CORROBORATED,
                CaptureObservationState.RECORDED,
            ),
            chain[-1].receipt_root,
            "two distinct matching witnesses produce recorded corroboration",
        )
    )

    envelope, snapshot = reference_offline_capture_bundle()
    decision = validate_offline_capability_capture(envelope, snapshot)
    status = replace(reference_capture_status(), environment_root=_root("other-env"))
    mismatch = compare_capture_status(
        envelope,
        decision,
        status,
        witness_id="witness-mismatch",
        witness_tool_root=_root("witness-tool-mismatch"),
    )
    match = reference_capture_observations()[0]
    mismatch_bundle = CaptureAttestationBundle(
        capture_root=match.capture_root,
        provider_snapshot_payload_root=match.provider_snapshot_payload_root,
        adapter_identity_root=match.adapter_identity_root,
        observations=canonicalize_observations((match, mismatch)),
    )
    mismatch_chain = record_attestation_bundle(mismatch_bundle)
    checks.append(
        CaptureAttestationCheck(
            "mismatch_quarantine",
            mismatch_bundle.decision is CaptureAttestationDecision.TARGET_ONLY
            and mismatch_chain[-1].state
            is CaptureObservationState.QUARANTINED
            and mismatch.mismatch_fields == ("environment_root",),
            mismatch_chain[-1].receipt_root,
            "any exact metadata mismatch remains target-only and quarantined",
        )
    )

    single_rejected = False
    try:
        CaptureAttestationBundle(
            match.capture_root,
            match.provider_snapshot_payload_root,
            match.adapter_identity_root,
            (match,),
        )
    except EaglegateExactnessError:
        single_rejected = True
    checks.append(
        CaptureAttestationCheck(
            "single_witness_rejected",
            single_rejected,
            match.observation_root,
            "one observation cannot satisfy witness quorum",
        )
    )

    observations = reference_capture_observations()
    duplicate_id = False
    try:
        second = replace(observations[1], witness_id=observations[0].witness_id)
        CaptureAttestationBundle(
            observations[0].capture_root,
            observations[0].provider_snapshot_payload_root,
            observations[0].adapter_identity_root,
            canonicalize_observations((observations[0], second)),
        )
    except EaglegateExactnessError:
        duplicate_id = True
    checks.append(
        CaptureAttestationCheck(
            "duplicate_witness_rejected",
            duplicate_id,
            bundle.attestation_root,
            "duplicate witness identity cannot inflate quorum",
        )
    )

    duplicate_tool = False
    try:
        second = replace(
            observations[1], witness_tool_root=observations[0].witness_tool_root
        )
        CaptureAttestationBundle(
            observations[0].capture_root,
            observations[0].provider_snapshot_payload_root,
            observations[0].adapter_identity_root,
            canonicalize_observations((observations[0], second)),
        )
    except EaglegateExactnessError:
        duplicate_tool = True
    checks.append(
        CaptureAttestationCheck(
            "duplicate_tool_rejected",
            duplicate_tool,
            bundle.attestation_root,
            "duplicate witness tool cannot inflate quorum",
        )
    )

    mixed_capture = False
    try:
        second = replace(observations[1], capture_root=_root("other-capture"))
        CaptureAttestationBundle(
            observations[0].capture_root,
            observations[0].provider_snapshot_payload_root,
            observations[0].adapter_identity_root,
            canonicalize_observations((observations[0], second)),
        )
    except EaglegateExactnessError:
        mixed_capture = True
    checks.append(
        CaptureAttestationCheck(
            "mixed_capture_rejected",
            mixed_capture,
            bundle.attestation_root,
            "witnesses cannot corroborate different capture roots",
        )
    )

    mixed_adapter = False
    try:
        second = replace(
            observations[1], adapter_identity_root=_root("other-adapter")
        )
        CaptureAttestationBundle(
            observations[0].capture_root,
            observations[0].provider_snapshot_payload_root,
            observations[0].adapter_identity_root,
            canonicalize_observations((observations[0], second)),
        )
    except EaglegateExactnessError:
        mixed_adapter = True
    checks.append(
        CaptureAttestationCheck(
            "mixed_adapter_rejected",
            mixed_adapter,
            bundle.attestation_root,
            "witnesses cannot detach capture from adapter identity",
        )
    )

    forged_predecessor = False
    try:
        first, second, third = chain
        validate_observation_chain(
            (first, replace(second, previous_receipt_root=_root("forged")), third)
        )
    except EaglegateExactnessError:
        forged_predecessor = True
    checks.append(
        CaptureAttestationCheck(
            "forged_predecessor_rejected",
            forged_predecessor,
            chain[-1].receipt_root,
            "append-only receipt history binds exact predecessor roots",
        )
    )

    terminal_quarantine = False
    try:
        next_observation_receipt(
            mismatch_chain[-1], CaptureObservationState.RECORDED
        )
    except EaglegateExactnessError:
        terminal_quarantine = True
    checks.append(
        CaptureAttestationCheck(
            "quarantine_is_terminal",
            terminal_quarantine,
            mismatch_chain[-1].receipt_root,
            "quarantined evidence cannot silently re-enter the lifecycle",
        )
    )

    authority_denied = False
    try:
        CaptureAttestationAuthorityBoundary(may_activate=True)
    except EaglegateExactnessError:
        authority_denied = True
    partial = CaptureAttestationReport(tuple(checks), bundle.attestation_root)
    checks.append(
        CaptureAttestationCheck(
            "authority_and_evidence_boundary",
            authority_denied and _content_free(partial.canonical_dict()),
            EAGLEGATE_CAPTURE_ATTESTATION_AUTHORITY.authority_root,
            "corroboration is not signature truth independence runtime or activation",
        )
    )

    return CaptureAttestationReport(tuple(checks), bundle.attestation_root)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="staqtapp-tds-eaglegate-capture-witness-lab"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_reference_capture_attestation_suite()
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    else:
        print(
            "Eaglegate capture witness attestation: "
            + ("PASS" if report.passed else "FAIL")
        )
        for item in report.checks:
            state = "PASS" if item.passed else "FAIL"
            print(f"  {state}  {item.name}: {item.detail}")
        print(f"report_root: {report.report_root}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_CAPTURE_ATTESTATION_SUITE_ID",
    "CaptureAttestationCheck",
    "CaptureAttestationReport",
    "reference_capture_attestation_bundle",
    "reference_capture_observations",
    "reference_capture_status",
    "run_reference_capture_attestation_suite",
]

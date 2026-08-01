"""Synthetic qualification suite for runtime-neutral offline captures."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any, Mapping, Sequence

from .exactness_common import (
    EaglegateExactnessError,
    canonical_root,
    require_ascii,
    require_root,
)
from .offline_capture import (
    EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY,
    EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID,
    EAGLEGATE_VLLM_EAGLE_PROVIDER_ID,
    OfflineCapabilityCaptureEnvelope,
    OfflineCaptureAuthorityBoundary,
    OfflineCaptureDecision,
    OfflineCaptureFault,
    capture_envelope_to_mapping,
    provider_snapshot_payload_root,
    validate_offline_capability_capture,
)
from .vllm_shadow_suite import (
    reference_vllm_eagle_snapshot,
    snapshot_to_mapping,
)

EAGLEGATE_OFFLINE_CAPTURE_SUITE_ID = "eaglegate-offline-capture-reference-v1"


def _root(label: str) -> str:
    return canonical_root("offline-capture-fixture", {"label": label})


def reference_offline_capture_bundle() -> tuple[
    OfflineCapabilityCaptureEnvelope, dict[str, Any]
]:
    snapshot = reference_vllm_eagle_snapshot()
    payload = snapshot_to_mapping(snapshot)
    envelope = OfflineCapabilityCaptureEnvelope(
        provider_id=EAGLEGATE_VLLM_EAGLE_PROVIDER_ID,
        capture_sequence=1,
        capture_tool_root=_root("capture-tool"),
        runtime_distribution_root=_root("runtime-distribution"),
        package_metadata_root=_root("package-metadata"),
        source_commit_root=_root("source-commit"),
        environment_root=_root("environment"),
        adapter_conformance_root=snapshot.adapter_conformance_root,
        provider_snapshot_payload_root=provider_snapshot_payload_root(payload),
    )
    return envelope, payload


@dataclass(frozen=True, slots=True)
class OfflineCaptureCheck:
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
class OfflineCaptureReport:
    checks: tuple[OfflineCaptureCheck, ...]
    reference_capture_root: str

    def __post_init__(self) -> None:
        if not self.checks or any(
            not isinstance(check, OfflineCaptureCheck) for check in self.checks
        ):
            raise EaglegateExactnessError("checks must contain OfflineCaptureCheck")
        require_root("reference_capture_root", self.reference_capture_root)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "capture_contract_id": EAGLEGATE_OFFLINE_CAPTURE_CONTRACT_ID,
            "suite_id": EAGLEGATE_OFFLINE_CAPTURE_SUITE_ID,
            "authority_root": EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY.authority_root,
            "reference_capture_root": self.reference_capture_root,
            "passed": self.passed,
            "check_count": len(self.checks),
            "checks": [check.canonical_dict() for check in self.checks],
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
    def report_root(self) -> str:
        return canonical_root("offline-capture-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def _decision_check(
    name: str,
    decision: OfflineCaptureDecision,
    expected: OfflineCaptureFault,
    detail: str,
) -> OfflineCaptureCheck:
    payload = decision.canonical_dict()
    passed = (
        decision.fault is expected
        and decision.compatible is (expected is OfflineCaptureFault.NONE)
        and payload["runtime_imported_by_tds"] is False
        and payload["model_invoked"] is False
        and payload["activation_authority"] is False
    )
    return OfflineCaptureCheck(name, passed, decision.decision_root, detail)


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
    }
    if isinstance(value, Mapping):
        return all(
            key not in forbidden and _content_free(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(_content_free(item) for item in value)
    return True


def run_reference_offline_capture_suite() -> OfflineCaptureReport:
    envelope, payload = reference_offline_capture_bundle()
    checks: list[OfflineCaptureCheck] = []

    ready = validate_offline_capability_capture(envelope, payload)
    checks.append(
        _decision_check(
            "valid_metadata_capture",
            ready,
            OfflineCaptureFault.NONE,
            "valid provider metadata translates without runtime invocation",
        )
    )

    roundtrip = OfflineCapabilityCaptureEnvelope.from_mapping(
        capture_envelope_to_mapping(envelope)
    )
    checks.append(
        OfflineCaptureCheck(
            "canonical_roundtrip",
            roundtrip == envelope and roundtrip.capture_root == envelope.capture_root,
            roundtrip.capture_root,
            "capture envelope roundtrips without identity drift",
        )
    )

    tampered = dict(payload)
    tampered["runtime_version"] = "0.0.1"
    decision = validate_offline_capability_capture(envelope, tampered)
    checks.append(
        _decision_check(
            "payload_tamper_detection",
            decision,
            OfflineCaptureFault.PAYLOAD_MISMATCH,
            "provider metadata changes invalidate the capture root",
        )
    )

    provider = replace(envelope, provider_id="unknown-provider-v1")
    decision = validate_offline_capability_capture(provider, payload)
    checks.append(
        _decision_check(
            "unsupported_provider",
            decision,
            OfflineCaptureFault.UNSUPPORTED_PROVIDER,
            "unregistered translators remain target-only",
        )
    )

    adapter = replace(envelope, adapter_conformance_root=_root("wrong-adapter"))
    decision = validate_offline_capability_capture(adapter, payload)
    checks.append(
        _decision_check(
            "adapter_conformance_binding",
            decision,
            OfflineCaptureFault.ADAPTER_MISMATCH,
            "provider metadata cannot detach from adapter qualification",
        )
    )

    invalid = dict(payload)
    del invalid["runtime_version"]
    invalid_envelope = replace(
        envelope,
        provider_snapshot_payload_root=provider_snapshot_payload_root(invalid),
    )
    decision = validate_offline_capability_capture(invalid_envelope, invalid)
    checks.append(
        _decision_check(
            "invalid_provider_snapshot",
            decision,
            OfflineCaptureFault.INVALID_BUNDLE,
            "malformed provider metadata fails target-only",
        )
    )

    content = {**payload, "prompt": "not permitted"}
    content_envelope = replace(
        envelope,
        provider_snapshot_payload_root=provider_snapshot_payload_root(content),
    )
    decision = validate_offline_capability_capture(content_envelope, content)
    checks.append(
        _decision_check(
            "content_rejection",
            decision,
            OfflineCaptureFault.CONTENT_REJECTED,
            "prompt token logits hidden state and KV fields are rejected",
        )
    )

    unknown = False
    try:
        OfflineCapabilityCaptureEnvelope.from_mapping(
            {**capture_envelope_to_mapping(envelope), "execute": True}
        )
    except EaglegateExactnessError:
        unknown = True
    checks.append(
        OfflineCaptureCheck(
            "unknown_fields_fail_closed",
            unknown,
            envelope.capture_root,
            "unknown capture fields cannot widen the schema",
        )
    )

    activity = False
    try:
        replace(envelope, model_loaded=True)
    except EaglegateExactnessError:
        activity = True
    checks.append(
        OfflineCaptureCheck(
            "forbidden_activity_rejected",
            activity,
            envelope.capture_root,
            "model inference network and subprocess activity are forbidden",
        )
    )

    authority = False
    try:
        OfflineCaptureAuthorityBoundary(activation_authority=True)
    except EaglegateExactnessError:
        authority = True
    partial = OfflineCaptureReport(tuple(checks), envelope.capture_root)
    checks.append(
        OfflineCaptureCheck(
            "authority_and_evidence_boundary",
            authority and _content_free(partial.canonical_dict()),
            EAGLEGATE_OFFLINE_CAPTURE_AUTHORITY.authority_root,
            "capture import cannot execute activate or persist model content",
        )
    )

    return OfflineCaptureReport(tuple(checks), envelope.capture_root)


def capture_bundle_to_mapping(
    envelope: OfflineCapabilityCaptureEnvelope,
    provider_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "envelope": capture_envelope_to_mapping(envelope),
        "provider_snapshot": dict(provider_snapshot),
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-capture-lab")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_reference_offline_capture_suite()
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    else:
        print("Eaglegate offline capture: " + ("PASS" if report.passed else "FAIL"))
        for check in report.checks:
            state = "PASS" if check.passed else "FAIL"
            print(f"  {state}  {check.name}: {check.detail}")
        print(f"report_root: {report.report_root}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_OFFLINE_CAPTURE_SUITE_ID",
    "OfflineCaptureCheck",
    "OfflineCaptureReport",
    "capture_bundle_to_mapping",
    "reference_offline_capture_bundle",
    "run_reference_offline_capture_suite",
]

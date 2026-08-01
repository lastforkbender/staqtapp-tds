"""Engineer CLI for off-path Eaglegate witness corroboration."""
from __future__ import annotations

import argparse
import json
from typing import Sequence

from .attestation_contract import (
    AttestationDecision,
    CapabilityAttestationBundle,
    CapabilityWitnessObservation,
    EAGLEGATE_ATTESTATION_AUTHORITY,
    EAGLEGATE_ATTESTATION_CONTRACT_ID,
    EAGLEGATE_ATTESTATION_MIN_WITNESSES,
    EaglegateAttestationAuthorityBoundary,
    ObservationState,
    ShadowObservationReceipt,
    VLLMReadOnlyStatusSnapshot,
    next_observation_receipt,
    validate_observation_chain,
)
from .attestation_suite import (
    EAGLEGATE_ATTESTATION_SUITE_ID,
    AttestationQualificationCheck,
    EaglegateAttestationQualificationReport,
    run_reference_attestation_suite,
)
from .attestation_vllm import (
    build_capability_attestation_bundle,
    build_shadow_observation_chain,
    compare_vllm_shadow_status,
    load_vllm_eagle_metadata,
    load_vllm_read_only_status,
    parse_vllm_read_only_status,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-attest")
    sub = parser.add_subparsers(dest="command", required=True)
    reference = sub.add_parser(
        "reference", help="run the deterministic corroboration qualification"
    )
    reference.add_argument("--json", action="store_true")
    compare = sub.add_parser(
        "compare", help="compare supplied metadata with one read-only status export"
    )
    compare.add_argument("--metadata", required=True)
    compare.add_argument("--status", required=True)
    compare.add_argument("--shadow-root", required=True)
    compare.add_argument("--witness-id", required=True)
    compare.add_argument("--witness-tool-root", required=True)
    compare.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "reference":
        report = run_reference_attestation_suite()
        if args.json:
            print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
        else:
            print(
                "Eaglegate shadow attestation: "
                + ("PASS" if report.passed else "FAIL")
            )
            for check in report.checks:
                state = "PASS" if check.passed else "FAIL"
                print(f"  {state}  {check.name}: {check.detail}")
            print(f"report_root: {report.report_root}")
        return 0 if report.passed else 1

    metadata = load_vllm_eagle_metadata(args.metadata)
    status = load_vllm_read_only_status(args.status)
    observation = compare_vllm_shadow_status(
        metadata,
        status,
        shadow_report_root=args.shadow_root,
        witness_id=args.witness_id,
        witness_tool_root=args.witness_tool_root,
    )
    payload = {
        **observation.canonical_dict(),
        "observation_root": observation.observation_root,
        "authority_root": EAGLEGATE_ATTESTATION_AUTHORITY.authority_root,
        "metadata_truth_claimed": False,
        "real_runtime_qualified": False,
        "activation_authority": False,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(
            "Eaglegate witness comparison: "
            + ("MATCH" if observation.matched else "MISMATCH")
        )
        print(f"mismatch_fields: {','.join(observation.mismatch_fields)}")
        print(f"observation_root: {observation.observation_root}")
    return 0 if observation.matched else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [name for name in globals() if name.startswith("Eaglegate")]
__all__ += [
    "AttestationDecision",
    "AttestationQualificationCheck",
    "CapabilityAttestationBundle",
    "CapabilityWitnessObservation",
    "EAGLEGATE_ATTESTATION_AUTHORITY",
    "EAGLEGATE_ATTESTATION_CONTRACT_ID",
    "EAGLEGATE_ATTESTATION_MIN_WITNESSES",
    "EAGLEGATE_ATTESTATION_SUITE_ID",
    "ObservationState",
    "ShadowObservationReceipt",
    "VLLMReadOnlyStatusSnapshot",
    "build_capability_attestation_bundle",
    "build_shadow_observation_chain",
    "compare_vllm_shadow_status",
    "load_vllm_read_only_status",
    "main",
    "next_observation_receipt",
    "parse_vllm_read_only_status",
    "run_reference_attestation_suite",
    "validate_observation_chain",
]

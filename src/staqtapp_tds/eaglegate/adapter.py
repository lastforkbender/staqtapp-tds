"""Public fake-runtime adapter-conformance laboratory and engineer command."""
from __future__ import annotations

import argparse
import json
from typing import Sequence

from .adapter_contract import (
    ADAPTER_ALLOWED_TRANSITIONS,
    AdapterFault,
    AdapterOperation,
    AdapterState,
    AdapterTraceEvent,
    EAGLEGATE_ADAPTER_ABI_VERSION,
    EAGLEGATE_ADAPTER_CONTRACT_ID,
    EAGLEGATE_ADAPTER_SEQUENCE_ID,
    EAGLEGATE_TARGET_COMMIT_AUTHORITY,
    EaglegateAdapterIdentity,
    EaglegateAdapterLimits,
    EaglegateAdapterRequest,
    EaglegateAdapterTrace,
)
from .adapter_runtime import (
    AdapterConformanceOutcome,
    AdapterExecution,
    AdapterTraceBuilder,
    DeterministicOperationClock,
    EaglegateAdapterBoundaryError,
    EaglegateProposerFailure,
    EaglegateResourceExhausted,
    EaglegateVerifierFailure,
    FakeEagleAdapter,
    FakeTargetRuntimeAdapter,
    VerificationDecision,
    run_adapter_conformance_reference,
)
from .adapter_suite import (
    EAGLEGATE_ADAPTER_SUITE_ID,
    EaglegateAdapterConformanceCheck,
    EaglegateAdapterConformanceReport,
    reference_adapter_identity,
    reference_adapter_limits,
    reference_adapter_request,
    run_reference_adapter_conformance_suite,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-adapter-lab")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit deterministic content-free adapter evidence",
    )
    args = parser.parse_args(argv)
    report = run_reference_adapter_conformance_suite()
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    else:
        print(
            "Eaglegate adapter conformance: "
            + ("PASS" if report.passed else "FAIL")
        )
        for check in report.checks:
            state = "PASS" if check.passed else "FAIL"
            print(f"  {state}  {check.name}: {check.detail}")
        print(f"report_root: {report.report_root}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [name for name in globals() if name.startswith("Eaglegate")]
__all__ += [
    "ADAPTER_ALLOWED_TRANSITIONS",
    "AdapterConformanceOutcome",
    "AdapterExecution",
    "AdapterFault",
    "AdapterOperation",
    "AdapterState",
    "AdapterTraceBuilder",
    "AdapterTraceEvent",
    "DeterministicOperationClock",
    "EAGLEGATE_ADAPTER_ABI_VERSION",
    "EAGLEGATE_ADAPTER_CONTRACT_ID",
    "EAGLEGATE_ADAPTER_SEQUENCE_ID",
    "EAGLEGATE_ADAPTER_SUITE_ID",
    "EAGLEGATE_TARGET_COMMIT_AUTHORITY",
    "FakeEagleAdapter",
    "FakeTargetRuntimeAdapter",
    "VerificationDecision",
    "main",
    "reference_adapter_identity",
    "reference_adapter_limits",
    "reference_adapter_request",
    "run_adapter_conformance_reference",
    "run_reference_adapter_conformance_suite",
]

"""Public differential exactness laboratory and engineer command."""
from __future__ import annotations

import argparse
import json
from typing import Sequence

from .exactness_common import (
    EAGLEGATE_EXACTNESS_CONTRACT_ID,
    EAGLEGATE_EXACTNESS_SUITE_ID,
    EaglegateExactnessError,
    committed_state_root,
    reference_epoch_root,
    token_sequence_root,
)
from .exactness_math import (
    LosslessDistributionProof,
    prove_lossless_one_step_distribution,
)
from .exactness_runtime import (
    BoundedEvidenceRing,
    DecodeOutcome,
    ReferenceKVLedger,
    ScriptedProposer,
    run_speculative_reference,
    run_target_only,
)
from .exactness_suite import (
    EaglegateExactnessReport,
    ExactnessCheck,
    run_reference_exactness_suite,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-lab")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit deterministic content-free JSON evidence",
    )
    args = parser.parse_args(argv)
    report = run_reference_exactness_suite()
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    else:
        print(
            "Eaglegate differential exactness: "
            + ("PASS" if report.passed else "FAIL")
        )
        for check in report.checks:
            state = "PASS" if check.passed else "FAIL"
            print(f"  {state}  {check.name}: {check.detail}")
        print(f"report_root: {report.report_root}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BoundedEvidenceRing",
    "DecodeOutcome",
    "EAGLEGATE_EXACTNESS_CONTRACT_ID",
    "EAGLEGATE_EXACTNESS_SUITE_ID",
    "EaglegateExactnessError",
    "EaglegateExactnessReport",
    "ExactnessCheck",
    "LosslessDistributionProof",
    "ReferenceKVLedger",
    "ScriptedProposer",
    "committed_state_root",
    "main",
    "prove_lossless_one_step_distribution",
    "reference_epoch_root",
    "run_reference_exactness_suite",
    "run_speculative_reference",
    "run_target_only",
    "token_sequence_root",
]

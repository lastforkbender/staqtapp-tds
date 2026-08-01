"""Deterministic qualification cases and content-free exactness report."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping

from .contract import (
    EAGLEGATE_ACCEPTANCE_CONTRACT_ID,
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
)
from .exactness_common import (
    EAGLEGATE_EXACTNESS_CONTRACT_ID,
    EAGLEGATE_EXACTNESS_SUITE_ID,
    EaglegateExactnessError,
    canonical_root,
    reference_epoch_root,
    require_ascii,
    require_root,
)
from .exactness_math import prove_lossless_one_step_distribution
from .exactness_runtime import (
    DecodeOutcome,
    ReferenceKVLedger,
    ScriptedProposer,
    run_speculative_reference,
    run_target_only,
)


@dataclass(frozen=True, slots=True)
class ExactnessCheck:
    name: str
    passed: bool
    target_outcome_root: str
    speculative_outcome_root: str
    detail: str

    def __post_init__(self) -> None:
        require_ascii("name", self.name)
        if not isinstance(self.passed, bool):
            raise EaglegateExactnessError("passed must be a boolean")
        require_root("target_outcome_root", self.target_outcome_root)
        require_root("speculative_outcome_root", self.speculative_outcome_root)
        require_ascii("detail", self.detail, allow_spaces=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "target_outcome_root": self.target_outcome_root,
            "speculative_outcome_root": self.speculative_outcome_root,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EaglegateExactnessReport:
    suite_id: str
    checks: tuple[ExactnessCheck, ...]
    distribution_proof_root: str

    def __post_init__(self) -> None:
        require_ascii("suite_id", self.suite_id)
        if not self.checks or any(
            not isinstance(check, ExactnessCheck) for check in self.checks
        ):
            raise EaglegateExactnessError(
                "checks must contain at least one ExactnessCheck"
            )
        require_root("distribution_proof_root", self.distribution_proof_root)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            "foundation_contract_id": EAGLEGATE_CONTRACT_ID,
            "foundation_format_version": EAGLEGATE_FORMAT_VERSION,
            "acceptance_contract_id": EAGLEGATE_ACCEPTANCE_CONTRACT_ID,
            "suite_id": self.suite_id,
            "passed": self.passed,
            "check_count": len(self.checks),
            "checks": [check.canonical_dict() for check in self.checks],
            "distribution_proof_root": self.distribution_proof_root,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
            "activation_authority": False,
        }

    @property
    def report_root(self) -> str:
        return canonical_root("exactness-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def _pair(
    name: str,
    target: DecodeOutcome,
    speculative: DecodeOutcome,
    *,
    extra: bool = True,
    detail: str = "equivalent",
) -> ExactnessCheck:
    passed = all(
        (
            target.token_sequence_root == speculative.token_sequence_root,
            target.committed_state_root == speculative.committed_state_root,
            target.token_count == speculative.token_count,
            speculative.outstanding_reservations == 0,
            speculative.all_commits_by_target,
            extra,
        )
    )
    return ExactnessCheck(
        name,
        passed,
        target.outcome_root,
        speculative.outcome_root,
        detail,
    )


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


def run_reference_exactness_suite() -> EaglegateExactnessReport:
    epoch = reference_epoch_root()
    other_epoch = reference_epoch_root("other")
    target_tokens = (11, 22, 33, 44, 55, 66)
    baseline = run_target_only(target_tokens)
    checks: list[ExactnessCheck] = []

    checks.append(
        _pair(
            "full_accept",
            baseline,
            run_speculative_reference(
                target_tokens,
                ScriptedProposer({0: target_tokens}),
                pinned_epoch_root=epoch,
                runtime_epoch_root=epoch,
            ),
        )
    )
    checks.append(
        _pair(
            "immediate_rejection",
            baseline,
            run_speculative_reference(
                target_tokens,
                ScriptedProposer(
                    {0: (999, 22, 33), 1: (22, 33, 44, 55, 66)}
                ),
                pinned_epoch_root=epoch,
                runtime_epoch_root=epoch,
            ),
        )
    )
    checks.append(
        _pair(
            "prefix_rejection",
            baseline,
            run_speculative_reference(
                target_tokens,
                ScriptedProposer({0: (11, 22, 999), 3: (44, 55, 66)}),
                pinned_epoch_root=epoch,
                runtime_epoch_root=epoch,
            ),
        )
    )

    failure = run_speculative_reference(
        target_tokens,
        ScriptedProposer({}, fail_at_position=0),
        pinned_epoch_root=epoch,
        runtime_epoch_root=epoch,
    )
    checks.append(
        _pair(
            "proposer_failure_fallback",
            baseline,
            failure,
            extra=failure.fallback_reason == "proposer_failure",
            detail="target-only fallback",
        )
    )

    stale_proposer = ScriptedProposer({0: target_tokens})
    mismatch = run_speculative_reference(
        target_tokens,
        stale_proposer,
        pinned_epoch_root=epoch,
        runtime_epoch_root=other_epoch,
    )
    checks.append(
        _pair(
            "epoch_mismatch_no_proposer",
            baseline,
            mismatch,
            extra=(
                mismatch.fallback_reason == "epoch_mismatch"
                and mismatch.proposer_calls == 0
            ),
            detail="mixed epoch denied",
        )
    )

    cancelled_baseline = run_target_only(target_tokens, cancel_after=4)
    cancelled = run_speculative_reference(
        target_tokens,
        ScriptedProposer({0: target_tokens}),
        pinned_epoch_root=epoch,
        runtime_epoch_root=epoch,
        cancel_after=4,
    )
    checks.append(
        _pair(
            "cancellation_release",
            cancelled_baseline,
            cancelled,
            extra=cancelled.cancelled,
            detail="committed prefix preserved",
        )
    )

    overflow = run_speculative_reference(
        target_tokens,
        ScriptedProposer({0: (11, 999), 2: (33, 999), 4: (55, 66)}),
        pinned_epoch_root=epoch,
        runtime_epoch_root=epoch,
        ring_capacity=1,
    )
    checks.append(
        _pair(
            "telemetry_overflow_noninterference",
            baseline,
            overflow,
            extra=overflow.observer_events_dropped > 0,
            detail="observer detail dropped only",
        )
    )

    proof = prove_lossless_one_step_distribution(
        {11: Fraction(1, 2), 22: Fraction(1, 3), 33: Fraction(1, 6)},
        {11: Fraction(1, 4), 22: Fraction(1, 4), 44: Fraction(1, 2)},
    )
    empty = run_target_only(())
    checks.append(
        ExactnessCheck(
            "exact_rational_distribution",
            proof.exact,
            empty.outcome_root,
            empty.outcome_root,
            "output mass equals target mass",
        )
    )

    ledger = ReferenceKVLedger()
    denied = False
    try:
        ledger.commit((1,), authority="proposer")
    except EaglegateExactnessError:
        denied = True
    checks.append(
        ExactnessCheck(
            "proposer_commit_denied",
            denied and ledger.committed == (),
            empty.outcome_root,
            empty.outcome_root,
            "target runtime remains sole commit authority",
        )
    )

    partial = EaglegateExactnessReport(
        EAGLEGATE_EXACTNESS_SUITE_ID,
        tuple(checks),
        proof.proof_root,
    )
    checks.append(
        ExactnessCheck(
            "content_free_evidence",
            _content_free(partial.canonical_dict()),
            empty.outcome_root,
            empty.outcome_root,
            "only roots counts and bounded facts persist",
        )
    )
    return EaglegateExactnessReport(
        EAGLEGATE_EXACTNESS_SUITE_ID,
        tuple(checks),
        proof.proof_root,
    )


__all__ = [
    "EaglegateExactnessReport",
    "ExactnessCheck",
    "run_reference_exactness_suite",
]

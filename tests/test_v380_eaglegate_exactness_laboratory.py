from fractions import Fraction
import hashlib
import json

import pytest

from staqtapp_tds.eaglegate.exactness import (
    BoundedEvidenceRing,
    EaglegateExactnessError,
    ReferenceKVLedger,
    ScriptedProposer,
    main,
    prove_lossless_one_step_distribution,
    run_reference_exactness_suite,
    run_speculative_reference,
    run_target_only,
)


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("ascii")).hexdigest()


def test_reference_suite_passes_and_is_deterministic():
    first = run_reference_exactness_suite()
    second = run_reference_exactness_suite()
    assert first.passed
    assert len(first.checks) == 10
    assert first.report_root == second.report_root
    assert first.to_dict() == second.to_dict()


def test_exact_distribution_recovery_uses_rationals():
    proof = prove_lossless_one_step_distribution(
        {1: Fraction(2, 3), 2: Fraction(1, 3)},
        {1: Fraction(1, 6), 3: Fraction(5, 6)},
    )
    assert proof.exact
    assert proof.acceptance_mass == Fraction(1, 6)
    assert proof.rejection_mass == Fraction(5, 6)


def test_invalid_distribution_is_rejected_without_tolerance():
    with pytest.raises(EaglegateExactnessError, match="sum exactly to one"):
        prove_lossless_one_step_distribution(
            {1: Fraction(1, 3)},
            {1: Fraction(1, 1)},
        )


def test_float_distribution_mass_is_rejected():
    with pytest.raises(EaglegateExactnessError, match="Fraction or int"):
        prove_lossless_one_step_distribution(
            {1: 0.5, 2: 0.5},
            {1: Fraction(1, 2), 2: Fraction(1, 2)},
        )


def test_observer_ring_rejects_content_bearing_events():
    ring = BoundedEvidenceRing(4)
    with pytest.raises(EaglegateExactnessError, match="only kind and count"):
        ring.publish({"kind": "proposal", "count": 1, "tokens": [7]})
    assert ring.published == 0
    assert ring.dropped == 0


def test_epoch_mismatch_never_calls_proposer():
    target = (1, 2, 3)
    proposer = ScriptedProposer({0: target})
    outcome = run_speculative_reference(
        target,
        proposer,
        pinned_epoch_root=_root("epoch-a"),
        runtime_epoch_root=_root("epoch-b"),
    )
    baseline = run_target_only(target)
    assert proposer.call_count == 0
    assert outcome.fallback_reason == "epoch_mismatch"
    assert outcome.token_sequence_root == baseline.token_sequence_root
    assert outcome.outstanding_reservations == 0


def test_proposer_failure_releases_and_continues_target_only():
    target = (1, 2, 3)
    outcome = run_speculative_reference(
        target,
        ScriptedProposer({}, fail_at_position=0),
        pinned_epoch_root=_root("epoch-a"),
        runtime_epoch_root=_root("epoch-a"),
    )
    assert outcome.fallback_reason == "proposer_failure"
    assert outcome.target_only_continuation
    assert outcome.outstanding_reservations == 0
    assert outcome.token_sequence_root == run_target_only(target).token_sequence_root


def test_cancellation_preserves_exact_committed_prefix():
    target = (1, 2, 3, 4, 5)
    baseline = run_target_only(target, cancel_after=3)
    outcome = run_speculative_reference(
        target,
        ScriptedProposer({0: target}),
        pinned_epoch_root=_root("epoch-a"),
        runtime_epoch_root=_root("epoch-a"),
        cancel_after=3,
    )
    assert outcome.cancelled
    assert outcome.token_sequence_root == baseline.token_sequence_root
    assert outcome.committed_state_root == baseline.committed_state_root
    assert outcome.outstanding_reservations == 0


def test_observer_overflow_is_noninterfering():
    target = (1, 2, 3, 4)
    outcome = run_speculative_reference(
        target,
        ScriptedProposer({0: (1, 9), 2: (3, 4)}),
        pinned_epoch_root=_root("epoch-a"),
        runtime_epoch_root=_root("epoch-a"),
        ring_capacity=0,
    )
    assert outcome.observer_events_dropped > 0
    assert outcome.token_sequence_root == run_target_only(target).token_sequence_root


def test_proposer_cannot_commit_reference_state():
    ledger = ReferenceKVLedger()
    with pytest.raises(EaglegateExactnessError, match="only target-runtime"):
        ledger.commit((7,), authority="proposer")
    assert ledger.committed == ()


def test_report_is_content_free_and_cli_emits_json(capsys):
    report = run_reference_exactness_suite()
    payload = report.to_dict()
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

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert forbidden.isdisjoint(set(keys(payload)))
    assert main(["--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    assert output["activation_authority"] is False
    assert output["report_root"] == report.report_root

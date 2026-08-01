import hashlib
import json

import pytest

from staqtapp_tds.eaglegate.adapter import main as adapter_main
from staqtapp_tds.eaglegate.adapter_contract import (
    AdapterFault,
    AdapterOperation,
    AdapterState,
    AdapterTraceEvent,
    EAGLEGATE_TARGET_COMMIT_AUTHORITY,
    EaglegateAdapterIdentity,
    EaglegateAdapterLimits,
    EaglegateAdapterRequest,
    EaglegateAdapterTrace,
)
from staqtapp_tds.eaglegate.adapter_runtime import (
    AdapterTraceBuilder,
    EaglegateProposerFailure,
    EaglegateVerifierFailure,
    FakeEagleAdapter,
    FakeTargetRuntimeAdapter,
    run_adapter_conformance_reference,
)
from staqtapp_tds.eaglegate.adapter_suite import (
    run_reference_adapter_conformance_suite,
)
from staqtapp_tds.eaglegate.exactness_common import EaglegateExactnessError
from staqtapp_tds.eaglegate.exactness_runtime import run_target_only


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("ascii")).hexdigest()


def _identity(label: str = "a") -> EaglegateAdapterIdentity:
    return EaglegateAdapterIdentity(
        foundation_identity_root=_root(f"foundation-{label}"),
        exactness_qualification_root=_root(f"exactness-{label}"),
        adapter_build_root=_root(f"adapter-{label}"),
        target_verifier_root=_root(f"verifier-{label}"),
        rng_contract_root=_root(f"rng-{label}"),
        sampler_order_root=_root(f"sampler-{label}"),
        logits_processor_order_root=_root(f"logits-{label}"),
        termination_contract_root=_root(f"termination-{label}"),
        kv_allocator_root=_root(f"kv-{label}"),
        numerical_kernel_root=_root(f"kernel-{label}"),
        deadline_contract_root=_root(f"deadline-{label}"),
    )


def _limits(
    *,
    candidate: int = 4,
    deadline: int = 128,
    events: int = 128,
) -> EaglegateAdapterLimits:
    return EaglegateAdapterLimits(
        max_candidate_tokens=candidate,
        max_outstanding_reservations=1,
        max_trace_events=events,
        deadline_budget_ticks=deadline,
    )


def _request(
    identity: EaglegateAdapterIdentity,
    limits: EaglegateAdapterLimits,
    *,
    epoch: str | None = None,
) -> EaglegateAdapterRequest:
    return EaglegateAdapterRequest(
        epoch_root=epoch or _root("epoch"),
        adapter_identity_root=identity.adapter_identity_root,
        plan_root=_root("plan"),
        request_class_root=_root("request-class"),
        limits_root=limits.limits_root,
    )


def _execute(
    target,
    proposals,
    *,
    identity: EaglegateAdapterIdentity | None = None,
    runtime_identity: EaglegateAdapterIdentity | None = None,
    request_epoch: str | None = None,
    runtime_epoch: str | None = None,
    limits: EaglegateAdapterLimits | None = None,
    proposer_fail: int | None = None,
    reserve_fail: int | None = None,
    verify_fail: int | None = None,
    cancel_at: int | None = None,
):
    identity = identity or _identity()
    runtime_identity = runtime_identity or identity
    limits = limits or _limits()
    request = _request(identity, limits, epoch=request_epoch)
    runtime = FakeTargetRuntimeAdapter(
        target,
        epoch_root=runtime_epoch or request.epoch_root,
        adapter_identity_root=runtime_identity.adapter_identity_root,
        reserve_fail_at_position=reserve_fail,
        verify_fail_at_position=verify_fail,
    )
    proposer = FakeEagleAdapter(proposals, fail_at_position=proposer_fail)
    execution = run_adapter_conformance_reference(
        target,
        proposer,
        runtime,
        request,
        limits,
        cancel_at_position=cancel_at,
    )
    return execution, proposer, runtime


def _operations(execution):
    return [event.operation for event in execution.trace.events]


def test_full_accept_uses_exact_abi_order_and_target_commit_authority():
    target = (1, 2, 3, 4)
    execution, proposer, runtime = _execute(target, {0: target})
    assert execution.outcome.fault is AdapterFault.NONE
    assert (
        execution.outcome.token_sequence_root
        == run_target_only(target).token_sequence_root
    )
    assert execution.outcome.outstanding_reservations == 0
    assert execution.outcome.all_commits_by_target
    assert proposer.call_count == 1
    assert runtime.ledger.committed == target
    assert _operations(execution) == [
        AdapterOperation.PIN,
        AdapterOperation.RESERVE,
        AdapterOperation.PROPOSE,
        AdapterOperation.VERIFY,
        AdapterOperation.COMMIT,
        AdapterOperation.RELEASE,
        AdapterOperation.CLOSE,
    ]
    commit = next(
        event
        for event in execution.trace.events
        if event.operation is AdapterOperation.COMMIT
    )
    assert commit.authority == EAGLEGATE_TARGET_COMMIT_AUTHORITY


def test_rejection_rewinds_before_target_correction_commit():
    target = (1, 2, 3, 4)
    execution, _, runtime = _execute(target, {0: (1, 9, 9), 2: (3, 4)})
    operations = _operations(execution)
    assert operations.index(AdapterOperation.REWIND) < operations.index(
        AdapterOperation.COMMIT
    )
    assert runtime.rewind_count == 2
    assert runtime.ledger.committed == target


def test_proposer_failure_cancels_releases_and_continues_target_only():
    target = (1, 2, 3)
    execution, proposer, runtime = _execute(target, {}, proposer_fail=0)
    assert execution.outcome.fault is AdapterFault.PROPOSER_FAILURE
    assert execution.outcome.fallback_reason == "proposer_failure"
    assert execution.outcome.outstanding_reservations == 0
    assert runtime.cancel_count == 1
    assert proposer.call_count == 1
    assert runtime.ledger.committed == target
    assert _operations(execution)[-4:] == [
        AdapterOperation.CANCEL,
        AdapterOperation.RELEASE,
        AdapterOperation.FALLBACK,
        AdapterOperation.CLOSE,
    ]


def test_epoch_mismatch_falls_back_before_pin_reserve_or_propose():
    target = (1, 2, 3)
    execution, proposer, runtime = _execute(
        target,
        {0: target},
        request_epoch=_root("epoch-a"),
        runtime_epoch=_root("epoch-b"),
    )
    assert execution.outcome.fault is AdapterFault.EPOCH_MISMATCH
    assert proposer.call_count == 0
    assert runtime.ledger.committed == target
    assert _operations(execution) == [
        AdapterOperation.FALLBACK,
        AdapterOperation.CLOSE,
    ]


def test_execution_identity_mismatch_including_rng_falls_back_before_proposer():
    target = (1, 2, 3)
    request_identity = _identity("request")
    runtime_identity = _identity("runtime")
    execution, proposer, runtime = _execute(
        target,
        {0: target},
        identity=request_identity,
        runtime_identity=runtime_identity,
    )
    assert request_identity.rng_contract_root != runtime_identity.rng_contract_root
    assert execution.outcome.fault is AdapterFault.IDENTITY_MISMATCH
    assert proposer.call_count == 0
    assert runtime.ledger.committed == target


def test_deadline_after_reservation_performs_safety_release_then_fallback():
    target = (1, 2, 3)
    execution, proposer, runtime = _execute(
        target,
        {0: target},
        limits=_limits(deadline=2),
    )
    assert execution.outcome.fault is AdapterFault.DEADLINE_EXCEEDED
    assert execution.outcome.fallback_reason == "deadline_before_propose"
    assert proposer.call_count == 0
    assert runtime.cancel_count == 1
    assert execution.outcome.outstanding_reservations == 0
    assert runtime.ledger.committed == target


def test_reservation_exhaustion_falls_back_without_proposer_call():
    target = (1, 2, 3)
    execution, proposer, runtime = _execute(target, {0: target}, reserve_fail=0)
    assert execution.outcome.fault is AdapterFault.RESOURCE_EXHAUSTED
    assert proposer.call_count == 0
    assert runtime.cancel_count == 0
    assert runtime.ledger.committed == target


def test_verifier_failure_releases_and_never_commits_proposal_state():
    target = (1, 2, 3)
    execution, proposer, runtime = _execute(target, {0: target}, verify_fail=0)
    assert execution.outcome.fault is AdapterFault.VERIFIER_FAILURE
    assert proposer.call_count == 1
    assert runtime.cancel_count == 1
    assert execution.outcome.outstanding_reservations == 0
    assert runtime.ledger.committed == target
    assert execution.outcome.all_commits_by_target


def test_request_cancellation_preserves_exact_prefix_and_releases():
    target = (1, 2, 3, 4, 5)
    execution, proposer, runtime = _execute(
        target,
        {0: (1, 2), 2: (3, 4, 5)},
        limits=_limits(candidate=3),
        cancel_at=2,
    )
    baseline = run_target_only(target, cancel_after=2)
    assert execution.outcome.fault is AdapterFault.REQUEST_CANCELLED
    assert execution.outcome.cancelled
    assert proposer.call_count == 2
    assert runtime.cancel_count == 1
    assert runtime.ledger.committed == (1, 2)
    assert execution.outcome.token_sequence_root == baseline.token_sequence_root
    assert execution.outcome.outstanding_reservations == 0


def test_invalid_transition_and_non_target_commit_are_rejected():
    builder = AdapterTraceBuilder(_root("request"), 8)
    with pytest.raises(EaglegateExactnessError, match="invalid adapter transition"):
        builder.record(
            AdapterOperation.COMMIT,
            position=0,
            authority="target-runtime",
        )
    with pytest.raises(EaglegateExactnessError, match="target-runtime"):
        AdapterTraceEvent(
            sequence=0,
            operation=AdapterOperation.COMMIT,
            state_before=AdapterState.VERIFIED,
            state_after=AdapterState.COMMITTED,
            position=0,
            token_count=1,
            reservation_id=1,
            authority="proposer",
        )


def test_adapter_abi_v1_rejects_multiple_outstanding_reservations():
    with pytest.raises(EaglegateExactnessError, match="exactly one"):
        EaglegateAdapterLimits(
            max_candidate_tokens=4,
            max_outstanding_reservations=2,
            max_trace_events=16,
            deadline_budget_ticks=16,
        )


def test_direct_trace_construction_replays_legal_state_machine():
    pin = AdapterTraceEvent(
        sequence=0,
        operation=AdapterOperation.PIN,
        state_before=AdapterState.NEW,
        state_after=AdapterState.PINNED,
        position=0,
        token_count=0,
        reservation_id=0,
        reason="identity_pinned",
    )
    bad_close = AdapterTraceEvent(
        sequence=1,
        operation=AdapterOperation.CLOSE,
        state_before=AdapterState.RESERVED,
        state_after=AdapterState.CLOSED,
        position=0,
        token_count=0,
        reservation_id=0,
        reason="forged_close",
        previous_event_root=pin.event_root,
    )
    with pytest.raises(EaglegateExactnessError, match="state chain"):
        EaglegateAdapterTrace(_root("trace-request"), (pin, bad_close))


def test_direct_trace_must_finish_closed():
    pin = AdapterTraceEvent(
        sequence=0,
        operation=AdapterOperation.PIN,
        state_before=AdapterState.NEW,
        state_after=AdapterState.PINNED,
        position=0,
        token_count=0,
        reservation_id=0,
        reason="identity_pinned",
    )
    with pytest.raises(EaglegateExactnessError, match="end closed"):
        EaglegateAdapterTrace(_root("open-trace"), (pin,))


def test_reference_adapter_suite_is_deterministic_and_non_activating():
    first = run_reference_adapter_conformance_suite()
    second = run_reference_adapter_conformance_suite()
    assert first.passed
    assert len(first.checks) == 10
    assert first.report_root == second.report_root
    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["activation_authority"] is False
    assert first.to_dict()["adapter_execution_authority"] is False
    assert first.to_dict()["real_runtime_qualified"] is False


def test_adapter_report_rejects_content_bearing_surface_keys():
    report = run_reference_adapter_conformance_suite().to_dict()
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

    assert forbidden.isdisjoint(set(keys(report)))


def test_adapter_lab_cli_emits_deterministic_json(capsys):
    report = run_reference_adapter_conformance_suite()
    assert adapter_main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["check_count"] == 10
    assert payload["activation_authority"] is False
    assert payload["adapter_execution_authority"] is False
    assert payload["real_runtime_qualified"] is False
    assert payload["report_root"] == report.report_root


def test_unclassified_proposer_programming_defect_fails_the_run():
    class BrokenProposer(FakeEagleAdapter):
        def propose(self, position, reservation_id, max_candidate_tokens):
            raise ValueError("unexpected programming defect")

    identity = _identity()
    limits = _limits()
    request = _request(identity, limits)
    runtime = FakeTargetRuntimeAdapter(
        (1, 2),
        epoch_root=request.epoch_root,
        adapter_identity_root=identity.adapter_identity_root,
    )
    with pytest.raises(ValueError, match="programming defect"):
        run_adapter_conformance_reference(
            (1, 2), BrokenProposer({}), runtime, request, limits
        )


def test_unclassified_verifier_programming_defect_fails_the_run():
    class BrokenRuntime(FakeTargetRuntimeAdapter):
        def verify(self, position, proposal):
            raise ValueError("unexpected verifier defect")

    identity = _identity()
    limits = _limits()
    request = _request(identity, limits)
    runtime = BrokenRuntime(
        (1, 2),
        epoch_root=request.epoch_root,
        adapter_identity_root=identity.adapter_identity_root,
    )
    with pytest.raises(ValueError, match="verifier defect"):
        run_adapter_conformance_reference(
            (1, 2), FakeEagleAdapter({0: (1, 2)}), runtime, request, limits
        )


def test_stable_boundary_failure_types_are_distinct():
    assert issubclass(EaglegateProposerFailure, RuntimeError)
    assert issubclass(EaglegateVerifierFailure, RuntimeError)
    assert EaglegateProposerFailure is not EaglegateVerifierFailure

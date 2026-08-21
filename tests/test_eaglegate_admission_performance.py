from __future__ import annotations

import copy
from dataclasses import asdict, replace
import hashlib
import pickle

import pytest

from staqtapp_tds.eaglegate import (
    EaglegateAdmissionPolicy,
    EaglegateContractError,
    EaglegateDecisionKind,
    EaglegateFault,
    EaglegateIdentity,
    EaglegateMode,
    EaglegatePlan,
    EaglegateRequestClass,
    EaglegateRuntimeHealth,
    EaglegateSamplerClass,
    EaglegateSpeculationEpoch,
    evaluate_admission,
)
from staqtapp_tds.eaglegate import admission as admission_module
from staqtapp_tds.eaglegate import plans as plans_module


def _root(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("ascii")).hexdigest()


def _identity() -> EaglegateIdentity:
    return EaglegateIdentity(
        target_model_root=_root("target"),
        tokenizer_root=_root("tokenizer"),
        proposer_root=_root("proposer"),
        target_runtime_root=_root("runtime"),
        sampler_contract_root=_root("sampler"),
        logits_processor_root=_root("logits"),
        kv_contract_root=_root("kv"),
        kernel_capability_root=_root("capability"),
        numerical_mode="fp16-deterministic-a",
        tenant_scope="tenant-a",
    )


def _plan(plan_id: str, *, max_batch: int = 4) -> EaglegatePlan:
    return EaglegatePlan(
        plan_id=plan_id,
        candidate_tokens=4,
        max_tree_nodes=8,
        workspace_budget_bytes=64 << 20,
        max_batch=max_batch,
        max_concurrency=8,
        max_context_tokens=32_768,
        max_kv_pressure_ppm=700_000,
        sampler_classes=(
            EaglegateSamplerClass.GREEDY,
            EaglegateSamplerClass.LOSSLESS_SAMPLING,
        ),
    )


def _epoch(
    identity: EaglegateIdentity,
    plans: tuple[EaglegatePlan, ...],
) -> EaglegateSpeculationEpoch:
    return EaglegateSpeculationEpoch(
        generation=1,
        identity=identity,
        plans=plans,
        policy=EaglegateAdmissionPolicy(
            policy_id="policy-v1",
            mode=EaglegateMode.SHADOW,
            plan_order=tuple(plan.plan_id for plan in plans),
        ),
    )


def _request(epoch: EaglegateSpeculationEpoch, *, batch_size: int = 1):
    return EaglegateRequestClass(
        identity_root=epoch.identity_root,
        sampler_class=EaglegateSamplerClass.GREEDY,
        batch_size=batch_size,
        concurrency=1,
        context_tokens=1_024,
        kv_pressure_ppm=100_000,
        request_bucket=0,
    )


def _health(epoch: EaglegateSpeculationEpoch) -> EaglegateRuntimeHealth:
    return EaglegateRuntimeHealth(
        epoch_root=epoch.epoch_root,
        identity_root=epoch.identity_root,
        target_available=True,
        proposer_available=True,
        workspace_available_bytes=1 << 30,
    )


def test_cached_roots_preserve_v381_canonical_bytes() -> None:
    identity = _identity()
    plan = _plan("eagle-linear-4")
    epoch = _epoch(identity, (plan,))
    request = _request(epoch)
    decision = evaluate_admission(epoch, request, _health(epoch))

    assert identity.identity_root == (
        "sha256:f53e77efa006936f08db23a648aeda237160ac0bc1e5c24abcf6f3ab32b776d4"
    )
    assert plan.plan_root == (
        "sha256:7380d42193e5d528a367f5ec6477128c2a87d5516e66b7f3a5916e8cc9df99f1"
    )
    assert epoch.policy_root == (
        "sha256:fe869c323a1a197581808177e4e83cb07565c797e44f370f2002abe3a2d35a7b"
    )
    assert epoch.epoch_root == (
        "sha256:041b7e866b1023e915f469c00f86b99f5350602c279f8cd77ddaf22332ab6b39"
    )
    assert request.request_class_root == (
        "sha256:8304712610aaafacd5f3cc3712655e316349d0ea048ef5c1c6eafa0fbba0992b"
    )
    assert decision.decision_root == (
        "sha256:22c0adadc5b942c7de63f475e97f089f82900ed67189639eeda8610b615d3fa3"
    )


def test_derived_caches_are_private_immutable_and_not_dataclass_state() -> None:
    epoch = _epoch(_identity(), (_plan("eagle-linear-4"),))
    request = _request(epoch)

    assert set(asdict(epoch)) == {
        "generation",
        "identity",
        "plans",
        "policy",
        "qualification_root",
        "previous_epoch_root",
    }
    assert set(asdict(request)) == {
        "identity_root",
        "sampler_class",
        "batch_size",
        "concurrency",
        "context_tokens",
        "kv_pressure_ppm",
        "request_bucket",
        "deadline_class",
    }
    assert epoch == replace(epoch)
    assert request == replace(request)
    with pytest.raises(TypeError):
        epoch._plans_by_id_cache["other"] = epoch.plans[0]  # type: ignore[index]


@pytest.mark.parametrize("copier", [copy.copy, copy.deepcopy, pickle.dumps])
def test_cache_slots_survive_standard_copy_protocols(copier) -> None:
    epoch = _epoch(_identity(), (_plan("eagle-linear-4"),))
    request = _request(epoch)

    if copier is pickle.dumps:
        copied_epoch = pickle.loads(copier(epoch))
        copied_request = pickle.loads(copier(request))
    else:
        copied_epoch = copier(epoch)
        copied_request = copier(request)

    assert copied_epoch.epoch_root == epoch.epoch_root
    assert copied_epoch.plan_by_id("eagle-linear-4") == epoch.plans[0]
    assert copied_request.request_class_root == request.request_class_root


def test_admission_reuses_epoch_request_and_identity_roots(monkeypatch) -> None:
    identity = _identity()
    epoch = _epoch(identity, (_plan("eagle-linear-4"),))
    request = _request(epoch)
    health = _health(epoch)
    expected = evaluate_admission(epoch, request, health)

    def unexpected_root(*_args, **_kwargs):
        raise AssertionError("immutable admission root was recomputed")

    monkeypatch.setattr(plans_module, "_canonical_root", unexpected_root)
    monkeypatch.setattr(admission_module, "_canonical_root", unexpected_root)
    monkeypatch.setattr(
        EaglegateIdentity,
        "identity_root",
        property(unexpected_root),
    )

    assert epoch.epoch_root == health.epoch_root
    assert request.request_class_root == expected.request_class_root
    assert epoch.canonical_dict()["identity_root"] == health.identity_root
    assert evaluate_admission(epoch, request, health) == expected


def test_policy_validation_and_admission_plan_lookup_scale_linearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 128
    plan_ids = tuple(f"eagle-linear-{index}" for index in range(count))
    plans = tuple(
        _plan(plan_id, max_batch=2 if index == count - 1 else 1)
        for index, plan_id in enumerate(plan_ids)
    )
    policy = EaglegateAdmissionPolicy(
        policy_id="scaling-policy",
        mode=EaglegateMode.SHADOW,
        plan_order=plan_ids,
    )

    epoch = EaglegateSpeculationEpoch(1, _identity(), plans, policy)
    assert len(epoch._plans_by_id_cache) == count
    assert all(epoch.plan_by_id(plan_id) is plans[index] for index, plan_id in enumerate(plan_ids))

    lookup_calls = 0
    original_lookup = EaglegateSpeculationEpoch.plan_by_id

    def counted_lookup(self, plan_id):
        nonlocal lookup_calls
        lookup_calls += 1
        return original_lookup(self, plan_id)

    monkeypatch.setattr(EaglegateSpeculationEpoch, "plan_by_id", counted_lookup)
    decision = evaluate_admission(
        epoch,
        _request(epoch, batch_size=2),
        _health(epoch),
    )
    assert decision.kind is EaglegateDecisionKind.ABSTAIN
    assert decision.plan_id == plan_ids[-1]
    assert lookup_calls <= count


def test_plan_ids_reject_string_subclasses_before_cache_construction() -> None:
    class OddHash(str):
        def __hash__(self) -> int:
            return 0

    with pytest.raises(EaglegateContractError, match="plan_id must be a valid string"):
        _plan(OddHash("eagle-linear-0"))


def test_epoch_cache_rebuild_cannot_accept_attacker_supplied_plan_state() -> None:
    epoch = _epoch(_identity(), (_plan("eagle-restrictive", max_batch=1),))

    assert not hasattr(epoch, "_set_derived_caches")
    with pytest.raises(TypeError):
        epoch._rebuild_derived_caches(  # type: ignore[call-arg]
            (_plan("eagle-permissive", max_batch=100).plan_root,),
            {"eagle-restrictive": _plan("eagle-permissive", max_batch=100)},
        )
    assert epoch.plan_by_id("eagle-restrictive").max_batch == 1


def test_unknown_plan_lookup_preserves_identity_mismatch_fault() -> None:
    epoch = _epoch(_identity(), (_plan("eagle-linear-4"),))
    with pytest.raises(EaglegateContractError) as caught:
        epoch.plan_by_id([])  # type: ignore[arg-type]
    assert str(caught.value) == "unknown plan"
    assert caught.value.fault is EaglegateFault.IDENTITY_MISMATCH

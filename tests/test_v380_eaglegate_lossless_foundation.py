from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path

import pytest

from staqtapp_tds.eaglegate import (
    EAGLEGATE_AUTHORITY,
    EAGLEGATE_CAPABILITY_SNAPSHOT_ID,
    EaglegateAdmissionPolicy,
    EaglegateAuthorityBoundary,
    EaglegateContractError,
    EaglegateDecisionKind,
    EaglegateEpisodeReceipt,
    EaglegateEpochReceipt,
    EaglegateEpochState,
    EaglegateFault,
    EaglegateIdentity,
    EaglegateLock,
    EaglegateMode,
    EaglegatePlan,
    EaglegateQualificationSummary,
    EaglegateRequestClass,
    EaglegateRuntimeHealth,
    EaglegateSamplerClass,
    EaglegateSpeculationEpoch,
    compile_project,
    epoch_diff,
    evaluate_admission,
    initialize_project,
    load_project,
    resolve_lock_from_snapshot,
    validate_epoch_transition,
    validate_qualification_for_epoch,
)
from staqtapp_tds.eaglegate.console import main as console_main


def root(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("ascii")).hexdigest()


def identity(**changes) -> EaglegateIdentity:
    values = {
        "target_model_root": root("target"),
        "tokenizer_root": root("tokenizer"),
        "proposer_root": root("proposer"),
        "target_runtime_root": root("runtime"),
        "sampler_contract_root": root("sampler"),
        "logits_processor_root": root("logits"),
        "kv_contract_root": root("kv"),
        "kernel_capability_root": root("capability"),
        "numerical_mode": "fp16-deterministic-a",
        "tenant_scope": "tenant-a",
    }
    values.update(changes)
    return EaglegateIdentity(**values)


def plan(**changes) -> EaglegatePlan:
    values = {
        "plan_id": "eagle-linear-4",
        "candidate_tokens": 4,
        "max_tree_nodes": 8,
        "workspace_budget_bytes": 64 << 20,
        "max_batch": 4,
        "max_concurrency": 8,
        "max_context_tokens": 32_768,
        "max_kv_pressure_ppm": 700_000,
        "sampler_classes": (
            EaglegateSamplerClass.GREEDY,
            EaglegateSamplerClass.LOSSLESS_SAMPLING,
        ),
    }
    values.update(changes)
    return EaglegatePlan(**values)


def epoch(
    *,
    mode: EaglegateMode = EaglegateMode.SHADOW,
    canary_basis_points: int = 0,
    qualification_root: str = "",
    identity_value: EaglegateIdentity | None = None,
    plans: tuple[EaglegatePlan, ...] | None = None,
) -> EaglegateSpeculationEpoch:
    plan_values = plans or (plan(),)
    return EaglegateSpeculationEpoch(
        generation=1,
        identity=identity_value or identity(),
        plans=plan_values,
        policy=EaglegateAdmissionPolicy(
            "policy-v1",
            mode,
            tuple(item.plan_id for item in plan_values),
            canary_basis_points,
        ),
        qualification_root=qualification_root,
    )


def request(value: EaglegateSpeculationEpoch, **changes) -> EaglegateRequestClass:
    fields = {
        "identity_root": value.identity.identity_root,
        "sampler_class": EaglegateSamplerClass.GREEDY,
        "batch_size": 1,
        "concurrency": 1,
        "context_tokens": 1_024,
        "kv_pressure_ppm": 100_000,
        "request_bucket": 0,
    }
    fields.update(changes)
    return EaglegateRequestClass(**fields)


def health(value: EaglegateSpeculationEpoch, **changes) -> EaglegateRuntimeHealth:
    fields = {
        "epoch_root": value.epoch_root,
        "identity_root": value.identity.identity_root,
        "target_available": True,
        "proposer_available": True,
        "workspace_available_bytes": 1 << 30,
    }
    fields.update(changes)
    return EaglegateRuntimeHealth(**fields)


def capability_snapshot(**changes) -> dict[str, object]:
    values: dict[str, object] = {
        "snapshot_contract_id": EAGLEGATE_CAPABILITY_SNAPSHOT_ID,
        "target_model_root": root("target"),
        "tokenizer_root": root("tokenizer"),
        "proposer_root": root("proposer"),
        "target_runtime_root": root("runtime"),
        "sampler_contract_root": root("sampler"),
        "logits_processor_root": root("logits"),
        "kv_contract_root": root("kv"),
        "numerical_mode": "fp16-deterministic-a",
        "tenant_scope": "tenant-a",
        "proposer_family": "eagle",
        "max_candidate_tokens": 16,
        "max_tree_nodes": 32,
        "max_workspace_budget_bytes": 256 << 20,
        "max_batch": 16,
        "max_concurrency": 32,
        "max_context_tokens": 131_072,
        "max_kv_pressure_ppm": 800_000,
        "sampler_classes": ["greedy", "lossless_sampling"],
    }
    values.update(changes)
    return values


def test_lossless_constitution_is_fixed_and_machine_checkable():
    snapshot = EAGLEGATE_AUTHORITY.canonical_dict()
    assert snapshot["target_verifier_required"] is True
    assert snapshot["target_sampler_is_acceptance_authority"] is True
    assert snapshot["target_runtime_is_commit_authority"] is True
    assert snapshot["proposer_may_accept_tokens"] is False
    assert snapshot["proposer_may_commit_kv"] is False
    assert snapshot["approximate_acceptance_allowed"] is False
    assert snapshot["semantic_similarity_acceptance_allowed"] is False
    assert snapshot["target_only_fallback_required"] is True
    assert snapshot["console_may_activate"] is False
    with pytest.raises(EaglegateContractError) as caught:
        EaglegateAuthorityBoundary(approximate_acceptance_allowed=True)
    assert caught.value.fault is EaglegateFault.AUTHORITY_REJECTED


def test_identity_plan_epoch_are_canonical_and_immutable():
    identity_value = identity()
    assert identity_value.identity_root == identity().identity_root
    assert replace(identity_value, numerical_mode="bf16").identity_root != identity_value.identity_root
    plan_value = plan()
    assert plan_value.plan_root == plan().plan_root
    assert replace(plan_value, candidate_tokens=5).plan_root != plan_value.plan_root
    value = epoch(identity_value=identity_value, plans=(plan_value,))
    assert value.epoch_root == epoch(identity_value=identity_value, plans=(plan_value,)).epoch_root
    with pytest.raises(FrozenInstanceError):
        value.generation = 2  # type: ignore[misc]


def test_bounds_and_qualification_fail_closed():
    with pytest.raises(EaglegateContractError):
        plan(candidate_tokens=9, max_tree_nodes=8)
    with pytest.raises(EaglegateContractError):
        plan(max_kv_pressure_ppm=1_000_001)
    with pytest.raises(EaglegateContractError) as caught:
        epoch(mode=EaglegateMode.CANARY, canary_basis_points=100)
    assert caught.value.fault is EaglegateFault.QUALIFICATION_REQUIRED


def test_admission_is_deterministic_and_only_selects_plans():
    shadow = epoch()
    decision = evaluate_admission(shadow, request(shadow), health(shadow))
    assert decision.kind is EaglegateDecisionKind.ABSTAIN
    assert decision.plan_id == "eagle-linear-4"
    target = epoch(mode=EaglegateMode.TARGET_ONLY)
    decision = evaluate_admission(target, request(target), health(target))
    assert decision.kind is EaglegateDecisionKind.FALLBACK
    assert decision.reason == "policy_target_only"
    canary = epoch(
        mode=EaglegateMode.CANARY,
        canary_basis_points=100,
        qualification_root=root("qualification"),
    )
    assert evaluate_admission(
        canary, request(canary, request_bucket=99), health(canary)
    ).kind is EaglegateDecisionKind.ADMIT
    assert evaluate_admission(
        canary, request(canary, request_bucket=100), health(canary)
    ).reason == "outside_canary"


def test_identity_and_resource_failures_are_contained():
    value = epoch()
    mismatch = evaluate_admission(
        value, request(value, identity_root=root("other")), health(value)
    )
    assert mismatch.kind is EaglegateDecisionKind.FAULT
    assert mismatch.fault is EaglegateFault.IDENTITY_MISMATCH
    unavailable = evaluate_admission(
        value, request(value), health(value, proposer_available=False)
    )
    assert unavailable.kind is EaglegateDecisionKind.FALLBACK
    assert unavailable.reason == "proposer_unavailable"
    workspace = evaluate_admission(
        value, request(value), health(value, workspace_available_bytes=1)
    )
    assert workspace.reason == "workspace_limit"


def test_qualification_binds_exact_identity_and_plan_order():
    value = epoch()
    summary = EaglegateQualificationSummary(
        "eg-exact-v1",
        value.identity.identity_root,
        tuple(item.plan_root for item in value.plans),
        True,
        100,
        100,
        100,
        100,
        True,
        True,
        True,
        True,
    )
    assert summary.qualified
    assert validate_qualification_for_epoch(value, summary) is summary
    with pytest.raises(EaglegateContractError) as caught:
        validate_qualification_for_epoch(value, replace(summary, identity_root=root("wrong")))
    assert caught.value.fault is EaglegateFault.IDENTITY_MISMATCH
    with pytest.raises(EaglegateContractError) as caught:
        validate_qualification_for_epoch(value, replace(summary, sampled_distribution_cases=0))
    assert caught.value.fault is EaglegateFault.QUALIFICATION_REQUIRED


def test_epoch_receipts_are_append_only_and_identity_bound():
    value = epoch()
    draft = EaglegateEpochReceipt(value.epoch_root, EaglegateEpochState.DRAFT)
    qualified = EaglegateEpochReceipt(
        value.epoch_root,
        EaglegateEpochState.QUALIFIED,
        root("qualification"),
        draft.receipt_root,
    )
    assert validate_epoch_transition(draft, qualified) is qualified
    active = EaglegateEpochReceipt(
        value.epoch_root,
        EaglegateEpochState.ACTIVE,
        qualified.qualification_root,
        qualified.receipt_root,
    )
    with pytest.raises(EaglegateContractError):
        validate_epoch_transition(qualified, active)


def test_episode_receipts_reject_private_content():
    value = epoch()
    decision = evaluate_admission(value, request(value), health(value))
    receipt = EaglegateEpisodeReceipt(
        value.epoch_root,
        decision.decision_root,
        request(value).request_class_root,
        4,
        4,
        3,
        4,
        1,
        10,
        20,
        5,
        2,
        1,
    )
    assert receipt.receipt_root.startswith("sha256:")
    with pytest.raises(EaglegateContractError) as caught:
        replace(receipt, prompt_content_persisted=True)
    assert caught.value.fault is EaglegateFault.AUTHORITY_REJECTED


def test_configuration_is_unresolved_then_capability_bound(tmp_path: Path):
    initialize_project(tmp_path)
    config, lock = load_project(tmp_path)
    assert config.mode is EaglegateMode.SHADOW
    assert lock.resolved is False
    with pytest.raises(EaglegateContractError) as caught:
        compile_project(tmp_path)
    assert caught.value.fault is EaglegateFault.QUALIFICATION_REQUIRED
    snapshot = tmp_path / "capabilities.json"
    snapshot.write_text(json.dumps(capability_snapshot()), encoding="utf-8")
    resolve_lock_from_snapshot(tmp_path, snapshot)
    config, lock = load_project(tmp_path)
    compiled = config.compile(lock)
    assert compiled.identity.kernel_capability_root == lock.capability_root
    narrow = EaglegateLock.from_mapping(
        {"schema": 1, **capability_snapshot(max_candidate_tokens=2), "resolved": True}
    )
    with pytest.raises(EaglegateContractError) as caught:
        config.compile(narrow)
    assert caught.value.fault is EaglegateFault.INCOMPATIBLE


def test_epoch_diff_requires_requalification_for_identity_or_plan_changes():
    base = epoch()
    changed = epoch(plans=(replace(plan(), candidate_tokens=5),))
    result = epoch_diff(base, changed)
    assert result["plans_changed"] == ["eagle-linear-4"]
    assert result["requires_full_requalification"] is True


def test_console_configures_and_simulates_without_authority(tmp_path: Path, capsys):
    assert console_main(["init", "--directory", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["serving_effect"] == "target_only"
    assert console_main(["validate", "--directory", str(tmp_path)]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["fault"] == "qualification_required"
    assert failure["activation_authority"] is False
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(capability_snapshot()), encoding="utf-8")
    assert console_main(
        ["resolve", "--directory", str(tmp_path), "--snapshot", str(snapshot)]
    ) == 0
    capsys.readouterr()
    assert console_main(["validate", "--directory", str(tmp_path)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["serving_effect"] == "target_only"
    assert validated["candidate_mode"] == "shadow"
    value = compile_project(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "sampler_class": "greedy",
                "batch_size": 1,
                "concurrency": 1,
                "context_tokens": 100,
                "kv_pressure_ppm": 1,
                "request_bucket": 0,
            }
        ),
        encoding="utf-8",
    )
    health_path = tmp_path / "health.json"
    health_path.write_text(
        json.dumps(
            {
                "target_available": True,
                "proposer_available": True,
                "workspace_available_bytes": 1 << 30,
            }
        ),
        encoding="utf-8",
    )
    assert console_main(
        [
            "evaluate",
            "--directory",
            str(tmp_path),
            "--request",
            str(request_path),
            "--health",
            str(health_path),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["simulation_only"] is True
    assert result["activation_authority"] is False
    assert result["decision"]["kind"] == "abstain"
    assert result["decision"]["epoch_root"] == value.epoch_root

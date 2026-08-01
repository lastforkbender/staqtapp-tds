"""Immutable Eaglegate configuration and conservative profiles."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from .capability import EAGLEGATE_CONFIG_SCHEMA, EaglegateLock
from .contract import (
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
    EaglegateContractError,
    EaglegateFault,
    EaglegateMode,
    EaglegateSamplerClass,
    _ascii,
    _canonical_root,
    _int,
    _root,
)
from .plans import (
    EaglegateAdmissionPolicy,
    EaglegatePlan,
    EaglegateQualificationSummary,
    EaglegateSpeculationEpoch,
    validate_qualification_for_epoch,
)


@dataclass(frozen=True, slots=True)
class EaglegateConfiguration:
    profile: str
    generation: int
    policy_id: str
    mode: EaglegateMode
    canary_basis_points: int
    plans: tuple[EaglegatePlan, ...]
    previous_epoch_root: str = ""

    def __post_init__(self) -> None:
        _ascii("profile", self.profile)
        _int("generation", self.generation, 1)
        _ascii("policy_id", self.policy_id)
        if not isinstance(self.mode, EaglegateMode):
            raise EaglegateContractError("invalid mode")
        _int("canary_basis_points", self.canary_basis_points, 0, 10_000)
        if not isinstance(self.plans, tuple) or not self.plans:
            raise EaglegateContractError("plans must be a non-empty tuple")
        if any(not isinstance(plan, EaglegatePlan) for plan in self.plans):
            raise EaglegateContractError("invalid plan")
        _root("previous_epoch_root", self.previous_epoch_root, empty=True)
        EaglegateAdmissionPolicy(
            policy_id=self.policy_id,
            mode=self.mode,
            plan_order=tuple(plan.plan_id for plan in self.plans),
            canary_basis_points=self.canary_basis_points,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "profile": self.profile,
            "generation": self.generation,
            "policy_id": self.policy_id,
            "mode": self.mode.value,
            "canary_basis_points": self.canary_basis_points,
            "plans": [plan.canonical_dict() for plan in self.plans],
            "previous_epoch_root": self.previous_epoch_root,
        }

    @property
    def configuration_root(self) -> str:
        return _canonical_root("configuration", self.canonical_dict())

    def validate_against_lock(self, lock: EaglegateLock) -> None:
        if not lock.resolved:
            raise EaglegateContractError(
                "lock unresolved; compilation is fail-closed",
                fault=EaglegateFault.QUALIFICATION_REQUIRED,
            )
        for plan in self.plans:
            checks = (
                (plan.candidate_tokens, lock.max_candidate_tokens, "candidate_tokens"),
                (plan.max_tree_nodes, lock.max_tree_nodes, "max_tree_nodes"),
                (
                    plan.workspace_budget_bytes,
                    lock.max_workspace_budget_bytes,
                    "workspace_budget_bytes",
                ),
                (plan.max_batch, lock.max_batch, "max_batch"),
                (plan.max_concurrency, lock.max_concurrency, "max_concurrency"),
                (
                    plan.max_context_tokens,
                    lock.max_context_tokens,
                    "max_context_tokens",
                ),
                (
                    plan.max_kv_pressure_ppm,
                    lock.max_kv_pressure_ppm,
                    "max_kv_pressure_ppm",
                ),
            )
            for requested, supported, name in checks:
                if requested > supported:
                    raise EaglegateContractError(
                        f"{plan.plan_id} exceeds {name} capability",
                        fault=EaglegateFault.INCOMPATIBLE,
                    )
            if any(v not in lock.sampler_classes for v in plan.sampler_classes):
                raise EaglegateContractError(
                    f"{plan.plan_id} uses unsupported sampler",
                    fault=EaglegateFault.INCOMPATIBLE,
                )

    def compile(
        self,
        lock: EaglegateLock,
        qualification: EaglegateQualificationSummary | None = None,
    ) -> EaglegateSpeculationEpoch:
        self.validate_against_lock(lock)
        epoch = EaglegateSpeculationEpoch(
            generation=self.generation,
            identity=lock.identity(),
            plans=self.plans,
            policy=EaglegateAdmissionPolicy(
                policy_id=self.policy_id,
                mode=self.mode,
                plan_order=tuple(plan.plan_id for plan in self.plans),
                canary_basis_points=self.canary_basis_points,
            ),
            qualification_root=(
                qualification.qualification_root if qualification else ""
            ),
            previous_epoch_root=self.previous_epoch_root,
        )
        if qualification:
            validate_qualification_for_epoch(epoch, qualification)
        return epoch

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EaglegateConfiguration":
        values = dict(data)
        if values.pop("schema", 1) != EAGLEGATE_CONFIG_SCHEMA:
            raise EaglegateContractError(
                "unsupported configuration schema",
                fault=EaglegateFault.INCOMPATIBLE,
            )
        deployment = values.pop("deployment", values.pop("mode", None))
        try:
            mode = EaglegateMode(str(deployment))
        except ValueError as exc:
            raise EaglegateContractError(
                "unsupported deployment mode", fault=EaglegateFault.INCOMPATIBLE
            ) from exc
        plans_data = values.pop("plans", None)
        if not isinstance(plans_data, list) or not plans_data:
            raise EaglegateContractError("configuration needs [[plans]]")
        plans: list[EaglegatePlan] = []
        plan_fields = set(EaglegatePlan.__dataclass_fields__)
        for item in plans_data:
            if not isinstance(item, Mapping):
                raise EaglegateContractError("plan must be a table")
            plan_data = dict(item)
            sampler_values = plan_data.pop("sampler_classes", None)
            if isinstance(sampler_values, str) or not isinstance(
                sampler_values, Sequence
            ):
                raise EaglegateContractError("sampler_classes must be an array")
            try:
                samplers = tuple(
                    EaglegateSamplerClass(str(v)) for v in sampler_values
                )
            except ValueError as exc:
                raise EaglegateContractError(
                    "unsupported sampler", fault=EaglegateFault.INCOMPATIBLE
                ) from exc
            unknown = sorted(set(plan_data) - plan_fields)
            if unknown:
                raise EaglegateContractError(
                    f"unknown plan fields: {unknown}",
                    fault=EaglegateFault.NONCANONICAL,
                )
            plans.append(EaglegatePlan(sampler_classes=samplers, **plan_data))
        allowed = set(cls.__dataclass_fields__) - {"mode", "plans"}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise EaglegateContractError(
                f"unknown configuration fields: {unknown}",
                fault=EaglegateFault.NONCANONICAL,
            )
        return cls(mode=mode, plans=tuple(plans), **values)


def _plan(
    plan_id: str,
    tokens: int,
    nodes: int,
    workspace: int,
    batch: int,
    concurrency: int,
    context: int,
    pressure: int,
) -> EaglegatePlan:
    return EaglegatePlan(
        plan_id=plan_id,
        candidate_tokens=tokens,
        max_tree_nodes=nodes,
        workspace_budget_bytes=workspace,
        max_batch=batch,
        max_concurrency=concurrency,
        max_context_tokens=context,
        max_kv_pressure_ppm=pressure,
        sampler_classes=(
            EaglegateSamplerClass.GREEDY,
            EaglegateSamplerClass.LOSSLESS_SAMPLING,
        ),
    )


def profile_configuration(profile: str = "conservative") -> EaglegateConfiguration:
    if profile == "observe":
        return EaglegateConfiguration(
            profile, 1, "eaglegate-observe-v1", EaglegateMode.TARGET_ONLY, 0,
            (_plan("eagle-linear-4", 4, 8, 64 << 20, 2, 4, 16_384, 600_000),),
        )
    if profile == "conservative":
        return EaglegateConfiguration(
            profile, 1, "eaglegate-conservative-v1", EaglegateMode.SHADOW, 0,
            (_plan("eagle-linear-4", 4, 8, 64 << 20, 4, 8, 32_768, 700_000),),
        )
    if profile == "balanced":
        return EaglegateConfiguration(
            profile, 1, "eaglegate-balanced-v1", EaglegateMode.SHADOW, 0,
            (
                _plan("eagle-linear-8", 8, 16, 128 << 20, 4, 8, 32_768, 650_000),
                _plan("eagle-linear-4", 4, 8, 64 << 20, 8, 16, 65_536, 750_000),
            ),
        )
    raise EaglegateContractError(
        "profile must be observe, conservative, or balanced",
        fault=EaglegateFault.INCOMPATIBLE,
    )


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def configuration_to_toml(config: EaglegateConfiguration) -> str:
    lines = [
        f"schema = {EAGLEGATE_CONFIG_SCHEMA}",
        f"profile = {_quote(config.profile)}",
        f"generation = {config.generation}",
        f"policy_id = {_quote(config.policy_id)}",
        f"deployment = {_quote(config.mode.value)}",
        f"canary_basis_points = {config.canary_basis_points}",
        f"previous_epoch_root = {_quote(config.previous_epoch_root)}",
        "",
        "# Losslessness is constitutional and is not configurable.",
    ]
    for plan in config.plans:
        lines += [
            "",
            "[[plans]]",
            f"plan_id = {_quote(plan.plan_id)}",
            f"candidate_tokens = {plan.candidate_tokens}",
            f"max_tree_nodes = {plan.max_tree_nodes}",
            f"workspace_budget_bytes = {plan.workspace_budget_bytes}",
            f"max_batch = {plan.max_batch}",
            f"max_concurrency = {plan.max_concurrency}",
            f"max_context_tokens = {plan.max_context_tokens}",
            f"max_kv_pressure_ppm = {plan.max_kv_pressure_ppm}",
            "sampler_classes = ["
            + ", ".join(_quote(v.value) for v in plan.sampler_classes)
            + "]",
        ]
    return "\n".join(lines) + "\n"


__all__ = [
    "EaglegateConfiguration",
    "configuration_to_toml",
    "profile_configuration",
]

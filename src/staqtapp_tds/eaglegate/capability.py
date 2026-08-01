"""Resolved Eaglegate capability identity and generated lock contract."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from .contract import (
    EAGLEGATE_CAPABILITY_SNAPSHOT_ID,
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
    EAGLEGATE_PROPOSER_FAMILY,
    EaglegateContractError,
    EaglegateFault,
    EaglegateIdentity,
    EaglegateSamplerClass,
    _ascii,
    _bool,
    _canonical_root,
    _int,
    _root,
)

EAGLEGATE_CONFIG_FILENAME = "eaglegate.toml"
EAGLEGATE_LOCK_FILENAME = "eaglegate.lock"
EAGLEGATE_CONFIG_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class EaglegateLock:
    resolved: bool
    target_model_root: str = ""
    tokenizer_root: str = ""
    proposer_root: str = ""
    target_runtime_root: str = ""
    sampler_contract_root: str = ""
    logits_processor_root: str = ""
    kv_contract_root: str = ""
    numerical_mode: str = ""
    tenant_scope: str = ""
    proposer_family: str = EAGLEGATE_PROPOSER_FAMILY
    max_candidate_tokens: int = 0
    max_tree_nodes: int = 0
    max_workspace_budget_bytes: int = 0
    max_batch: int = 0
    max_concurrency: int = 0
    max_context_tokens: int = 0
    max_kv_pressure_ppm: int = 0
    sampler_classes: tuple[EaglegateSamplerClass, ...] = ()
    snapshot_contract_id: str = EAGLEGATE_CAPABILITY_SNAPSHOT_ID

    def __post_init__(self) -> None:
        _bool("resolved", self.resolved)
        if self.proposer_family != EAGLEGATE_PROPOSER_FAMILY:
            raise EaglegateContractError(
                "only EAGLE-family proposers are supported",
                fault=EaglegateFault.INCOMPATIBLE,
            )
        if self.snapshot_contract_id != EAGLEGATE_CAPABILITY_SNAPSHOT_ID:
            raise EaglegateContractError(
                "unsupported capability snapshot",
                fault=EaglegateFault.INCOMPATIBLE,
            )
        if not isinstance(self.sampler_classes, tuple):
            raise EaglegateContractError("sampler_classes must be a tuple")
        if any(
            not isinstance(value, EaglegateSamplerClass)
            for value in self.sampler_classes
        ):
            raise EaglegateContractError("invalid sampler class")
        if len(set(self.sampler_classes)) != len(self.sampler_classes):
            raise EaglegateContractError(
                "duplicate sampler class", fault=EaglegateFault.NONCANONICAL
            )
        roots = (
            "target_model_root",
            "tokenizer_root",
            "proposer_root",
            "target_runtime_root",
            "sampler_contract_root",
            "logits_processor_root",
            "kv_contract_root",
        )
        texts = ("numerical_mode", "tenant_scope")
        limits = (
            "max_candidate_tokens",
            "max_tree_nodes",
            "max_workspace_budget_bytes",
            "max_batch",
            "max_concurrency",
            "max_context_tokens",
            "max_kv_pressure_ppm",
        )
        if self.resolved:
            for name in roots:
                _root(name, getattr(self, name))
            for name in texts:
                _ascii(name, getattr(self, name))
            for name in limits[:-1]:
                _int(name, getattr(self, name), 1)
            _int("max_kv_pressure_ppm", self.max_kv_pressure_ppm, 0, 1_000_000)
            if not self.sampler_classes:
                raise EaglegateContractError("resolved lock needs sampler classes")
        else:
            if any(getattr(self, name) != "" for name in roots + texts):
                raise EaglegateContractError(
                    "unresolved lock contains identity",
                    fault=EaglegateFault.NONCANONICAL,
                )
            if any(getattr(self, name) != 0 for name in limits):
                raise EaglegateContractError(
                    "unresolved lock contains limits",
                    fault=EaglegateFault.NONCANONICAL,
                )
            if self.sampler_classes:
                raise EaglegateContractError(
                    "unresolved lock contains sampler classes",
                    fault=EaglegateFault.NONCANONICAL,
                )

    def capability_dict(self) -> dict[str, Any]:
        return {
            "snapshot_contract_id": self.snapshot_contract_id,
            "proposer_family": self.proposer_family,
            "max_candidate_tokens": self.max_candidate_tokens,
            "max_tree_nodes": self.max_tree_nodes,
            "max_workspace_budget_bytes": self.max_workspace_budget_bytes,
            "max_batch": self.max_batch,
            "max_concurrency": self.max_concurrency,
            "max_context_tokens": self.max_context_tokens,
            "max_kv_pressure_ppm": self.max_kv_pressure_ppm,
            "sampler_classes": [item.value for item in self.sampler_classes],
        }

    @property
    def capability_root(self) -> str:
        return _canonical_root("capability-lock", self.capability_dict())

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_CONTRACT_ID,
            "format_version": EAGLEGATE_FORMAT_VERSION,
            "resolved": self.resolved,
            "target_model_root": self.target_model_root,
            "tokenizer_root": self.tokenizer_root,
            "proposer_root": self.proposer_root,
            "target_runtime_root": self.target_runtime_root,
            "sampler_contract_root": self.sampler_contract_root,
            "logits_processor_root": self.logits_processor_root,
            "kv_contract_root": self.kv_contract_root,
            "numerical_mode": self.numerical_mode,
            "tenant_scope": self.tenant_scope,
            **self.capability_dict(),
            "capability_root": self.capability_root,
        }

    @property
    def lock_root(self) -> str:
        return _canonical_root("lock", self.canonical_dict())

    def identity(self) -> EaglegateIdentity:
        if not self.resolved:
            raise EaglegateContractError(
                "lock unresolved; target-only remains required",
                fault=EaglegateFault.QUALIFICATION_REQUIRED,
            )
        return EaglegateIdentity(
            target_model_root=self.target_model_root,
            tokenizer_root=self.tokenizer_root,
            proposer_root=self.proposer_root,
            target_runtime_root=self.target_runtime_root,
            sampler_contract_root=self.sampler_contract_root,
            logits_processor_root=self.logits_processor_root,
            kv_contract_root=self.kv_contract_root,
            kernel_capability_root=self.capability_root,
            numerical_mode=self.numerical_mode,
            tenant_scope=self.tenant_scope,
        )

    @classmethod
    def unresolved(cls) -> "EaglegateLock":
        return cls(resolved=False)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EaglegateLock":
        values = dict(data)
        if values.pop("schema", 1) != EAGLEGATE_CONFIG_SCHEMA:
            raise EaglegateContractError(
                "unsupported lock schema", fault=EaglegateFault.INCOMPATIBLE
            )
        sampler_values = values.pop("sampler_classes", ())
        if isinstance(sampler_values, str) or not isinstance(
            sampler_values, Sequence
        ):
            raise EaglegateContractError("sampler_classes must be an array")
        try:
            samplers = tuple(EaglegateSamplerClass(str(v)) for v in sampler_values)
        except ValueError as exc:
            raise EaglegateContractError(
                "unsupported sampler class", fault=EaglegateFault.INCOMPATIBLE
            ) from exc
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise EaglegateContractError(
                f"unknown lock fields: {unknown}", fault=EaglegateFault.NONCANONICAL
            )
        return cls(sampler_classes=samplers, **values)


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def lock_to_toml(lock: EaglegateLock) -> str:
    values = lock.canonical_dict()
    keys = (
        "resolved",
        "snapshot_contract_id",
        "proposer_family",
        "target_model_root",
        "tokenizer_root",
        "proposer_root",
        "target_runtime_root",
        "sampler_contract_root",
        "logits_processor_root",
        "kv_contract_root",
        "numerical_mode",
        "tenant_scope",
        "max_candidate_tokens",
        "max_tree_nodes",
        "max_workspace_budget_bytes",
        "max_batch",
        "max_concurrency",
        "max_context_tokens",
        "max_kv_pressure_ppm",
    )
    lines = [f"schema = {EAGLEGATE_CONFIG_SCHEMA}"]
    for key in keys:
        value = values[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = str(value)
        else:
            rendered = _quote(str(value))
        lines.append(f"{key} = {rendered}")
    lines.append(
        "sampler_classes = ["
        + ", ".join(_quote(v.value) for v in lock.sampler_classes)
        + "]"
    )
    lines += ["", f"# lock_root = {lock.lock_root}"]
    return "\n".join(lines) + "\n"


__all__ = [
    "EAGLEGATE_CONFIG_FILENAME",
    "EAGLEGATE_CONFIG_SCHEMA",
    "EAGLEGATE_LOCK_FILENAME",
    "EaglegateLock",
    "lock_to_toml",
]

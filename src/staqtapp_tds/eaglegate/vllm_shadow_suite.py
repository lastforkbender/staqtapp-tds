"""Deterministic non-executing vLLM EAGLE shadow integration fixtures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from typing import Any, Mapping, Sequence

from .adapter_suite import (
    reference_adapter_identity,
    run_reference_adapter_conformance_suite,
)
from .contract import EaglegateSamplerClass
from .exactness_common import (
    EaglegateExactnessError,
    canonical_root,
    require_ascii,
    require_root,
)
from .vllm_shadow import (
    EAGLEGATE_VLLM_METHOD,
    EAGLEGATE_VLLM_RUNTIME_NAME,
    EAGLEGATE_VLLM_SHADOW_AUTHORITY,
    EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
    EAGLEGATE_VLLM_SHADOW_SUITE_ID,
    EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID,
    VllmEagleCapabilitySnapshot,
    VllmShadowAuthorityBoundary,
    VllmShadowDecision,
    VllmShadowFault,
    VllmShadowRequirement,
    evaluate_vllm_shadow,
)


def _root(label: str) -> str:
    return canonical_root("vllm-shadow-fixture", {"label": label})


def reference_vllm_eagle_snapshot() -> VllmEagleCapabilitySnapshot:
    adapter_identity = reference_adapter_identity()
    adapter_report = run_reference_adapter_conformance_suite()
    return VllmEagleCapabilitySnapshot(
        runtime_version="0.0.0-fixture.1",
        runtime_build_root=_root("runtime-build"),
        engine_api_root=_root("engine-api"),
        foundation_identity_root=adapter_identity.foundation_identity_root,
        exactness_qualification_root=(
            adapter_identity.exactness_qualification_root
        ),
        adapter_conformance_root=adapter_report.report_root,
        shadow_adapter_build_root=_root("shadow-adapter"),
        target_model_root=_root("target-model"),
        tokenizer_root=_root("tokenizer"),
        draft_model_root=_root("eagle-draft-model"),
        target_verifier_root=_root("target-verifier"),
        rng_contract_root=_root("target-rng"),
        sampler_order_root=_root("sampler-order"),
        logits_processor_order_root=_root("logits-order"),
        termination_contract_root=_root("termination"),
        kv_allocator_root=_root("kv-allocator"),
        numerical_kernel_root=_root("numerical-kernel"),
        deadline_contract_root=_root("deadline"),
        scheduler_contract_root=_root("scheduler"),
        num_speculative_tokens=4,
        target_tensor_parallel_size=2,
        max_batch=8,
        max_concurrency=16,
        max_context_tokens=131_072,
        max_kv_pressure_ppm=700_000,
        max_workspace_budget_bytes=256 << 20,
        sampler_classes=(
            EaglegateSamplerClass.GREEDY,
            EaglegateSamplerClass.LOSSLESS_SAMPLING,
        ),
    )


def reference_vllm_shadow_requirement(
    snapshot: VllmEagleCapabilitySnapshot | None = None,
) -> VllmShadowRequirement:
    value = snapshot or reference_vllm_eagle_snapshot()
    return VllmShadowRequirement(
        expected_snapshot_root=value.snapshot_root,
        sampler_class=EaglegateSamplerClass.LOSSLESS_SAMPLING,
        candidate_tokens=4,
        target_tensor_parallel_size=2,
    )


@dataclass(frozen=True, slots=True)
class VllmShadowCheck:
    name: str
    passed: bool
    evidence_root: str
    detail: str

    def __post_init__(self) -> None:
        require_ascii("name", self.name)
        if not isinstance(self.passed, bool):
            raise EaglegateExactnessError("passed must be a boolean")
        require_root("evidence_root", self.evidence_root)
        require_ascii("detail", self.detail, allow_spaces=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence_root": self.evidence_root,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class VllmShadowReport:
    checks: tuple[VllmShadowCheck, ...]
    reference_snapshot_root: str
    reference_adapter_identity_root: str

    def __post_init__(self) -> None:
        if not self.checks or any(
            not isinstance(check, VllmShadowCheck) for check in self.checks
        ):
            raise EaglegateExactnessError("checks must contain VllmShadowCheck values")
        require_root("reference_snapshot_root", self.reference_snapshot_root)
        require_root(
            "reference_adapter_identity_root",
            self.reference_adapter_identity_root,
        )

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "shadow_contract_id": EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
            "snapshot_contract_id": EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID,
            "suite_id": EAGLEGATE_VLLM_SHADOW_SUITE_ID,
            "runtime_name": EAGLEGATE_VLLM_RUNTIME_NAME,
            "method": EAGLEGATE_VLLM_METHOD,
            "authority_root": EAGLEGATE_VLLM_SHADOW_AUTHORITY.authority_root,
            "reference_snapshot_root": self.reference_snapshot_root,
            "reference_adapter_identity_root": self.reference_adapter_identity_root,
            "passed": self.passed,
            "check_count": len(self.checks),
            "checks": [check.canonical_dict() for check in self.checks],
            "runtime_invoked": False,
            "model_invoked": False,
            "inference_performed": False,
            "token_acceptance_authority": False,
            "kv_commit_authority": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
        }

    @property
    def report_root(self) -> str:
        return canonical_root("vllm-shadow-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def _decision_check(
    name: str,
    decision: VllmShadowDecision,
    expected: VllmShadowFault,
    detail: str,
) -> VllmShadowCheck:
    passed = (
        decision.fault is expected
        and decision.compatible is (expected is VllmShadowFault.NONE)
        and decision.canonical_dict()["runtime_invoked"] is False
        and decision.canonical_dict()["model_invoked"] is False
        and decision.canonical_dict()["activation_authority"] is False
    )
    return VllmShadowCheck(name, passed, decision.decision_root, detail)


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


def run_reference_vllm_shadow_suite() -> VllmShadowReport:
    snapshot = reference_vllm_eagle_snapshot()
    requirement = reference_vllm_shadow_requirement(snapshot)
    identity = snapshot.adapter_identity()
    checks: list[VllmShadowCheck] = []

    ready = evaluate_vllm_shadow(snapshot, requirement)
    checks.append(
        _decision_check(
            "deterministic_metadata_translation",
            ready,
            VllmShadowFault.NONE,
            "complete pinned metadata translates without runtime invocation",
        )
    )

    mismatch = evaluate_vllm_shadow(
        snapshot,
        replace(requirement, expected_snapshot_root=_root("other-snapshot")),
    )
    checks.append(
        _decision_check(
            "snapshot_identity_mismatch",
            mismatch,
            VllmShadowFault.SNAPSHOT_MISMATCH,
            "stale or foreign capability metadata remains target-only",
        )
    )

    greedy_only = replace(
        snapshot,
        sampler_classes=(EaglegateSamplerClass.GREEDY,),
    )
    sampler = evaluate_vllm_shadow(
        greedy_only,
        replace(
            requirement,
            expected_snapshot_root=greedy_only.snapshot_root,
        ),
    )
    checks.append(
        _decision_check(
            "unsupported_sampler",
            sampler,
            VllmShadowFault.SAMPLER_UNSUPPORTED,
            "unqualified sampling contract remains target-only",
        )
    )

    candidate = evaluate_vllm_shadow(
        snapshot,
        replace(requirement, candidate_tokens=5),
    )
    checks.append(
        _decision_check(
            "candidate_bound",
            candidate,
            VllmShadowFault.CANDIDATE_LIMIT,
            "requested candidate width cannot exceed pinned vLLM metadata",
        )
    )

    parallelism = evaluate_vllm_shadow(
        snapshot,
        replace(requirement, target_tensor_parallel_size=4),
    )
    checks.append(
        _decision_check(
            "target_parallelism_identity",
            parallelism,
            VllmShadowFault.TARGET_PARALLELISM_MISMATCH,
            "target tensor parallelism is part of the immutable fixture",
        )
    )

    invalid_version = False
    try:
        replace(snapshot, runtime_version="latest")
    except EaglegateExactnessError:
        invalid_version = True
    checks.append(
        VllmShadowCheck(
            "exact_runtime_version_required",
            invalid_version,
            snapshot.snapshot_root,
            "latest ranges and unpinned versions are rejected",
        )
    )

    invalid_method = False
    try:
        replace(snapshot, method="eagle3")
    except EaglegateExactnessError:
        invalid_method = True
    checks.append(
        VllmShadowCheck(
            "method_scope_is_eagle_only",
            invalid_method,
            snapshot.speculative_config_root,
            "EAGLE-3 requires a separate contract and qualification",
        )
    )

    invalid_draft_parallelism = False
    try:
        replace(snapshot, draft_tensor_parallel_size=2)
    except EaglegateExactnessError:
        invalid_draft_parallelism = True
    checks.append(
        VllmShadowCheck(
            "draft_parallelism_profile",
            invalid_draft_parallelism,
            snapshot.speculative_config_root,
            "fixture v1 requires one draft tensor-parallel worker",
        )
    )

    unknown_field = False
    try:
        VllmEagleCapabilitySnapshot.from_mapping(
            {**snapshot_to_mapping(snapshot), "execute_model": True}
        )
    except EaglegateExactnessError:
        unknown_field = True
    checks.append(
        VllmShadowCheck(
            "unknown_fields_fail_closed",
            unknown_field,
            snapshot.snapshot_root,
            "unregistered execution fields cannot widen the metadata schema",
        )
    )

    authority_denied = False
    try:
        VllmShadowAuthorityBoundary(inference_allowed=True)
    except EaglegateExactnessError:
        authority_denied = True
    partial = VllmShadowReport(
        tuple(checks),
        snapshot.snapshot_root,
        identity.adapter_identity_root,
    )
    checks.append(
        VllmShadowCheck(
            "authority_and_evidence_boundary",
            authority_denied and _content_free(partial.canonical_dict()),
            EAGLEGATE_VLLM_SHADOW_AUTHORITY.authority_root,
            "fixture cannot import execute sample commit activate or persist content",
        )
    )

    return VllmShadowReport(
        tuple(checks),
        snapshot.snapshot_root,
        identity.adapter_identity_root,
    )


def snapshot_to_mapping(snapshot: VllmEagleCapabilitySnapshot) -> dict[str, Any]:
    value = asdict(snapshot)
    value["sampler_classes"] = [item.value for item in snapshot.sampler_classes]
    return value


def requirement_to_mapping(requirement: VllmShadowRequirement) -> dict[str, Any]:
    value = asdict(requirement)
    value["sampler_class"] = requirement.sampler_class.value
    return value


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-vllm-shadow-lab")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_reference_vllm_shadow_suite()
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    else:
        print("Eaglegate vLLM shadow fixture: " + ("PASS" if report.passed else "FAIL"))
        for check in report.checks:
            state = "PASS" if check.passed else "FAIL"
            print(f"  {state}  {check.name}: {check.detail}")
        print(f"report_root: {report.report_root}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "VllmShadowCheck",
    "VllmShadowReport",
    "reference_vllm_eagle_snapshot",
    "reference_vllm_shadow_requirement",
    "requirement_to_mapping",
    "run_reference_vllm_shadow_suite",
    "snapshot_to_mapping",
]

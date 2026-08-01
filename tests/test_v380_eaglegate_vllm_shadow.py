from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import re

import pytest

from staqtapp_tds.eaglegate.adapter_suite import (
    run_reference_adapter_conformance_suite,
)
from staqtapp_tds.eaglegate.contract import EaglegateSamplerClass
from staqtapp_tds.eaglegate.exactness_common import EaglegateExactnessError
from staqtapp_tds.eaglegate.vllm_shadow import (
    EAGLEGATE_VLLM_DRAFT_TENSOR_PARALLEL_SIZE,
    EAGLEGATE_VLLM_METHOD,
    EAGLEGATE_VLLM_RUNTIME_NAME,
    EAGLEGATE_VLLM_SHADOW_AUTHORITY,
    EAGLEGATE_VLLM_SHADOW_CONTRACT_ID,
    EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID,
    VllmEagleCapabilitySnapshot,
    VllmShadowAuthorityBoundary,
    VllmShadowFault,
    VllmShadowRequirement,
    evaluate_vllm_shadow,
    main as shadow_main,
)
from staqtapp_tds.eaglegate.vllm_shadow_suite import (
    reference_vllm_eagle_snapshot,
    reference_vllm_shadow_requirement,
    requirement_to_mapping,
    run_reference_vllm_shadow_suite,
    snapshot_to_mapping,
)


def test_shadow_authority_is_fixed_metadata_only():
    value = EAGLEGATE_VLLM_SHADOW_AUTHORITY.canonical_dict()
    assert value["metadata_translation_only"] is True
    assert value["runtime_import_allowed"] is False
    assert value["model_loading_allowed"] is False
    assert value["inference_allowed"] is False
    assert value["network_io_allowed"] is False
    assert value["subprocess_allowed"] is False
    assert value["token_acceptance_authority"] is False
    assert value["target_rng_authority"] is False
    assert value["kv_commit_authority"] is False
    assert value["activation_authority"] is False
    assert value["target_only_execution_required"] is True
    with pytest.raises(EaglegateExactnessError, match="cannot be widened"):
        VllmShadowAuthorityBoundary(inference_allowed=True)


def test_snapshot_is_canonical_immutable_and_adapter_bound():
    first = reference_vllm_eagle_snapshot()
    second = reference_vllm_eagle_snapshot()
    assert first.snapshot_root == second.snapshot_root
    assert (
        first.adapter_identity().adapter_identity_root
        == second.adapter_identity().adapter_identity_root
    )
    assert (
        first.adapter_conformance_root
        == run_reference_adapter_conformance_suite().report_root
    )
    assert first.speculative_config_dict() == {
        "method": "eagle",
        "draft_model_root": first.draft_model_root,
        "draft_tensor_parallel_size": 1,
        "num_speculative_tokens": 4,
    }
    changed = replace(first, runtime_build_root=second.engine_api_root)
    assert changed.snapshot_root != first.snapshot_root
    assert (
        changed.adapter_identity().adapter_identity_root
        != first.adapter_identity().adapter_identity_root
    )
    with pytest.raises(FrozenInstanceError):
        first.runtime_version = "1.0.0"  # type: ignore[misc]


@pytest.mark.parametrize(
    "version",
    ["latest", "1", "1.2", "^1.2.3", ">=1.2.3", "1.2.x", " 1.2.3", "1.2.3 "],
)
def test_runtime_version_must_be_one_exact_semver(version: str):
    with pytest.raises(EaglegateExactnessError, match="exact Semantic Version"):
        replace(reference_vllm_eagle_snapshot(), runtime_version=version)


@pytest.mark.parametrize(
    "version", ["0.0.0", "1.2.3", "1.2.3-rc.1", "1.2.3+build.7"]
)
def test_exact_semver_forms_are_accepted(version: str):
    assert (
        replace(reference_vllm_eagle_snapshot(), runtime_version=version).runtime_version
        == version
    )


def test_named_fixture_is_eagle_only_and_draft_tp_one():
    snapshot = reference_vllm_eagle_snapshot()
    assert snapshot.runtime_name == EAGLEGATE_VLLM_RUNTIME_NAME
    assert snapshot.method == EAGLEGATE_VLLM_METHOD
    assert (
        snapshot.draft_tensor_parallel_size
        == EAGLEGATE_VLLM_DRAFT_TENSOR_PARALLEL_SIZE
    )
    assert snapshot.fixture_only is True
    with pytest.raises(EaglegateExactnessError, match="method=eagle"):
        replace(snapshot, method="eagle3")
    with pytest.raises(
        EaglegateExactnessError, match="draft_tensor_parallel_size=1"
    ):
        replace(snapshot, draft_tensor_parallel_size=2)
    with pytest.raises(EaglegateExactnessError, match="runtime_name"):
        replace(snapshot, runtime_name="other")
    with pytest.raises(EaglegateExactnessError, match="fixture_only=true"):
        replace(snapshot, fixture_only=False)


def test_mapping_roundtrip_and_unknown_fields_fail_closed():
    snapshot = reference_vllm_eagle_snapshot()
    restored = VllmEagleCapabilitySnapshot.from_mapping(snapshot_to_mapping(snapshot))
    assert restored == snapshot
    requirement = reference_vllm_shadow_requirement(snapshot)
    restored_requirement = VllmShadowRequirement.from_mapping(
        requirement_to_mapping(requirement)
    )
    assert restored_requirement == requirement
    with pytest.raises(
        EaglegateExactnessError, match="unknown vLLM capability fields"
    ):
        VllmEagleCapabilitySnapshot.from_mapping(
            {**snapshot_to_mapping(snapshot), "execute_model": True}
        )
    with pytest.raises(
        EaglegateExactnessError, match="unknown vLLM requirement fields"
    ):
        VllmShadowRequirement.from_mapping(
            {**requirement_to_mapping(requirement), "activate": True}
        )


def test_missing_mapping_fields_are_structured_failures():
    snapshot = snapshot_to_mapping(reference_vllm_eagle_snapshot())
    del snapshot["runtime_version"]
    with pytest.raises(
        EaglegateExactnessError, match="invalid vLLM capability snapshot fields"
    ):
        VllmEagleCapabilitySnapshot.from_mapping(snapshot)
    requirement = requirement_to_mapping(reference_vllm_shadow_requirement())
    del requirement["candidate_tokens"]
    with pytest.raises(
        EaglegateExactnessError, match="invalid vLLM shadow requirement fields"
    ):
        VllmShadowRequirement.from_mapping(requirement)


def test_compatible_translation_remains_shadow_metadata_only():
    snapshot = reference_vllm_eagle_snapshot()
    decision = evaluate_vllm_shadow(
        snapshot, reference_vllm_shadow_requirement(snapshot)
    )
    payload = decision.to_dict()
    assert decision.compatible is True
    assert decision.fault is VllmShadowFault.NONE
    assert payload["serving_effect"] == "shadow_metadata_only"
    assert payload["runtime_invoked"] is False
    assert payload["model_invoked"] is False
    assert payload["inference_performed"] is False
    assert payload["token_acceptance_authority"] is False
    assert payload["kv_commit_authority"] is False
    assert payload["activation_authority"] is False
    assert payload["real_runtime_qualified"] is False


def test_every_incompatibility_is_target_only():
    snapshot = reference_vllm_eagle_snapshot()
    requirement = reference_vllm_shadow_requirement(snapshot)

    stale_requirement = replace(
        requirement,
        expected_snapshot_root=replace(
            snapshot, runtime_version="0.0.1"
        ).snapshot_root,
    )
    stale = evaluate_vllm_shadow(snapshot, stale_requirement)
    assert stale.fault is VllmShadowFault.SNAPSHOT_MISMATCH
    assert stale.to_dict()["serving_effect"] == "target_only"

    sampler_snapshot = replace(
        snapshot, sampler_classes=(EaglegateSamplerClass.GREEDY,)
    )
    sampler_requirement = replace(
        requirement,
        expected_snapshot_root=sampler_snapshot.snapshot_root,
    )
    sampler = evaluate_vllm_shadow(sampler_snapshot, sampler_requirement)
    assert sampler.fault is VllmShadowFault.SAMPLER_UNSUPPORTED
    assert sampler.to_dict()["serving_effect"] == "target_only"

    candidate = evaluate_vllm_shadow(
        snapshot,
        replace(requirement, candidate_tokens=snapshot.num_speculative_tokens + 1),
    )
    assert candidate.fault is VllmShadowFault.CANDIDATE_LIMIT
    assert candidate.to_dict()["serving_effect"] == "target_only"

    parallel = evaluate_vllm_shadow(
        snapshot,
        replace(
            requirement,
            target_tensor_parallel_size=snapshot.target_tensor_parallel_size + 1,
        ),
    )
    assert parallel.fault is VllmShadowFault.TARGET_PARALLELISM_MISMATCH
    assert parallel.to_dict()["serving_effect"] == "target_only"


def test_source_has_no_runtime_network_or_subprocess_imports():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "staqtapp_tds"
        / "eaglegate"
        / "vllm_shadow.py"
    ).read_text(encoding="utf-8")
    forbidden_import = re.compile(
        r"^\s*(?:from|import)\s+(?:vllm|torch|requests|urllib|socket|subprocess|http\.client)\b",
        re.MULTILINE,
    )
    assert forbidden_import.search(source) is None
    assert "os.system(" not in source
    assert "Popen(" not in source
    assert "run_model(" not in source
    assert "generate(" not in source


def test_reference_suite_is_deterministic_content_free_and_non_qualifying():
    first = run_reference_vllm_shadow_suite()
    second = run_reference_vllm_shadow_suite()
    assert first.passed
    assert len(first.checks) == 10
    assert first.report_root == second.report_root
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    assert payload["runtime_invoked"] is False
    assert payload["model_invoked"] is False
    assert payload["inference_performed"] is False
    assert payload["activation_authority"] is False
    assert payload["real_runtime_qualified"] is False
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


def test_shadow_cli_accepts_complete_metadata_without_execution(
    tmp_path: Path, capsys
):
    snapshot = reference_vllm_eagle_snapshot()
    requirement = reference_vllm_shadow_requirement(snapshot)
    snapshot_path = tmp_path / "snapshot.json"
    requirement_path = tmp_path / "requirement.json"
    snapshot_path.write_text(
        json.dumps(snapshot_to_mapping(snapshot), sort_keys=True), encoding="utf-8"
    )
    requirement_path.write_text(
        json.dumps(requirement_to_mapping(requirement), sort_keys=True),
        encoding="utf-8",
    )
    assert shadow_main(
        [
            "--snapshot",
            str(snapshot_path),
            "--requirement",
            str(requirement_path),
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["compatible"] is True
    assert payload["runtime_invoked"] is False
    assert payload["model_invoked"] is False
    assert payload["activation_authority"] is False


def test_shadow_cli_invalid_metadata_is_structured_target_only(
    tmp_path: Path, capsys
):
    snapshot_path = tmp_path / "snapshot.json"
    requirement_path = tmp_path / "requirement.json"
    snapshot_path.write_text(
        json.dumps({"runtime_version": "latest"}), encoding="utf-8"
    )
    requirement_path.write_text(json.dumps({}), encoding="utf-8")
    assert shadow_main(
        [
            "--snapshot",
            str(snapshot_path),
            "--requirement",
            str(requirement_path),
            "--json",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["fault"] == "invalid_metadata"
    assert payload["serving_effect"] == "target_only"
    assert payload["runtime_invoked"] is False
    assert payload["model_invoked"] is False
    assert payload["activation_authority"] is False


def test_contract_ids_are_explicit_and_stable():
    assert EAGLEGATE_VLLM_SHADOW_CONTRACT_ID == "tds-eaglegate-vllm-shadow-v1"
    assert (
        EAGLEGATE_VLLM_SNAPSHOT_CONTRACT_ID
        == "vllm-eagle-capability-snapshot-v1"
    )

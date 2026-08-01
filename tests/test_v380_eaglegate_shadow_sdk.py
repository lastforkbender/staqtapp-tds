from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from staqtapp_tds.eaglegate.exactness_common import EaglegateExactnessError
from staqtapp_tds.eaglegate.shadow import main
from staqtapp_tds.eaglegate.shadow_contract import (
    EAGLEGATE_SHADOW_AUTHORITY,
    EaglegateShadowAuthorityBoundary,
    ShadowDecisionKind,
    ShadowReason,
)
from staqtapp_tds.eaglegate.shadow_vllm import (
    compile_vllm_eagle_shadow,
    parse_vllm_eagle_metadata,
    vllm_eagle_metadata_schema,
)


ROOT = Path(__file__).resolve().parents[1]


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("ascii")).hexdigest()


def _metadata_dict(**overrides):
    value = {
        "runtime_version": "0.22.0",
        "method": "eagle",
        "foundation_identity_root": _root("foundation"),
        "target_model_root": _root("target-model"),
        "tokenizer_root": _root("tokenizer"),
        "draft_model_root": _root("draft-model"),
        "adapter_build_root": _root("adapter-build"),
        "target_verifier_root": _root("target-verifier"),
        "rng_contract_root": _root("rng"),
        "sampler_order_root": _root("sampler"),
        "logits_processor_order_root": _root("logits"),
        "termination_contract_root": _root("termination"),
        "kv_allocator_root": _root("kv"),
        "numerical_kernel_root": _root("kernel"),
        "deadline_contract_root": _root("deadline"),
        "capability_source_root": _root("source"),
        "metadata_attestation_root": _root("attestation"),
        "num_speculative_tokens": 3,
        "draft_tensor_parallel_size": 1,
        "target_tensor_parallel_size": 4,
        "max_model_len": 32768,
        "parallel_drafting": False,
        "rejection_sample_method": "strict",
    }
    value.update(overrides)
    return value


def _compile(metadata):
    return compile_vllm_eagle_shadow(
        metadata,
        exactness_qualification_root=_root("exactness"),
        adapter_conformance_report_root=_root("adapter-report"),
    )


def test_shadow_authority_is_non_widenable():
    assert EAGLEGATE_SHADOW_AUTHORITY.may_import_runtime is False
    assert EAGLEGATE_SHADOW_AUTHORITY.may_load_model is False
    assert EAGLEGATE_SHADOW_AUTHORITY.may_generate_tokens is False
    assert EAGLEGATE_SHADOW_AUTHORITY.may_activate is False
    assert EAGLEGATE_SHADOW_AUTHORITY.target_only_default is True
    with pytest.raises(EaglegateExactnessError, match="cannot be widened"):
        EaglegateShadowAuthorityBoundary(may_load_model=True)


def test_strict_metadata_parses_and_roots_deterministically():
    first = parse_vllm_eagle_metadata(_metadata_dict())
    second = parse_vllm_eagle_metadata(_metadata_dict())
    assert first.metadata_root == second.metadata_root
    assert first.adapter_identity(
        exactness_qualification_root=_root("exactness")
    ).adapter_identity_root == second.adapter_identity(
        exactness_qualification_root=_root("exactness")
    ).adapter_identity_root


def test_eagle3_metadata_is_structurally_supported_for_observation():
    metadata = parse_vllm_eagle_metadata(_metadata_dict(method="eagle3"))
    preview, report = _compile(metadata)
    assert preview.method == "eagle3"
    assert report.decision is ShadowDecisionKind.OBSERVE
    assert report.reason is ShadowReason.METADATA_ONLY_SHADOW
    assert report.to_dict()["real_runtime_qualified"] is False


def test_synthetic_acceptance_is_target_only():
    metadata = parse_vllm_eagle_metadata(
        _metadata_dict(rejection_sample_method="synthetic")
    )
    _, report = _compile(metadata)
    assert report.decision is ShadowDecisionKind.TARGET_ONLY
    assert report.reason is ShadowReason.SYNTHETIC_ACCEPTANCE_FORBIDDEN


def test_parallel_drafting_is_target_only_until_separately_qualified():
    metadata = parse_vllm_eagle_metadata(_metadata_dict(parallel_drafting=True))
    _, report = _compile(metadata)
    assert report.decision is ShadowDecisionKind.TARGET_ONLY
    assert report.reason is ShadowReason.PARALLEL_DRAFTING_UNQUALIFIED


def test_unknown_or_missing_metadata_fields_fail_closed():
    with pytest.raises(EaglegateExactnessError, match="unknown"):
        parse_vllm_eagle_metadata(_metadata_dict(unexpected="value"))
    missing = _metadata_dict()
    missing.pop("rng_contract_root")
    with pytest.raises(EaglegateExactnessError, match="missing"):
        parse_vllm_eagle_metadata(missing)


def test_only_eagle_family_and_vllm_runtime_are_accepted():
    with pytest.raises(EaglegateExactnessError, match="eagle or eagle3"):
        parse_vllm_eagle_metadata(_metadata_dict(method="mtp"))
    with pytest.raises(EaglegateExactnessError, match="only vllm"):
        parse_vllm_eagle_metadata(_metadata_dict(runtime_name="other"))


def test_raw_model_paths_and_identifiers_are_not_schema_fields():
    with pytest.raises(EaglegateExactnessError, match="unknown"):
        parse_vllm_eagle_metadata(_metadata_dict(model="org/model"))
    schema = vllm_eagle_metadata_schema()
    assert schema["model_identifiers"] == "sha256 roots only"
    assert "model" not in schema["required_fields"]


def test_version_and_numeric_bounds_are_canonical():
    with pytest.raises(EaglegateExactnessError, match="normalized package version"):
        parse_vllm_eagle_metadata(_metadata_dict(runtime_version="latest"))
    with pytest.raises(EaglegateExactnessError):
        parse_vllm_eagle_metadata(_metadata_dict(num_speculative_tokens=0))
    with pytest.raises(EaglegateExactnessError):
        parse_vllm_eagle_metadata(_metadata_dict(max_model_len=True))


def test_metadata_changes_rebind_identity_and_report():
    first = parse_vllm_eagle_metadata(_metadata_dict())
    second = parse_vllm_eagle_metadata(
        _metadata_dict(rng_contract_root=_root("rng-v2"))
    )
    _, first_report = _compile(first)
    _, second_report = _compile(second)
    assert first.metadata_root != second.metadata_root
    assert first_report.adapter_identity_root != second_report.adapter_identity_root
    assert first_report.report_root != second_report.report_root


def test_qualification_roots_rebind_report_without_qualifying_runtime():
    metadata = parse_vllm_eagle_metadata(_metadata_dict())
    _, first = compile_vllm_eagle_shadow(
        metadata,
        exactness_qualification_root=_root("exactness-a"),
        adapter_conformance_report_root=_root("adapter-a"),
    )
    _, second = compile_vllm_eagle_shadow(
        metadata,
        exactness_qualification_root=_root("exactness-b"),
        adapter_conformance_report_root=_root("adapter-b"),
    )
    assert first.report_root != second.report_root
    assert first.to_dict()["real_runtime_qualified"] is False
    assert second.to_dict()["production_execution_authority"] is False


def test_preview_never_contains_or_emits_an_executable_command():
    preview, report = _compile(parse_vllm_eagle_metadata(_metadata_dict()))
    payload = {**report.to_dict(), "preview": preview.canonical_dict()}
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["executable_command_emitted"] is False
    assert preview.executable_command_emitted is False
    assert "vllm serve" not in encoded
    assert "subprocess" not in encoded


def test_fixture_source_never_imports_or_invokes_vllm():
    package = ROOT / "src" / "staqtapp_tds" / "eaglegate"
    sources = "\n".join(
        (package / name).read_text(encoding="utf-8")
        for name in ("shadow_contract.py", "shadow_vllm.py", "shadow.py")
    )
    forbidden = (
        "import vllm",
        "from vllm",
        "subprocess",
        "os.system",
        "Popen",
        "vllm serve",
    )
    assert all(term not in sources for term in forbidden)


def test_schema_cli_is_content_free_and_non_activating(capsys):
    assert main(["schema", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runtime_imported"] is False
    assert payload["executable_command_emitted"] is False
    assert payload["activation_authority"] is False
    assert payload["real_runtime_qualified"] is False
    assert payload["authority"]["may_load_model"] is False


def test_inspect_cli_is_deterministic(tmp_path, capsys):
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(_metadata_dict(), sort_keys=True), encoding="utf-8"
    )
    args = [
        "inspect",
        "--metadata",
        str(metadata_path),
        "--exactness-root",
        _root("exactness"),
        "--adapter-root",
        _root("adapter-report"),
        "--json",
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert payload["decision"] == "observe"
    assert payload["runtime_imported"] is False
    assert payload["model_loaded"] is False
    assert payload["tokens_generated"] is False
    assert payload["activation_authority"] is False
    assert payload["real_runtime_qualified"] is False


def test_report_is_content_free():
    preview, report = _compile(parse_vllm_eagle_metadata(_metadata_dict()))
    payload = {**report.to_dict(), "preview": preview.canonical_dict()}
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
        "executable_command",
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

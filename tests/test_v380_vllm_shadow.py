from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import pytest

from staqtapp_tds.eaglegate import vllm_shadow
from staqtapp_tds.eaglegate.vllm_shadow import (
    DRAFT_MODEL,
    DRAFT_REVISION,
    PINNED_VLLM_SHADOW_MATRIX,
    QUALIFIED_DRAFT_TENSOR_PARALLEL_SIZE,
    QUALIFIED_KV_BLOCK_SIZE,
    QUALIFIED_KV_CACHE_DTYPE,
    QUALIFIED_PREFIX_CACHING,
    TARGET_MODEL,
    TARGET_REVISION,
    VLLM_BUILD_COMMIT,
    VLLM_VERSION,
    BoundedShadowObservationQueue,
    VLLMShadowError,
    VLLMShadowQualificationReport,
    VLLMShadowSettings,
    persist_vllm_shadow_report,
    provision_vllm_shadow_serving_epoch,
    run_vllm_shadow_qualification,
)
from staqtapp_tds.generation.generation_store import AtomicGenerationStore, bytes_root


class _FakeSamplingParams:
    created: ClassVar[list[dict[str, object]]] = []

    def __init__(self, **kwargs: object) -> None:
        self.values = dict(kwargs)
        self.created.append(self.values)


class _FakeTokenizer:
    @staticmethod
    def encode(prompt: str) -> list[int]:
        return list(prompt.encode("utf-8"))


class _FakeLLM:
    instances: ClassVar[list[_FakeLLM]] = []
    mismatch_plan: int | None = None

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = dict(kwargs)
        self.generate_calls: list[tuple[list[object], dict[str, object]]] = []
        self.shutdown_called = False
        self.instances.append(self)

    def get_tokenizer(self) -> _FakeTokenizer:
        return _FakeTokenizer()

    def generate(
        self,
        *,
        prompts: list[object],
        sampling_params: _FakeSamplingParams,
        use_tqdm: bool,
    ) -> list[object]:
        assert use_tqdm is False
        assert len(prompts) == 1
        self.generate_calls.append((prompts, sampling_params.values))
        prompt = prompts[0]
        if isinstance(prompt, str):
            material = list(prompt.encode("utf-8"))
        else:
            material = list(prompt["prompt_token_ids"])  # type: ignore[index]
        seed = int(sampling_params.values["seed"])
        count = int(sampling_params.values["max_tokens"])
        base = (sum(material) + seed) % 101
        tokens = [(base + index * 7) % 257 for index in range(count)]
        speculative = self.kwargs.get("speculative_config")
        if (
            isinstance(speculative, dict)
            and speculative["num_speculative_tokens"] == self.mismatch_plan
            and sampling_params.values["temperature"] == 0.0
        ):
            tokens[0] += 1
        candidate = SimpleNamespace(token_ids=tokens, finish_reason="length")
        return [SimpleNamespace(outputs=[candidate])]

    def shutdown(self) -> None:
        self.shutdown_called = True


class _FakeCuda:
    empty_cache_calls = 0

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def get_device_name(index: int) -> str:
        assert index == 0
        return "NVIDIA H100 80GB HBM3"

    @staticmethod
    def get_device_capability(index: int) -> tuple[int, int]:
        assert index == 0
        return (9, 0)

    @staticmethod
    def is_bf16_supported() -> bool:
        return True

    @classmethod
    def empty_cache(cls) -> None:
        cls.empty_cache_calls += 1


def _install_fake_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeLLM.instances = []
    _FakeLLM.mismatch_plan = None
    _FakeSamplingParams.created = []
    _FakeCuda.empty_cache_calls = 0
    fake_vllm = ModuleType("vllm")
    fake_vllm.__version__ = VLLM_VERSION
    fake_vllm.__commit__ = VLLM_BUILD_COMMIT
    fake_vllm.LLM = _FakeLLM
    fake_vllm.SamplingParams = _FakeSamplingParams
    fake_torch = ModuleType("torch")
    fake_torch.cuda = _FakeCuda
    monkeypatch.setitem(sys.modules, "vllm", fake_vllm)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        vllm_shadow.metadata,
        "version",
        lambda name: VLLM_VERSION,
    )


def _settings(*, capacity: int = 64) -> VLLMShadowSettings:
    return VLLMShadowSettings(
        request_seed=271_828,
        max_new_tokens=3,
        sampled_cases=4,
        sampled_distribution_tolerance_ppm=0,
        observation_capacity=capacity,
    )


@pytest.fixture
def serving(tmp_path: Path) -> tuple[AtomicGenerationStore, str, str]:
    store = AtomicGenerationStore(tmp_path / "authority")
    publication = provision_vllm_shadow_serving_epoch(store)
    return (
        store,
        vllm_shadow.VLLM_SHADOW_SERVING_NAMESPACE,
        publication.head.generation_root,
    )


def _run(
    serving: tuple[AtomicGenerationStore, str, str],
    prompts: tuple[str, ...],
    **kwargs: object,
) -> VLLMShadowQualificationReport:
    store, namespace, generation_root = serving
    return run_vllm_shadow_qualification(
        prompts,
        store=store,
        serving_namespace=namespace,
        serving_generation_root=generation_root,
        **kwargs,
    )


def test_real_dynamic_vllm_construction_uses_the_exact_pinned_matrix(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    queue = BoundedShadowObservationQueue(1)
    report = _run(
        serving,
        ("qualification prompt",),
        settings=_settings(capacity=1),
        observation_queue=queue,
    )

    assert report.passed is True
    assert report.fallback_reason == ""
    assert len(report.gates) == 12
    assert report.cleanup_attempts == report.cleanup_successes == 4
    assert report.observations_published == 12
    assert report.observations_dropped == 11
    assert len(_FakeLLM.instances) == 4

    target, *shadows = _FakeLLM.instances
    assert target.kwargs["speculative_config"] is None
    for engine in _FakeLLM.instances:
        assert engine.kwargs["model"] == TARGET_MODEL
        assert engine.kwargs["revision"] == TARGET_REVISION
        assert engine.kwargs["tokenizer"] == TARGET_MODEL
        assert engine.kwargs["tokenizer_revision"] == TARGET_REVISION
        assert engine.kwargs["dtype"] == "bfloat16"
        assert engine.kwargs["kv_cache_dtype"] == QUALIFIED_KV_CACHE_DTYPE
        assert engine.kwargs["block_size"] == QUALIFIED_KV_BLOCK_SIZE
        assert engine.kwargs["enable_prefix_caching"] is QUALIFIED_PREFIX_CACHING
        assert engine.kwargs["tensor_parallel_size"] == 1
        assert engine.kwargs["max_num_seqs"] == 1
        assert engine.shutdown_called is True
        assert all(len(prompts) == 1 for prompts, _ in engine.generate_calls)
    for plan, engine in zip((1, 2, 3), shadows):
        config = engine.kwargs["speculative_config"]
        assert config == {
            "method": "eagle",
            "model": DRAFT_MODEL,
            "revision": DRAFT_REVISION,
            "code_revision": DRAFT_REVISION,
            "num_speculative_tokens": plan,
            "rejection_sample_method": "standard",
            "draft_sample_method": "greedy",
            "draft_tensor_parallel_size": QUALIFIED_DRAFT_TENSOR_PARALLEL_SIZE,
        }
    assert all(params["seed"] is not None for params in _FakeSamplingParams.created)
    assert _FakeCuda.empty_cache_calls == 4


def test_report_is_content_free_and_labels_public_kv_limits_truthfully(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    report = _run(
        serving,
        ("this prompt must never persist",),
        settings=_settings(),
    )
    value = report.to_dict()
    encoded = report.canonical_bytes()
    assert b"this prompt must never persist" not in encoded
    assert value["contains_prompt_content"] is False
    assert value["contains_token_sequences"] is False
    assert value["contains_logits"] is False
    assert value["contains_kv_tensors"] is False
    assert value["direct_kv_tensor_equivalence_tested"] is False
    assert value["continuation_observation_scope"] == "public-runtime-output-only"
    assert value["in_flight_cancellation_qualified"] is False
    assert value["production_serving_qualified"] is False
    assert value["canary_authority"] is False
    assert value["activation_authority"] is False
    assert json.loads(encoded)["passed"] is True


def test_uncertainty_and_gate_mismatch_fail_to_target_only(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    _FakeLLM.mismatch_plan = 2
    report = _run(
        serving,
        ("mismatch prompt",),
        settings=_settings(),
    )
    assert report.passed is False
    assert report.to_dict()["fallback_required"] is True
    assert report.fallback_reason == "qualification-gate-failed"
    assert len(_FakeLLM.instances) == 3
    assert all(instance.shutdown_called for instance in _FakeLLM.instances)
    assert any(not gate.passed for gate in report.gates if gate.plan_tokens == 2)


def test_runtime_attestation_mismatch_constructs_no_engine(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    monkeypatch.setattr(vllm_shadow.metadata, "version", lambda name: "0.25.1")
    sys.modules["vllm"].__version__ = "0.25.1"
    report = _run(
        serving,
        ("never dispatched",),
        settings=_settings(),
    )
    assert report.passed is False
    assert report.attestation.failure_reason == "vllm_version_mismatch"
    assert report.fallback_reason == "runtime-attestation-failed"
    assert _FakeLLM.instances == []


def test_matrix_rejects_eagle3_or_any_widened_plan() -> None:
    with pytest.raises(VLLMShadowError):
        replace(PINNED_VLLM_SHADOW_MATRIX, speculative_method="eagle3")
    with pytest.raises(VLLMShadowError):
        replace(PINNED_VLLM_SHADOW_MATRIX, speculative_plans=(1, 2, 3, 4))
    assert PINNED_VLLM_SHADOW_MATRIX.vllm_build_commit == VLLM_BUILD_COMMIT


def test_content_free_report_uses_only_atomic_generation_authority(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    report = _run(
        serving,
        ("not stored",),
        settings=_settings(),
    )
    store, _, _ = serving
    published = persist_vllm_shadow_report(store, report)
    assert published.head.publication_sequence == 1
    assert not list(store.root.glob("**/EAGLEGATE_CURRENT"))
    with store.pin("eaglegate:vllm-shadow-qualification") as lease:
        assert lease.read_payload("eaglegate.vllm-shadow.report") == (
            report.canonical_bytes()
        )
        assert all(not payload.authoritative for payload in lease.manifest.payloads)
        assert dict(lease.manifest.metadata) == {
            "consumer": "tds-eaglegate-vllm-shadow-v1",
            "scope": "qualification-only",
        }
        qualifications = {
            item.name: item.evidence_root for item in lease.manifest.qualifications
        }
        assert qualifications["eaglegate.vllm-shadow.binding"] == (
            report.serving_binding.binding_root
        )
        assert qualifications["eaglegate.vllm-shadow.serving-generation"] == (
            report.serving_generation_root
        )
        assert qualifications["eaglegate.vllm-shadow.storage-generation"] == (
            report.serving_binding.storage_generation_root
        )
        assert qualifications["eaglegate.vllm-shadow.policy-plans"] == (
            report.serving_binding.eaglegate_policy_root
        )
        assert qualifications["eaglegate.vllm-shadow.exactness-qualification"] == (
            report.serving_binding.exactness_qualification_root
        )
        assert qualifications["eaglegate.vllm-shadow.receipt-chain"] == (
            report.serving_binding.receipt_chain_root
        )


def test_report_binds_exact_matrix_settings_workload_and_gate_catalog(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    settings = _settings()
    report = _run(serving, ("first", "second"), settings=settings)
    value = report.to_dict()

    assert value["matrix"] == PINNED_VLLM_SHADOW_MATRIX.canonical_dict()
    assert value["matrix_root"] == PINNED_VLLM_SHADOW_MATRIX.matrix_root
    assert value["settings"] == settings.canonical_dict()
    assert value["settings_root"] == settings.settings_root
    assert value["workload"]["prompt_count"] == 2
    assert value["workload_root"] == report.workload.workload_root
    assert value["serving_binding"] == report.serving_binding.canonical_dict()
    assert value["serving_binding_root"] == report.serving_binding.binding_root
    assert [(gate.plan_tokens, gate.name) for gate in report.gates] == [
        (plan, name)
        for plan in (1, 2, 3)
        for name in (
            "greedy-equality",
            "sampled-distribution",
            "continuation-semantics",
            "cancellation-shutdown-cleanup",
        )
    ]
    assert all(gate.executed for gate in report.gates)


def test_gate_catalog_and_numeric_forgery_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    report = _run(serving, ("forgery",), settings=_settings())

    with pytest.raises(VLLMShadowError, match="mismatch count and metric"):
        replace(report.gates[0], mismatches=1, metric_ppm=0, passed=False)

    inconsistent = replace(
        report.gates[0],
        mismatches=1,
        metric_ppm=1_000_000,
        passed=True,
    )
    with pytest.raises(VLLMShadowError, match="pass result"):
        replace(report, gates=(inconsistent, *report.gates[1:]))

    with pytest.raises(VLLMShadowError, match="exact 1/2/3 gate catalog"):
        replace(report, gates=tuple(reversed(report.gates)))

    repeated_evidence = tuple(
        replace(gate, evidence_root=report.gates[0].evidence_root)
        for gate in report.gates
    )
    with pytest.raises(VLLMShadowError, match="evidence roots must be unique"):
        replace(report, gates=repeated_evidence)

    with pytest.raises(ValueError):
        VLLMShadowSettings(sampled_distribution_tolerance_ppm=250_001)


def test_raw_gpu_name_and_prompt_content_never_persist(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    raw_gpu_secret = "NVIDIA H100 80GB HBM3 tenant-secret-value"
    raw_prompt_secret = "prompt-secret-value"
    monkeypatch.setattr(
        _FakeCuda,
        "get_device_name",
        staticmethod(lambda index: raw_gpu_secret),
    )

    report = _run(serving, (raw_prompt_secret,), settings=_settings())
    encoded = report.canonical_bytes()
    assert raw_gpu_secret.encode("utf-8") not in encoded
    assert raw_prompt_secret.encode("utf-8") not in encoded
    assert b'"gpu_name"' not in encoded
    assert report.attestation.gpu_family == "NVIDIA H100"
    assert report.attestation.gpu_identity_root.startswith("sha256:")
    with pytest.raises(VLLMShadowError, match="fixed status value"):
        replace(report.attestation, installed_version="tenant-secret-value")
    with pytest.raises(VLLMShadowError, match="fixed status value"):
        replace(report.attestation, installed_commit="tenant-secret-value")


def test_persistence_reopens_pins_and_compares_the_exact_serving_generation(
    monkeypatch: pytest.MonkeyPatch,
    serving: tuple[AtomicGenerationStore, str, str],
) -> None:
    _install_fake_runtime(monkeypatch)
    report = _run(serving, ("binding",), settings=_settings())
    store, _, _ = serving

    forged_binding = replace(
        report.serving_binding,
        receipt_chain_root=bytes_root(b"forged-receipt-chain"),
    )
    forged_report = replace(report, serving_binding=forged_binding)
    with pytest.raises(VLLMShadowError, match="re-opened ServingEpoch"):
        persist_vllm_shadow_report(store, forged_report)

    original_publish = store.publish

    def checked_publish(candidate, *, expected_head_root):
        assert store.pin_count(report.serving_generation_root) == 1
        assert store.pin_count(report.serving_binding.storage_generation_root) == 1
        return original_publish(candidate, expected_head_root=expected_head_root)

    monkeypatch.setattr(store, "publish", checked_publish)
    persist_vllm_shadow_report(store, report)

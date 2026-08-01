from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from staqtapp_tds.eaglegate import (
    EaglegateAdmissionPolicy,
    EaglegateConfiguration,
    EaglegateContractError,
    EaglegateFault,
    EaglegateIdentity,
    EaglegateMode,
    EaglegatePlan,
    EaglegateSamplerClass,
    EaglegateSpeculationEpoch,
    profile_configuration,
    run_reference_exactness_suite,
)
from staqtapp_tds.eaglegate.generation import (
    EAGLEGATE_SERVING_BINDING_PAYLOAD,
    build_eaglegate_serving_candidate,
    open_eaglegate_serving_generation,
    publish_eaglegate_serving_candidate,
    qualify_eaglegate_core_epoch,
)
from staqtapp_tds.generation import (
    AtomicGenerationStore,
    GenerationContractError,
    GenerationPublicationConflict,
    GenerationStoreError,
    bytes_root,
)


def _root(label: str) -> str:
    return bytes_root(label.encode("ascii"))


def _storage(store: AtomicGenerationStore, namespace: str, source: bytes):
    candidate = store.build_candidate(
        namespace=namespace,
        payloads={"dataset.source": source},
        authoritative_payload="dataset.source",
        metadata={"consumer": "test-storage-generation"},
    )
    return store.publish(candidate, expected_head_root=None)


def _epoch(
    *,
    generation: int = 1,
    mode: EaglegateMode = EaglegateMode.SHADOW,
    previous: str = "",
    tokens: int = 2,
) -> EaglegateSpeculationEpoch:
    identity = EaglegateIdentity(
        target_model_root=_root("target-model"),
        tokenizer_root=_root("tokenizer"),
        proposer_root=_root("eagle-proposer"),
        target_runtime_root=_root("target-runtime"),
        sampler_contract_root=_root("sampler"),
        logits_processor_root=_root("logits-order"),
        kv_contract_root=_root("kv-contract"),
        kernel_capability_root=_root("kernel-capability"),
        numerical_mode="bf16-sm90",
        tenant_scope="qualification-only",
    )
    plan = EaglegatePlan(
        plan_id=f"eagle-linear-{tokens}",
        candidate_tokens=tokens,
        max_tree_nodes=tokens,
        workspace_budget_bytes=64 << 20,
        max_batch=1,
        max_concurrency=1,
        max_context_tokens=8_192,
        max_kv_pressure_ppm=500_000,
        sampler_classes=(
            EaglegateSamplerClass.GREEDY,
            EaglegateSamplerClass.LOSSLESS_SAMPLING,
        ),
    )
    return EaglegateSpeculationEpoch(
        generation=generation,
        identity=identity,
        plans=(plan,),
        policy=EaglegateAdmissionPolicy(
            policy_id=f"shadow-policy-{generation}",
            mode=mode,
            plan_order=(plan.plan_id,),
            canary_basis_points=100 if mode is EaglegateMode.CANARY else 0,
        ),
        previous_epoch_root=previous,
    )


def _serving_candidate(
    store: AtomicGenerationStore,
    storage_root: str,
    *,
    epoch: EaglegateSpeculationEpoch,
    parent: str | None = None,
):
    qualified, summary, exactness, adapter = qualify_eaglegate_core_epoch(epoch)
    return qualified, build_eaglegate_serving_candidate(
        store,
        namespace="serving:eaglegate",
        storage_namespace="dataset:primary",
        storage_generation_root=storage_root,
        epoch=qualified,
        qualification=summary,
        exactness_report=exactness,
        adapter_report=adapter,
        parent_authority_generation_root=parent,
    )


def test_serving_epoch_publishes_only_through_generation_authority(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    source = b"private authoritative dataset bytes"
    storage = _storage(store, "dataset:primary", source)
    epoch, candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(),
    )
    publication = publish_eaglegate_serving_candidate(
        store, candidate, expected_head_root=None
    )

    with open_eaglegate_serving_generation(store, "serving:eaglegate") as lease:
        assert lease.generation_root == publication.head.generation_root
        assert lease.binding.eaglegate_epoch_root == epoch.epoch_root
        assert lease.binding.storage_generation_root == storage.head.generation_root
        assert lease.binding.serving_mode == "shadow"
        assert lease.loaded.qualification_bridge.real_runtime_qualified is False
        assert lease.loaded.receipts[-1].state.value == "shadow"
        assert store.pin_count(storage.head.generation_root) == 1

    persisted = b"".join(candidate.payload_map().values())
    assert source not in persisted
    assert b'"real_runtime_qualified":false' in persisted
    current_files = sorted((tmp_path / "authority").rglob("CURRENT"))
    assert len(current_files) == 2  # one storage CURRENT and one generic serving CURRENT
    assert not any("eaglegate" in path.name.lower() for path in current_files)


def test_head_root_cas_lineage_pin_rollback_and_retirement(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    first_storage = _storage(store, "dataset:primary", b"generation-one")
    first_epoch, first_candidate = _serving_candidate(
        store, first_storage.head.generation_root, epoch=_epoch()
    )
    first = publish_eaglegate_serving_candidate(
        store, first_candidate, expected_head_root=None
    )
    pinned_first = open_eaglegate_serving_generation(store, "serving:eaglegate")

    second_epoch, second_candidate = _serving_candidate(
        store,
        first_storage.head.generation_root,
        epoch=_epoch(generation=2, previous=first_epoch.epoch_root, tokens=3),
        parent=first.head.generation_root,
    )
    second = publish_eaglegate_serving_candidate(
        store,
        second_candidate,
        expected_head_root=first.head.head_root,
    )
    assert pinned_first.binding.eaglegate_epoch_root == first_epoch.epoch_root

    _, stale = _serving_candidate(
        store,
        first_storage.head.generation_root,
        epoch=_epoch(generation=3, previous=first_epoch.epoch_root, tokens=1),
        parent=first.head.generation_root,
    )
    with pytest.raises(GenerationPublicationConflict):
        publish_eaglegate_serving_candidate(
            store, stale, expected_head_root=first.head.head_root
        )

    rollback = store.rollback(
        "serving:eaglegate",
        first.head.generation_root,
        expected_head_root=second.head.head_root,
    )
    assert rollback.head.generation_root == first.head.generation_root
    pinned_first.close()
    store.retire("serving:eaglegate", second.head.generation_root)
    with pytest.raises(GenerationStoreError):
        open_eaglegate_serving_generation(
            store, "serving:eaglegate", second.head.generation_root
        )


def test_serving_lease_prevents_source_retirement_and_fails_after_retirement(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    old_storage = _storage(store, "dataset:primary", b"old")
    _, candidate = _serving_candidate(
        store, old_storage.head.generation_root, epoch=_epoch()
    )
    publish_eaglegate_serving_candidate(store, candidate, expected_head_root=None)
    serving = open_eaglegate_serving_generation(store, "serving:eaglegate")

    replacement = store.build_candidate(
        namespace="dataset:primary",
        payloads={"dataset.source": b"new"},
        authoritative_payload="dataset.source",
        parent_generation_root=old_storage.head.generation_root,
    )
    store.publish(replacement, expected_head_root=old_storage.head.head_root)
    with pytest.raises(GenerationStoreError):
        store.retire("dataset:primary", old_storage.head.generation_root)
    serving.close()
    store.retire("dataset:primary", old_storage.head.generation_root)
    with pytest.raises(GenerationStoreError):
        open_eaglegate_serving_generation(store, "serving:eaglegate")


def test_canary_active_and_self_asserted_reports_are_rejected(tmp_path: Path) -> None:
    for mode in (EaglegateMode.CANARY, EaglegateMode.ACTIVE):
        with pytest.raises(EaglegateContractError) as configured:
            EaglegateConfiguration(
                profile="forbidden",
                generation=1,
                policy_id="forbidden",
                mode=mode,
                canary_basis_points=1,
                plans=profile_configuration().plans,
            )
        assert configured.value.fault is EaglegateFault.AUTHORITY_REJECTED

    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    qualified, summary, exactness, adapter = qualify_eaglegate_core_epoch(_epoch())
    qualified = replace(
        qualified,
        policy=replace(
            qualified.policy,
            mode=EaglegateMode.CANARY,
            canary_basis_points=100,
        ),
    )
    with pytest.raises(EaglegateContractError) as publishing:
        build_eaglegate_serving_candidate(
            store,
            namespace="serving:eaglegate",
            storage_namespace="dataset:primary",
            storage_generation_root=storage.head.generation_root,
            epoch=qualified,
            qualification=summary,
            exactness_report=exactness,
            adapter_report=adapter,
        )
    assert publishing.value.fault is EaglegateFault.AUTHORITY_REJECTED

    altered = replace(
        run_reference_exactness_suite(),
        distribution_proof_root=_root("self-asserted-proof"),
    )
    shadow = _epoch()
    qualified, summary, _, adapter = qualify_eaglegate_core_epoch(shadow)
    with pytest.raises(EaglegateContractError) as report:
        build_eaglegate_serving_candidate(
            store,
            namespace="serving:eaglegate",
            storage_namespace="dataset:primary",
            storage_generation_root=storage.head.generation_root,
            epoch=qualified,
            qualification=summary,
            exactness_report=altered,
            adapter_report=adapter,
        )
    assert report.value.fault is EaglegateFault.QUALIFICATION_REQUIRED


def test_mixed_binding_is_rejected_before_serving(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, first = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch(tokens=2)
    )
    _, other = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch(tokens=3)
    )
    payloads = first.payload_map()
    payloads[EAGLEGATE_SERVING_BINDING_PAYLOAD] = other.payload_map()[
        EAGLEGATE_SERVING_BINDING_PAYLOAD
    ]
    mixed = store.build_candidate(
        namespace="serving:mixed",
        payloads=payloads,
        media_types={name: "application/json" for name in payloads},
        qualifications={
            item.name: item.evidence_root for item in first.manifest.qualifications
        },
        metadata={
            "consumer": "tds-eaglegate-serving-generation-v1",
            "serving-effect": "shadow-only",
        },
    )
    store.publish(mixed, expected_head_root=None)
    with pytest.raises(GenerationContractError):
        open_eaglegate_serving_generation(store, "serving:mixed")

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from staqtapp_tds.eaglegate import (
    EaglegateAdmissionPolicy,
    EaglegateConfiguration,
    EaglegateContractError,
    EaglegateEpochReceipt,
    EaglegateEpochState,
    EaglegateFault,
    EaglegateIdentity,
    EaglegateMode,
    EaglegatePlan,
    EaglegateSamplerClass,
    EaglegateSpeculationEpoch,
    profile_configuration,
    run_reference_exactness_suite,
)
from staqtapp_tds.eaglegate.contract import _canonical_root as _eaglegate_root
from staqtapp_tds.eaglegate.generation import (
    EAGLEGATE_EPOCH_PAYLOAD,
    EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD,
    EAGLEGATE_QUALIFICATION_PAYLOAD,
    EAGLEGATE_RECEIPTS_PAYLOAD,
    EAGLEGATE_SERVING_BINDING_PAYLOAD,
    EaglegateQualificationBridge,
    EaglegateServingEpochBinding,
    build_eaglegate_serving_candidate,
    load_eaglegate_serving_generation,
    open_eaglegate_serving_generation,
    publish_eaglegate_serving_candidate,
    qualify_eaglegate_core_epoch,
)
from staqtapp_tds.generation import (
    AtomicGenerationStore,
    GenerationContractError,
    GenerationFault,
    GenerationPublicationConflict,
    GenerationStoreError,
    bytes_root,
    canonical_json_bytes,
    canonical_root,
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


def _two_plan_epoch() -> EaglegateSpeculationEpoch:
    value = _epoch()
    second = replace(
        value.plans[0],
        plan_id="eagle-linear-3",
        candidate_tokens=3,
        max_tree_nodes=3,
    )
    return replace(
        value,
        plans=(*value.plans, second),
        policy=replace(
            value.policy,
            plan_order=(value.plans[0].plan_id, second.plan_id),
        ),
    )


def _rebound_candidate(
    store: AtomicGenerationStore,
    candidate,
    *,
    epoch_value: dict[str, object] | None = None,
    qualification_value: dict[str, object] | None = None,
    serving_mode: str | None = None,
    serving_effect: str | None = None,
    parent_authority_generation_root: str | None = None,
):
    """Re-root a deliberately mixed envelope as an adversarial producer."""

    payloads = candidate.payload_map()
    epoch_payload = dict(
        epoch_value
        or json.loads(payloads[EAGLEGATE_EPOCH_PAYLOAD].decode("ascii"))
    )
    qualification_payload = dict(
        qualification_value
        or json.loads(payloads[EAGLEGATE_QUALIFICATION_PAYLOAD].decode("ascii"))
    )
    qualification_root = _eaglegate_root(
        "qualification", qualification_payload
    )
    epoch_payload["qualification_root"] = qualification_root
    epoch_root = _eaglegate_root("epoch", epoch_payload)

    bridge = EaglegateQualificationBridge.from_bytes(
        payloads[EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD]
    )
    bridge = replace(
        bridge,
        eaglegate_epoch_root=epoch_root,
        identity_root=epoch_payload["identity_root"],
        plan_roots=tuple(epoch_payload["plan_roots"]),
        qualification_summary_root=qualification_root,
    )
    binding = EaglegateServingEpochBinding.from_bytes(
        payloads[EAGLEGATE_SERVING_BINDING_PAYLOAD]
    )
    bound_mode = serving_mode or binding.serving_mode
    states = [
        EaglegateEpochState.DRAFT,
        EaglegateEpochState.QUALIFIED,
        EaglegateEpochState.STAGED,
    ]
    if bound_mode == EaglegateMode.SHADOW.value:
        states.append(EaglegateEpochState.SHADOW)
    receipts: list[EaglegateEpochReceipt] = []
    for state in states:
        receipt = EaglegateEpochReceipt(
            epoch_root=epoch_root,
            state=state,
            qualification_root=(
                "" if state is EaglegateEpochState.DRAFT else qualification_root
            ),
            previous_receipt_root=(
                receipts[-1].receipt_root if receipts else ""
            ),
        )
        receipts.append(receipt)
    receipt_values = [item.canonical_dict() for item in receipts]
    binding = replace(
        binding,
        eaglegate_epoch_root=epoch_root,
        eaglegate_policy_root=canonical_root(
            "eaglegate-policy-plans",
            {
                "policy_root": epoch_payload["policy_root"],
                "plan_roots": epoch_payload["plan_roots"],
            },
        ),
        target_runtime_identity_root=epoch_payload["identity_root"],
        exactness_qualification_root=bridge.bridge_root,
        qualification_summary_root=qualification_root,
        receipt_chain_root=canonical_root(
            "eaglegate-epoch-receipts", receipt_values
        ),
        serving_mode=bound_mode,
        parent_authority_generation_root=(
            parent_authority_generation_root
            or binding.parent_authority_generation_root
        ),
    )
    payloads.update(
        {
            EAGLEGATE_EPOCH_PAYLOAD: canonical_json_bytes(epoch_payload),
            EAGLEGATE_QUALIFICATION_PAYLOAD: canonical_json_bytes(
                qualification_payload
            ),
            EAGLEGATE_QUALIFICATION_BRIDGE_PAYLOAD: bridge.canonical_bytes(),
            EAGLEGATE_RECEIPTS_PAYLOAD: canonical_json_bytes(receipt_values),
            EAGLEGATE_SERVING_BINDING_PAYLOAD: binding.canonical_bytes(),
        }
    )
    qualifications = {
        "adapter-conformance": binding.adapter_conformance_root,
        "eaglegate-policy": binding.eaglegate_policy_root,
        "exactness-qualification": binding.exactness_qualification_root,
        "exactness-report": binding.exactness_report_root,
        "qualification-summary": binding.qualification_summary_root,
        "receipt-chain": binding.receipt_chain_root,
        "serving-epoch": binding.eaglegate_epoch_root,
        "storage-generation": binding.storage_generation_root,
        "target-runtime-identity": binding.target_runtime_identity_root,
    }
    effect = serving_effect or (
        "shadow-only"
        if bound_mode == EaglegateMode.SHADOW.value
        else "target-only"
    )
    return store.build_candidate(
        namespace=binding.namespace,
        payloads=payloads,
        media_types={name: "application/json" for name in payloads},
        parent_generation_root=binding.parent_authority_generation_root,
        qualifications=qualifications,
        metadata={
            "consumer": "tds-eaglegate-serving-generation-v1",
            "serving-effect": effect,
        },
    )


def _candidate_with_receipts(
    store: AtomicGenerationStore,
    candidate,
    receipts: tuple[EaglegateEpochReceipt, ...],
):
    payloads = candidate.payload_map()
    binding = EaglegateServingEpochBinding.from_bytes(
        payloads[EAGLEGATE_SERVING_BINDING_PAYLOAD]
    )
    receipt_values = [item.canonical_dict() for item in receipts]
    binding = replace(
        binding,
        receipt_chain_root=canonical_root(
            "eaglegate-epoch-receipts", receipt_values
        ),
    )
    payloads.update(
        {
            EAGLEGATE_RECEIPTS_PAYLOAD: canonical_json_bytes(receipt_values),
            EAGLEGATE_SERVING_BINDING_PAYLOAD: binding.canonical_bytes(),
        }
    )
    qualifications = {
        item.name: item.evidence_root
        for item in candidate.manifest.qualifications
    }
    qualifications["receipt-chain"] = binding.receipt_chain_root
    return store.build_candidate(
        namespace=binding.namespace,
        payloads=payloads,
        media_types={name: "application/json" for name in payloads},
        parent_generation_root=binding.parent_authority_generation_root,
        qualifications=qualifications,
        metadata=dict(candidate.manifest.metadata),
    )


def _publish_three_generation_lineage(
    store: AtomicGenerationStore,
    storage_generation_root: str,
):
    first_epoch, first_candidate = _serving_candidate(
        store,
        storage_generation_root,
        epoch=_epoch(),
    )
    first = publish_eaglegate_serving_candidate(
        store,
        first_candidate,
        expected_head_root=None,
    )
    second_epoch, second_candidate = _serving_candidate(
        store,
        storage_generation_root,
        epoch=_epoch(
            generation=2,
            previous=first_epoch.epoch_root,
            tokens=3,
        ),
        parent=first.head.generation_root,
    )
    second = publish_eaglegate_serving_candidate(
        store,
        second_candidate,
        expected_head_root=first.head.head_root,
    )
    third_epoch, third_candidate = _serving_candidate(
        store,
        storage_generation_root,
        epoch=_epoch(
            generation=3,
            previous=second_epoch.epoch_root,
            tokens=4,
        ),
        parent=second.head.generation_root,
    )
    third = publish_eaglegate_serving_candidate(
        store,
        third_candidate,
        expected_head_root=second.head.head_root,
    )
    return first_epoch, first, second_epoch, second, third_epoch, third


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


@pytest.mark.parametrize(
    ("mode", "effect", "terminal"),
    (
        (EaglegateMode.TARGET_ONLY, "target-only", EaglegateEpochState.STAGED),
        (EaglegateMode.SHADOW, "shadow-only", EaglegateEpochState.SHADOW),
    ),
)
def test_target_only_and_shadow_qualified_generations_remain_loadable(
    tmp_path: Path,
    mode: EaglegateMode,
    effect: str,
    terminal: EaglegateEpochState,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(mode=mode),
    )
    assert dict(candidate.manifest.metadata)["serving-effect"] == effect
    publish_eaglegate_serving_candidate(store, candidate, expected_head_root=None)

    with open_eaglegate_serving_generation(store, "serving:eaglegate") as lease:
        assert lease.binding.serving_mode == mode.value
        assert lease.loaded.epoch["policy"]["mode"] == mode.value
        assert lease.loaded.receipts[-1].state is terminal


def test_loader_rejects_policy_binding_mode_mismatch(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    mixed = _rebound_candidate(
        store,
        candidate,
        serving_mode=EaglegateMode.TARGET_ONLY.value,
    )
    store.publish(mixed, expected_head_root=None)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_loader_rejects_manifest_serving_effect_mismatch(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    mixed = _rebound_candidate(
        store,
        candidate,
        serving_effect="target-only",
    )
    store.publish(mixed, expected_head_root=None)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH


@pytest.mark.parametrize(
    ("foreign_draft_predecessor", "foreign_qualification"),
    ((True, False), (False, True)),
)
def test_loader_rejects_re_rooted_receipt_lineage(
    tmp_path: Path,
    foreign_draft_predecessor: bool,
    foreign_qualification: bool,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    original = json.loads(
        candidate.payload_map()[EAGLEGATE_RECEIPTS_PAYLOAD].decode("ascii")
    )
    foreign_root = _root("foreign-receipt-lineage")
    receipts: list[EaglegateEpochReceipt] = []
    for index, value in enumerate(original):
        qualification_root = value["qualification_root"]
        if index and foreign_qualification:
            qualification_root = foreign_root
        previous_receipt_root = (
            receipts[-1].receipt_root
            if receipts
            else (foreign_root if foreign_draft_predecessor else "")
        )
        receipts.append(
            EaglegateEpochReceipt(
                epoch_root=value["epoch_root"],
                state=EaglegateEpochState(value["state"]),
                qualification_root=qualification_root,
                previous_receipt_root=previous_receipt_root,
            )
        )
    mixed = _candidate_with_receipts(store, candidate, tuple(receipts))
    store.publish(mixed, expected_head_root=None)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_loader_rejects_qualification_identity_mismatch(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    qualification = json.loads(
        candidate.payload_map()[EAGLEGATE_QUALIFICATION_PAYLOAD].decode("ascii")
    )
    qualification["identity_root"] = _root("foreign-runtime-identity")
    mixed = _rebound_candidate(
        store,
        candidate,
        qualification_value=qualification,
    )
    store.publish(mixed, expected_head_root=None)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_loader_rejects_qualification_plan_root_reordering(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_two_plan_epoch(),
    )
    qualification = json.loads(
        candidate.payload_map()[EAGLEGATE_QUALIFICATION_PAYLOAD].decode("ascii")
    )
    qualification["plan_roots"] = list(
        reversed(qualification["plan_roots"])
    )
    mixed = _rebound_candidate(
        store,
        candidate,
        qualification_value=qualification,
    )
    store.publish(mixed, expected_head_root=None)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_loader_rejects_plan_payload_order_root_mismatch(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_two_plan_epoch(),
    )
    epoch_value = json.loads(
        candidate.payload_map()[EAGLEGATE_EPOCH_PAYLOAD].decode("ascii")
    )
    epoch_value["plans"] = list(reversed(epoch_value["plans"]))
    mixed = _rebound_candidate(
        store,
        candidate,
        epoch_value=epoch_value,
    )
    store.publish(mixed, expected_head_root=None)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_loader_rejects_predecessor_without_authority_parent(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    epoch_value = json.loads(
        candidate.payload_map()[EAGLEGATE_EPOCH_PAYLOAD].decode("ascii")
    )
    epoch_value["previous_epoch_root"] = _root("unrelated-predecessor")
    mixed = _rebound_candidate(store, candidate, epoch_value=epoch_value)
    store.publish(mixed, expected_head_root=None)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_loader_cross_binds_predecessor_to_authority_parent(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    first_epoch, first_candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    first = publish_eaglegate_serving_candidate(
        store, first_candidate, expected_head_root=None
    )
    second_epoch, second_candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(
            generation=2,
            previous=first_epoch.epoch_root,
            tokens=3,
        ),
        parent=first.head.generation_root,
    )
    second = publish_eaglegate_serving_candidate(
        store,
        second_candidate,
        expected_head_root=first.head.head_root,
    )

    with open_eaglegate_serving_generation(store, "serving:eaglegate") as lease:
        assert lease.generation_root == second.head.generation_root
        assert lease.loaded.epoch["previous_epoch_root"] == first_epoch.epoch_root
        assert lease.binding.eaglegate_epoch_root == second_epoch.epoch_root


def test_loader_rejects_predecessor_mismatched_with_authority_parent(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    first_epoch, first_candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    first = publish_eaglegate_serving_candidate(
        store, first_candidate, expected_head_root=None
    )
    _, second_candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(
            generation=2,
            previous=first_epoch.epoch_root,
            tokens=3,
        ),
        parent=first.head.generation_root,
    )
    epoch_value = json.loads(
        second_candidate.payload_map()[EAGLEGATE_EPOCH_PAYLOAD].decode("ascii")
    )
    epoch_value["previous_epoch_root"] = _root("unrelated-predecessor")
    mixed = _rebound_candidate(
        store,
        second_candidate,
        epoch_value=epoch_value,
    )
    store.publish(mixed, expected_head_root=first.head.head_root)

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.IDENTITY_MISMATCH
    assert store.pin_count(first.head.generation_root) == 0


def test_child_lease_pins_parent_until_close(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    first_epoch, first_candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    first = publish_eaglegate_serving_candidate(
        store, first_candidate, expected_head_root=None
    )
    _, second_candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(
            generation=2,
            previous=first_epoch.epoch_root,
            tokens=3,
        ),
        parent=first.head.generation_root,
    )
    publish_eaglegate_serving_candidate(
        store,
        second_candidate,
        expected_head_root=first.head.head_root,
    )

    child = open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert store.pin_count(first.head.generation_root) == 1
    with pytest.raises(GenerationStoreError, match="pinned generation"):
        store.retire("serving:eaglegate", first.head.generation_root)
    child.close()
    assert store.pin_count(first.head.generation_root) == 0
    store.retire("serving:eaglegate", first.head.generation_root)


def test_three_generation_lineage_pins_every_ancestor(tmp_path: Path) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    (
        _,
        first,
        _,
        second,
        third_epoch,
        third,
    ) = _publish_three_generation_lineage(store, storage.head.generation_root)

    child = open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert child.generation_root == third.head.generation_root
    assert child.binding.eaglegate_epoch_root == third_epoch.epoch_root
    assert store.pin_count(first.head.generation_root) == 1
    assert store.pin_count(second.head.generation_root) == 1
    assert store.pin_count(third.head.generation_root) == 1
    for ancestor in (first, second):
        with pytest.raises(GenerationStoreError, match="pinned generation"):
            store.retire("serving:eaglegate", ancestor.head.generation_root)

    child.close()
    assert store.pin_count(first.head.generation_root) == 0
    assert store.pin_count(second.head.generation_root) == 0
    assert store.pin_count(third.head.generation_root) == 0
    assert store.pin_count(storage.head.generation_root) == 0


def test_builder_and_loader_reject_malformed_middle_hop_laundering(
    tmp_path: Path,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    first_epoch, first_candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    first = publish_eaglegate_serving_candidate(
        store, first_candidate, expected_head_root=None
    )
    _, second_candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(
            generation=2,
            previous=first_epoch.epoch_root,
            tokens=3,
        ),
        parent=first.head.generation_root,
    )
    second_epoch_value = json.loads(
        second_candidate.payload_map()[EAGLEGATE_EPOCH_PAYLOAD].decode("ascii")
    )
    second_epoch_value["previous_epoch_root"] = _root(
        "foreign-middle-predecessor"
    )
    malformed_second = _rebound_candidate(
        store,
        second_candidate,
        epoch_value=second_epoch_value,
    )
    second = store.publish(
        malformed_second,
        expected_head_root=first.head.head_root,
    )
    second_binding = EaglegateServingEpochBinding.from_bytes(
        malformed_second.payload_map()[EAGLEGATE_SERVING_BINDING_PAYLOAD]
    )

    with pytest.raises(GenerationContractError) as build_failure:
        _serving_candidate(
            store,
            storage.head.generation_root,
            epoch=_epoch(
                generation=3,
                previous=second_binding.eaglegate_epoch_root,
                tokens=4,
            ),
            parent=second.head.generation_root,
        )
    assert build_failure.value.fault is GenerationFault.IDENTITY_MISMATCH
    assert store.pin_count(first.head.generation_root) == 0
    assert store.pin_count(second.head.generation_root) == 0

    _, unparented_third = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(generation=3, tokens=4),
    )
    third_epoch_value = json.loads(
        unparented_third.payload_map()[EAGLEGATE_EPOCH_PAYLOAD].decode("ascii")
    )
    third_epoch_value["previous_epoch_root"] = second_binding.eaglegate_epoch_root
    forged_third = _rebound_candidate(
        store,
        unparented_third,
        epoch_value=third_epoch_value,
        parent_authority_generation_root=second.head.generation_root,
    )
    third = store.publish(
        forged_third,
        expected_head_root=second.head.head_root,
    )

    with pytest.raises(GenerationContractError) as open_failure:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert open_failure.value.fault is GenerationFault.IDENTITY_MISMATCH
    assert store.pin_count(first.head.generation_root) == 0
    assert store.pin_count(second.head.generation_root) == 0
    assert store.pin_count(third.head.generation_root) == 0
    assert store.pin_count(storage.head.generation_root) == 0


def test_lineage_hop_limit_fails_closed_and_releases_every_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    _, first, _, second, _, third = _publish_three_generation_lineage(
        store, storage.head.generation_root
    )
    monkeypatch.setattr(
        "staqtapp_tds.eaglegate.generation._MAX_AUTHORITY_LINEAGE_HOPS",
        1,
    )

    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.BOUND_EXCEEDED
    assert store.pin_count(first.head.generation_root) == 0
    assert store.pin_count(second.head.generation_root) == 0
    assert store.pin_count(third.head.generation_root) == 0
    assert store.pin_count(storage.head.generation_root) == 0


def test_lineage_cycle_guard_fails_closed_and_releases_every_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AtomicGenerationStore(tmp_path / "authority")
    storage = _storage(store, "dataset:primary", b"source")
    first_epoch, first_candidate = _serving_candidate(
        store, storage.head.generation_root, epoch=_epoch()
    )
    first = publish_eaglegate_serving_candidate(
        store, first_candidate, expected_head_root=None
    )
    _, second_candidate = _serving_candidate(
        store,
        storage.head.generation_root,
        epoch=_epoch(
            generation=2,
            previous=first_epoch.epoch_root,
            tokens=3,
        ),
        parent=first.head.generation_root,
    )
    second = publish_eaglegate_serving_candidate(
        store,
        second_candidate,
        expected_head_root=first.head.head_root,
    )

    def inject_cycle(lease):
        loaded = load_eaglegate_serving_generation(lease)
        if loaded.generation_root != first.head.generation_root:
            return loaded
        epoch_value = dict(loaded.epoch)
        epoch_value["previous_epoch_root"] = first_epoch.epoch_root
        return replace(
            loaded,
            binding=replace(
                loaded.binding,
                parent_authority_generation_root=first.head.generation_root,
            ),
            epoch=epoch_value,
        )

    monkeypatch.setattr(
        "staqtapp_tds.eaglegate.generation.load_eaglegate_serving_generation",
        inject_cycle,
    )
    with pytest.raises(GenerationContractError) as caught:
        open_eaglegate_serving_generation(store, "serving:eaglegate")
    assert caught.value.fault is GenerationFault.NONCANONICAL
    assert store.pin_count(first.head.generation_root) == 0
    assert store.pin_count(second.head.generation_root) == 0
    assert store.pin_count(storage.head.generation_root) == 0


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

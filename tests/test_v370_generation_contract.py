from __future__ import annotations

from dataclasses import replace
import json

import pytest

from staqtapp_tds.generation.generation_contract import (
    DEFAULT_GENERATION_LIMITS,
    GENERATION_AUTHORITY,
    GENERATION_CONTRACT_ID,
    GenerationAuthorityBoundary,
    GenerationContractError,
    GenerationFault,
    GenerationPublicationRecord,
    GenerationState,
    PublicationAction,
    QualifiedGenerationLimits,
    build_lifecycle_chain,
    build_manifest,
    manifest_from_json,
    validate_generation_bindings,
    validate_lifecycle_chain,
    validate_publication_record,
)


def payloads(source: bytes = b"id,name\n1,Ada\n"):
    return {
        "source": (source, "application/octet-stream", True),
        "offsets": (b"\x00" * 16, "application/octet-stream", False),
    }


def test_manifest_identity_is_deterministic_and_domain_separated():
    a = build_manifest(namespace="dataset:people", payloads=payloads())
    b = build_manifest(namespace="dataset:people", payloads=payloads())
    assert a == b
    assert a.manifest_root == b.manifest_root
    assert a.generation_root == b.generation_root
    assert a.manifest_root != a.generation_root
    assert a.contract_id == GENERATION_CONTRACT_ID


def test_manifest_roundtrip_requires_canonical_json():
    manifest = build_manifest(namespace="dataset:people", payloads=payloads())
    assert manifest_from_json(manifest.canonical_bytes()) == manifest
    pretty = json.dumps(manifest.canonical_dict(), indent=2).encode()
    with pytest.raises(GenerationContractError) as error:
        manifest_from_json(pretty)
    assert error.value.fault is GenerationFault.NONCANONICAL


def test_build_manifest_sorts_names_and_requires_one_authoritative_source():
    manifest = build_manifest(
        namespace="dataset:people",
        payloads={
            "z": (b"z", "application/octet-stream", False),
            "a": (b"a", "application/octet-stream", True),
        },
    )
    assert tuple(item.name for item in manifest.payloads) == ("a", "z")
    bad = tuple(replace(item, authoritative=True) for item in manifest.payloads)
    with pytest.raises(GenerationContractError):
        replace(manifest, payloads=bad)


def test_manifest_bounds_fail_one_over():
    limits = QualifiedGenerationLimits(
        max_payloads=1,
        max_payload_bytes=2,
        max_single_payload_bytes=2,
    )
    with pytest.raises(GenerationContractError) as error:
        build_manifest(
            namespace="dataset:people",
            payloads={
                "a": (b"a", "application/octet-stream", True),
                "b": (b"b", "application/octet-stream", False),
            },
            limits=limits,
        )
    assert error.value.fault is GenerationFault.BOUND_EXCEEDED


def test_lifecycle_is_exactly_adjacent_and_predecessor_bound():
    manifest = build_manifest(namespace="dataset:people", payloads=payloads())
    chain = build_lifecycle_chain(manifest)
    assert tuple(item.state for item in chain) == (
        GenerationState.STAGING,
        GenerationState.SEALED,
        GenerationState.VERIFIED,
        GenerationState.PUBLISHED,
    )
    assert validate_lifecycle_chain(manifest, chain) == chain[-1]

    forged = list(chain)
    forged[2] = replace(forged[2], predecessor_receipt_root=chain[0].receipt_root)
    with pytest.raises(GenerationContractError) as error:
        validate_lifecycle_chain(manifest, forged)
    assert error.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_lifecycle_rejects_skips_and_cross_generation_receipts():
    first = build_manifest(namespace="dataset:people", payloads=payloads(b"a"))
    second = build_manifest(namespace="dataset:people", payloads=payloads(b"b"))
    first_chain = build_lifecycle_chain(first)
    with pytest.raises(GenerationContractError):
        validate_lifecycle_chain(first, (first_chain[0], first_chain[2]))
    mixed = list(first_chain)
    mixed[-1] = replace(
        mixed[-1],
        generation_root=second.generation_root,
        manifest_root=second.manifest_root,
    )
    with pytest.raises(GenerationContractError):
        validate_lifecycle_chain(first, mixed)


def test_publication_record_requires_exact_cas_and_chain():
    manifest = build_manifest(namespace="dataset:people", payloads=payloads())
    published = build_lifecycle_chain(manifest)[-1]
    first = GenerationPublicationRecord(
        namespace=manifest.namespace,
        publication_sequence=1,
        action=PublicationAction.PUBLISH,
        generation_root=manifest.generation_root,
        manifest_root=manifest.manifest_root,
        published_receipt_root=published.receipt_root,
        previous_generation_root=None,
        predecessor_record_root=None,
    )
    validate_publication_record(
        first,
        previous_record=None,
        expected_current_root=None,
    )
    with pytest.raises(GenerationContractError) as error:
        validate_publication_record(
            first,
            previous_record=None,
            expected_current_root="sha256:" + "0" * 64,
        )
    assert error.value.fault is GenerationFault.PUBLICATION_CONFLICT


def test_publication_record_sequence_and_predecessor_are_contiguous():
    first_manifest = build_manifest(namespace="dataset:people", payloads=payloads(b"a"))
    second_manifest = build_manifest(
        namespace="dataset:people",
        payloads=payloads(b"b"),
        parent_generation_root=first_manifest.generation_root,
    )
    first_receipt = build_lifecycle_chain(first_manifest)[-1]
    second_receipt = build_lifecycle_chain(second_manifest)[-1]
    first = GenerationPublicationRecord(
        namespace="dataset:people",
        publication_sequence=1,
        action=PublicationAction.PUBLISH,
        generation_root=first_manifest.generation_root,
        manifest_root=first_manifest.manifest_root,
        published_receipt_root=first_receipt.receipt_root,
        previous_generation_root=None,
        predecessor_record_root=None,
    )
    second = GenerationPublicationRecord(
        namespace="dataset:people",
        publication_sequence=2,
        action=PublicationAction.PUBLISH,
        generation_root=second_manifest.generation_root,
        manifest_root=second_manifest.manifest_root,
        published_receipt_root=second_receipt.receipt_root,
        previous_generation_root=first_manifest.generation_root,
        predecessor_record_root=first.record_root,
    )
    validate_publication_record(
        second,
        previous_record=first,
        expected_current_root=first_manifest.generation_root,
    )
    with pytest.raises(GenerationContractError):
        validate_publication_record(
            replace(second, publication_sequence=3),
            previous_record=first,
            expected_current_root=first_manifest.generation_root,
        )


def test_mixed_generation_bindings_fail_before_consumption():
    root = "sha256:" + "1" * 64
    validate_generation_bindings(root, {"source": root, "offsets": root})
    with pytest.raises(GenerationContractError) as error:
        validate_generation_bindings(
            root,
            {"source": root, "offsets": "sha256:" + "2" * 64},
        )
    assert error.value.fault is GenerationFault.IDENTITY_MISMATCH


def test_authority_boundary_cannot_be_widened():
    assert GENERATION_AUTHORITY.activation_authority is False
    assert GENERATION_AUTHORITY.browser_publication_authority is False
    with pytest.raises(GenerationContractError) as error:
        GenerationAuthorityBoundary(semantic_authority=True)
    assert error.value.fault is GenerationFault.AUTHORITY_REJECTED


def test_metadata_and_qualification_order_are_canonical():
    root_a = "sha256:" + "a" * 64
    root_b = "sha256:" + "b" * 64
    manifest = build_manifest(
        namespace="dataset:people",
        payloads=payloads(),
        qualifications={"z": root_b, "a": root_a},
        metadata={"z": "last", "a": "first"},
    )
    assert tuple(item.name for item in manifest.qualifications) == ("a", "z")
    assert manifest.metadata == (("a", "first"), ("z", "last"))


def test_empty_payload_set_is_rejected():
    with pytest.raises(GenerationContractError):
        build_manifest(namespace="dataset:empty", payloads={})


def test_default_limits_are_immutable_and_reasonably_bounded():
    assert DEFAULT_GENERATION_LIMITS.max_payloads == 4096
    with pytest.raises(Exception):
        DEFAULT_GENERATION_LIMITS.max_payloads = 1

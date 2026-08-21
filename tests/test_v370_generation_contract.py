from __future__ import annotations

import copy
from dataclasses import asdict, fields, replace
import json
import pickle

import pytest

import staqtapp_tds.generation.generation_contract as generation_contract
from staqtapp_tds.generation.generation_contract import (
    DEFAULT_GENERATION_LIMITS,
    GENERATION_AUTHORITY,
    GENERATION_CONTRACT_ID,
    GenerationAuthorityBoundary,
    GenerationContractError,
    GenerationFault,
    GenerationManifest,
    GenerationPayload,
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


def test_frozen_manifest_roots_are_not_rehashed_on_access(monkeypatch):
    manifest = build_manifest(namespace="dataset:cached-roots", payloads=payloads())
    expected_manifest_root = manifest.manifest_root
    expected_generation_root = manifest.generation_root

    def unexpected_hash(*args, **kwargs):
        raise AssertionError("immutable manifest root was recomputed")

    monkeypatch.setattr(generation_contract.hashlib, "sha256", unexpected_hash)
    assert manifest.manifest_root == expected_manifest_root
    assert manifest.generation_root == expected_generation_root


def test_manifest_root_caches_do_not_change_dataclass_contract():
    manifest = build_manifest(namespace="dataset:cached-roots", payloads=payloads())
    expected_field_names = {
        "namespace",
        "parent_generation_root",
        "payloads",
        "qualifications",
        "metadata",
        "limits",
        "format_version",
        "contract_id",
    }

    assert {field.name for field in fields(manifest)} == expected_field_names
    assert set(asdict(manifest)) == expected_field_names
    assert manifest.manifest_root == (
        "sha256:d2093d865a1123821878086fa3a53769f9a040d42cb9fbf1d6be9b0bd9b1f80e"
    )
    assert manifest.generation_root == (
        "sha256:b6e7551639b3910169509e033620ffe02358ac7dd8aeda219155e81062aae12e"
    )


@pytest.mark.parametrize("copier", [copy.copy, copy.deepcopy, pickle.dumps])
def test_manifest_root_caches_survive_standard_copy_protocols(copier):
    manifest = build_manifest(namespace="dataset:cached-roots", payloads=payloads())

    if copier is pickle.dumps:
        copied = pickle.loads(copier(manifest))
    else:
        copied = copier(manifest)

    assert copied == manifest
    assert copied.manifest_root == manifest.manifest_root
    assert copied.generation_root == manifest.generation_root


def test_manifest_root_cache_rejects_mutable_or_subclassed_contract_records():
    manifest = build_manifest(namespace="dataset:cached-roots", payloads=payloads())

    class MutablePayload:
        name = "source"
        media_type = "application/octet-stream"
        size = 1
        content_root = "sha256:" + "0" * 64
        authoritative = True

        def canonical_dict(self):
            return {
                "name": self.name,
                "media_type": self.media_type,
                "size": self.size,
                "content_root": self.content_root,
                "authoritative": self.authoritative,
            }

    with pytest.raises(GenerationContractError, match="exact immutable"):
        replace(manifest, payloads=(MutablePayload(),))

    class PayloadSubclass(GenerationPayload):
        pass

    payload = manifest.payloads[0]
    subclassed = PayloadSubclass(
        payload.name,
        payload.media_type,
        payload.size,
        payload.content_root,
        payload.authoritative,
    )
    with pytest.raises(GenerationContractError, match="exact immutable"):
        replace(manifest, payloads=(subclassed,))

    class ManifestSubclass(GenerationManifest):
        pass

    with pytest.raises(GenerationContractError, match="exact GenerationManifest"):
        ManifestSubclass(
            namespace=manifest.namespace,
            parent_generation_root=manifest.parent_generation_root,
            payloads=manifest.payloads,
        )


def test_generation_cached_root_inputs_reject_scalar_subclasses():
    class EvilInt(int):
        def __lt__(self, other):
            return False

        def __gt__(self, other):
            return False

    class EvilStr(str):
        def __eq__(self, other):
            return True

    with pytest.raises(GenerationContractError, match="payload size must be an integer"):
        GenerationPayload(
            name="source",
            media_type="application/octet-stream",
            size=EvilInt(-1),
            content_root="sha256:" + "0" * 64,
            authoritative=True,
        )

    with pytest.raises(GenerationContractError, match="max_payloads must be an integer"):
        QualifiedGenerationLimits(max_payloads=EvilInt(-1))

    manifest = build_manifest(namespace="dataset:exact-scalars", payloads=payloads())
    with pytest.raises(
        GenerationContractError,
        match="generation format version must be an integer",
    ):
        replace(manifest, format_version=EvilInt(99))
    with pytest.raises(GenerationContractError, match="namespace is not canonical"):
        replace(manifest, namespace=EvilStr(manifest.namespace))


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


def test_linear_canonical_order_checks_preserve_rejection_semantics():
    root_a = "sha256:" + "a" * 64
    root_b = "sha256:" + "b" * 64
    manifest = build_manifest(
        namespace="dataset:order",
        payloads=payloads(),
        qualifications={"a": root_a, "b": root_b},
        metadata={"a": "first", "b": "second"},
    )

    with pytest.raises(GenerationContractError) as unsorted_payloads:
        replace(manifest, payloads=tuple(reversed(manifest.payloads)))
    assert unsorted_payloads.value.fault is GenerationFault.NONCANONICAL

    with pytest.raises(GenerationContractError, match="duplicate payload name"):
        replace(manifest, payloads=(manifest.payloads[0], manifest.payloads[0]))

    with pytest.raises(GenerationContractError) as unsorted_qualifications:
        replace(manifest, qualifications=tuple(reversed(manifest.qualifications)))
    assert unsorted_qualifications.value.fault is GenerationFault.NONCANONICAL

    with pytest.raises(GenerationContractError, match="duplicate qualification name"):
        replace(
            manifest,
            qualifications=(manifest.qualifications[0], manifest.qualifications[0]),
        )

    with pytest.raises(GenerationContractError, match="duplicate metadata key"):
        replace(manifest, metadata=(("a", "first"), ("a", "second")))


def test_empty_payload_set_is_rejected():
    with pytest.raises(GenerationContractError):
        build_manifest(namespace="dataset:empty", payloads={})


def test_default_limits_are_immutable_and_reasonably_bounded():
    assert DEFAULT_GENERATION_LIMITS.max_payloads == 4096
    with pytest.raises(Exception):
        DEFAULT_GENERATION_LIMITS.max_payloads = 1

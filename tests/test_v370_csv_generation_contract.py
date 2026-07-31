from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path

import pytest

from staqtapp_tds.csv_layer.generation_contract import (
    CSV_GENERATION_AUTHORITY,
    CSV_GENERATION_CONTRACT_ID,
    CSV_GENERATION_FORMAT_VERSION,
    CSVChunkDescriptor,
    CSVGenerationAuthorityBoundary,
    CSVGenerationContractError,
    CSVGenerationFault,
    CSVGenerationIdentity,
    CSVGenerationLimits,
    CSVGenerationManifest,
    CSVGenerationReceipt,
    CSVGenerationState,
    chunk_sequence_root,
    validate_atomic_publication,
    validate_manifest,
    validate_pinned_generation,
    validate_receipt_transition,
)

ROOT = Path(__file__).resolve().parents[1]


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _limits(**overrides: int) -> CSVGenerationLimits:
    values = {
        "max_source_bytes": 1_024,
        "max_chunk_bytes": 256,
        "max_chunks": 16,
        "max_rows": 128,
        "max_closure_nodes": 64,
        "max_closure_edges": 256,
    }
    values.update(overrides)
    return CSVGenerationLimits(**values)


def _chunks() -> tuple[CSVChunkDescriptor, ...]:
    return (
        CSVChunkDescriptor(0, 0, 4, _root("chunk-0")),
        CSVChunkDescriptor(1, 4, 9, _root("chunk-1")),
    )


def _identity(
    *,
    chunks: tuple[CSVChunkDescriptor, ...] | None = None,
    limits: CSVGenerationLimits | None = None,
    **overrides: str,
) -> CSVGenerationIdentity:
    selected_chunks = _chunks() if chunks is None else chunks
    selected_limits = _limits() if limits is None else limits
    values = {
        "dataset_id": "dataset:qualification-csv",
        "source_sha256": _root("source"),
        "chunk_sequence_root": chunk_sequence_root(selected_chunks),
        "parser_contract_root": _root("parser"),
        "dialect_root": _root("dialect"),
        "row_offsets_root": _root("offsets"),
        "row_anchors_root": _root("anchors"),
        "closure_root": _root("closure"),
        "limits_root": selected_limits.limits_root,
        "parent_generation_root": "",
    }
    values.update(overrides)
    return CSVGenerationIdentity(**values)


def _manifest(
    *,
    chunks: tuple[CSVChunkDescriptor, ...] | None = None,
    limits: CSVGenerationLimits | None = None,
    source_bytes: int = 9,
    row_count: int = 2,
) -> CSVGenerationManifest:
    selected_chunks = _chunks() if chunks is None else chunks
    selected_limits = _limits() if limits is None else limits
    return CSVGenerationManifest(
        identity=_identity(chunks=selected_chunks, limits=selected_limits),
        source_bytes=source_bytes,
        row_count=row_count,
        closure_node_count=4,
        closure_edge_count=3,
        chunks=selected_chunks,
    )


def test_contract_identity_is_stable_canonical_and_immutable() -> None:
    assert CSV_GENERATION_FORMAT_VERSION == 1
    assert CSV_GENERATION_CONTRACT_ID == "tds-csv-generation-v1"
    first = _manifest()
    second = _manifest()
    assert first.identity.generation_root == second.identity.generation_root
    assert first.manifest_root == second.manifest_root
    assert first.manifest_root.startswith("sha256:")
    assert len(first.manifest_root) == 71
    with pytest.raises(FrozenInstanceError):
        first.source_bytes = 10  # type: ignore[misc]


def test_empty_input_has_one_canonical_no_chunk_representation() -> None:
    limits = _limits()
    chunks: tuple[CSVChunkDescriptor, ...] = ()
    manifest = CSVGenerationManifest(
        identity=_identity(
            chunks=chunks,
            limits=limits,
            source_sha256=_root("empty-source"),
        ),
        source_bytes=0,
        row_count=0,
        closure_node_count=1,
        closure_edge_count=0,
        chunks=chunks,
    )
    validate_manifest(manifest, limits)

    with pytest.raises(CSVGenerationContractError) as noncanonical:
        CSVGenerationManifest(
            identity=_identity(chunks=_chunks(), limits=limits),
            source_bytes=0,
            row_count=0,
            closure_node_count=1,
            closure_edge_count=0,
            chunks=_chunks(),
        )
    assert noncanonical.value.fault is CSVGenerationFault.NONCANONICAL


def test_chunk_spans_must_be_ordered_contiguous_and_exact() -> None:
    gap = (
        CSVChunkDescriptor(0, 0, 4, _root("gap-0")),
        CSVChunkDescriptor(1, 5, 9, _root("gap-1")),
    )
    with pytest.raises(CSVGenerationContractError) as gap_error:
        _manifest(chunks=gap)
    assert gap_error.value.fault is CSVGenerationFault.NONCANONICAL

    wrong_ordinal = (
        CSVChunkDescriptor(0, 0, 4, _root("ordinal-0")),
        CSVChunkDescriptor(2, 4, 9, _root("ordinal-1")),
    )
    with pytest.raises(CSVGenerationContractError) as ordinal_error:
        _manifest(chunks=wrong_ordinal)
    assert ordinal_error.value.fault is CSVGenerationFault.NONCANONICAL

    with pytest.raises(CSVGenerationContractError) as incomplete:
        _manifest(source_bytes=10)
    assert incomplete.value.fault is CSVGenerationFault.INCOMPLETE_GENERATION


def test_chunk_sequence_root_is_bound_into_generation_identity() -> None:
    chunks = _chunks()
    identity = _identity(chunks=chunks, chunk_sequence_root=_root("wrong-sequence"))
    with pytest.raises(CSVGenerationContractError) as mismatch:
        CSVGenerationManifest(
            identity=identity,
            source_bytes=9,
            row_count=2,
            closure_node_count=4,
            closure_edge_count=3,
            chunks=chunks,
        )
    assert mismatch.value.fault is CSVGenerationFault.IDENTITY_MISMATCH


def test_qualified_limits_are_rooted_and_fail_one_over() -> None:
    limits = _limits(max_source_bytes=8)
    manifest = _manifest(limits=limits)
    with pytest.raises(CSVGenerationContractError) as oversized:
        validate_manifest(manifest, limits)
    assert oversized.value.fault is CSVGenerationFault.BOUND_EXCEEDED

    admitted = _limits()
    manifest = _manifest(limits=admitted)
    validate_manifest(manifest, admitted)
    with pytest.raises(CSVGenerationContractError) as profile_mismatch:
        validate_manifest(manifest, _limits(max_rows=127))
    assert profile_mismatch.value.fault is CSVGenerationFault.IDENTITY_MISMATCH


def test_receipts_require_adjacent_append_only_transitions() -> None:
    manifest = _manifest()
    staging = CSVGenerationReceipt(
        manifest.identity.generation_root,
        manifest.manifest_root,
        CSVGenerationState.STAGING,
    )
    sealed = CSVGenerationReceipt(
        manifest.identity.generation_root,
        manifest.manifest_root,
        CSVGenerationState.SEALED,
        staging.receipt_root,
    )
    verified = CSVGenerationReceipt(
        manifest.identity.generation_root,
        manifest.manifest_root,
        CSVGenerationState.VERIFIED,
        sealed.receipt_root,
    )
    published = CSVGenerationReceipt(
        manifest.identity.generation_root,
        manifest.manifest_root,
        CSVGenerationState.PUBLISHED,
        verified.receipt_root,
    )
    validate_receipt_transition(staging, sealed)
    validate_receipt_transition(sealed, verified)
    validate_receipt_transition(verified, published)

    skipped = CSVGenerationReceipt(
        manifest.identity.generation_root,
        manifest.manifest_root,
        CSVGenerationState.PUBLISHED,
        staging.receipt_root,
    )
    with pytest.raises(CSVGenerationContractError) as invalid:
        validate_receipt_transition(staging, skipped)
    assert invalid.value.fault is CSVGenerationFault.NONCANONICAL


def test_atomic_publication_requires_cas_and_published_receipt() -> None:
    manifest = _manifest()
    published = CSVGenerationReceipt(
        manifest.identity.generation_root,
        manifest.manifest_root,
        CSVGenerationState.PUBLISHED,
        _root("verified-receipt"),
    )
    current = _root("current-manifest")
    validate_atomic_publication(
        observed_current_manifest_root=current,
        expected_current_manifest_root=current,
        candidate=published,
    )

    with pytest.raises(CSVGenerationContractError) as conflict:
        validate_atomic_publication(
            observed_current_manifest_root=_root("other-current"),
            expected_current_manifest_root=current,
            candidate=published,
        )
    assert conflict.value.fault is CSVGenerationFault.PUBLICATION_CONFLICT

    verified = CSVGenerationReceipt(
        manifest.identity.generation_root,
        manifest.manifest_root,
        CSVGenerationState.VERIFIED,
        _root("sealed-receipt"),
    )
    with pytest.raises(CSVGenerationContractError) as incomplete:
        validate_atomic_publication(
            observed_current_manifest_root=current,
            expected_current_manifest_root=current,
            candidate=verified,
        )
    assert incomplete.value.fault is CSVGenerationFault.INCOMPLETE_GENERATION


def test_mixed_generation_components_fail_before_ranking() -> None:
    generation = _manifest().identity.generation_root
    validate_pinned_generation(
        generation,
        {
            "source_binding": generation,
            "offset_binding": generation,
            "anchor_binding": generation,
            "closure_binding": generation,
        },
    )
    with pytest.raises(CSVGenerationContractError) as mixed:
        validate_pinned_generation(
            generation,
            {
                "source_binding": generation,
                "closure_binding": _root("other-generation"),
            },
        )
    assert mixed.value.fault is CSVGenerationFault.IDENTITY_MISMATCH


def test_generation_authority_cannot_be_widened() -> None:
    assert CSV_GENERATION_AUTHORITY.original_bytes_authoritative is True
    assert CSV_GENERATION_AUTHORITY.immutable_after_seal is True
    assert CSV_GENERATION_AUTHORITY.may_rank_traces is False
    assert CSV_GENERATION_AUTHORITY.may_accept_learned_writes is False
    assert CSV_GENERATION_AUTHORITY.browser_or_studio_may_publish is False
    assert CSV_GENERATION_AUTHORITY.authority_root.startswith("sha256:")
    with pytest.raises(CSVGenerationContractError) as widened:
        CSVGenerationAuthorityBoundary(may_rank_traces=True)
    assert widened.value.fault is CSVGenerationFault.AUTHORITY_REJECTED


def test_phase_contract_blocks_learned_serving_and_requires_exact_round_trip() -> None:
    contract = (ROOT / "docs" / "122_v370_Atomic_CSV_Generation_Contract.md").read_text(
        encoding="utf-8"
    )
    assert "Original bytes are authoritative" in contract
    assert "old complete generation or" in contract
    assert "learned Trace Ranking layer is still disabled" in contract
    assert "Only after this gate" in contract
    assert "3.7.0" in contract
    assert ".postN" in contract

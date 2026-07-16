from __future__ import annotations

from staqtapp_tds import __version__
from staqtapp_tds.tds_filesystem import TDSFileSystem
from staqtapp_tds.csv_layer import (
    CSV_SEMANTIC_IR_CANDIDATE_CONTRACT_KEYS,
    CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES,
    CSV_SEMANTIC_IR_MAX_PROPOSITIONS,
    CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT,
    CSV_SEMANTIC_IR_PROPOSITION_STATES,
    CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES,
    CSV_SEMANTIC_IR_VERSION,
    CSVSemanticIRDeclaration,
    artifact_keys,
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_interpole_timeline_ring_report,
    commit_csv_kernel_performance_gate_report,
    commit_csv_kernel_readiness_contract_report,
    commit_csv_native_row_anchor_kernel_report,
    commit_csv_native_scan_kernel_prototype_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    csv_semantic_ir_candidate_fingerprint,
    csv_semantic_ir_candidate_summary,
    csv_semantic_ir_declaration_fingerprint,
    import_csv_bytes,
    prepare_csv_semantic_ir_candidate,
    prepare_csv_semantic_ir_handoff,
    replay_csv_semantic_ir_candidate,
    validate_csv_semantic_ir_candidate,
)


def _ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b'id,name,score\n1,Ada,99\n2,Grace,98\n3,Katherine,97\n',
    *,
    chunk_size: int | None = 7,
):
    manifest = import_csv_bytes(fs.root, payload, source_name="semantic_ir_foundation.csv")
    reports = (
        commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id),
        commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id),
        commit_csv_native_storage_artifacts(fs.root, manifest.csv_id),
        commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id),
        commit_csv_interpole_timeline_report(fs.root, manifest.csv_id),
        commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id),
        commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id),
        commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id, chunk_size=chunk_size),
        commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id, chunk_size=chunk_size),
        commit_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id, chunk_size=chunk_size),
        commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id),
    )
    assert all(report.ok for report in reports)
    return manifest


def _declarations() -> tuple[CSVSemanticIRDeclaration, ...]:
    return (
        CSVSemanticIRDeclaration(
            proposition_id="customer_identifier_role",
            semantic_kind="column_role",
            subject_scope="column",
            subject_locator="index:0",
            predicate="represents",
            object_value="CustomerIdentifier",
            state="proposed",
            evidence_names=(
                "core_artifact_integrity",
                "interpole_timeline_ring",
                "native_row_anchor_parity",
            ),
        ),
        CSVSemanticIRDeclaration(
            proposition_id="dataset_domain",
            semantic_kind="dataset_concept",
            subject_scope="dataset",
            subject_locator="current_csv",
            predicate="candidate_domain",
            object_value="CustomerScoreRecords",
            state="proposed",
            evidence_names=(
                "original_byte_identity",
                "storage_adapter_replay",
                "browser_monitor_replay",
            ),
        ),
    )


def test_version_350_formal_semantic_ir_foundation_contract():
    assert __version__ == "3.5.3.post1"
    assert CSV_SEMANTIC_IR_VERSION == "1.0"
    assert CSV_SEMANTIC_IR_PAYLOAD_BYTE_LIMIT >= 131_072
    assert CSV_SEMANTIC_IR_MAX_PROPOSITIONS == 256
    assert CSV_SEMANTIC_IR_FOUNDATION_ACCEPTED_STATES == ("proposed",)
    assert CSV_SEMANTIC_IR_PROPOSITION_STATES == (
        "proposed",
        "validated",
        "contested",
        "superseded",
        "committed",
    )
    assert "formal_ir_committed" in CSV_SEMANTIC_IR_CANDIDATE_CONTRACT_KEYS


def test_semantic_ir_candidate_requires_explicit_opt_in_and_remains_read_only():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    candidate = prepare_csv_semantic_ir_candidate(fs.root, manifest.csv_id, _declarations())

    assert candidate.ok is False
    assert candidate.status == "semantic_ir_candidate_blocked"
    assert candidate.explicit_opt_in is False
    assert candidate.source_handoff_revalidated is False
    assert "semantic_ir_explicit_opt_in_required" in candidate.errors
    assert candidate.tds_artifact_writes == 0
    assert candidate.directory_state_unchanged is True
    assert set(fs.root._entries.keys()) == before_keys


def test_semantic_ir_validation_does_not_promote_a_blocked_candidate():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    blocked = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=False,
    )

    validation = validate_csv_semantic_ir_candidate(blocked.to_dict())

    assert validation.ok is False
    assert "semantic_ir_candidate_source_blocked" in validation.errors
    assert "semantic_ir_candidate_contains_errors" in validation.errors


def test_semantic_ir_candidate_builds_explicit_propositions_without_storage_writes():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    before_keys = set(fs.root._entries.keys())

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    )
    summary = csv_semantic_ir_candidate_summary(candidate)

    assert candidate.ok is True
    assert candidate.status == "semantic_ir_candidate_ready"
    assert candidate.explicit_opt_in is True
    assert candidate.caller_declarations_only is True
    assert candidate.evidence_references_only is True
    assert candidate.immutable_source_evidence is True
    assert candidate.lifecycle_transitions_applied is False
    assert candidate.semantic_artifact_persisted is False
    assert candidate.formal_ir_committed is False
    assert candidate.source_handoff_revalidated is True
    assert candidate.automatic_semantic_reasoning is False
    assert candidate.semantic_conclusions_committed is False
    assert candidate.ai_behavior is False
    assert all(item.state == "proposed" for item in candidate.propositions)
    assert all(item.explicit_declaration and not item.inferred for item in candidate.propositions)
    assert all(ref.ok for item in candidate.propositions for ref in item.evidence)
    assert summary["proposition_count"] == 2
    assert summary["evidence_reference_count"] == 6
    assert candidate.tds_artifact_writes == 0
    assert candidate.directory_state_unchanged is True
    assert set(fs.root._entries.keys()) == before_keys


def test_semantic_ir_candidate_is_deterministic_and_serialization_validates():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)

    first = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    )
    second = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    )
    validation = validate_csv_semantic_ir_candidate(first.to_dict())

    assert first.ok is True
    assert second.ok is True
    assert first.candidate_fingerprint == second.candidate_fingerprint
    assert first.payload_bytes == second.payload_bytes
    assert first.candidate_fingerprint == csv_semantic_ir_candidate_fingerprint(first)
    assert first.propositions[0].declaration_fingerprint == csv_semantic_ir_declaration_fingerprint(_declarations()[0])
    assert validation.ok is True
    assert validation.status == "semantic_ir_candidate_valid"


def test_semantic_ir_candidate_replays_from_current_committed_evidence():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    )
    before_keys = set(fs.root._entries.keys())

    replay = replay_csv_semantic_ir_candidate(fs.root, manifest.csv_id, candidate.to_dict())

    assert replay.ok is True
    assert replay.status == "semantic_ir_replay_valid"
    assert replay.source_candidate_fingerprint == replay.replay_candidate_fingerprint
    assert replay.source_handoff_closure_fingerprint == replay.replay_handoff_closure_fingerprint
    assert replay.mismatched_fields == ()
    assert replay.tds_artifact_writes == 0
    assert set(fs.root._entries.keys()) == before_keys


def test_semantic_ir_candidate_serialized_contract_rejects_missing_top_level_field():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    payload = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    ).to_dict()
    payload.pop("automatic_type_inference")

    validation = validate_csv_semantic_ir_candidate(payload)

    assert validation.ok is False
    assert "automatic_type_inference" in validation.missing_contract_keys
    assert "semantic_ir_contract_missing:automatic_type_inference" in validation.errors


def test_semantic_ir_candidate_rejects_missing_nested_proposition_and_evidence_fields():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    payload = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    ).to_dict()
    payload["propositions"][0].pop("predicate")
    payload["propositions"][1]["evidence"][0].pop("source_key")

    validation = validate_csv_semantic_ir_candidate(payload)

    assert validation.ok is False
    assert "0:predicate" in validation.missing_proposition_keys
    assert "1:0:source_key" in validation.missing_evidence_ref_keys


def test_semantic_ir_candidate_rejects_nested_semantic_tamper():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    payload = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    ).to_dict()
    payload["propositions"][0]["object_value"] = "TamperedMeaning"

    validation = validate_csv_semantic_ir_candidate(payload)

    assert validation.ok is False
    assert "semantic_ir_candidate_fingerprint_mismatch" in validation.errors
    assert any(error.endswith("declaration_fingerprint_mismatch") for error in validation.errors)


def test_semantic_ir_foundation_blocks_non_proposed_lifecycle_states():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    declaration = CSVSemanticIRDeclaration(
        proposition_id="premature_commit",
        semantic_kind="column_type",
        subject_scope="column",
        subject_locator="index:2",
        predicate="has_type",
        object_value="integer",
        state="committed",
        evidence_names=("core_artifact_integrity",),
    )

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        (declaration,),
        explicit_opt_in=True,
    )

    assert candidate.ok is False
    assert candidate.propositions == ()
    assert any("state_not_admitted_in_foundation:committed" in error for error in candidate.errors)
    assert candidate.lifecycle_transitions_applied is False
    assert candidate.formal_ir_committed is False


def test_semantic_ir_candidate_blocks_unknown_or_duplicate_evidence_references():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    declarations = (
        CSVSemanticIRDeclaration(
            proposition_id="unknown_evidence",
            semantic_kind="custom",
            subject_scope="custom",
            subject_locator="logical:subject",
            predicate="candidate_relation",
            object_value="LogicalObject",
            evidence_names=("not_a_csv_evidence_lane",),
        ),
        CSVSemanticIRDeclaration(
            proposition_id="duplicate_evidence",
            semantic_kind="custom",
            subject_scope="custom",
            subject_locator="logical:subject:2",
            predicate="candidate_relation",
            object_value="LogicalObject2",
            evidence_names=("core_artifact_integrity", "core_artifact_integrity"),
        ),
    )

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        declarations,
        explicit_opt_in=True,
    )

    assert candidate.ok is False
    assert any("evidence_name_unknown:not_a_csv_evidence_lane" in error for error in candidate.errors)
    assert any("duplicate_evidence_names" in error for error in candidate.errors)


def test_semantic_ir_candidate_blocks_duplicate_proposition_ids():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    first, second = _declarations()
    duplicate = CSVSemanticIRDeclaration(
        proposition_id=first.proposition_id,
        semantic_kind=second.semantic_kind,
        subject_scope=second.subject_scope,
        subject_locator=second.subject_locator,
        predicate=second.predicate,
        object_value=second.object_value,
        evidence_names=second.evidence_names,
    )

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        (first, duplicate),
        explicit_opt_in=True,
    )

    assert candidate.ok is False
    assert f"duplicate_proposition_id:{first.proposition_id}" in candidate.errors


def test_semantic_ir_candidate_blocks_empty_and_excessive_declaration_sets():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)

    empty = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        (),
        explicit_opt_in=True,
    )
    base = _declarations()[0]
    excessive_declarations = tuple(
        CSVSemanticIRDeclaration(
            proposition_id=f"proposal_{index}",
            semantic_kind=base.semantic_kind,
            subject_scope=base.subject_scope,
            subject_locator=f"index:{index}",
            predicate=base.predicate,
            object_value=base.object_value,
            evidence_names=base.evidence_names,
        )
        for index in range(CSV_SEMANTIC_IR_MAX_PROPOSITIONS + 1)
    )
    excessive = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        excessive_declarations,
        explicit_opt_in=True,
    )

    assert empty.ok is False
    assert "semantic_ir_declarations_empty" in empty.errors
    assert excessive.ok is False
    assert any(error.startswith("semantic_ir_proposition_count_exceeded:") for error in excessive.errors)
    assert len(excessive.propositions) == CSV_SEMANTIC_IR_MAX_PROPOSITIONS


def test_semantic_ir_candidate_accepts_matching_supplied_handoff_snapshot():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    handoff = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id)

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
        source_handoff=handoff.to_dict(),
    )

    assert candidate.ok is True
    assert candidate.handoff_closure_fingerprint == handoff.closure_fingerprint


def test_semantic_ir_candidate_rejects_stale_supplied_handoff_after_source_drift():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    handoff = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id)
    fs.root.write_text(
        artifact_keys(manifest.csv_id)["raw"],
        "id,name,score\n1,Drifted,0\n",
        overwrite=True,
        provenance="REAL",
    )

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
        source_handoff=handoff.to_dict(),
    )

    assert candidate.ok is False
    assert candidate.status == "semantic_ir_candidate_blocked"
    assert any(
        error in {
            "semantic_ir_source_handoff_stale_or_drifted",
            "semantic_ir_source_handoff_raw_sha256_mismatch",
        }
        or error.startswith("semantic_ir_handoff:")
        for error in candidate.errors
    )


def test_semantic_ir_candidate_rejects_tampered_handoff_admission_contract():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    handoff = prepare_csv_semantic_ir_handoff(fs.root, manifest.csv_id).to_dict()
    handoff["evidence"][0]["fingerprint"] = "0" * 64

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
        source_handoff=handoff,
    )

    assert candidate.ok is False
    assert candidate.status == "semantic_ir_candidate_blocked"
    assert any("closure_fingerprint_mismatch" in error for error in candidate.errors)
    assert candidate.formal_ir_committed is False


def test_semantic_ir_replay_fails_closed_after_source_csv_drift():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    )
    fs.root.write_text(
        artifact_keys(manifest.csv_id)["raw"],
        "id,name,score\n1,Tampered,0\n",
        overwrite=True,
        provenance="REAL",
    )

    replay = replay_csv_semantic_ir_candidate(fs.root, manifest.csv_id, candidate)

    assert replay.ok is False
    assert replay.status == "semantic_ir_replay_blocked"
    assert replay.source_handoff_closure_fingerprint != replay.replay_handoff_closure_fingerprint
    assert any(error.startswith("semantic_ir_rebuild:") for error in replay.errors)
    assert replay.native_storage_writes is False
    assert replay.native_storage_hot_path_touched is False


def test_semantic_ir_candidate_payload_bound_fails_closed():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
        payload_byte_limit=512,
    )

    assert candidate.ok is False
    assert candidate.status == "semantic_ir_candidate_blocked"
    assert candidate.payload_bytes > candidate.payload_byte_limit
    assert any(error.startswith("semantic_ir_payload_too_large:") for error in candidate.errors)


def test_semantic_ir_validation_rejects_forbidden_inference_or_commit_flags():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    payload = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        _declarations(),
        explicit_opt_in=True,
    ).to_dict()
    payload["automatic_entity_inference"] = True
    payload["automatic_semantic_reasoning"] = True
    payload["ai_behavior"] = True
    payload["formal_ir_committed"] = True
    payload["native_storage_hot_path_touched"] = True

    validation = validate_csv_semantic_ir_candidate(payload)

    assert validation.ok is False
    assert "semantic_ir_forbidden_boundary_true:automatic_entity_inference" in validation.errors
    assert "semantic_ir_forbidden_boundary_true:automatic_semantic_reasoning" in validation.errors
    assert "semantic_ir_forbidden_boundary_true:ai_behavior" in validation.errors
    assert "semantic_ir_forbidden_boundary_true:formal_ir_committed" in validation.errors
    assert "semantic_ir_forbidden_boundary_true:native_storage_hot_path_touched" in validation.errors


def test_semantic_ir_candidate_rejects_unsafe_identifiers_and_unbounded_text():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    declaration = CSVSemanticIRDeclaration(
        proposition_id="../unsafe",
        semantic_kind="custom",
        subject_scope="custom",
        subject_locator="x" * 513,
        predicate="candidate_relation",
        object_value="LogicalObject",
        evidence_names=(CSV_SEMANTIC_IR_REQUIRED_EVIDENCE_NAMES[0],),
    )

    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        (declaration,),
        explicit_opt_in=True,
    )

    assert candidate.ok is False
    assert any("proposition_id_invalid" in error for error in candidate.errors)
    assert any("subject_locator_invalid" in error for error in candidate.errors)

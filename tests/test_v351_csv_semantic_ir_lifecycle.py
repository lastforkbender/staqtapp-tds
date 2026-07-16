from __future__ import annotations

from staqtapp_tds import __version__
from staqtapp_tds.tds_filesystem import TDSFileSystem
from staqtapp_tds.csv_layer import (
    CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS,
    CSV_SEMANTIC_IR_LIFECYCLE_CONTRACT_KEYS,
    CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT,
    CSV_SEMANTIC_IR_LIFECYCLE_STATES,
    CSV_SEMANTIC_IR_LIFECYCLE_VERSION,
    CSV_SEMANTIC_IR_MAX_TRANSITIONS,
    CSV_SEMANTIC_IR_TRANSITION_AUTHORITY_SCOPES,
    CSVSemanticIRDeclaration,
    CSVSemanticIRTransitionAuthorization,
    CSVSemanticIRTransitionRequest,
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
    csv_semantic_ir_lifecycle_fingerprint,
    csv_semantic_ir_transition_authorization_fingerprint,
    csv_semantic_ir_transition_fingerprint,
    import_csv_bytes,
    prepare_csv_semantic_ir_candidate,
    prepare_csv_semantic_ir_transition,
    replay_csv_semantic_ir_lifecycle,
    validate_csv_semantic_ir_lifecycle,
)


def _ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b"id,name,score\n1,Ada,99\n2,Grace,98\n3,Katherine,97\n",
    *,
    chunk_size: int | None = 7,
):
    manifest = import_csv_bytes(
        fs.root,
        payload,
        source_name="semantic_ir_lifecycle.csv",
    )
    reports = (
        commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id),
        commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id),
        commit_csv_native_storage_artifacts(fs.root, manifest.csv_id),
        commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id),
        commit_csv_interpole_timeline_report(fs.root, manifest.csv_id),
        commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id),
        commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id),
        commit_csv_kernel_readiness_contract_report(
            fs.root,
            manifest.csv_id,
            chunk_size=chunk_size,
        ),
        commit_csv_native_scan_kernel_prototype_report(
            fs.root,
            manifest.csv_id,
            chunk_size=chunk_size,
        ),
        commit_csv_native_row_anchor_kernel_report(
            fs.root,
            manifest.csv_id,
            chunk_size=chunk_size,
        ),
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
            evidence_names=(
                "original_byte_identity",
                "storage_adapter_replay",
                "browser_monitor_replay",
            ),
        ),
    )


def _candidate(fs: TDSFileSystem, csv_id: str):
    candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        csv_id,
        _declarations(),
        explicit_opt_in=True,
    )
    assert candidate.ok
    return candidate


def _authorization(
    *,
    authorization_id: str = "auth_validation_001",
    actor_id: str = "semantic_reviewer_001",
    scope: str = "validate_proposition",
    reference: str = "review-ticket:SEM-001",
    explicit: bool = True,
) -> CSVSemanticIRTransitionAuthorization:
    return CSVSemanticIRTransitionAuthorization(
        authorization_id=authorization_id,
        actor_id=actor_id,
        authority_scope=scope,
        authorization_reference=reference,
        explicit_authorization=explicit,
    )


def _request(
    *,
    transition_id: str = "transition_001",
    proposition_id: str = "customer_identifier_role",
    from_state: str = "proposed",
    to_state: str = "validated",
    reason: str = "Human reviewer confirmed the explicit proposition against the referenced evidence.",
    authorization: CSVSemanticIRTransitionAuthorization | None = None,
) -> CSVSemanticIRTransitionRequest:
    return CSVSemanticIRTransitionRequest(
        transition_id=transition_id,
        proposition_id=proposition_id,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        authorization=authorization or _authorization(),
    )


def test_version_351_semantic_ir_lifecycle_contract():
    assert __version__ == "3.5.3.post1"
    assert CSV_SEMANTIC_IR_LIFECYCLE_VERSION == "1.0"
    assert CSV_SEMANTIC_IR_LIFECYCLE_PAYLOAD_BYTE_LIMIT == 524_288
    assert CSV_SEMANTIC_IR_MAX_TRANSITIONS == 256
    assert CSV_SEMANTIC_IR_LIFECYCLE_STATES == (
        "proposed",
        "validated",
        "contested",
    )
    assert CSV_SEMANTIC_IR_ALLOWED_TRANSITIONS == (
        ("proposed", "validated"),
        ("proposed", "contested"),
        ("validated", "contested"),
    )
    assert CSV_SEMANTIC_IR_TRANSITION_AUTHORITY_SCOPES == (
        "validate_proposition",
        "contest_proposition",
    )
    assert "formal_ir_committed" in CSV_SEMANTIC_IR_LIFECYCLE_CONTRACT_KEYS
    assert "committed_state_admitted" in CSV_SEMANTIC_IR_LIFECYCLE_CONTRACT_KEYS


def test_proposed_to_validated_is_explicit_deterministic_and_read_only():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    before_keys = set(fs.root._entries.keys())
    request = _request()

    first = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        request,
    )
    second = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        request,
    )

    assert first.ok is True
    assert second.ok is True
    assert first.status == "semantic_ir_lifecycle_ready"
    assert first.lifecycle_fingerprint == second.lifecycle_fingerprint
    assert first.lifecycle_fingerprint == csv_semantic_ir_lifecycle_fingerprint(first)
    assert first.current_states[0].state == "validated"
    assert first.current_states[0].transition_count == 1
    assert first.history[0].explicit_authorization is True
    assert first.history[0].automatic_transition is False
    assert first.history[0].semantic_commitment is False
    assert first.history[0].transition_fingerprint == csv_semantic_ir_transition_fingerprint(
        first.history[0]
    )
    assert (
        first.history[0].authorization_fingerprint
        == csv_semantic_ir_transition_authorization_fingerprint(
            first.history[0].authorization
        )
    )
    assert first.tds_artifact_writes == 0
    assert first.directory_state_unchanged is True
    assert set(fs.root._entries.keys()) == before_keys


def test_proposed_to_contested_is_admitted_with_contestation_scope():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    request = _request(
        transition_id="transition_contest_001",
        proposition_id="dataset_domain",
        to_state="contested",
        reason="A human reviewer supplied unresolved counterevidence.",
        authorization=_authorization(
            authorization_id="auth_contest_001",
            scope="contest_proposition",
            reference="review-ticket:SEM-002",
        ),
    )

    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        request,
    )

    assert lifecycle.ok is True
    states = {item.proposition_id: item.state for item in lifecycle.current_states}
    assert states["dataset_domain"] == "contested"
    assert states["customer_identifier_role"] == "proposed"
    assert lifecycle.history[0].to_state == "contested"


def test_validated_to_contested_builds_immutable_two_step_lineage():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    validated = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    )
    contested_request = _request(
        transition_id="transition_002",
        from_state="validated",
        to_state="contested",
        reason="A second human reviewer found conflicting evidence.",
        authorization=_authorization(
            authorization_id="auth_contest_002",
            actor_id="semantic_reviewer_002",
            scope="contest_proposition",
            reference="review-ticket:SEM-003",
        ),
    )

    contested = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        contested_request,
        source_lifecycle=validated,
    )

    assert validated.ok is True
    assert contested.ok is True
    assert len(validated.history) == 1
    assert len(contested.history) == 2
    assert validated.current_states[0].state == "validated"
    assert contested.current_states[0].state == "contested"
    assert contested.history[0] == validated.history[0]
    assert (
        contested.history[1].predecessor_fingerprint
        == contested.history[0].transition_fingerprint
    )
    assert (
        contested.history[1].proposition_predecessor_fingerprint
        == contested.history[0].transition_fingerprint
    )


def test_lifecycle_serialization_validates_complete_lineage():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    )

    validation = validate_csv_semantic_ir_lifecycle(
        lifecycle.to_dict(),
        source_candidate=candidate.to_dict(),
    )

    assert validation.ok is True
    assert validation.status == "semantic_ir_lifecycle_valid"
    assert validation.source_lifecycle_fingerprint == lifecycle.lifecycle_fingerprint
    assert validation.recomputed_lifecycle_fingerprint == lifecycle.lifecycle_fingerprint
    assert validation.source_payload_bytes == lifecycle.payload_bytes
    assert validation.recomputed_payload_bytes == lifecycle.payload_bytes


def test_lifecycle_replay_reconstructs_every_transition_from_current_evidence():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    first = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    )
    second = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(
            transition_id="transition_002",
            from_state="validated",
            to_state="contested",
            reason="Conflicting human review requires contestation.",
            authorization=_authorization(
                authorization_id="auth_contest_002",
                scope="contest_proposition",
                reference="review-ticket:SEM-004",
            ),
        ),
        source_lifecycle=first,
    )
    before_keys = set(fs.root._entries.keys())

    replay = replay_csv_semantic_ir_lifecycle(
        fs.root,
        manifest.csv_id,
        candidate.to_dict(),
        second.to_dict(),
    )

    assert replay.ok is True
    assert replay.status == "semantic_ir_lifecycle_replay_valid"
    assert replay.source_lifecycle_fingerprint == replay.replay_lifecycle_fingerprint
    assert replay.source_candidate_fingerprint == replay.replay_candidate_fingerprint
    assert replay.mismatched_fields == ()
    assert replay.tds_artifact_writes == 0
    assert set(fs.root._entries.keys()) == before_keys


def test_transition_requires_explicit_authorization():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    request = _request(authorization=_authorization(explicit=False))

    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        request,
    )

    assert lifecycle.ok is False
    assert lifecycle.status == "semantic_ir_lifecycle_blocked"
    assert lifecycle.history == ()
    assert any("explicit_authorization_required" in error for error in lifecycle.errors)
    assert lifecycle.formal_ir_committed is False


def test_transition_authority_scope_must_match_target_state():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    request = _request(
        authorization=_authorization(scope="contest_proposition")
    )

    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        request,
    )

    assert lifecycle.ok is False
    assert any("authorization_scope_mismatch" in error for error in lifecycle.errors)


def test_committed_superseded_and_reverse_transitions_remain_deferred():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)

    for index, (from_state, to_state, scope) in enumerate(
        (
            ("proposed", "committed", "validate_proposition"),
            ("proposed", "superseded", "validate_proposition"),
            ("validated", "proposed", "validate_proposition"),
            ("contested", "validated", "validate_proposition"),
        ),
        start=1,
    ):
        lifecycle = prepare_csv_semantic_ir_transition(
            fs.root,
            manifest.csv_id,
            candidate,
            _request(
                transition_id=f"forbidden_transition_{index}",
                from_state=from_state,
                to_state=to_state,
                authorization=_authorization(
                    authorization_id=f"forbidden_auth_{index}",
                    scope=scope,
                    reference=f"review-ticket:FORBIDDEN-{index}",
                ),
            ),
        )
        assert lifecycle.ok is False
        assert any("transition_not_admitted" in error for error in lifecycle.errors)
        assert lifecycle.formal_ir_committed is False
        assert lifecycle.committed_state_admitted is False
        assert lifecycle.superseded_state_admitted is False


def test_transition_rejects_unknown_proposition_and_wrong_predecessor_state():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)

    unknown = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(proposition_id="not_in_candidate"),
    )
    wrong_state = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(from_state="validated", to_state="contested", authorization=_authorization(
            scope="contest_proposition"
        )),
    )

    assert unknown.ok is False
    assert any("proposition_not_found" in error for error in unknown.errors)
    assert wrong_state.ok is False
    assert any("predecessor_state_mismatch" in error for error in wrong_state.errors)


def test_duplicate_transition_id_is_rejected_without_mutating_prior_history():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    first = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    )

    duplicate = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(
            from_state="validated",
            to_state="contested",
            authorization=_authorization(
                authorization_id="auth_contest_duplicate",
                scope="contest_proposition",
                reference="review-ticket:SEM-DUPLICATE",
            ),
        ),
        source_lifecycle=first,
    )

    assert duplicate.ok is False
    assert any("duplicate_transition_id" in error for error in duplicate.errors)
    assert duplicate.history == first.history
    assert duplicate.current_states == first.current_states


def test_serialized_lifecycle_rejects_nested_history_and_authorization_tamper():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    )
    payload = lifecycle.to_dict()
    payload["history"][0]["reason"] = "Tampered reason"
    payload["history"][0]["authorization"]["actor_id"] = "tampered_actor"

    validation = validate_csv_semantic_ir_lifecycle(
        payload,
        source_candidate=candidate,
    )

    assert validation.ok is False
    assert "semantic_ir_lifecycle_fingerprint_mismatch" in validation.errors
    assert any("authorization_fingerprint_mismatch" in error for error in validation.errors)
    assert any("transition_fingerprint_mismatch" in error for error in validation.errors)


def test_serialized_lifecycle_rejects_missing_nested_contract_fields():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    payload = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    ).to_dict()
    payload["current_states"][0].pop("state")
    payload["history"][0].pop("predecessor_fingerprint")
    payload["history"][0]["authorization"].pop("authorization_reference")

    validation = validate_csv_semantic_ir_lifecycle(
        payload,
        source_candidate=candidate,
    )

    assert validation.ok is False
    assert "0:state" in validation.missing_state_keys
    assert "0:predecessor_fingerprint" in validation.missing_record_keys
    assert "0:authorization_reference" in validation.missing_authorization_keys


def test_lifecycle_validation_rejects_current_state_and_predecessor_tamper():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    payload = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    ).to_dict()
    payload["current_states"][0]["state"] = "contested"
    payload["history"][0]["predecessor_fingerprint"] = "0" * 64

    validation = validate_csv_semantic_ir_lifecycle(
        payload,
        source_candidate=candidate,
    )

    assert validation.ok is False
    assert any("predecessor_fingerprint_mismatch" in error for error in validation.errors)
    assert any("current_state_mismatch" in error for error in validation.errors)


def test_transition_rejects_tampered_source_candidate():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    payload = candidate.to_dict()
    payload["propositions"][0]["object_value"] = "TamperedSemanticValue"

    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        payload,
        _request(),
    )

    assert lifecycle.ok is False
    assert any("source_candidate" in error for error in lifecycle.errors)
    assert lifecycle.history == ()


def test_transition_and_replay_fail_closed_after_csv_drift():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    )
    fs.root.write_text(
        artifact_keys(manifest.csv_id)["raw"],
        "id,name,score\n1,Tampered,0\n",
        overwrite=True,
        provenance="REAL",
    )

    next_transition = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(
            transition_id="transition_after_drift",
            proposition_id="dataset_domain",
        ),
        source_lifecycle=lifecycle,
    )
    replay = replay_csv_semantic_ir_lifecycle(
        fs.root,
        manifest.csv_id,
        candidate,
        lifecycle,
    )

    assert next_transition.ok is False
    assert any("source_candidate_replay" in error for error in next_transition.errors)
    assert replay.ok is False
    assert replay.status == "semantic_ir_lifecycle_replay_blocked"
    assert any("source_candidate_replay" in error for error in replay.errors)


def test_lifecycle_payload_bound_fails_closed():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)

    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(reason="R" * 1800),
        payload_byte_limit=1024,
    )

    assert lifecycle.ok is False
    assert lifecycle.status == "semantic_ir_lifecycle_blocked"
    assert lifecycle.payload_bytes > lifecycle.payload_byte_limit
    assert any(
        error.startswith("semantic_ir_lifecycle_payload_too_large:")
        for error in lifecycle.errors
    )


def test_lifecycle_boundary_flags_cannot_be_promoted_by_serialized_tamper():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    payload = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    ).to_dict()
    payload["formal_ir_committed"] = True
    payload["semantic_conclusions_committed"] = True
    payload["automatic_lifecycle_transitions"] = True
    payload["native_storage_writes"] = True

    validation = validate_csv_semantic_ir_lifecycle(
        payload,
        source_candidate=candidate,
    )

    assert validation.ok is False
    for field_name in (
        "formal_ir_committed",
        "semantic_conclusions_committed",
        "automatic_lifecycle_transitions",
        "native_storage_writes",
    ):
        assert (
            f"semantic_ir_lifecycle_forbidden_boundary_true:{field_name}"
            in validation.errors
        )


def test_source_lifecycle_candidate_binding_cannot_be_reused_for_another_candidate():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _request(),
    )
    other_candidate = prepare_csv_semantic_ir_candidate(
        fs.root,
        manifest.csv_id,
        (_declarations()[0],),
        explicit_opt_in=True,
    )
    assert other_candidate.ok

    blocked = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        other_candidate,
        _request(
            transition_id="transition_other_candidate",
            proposition_id="customer_identifier_role",
            from_state="validated",
            to_state="contested",
            authorization=_authorization(
                authorization_id="auth_other_candidate",
                scope="contest_proposition",
                reference="review-ticket:SEM-OTHER",
            ),
        ),
        source_lifecycle=lifecycle,
    )

    assert blocked.ok is False
    assert any("source_lifecycle" in error for error in blocked.errors)


def test_mapping_request_missing_fields_fails_closed():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    request = _request().to_dict()
    request.pop("reason")
    request["authorization"].pop("authorization_reference")

    lifecycle = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        request,
    )

    assert lifecycle.ok is False
    assert "transition_request_contract_missing:reason" in lifecycle.errors
    assert (
        "transition_authorization_contract_missing:authorization_reference"
        in lifecycle.errors
    )

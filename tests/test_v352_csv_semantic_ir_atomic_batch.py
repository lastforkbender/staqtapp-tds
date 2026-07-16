from __future__ import annotations

from dataclasses import replace

import pytest

from staqtapp_tds import __version__
from staqtapp_tds.tds_filesystem import TDSFileSystem
from staqtapp_tds.csv_layer import (
    CSV_SEMANTIC_IR_BATCH_AUTHORITY_SCOPES,
    CSV_SEMANTIC_IR_BATCH_RECEIPT_CONTRACT_KEYS,
    CSV_SEMANTIC_IR_MAX_BATCH_TRANSITIONS,
    CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT,
    CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION,
    CSVSemanticIRBatchAuthorization,
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
    csv_semantic_ir_batch_authorization_fingerprint,
    csv_semantic_ir_batch_receipt_fingerprint,
    csv_semantic_ir_transition_batch_fingerprint,
    csv_semantic_ir_transition_request_fingerprint,
    import_csv_bytes,
    prepare_csv_semantic_ir_candidate,
    prepare_csv_semantic_ir_transition,
    prepare_csv_semantic_ir_transition_batch,
    replay_csv_semantic_ir_transition_batch,
    validate_csv_semantic_ir_transition_batch,
)
from staqtapp_tds.csv_layer.semantic_ir import _finalize_candidate_integrity
from staqtapp_tds.csv_layer.semantic_ir_lifecycle import _finalize_lifecycle
import staqtapp_tds.csv_layer.semantic_ir_lifecycle_batch as batch_module


def _ready_csv(
    fs: TDSFileSystem,
    payload: bytes = b"id,name,score\n1,Ada,99\n2,Grace,98\n3,Katherine,97\n",
    *,
    chunk_size: int | None = 7,
):
    manifest = import_csv_bytes(
        fs.root,
        payload,
        source_name="semantic_ir_atomic_batch.csv",
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


def _transition_authorization(
    authorization_id: str,
    scope: str,
    *,
    actor_id: str = "semantic_reviewer_001",
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
    transition_id: str,
    proposition_id: str,
    to_state: str,
    authorization_id: str,
    *,
    from_state: str = "proposed",
    reason: str = "Human reviewer accepted the explicit transition against current evidence.",
    scope: str | None = None,
) -> CSVSemanticIRTransitionRequest:
    resolved_scope = scope or (
        "validate_proposition" if to_state == "validated" else "contest_proposition"
    )
    return CSVSemanticIRTransitionRequest(
        transition_id=transition_id,
        proposition_id=proposition_id,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        authorization=_transition_authorization(
            authorization_id,
            resolved_scope,
            reference=f"review-ticket:{transition_id}",
        ),
    )


def _requests() -> tuple[CSVSemanticIRTransitionRequest, ...]:
    return (
        _request(
            "transition_001",
            "customer_identifier_role",
            "validated",
            "auth_transition_001",
        ),
        _request(
            "transition_002",
            "dataset_domain",
            "contested",
            "auth_transition_002",
        ),
    )


def _batch_authorization(
    *,
    authorization_id: str = "batch_auth_001",
    scope: str = "review_transition_batch",
    explicit: bool = True,
) -> CSVSemanticIRBatchAuthorization:
    return CSVSemanticIRBatchAuthorization(
        authorization_id=authorization_id,
        actor_id="batch_reviewer_001",
        authority_scope=scope,
        authorization_reference="batch-review-ticket:BATCH-001",
        explicit_authorization=explicit,
    )


def _receipt(fs: TDSFileSystem, csv_id: str, candidate, requests=None, **kwargs):
    return prepare_csv_semantic_ir_transition_batch(
        fs.root,
        csv_id,
        candidate,
        requests or _requests(),
        batch_id=kwargs.pop("batch_id", "batch_001"),
        batch_authorization=kwargs.pop(
            "batch_authorization", _batch_authorization()
        ),
        **kwargs,
    )


def test_version_352_atomic_batch_contract():
    assert __version__ == "3.5.3.post1"
    assert CSV_SEMANTIC_IR_TRANSITION_BATCH_VERSION == "1.0"
    assert CSV_SEMANTIC_IR_MAX_BATCH_TRANSITIONS == 32
    assert CSV_SEMANTIC_IR_TRANSITION_BATCH_PAYLOAD_BYTE_LIMIT == 524_288
    assert CSV_SEMANTIC_IR_BATCH_AUTHORITY_SCOPES == ("review_transition_batch",)
    assert "partial_acceptance" in CSV_SEMANTIC_IR_BATCH_RECEIPT_CONTRACT_KEYS
    assert "native_storage_hot_path_touched" in CSV_SEMANTIC_IR_BATCH_RECEIPT_CONTRACT_KEYS


def test_mixed_batch_is_deterministic_atomic_and_read_only():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    before_keys = set(fs.root._entries.keys())

    first = _receipt(fs, manifest.csv_id, candidate)
    second = _receipt(fs, manifest.csv_id, candidate)

    assert first.ok is True
    assert second.ok is True
    assert first.receipt_fingerprint == second.receipt_fingerprint
    assert first.receipt_fingerprint == csv_semantic_ir_batch_receipt_fingerprint(first)
    assert first.batch.batch_fingerprint == csv_semantic_ir_transition_batch_fingerprint(
        first.batch
    )
    assert first.batch.batch_authorization_fingerprint == (
        csv_semantic_ir_batch_authorization_fingerprint(first.batch.batch_authorization)
    )
    assert all(
        item.request_fingerprint
        == csv_semantic_ir_transition_request_fingerprint(item.request)
        for item in first.batch.items
    )
    states = {
        state.proposition_id: state.state
        for state in first.result_lifecycle.current_states
    }
    assert states == {
        "customer_identifier_role": "validated",
        "dataset_domain": "contested",
    }
    assert first.result_transition_fingerprints == tuple(
        record.transition_fingerprint
        for record in first.result_lifecycle.history
    )
    assert first.batch_accepted is True
    assert first.all_or_nothing is True
    assert first.partial_acceptance is False
    assert first.tds_artifact_writes == 0
    assert first.directory_state_unchanged is True
    assert set(fs.root._entries.keys()) == before_keys


def test_batch_result_matches_equivalent_sequential_transitions():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    requests = _requests()

    batch = _receipt(fs, manifest.csv_id, candidate, requests)
    first = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        requests[0],
    )
    sequential = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        requests[1],
        source_lifecycle=first,
    )

    assert batch.ok is True
    assert sequential.ok is True
    assert batch.result_lifecycle == sequential
    assert batch.result_lifecycle_fingerprint == sequential.lifecycle_fingerprint


def test_batch_validation_and_replay_reconstruct_complete_receipt():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    receipt = _receipt(fs, manifest.csv_id, candidate)

    validation = validate_csv_semantic_ir_transition_batch(
        receipt.to_dict(),
        source_candidate=candidate,
    )
    replay = replay_csv_semantic_ir_transition_batch(
        fs.root,
        manifest.csv_id,
        candidate,
        receipt.to_dict(),
    )

    assert validation.ok is True
    assert validation.source_receipt_fingerprint == receipt.receipt_fingerprint
    assert validation.recomputed_receipt_fingerprint == receipt.receipt_fingerprint
    assert replay.ok is True
    assert replay.source_receipt_fingerprint == replay.replay_receipt_fingerprint
    assert replay.source_batch_fingerprint == replay.replay_batch_fingerprint
    assert replay.source_result_lifecycle_fingerprint == (
        replay.replay_result_lifecycle_fingerprint
    )
    assert replay.mismatched_fields == ()


def test_one_invalid_item_blocks_every_item_without_creating_lifecycle():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    requests = (
        _requests()[0],
        _request(
            "transition_invalid",
            "not_in_candidate",
            "contested",
            "auth_invalid",
        ),
    )

    receipt = _receipt(fs, manifest.csv_id, candidate, requests)

    assert receipt.ok is False
    assert receipt.status == "semantic_ir_transition_batch_blocked"
    assert receipt.batch_accepted is False
    assert receipt.result_transition_fingerprints == ()
    assert receipt.result_lifecycle is None
    assert any("proposition_not_found" in error for error in receipt.errors)


def test_invalid_item_preserves_supplied_lifecycle_exactly():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    prior = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        _requests()[0],
    )
    requests = (
        _request(
            "transition_valid_002",
            "dataset_domain",
            "contested",
            "auth_valid_002",
        ),
        _request(
            "transition_invalid_003",
            "missing_proposition",
            "validated",
            "auth_invalid_003",
        ),
    )

    receipt = _receipt(
        fs,
        manifest.csv_id,
        candidate,
        requests,
        source_lifecycle=prior,
    )

    assert receipt.ok is False
    assert receipt.result_lifecycle == prior
    assert receipt.result_lifecycle_fingerprint == prior.lifecycle_fingerprint
    assert receipt.result_transition_fingerprints == ()
    assert len(receipt.result_lifecycle.history) == 1


@pytest.mark.parametrize(
    ("requests", "error_token"),
    (
        (
            (
                _request("duplicate_id", "customer_identifier_role", "validated", "auth_a"),
                _request("duplicate_id", "dataset_domain", "contested", "auth_b"),
            ),
            "duplicate_transition_id",
        ),
        (
            (
                _request("transition_a", "customer_identifier_role", "validated", "auth_a"),
                _request("transition_b", "customer_identifier_role", "contested", "auth_b"),
            ),
            "duplicate_proposition_id",
        ),
        (
            (
                _request("transition_a", "customer_identifier_role", "validated", "same_auth"),
                _request("transition_b", "dataset_domain", "contested", "same_auth"),
            ),
            "duplicate_authorization_id",
        ),
    ),
)
def test_batch_duplicate_id_classes_fail_closed(requests, error_token):
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)

    receipt = _receipt(fs, manifest.csv_id, candidate, requests)

    assert receipt.ok is False
    assert receipt.result_lifecycle is None
    assert any(error_token in error for error in receipt.errors)


def test_batch_rejects_collisions_with_source_lifecycle_history():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    prior_request = _requests()[0]
    prior = prepare_csv_semantic_ir_transition(
        fs.root,
        manifest.csv_id,
        candidate,
        prior_request,
    )
    collision = _request(
        prior_request.transition_id,
        "dataset_domain",
        "contested",
        prior_request.authorization.authorization_id,
    )

    receipt = _receipt(
        fs,
        manifest.csv_id,
        candidate,
        (collision,),
        source_lifecycle=prior,
    )

    assert receipt.ok is False
    assert receipt.result_lifecycle == prior
    assert any("duplicate_transition_id_in_source_lifecycle" in e for e in receipt.errors)
    assert any("duplicate_authorization_id_in_source_lifecycle" in e for e in receipt.errors)


def test_all_requests_are_preflighted_against_batch_entry_state():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    requests = (
        _request(
            "transition_validate",
            "customer_identifier_role",
            "validated",
            "auth_validate",
        ),
        _request(
            "transition_contest_after_validate",
            "customer_identifier_role",
            "contested",
            "auth_contest",
            from_state="validated",
        ),
    )

    receipt = _receipt(fs, manifest.csv_id, candidate, requests)

    assert receipt.ok is False
    assert receipt.result_lifecycle is None
    assert any("duplicate_proposition_id" in error for error in receipt.errors)
    assert any("predecessor_state_mismatch" in error for error in receipt.errors)


def test_batch_and_item_authorization_scopes_are_independently_enforced():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)

    wrong_batch_scope = _receipt(
        fs,
        manifest.csv_id,
        candidate,
        batch_authorization=_batch_authorization(scope="validate_proposition"),
    )
    wrong_item_scope = _receipt(
        fs,
        manifest.csv_id,
        candidate,
        (
            _request(
                "wrong_scope",
                "customer_identifier_role",
                "validated",
                "wrong_scope_auth",
                scope="contest_proposition",
            ),
        ),
    )
    no_batch_authorization = _receipt(
        fs,
        manifest.csv_id,
        candidate,
        batch_authorization=_batch_authorization(explicit=False),
    )

    assert wrong_batch_scope.ok is False
    assert any("transition_batch_authorization_invalid" in e for e in wrong_batch_scope.errors)
    assert wrong_item_scope.ok is False
    assert any("authorization_scope_mismatch" in e for e in wrong_item_scope.errors)
    assert no_batch_authorization.ok is False
    assert any("explicit_authorization_required" in e for e in no_batch_authorization.errors)


def test_committed_and_superseded_remain_outside_batch_contract():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)

    for index, state in enumerate(("committed", "superseded"), start=1):
        receipt = _receipt(
            fs,
            manifest.csv_id,
            candidate,
            (
                _request(
                    f"forbidden_{index}",
                    "customer_identifier_role",
                    state,
                    f"forbidden_auth_{index}",
                    scope="validate_proposition",
                ),
            ),
            batch_id=f"forbidden_batch_{index}",
        )
        assert receipt.ok is False
        assert any("transition_not_admitted" in error for error in receipt.errors)
        assert receipt.formal_ir_committed is False
        assert receipt.committed_state_admitted is False
        assert receipt.superseded_state_admitted is False


def test_validation_detects_order_batch_authorization_and_request_tampering():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    receipt = _receipt(fs, manifest.csv_id, candidate)

    reordered = receipt.to_dict()
    reordered["batch"]["items"].reverse()
    reordered_validation = validate_csv_semantic_ir_transition_batch(
        reordered,
        source_candidate=candidate,
    )

    authorization_tamper = receipt.to_dict()
    authorization_tamper["batch"]["batch_authorization"]["actor_id"] = "tampered_actor"
    authorization_validation = validate_csv_semantic_ir_transition_batch(
        authorization_tamper,
        source_candidate=candidate,
    )

    request_tamper = receipt.to_dict()
    request_tamper["batch"]["items"][0]["request"]["reason"] = "Tampered reason"
    request_validation = validate_csv_semantic_ir_transition_batch(
        request_tamper,
        source_candidate=candidate,
    )

    assert reordered_validation.ok is False
    assert any("fingerprint_mismatch" in e for e in reordered_validation.errors)
    assert authorization_validation.ok is False
    assert any("fingerprint_mismatch" in e for e in authorization_validation.errors)
    assert request_validation.ok is False
    assert any("fingerprint_mismatch" in e for e in request_validation.errors)


def test_validation_detects_result_lifecycle_and_receipt_tampering():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    payload = _receipt(fs, manifest.csv_id, candidate).to_dict()
    payload["result_lifecycle"]["current_states"][0]["state"] = "contested"
    payload["partial_acceptance"] = True

    validation = validate_csv_semantic_ir_transition_batch(
        payload,
        source_candidate=candidate,
    )

    assert validation.ok is False
    assert "transition_batch_receipt_fingerprint_mismatch" in validation.errors
    assert "transition_batch_atomicity_boundary_invalid" in validation.errors
    assert any("result_lifecycle" in error for error in validation.errors)


def test_validation_rejects_missing_nested_contract_fields():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    payload = _receipt(fs, manifest.csv_id, candidate).to_dict()
    payload.pop("all_or_nothing")
    payload["batch"].pop("raw_sha256")
    payload["batch"]["batch_authorization"].pop("authorization_reference")
    payload["batch"]["items"][0].pop("request_fingerprint")
    payload["batch"]["items"][0]["request"].pop("reason")
    payload["batch"]["items"][0]["request"]["authorization"].pop("actor_id")

    validation = validate_csv_semantic_ir_transition_batch(
        payload,
        source_candidate=candidate,
    )

    assert validation.ok is False
    assert "all_or_nothing" in validation.missing_receipt_keys
    assert "raw_sha256" in validation.missing_batch_keys
    assert "authorization_reference" in validation.missing_batch_authorization_keys
    assert "0:request_fingerprint" in validation.missing_item_keys
    assert "0:reason" in validation.missing_request_keys
    assert "0:actor_id" in validation.missing_transition_authorization_keys


def test_csv_drift_blocks_new_batch_and_replay():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    receipt = _receipt(fs, manifest.csv_id, candidate)
    fs.root.write_text(
        artifact_keys(manifest.csv_id)["raw"],
        "id,name,score\n1,Tampered,0\n",
        overwrite=True,
        provenance="REAL",
    )

    next_batch = _receipt(
        fs,
        manifest.csv_id,
        candidate,
        (_requests()[0],),
        batch_id="batch_after_drift",
    )
    replay = replay_csv_semantic_ir_transition_batch(
        fs.root,
        manifest.csv_id,
        candidate,
        receipt,
    )

    assert next_batch.ok is False
    assert any("source_candidate_replay" in error for error in next_batch.errors)
    assert replay.ok is False
    assert any("replay_status_mismatch" in error for error in replay.errors)
    assert any("receipt_fingerprint_mismatch" in error for error in replay.errors)


def test_batch_count_and_payload_bounds_fail_closed():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    many = tuple(
        _request(
            f"transition_{index:03d}",
            "customer_identifier_role" if index % 2 else "dataset_domain",
            "validated" if index % 2 else "contested",
            f"auth_{index:03d}",
        )
        for index in range(1, CSV_SEMANTIC_IR_MAX_BATCH_TRANSITIONS + 2)
    )

    count_blocked = _receipt(fs, manifest.csv_id, candidate, many)
    payload_blocked = _receipt(
        fs,
        manifest.csv_id,
        candidate,
        payload_byte_limit=1024,
    )

    assert count_blocked.ok is False
    assert any("transition_batch_count_exceeded" in e for e in count_blocked.errors)
    assert payload_blocked.ok is False
    assert any("payload_too_large" in e for e in payload_blocked.errors)


def test_candidate_validation_and_evidence_replay_execute_once_per_batch(monkeypatch):
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    counts = {"validate": 0, "replay": 0}
    original_validate = batch_module.validate_csv_semantic_ir_candidate
    original_replay = batch_module.replay_csv_semantic_ir_candidate

    def counted_validate(*args, **kwargs):
        counts["validate"] += 1
        return original_validate(*args, **kwargs)

    def counted_replay(*args, **kwargs):
        counts["replay"] += 1
        return original_replay(*args, **kwargs)

    monkeypatch.setattr(
        batch_module,
        "validate_csv_semantic_ir_candidate",
        counted_validate,
    )
    monkeypatch.setattr(
        batch_module,
        "replay_csv_semantic_ir_candidate",
        counted_replay,
    )

    receipt = _receipt(fs, manifest.csv_id, candidate)

    assert receipt.ok is True
    assert counts == {"validate": 1, "replay": 1}


def test_v351_serialized_candidate_and_lifecycle_are_accepted_compatibly():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    current_candidate = _candidate(fs, manifest.csv_id)
    legacy_candidate = _finalize_candidate_integrity(
        replace(
            current_candidate,
            suite_release_version="3.5.1",
            candidate_fingerprint="",
            payload_bytes=0,
        )
    )
    first_receipt = _receipt(
        fs,
        manifest.csv_id,
        legacy_candidate,
        (_requests()[0],),
        batch_id="legacy_seed_batch",
        batch_authorization=_batch_authorization(
            authorization_id="legacy_seed_batch_auth"
        ),
    )
    assert first_receipt.ok is True
    legacy_lifecycle = _finalize_lifecycle(
        replace(
            first_receipt.result_lifecycle,
            suite_release_version="3.5.1",
            lifecycle_fingerprint="",
            payload_bytes=0,
        )
    )

    receipt = _receipt(
        fs,
        manifest.csv_id,
        legacy_candidate.to_dict(),
        (
            _request(
                "legacy_transition_002",
                "dataset_domain",
                "contested",
                "legacy_auth_002",
            ),
        ),
        batch_id="legacy_followup_batch",
        batch_authorization=_batch_authorization(
            authorization_id="legacy_followup_batch_auth"
        ),
        source_lifecycle=legacy_lifecycle.to_dict(),
    )

    assert legacy_candidate.ok is True
    assert legacy_lifecycle.ok is True
    assert receipt.ok is True
    assert receipt.result_lifecycle.suite_release_version == "3.5.3.post1"
    assert len(receipt.result_lifecycle.history) == 2
    assert any("compatible_release_replay:3.5.1->3.5.3" in w for w in receipt.warnings)


def test_batch_receipt_keeps_all_semantic_and_storage_boundaries_closed():
    fs = TDSFileSystem("root")
    manifest = _ready_csv(fs)
    candidate = _candidate(fs, manifest.csv_id)
    receipt = _receipt(fs, manifest.csv_id, candidate)

    assert receipt.ok is True
    assert receipt.csv_artifact_mutation is False
    assert receipt.retroactive_csv_artifact_mutation is False
    assert receipt.interpole_mutation is False
    assert receipt.native_storage_writes is False
    assert receipt.native_storage_hot_path_touched is False
    assert receipt.native_storage_locks_controlled is False
    assert receipt.native_c_storage_engine_changed is False
    assert receipt.per_row_writes is False
    assert receipt.per_cell_writes is False
    assert receipt.semantic_artifact_persisted is False
    assert receipt.formal_ir_committed is False
    assert receipt.semantic_conclusions_committed is False
    assert receipt.committed_state_admitted is False
    assert receipt.superseded_state_admitted is False
    assert receipt.automatic_lifecycle_transitions is False

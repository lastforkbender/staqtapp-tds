import pytest

from staqtapp_tds.drivers import (
    DriverManifest,
    DriverRegistry,
    DriverState,
    RegistryError,
    SignaturePolicy,
    SignatureVerdict,
    TraceEvidence,
    rank_traces,
    sign_payload,
    validate_manifest,
)


def test_driver_manifest_canonical_payload_is_deterministic():
    a = DriverManifest(
        driver_id="SearchPolicies",
        version=1,
        kind="search",
        capabilities=("manifest.read", "registry.scan"),
        adapters=("scorer.trace_rank.v1", "predicate.capability_vector.v1"),
    )
    b = DriverManifest(
        driver_id="SearchPolicies",
        version=1,
        kind="search",
        capabilities=("registry.scan", "manifest.read"),
        adapters=("predicate.capability_vector.v1", "scorer.trace_rank.v1"),
    )
    validate_manifest(a)
    assert a.canonical_payload() == b.canonical_payload()


@pytest.mark.parametrize(
    "manifest,error",
    [
        (DriverManifest(driver_id="bad id", version=1, kind="search", capabilities=("registry.scan",)), "driver_id"),
        (DriverManifest(driver_id="ok", version=0, kind="search", capabilities=("registry.scan",)), "version"),
        (DriverManifest(driver_id="ok", version=1, kind="unknown", capabilities=("registry.scan",)), "kind"),
        (DriverManifest(driver_id="ok", version=1, kind="search", capabilities=()), "capability"),
    ],
)
def test_driver_manifest_validation_fails_closed(manifest, error):
    with pytest.raises(ValueError, match=error):
        validate_manifest(manifest)


def test_signature_policy_accepts_only_known_valid_unrevoked_signatures():
    policy = SignaturePolicy({"admin": b"secret"})
    payload = b"driver payload"
    signature = sign_payload(payload, signer="admin", secret=b"secret")

    assert policy.evaluate(payload, None) is SignatureVerdict.UNSIGNED
    assert policy.evaluate(payload, "tds-sig-v1:admin:bad") is SignatureVerdict.BAD_SIGNATURE
    assert policy.evaluate(payload, sign_payload(payload, signer="unknown", secret=b"x")) is SignatureVerdict.UNKNOWN_SIGNER
    assert policy.evaluate(payload, signature) is SignatureVerdict.ACCEPT

    policy.revoke(signature)
    assert policy.evaluate(payload, signature) is SignatureVerdict.REVOKED


def test_registry_requires_candidate_tests_signature_before_activation():
    policy = SignaturePolicy({"admin": b"secret"})
    registry = DriverRegistry(policy)
    manifest = DriverManifest(
        driver_id="SearchPolicies",
        version=1,
        kind="search",
        capabilities=("registry.scan", "manifest.read"),
    )

    registry.add_candidate(manifest)
    with pytest.raises(RegistryError, match="test report"):
        registry.approve("SearchPolicies")
    with pytest.raises(RegistryError, match="only signed"):
        registry.activate("SearchPolicies")

    registry.add_candidate(manifest, test_report_hash="sha256:tests-pass")
    record = registry.approve("SearchPolicies")
    assert record.state is DriverState.APPROVED

    bad_sig = sign_payload(manifest.canonical_payload(), signer="admin", secret=b"wrong")
    with pytest.raises(RegistryError, match="bad_signature"):
        registry.attach_signature("SearchPolicies", bad_sig)

    sig = sign_payload(manifest.canonical_payload(), signer="admin", secret=b"secret")
    assert registry.attach_signature("SearchPolicies", sig).state is DriverState.SIGNED
    assert registry.activate("SearchPolicies").state is DriverState.ACTIVE


def test_registry_revoked_driver_cannot_be_reactivated():
    policy = SignaturePolicy({"admin": b"secret"})
    registry = DriverRegistry(policy)
    manifest = DriverManifest(
        driver_id="ExtractTelemetry",
        version=1,
        kind="extract",
        capabilities=("payload.read",),
    )
    registry.add_candidate(manifest, test_report_hash="sha256:tests-pass")
    registry.approve("ExtractTelemetry")
    sig = sign_payload(manifest.canonical_payload(), signer="admin", secret=b"secret")
    registry.attach_signature("ExtractTelemetry", sig)
    registry.revoke("ExtractTelemetry")

    with pytest.raises(RegistryError, match="only signed"):
        registry.activate("ExtractTelemetry")


def test_trace_ranking_is_deterministic_and_evidence_based():
    traces = [
        TraceEvidence("b", "/tds/b", semantic_score=0.80, manifest_score=0.70, extraction_score=0.90),
        TraceEvidence("a", "/tds/a", semantic_score=0.80, manifest_score=0.70, extraction_score=0.90),
        TraceEvidence("c", "/tds/c", semantic_score=0.90, manifest_score=0.90, extraction_score=0.80),
    ]
    ranked = rank_traces(traces)
    assert [item.driver_id for item in ranked] == ["c", "a", "b"]
    assert ranked[0].rank_score > ranked[1].rank_score
    assert ranked[1].rank_score == ranked[2].rank_score

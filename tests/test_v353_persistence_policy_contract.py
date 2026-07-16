import pytest

from staqtapp_tds import CleanupMode, Durability, PersistencePolicy, PersistenceStatus


def test_production_safe_defaults_are_explicit_and_atomic():
    policy = PersistencePolicy.production_safe()
    assert policy.durability is Durability.DURABLE
    assert policy.retained_generations == 2
    assert policy.atomic_generations is True
    assert policy.acknowledged_loss_window_ms == 0
    assert policy.reduced_recovery_depth is False


def test_relaxed_cache_exposes_data_loss_and_backup_risks():
    policy = PersistencePolicy.relaxed_cache()
    joined = " ".join(policy.risk_summary()).lower()
    assert "acknowledged writes may be lost" in joined
    assert "no historical rollback" in joined
    assert "not off-device backups" in joined


def test_zero_retention_and_atomic_disable_are_rejected():
    with pytest.raises(ValueError, match=">= 1"):
        PersistencePolicy(retained_generations=0)
    with pytest.raises(ValueError, match="cannot be disabled"):
        PersistencePolicy.from_mapping({"atomic_generations": False})


def test_group_durable_requires_a_positive_bounded_window():
    with pytest.raises(ValueError, match="requires"):
        PersistencePolicy(durability=Durability.GROUP_DURABLE)
    policy = PersistencePolicy(
        durability=Durability.GROUP_DURABLE,
        retained_generations=2,
        group_commit_window_ms=25,
    )
    assert policy.acknowledged_loss_window_ms == 25
    assert "25 ms" in " ".join(policy.risk_summary())


def test_policy_mapping_round_trip_is_strict():
    original = PersistencePolicy.production_safe(retained_generations=3)
    restored = PersistencePolicy.from_mapping(original.to_dict())
    assert restored == original
    with pytest.raises(ValueError, match="Unknown"):
        PersistencePolicy.from_mapping({"mystery": True})


def test_recovery_status_requires_complete_observability():
    policy = PersistencePolicy.production_safe()
    status = PersistenceStatus.unmounted(policy)
    assert status.current_generation is None
    with pytest.raises(ValueError, match="requires"):
        PersistenceStatus(
            durability=Durability.DURABLE,
            retained_generations=2,
            atomic_generations=True,
            external_backup_configured=False,
            current_generation="gen-2",
            last_verified_generation="gen-1",
            recovery_fallback_active=True,
        )


def test_recovery_status_cannot_disguise_same_generation_as_fallback():
    with pytest.raises(ValueError, match="different"):
        PersistenceStatus(
            durability=Durability.DURABLE,
            retained_generations=2,
            atomic_generations=True,
            external_backup_configured=False,
            current_generation="gen-2",
            last_verified_generation="gen-2",
            recovery_fallback_active=True,
            requested_generation="gen-2",
            mounted_generation="gen-2",
            recovery_reason="test",
        )

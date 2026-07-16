from pathlib import Path

import pytest

from staqtapp_tds import (
    CleanupMode,
    GenerationIntegrityError,
    ImmutableGenerationStore,
    PersistencePolicy,
)


def test_commit_writes_complete_generation_then_promotes_current(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"expensive-ai-state", application_metadata={"model": "x"})
    assert store.current_generation() == info.generation_id
    assert store.read_current() == b"expensive-ai-state"
    assert (info.path / "data.tds").is_file()
    assert (info.path / "integrity.json").is_file()


def test_failure_before_current_promotion_preserves_previous_commit(tmp_path: Path):
    first = ImmutableGenerationStore(tmp_path).commit(b"old")

    def fail(name: str) -> None:
        if name == "generation_verified":
            raise RuntimeError("injected")

    store = ImmutableGenerationStore(tmp_path, fault_hook=fail)
    with pytest.raises(RuntimeError, match="injected"):
        store.commit(b"new")
    clean = ImmutableGenerationStore(tmp_path)
    assert clean.current_generation() == first.generation_id
    assert clean.read_current() == b"old"


def test_promoted_generation_is_self_verifying(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"abc")
    (info.path / "data.tds").write_bytes(b"abd")
    with pytest.raises(GenerationIntegrityError, match="checksum"):
        store.current_generation()


def test_recovery_falls_back_observably_to_newest_valid_generation(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    old = store.commit(b"old")
    new = store.commit(b"new")
    (new.path / "data.tds").write_bytes(b"bad")
    status = store.recover()
    assert status.recovery_fallback_active is True
    assert status.requested_generation == new.generation_id
    assert status.mounted_generation == old.generation_id
    assert "checksum" in status.recovery_reason


def test_immediate_retention_prunes_only_after_successful_promotion(tmp_path: Path):
    policy = PersistencePolicy.production_safe(
        retained_generations=2,
        cleanup=CleanupMode.IMMEDIATE,
    )
    store = ImmutableGenerationStore(tmp_path, policy=policy)
    store.commit(b"1")
    store.commit(b"2")
    store.commit(b"3")
    valid = store.list_generations(valid_only=True)
    assert len(valid) == 2
    assert store.read_current() == b"3"


def test_missing_current_pointer_is_recoverable_and_visible(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"state")
    store.current_path.unlink()
    status = store.recover()
    assert status.recovery_fallback_active is True
    assert status.mounted_generation == info.generation_id
    assert status.requested_generation == "CURRENT-missing"

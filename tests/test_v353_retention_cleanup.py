from pathlib import Path
import pytest

from staqtapp_tds import CleanupError, ImmutableGenerationStore


def _three(store):
    return [store.commit(x).generation_id for x in (b"one", b"two", b"three")]


def test_pin_survives_reopen_and_blocks_prune(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    first, second, third = _three(store)
    store.pin(first)
    reopened = ImmutableGenerationStore(tmp_path)
    assert reopened.list_pins() == (first,)
    report = reopened.prune(keep=1, acknowledge_reduced_recovery=True)
    assert second in report.removed_generations
    assert first not in report.removed_generations
    assert reopened.verify(first).generation_id == first
    assert reopened.current_generation() == third


def test_prune_requires_explicit_acknowledgement(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    _three(store)
    with pytest.raises(CleanupError, match="acknowledge_reduced_recovery"):
        store.prune(keep=1)


def test_unpin_requires_explicit_acknowledgement(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    generation = store.commit(b"one").generation_id
    store.pin(generation)
    with pytest.raises(CleanupError):
        store.unpin(generation)
    store.unpin(generation, acknowledge_reduced_recovery=True)
    assert store.list_pins() == ()


def test_interrupted_cleanup_resumes_from_durable_plan(tmp_path):
    base = ImmutableGenerationStore(tmp_path)
    first, second, third = _three(base)
    calls = 0
    def crash(name):
        nonlocal calls
        if name == "cleanup_after_quarantine":
            calls += 1
            if calls == 1:
                raise RuntimeError("simulated interruption")
    interrupted = ImmutableGenerationStore(tmp_path, fault_hook=crash)
    with pytest.raises(RuntimeError):
        interrupted.prune(keep=1, acknowledge_reduced_recovery=True)
    assert (Path(tmp_path) / interrupted.CLEANUP_PLAN_NAME).exists()
    clean = ImmutableGenerationStore(tmp_path)
    report = clean.resume_cleanup()
    assert report is not None and report.completed and report.resumed
    assert clean.current_generation() == third
    assert clean.read_current() == b"three"
    assert not (Path(tmp_path) / clean.CLEANUP_PLAN_NAME).exists()


def test_cleanup_rechecks_pin_before_each_delete(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    first, second, third = _three(store)
    store._write_cleanup_plan([first, second])
    store.pin(second)
    report = store.resume_cleanup()
    assert first in report.removed_generations
    assert second in report.skipped_protected
    assert store.verify(second).generation_id == second
    assert store.current_generation() == third


def test_invalid_cleanup_plan_fails_closed(tmp_path):
    store = ImmutableGenerationStore(tmp_path)
    store.cleanup_plan_path.write_text('{"schema":"bad","candidates":[]}', encoding="utf-8")
    with pytest.raises(CleanupError):
        store.resume_cleanup()

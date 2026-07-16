from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from staqtapp_tds import GenerationIntegrityError, ImmutableGenerationStore


PRE_PROMOTION_CHECKPOINTS = (
    "generation_created",
    "data_before_fsync",
    "data_after_fsync",
    "data_written",
    "metadata_before_fsync",
    "metadata_after_fsync",
    "metadata_written",
    "generation_dir_before_fsync",
    "generation_dir_after_fsync",
    "generation_verified",
    "current_temp_before_fsync",
    "current_temp_after_fsync",
    "current_temp_written",
)

POST_PROMOTION_CHECKPOINTS = (
    "current_replaced",
    "parent_before_fsync",
    "parent_after_fsync",
    "parent_synced",
)


def _crash_commit(root: Path, checkpoint: str) -> subprocess.CompletedProcess[str]:
    script = r'''
import os, sys
from staqtapp_tds import ImmutableGenerationStore
root, checkpoint = sys.argv[1], sys.argv[2]
def crash(name):
    if name == checkpoint:
        os._exit(77)
ImmutableGenerationStore(root, fault_hook=crash).commit(b"new-state")
'''
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", script, str(root), checkpoint],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("checkpoint", PRE_PROMOTION_CHECKPOINTS)
def test_real_process_death_before_promotion_preserves_previous_generation(
    tmp_path: Path, checkpoint: str
):
    store = ImmutableGenerationStore(tmp_path)
    old = store.commit(b"old-state")
    result = _crash_commit(tmp_path, checkpoint)
    assert result.returncode == 77, (checkpoint, result.stdout, result.stderr)

    reopened = ImmutableGenerationStore(tmp_path)
    assert reopened.current_generation() == old.generation_id
    assert reopened.read_current() == b"old-state"


@pytest.mark.parametrize("checkpoint", POST_PROMOTION_CHECKPOINTS)
def test_real_process_death_after_atomic_promotion_exposes_complete_new_generation(
    tmp_path: Path, checkpoint: str
):
    ImmutableGenerationStore(tmp_path).commit(b"old-state")
    result = _crash_commit(tmp_path, checkpoint)
    assert result.returncode == 77, (checkpoint, result.stdout, result.stderr)

    reopened = ImmutableGenerationStore(tmp_path)
    assert reopened.read_current() == b"new-state"
    status = reopened.recover()
    assert status.recovery_fallback_active is False


def test_application_metadata_rejects_excessive_nesting_before_json_codec(tmp_path: Path):
    nested: object = "leaf"
    for _ in range(ImmutableGenerationStore.MAX_METADATA_DEPTH + 1):
        nested = {"child": nested}
    store = ImmutableGenerationStore(tmp_path)
    with pytest.raises(GenerationIntegrityError, match="nesting depth"):
        store.commit(b"state", application_metadata={"root": nested})
    assert not store.current_path.exists()


def test_application_metadata_rejects_excessive_node_count(tmp_path: Path):
    metadata = {"items": list(range(ImmutableGenerationStore.MAX_METADATA_NODES + 1))}
    with pytest.raises(GenerationIntegrityError, match="node count"):
        ImmutableGenerationStore(tmp_path).commit(b"state", application_metadata=metadata)


def test_oversized_integrity_metadata_is_rejected_before_parse(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"state")
    meta = info.path / store.META_NAME
    meta.write_bytes(b"{" + b" " * store.MAX_METADATA_BYTES + b"}")
    with pytest.raises(GenerationIntegrityError, match="exceeds"):
        store.verify(info.generation_id)


def test_deeply_nested_integrity_metadata_is_rejected_as_integrity_failure(tmp_path: Path):
    store = ImmutableGenerationStore(tmp_path)
    info = store.commit(b"state")
    nested = '"leaf"'
    for _ in range(store.MAX_METADATA_DEPTH + 5):
        nested = '{"x":' + nested + '}'
    (info.path / store.META_NAME).write_text(nested, encoding="utf-8")
    with pytest.raises(GenerationIntegrityError):
        store.verify(info.generation_id)

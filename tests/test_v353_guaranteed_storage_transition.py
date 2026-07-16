from pathlib import Path
import struct

import pytest

from staqtapp_tds import (
    GuaranteedStorageBridge,
    GuaranteedStorageError,
    TDSFileSystem,
    TDSReader,
)


def _filesystem() -> TDSFileSystem:
    fs = TDSFileSystem("root")
    models = fs.root.mkdir("models")
    models.write("state", {"epoch": 7, "loss": 0.125})
    models.write("blob", b"expensive-ai-state" * 100)
    return fs


def test_transition_fit_is_explicit_and_does_not_change_default_path():
    fit = GuaranteedStorageBridge.analyze_fit()
    assert fit.legacy_serializer_reused is True
    assert fit.atomic_mount_boundary is True
    assert fit.bounded_memory is True
    assert fit.default_path_changed is False
    assert fit.image_format == "tds.transition.image.v1"


def test_complete_legacy_image_round_trips_through_one_generation(tmp_path: Path):
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    report = bridge.commit_filesystem(_filesystem(), parallel_nodes=False)
    assert report.files_archived >= 2
    assert report.source_bytes > 0
    restored = bridge.materialize_current(tmp_path / "restored")
    state_files = sorted(restored.glob("*.tds"))
    assert state_files
    values = {}
    for path in state_files:
        reader = TDSReader(path)
        try:
            for key in reader.keys():
                values[key.rsplit("/", 1)[-1]] = reader.read(key)
        finally:
            reader.close()
    assert values["state"] == {"epoch": 7, "loss": 0.125}
    assert values["blob"] == b"expensive-ai-state" * 100


def test_failed_second_transition_preserves_previous_generation(tmp_path: Path, monkeypatch):
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    first = bridge.commit_filesystem(_filesystem(), parallel_nodes=False)

    original = bridge.store._write_file
    calls = 0
    def fail_during_data(path, chunks, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            iterator = iter(chunks)
            first_chunk = next(iterator)
            original(path, [first_chunk], durable=False, hasher=kwargs.get("hasher"))
            raise OSError("injected storage failure")
        return original(path, chunks, **kwargs)

    monkeypatch.setattr(bridge.store, "_write_file", fail_during_data)
    with pytest.raises(OSError, match="injected"):
        bridge.commit_filesystem(_filesystem(), parallel_nodes=False)
    assert bridge.store.current_generation() == first.generation.generation_id


def test_materialisation_rejects_existing_destination(tmp_path: Path):
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    bridge.commit_filesystem(_filesystem(), parallel_nodes=False)
    destination = tmp_path / "restored"
    destination.mkdir()
    with pytest.raises(GuaranteedStorageError, match="already exists"):
        bridge.materialize_current(destination)


def test_materialisation_rejects_traversal_even_when_generation_hash_is_updated(tmp_path: Path):
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    report = bridge.commit_filesystem(_filesystem(), parallel_nodes=False)
    data_path = report.generation.path / bridge.store.DATA_NAME
    payload = bytearray(data_path.read_bytes())
    magic_len = len(b"TDSIMG1\n")
    path_len, size = struct.unpack(">IQ", payload[magic_len:magic_len + 12])
    assert path_len >= 4
    payload[magic_len + 12:magic_len + 16] = b"../x"
    # Keep path length stable and rewrite the generation integrity hash so the
    # transition extractor, not outer generation verification, sees the attack.
    data_path.write_bytes(payload)
    meta_path = report.generation.path / bridge.store.META_NAME
    import json, hashlib
    meta = json.loads(meta_path.read_text())
    meta["data_sha256"] = hashlib.sha256(payload).hexdigest()
    meta_path.write_text(json.dumps(meta, sort_keys=True, separators=(",", ":")))
    with pytest.raises(GuaranteedStorageError, match="unsafe archive path"):
        bridge.materialize_current(tmp_path / "restored")


def test_commit_stream_rejects_mutable_chunks_without_promotion(tmp_path: Path):
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    first = bridge.store.commit(b"old")
    with pytest.raises(Exception, match="read-only"):
        bridge.store.commit_stream([bytearray(b"mutable")])
    assert bridge.store.current_generation() == first.generation_id

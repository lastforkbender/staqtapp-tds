from pathlib import Path

import pytest

from staqtapp_tds import GuaranteedStorageBridge, GuaranteedStorageError, TDSFileSystem
from staqtapp_tds.tds_persistence import TDSPersistence


def _legacy_mount(path: Path) -> Path:
    fs = TDSFileSystem("root")
    models = fs.root.mkdir("models")
    models.write("state", {"epoch": 11, "loss": 0.03125})
    models.write("blob", b"verified-migration" * 257)
    nested = models.mkdir("nested")
    nested.write("weights", [1, 2, 3, 5, 8])
    TDSPersistence(path).flush(fs, parallel_nodes=False)
    return path


def test_verified_round_trip_proves_all_equivalence_gates(tmp_path: Path):
    source = _legacy_mount(tmp_path / "legacy")
    source_before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    report = bridge.verify_round_trip(source, tmp_path / "materialized")

    assert report.inventory_equivalent is True
    assert report.lengths_equivalent is True
    assert report.digests_equivalent is True
    assert report.metadata_equivalent is True
    assert report.logical_reopen_equivalent is True
    assert report.source_unchanged is True
    assert report.activation_eligible is True
    assert report.published is True
    assert report.files_verified == len(source_before)
    assert {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()} == source_before


def test_destination_is_not_published_when_equivalence_fails(tmp_path: Path, monkeypatch):
    source = _legacy_mount(tmp_path / "legacy")
    destination = tmp_path / "materialized"
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    original = bridge._logical_mount_signature
    calls = 0

    def mismatch(root):
        nonlocal calls
        calls += 1
        value = original(root)
        if calls == 2:
            return {**value, "unexpected.tds": ()}
        return value

    previous = bridge.store.commit(b"previous-generation")
    monkeypatch.setattr(bridge, "_logical_mount_signature", mismatch)
    with pytest.raises(GuaranteedStorageError, match="activation remains prohibited"):
        bridge.verify_round_trip(source, destination)
    assert not destination.exists()
    assert bridge.store.current_generation() == previous.generation_id


def test_existing_destination_is_rejected_before_generation_commit(tmp_path: Path):
    source = _legacy_mount(tmp_path / "legacy")
    destination = tmp_path / "materialized"
    destination.mkdir()
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    with pytest.raises(GuaranteedStorageError, match="already exists"):
        bridge.verify_round_trip(source, destination)
    assert bridge.store.current_generation() is None


def test_symlinked_legacy_source_is_rejected(tmp_path: Path):
    source = _legacy_mount(tmp_path / "legacy")
    link = source / "injected"
    try:
        link.symlink_to(source / "tds.manifest.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    bridge = GuaranteedStorageBridge(tmp_path / "guaranteed")
    with pytest.raises(GuaranteedStorageError, match="symlink"):
        bridge.verify_round_trip(source, tmp_path / "materialized")

from pathlib import Path

import pytest

from staqtapp_tds import (
    ControlledActivationError,
    ControlledStorage,
    StorageMode,
    TDSFileSystem,
)
from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.tds_persistence import TDSPersistence


def _filesystem(value: str = "legacy") -> TDSFileSystem:
    fs = TDSFileSystem("root")
    models = fs.root.mkdir("models")
    models.write("state", {"mode": value, "epoch": 11})
    models.write("blob", (value.encode("utf-8") + b"-") * 4096)
    return fs


def _legacy_mount(path: Path, value: str = "legacy") -> Path:
    TDSPersistence(path).flush(_filesystem(value), parallel_nodes=False)
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _qualified(tmp_path: Path) -> tuple[ControlledStorage, object, Path, dict[str, bytes]]:
    legacy = _legacy_mount(tmp_path / "legacy")
    original = _snapshot(legacy)
    controlled = ControlledStorage(tmp_path / "guaranteed", legacy)
    qualification = controlled.qualify_activation()
    return controlled, qualification, legacy, original


def test_default_is_visible_legacy_mode_without_a_state_file(tmp_path: Path) -> None:
    legacy = _legacy_mount(tmp_path / "legacy")
    controlled = ControlledStorage(tmp_path / "guaranteed", legacy)
    status = controlled.status()
    assert status.mode is StorageMode.LEGACY
    assert status.revision == 0
    assert status.state_persisted is False
    assert status.current_generation is None
    assert status.rollback_available is False
    assert not controlled.state_path.exists()


def test_qualification_proves_segmented_equivalence_without_activation(tmp_path: Path) -> None:
    controlled, qualification, legacy, original = _qualified(tmp_path)
    assert qualification.activation_eligible is True
    assert qualification.inventory_equivalent is True
    assert qualification.lengths_equivalent is True
    assert qualification.digests_equivalent is True
    assert qualification.metadata_equivalent is True
    assert qualification.logical_reopen_equivalent is True
    assert qualification.source_unchanged is True
    assert controlled.status().mode is StorageMode.LEGACY
    assert _snapshot(legacy) == original


def test_activation_requires_exact_acknowledgement(tmp_path: Path) -> None:
    controlled, qualification, _legacy, _original = _qualified(tmp_path)
    with pytest.raises(ControlledActivationError, match="acknowledgement"):
        controlled.activate(qualification, acknowledgement="yes")
    assert controlled.status().mode is StorageMode.LEGACY


def test_qualified_activation_is_persisted_and_browser_visible(tmp_path: Path) -> None:
    controlled, qualification, legacy, original = _qualified(tmp_path)
    status = controlled.activate(
        qualification,
        acknowledgement=controlled.ACTIVATE_ACKNOWLEDGEMENT,
    )
    assert status.mode is StorageMode.GUARANTEED_SEGMENTED
    assert status.revision == 1
    assert status.state_persisted is True
    assert status.activation_verified is True
    assert status.current_generation_verified is True
    assert status.current_generation == qualification.generation_id
    assert status.rollback_available is True
    assert _snapshot(legacy) == original
    admin = AdminControl(observation_source=controlled).status()
    assert admin["storage_mode"]["mode"] == "guaranteed-segmented"
    assert admin["storage_mode"]["activation_verified"] is True
    assert admin["storage_mode"]["current_generation_verified"] is False


def test_activation_rejects_source_changed_after_qualification(tmp_path: Path) -> None:
    controlled, qualification, legacy, _original = _qualified(tmp_path)
    (legacy / "unexpected.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ControlledActivationError, match="changed"):
        controlled.activate(
            qualification,
            acknowledgement=controlled.ACTIVATE_ACKNOWLEDGEMENT,
        )
    assert controlled.status().mode is StorageMode.LEGACY


def test_active_mount_is_a_verified_private_reconstruction(tmp_path: Path) -> None:
    controlled, qualification, legacy, original = _qualified(tmp_path)
    controlled.activate(
        qualification,
        acknowledgement=controlled.ACTIVATE_ACKNOWLEDGEMENT,
    )
    with controlled.active_mount() as active:
        assert active != legacy
        assert _snapshot(active) == original
    assert _snapshot(legacy) == original


def test_guaranteed_commit_then_lossless_rollback_to_new_legacy_mount(tmp_path: Path) -> None:
    controlled, qualification, original_legacy, original = _qualified(tmp_path)
    controlled.activate(
        qualification,
        acknowledgement=controlled.ACTIVATE_ACKNOWLEDGEMENT,
    )
    commit = controlled.commit_filesystem(_filesystem("after-activation"), parallel_nodes=False)
    assert commit.mode is StorageMode.GUARANTEED_SEGMENTED
    assert commit.generation_id is not None
    assert commit.segments_created > 0
    with controlled.active_mount() as active:
        guaranteed_bytes = _snapshot(active)
    rolled = controlled.rollback_to_legacy(
        acknowledgement=controlled.ROLLBACK_ACKNOWLEDGEMENT
    )
    assert rolled.mode is StorageMode.LEGACY
    assert rolled.revision == 2
    assert rolled.previous_mode is StorageMode.GUARANTEED_SEGMENTED
    assert rolled.legacy_mount != original_legacy
    assert _snapshot(rolled.legacy_mount) == guaranteed_bytes
    assert _snapshot(original_legacy) == original
    with controlled.active_mount() as active:
        assert active == rolled.legacy_mount


def test_state_publication_failure_leaves_legacy_mode(tmp_path: Path) -> None:
    def fail(name: str) -> None:
        if name == "activation_before_state_publish":
            raise RuntimeError("injected state publication failure")

    legacy = _legacy_mount(tmp_path / "legacy")
    controlled = ControlledStorage(tmp_path / "guaranteed", legacy, fault_hook=fail)
    qualification = controlled.qualify_activation()
    with pytest.raises(RuntimeError, match="injected"):
        controlled.activate(
            qualification,
            acknowledgement=controlled.ACTIVATE_ACKNOWLEDGEMENT,
        )
    assert controlled.status().mode is StorageMode.LEGACY
    assert not controlled.state_path.exists()


def test_noncanonical_or_corrupt_mode_record_fails_closed(tmp_path: Path) -> None:
    controlled, qualification, _legacy, _original = _qualified(tmp_path)
    controlled.activate(
        qualification,
        acknowledgement=controlled.ACTIVATE_ACKNOWLEDGEMENT,
    )
    controlled.state_path.write_bytes(controlled.state_path.read_bytes() + b"\n")
    with pytest.raises(ControlledActivationError, match="canonical"):
        controlled.status()


def test_guaranteed_root_inside_legacy_mount_is_rejected(tmp_path: Path) -> None:
    legacy = _legacy_mount(tmp_path / "legacy")
    with pytest.raises(ControlledActivationError, match="inside"):
        ControlledStorage(legacy / "guaranteed", legacy)

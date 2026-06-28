from staqtapp_tds import TDSFileSystem, RuntimeConfig, ConfigRegistry
from staqtapp_tds.admin import AdminControl, LocalAuthProvider


def test_runtime_config_generation_metadata_on_write():
    cfg = RuntimeConfig.default(config_id="rc-001", generation=1)
    fs = TDSFileSystem(runtime_config=cfg)
    fs.root.write("a", "hello")
    meta = fs.root.entry_metadata("a")
    assert meta["config_id"] == "rc-001"
    assert meta["config_generation"] == 1


def test_stage_promote_candidate_config_without_mutating_old_entry():
    registry = ConfigRegistry(RuntimeConfig.default(config_id="rc-001", generation=1))
    fs = TDSFileSystem(config_registry=registry)
    control = AdminControl(registry=registry, auth=LocalAuthProvider("s"))
    fs.root.write("old", "before")

    candidate = registry.active().next_generation(config_id="rc-002", compression_enabled=True, compression_threshold_bytes=1)
    control.stage_config(candidate, control.auth.issue("stage"))
    assert registry.active().config_id == "rc-001"

    control.promote_config(control.auth.issue("promote"))
    fs.root.write_text("new", "after" * 128)

    assert fs.root.entry_metadata("old")["config_id"] == "rc-001"
    assert fs.root.entry_metadata("new")["config_id"] == "rc-002"
    assert fs.root.entry_metadata("new")["compressed"] is True
    assert control.status()["active"]["config_id"] == "rc-002"


def test_admin_rollback_returns_prior_generation():
    registry = ConfigRegistry(RuntimeConfig.default(config_id="rc-001", generation=1))
    control = AdminControl(registry=registry, auth=LocalAuthProvider("s"))
    control.stage_config(registry.active().next_generation(config_id="rc-002"), control.auth.issue("stage"))
    control.promote_config(control.auth.issue("promote"))
    rolled = control.rollback_config(control.auth.issue("rollback"))
    assert rolled.config_id == "rc-001"

from __future__ import annotations
from typing import Any
from staqtapp_tds.config import ConfigRegistry, RuntimeConfig
from staqtapp_tds.admin.auth import ConfigGrant, LocalAuthProvider
from staqtapp_tds.admin.audit import AuditEvent, AuditLog
from staqtapp_tds.admin.spiral_rank import SpiralRankTelemetry, spiral_rank_snapshot_from

class AdminControl:
    def __init__(self, registry: ConfigRegistry | None = None, auth: LocalAuthProvider | None = None, audit: AuditLog | None = None, observation_source: Any | None = None):
        self.registry = registry or ConfigRegistry()
        self.auth = auth or LocalAuthProvider()
        self.audit = audit or AuditLog()
        self.observation_source = observation_source
        self.spiral_rank_telemetry = SpiralRankTelemetry()

    def status(self) -> dict[str, Any]:
        snap = self.registry.snapshot()
        snap["audit_count"] = len(self.audit.entries())
        if self.observation_source is not None:
            source = self.observation_source
            if hasattr(source, "storage_status"):
                snap["storage_mode"] = source.storage_status()
            if hasattr(source, "observation_snapshot"):
                snap["observation"] = source.observation_snapshot()
            elif hasattr(source, "snapshot"):
                snap["observation"] = source.snapshot()
            elif callable(source):
                snap["observation"] = source()
            if hasattr(source, "csv_interpole_monitor_snapshot"):
                csv_snapshot = source.csv_interpole_monitor_snapshot()
                snap["csv_interpole_monitor"] = (
                    csv_snapshot.to_dict() if hasattr(csv_snapshot, "to_dict") else csv_snapshot
                )
            elif hasattr(source, "csv_interpole_monitor"):
                csv_snapshot = source.csv_interpole_monitor
                snap["csv_interpole_monitor"] = (
                    csv_snapshot.to_dict() if hasattr(csv_snapshot, "to_dict") else csv_snapshot
                )
            snap["spiral_rank"] = spiral_rank_snapshot_from(source)
        else:
            snap["spiral_rank"] = self.spiral_rank_telemetry.snapshot()
        return snap

    def stage_config(self, candidate: RuntimeConfig, grant: ConfigGrant) -> RuntimeConfig:
        self.auth.verify(grant, "stage")
        staged = self.registry.stage(candidate)
        self.audit.record(AuditEvent("stage", grant.subject, staged.config_id, staged.generation))
        return staged

    def promote_config(self, grant: ConfigGrant) -> RuntimeConfig:
        self.auth.verify(grant, "promote")
        promoted = self.registry.promote()
        self.audit.record(AuditEvent("promote", grant.subject, promoted.config_id, promoted.generation))
        return promoted

    def rollback_config(self, grant: ConfigGrant) -> RuntimeConfig:
        self.auth.verify(grant, "rollback")
        rolled = self.registry.rollback()
        self.audit.record(AuditEvent("rollback", grant.subject, rolled.config_id, rolled.generation))
        return rolled

"""Runtime/admin configuration boundary for Staqtapp-TDS.

The config layer is intentionally control-plane only: immutable runtime configs are
built, validated, staged, and atomically promoted without putting vault/auth work
in the directory/index hot path.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from staqtapp_tds.tds_json import dumps_canonical
import hashlib
import time


DEFAULT_CONFIG_ID_PREFIX = "rc"


@dataclass(frozen=True)
class RuntimeConfig:
    config_id: str
    generation: int = 1
    created_at: float = field(default_factory=time.time)
    chunk_bytes: int = 65536
    compression: str = "zlib"
    compression_enabled: bool = False
    compression_threshold_bytes: int = 4096
    serializer: str = "pickle"
    index_backend: str = "native"
    radix_depth: int = 64
    key_id: str | None = None
    max_memory_bytes: int | None = None
    numba_enabled: bool = True
    numba_parallel: bool = False
    admin_panel_enabled: bool = False
    spiral_support_enabled: bool = False
    network_mode: str = "local-only"
    telemetry_level: str = "normal"

    @staticmethod
    def default(config_id: str = "rc-default", generation: int = 1) -> "RuntimeConfig":
        return RuntimeConfig(config_id=config_id, generation=generation)

    def validate(self) -> None:
        if not self.config_id:
            raise ValueError("RuntimeConfig.config_id is required")
        if self.generation < 1:
            raise ValueError("RuntimeConfig.generation must be positive")
        if self.chunk_bytes <= 0:
            raise ValueError("RuntimeConfig.chunk_bytes must be positive")
        if self.compression_threshold_bytes < 0:
            raise ValueError("compression_threshold_bytes cannot be negative")
        if self.network_mode not in {"local-only", "private-api", "external-disabled"}:
            raise ValueError("network_mode must be local-only, private-api, or external-disabled")
        if str(self.telemetry_level).lower() not in {"off", "minimal", "normal", "engineering", "developer"}:
            raise ValueError("telemetry_level must be off, minimal, normal, engineering, or developer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "generation": self.generation,
            "created_at": self.created_at,
            "chunk_bytes": self.chunk_bytes,
            "compression": self.compression,
            "compression_enabled": self.compression_enabled,
            "compression_threshold_bytes": self.compression_threshold_bytes,
            "serializer": self.serializer,
            "index_backend": self.index_backend,
            "radix_depth": self.radix_depth,
            "key_id": self.key_id,
            "max_memory_bytes": self.max_memory_bytes,
            "numba_enabled": self.numba_enabled,
            "numba_parallel": self.numba_parallel,
            "admin_panel_enabled": self.admin_panel_enabled,
            "spiral_support_enabled": self.spiral_support_enabled,
            "network_mode": self.network_mode,
            "telemetry_level": self.telemetry_level,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RuntimeConfig":
        allowed = set(cls.__dataclass_fields__.keys())
        cfg = cls(**{k: v for k, v in dict(data).items() if k in allowed})
        cfg.validate()
        return cfg

    def fingerprint(self) -> str:
        payload, _backend = dumps_canonical(self.to_dict())
        return hashlib.sha256(payload).hexdigest()

    def next_generation(self, **changes: Any) -> "RuntimeConfig":
        next_gen = int(changes.pop("generation", self.generation + 1))
        cfg_id = changes.pop("config_id", f"{DEFAULT_CONFIG_ID_PREFIX}-{next_gen:06d}")
        cfg = replace(self, generation=next_gen, config_id=cfg_id, created_at=time.time(), **changes)
        cfg.validate()
        return cfg


@dataclass(frozen=True)
class AdminConfig:
    runtime: RuntimeConfig
    required_subject: str = "local-admin"
    allow_network_panel: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AdminConfig":
        runtime_data = dict(data.get("runtime", data))
        runtime = RuntimeConfig.from_mapping(runtime_data)
        return cls(
            runtime=runtime,
            required_subject=str(data.get("required_subject", "local-admin")),
            allow_network_panel=bool(data.get("allow_network_panel", False)),
        )

    def build_runtime(self) -> tuple[RuntimeConfig, dict[str, Any]]:
        self.runtime.validate()
        return self.runtime, {}


class ConfigRegistry:
    """Thread-safe active/candidate config pointer.

    The hot path calls active() only. Validation, signing, auth, and promotion stay
    in the admin/control layer.
    """

    def __init__(self, initial: RuntimeConfig | None = None):
        import threading
        self._lock = threading.RLock()
        self._active = initial or RuntimeConfig.default()
        self._candidate: RuntimeConfig | None = None
        self._history: list[RuntimeConfig] = [self._active]
        self._active.validate()

    def active(self) -> RuntimeConfig:
        return self._active

    def stage(self, candidate: RuntimeConfig) -> RuntimeConfig:
        candidate.validate()
        with self._lock:
            self._candidate = candidate
            return candidate

    def candidate(self) -> RuntimeConfig | None:
        with self._lock:
            return self._candidate

    def promote(self, candidate: RuntimeConfig | None = None) -> RuntimeConfig:
        with self._lock:
            cfg = candidate or self._candidate
            if cfg is None:
                raise ValueError("No candidate RuntimeConfig staged")
            cfg.validate()
            if cfg.generation <= self._active.generation:
                raise ValueError("Candidate generation must be newer than active generation")
            self._active = cfg
            self._history.append(cfg)
            self._candidate = None
            return cfg

    def rollback(self) -> RuntimeConfig:
        with self._lock:
            if len(self._history) < 2:
                raise ValueError("No prior RuntimeConfig to roll back to")
            self._history.pop()
            self._active = self._history[-1]
            self._candidate = None
            return self._active

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._active.to_dict(),
                "candidate": self._candidate.to_dict() if self._candidate else None,
                "history_generations": [c.generation for c in self._history],
            }

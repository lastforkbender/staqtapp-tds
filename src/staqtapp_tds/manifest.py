"""Read-once manifest policy for Staqtapp-TDS."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from staqtapp_tds.capabilities import CapabilityRegistry
from staqtapp_tds.latency import LatencyPolicy
from staqtapp_tds.telemetry import TelemetryMode
from staqtapp_tds.namespaces import ReservedNamespaces
from staqtapp_tds.tds_json import dumps_canonical, dumps_pretty, loads_manifest

MANIFEST_FILENAME = ".tds_manifest"
DEFAULT_FOLDER_SIGNATURE = "STAQTTDS-SRZ-v1"


def _stable_json(data: Dict[str, Any]) -> str:
    return dumps_canonical(data)[0].decode("utf-8")


@dataclass(frozen=True)
class ManifestPolicy:
    tds_manifest_version: int = 1
    folder_signature: str = DEFAULT_FOLDER_SIGNATURE
    schema_version: str = "1.7.3"
    route_stamp_version: str = "RSPEC-1"
    hash_policy: str = "sha256"
    codec_policy: str = "raw-or-zlib"
    strict_mode: bool = True
    inherits: bool = True
    telemetry_mode: TelemetryMode = TelemetryMode.LIGHT
    telemetry_flush_policy: str = "snapshot"
    trace_window: int = 1024
    latency_policy: LatencyPolicy = field(default_factory=LatencyPolicy)
    capabilities: CapabilityRegistry = field(default_factory=lambda: CapabilityRegistry.from_names(["srz", "latency", "telemetry", "compression", "shared_arena", "native_index_ready", "manifest_bound"]))
    manifest_hash: str = ""
    reserved_namespaces: ReservedNamespaces = field(default_factory=ReservedNamespaces)

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        data = {
            "tds_manifest_version": self.tds_manifest_version,
            "folder_signature": self.folder_signature,
            "schema_version": self.schema_version,
            "route_stamp_version": self.route_stamp_version,
            "hash_policy": self.hash_policy,
            "codec_policy": self.codec_policy,
            "strict_mode": self.strict_mode,
            "inherits": self.inherits,
            "telemetry": {
                "mode": self.telemetry_mode.name.lower(),
                "flush_policy": self.telemetry_flush_policy,
                "trace_window": self.trace_window,
            },
            "latency": {
                "expected_lookup_ns": self.latency_policy.expected_lookup_ns,
                "soft_limit_ns": self.latency_policy.soft_limit_ns,
                "hard_limit_ns": self.latency_policy.hard_limit_ns,
            },
            "capabilities": self.capabilities.names(),
            "reserved_namespaces": self.reserved_namespaces.to_dict(),
        }
        if include_hash and self.manifest_hash:
            data["manifest_hash"] = self.manifest_hash
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, inherited: Optional["ManifestPolicy"] = None) -> "ManifestPolicy":
        base = inherited or cls()
        telemetry = data.get("telemetry", {}) or {}
        latency = data.get("latency", {}) or {}
        mode_name = str(telemetry.get("mode", base.telemetry_mode.name.lower())).upper()
        mode = TelemetryMode[mode_name] if mode_name in TelemetryMode.__members__ else base.telemetry_mode
        caps = data.get("capabilities", base.capabilities.names())
        policy = cls(
            tds_manifest_version=int(data.get("tds_manifest_version", base.tds_manifest_version)),
            folder_signature=str(data.get("folder_signature", base.folder_signature)),
            schema_version=str(data.get("schema_version", base.schema_version)),
            route_stamp_version=str(data.get("route_stamp_version", base.route_stamp_version)),
            hash_policy=str(data.get("hash_policy", base.hash_policy)),
            codec_policy=str(data.get("codec_policy", base.codec_policy)),
            strict_mode=bool(data.get("strict_mode", base.strict_mode)),
            inherits=bool(data.get("inherits", base.inherits)),
            telemetry_mode=mode,
            telemetry_flush_policy=str(telemetry.get("flush_policy", base.telemetry_flush_policy)),
            trace_window=int(telemetry.get("trace_window", base.trace_window)),
            latency_policy=LatencyPolicy(
                expected_lookup_ns=int(latency.get("expected_lookup_ns", base.latency_policy.expected_lookup_ns)),
                soft_limit_ns=int(latency.get("soft_limit_ns", base.latency_policy.soft_limit_ns)),
                hard_limit_ns=int(latency.get("hard_limit_ns", base.latency_policy.hard_limit_ns)),
            ),
            capabilities=CapabilityRegistry.from_names(caps if isinstance(caps, Iterable) and not isinstance(caps, (str, bytes)) else []),
            manifest_hash="",
            reserved_namespaces=ReservedNamespaces.from_dict(data.get("reserved_namespaces", base.reserved_namespaces.to_dict())),
        )
        mh = hashlib.sha256(_stable_json(policy.to_dict(include_hash=False)).encode("utf-8")).hexdigest()
        return cls(**{**policy.__dict__, "manifest_hash": mh})

    @classmethod
    def default(cls) -> "ManifestPolicy":
        return cls.from_dict({})


def find_manifest(start: Path) -> Optional[Path]:
    p = Path(start).resolve()
    if p.is_file():
        p = p.parent
    for cur in [p, *p.parents]:
        candidate = cur / MANIFEST_FILENAME
        if candidate.exists():
            return candidate
    return None


def load_manifest(folder: Path, *, inherit: bool = True) -> ManifestPolicy:
    folder = Path(folder)
    manifest_path = find_manifest(folder) if inherit else folder / MANIFEST_FILENAME
    if manifest_path is None or not manifest_path.exists():
        return ManifestPolicy.default()
    data, _backend = loads_manifest(manifest_path.read_bytes())
    return ManifestPolicy.from_dict(data)


def write_default_manifest(folder: Path, *, overwrite: bool = False) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / MANIFEST_FILENAME
    if target.exists() and not overwrite:
        return target
    policy = ManifestPolicy.default()
    target.write_text(dumps_pretty(policy.to_dict(include_hash=False))[0])
    return target

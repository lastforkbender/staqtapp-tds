from staqtapp_tds import (
    TDSFileSystem,
    ManifestPolicy,
    ReservedNamespaces,
    TelemetryMode,
)

reserved = ReservedNamespaces(directory_names=("future_zone",))
policy = ManifestPolicy.from_dict({
    "schema_version": "1.7.3",
    "telemetry": {"mode": "light", "flush_policy": "snapshot", "trace_window": 1024},
    "capabilities": ["srz", "latency", "telemetry", "reserved_namespaces"],
    "reserved_namespaces": reserved.to_dict(),
})

fs = TDSFileSystem("root", manifest_policy=policy)

zone = fs.root.mkdir(
    "tokenizers",
    srz_enabled=True,
    route_stamp="ML.TOK.ENC.SEM.v1",
    source_tags=["ml", "tokenizer", "encoding"],
    telemetry_mode=TelemetryMode.LIGHT,
)
zone.write("sample", {"token": 1})
print(zone.read("sample"))
print(zone.telemetry_snapshot())
print(fs.capability_snapshot())

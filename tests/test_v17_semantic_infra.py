import json

import numpy as np

from staqtapp_tds import (
    TDSFileSystem,
    TDSPersistence,
    ManifestPolicy,
    TelemetryMode,
    LatencyBucket,
    ZoneCapability,
    load_manifest,
    write_default_manifest,
    route_id_for,
    SRZ_DTYPE,
)


def test_manifest_default_and_inheritance(tmp_path):
    write_default_manifest(tmp_path)
    child = tmp_path / "a" / "b"
    child.mkdir(parents=True)
    policy = load_manifest(child, inherit=True)
    assert policy.schema_version == "1.7.3"
    assert policy.manifest_hash
    assert policy.capabilities.supports(ZoneCapability.SRZ)


def test_optional_srz_directory_metadata_and_compact_record():
    fs = TDSFileSystem("root")
    plain = fs.root.mkdir("plain")
    semantic = fs.root.mkdir(
        "tokenizers",
        srz_enabled=True,
        route_stamp="ML.TOK.ENC.SEM.v1",
        source_tags=["ml", "tokenizer"],
        aliases=["semantic-token-map"],
    )
    assert not plain.srz.enabled
    assert semantic.srz.enabled
    assert semantic.srz.route_id == route_id_for("ML.TOK.ENC.SEM.v1", semantic.path())
    rec = semantic.srz_record()
    assert rec.dtype == SRZ_DTYPE
    assert int(rec["route_id"][0]) == semantic.srz.route_id


def test_directory_telemetry_light_mode_records_hits_and_misses():
    fs = TDSFileSystem("root")
    d = fs.root.mkdir("fast", telemetry_mode=TelemetryMode.LIGHT, expected_lookup_ns=1)
    d.write("x", b"payload")
    assert d.read("x") == b"payload"
    try:
        d.read("missing")
    except KeyError:
        pass
    snap = d.telemetry_snapshot()
    assert snap["hits"] >= 1
    assert snap["misses"] >= 1
    assert snap["bucket"] in {b.name.lower() for b in LatencyBucket}


def test_capability_snapshot_exposes_zone_features():
    fs = TDSFileSystem("root")
    fs.root.mkdir("srz", srz_enabled=True)
    caps = fs.capability_snapshot()
    assert "telemetry" in caps["/root"]
    assert "srz" in caps["/root/srz"]


def test_persistence_writes_manifest_and_preserves_srz_telemetry(tmp_path):
    fs = TDSFileSystem("root")
    d = fs.root.mkdir("zone", srz_enabled=True, route_stamp="ZONE.TEST.v1")
    d.write("a", {"v": 1})
    d.read("a")
    p = TDSPersistence(tmp_path)
    p.flush(fs, parallel_nodes=False)
    assert (tmp_path / ".tds_manifest").exists()
    meta = json.loads((tmp_path / "root__zone.tds.meta").read_text())
    assert meta["srz"]["enabled"] is True
    assert meta["telemetry"]["hits"] >= 1
    loaded = p.load_node(tmp_path / "root__zone.tds")
    assert loaded.srz.enabled is True
    assert loaded.srz.route_stamp == "ZONE.TEST.v1"
    assert loaded.telemetry.snapshot()["hits"] >= 1

from staqtapp_tds import ReservedNamespaces


def test_reserved_namespaces_block_accidental_directory_creation():
    reserved = ReservedNamespaces(directory_names=("future_zone",))
    policy = ManifestPolicy.from_dict({"reserved_namespaces": reserved.to_dict(), "capabilities": ["reserved_namespaces"]})
    fs = TDSFileSystem("root", manifest_policy=policy)
    assert fs.root.is_reserved_namespace("future_zone")
    try:
        fs.root.mkdir("future_zone")
        raised = False
    except ValueError:
        raised = True
    assert raised
    child = fs.root.mkdir("future_zone", allow_reserved=True)
    assert child.name == "future_zone"
    assert "reserved_namespaces" in fs.root.capability_names()

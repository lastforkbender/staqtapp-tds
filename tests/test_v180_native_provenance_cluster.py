import pytest
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from staqtapp_tds import EntryIndex, TDSDirectory, ProvenanceClass, ProvenanceTag, TDSClusterIdentity, query_requires_selector


def test_native_index_backend_if_extension_available():
    idx = EntryIndex(backend="auto")
    h1 = idx.put("alpha", {"v": 1})
    h2 = idx.put("beta", {"v": 2})
    assert idx.get_handle("alpha") == h1
    assert idx.get("beta") == {"v": 2}
    assert "alpha" in idx
    assert idx.pop("alpha") == {"v": 1}
    assert idx.get_handle("alpha") == -1
    stats = idx.stats()
    assert stats.size == 1
    assert stats.backend in {"python-sharded", "native-c-handle-index", "native-c-swiss-entryindex"}


def test_native_backend_can_be_forced_after_build():
    try:
        idx = EntryIndex(backend="native")
    except RuntimeError:
        return
    if 'native' not in idx.backend_name:
        pytest.skip('native backend not active on this interpreter')
    h = idx.put("route::one", "payload")
    assert idx.backend_name in {"native-c", "native-c-handle-index", "native-c-swiss"}
    assert idx.get_handle("route::one") == h
    assert idx.get("route::one") == "payload"
    assert idx.stats().backend in {"native-c-handle-index", "native-c-swiss-entryindex"}


def test_provenance_tags_on_text_json_and_variables():
    d = TDSDirectory("root")
    r = d.write_text("real.txt", "observed source", provenance="REAL")
    assert r.ok
    meta = d.entry_metadata("real.txt")
    assert meta["provenance"]["provenance"] == "REAL"
    rec = d.provenance_record("real.txt")
    assert rec.dtype.names == ("entry_id", "source_id", "class_id", "trust_q16", "flags")
    assert int(rec["class_id"][0]) == int(ProvenanceClass.REAL)
    p = ProvenanceTag.create("SYNTHETIC", source_id="gen-a", trust=0.25)
    d.write("var", {"a": 1}, provenance=p)
    assert d.entry_metadata("var")["provenance"]["source_id"] == "gen-a"


def test_cluster_identity_feedback_and_query_selector_guard():
    c = TDSClusterIdentity("alpha")
    c.add_shard("shards/shard_000001.tds")
    fb = c.feedback(entry_count=10, provenance_counts={"REAL": 4, "SYNTHETIC": 6})
    assert fb["cluster_id"]
    assert fb["shard_count"] == 1
    rec = c.compact_record(entry_count=10, provenance_counts={"REAL": 4, "SYNTHETIC": 6})
    assert int(rec["real_count"][0]) == 4
    assert not query_requires_selector().ok
    assert query_requires_selector(route_stamp="ML.TEST").ok

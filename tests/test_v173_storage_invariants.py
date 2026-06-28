
from pathlib import Path

from staqtapp_tds import TDSFileSystem, TDSPersistence, FmtID, InvariantEngine


def test_variable_serializer_lanes_and_metadata():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    assert d.addvar('cfg', {'a': 1, 'b': [2, 3]}).ok
    assert d.addvar('obj', ({'tuple': True}, 7)).ok

    cfg_meta = d.entry_metadata('cfg')
    obj_meta = d.entry_metadata('obj')
    assert cfg_meta['payload_kind'] == 'JSON_UTF8'
    assert cfg_meta['content_hash']
    assert obj_meta['payload_kind'] == 'PICKLE_OBJ'
    assert d.read('cfg') == {'a': 1, 'b': [2, 3]}
    assert d.read('obj') == ({'tuple': True}, 7)


def test_text_metadata_hash_and_compression_threshold():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/source')
    d.compression_policy = d.compression_policy.__class__(enabled=True, threshold_bytes=16)
    r = d.write_text('notes.md', 'x' * 128)
    assert r.ok
    meta = d.entry_metadata('notes.md')
    assert meta['payload_kind'] == 'TEXT_UTF8'
    assert meta['compressed'] is True
    assert meta['raw_size'] == 128
    assert meta['stored_size'] > 0
    assert d.read_text('notes.md') == 'x' * 128


def test_json_entry_roundtrip_and_persistence(tmp_path: Path):
    fs = TDSFileSystem('root')
    d = fs.makedirs('/json')
    assert d.write_json('config.json', {'name': 'tds', 'n': 3}).ok
    assert d.read('config.json') == {'name': 'tds', 'n': 3}
    p = TDSPersistence(tmp_path)
    p.flush(fs, parallel_nodes=False)
    loaded = p.load_node(tmp_path / 'root__json.tds')
    assert loaded.read('config.json') == {'name': 'tds', 'n': 3}
    assert loaded.entry_metadata('config.json')['payload_kind'] == 'JSON_UTF8'


def test_invariant_engine_reports_clean_and_broken_stalk_chain():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    d.addvar('v', [1])
    d.stalkvar('~v', [2])
    report = InvariantEngine().evaluate_directory(d)
    assert report.ok, report.as_dict()

    # Simulate corruption/entropy: tracked chain name missing from namespace.
    d.delete('v_0001')
    broken = InvariantEngine().evaluate_directory(d)
    codes = {v.code for v in broken.violations}
    assert not broken.ok
    assert 'STALK_LATEST_MISSING' in codes or 'STALK_CHAIN_MISSING' in codes


def test_invariant_engine_entry_limit():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    d.addvar('a', 1)
    d.addvar('b', 2)
    report = InvariantEngine(max_entries=1).evaluate_directory(d)
    assert not report.ok
    assert any(v.code == 'ENTRY_COUNT_LIMIT' for v in report.violations)

def test_chunked_text_roundtrip_and_overwrite():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/source')
    text = 'abcdef' * 100
    r = d.write_text_chunked('long.md', text, chunk_size=10)
    assert r.ok and r.meta['chunks'] > 1
    assert d.read_text('long.md') == text
    dup = d.write_text_chunked('long.md', 'other', chunk_size=2)
    assert not dup.ok and dup.code == 'TEXT_EXISTS'
    ow = d.write_text_chunked('long.md', 'other', chunk_size=2, overwrite=True)
    assert ow.ok
    assert d.read_text('long.md') == 'other'

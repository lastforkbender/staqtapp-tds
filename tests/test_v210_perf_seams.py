from __future__ import annotations

import pytest

from staqtapp_tds import TDSFileSystem, RadixDirectoryRouter
from staqtapp_tds.index import EntryIndex


def test_chunked_text_uses_utf8_byte_budget_without_splitting_codepoints():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/unicode')
    text = 'a😀bé𝄞' * 8
    raw = text.encode('utf-8')
    result = d.write_text_chunked('unicode.txt', text, chunk_size=5)
    assert result.ok
    assert d.read_text('unicode.txt') == text
    manifest = d.read('unicode.txt').value
    assert manifest['chunk_size_unit'] == 'utf8_bytes'
    for chunk_name in manifest['chunks']:
        chunk = d.read(chunk_name).value
        encoded = chunk.encode('utf-8')
        # Some chunks may exceed the budget only when a single UTF-8 code point
        # is wider than the budget. With a 5-byte budget here every emitted
        # chunk must stay within the byte target.
        assert len(encoded) <= 5
        encoded.decode('utf-8')
    assert manifest['raw_size'] == len(raw)


def test_entryindex_batch_handles_and_swiss_probe_stats():
    idx = EntryIndex(backend='auto')
    keys = [f'k{i:04d}' for i in range(256)]
    for i, key in enumerate(keys):
        idx.put(key, i)
    handles = idx.get_handles(keys + ['missing'])
    assert all(h > 0 for h in handles[:-1])
    assert handles[-1] == -1
    stats = idx.stats()
    assert stats.size == 256
    if 'native' in idx.backend_name:
        raw = idx._impl._index.stats()
        assert raw['gil_released_get_handles'] is True
        assert raw['gil_released_pop_lookup'] is True
        assert raw['tombstones'] == 0
        assert raw['load_factor'] > 0
        assert raw['max_probe'] >= 1
        assert raw['avg_probe'] >= 1.0


def test_native_tombstone_reuse_and_delete_reinsert_if_available():
    try:
        idx = EntryIndex(backend='native')
    except RuntimeError:
        pytest.skip('native backend not built on this interpreter')
    for i in range(512):
        idx.put(f'item-{i}', i)
    for i in range(0, 512, 2):
        assert idx.pop(f'item-{i}') == i
    if 'native' not in idx.backend_name:
        pytest.skip('native backend not active on this interpreter')
    raw = idx._impl._index.stats()
    assert raw['tombstones'] > 0
    for i in range(0, 512, 2):
        idx.put(f'item-{i}', i * 10)
    assert len(idx) == 512
    assert idx.get('item-10') == 100


def test_radix_stats_include_depth_and_lookup_cost():
    r = RadixDirectoryRouter[int]()
    for i, key in enumerate(['alpha', 'alphabet', 'alphanumeric', 'alpine', 'beta']):
        r.insert(key, i)
    stats = r.stats()
    assert stats['nodes'] >= 1
    assert stats['edges'] >= 1
    assert stats['max_depth'] >= 1
    assert stats['average_edge_length'] > 0
    assert stats['average_lookup_steps'] > 0
    assert r.lookup_steps('alphanumeric') >= 1

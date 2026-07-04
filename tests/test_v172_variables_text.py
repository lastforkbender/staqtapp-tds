from pathlib import Path

import pytest

from staqtapp_tds import TDSFileSystem, TDSPersistence


def test_addvar_duplicate_is_status_not_exception():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    r1 = d.addvar('alpha', {'a': 1})
    r2 = d.addvar('alpha', {'b': 2})
    assert r1.ok and r1.code == 'VAR_ADDED'
    assert not r2.ok and r2.code == 'VAR_EXISTS'
    assert d.read_value('alpha') == {'a': 1}


def test_editvar_and_lockvar_statuses():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    assert d.addvar('x', 1).ok
    assert d.lockvar('x').ok
    blocked = d.editvar('x', 2)
    assert not blocked.ok and blocked.code == 'VAR_LOCKED'
    assert d.read_value('x') == 1
    assert d.unlockvar('x').ok
    edited = d.editvar('x', 2)
    assert edited.ok and d.read_value('x') == 2


def test_stalkvar_linear_compound_and_clear_keep_base():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    assert d.addvar('new_var', {'a': 1}).ok
    r1 = d.stalkvar('~new_var', {'b': 2})
    r2 = d.stalkvar('~new_var', {'c': 3})
    assert r1.ok and r1.name == 'new_var_0001'
    assert r2.ok and r2.name == 'new_var_0002'
    assert d.read_value('new_var') == {'a': 1}
    assert d.read_value('new_var_0001') == {'a': 1, 'b': 2}
    assert d.read_value('new_var_0002') == {'a': 1, 'b': 2, 'c': 3}
    cleared = d.stalkvar('new_var', None)
    assert cleared.ok and cleared.code == 'VAR_STALK_CLEARED'
    assert d.read_value('new_var') == {'a': 1}
    with pytest.raises(KeyError):
        d.read_value('new_var_0001')
    with pytest.raises(KeyError):
        d.read_value('new_var_0002')


def test_stalkvar_clear_and_replace_base():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    d.addvar('v', [1])
    d.stalkvar('~v', [2])
    d.stalkvar('~v', [3])
    replaced = d.stalkvar('v', [9])
    assert replaced.ok and replaced.code == 'VAR_EDITED'
    assert d.read_value('v') == [9]
    with pytest.raises(KeyError):
        d.read_value('v_0001')


def test_stalkvar_without_chain_behaves_like_editvar_when_data_present():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    d.addvar('my_var', 1)
    r = d.stalkvar('my_var', 5)
    assert r.ok and r.code == 'VAR_EDITED'
    assert d.read_value('my_var') == 5
    noop = d.stalkvar('my_var', None)
    assert noop.ok and noop.code == 'VAR_NOOP'
    assert d.read_value('my_var') == 5


def test_text_storage_duplicate_and_overwrite():
    fs = TDSFileSystem('root')
    d = fs.makedirs('/source')
    r1 = d.write_text('README.md', '# Hello')
    r2 = d.write_text('README.md', '# Other')
    r3 = d.write_text('README.md', '# Other', overwrite=True)
    assert r1.ok and r1.code == 'TEXT_WRITTEN'
    assert not r2.ok and r2.code == 'TEXT_EXISTS'
    assert r3.ok and r3.code == 'TEXT_OVERWRITTEN'
    assert d.read_text('README.md') == '# Other'


def test_variable_and_text_persistence_roundtrip(tmp_path: Path):
    fs = TDSFileSystem('root')
    d = fs.makedirs('/vars')
    d.addvar('state', {'base': True})
    d.stalkvar('~state', {'step': 1})
    d.stalkvar('~state', {'step': 2})
    d.lockvar('state')
    src = fs.makedirs('/source')
    src.write_text('notes.md', 'alpha\nbeta', compress=True)

    p = TDSPersistence(tmp_path)
    p.flush(fs, parallel_nodes=False)

    loaded_vars = p.load_node(tmp_path / 'root__vars.tds')
    assert loaded_vars.read_value('state') == {'base': True}
    assert loaded_vars.read_value('state_0001') == {'base': True, 'step': 1}
    assert loaded_vars.read_value('state_0002') == {'base': True, 'step': 2}
    assert loaded_vars.variables.is_locked('state') is True
    assert not loaded_vars.stalkvar('state', None).ok
    loaded_vars.unlockvar('state')
    clear = loaded_vars.stalkvar('state', None)
    assert clear.ok and clear.meta['removed'] == ['state_0001', 'state_0002']

    loaded_src = p.load_node(tmp_path / 'root__source.tds')
    assert loaded_src.read_text('notes.md') == 'alpha\nbeta'

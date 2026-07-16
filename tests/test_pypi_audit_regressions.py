import os
from pathlib import Path
import numpy as np
import pytest
from staqtapp_tds import TDSFileSystem, TDSPersistence, FmtID, DirFlags, CompressorRegistry, TDSResultCode
from staqtapp_tds.tds_persistence import TDSReader, TDSPersistenceIntegrityError


def test_collision_free_node_filenames(tmp_path):
    fs=TDSFileSystem('root')
    fs.root.mkdir('a').mkdir('b')
    fs.root.mkdir('a__b')
    p=TDSPersistence(tmp_path)
    paths=p.flush(fs, parallel_nodes=False)
    assert len(paths)==4
    assert len(set(paths))==4


def test_entry_name_with_slash_round_trips(tmp_path):
    fs=TDSFileSystem('root')
    fs.root.write_text('a/x','one')
    fs.root.write_text('x','two')
    p=TDSPersistence(tmp_path)
    path,_=p.flush_node(fs.root)
    loaded=p.load_node(path)
    assert loaded.read_value('a/x')=='one'
    assert loaded.read_value('x')=='two'


def test_numpy_is_frozen_at_write(tmp_path):
    fs=TDSFileSystem('root')
    a=np.array([1])
    fs.root.write_entry('a',a,fmt_id=FmtID.NUMPY_MATRIX)
    a[0]=2
    p=TDSPersistence(tmp_path)
    path,_=p.flush_node(fs.root)
    loaded=p.load_node(path)
    assert loaded.read_value('a').tolist()==[1]


def test_locked_variable_blocks_generic_mutation():
    fs=TDSFileSystem('root')
    d=fs.root
    assert d.addvar('v',1).ok
    assert d.lockvar('v').ok
    assert d.write('v',2).code==TDSResultCode.VAR_LOCKED
    assert d.delete('v').code==TDSResultCode.VAR_LOCKED
    assert d.read_value('v')==1


def test_unknown_codec_fails():
    with pytest.raises(KeyError):
        CompressorRegistry.compress(b'abc','not-a-codec')


def test_encryption_flag_fails_closed():
    with pytest.raises(NotImplementedError):
        TDSFileSystem('root').root.mkdir('secret', flags=DirFlags.ENCRYPTED)


def test_v2_missing_sidecar_fails(tmp_path):
    fs=TDSFileSystem('root')
    fs.root.write_text('safe','safe')
    p=TDSPersistence(tmp_path)
    path,_=p.flush_node(fs.root)
    Path(path).with_suffix('.tds.meta').unlink()
    with pytest.raises(TDSPersistenceIntegrityError):
        TDSReader(path)


def test_duplicate_mkdir_rejected():
    fs=TDSFileSystem('root')
    fs.root.mkdir('a')
    with pytest.raises(FileExistsError):
        fs.root.mkdir('a')


def test_parallel_batch_returns_results():
    fs=TDSFileSystem('root')
    out=fs.parallel_batch_write([('/', 'a', 1), ('/', 'b', 2)])
    assert len(out)==2 and all(r.ok for r in out)

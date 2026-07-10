from __future__ import annotations

from staqtapp_tds import TDSDirectory, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    detect_csv_dialect,
    import_csv_bytes,
    load_csv_artifact,
    logical_record_offsets,
    logical_record_offsets_bytes,
)


class CountingDirectory(TDSDirectory):
    def __init__(self, name: str):
        super().__init__(name)
        self.text_writes = 0
        self.json_writes = 0

    def write_text(self, *args, **kwargs):
        self.text_writes += 1
        return super().write_text(*args, **kwargs)

    def write_json(self, *args, **kwargs):
        self.json_writes += 1
        return super().write_json(*args, **kwargs)


def test_version_321_csv_foundation_shape_pass():
    assert __version__ == "3.5.2"


def test_memoryview_row_offset_scanner_matches_text_contract_for_quoted_records():
    text = 'id,note\r\n1,"hello\nworld"\r\n2,"done"\r\n3,"quote "" kept"\r\n'
    raw = text.encode("utf-8")
    dialect = detect_csv_dialect(text)

    text_offsets = logical_record_offsets(text, dialect)
    byte_offsets = logical_record_offsets_bytes(raw, dialect)

    assert byte_offsets == text_offsets
    assert len(byte_offsets) == 4
    assert raw[byte_offsets[1]:].decode("utf-8").startswith('1,"hello')
    assert raw[byte_offsets[2]:].decode("utf-8").startswith('2,"done"')


def test_csv_import_uses_fixed_artifact_write_shape_not_per_cell_writes():
    directory = CountingDirectory("root")
    rows = ["c1,c2,c3"] + [f"{i},{i + 1},{i + 2}" for i in range(250)]
    payload = ("\n".join(rows) + "\n").encode("utf-8")

    manifest = import_csv_bytes(directory, payload, source_name="shape.csv")
    report = load_csv_artifact(directory, manifest.csv_id, "import_report")
    keys = artifact_keys(manifest.csv_id)

    assert manifest.row_count == 251
    assert manifest.column_count == 3
    assert directory.text_writes == 1
    assert directory.json_writes == 5
    assert report["artifact_write_count"] == 6
    assert report["raw_artifact_count"] == 1
    assert report["derived_artifact_count"] == 5
    assert report["per_cell_writes"] is False
    assert directory.read_value(keys["row_offsets"])["row_count"] == 251


def test_csv_import_handles_larger_quoted_csv_without_reader_offset_drift():
    directory = CountingDirectory("root")
    rows = ["id,note"]
    for i in range(1024):
        note = f"line {i} first\nline {i} second" if i % 17 == 0 else f"line {i} flat"
        rows.append(f'{i},"{note}"')
    payload = ("\n".join(rows) + "\n").encode("utf-8")

    manifest = import_csv_bytes(directory, payload, source_name="quoted_large.csv")
    row_offsets = load_csv_artifact(directory, manifest.csv_id, "row_offsets")

    assert manifest.row_count == 1025
    assert row_offsets["row_count"] == manifest.row_count
    assert not manifest.warnings

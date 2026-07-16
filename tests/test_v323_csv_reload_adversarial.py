from __future__ import annotations

from pathlib import Path

from staqtapp_tds import TDSDirectory, TDSFileSystem, TDSPersistence, __version__
from staqtapp_tds.csv_layer import (
    artifact_keys,
    import_csv_bytes,
    load_csv_artifact,
    reload_csv_artifacts,
    validate_csv_artifacts,
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


def test_version_323_csv_reload_adversarial_pass():
    assert __version__ == "3.5.3"


def test_csv_reload_artifacts_from_persisted_tds_snapshot_without_import_objects(tmp_path: Path):
    fs = TDSFileSystem("root")
    payload = 'id,note\r\n1,"hello\nworld"\r\n2,"quote "" kept"\r\n'.encode("utf-8")
    manifest = import_csv_bytes(fs.root, payload, source_name="reload.csv")

    persist = TDSPersistence(tmp_path / "mount")
    persist.flush(fs, parallel_nodes=False)
    loaded = persist.load_node(tmp_path / "mount" / "root.tds")

    reloaded = reload_csv_artifacts(loaded, manifest.csv_id)

    assert reloaded.ok is True
    assert reloaded.validation_report.primary_result_code == "csv.validation.valid"
    assert reloaded.validation_report.result_codes == ("csv.validation.valid",)
    assert reloaded.manifest.to_dict() == manifest.to_dict()
    assert reloaded.raw.encode("utf-8") == payload
    assert reloaded.row_offsets.row_count == manifest.row_count
    assert reloaded.content_hashes["raw_sha256"] == manifest.raw_sha256
    assert reloaded.import_report["artifact_write_count"] == 6


def test_csv_adversarial_corpus_remains_artifact_valid_after_reload(tmp_path: Path):
    cases = {
        "mixed_newlines.csv": b"a,b\r\n1,2\n3,4\r5,6\n",
        "quoted_delimiter.csv": b'id,note\n1,"comma, inside"\n2,"semi; inside"\n',
        "quoted_newline.csv": b'id,note\n1,"line one\nline two"\n2,done\n',
        "doubled_quotes.csv": b'id,note\n1,"quote "" kept"\n2,"""edge"""\n',
        "tabs.tsv": b"id\tnote\n1\talpha\n2\tbeta\n",
        "pipes.psv": b"id|note\n1|alpha\n2|beta\n",
        "unicode.csv": "id,name\n1,Åsa\n2,東京\n".encode("utf-8"),
        "empty_fields.csv": b"a,b,c\n1,,3\n,,\n",
        "no_terminal_newline.csv": b"a,b\n1,2",
        "unterminated_quote.csv": b'id,note\n1,"still a single logical record\n2,inside quote\n',
    }
    fs = TDSFileSystem("root")
    expected_raw: dict[str, bytes] = {}

    for name, payload in cases.items():
        manifest = import_csv_bytes(fs.root, payload, source_name=name)
        expected_raw[manifest.csv_id] = payload

    persist = TDSPersistence(tmp_path / "mount")
    persist.flush(fs, parallel_nodes=False)
    loaded = persist.load_node(tmp_path / "mount" / "root.tds")

    for csv_id, payload in expected_raw.items():
        reloaded = reload_csv_artifacts(loaded, csv_id)
        assert reloaded.ok is True, (csv_id, reloaded.validation_report.errors)
        assert reloaded.raw.encode(reloaded.manifest.encoding) == payload
        assert reloaded.validation_report.raw_sha256_verified is True
        assert reloaded.validation_report.row_offsets_verified is True
        assert reloaded.validation_report.derived_artifacts_only is True
        assert reloaded.validation_report.native_storage_hot_path_touched is False


def test_csv_validator_result_codes_fail_closed_for_bad_numeric_artifacts():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="bad_numeric.csv")
    content_hashes = load_csv_artifact(fs.root, manifest.csv_id, "content_hashes")
    content_hashes["row_count"] = "not-an-integer"
    fs.root.write_json(manifest.artifact_keys["content_hashes"], content_hashes, overwrite=True, provenance="DERIVED")

    report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is False
    assert report.primary_result_code == "csv.validation.invalid"
    assert "content_hashes_row_count_not_integer" in report.errors
    assert "csv.validation.error.content_hashes_row_count_not_integer" in report.result_codes
    assert report.to_dict()["primary_result_code"] == "csv.validation.invalid"


def test_csv_validator_tightens_import_report_shape_fields():
    fs = TDSFileSystem("root")
    manifest = import_csv_bytes(fs.root, b"a,b\n1,2\n", source_name="shape_tight.csv")
    import_report = load_csv_artifact(fs.root, manifest.csv_id, "import_report")
    import_report["status"] = "partial"
    import_report["raw_artifact_count"] = 2
    import_report["derived_artifact_count"] = 500
    fs.root.write_json(manifest.artifact_keys["import_report"], import_report, overwrite=True, provenance="DERIVED")

    report = validate_csv_artifacts(fs.root, manifest.csv_id)

    assert report.ok is False
    assert "import_report_status_mismatch" in report.errors
    assert "import_report_raw_artifact_count_mismatch" in report.errors
    assert "import_report_derived_artifact_count_mismatch" in report.errors
    assert "csv.validation.error.import_report_status_mismatch" in report.result_codes


def test_large_csv_reload_sanity_keeps_fixed_artifact_write_shape(tmp_path: Path):
    directory = CountingDirectory("root")
    rows = ["id,value,note"]
    for i in range(4096):
        note = f"quoted line {i} first\nquoted line {i} second" if i % 113 == 0 else f"flat {i}"
        rows.append(f'{i},{i * 3},"{note}"')
    payload = ("\n".join(rows) + "\n").encode("utf-8")

    manifest = import_csv_bytes(directory, payload, source_name="large_reload.csv")
    keys = artifact_keys(manifest.csv_id)

    assert directory.text_writes == 1
    assert directory.json_writes == 5
    assert manifest.row_count == 4097
    assert directory.read_value(keys["import_report"])["artifact_write_count"] == 6

    fs = TDSFileSystem("root")
    fs.root = directory
    persist = TDSPersistence(tmp_path / "mount")
    persist.flush(fs, parallel_nodes=False)
    loaded = persist.load_node(tmp_path / "mount" / "root.tds")
    reloaded = reload_csv_artifacts(loaded, manifest.csv_id)

    assert reloaded.ok is True
    assert reloaded.raw.encode("utf-8") == payload
    assert reloaded.validation_report.row_offsets_verified is True

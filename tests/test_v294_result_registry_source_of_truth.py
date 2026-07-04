import ast
import json
from pathlib import Path

from staqtapp_tds.result import (
    TDSResult,
    TDSResultCode,
    TDS_RESULT_CODES,
    TDS_RESULT_REGISTRY,
    is_known_result_code,
    result_info,
)


ROOT = Path(__file__).resolve().parents[1]


def test_result_registry_is_enum_backed_source_of_truth():
    enum_codes = {code.value for code in TDSResultCode}
    registry_codes = {code.value for code in TDS_RESULT_REGISTRY}
    public_codes = set(TDS_RESULT_CODES)
    assert enum_codes == registry_codes == public_codes
    assert is_known_result_code(TDSResultCode.READ_OK)
    assert result_info(TDSResultCode.PAYLOAD_DESERIALIZE_ERROR).category == "serialization"


def test_tds_result_accepts_enum_but_serializes_stable_string():
    result = TDSResult.success(TDSResultCode.WRITE_OK, "written")
    assert result.code == "WRITE_OK"
    assert result.as_dict()["code"] == "WRITE_OK"
    assert result.known_code is True
    assert result.info.surface == "TDSDirectory.write/write_result"


def test_docs_json_generated_from_registry_without_drift():
    docs = json.loads((ROOT / "docs" / "TDS_RESULT_CODES.json").read_text())
    assert docs == {code: TDS_RESULT_CODES[code] for code in sorted(TDS_RESULT_CODES)}


def test_public_result_call_sites_do_not_hard_code_result_code_literals():
    codes = {code.value for code in TDSResultCode}
    violations = []
    for path in (ROOT / "src" / "staqtapp_tds").rglob("*.py"):
        if path.name == "result.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in codes:
                violations.append((str(path.relative_to(ROOT)), node.lineno, node.value))
    assert violations == []

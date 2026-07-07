import pytest

from staqtapp_tds import __version__
from staqtapp_tds.drivers import (
    InstructionName,
    TDDLValidationError,
    instruction_specs,
    parse_tddl,
)


VALID_SEARCH_DRIVER = '''
driver SearchPolicyDrivers v1

manifest:
  kind = "search"
  description = "Find policy-related driver manifests"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read
  capability trace.write
  adapter predicate.semantic_manifest.v1
  adapter scorer.trace_rank.v1

limits:
  max_scan = 5000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=5000 depth=8
  READ target="manifest"
  MATCH field="manifest.kind" eq="driver"
  MATCH using="predicate.semantic_manifest.v1" query="policy routing" threshold=0.82
  EXTRACT from="manifest" fields=["driver_id", "version", "path", "capabilities", "safety"]
  SCORE using="scorer.trace_rank.v1" weight="semantic" threshold=0.75
  TRACE event="policy_driver_candidate"
  EMIT mode="ranked" limit=25
  HALT

evolution:
  allow reorder MATCH SCORE
  allow replace SCORE from registry
  deny external_io
  max_delta = 2
'''


def test_v306_version():
    assert __version__ == "3.1.23"


def test_tddl_valid_search_driver_parses_to_ir():
    program = parse_tddl(VALID_SEARCH_DRIVER)

    assert program.driver_id == "SearchPolicyDrivers"
    assert program.version == 1
    assert program.manifest["kind"] == "search"
    assert program.capabilities == ("registry.scan", "manifest.read", "trace.write")
    assert "predicate.semantic_manifest.v1" in program.adapters
    assert program.instruction_names == (
        "SCAN",
        "READ",
        "MATCH",
        "MATCH",
        "EXTRACT",
        "SCORE",
        "TRACE",
        "EMIT",
        "HALT",
    )
    assert program.instructions[-1].name is InstructionName.HALT


def test_instruction_metadata_table_is_self_describing_for_future_studio():
    specs = instruction_specs()
    assert set(specs) >= {"SCAN", "READ", "MATCH", "EXTRACT", "SCORE", "EMIT", "HALT"}
    assert "scope" in specs["SCAN"].required
    assert "target" in specs["READ"].required
    assert "using" in specs["MATCH"].optional
    assert "fields" in specs["EXTRACT"].optional


@pytest.mark.parametrize(
    "bad_line,error",
    [
        ('SCAN scope="/etc" recursive=true', "scope"),
        ('SCAN scope="../.tds" recursive=true', "scope"),
        ('CALL adapter="python.eval"', "unsafe"),
        ('MATCH regex_unbounded=".*"', "unknown operands"),
        ('MATCH regex_limited=".*.*"', "too broad"),
        ('MATCH using="predicate.semantic_manifest.v1" query="policy" threshold=2.0', "threshold"),
        ('EXTRACT from="raw_pickle" fields=["x"]', "unsupported value"),
        ('SCORE using="scorer.trace_rank.v1" weight="wild"', "unsupported value"),
    ],
)
def test_tddl_fails_closed_for_dangerous_or_unknown_search_parameters(bad_line, error):
    source = VALID_SEARCH_DRIVER.replace('SCAN scope=".tds" recursive=true limit=5000 depth=8', bad_line, 1)
    with pytest.raises(TDDLValidationError, match=error):
        parse_tddl(source)


def test_tddl_rejects_adapter_use_not_declared_in_requires():
    source = VALID_SEARCH_DRIVER.replace(
        'MATCH using="predicate.semantic_manifest.v1" query="policy routing" threshold=0.82',
        'MATCH using="predicate.undeclared.v1" query="policy" threshold=0.82',
    )
    with pytest.raises(TDDLValidationError, match="declared"):
        parse_tddl(source)


def test_tddl_requires_halt_as_final_instruction():
    source = VALID_SEARCH_DRIVER.replace("  HALT\n\nevolution:", "  TRACE event=\"after_halt\"\n\nevolution:")
    with pytest.raises(TDDLValidationError, match="HALT"):
        parse_tddl(source)


def test_tddl_rejects_scan_over_limit():
    source = VALID_SEARCH_DRIVER.replace("limit=5000", "limit=5001", 1)
    with pytest.raises(TDDLValidationError, match="SCAN.limit"):
        parse_tddl(source)


def test_tddl_rejects_missing_capabilities():
    source = VALID_SEARCH_DRIVER.replace(
        '''requires:\n  capability registry.scan\n  capability manifest.read\n  capability trace.write\n  adapter predicate.semantic_manifest.v1\n  adapter scorer.trace_rank.v1''',
        '''requires:\n  adapter predicate.semantic_manifest.v1\n  adapter scorer.trace_rank.v1''',
    )
    with pytest.raises(TDDLValidationError, match="capability"):
        parse_tddl(source)


def test_tddl_rejects_unknown_evolution_rule():
    source = VALID_SEARCH_DRIVER.replace("  deny external_io", "  mutate freely")
    with pytest.raises(TDDLValidationError, match="evolution"):
        parse_tddl(source)


def test_tddl_valid_extract_driver_parameters():
    source = '''
driver ExtractTelemetrySummary v1

manifest:
  kind = "extract"
  description = "Extract telemetry summary records"

requires:
  capability registry.scan
  capability payload.read
  adapter extractor.telemetry_summary.v1

limits:
  max_scan = 1000
  max_extract = 100
  timeout_ms = 300

program:
  SCAN scope=".tds/telemetry" recursive=false limit=1000 depth=2
  READ target="payload_header"
  MATCH field="type" eq="telemetry_summary"
  EXTRACT using="extractor.telemetry_summary.v1" from="payload_header" required=true
  EMIT mode="list" limit=100
  HALT
'''
    program = parse_tddl(source)
    assert program.driver_id == "ExtractTelemetrySummary"
    assert program.instructions[3].name is InstructionName.EXTRACT
    assert program.instructions[3].operands["using"] == "extractor.telemetry_summary.v1"

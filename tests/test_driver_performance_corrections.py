from __future__ import annotations

from types import SimpleNamespace

import staqtapp_tds.drivers.audit as audit_module
import staqtapp_tds.drivers.bytecode as bytecode_module
import staqtapp_tds.drivers.performance as performance_module
import staqtapp_tds.drivers.studio as studio_module
import staqtapp_tds.drivers.studio_builder as studio_builder_module
import staqtapp_tds.drivers.tddl as tddl_module
import staqtapp_tds.drivers.vm as vm_module
from staqtapp_tds.drivers import (
    BytecodePackage,
    DriverFoundry,
    DriverRuntimeManager,
    DriverStudioAdminReviewActions,
    DriverStudioConsoleSnapshot,
    DriverStudioManualProposalBuilder,
    DriverStudioReadOnlyConsole,
    DriverVMRuntime,
    EvidenceIntegrityStatus,
    ReviewAction,
    StudioManualDriverTask,
    StudioReviewActionRequest,
    StudioReviewSubmissionStatus,
    compile_program,
    compile_tddl,
    parse_tddl,
    run_studio_quick_test,
)


DRIVER_SOURCE = '''
driver DriverPerfCorrections v1

manifest:
  kind = "search"
  description = "Exercise bounded driver performance corrections"
  safety = "bounded"

requires:
  capability registry.scan
  capability manifest.read
  capability trace.write
  adapter scorer.trace_rank.v1

limits:
  max_scan = 1000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=1000 depth=8
  READ target="manifest"
  MATCH field="manifest.kind" eq="driver"
  EXTRACT from="manifest" fields=["driver_id", "capabilities"] limit=1000
  SCORE using="scorer.trace_rank.v1" threshold=0.0
  TRACE event="driver_perf_correction"
  EMIT mode="list" limit=1000
  HALT

evolution:
  deny external_io
'''


RECORDS = [
    {
        "path": ".tds/drivers/a",
        "manifest": {"kind": "driver", "driver_id": "A", "capabilities": ["search"]},
        "semantic_score": 0.9,
    },
    {
        "path": ".tds/drivers/b",
        "manifest": {"kind": "driver", "driver_id": "B", "capabilities": ["extract"]},
        "semantic_score": 0.8,
    },
]


def test_source_compile_and_foundry_each_walk_tddl_validation_once(monkeypatch):
    calls = 0
    original = tddl_module.validate_tddl

    def counted(program):
        nonlocal calls
        calls += 1
        return original(program)

    monkeypatch.setattr(tddl_module, "validate_tddl", counted)

    assert compile_tddl(DRIVER_SOURCE).verify_hash()
    assert calls == 1

    calls = 0
    result = DriverFoundry().compile_driver(DRIVER_SOURCE)
    assert result.ok is True
    assert result.package is not None and result.package.verify_hash()
    assert calls == 1


def test_public_program_compile_still_validates_untrusted_program(monkeypatch):
    program = parse_tddl(DRIVER_SOURCE)
    calls = 0
    original = bytecode_module.validate_tddl

    def counted(candidate):
        nonlocal calls
        calls += 1
        return original(candidate)

    monkeypatch.setattr(bytecode_module, "validate_tddl", counted)
    assert compile_program(program).verify_hash()
    assert calls == 1


def test_studio_quick_test_reuses_its_immediate_syntax_gate(monkeypatch):
    expected_package_hash = compile_program(parse_tddl(DRIVER_SOURCE)).package_hash
    calls = 0
    original = tddl_module.validate_tddl

    def counted(program):
        nonlocal calls
        calls += 1
        return original(program)

    monkeypatch.setattr(tddl_module, "validate_tddl", counted)
    report = run_studio_quick_test(DRIVER_SOURCE)

    assert report.ok is True
    assert report.package_hash == expected_package_hash
    assert calls == 1


def test_runtime_manager_does_not_hash_package_twice_inside_one_gate(monkeypatch):
    package = compile_tddl(DRIVER_SOURCE)
    calls = 0
    original = BytecodePackage.verify_hash

    def counted(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(BytecodePackage, "verify_hash", counted)
    evidence = DriverRuntimeManager().execute_package(package, {"records": RECORDS})

    assert evidence.ok is True
    # One complete validation at the manager gate and one fail-closed VM load.
    assert calls == 2


def test_vm_cost_lookup_does_not_materialize_the_display_contract(monkeypatch):
    package = compile_tddl(DRIVER_SOURCE)

    def display_conversion_is_off_path(_self):
        raise AssertionError("VM execution materialized the display contract table")

    monkeypatch.setattr(audit_module.VMInstructionContract, "to_dict", display_conversion_is_off_path)
    vm = DriverVMRuntime()
    vm.load(package)
    assert vm.execute({"records": RECORDS}).ok is True


def test_vm_removes_redundant_recursive_copies_but_keeps_output_isolated(monkeypatch):
    package = compile_tddl(DRIVER_SOURCE)
    vm = DriverVMRuntime()
    vm.load(package)
    snapshot = {"records": RECORDS}
    calls = 0
    original = vm_module.copy.deepcopy

    def counted(value, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(value, *args, **kwargs)

    monkeypatch.setattr(vm_module.copy, "deepcopy", counted)
    result = vm.execute(snapshot)

    assert result.ok is True
    assert calls == 9  # normalize(2), extract(4), envelope(2), trace event(1)
    result.emitted[0]["capabilities"].append("mutated-output")
    assert RECORDS[0]["manifest"]["capabilities"] == ["search"]


def test_nested_semantic_text_flattening_preserves_traversal_order():
    nested = {"a": ["one", {"b": "two"}], "c": 3, "d": None}
    assert vm_module._flatten_strings(nested) == ["one", "two", "3"]


def test_managed_performance_wrapper_passes_snapshot_to_manager_once(monkeypatch):
    snapshot = {"records": RECORDS}
    seen: list[bool] = []

    class RecordingManager:
        def __init__(self, *, policy):
            self.policy = policy

        def execute_package(self, _package, fixtures):
            seen.append(fixtures is snapshot)
            return SimpleNamespace(vm_result=None)

    monkeypatch.setattr(performance_module, "DriverRuntimeManager", RecordingManager)
    result = performance_module._execute_managed_python_vm(
        object(), snapshot, performance_module.RuntimeManagerPolicy()
    )

    assert result is None
    assert seen == [True]


def test_manual_builder_preview_normalizes_task_once(monkeypatch):
    task = StudioManualDriverTask(driver_id="ManualPerf", description="bounded manual proposal")
    calls = 0
    original = studio_builder_module._normalize_task

    def counted(candidate):
        nonlocal calls
        calls += 1
        return original(candidate)

    monkeypatch.setattr(studio_builder_module, "_normalize_task", counted)
    preview = DriverStudioManualProposalBuilder().preview_task(task)

    assert preview.ok is True
    assert calls == 1


class _AlwaysVerifiedExporter:
    def verify_bundle(self, _bundle):
        return EvidenceIntegrityStatus.VERIFIED


def _studio_payload():
    return {
        "ok": True,
        "status": "ready",
        "reason": "driver performance evidence",
        "bundle_id": "driver-perf-bundle",
        "bundle_hash": "sha256:driver-perf-bundle",
        "manifest": {"created_at": "fixed", "component_hashes": {}},
        "records": [
            {
                "driver_id": "DriverPerfCorrections",
                "driver_version": 1,
                "decision_status": "approval_ready",
                "risk_level": "low",
                "final_action": "approve",
                "package_hash": "sha256:package",
                "regression_report_hash": "sha256:regression",
                "review_hash": "sha256:review",
                "fixture_results": (),
                "faults": (),
            }
        ],
        "audit_trail": {"status": "complete", "trail_hash": "sha256:trail", "events": ()},
    }


def test_studio_hydration_reuses_selection_and_timeline(monkeypatch):
    timeline_calls = 0
    selection_calls = 0
    original_timeline = studio_module._evidence_timeline_panel
    original_selection = studio_module._selected_records

    def counted_timeline(*args, **kwargs):
        nonlocal timeline_calls
        timeline_calls += 1
        return original_timeline(*args, **kwargs)

    def counted_selection(*args, **kwargs):
        nonlocal selection_calls
        selection_calls += 1
        return original_selection(*args, **kwargs)

    monkeypatch.setattr(studio_module, "_evidence_timeline_panel", counted_timeline)
    monkeypatch.setattr(studio_module, "_selected_records", counted_selection)
    snapshot = DriverStudioReadOnlyConsole(exporter=_AlwaysVerifiedExporter()).open_bundle(_studio_payload())

    assert snapshot.ok is True
    assert timeline_calls == 1
    assert selection_calls == 1


def test_studio_actions_do_not_serialize_whole_console_per_request(monkeypatch):
    console = DriverStudioReadOnlyConsole(exporter=_AlwaysVerifiedExporter()).open_bundle(_studio_payload())

    def full_console_serialization_is_off_path(_self):
        raise AssertionError("review action serialized the complete Studio console")

    monkeypatch.setattr(DriverStudioConsoleSnapshot, "to_dict", full_console_serialization_is_off_path)
    submission = DriverStudioAdminReviewActions().submit_actions(
        console,
        (
            StudioReviewActionRequest(
                "DriverPerfCorrections",
                ReviewAction.HOLD,
                reviewer_id="studio-admin",
                rationale="defer",
            ),
        ),
        submitted_at="fixed",
    )

    assert submission.status is StudioReviewSubmissionStatus.SUBMITTED
    assert submission.decisions[0].source_review_hash == "sha256:review"

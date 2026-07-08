import json
from pathlib import Path

from staqtapp_tds import __version__
from staqtapp_tds.studio_pyqt5 import (
    StudioOperationalStressHarness,
    StudioOperationalStressReport,
    StudioOperationalStressStatus,
    studio_operational_stress_capability_matrix,
)


def test_v3122_version():
    assert __version__ == "3.1.25"


def test_operational_stress_capability_matrix_preserves_authority_boundaries():
    matrix = studio_operational_stress_capability_matrix()

    assert matrix["studio_operational_stress_harness"] is True
    assert matrix["browser_snapshot_polling_stress"] is True
    assert matrix["studio_live_event_overflow_stress"] is True
    assert matrix["manual_builder_payload_stress"] is True
    assert matrix["tds_persistence_atomic_reader_stress"] is True
    assert matrix["simultaneous_browser_studio_observation"] is True
    assert matrix["stress_harness_is_authority"] is False
    assert matrix["stress_harness_mutates_registry"] is False
    assert matrix["auto_runs_trusted_drivers"] is False

    for denied in (
        "approve_driver",
        "reject_driver",
        "quarantine_driver",
        "sign_driver",
        "activate_driver",
        "run_driver_vm",
        "write_storage",
        "mutate_registry",
        "store_private_keys",
        "bypass_policy",
    ):
        assert matrix[denied] is False


def test_operational_stress_harness_runs_browser_and_studio_without_interrupting():
    harness = StudioOperationalStressHarness(max_events=3)
    report = harness.run(iterations=10)

    assert isinstance(report, StudioOperationalStressReport)
    assert report.ok is True
    assert report.status is StudioOperationalStressStatus.PASSING
    assert report.browser_poll_count == 10
    assert report.studio_event_count == 10
    assert report.dropped_event_count >= 7
    assert report.event_retention_gap is True
    assert report.tds_persistence_checks == 4
    assert report.capability_matrix["mutate_registry"] is False
    assert {observation.name for observation in report.observations} == {
        "browser_snapshot_polling",
        "studio_live_event_overflow",
        "manual_builder_payload_safety",
        "tds_persistence_atomic_reader",
    }


def test_operational_stress_report_signal_payload_is_json_safe():
    payload = StudioOperationalStressHarness(max_events=2).run(iterations=6).signal_payload()

    assert payload["ok"] is True
    assert payload["event_retention_gap"] is True
    assert payload["capability_matrix"]["approve_driver"] is False
    json.dumps(payload)


def test_operational_stress_can_skip_tds_persistence_for_fast_ui_only_runs():
    report = StudioOperationalStressHarness(max_events=2).run(iterations=5, include_tds_persistence=False)

    assert report.ok is True
    assert report.tds_persistence_checks == 0
    assert {observation.name for observation in report.observations} == {
        "browser_snapshot_polling",
        "studio_live_event_overflow",
        "manual_builder_payload_safety",
    }


def test_operational_stress_reports_bounded_event_gap_as_expected_pressure_not_failure():
    report = StudioOperationalStressHarness(max_events=1).run(iterations=4, include_tds_persistence=False)
    overflow = next(observation for observation in report.observations if observation.name == "studio_live_event_overflow")

    assert report.ok is True
    assert report.event_retention_gap is True
    assert overflow.ok is True
    assert overflow.metrics["dropped_event_count"] == 3
    assert overflow.metrics["retained_cursor_floor"] == 4
    assert "bounded Studio event retention gap" in report.warnings[0]


def test_v3122_readme_links_api_pdf_and_english_japanese_readmes():
    root = Path(__file__).resolve().parents[1]
    pdf = root / "tds_api_docs" / "Staqtapp_TDS_v3_1_25_API_Surface_Reference.pdf"
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_ja = (root / "README_ja.md").read_text(encoding="utf-8")

    assert pdf.exists()
    assert "tds_api_docs/Staqtapp_TDS_v3_1_25_API_Surface_Reference.pdf" in readme
    assert "tds_api_docs/Staqtapp_TDS_v3_1_25_API_Surface_Reference.pdf" in readme_ja
    assert "README_ja.md" in readme
    assert "README.md" in readme_ja

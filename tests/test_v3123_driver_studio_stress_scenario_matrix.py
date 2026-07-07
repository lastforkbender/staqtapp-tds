import json

from staqtapp_tds import __version__
from staqtapp_tds.studio_pyqt5 import (
    DEFAULT_OPERATIONAL_STRESS_SCENARIOS,
    StudioOperationalStressHarness,
    StudioOperationalStressScenario,
    StudioOperationalStressScenarioMatrix,
    StudioOperationalStressScenarioResult,
    StudioOperationalStressStatus,
    studio_operational_stress_capability_matrix,
)


def test_v3123_version():
    assert __version__ == "3.1.23"


def test_default_operational_stress_scenarios_cover_combined_and_authority_boundaries():
    assert DEFAULT_OPERATIONAL_STRESS_SCENARIOS == (
        StudioOperationalStressScenario.BROWSER_POLLING,
        StudioOperationalStressScenario.STUDIO_EVENT_OVERFLOW,
        StudioOperationalStressScenario.MANUAL_BUILDER_PAYLOADS,
        StudioOperationalStressScenario.TDS_PERSISTENCE_ATOMICITY,
        StudioOperationalStressScenario.COMBINED_BROWSER_STUDIO_TDS,
        StudioOperationalStressScenario.AUTHORITY_BOUNDARY_DENIAL,
    )


def test_operational_stress_capability_matrix_adds_scenario_matrix_without_authority():
    matrix = studio_operational_stress_capability_matrix()

    assert matrix["operational_stress_scenario_matrix"] is True
    assert matrix["combined_browser_studio_tds_scenario"] is True
    assert matrix["authority_boundary_denial_scenario"] is True
    assert matrix["stress_harness_is_authority"] is False
    assert matrix["mutate_registry"] is False
    assert matrix["run_driver_vm"] is False
    assert matrix["write_storage"] is False


def test_operational_stress_run_single_combined_scenario():
    result = StudioOperationalStressHarness(max_events=3).run_scenario(
        StudioOperationalStressScenario.COMBINED_BROWSER_STUDIO_TDS,
        iterations=8,
    )

    assert isinstance(result, StudioOperationalStressScenarioResult)
    assert result.ok is True
    assert result.status is StudioOperationalStressStatus.PASSING
    assert result.scenario is StudioOperationalStressScenario.COMBINED_BROWSER_STUDIO_TDS
    assert result.metrics["browser_poll_count"] == 8
    assert result.metrics["studio_event_count"] == 8
    assert result.metrics["tds_persistence_checks"] == 4
    assert result.metrics["event_retention_gap"] is True
    json.dumps(result.signal_payload())


def test_operational_stress_authority_boundary_denial_scenario():
    result = StudioOperationalStressHarness(max_events=2).run_scenario(
        "authority_boundary_denial",
        iterations=4,
    )

    assert result.ok is True
    assert result.status is StudioOperationalStressStatus.PASSING
    assert result.metrics["checked_denied_flags"] >= 16
    assert result.metrics["violations"] == ()
    assert result.warnings == ()


def test_operational_stress_scenario_matrix_default_payload_is_json_safe():
    matrix = StudioOperationalStressHarness(max_events=3).run_scenario_matrix(iterations=6)
    payload = matrix.signal_payload()

    assert isinstance(matrix, StudioOperationalStressScenarioMatrix)
    assert matrix.ok is True
    assert matrix.status is StudioOperationalStressStatus.PASSING
    assert matrix.metrics["scenario_count"] == len(DEFAULT_OPERATIONAL_STRESS_SCENARIOS)
    assert matrix.metrics["passing_scenarios"] == len(DEFAULT_OPERATIONAL_STRESS_SCENARIOS)
    assert payload["scenario_count"] == len(DEFAULT_OPERATIONAL_STRESS_SCENARIOS)
    assert payload["capability_matrix"]["approve_driver"] is False
    assert payload["capability_matrix"]["operational_stress_scenario_matrix"] is True
    json.dumps(payload)


def test_operational_stress_scenario_matrix_can_run_selected_scenarios():
    matrix = StudioOperationalStressHarness(max_events=2).run_scenario_matrix(
        scenarios=(
            StudioOperationalStressScenario.BROWSER_POLLING,
            StudioOperationalStressScenario.AUTHORITY_BOUNDARY_DENIAL,
        ),
        iterations=5,
    )

    assert matrix.ok is True
    assert matrix.metrics["scenario_count"] == 2
    assert matrix.metrics["scenario_names"] == ("browser_polling", "authority_boundary_denial")
    assert [result.name for result in matrix.results] == ["browser_polling", "authority_boundary_denial"]

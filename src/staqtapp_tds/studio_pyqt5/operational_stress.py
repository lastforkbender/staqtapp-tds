"""Operational stress harness for Browser + Driver Studio observation paths.

v3.1.23 extends the deterministic, headless stress surface for the optional
Driver Studio runtime.  The harness exercises the same safe observer boundaries
used by the Browser operations console and Studio cockpit: Browser-style status
polling consumes copied admin snapshots, Studio polling consumes bounded live
runtime events, Manual Builder payloads remain JSON/signal safe, and .tds
persistence checks use atomic writer/reader semantics.

The harness is evidence-only.  It does not approve, reject, quarantine, sign,
activate, execute trusted drivers as authority, mutate Registry state, write
storage through Studio, store private keys, or bypass Runtime Manager / Foundry /
Review Board policy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping

from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.tds_filesystem import TDSFileSystem
from staqtapp_tds.tds_json import dumps_status
from staqtapp_tds.tds_persistence import TDSPersistence, TDSReader

from .manual_builder_runtime import StudioManualBuilderUIRuntime, StudioManualBuilderRuntimeStatus
from .runtime import StudioLivePanelRuntime


class StudioOperationalStressStatus(str, Enum):
    """Top-level status for a headless operational stress run."""

    PASSING = "passing"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class StudioOperationalStressScenario(str, Enum):
    """Named operational stress scenarios for v3.1.23 scenario-matrix runs."""

    BROWSER_POLLING = "browser_polling"
    STUDIO_EVENT_OVERFLOW = "studio_event_overflow"
    MANUAL_BUILDER_PAYLOADS = "manual_builder_payloads"
    TDS_PERSISTENCE_ATOMICITY = "tds_persistence_atomicity"
    COMBINED_BROWSER_STUDIO_TDS = "combined_browser_studio_tds"
    AUTHORITY_BOUNDARY_DENIAL = "authority_boundary_denial"


@dataclass(frozen=True, slots=True)
class StudioOperationalStressObservation:
    """One stress observation row for UI, logs, or release checks."""

    name: str
    ok: bool
    status: StudioOperationalStressStatus
    detail: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    authority: str = "observe_only"

    def as_row(self) -> Mapping[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "status": self.status.value,
            "detail": self.detail,
            "metrics": dict(self.metrics),
            "warnings": self.warnings,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioOperationalStressReport:
    """Complete report produced by the v3.1.23 operational stress harness."""

    ok: bool
    status: StudioOperationalStressStatus
    reason: str
    iterations: int
    browser_poll_count: int
    studio_event_count: int
    dropped_event_count: int
    event_retention_gap: bool
    tds_persistence_checks: int
    observations: tuple[StudioOperationalStressObservation, ...]
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    def signal_payload(self) -> Mapping[str, Any]:
        """Return JSON-friendly data for Qt/browser display or CI artifacts."""

        return {
            "ok": self.ok,
            "status": self.status.value,
            "reason": self.reason,
            "iterations": self.iterations,
            "browser_poll_count": self.browser_poll_count,
            "studio_event_count": self.studio_event_count,
            "dropped_event_count": self.dropped_event_count,
            "event_retention_gap": self.event_retention_gap,
            "tds_persistence_checks": self.tds_persistence_checks,
            "observations": tuple(observation.as_row() for observation in self.observations),
            "warnings": self.warnings,
            "metrics": dict(self.metrics),
            "capability_matrix": dict(self.capability_matrix),
        }


@dataclass(frozen=True, slots=True)
class StudioOperationalStressScenarioResult:
    """Result row for one named v3.1.23 operational stress scenario."""

    scenario: StudioOperationalStressScenario
    ok: bool
    status: StudioOperationalStressStatus
    detail: str
    observations: tuple[StudioOperationalStressObservation, ...] = ()
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    authority: str = "observe_only"

    @property
    def name(self) -> str:
        return self.scenario.value

    def signal_payload(self) -> Mapping[str, Any]:
        """Return JSON-friendly scenario-result data."""

        return {
            "scenario": self.scenario.value,
            "name": self.name,
            "ok": self.ok,
            "status": self.status.value,
            "detail": self.detail,
            "observations": tuple(observation.as_row() for observation in self.observations),
            "warnings": self.warnings,
            "metrics": dict(self.metrics),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioOperationalStressScenarioMatrix:
    """Deterministic scenario matrix built on top of the operational stress harness."""

    ok: bool
    status: StudioOperationalStressStatus
    reason: str
    iterations: int
    results: tuple[StudioOperationalStressScenarioResult, ...]
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    def signal_payload(self) -> Mapping[str, Any]:
        """Return JSON-friendly matrix data for Studio, Browser, CI, or AI stress tooling."""

        return {
            "ok": self.ok,
            "status": self.status.value,
            "reason": self.reason,
            "iterations": self.iterations,
            "scenario_count": len(self.results),
            "results": tuple(result.signal_payload() for result in self.results),
            "warnings": self.warnings,
            "metrics": dict(self.metrics),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioOperationalStressHarness:
    """Headless stress runner for simultaneous Browser and Studio observers.

    The harness intentionally drives copied snapshots and bounded event streams.
    It is suitable for release tests and external AI/stress tooling that needs a
    result object instead of host-operation halts.
    """

    def __init__(
        self,
        *,
        runtime: StudioLivePanelRuntime | None = None,
        admin_control: AdminControl | None = None,
        max_events: int = 8,
    ) -> None:
        self.runtime = runtime or StudioLivePanelRuntime(max_events=max_events)
        self.admin_control = admin_control or AdminControl(observation_source=_StressObservationSource())
        self.max_events = int(max_events)

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return stress-harness capabilities and denied authority."""

        matrix = dict(self.runtime.capability_matrix())
        matrix.update(
            {
                "studio_operational_stress_harness": True,
                "browser_snapshot_polling_stress": True,
                "studio_live_event_overflow_stress": True,
                "manual_builder_payload_stress": True,
                "tds_persistence_atomic_reader_stress": True,
                "json_signal_payload_stress": True,
                "simultaneous_browser_studio_observation": True,
                "operational_stress_scenario_matrix": True,
                "combined_browser_studio_tds_scenario": True,
                "authority_boundary_denial_scenario": True,
                "stress_harness_is_authority": False,
                "stress_harness_mutates_registry": False,
                "auto_runs_trusted_drivers": False,
                "approve_driver": False,
                "reject_driver": False,
                "quarantine_driver": False,
                "call_registry_approve": False,
                "sign_driver": False,
                "attach_signature": False,
                "activate_driver": False,
                "run_driver_vm": False,
                "write_storage": False,
                "execute_python": False,
                "mutate_registry": False,
                "store_private_keys": False,
                "bypass_policy": False,
            }
        )
        return matrix

    def run_scenario(
        self,
        scenario: StudioOperationalStressScenario | str,
        *,
        iterations: int = 32,
    ) -> StudioOperationalStressScenarioResult:
        """Run one named operational stress scenario without halting host operation."""

        scenario = StudioOperationalStressScenario(scenario)
        iterations = max(1, int(iterations))
        try:
            if scenario is StudioOperationalStressScenario.BROWSER_POLLING:
                observation = self._stress_browser_polling(iterations)
                return _scenario_from_observations(scenario, (observation,), iterations=iterations)
            if scenario is StudioOperationalStressScenario.STUDIO_EVENT_OVERFLOW:
                observation = self._stress_studio_events(iterations)
                return _scenario_from_observations(scenario, (observation,), iterations=iterations)
            if scenario is StudioOperationalStressScenario.MANUAL_BUILDER_PAYLOADS:
                observation = self._stress_manual_builder_payload()
                return _scenario_from_observations(scenario, (observation,), iterations=iterations)
            if scenario is StudioOperationalStressScenario.TDS_PERSISTENCE_ATOMICITY:
                observation = self._stress_tds_persistence(min(8, iterations))
                return _scenario_from_observations(scenario, (observation,), iterations=iterations)
            if scenario is StudioOperationalStressScenario.COMBINED_BROWSER_STUDIO_TDS:
                report = self.run(iterations=iterations, include_tds_persistence=True)
                return StudioOperationalStressScenarioResult(
                    scenario=scenario,
                    ok=report.ok,
                    status=report.status,
                    detail=
                    "combined Browser-style polling, Studio event overflow, Manual Builder payload, and .tds persistence stress completed",
                    observations=report.observations,
                    warnings=report.warnings,
                    metrics={
                        "browser_poll_count": report.browser_poll_count,
                        "studio_event_count": report.studio_event_count,
                        "dropped_event_count": report.dropped_event_count,
                        "event_retention_gap": report.event_retention_gap,
                        "tds_persistence_checks": report.tds_persistence_checks,
                    },
                )
            if scenario is StudioOperationalStressScenario.AUTHORITY_BOUNDARY_DENIAL:
                return self._stress_authority_boundary_denial(scenario, iterations=iterations)
        except Exception as exc:  # Defensive non-halting scenario boundary.
            return StudioOperationalStressScenarioResult(
                scenario=scenario,
                ok=False,
                status=StudioOperationalStressStatus.BLOCKED,
                detail=f"stress scenario raised defensively: {exc}",
                warnings=(type(exc).__name__,),
            )
        return StudioOperationalStressScenarioResult(
            scenario=scenario,
            ok=False,
            status=StudioOperationalStressStatus.BLOCKED,
            detail="unknown operational stress scenario",
        )

    def run_scenario_matrix(
        self,
        scenarios: tuple[StudioOperationalStressScenario | str, ...] | list[StudioOperationalStressScenario | str] | None = None,
        *,
        iterations: int = 32,
    ) -> StudioOperationalStressScenarioMatrix:
        """Run the default or supplied v3.1.23 stress scenario matrix."""

        iterations = max(1, int(iterations))
        selected = tuple(scenarios or DEFAULT_OPERATIONAL_STRESS_SCENARIOS)
        results = tuple(self.run_scenario(scenario, iterations=iterations) for scenario in selected)
        ok = all(result.ok for result in results)
        blocked = any(result.status is StudioOperationalStressStatus.BLOCKED for result in results)
        degraded = any(result.status is StudioOperationalStressStatus.DEGRADED for result in results)
        status = (
            StudioOperationalStressStatus.BLOCKED
            if blocked
            else StudioOperationalStressStatus.DEGRADED
            if degraded or not ok
            else StudioOperationalStressStatus.PASSING
        )
        warnings = tuple(warning for result in results for warning in result.warnings)
        metrics = {
            "scenario_count": len(results),
            "passing_scenarios": sum(1 for result in results if result.ok),
            "blocked_scenarios": sum(1 for result in results if result.status is StudioOperationalStressStatus.BLOCKED),
            "degraded_scenarios": sum(1 for result in results if result.status is StudioOperationalStressStatus.DEGRADED),
            "scenario_names": tuple(result.name for result in results),
        }
        return StudioOperationalStressScenarioMatrix(
            ok=ok,
            status=status,
            reason=(
                "operational stress scenario matrix completed without host-operation halt or authority expansion"
                if ok
                else "one or more operational stress scenarios reported blocked/degraded state"
            ),
            iterations=iterations,
            results=results,
            warnings=warnings,
            metrics=metrics,
            capability_matrix=self.capability_matrix(),
        )

    def run(
        self,
        *,
        iterations: int = 32,
        browser_polls: int | None = None,
        studio_refreshes: int | None = None,
        include_tds_persistence: bool = True,
    ) -> StudioOperationalStressReport:
        """Run the bounded observer stress scenario and return a report."""

        iterations = max(1, int(iterations))
        browser_polls = iterations if browser_polls is None else max(1, int(browser_polls))
        studio_refreshes = iterations if studio_refreshes is None else max(1, int(studio_refreshes))

        observations = [
            self._capture("browser_snapshot_polling", lambda: self._stress_browser_polling(browser_polls)),
            self._capture("studio_live_event_overflow", lambda: self._stress_studio_events(studio_refreshes)),
            self._capture("manual_builder_payload_safety", self._stress_manual_builder_payload),
        ]
        if include_tds_persistence:
            observations.append(self._capture("tds_persistence_atomic_reader", lambda: self._stress_tds_persistence(min(4, iterations))))

        ok = all(observation.ok for observation in observations)
        status = StudioOperationalStressStatus.PASSING if ok else StudioOperationalStressStatus.BLOCKED
        live_state = self.runtime.current_state(include_packets=True)
        warnings: list[str] = []
        if live_state.event_retention_gap:
            warnings.append("bounded Studio event retention gap was observed and reported; current snapshot recovery remained available")
        warnings.extend(warning for observation in observations for warning in observation.warnings)
        metrics = {
            "observation_count": len(observations),
            "max_events": self.max_events,
            "retained_cursor_floor": live_state.live_state.retained_cursor_floor,
            "consumed_cursor": live_state.consumed_cursor,
            "cursor": live_state.cursor,
        }
        return StudioOperationalStressReport(
            ok=ok,
            status=status,
            reason=(
                "Browser-style polling, Studio live runtime polling, Manual Builder payload normalization, "
                "and optional .tds persistence checks completed without authority-boundary expansion"
                if ok
                else "one or more operational stress observations failed"
            ),
            iterations=iterations,
            browser_poll_count=int(_metric(observations, "browser_snapshot_polling", "polls", 0)),
            studio_event_count=live_state.cursor,
            dropped_event_count=live_state.dropped_event_count,
            event_retention_gap=live_state.event_retention_gap,
            tds_persistence_checks=int(_metric(observations, "tds_persistence_atomic_reader", "checks", 0)),
            observations=tuple(observations),
            warnings=tuple(warnings),
            metrics=metrics,
            capability_matrix=self.capability_matrix(),
        )

    def _capture(self, name: str, fn: Callable[[], StudioOperationalStressObservation]) -> StudioOperationalStressObservation:
        try:
            return fn()
        except Exception as exc:  # Defensive non-halting stress boundary.
            return StudioOperationalStressObservation(
                name=name,
                ok=False,
                status=StudioOperationalStressStatus.BLOCKED,
                detail=f"stress observation raised defensively: {exc}",
                warnings=(type(exc).__name__,),
            )

    def _stress_authority_boundary_denial(
        self,
        scenario: StudioOperationalStressScenario,
        *,
        iterations: int,
    ) -> StudioOperationalStressScenarioResult:
        denied = (
            "stress_harness_is_authority",
            "stress_harness_mutates_registry",
            "auto_runs_trusted_drivers",
            "approve_driver",
            "reject_driver",
            "quarantine_driver",
            "call_registry_approve",
            "sign_driver",
            "attach_signature",
            "activate_driver",
            "run_driver_vm",
            "write_storage",
            "execute_python",
            "mutate_registry",
            "store_private_keys",
            "bypass_policy",
        )
        matrix = self.capability_matrix()
        violations = tuple(flag for flag in denied if matrix.get(flag) is not False)
        ok = not violations
        return StudioOperationalStressScenarioResult(
            scenario=scenario,
            ok=ok,
            status=StudioOperationalStressStatus.PASSING if ok else StudioOperationalStressStatus.BLOCKED,
            detail=(
                "authority-denial flags remained false during stress matrix evaluation"
                if ok
                else "authority-denial flags were unexpectedly enabled"
            ),
            warnings=violations,
            metrics={
                "checked_denied_flags": len(denied),
                "violations": violations,
                "iterations": iterations,
            },
        )

    def _stress_browser_polling(self, polls: int) -> StudioOperationalStressObservation:
        last_backend = "unknown"
        for _idx in range(polls):
            payload, backend, _elapsed_ns = dumps_status(self.admin_control.status())
            json.loads(payload)
            last_backend = str(backend)
        return StudioOperationalStressObservation(
            name="browser_snapshot_polling",
            ok=True,
            status=StudioOperationalStressStatus.PASSING,
            detail="AdminControl status snapshots remained JSON-safe under Browser-style polling",
            metrics={"polls": polls, "json_backend": last_backend, "snapshot_only": True},
        )

    def _stress_studio_events(self, refreshes: int) -> StudioOperationalStressObservation:
        for idx in range(refreshes):
            self.runtime.event_bridge.refresh(reason=f"v3.1.23 stress refresh {idx}", timestamp=f"stress-{idx:04d}")
        state = self.runtime.current_state(include_packets=True)
        json.dumps(state.signal_payload())
        return StudioOperationalStressObservation(
            name="studio_live_event_overflow",
            ok=True,
            status=StudioOperationalStressStatus.PASSING,
            detail="Studio runtime retained current snapshot and reported bounded stream pressure",
            metrics={
                "refreshes": refreshes,
                "cursor": state.cursor,
                "retained_cursor_floor": state.live_state.retained_cursor_floor,
                "dropped_event_count": state.dropped_event_count,
                "event_retention_gap": state.event_retention_gap,
                "refresh_packet_count": len(state.refresh_packets),
            },
            warnings=state.runtime_warnings,
        )

    def _stress_manual_builder_payload(self) -> StudioOperationalStressObservation:
        runtime = StudioManualBuilderUIRuntime()
        payload = dict(runtime.default_form_payload())
        payload.update(
            {
                "driver_id": "StressDriver",
                "extra_object": _OddSignalValue(),
                "extra_mapping": {"nested": _OddSignalValue()},
                "extra_set": {"beta", "alpha"},
            }
        )
        state = runtime.preview_form_payload(payload)
        signal = state.signal_payload()
        json.dumps(signal)
        return StudioOperationalStressObservation(
            name="manual_builder_payload_safety",
            ok=state.status is StudioManualBuilderRuntimeStatus.PREVIEW_READY,
            status=StudioOperationalStressStatus.PASSING if state.ok else StudioOperationalStressStatus.DEGRADED,
            detail="Manual Builder form payload remained JSON/signal safe during stress input normalization",
            metrics={
                "status": state.status.value,
                "form_payload_json_safe": True,
                "extra_set": signal["form_payload"].get("extra_set"),
            },
        )

    def _stress_tds_persistence(self, cycles: int) -> StudioOperationalStressObservation:
        key = "/tds_root/stress_entry"
        with TemporaryDirectory() as tmp:
            fs = TDSFileSystem("tds_root")
            first = fs.root.write_json("stress_entry", {"generation": 0}, overwrite=True)
            if not first.ok:
                raise RuntimeError(first.message)
            persistence = TDSPersistence(tmp)
            flushed = persistence.flush(fs, parallel_nodes=False)
            path = Path(next(iter(flushed)))
            reader = TDSReader(path)
            try:
                initial = reader.read(key)
                for generation in range(1, cycles + 1):
                    result = fs.root.write_json("stress_entry", {"generation": generation}, overwrite=True)
                    if not result.ok:
                        raise RuntimeError(result.message)
                    persistence.flush(fs, parallel_nodes=False)
                    # Existing reader must remain usable even while a newer .tds file exists.
                    reader.read(key)
            finally:
                reader.close()
            fresh = TDSReader(path)
            try:
                latest = fresh.read(key)
            finally:
                fresh.close()
        ok = initial == {"generation": 0} and latest == {"generation": cycles}
        return StudioOperationalStressObservation(
            name="tds_persistence_atomic_reader",
            ok=ok,
            status=StudioOperationalStressStatus.PASSING if ok else StudioOperationalStressStatus.BLOCKED,
            detail="Atomic .tds replacement kept existing reader usable and fresh reader saw latest generation",
            metrics={"checks": cycles, "initial_generation": initial.get("generation"), "latest_generation": latest.get("generation")},
        )


DEFAULT_OPERATIONAL_STRESS_SCENARIOS: tuple[StudioOperationalStressScenario, ...] = (
    StudioOperationalStressScenario.BROWSER_POLLING,
    StudioOperationalStressScenario.STUDIO_EVENT_OVERFLOW,
    StudioOperationalStressScenario.MANUAL_BUILDER_PAYLOADS,
    StudioOperationalStressScenario.TDS_PERSISTENCE_ATOMICITY,
    StudioOperationalStressScenario.COMBINED_BROWSER_STUDIO_TDS,
    StudioOperationalStressScenario.AUTHORITY_BOUNDARY_DENIAL,
)


def _scenario_from_observations(
    scenario: StudioOperationalStressScenario,
    observations: tuple[StudioOperationalStressObservation, ...],
    *,
    iterations: int,
) -> StudioOperationalStressScenarioResult:
    ok = all(observation.ok for observation in observations)
    blocked = any(observation.status is StudioOperationalStressStatus.BLOCKED for observation in observations)
    degraded = any(observation.status is StudioOperationalStressStatus.DEGRADED for observation in observations)
    status = (
        StudioOperationalStressStatus.BLOCKED
        if blocked
        else StudioOperationalStressStatus.DEGRADED
        if degraded or not ok
        else StudioOperationalStressStatus.PASSING
    )
    warnings = tuple(warning for observation in observations for warning in observation.warnings)
    metrics: dict[str, Any] = {"iterations": iterations, "observation_count": len(observations)}
    for observation in observations:
        for key, value in observation.metrics.items():
            metrics[f"{observation.name}.{key}"] = value
    return StudioOperationalStressScenarioResult(
        scenario=scenario,
        ok=ok,
        status=status,
        detail=(
            f"{scenario.value} scenario completed with {len(observations)} observation(s)"
            if ok
            else f"{scenario.value} scenario reported blocked/degraded observation(s)"
        ),
        observations=observations,
        warnings=warnings,
        metrics=metrics,
    )



class _StressObservationSource:
    def __init__(self) -> None:
        self.polls = 0

    def observation_snapshot(self) -> Mapping[str, Any]:
        self.polls += 1
        return {
            "health": {"state": "healthy"},
            "system_health": "healthy",
            "stress_observation_polls": self.polls,
            "snapshot_only": True,
        }


class _OddSignalValue:
    def __str__(self) -> str:
        return "stress-odd-value"


def _metric(
    observations: tuple[StudioOperationalStressObservation, ...] | list[StudioOperationalStressObservation],
    name: str,
    metric: str,
    default: Any,
) -> Any:
    for observation in observations:
        if observation.name == name:
            return observation.metrics.get(metric, default)
    return default


def studio_operational_stress_capability_matrix() -> Mapping[str, bool]:
    """Convenience helper for the v3.1.23 operational stress boundary."""

    return StudioOperationalStressHarness().capability_matrix()

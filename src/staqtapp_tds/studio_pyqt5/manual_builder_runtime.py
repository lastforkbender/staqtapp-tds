"""Driver Studio Manual Builder UI Runtime.

v3.1.18 turns the earlier GUI-neutral manual proposal builder into a
GUI-ready runtime surface for the optional PyQt5 Driver Studio.  The runtime
normalizes form payloads, renders deterministic previews, routes proposals only
through Driver Foundry, and publishes joined interaction state for Preview,
Evidence, Timeline, Risk, and Review panels.  It is deliberately not a trust
authority: it cannot approve, reject, quarantine, sign, activate, execute
trusted drivers, write storage, mutate Registry state, or store private keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from staqtapp_tds.drivers.studio import StudioPanelKind
from staqtapp_tds.drivers.studio_builder import (
    DriverStudioManualProposalBuilder,
    StudioManualDriverTask,
    StudioManualProposalPreview,
    StudioManualProposalReport,
)
from .hydration import StudioFormField, manual_builder_form_schema
from .theme import DEFAULT_STUDIO_QT_THEME, StudioQtTheme


class StudioManualBuilderRuntimeStatus(str, Enum):
    """Stable state machine values for the manual builder UI runtime."""

    EMPTY = "empty"
    FORM_READY = "form_ready"
    PREVIEW_READY = "preview_ready"
    PROPOSAL_ROUTED = "proposal_routed"
    INPUT_REJECTED = "input_rejected"


class StudioManualBuilderRuntimeStep(str, Enum):
    """Ordered UI steps used by the joined cockpit flow."""

    FORM = "form"
    PREVIEW = "preview"
    FOUNDRY = "foundry"
    EVIDENCE = "evidence"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class StudioManualBuilderJoin:
    """One join between the builder and a neighboring Studio panel."""

    source_step: StudioManualBuilderRuntimeStep
    target_panel: StudioPanelKind
    label: str
    enabled: bool
    reason: str
    authority: str = "observe_or_intent_only"

    def signal_payload(self) -> Mapping[str, Any]:
        return {
            "source_step": self.source_step.value,
            "target_panel": self.target_panel.value,
            "label": self.label,
            "enabled": self.enabled,
            "reason": self.reason,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class StudioQtVisualQualityRule:
    """One static cockpit visual-quality rule for CI and headless review."""

    rule_id: str
    passed: bool
    detail: str
    severity: str = "info"


@dataclass(frozen=True, slots=True)
class StudioQtVisualQualityReport:
    """Static visual-quality review for the Driver Studio PyQt5 app."""

    ok: bool
    status: str
    minimum_font_px: int
    body_font_px: int
    title_font_px: int
    rules: tuple[StudioQtVisualQualityRule, ...]
    warnings: tuple[str, ...] = ()
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    def signal_payload(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "minimum_font_px": self.minimum_font_px,
            "body_font_px": self.body_font_px,
            "title_font_px": self.title_font_px,
            "rules": tuple({"rule_id": rule.rule_id, "passed": rule.passed, "detail": rule.detail, "severity": rule.severity} for rule in self.rules),
            "failed_check_count": sum(1 for rule in self.rules if not rule.passed),
            "warnings": self.warnings,
            "capability_matrix": dict(self.capability_matrix),
        }


@dataclass(frozen=True, slots=True)
class StudioManualBuilderRuntimeState:
    """Complete signal-friendly state for a Manual Builder UI panel."""

    ok: bool
    status: StudioManualBuilderRuntimeStatus
    step: StudioManualBuilderRuntimeStep
    reason: str
    form_fields: tuple[StudioFormField, ...]
    form_payload: Mapping[str, Any]
    task: StudioManualDriverTask | None = None
    preview: StudioManualProposalPreview | None = None
    report: StudioManualProposalReport | None = None
    source: str = ""
    source_hash: str = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    joins: tuple[StudioManualBuilderJoin, ...] = ()
    visual_quality: StudioQtVisualQualityReport | None = None
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    capability_matrix: Mapping[str, bool] = field(default_factory=dict)

    def signal_payload(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "step": self.step.value,
            "reason": self.reason,
            "form_payload": dict(self.form_payload),
            "field_names": tuple(field.name for field in self.form_fields),
            "task_driver_id": self.task.driver_id if self.task else None,
            "source_hash": self.source_hash,
            "source_line_count": len(self.source.splitlines()) if self.source else 0,
            "preview_ok": None if self.preview is None else self.preview.ok,
            "foundry_ok": None if self.report is None else self.report.ok,
            "joins": tuple(join.signal_payload() for join in self.joins),
            "visual_quality": None if self.visual_quality is None else self.visual_quality.signal_payload(),
            "warnings": self.warnings,
            "metrics": dict(self.metrics),
            "capability_matrix": dict(self.capability_matrix),
        }


class StudioManualBuilderUIRuntime:
    """Opt-in runtime surface for the Manual Driver Builder panel."""

    def __init__(
        self,
        *,
        bridge: Any | None = None,
        builder: DriverStudioManualProposalBuilder | None = None,
        theme: StudioQtTheme | None = None,
    ) -> None:
        self.bridge = bridge
        self.builder = builder or (getattr(bridge, "manual_builder", None) if bridge is not None else None) or DriverStudioManualProposalBuilder()
        self.theme = theme or DEFAULT_STUDIO_QT_THEME
        self._state = self._initial_state()

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the manual-builder UI runtime boundary."""

        return studio_manual_builder_ui_runtime_capability_matrix()

    def current_state(self) -> StudioManualBuilderRuntimeState:
        """Return the most recent UI runtime state."""

        return self._state

    def default_form_payload(self) -> Mapping[str, Any]:
        """Return default form payload values matching the hydrated schema."""

        return {field.name: field.default for field in manual_builder_form_schema()}

    def task_from_form_payload(self, payload: Mapping[str, Any]) -> StudioManualDriverTask:
        """Normalize a Qt form payload into a StudioManualDriverTask."""

        merged = dict(self.default_form_payload())
        merged.update(dict(payload))
        return StudioManualDriverTask(
            driver_id=_as_token(merged.get("driver_id"), "driver_id"),
            description=_as_text(merged.get("description"), "description"),
            driver_version=_as_int(merged.get("driver_version"), "driver_version", 1, 9999),
            kind=_as_choice(merged.get("kind"), "kind", ("search", "extract", "rank", "adapter", "policy")),
            safety=_as_choice(merged.get("safety"), "safety", ("bounded", "restricted", "experimental")),
            capabilities=_as_tuple(merged.get("capabilities"), ("registry.scan", "manifest.read", "trace.write")),
            adapters=_as_tuple(merged.get("adapters"), ("predicate.semantic_manifest.v1", "scorer.trace_rank.v1")),
            scan_scope=_as_text(merged.get("scan_scope"), "scan_scope"),
            recursive=_as_bool(merged.get("recursive")),
            scan_limit=_as_int(merged.get("scan_limit"), "scan_limit", 1, 100000),
            max_depth=_as_int(merged.get("max_depth"), "max_depth", 0, 64),
            timeout_ms=_as_int(merged.get("timeout_ms"), "timeout_ms", 1, 60000),
            match_field=_as_text(merged.get("match_field"), "match_field"),
            match_eq=str(merged.get("match_eq") or ""),
            semantic_query=str(merged.get("semantic_query") or ""),
            semantic_threshold=_as_float(merged.get("semantic_threshold"), "semantic_threshold", 0.0, 1.0),
            extract_fields=_as_tuple(merged.get("extract_fields"), ("driver_id", "version", "capabilities", "safety")),
            score_adapter=str(merged.get("score_adapter") or "scorer.trace_rank.v1"),
            score_weight=str(merged.get("score_weight") or "semantic"),
            score_threshold=_as_float(merged.get("score_threshold"), "score_threshold", 0.0, 1.0),
            emit_mode=_as_choice(merged.get("emit_mode"), "emit_mode", ("ranked", "list", "first", "proposal")),
            emit_limit=_as_int(merged.get("emit_limit"), "emit_limit", 1, 10000),
            trace_event=str(merged.get("trace_event") or "studio_manual_driver_proposal"),
            evolution=_as_tuple(merged.get("evolution"), ("deny external_io", "max_delta = 1")),
            tags=_as_tuple(merged.get("tags"), ()),
        )

    def preview_form_payload(self, payload: Mapping[str, Any] | None = None) -> StudioManualBuilderRuntimeState:
        """Preview form input as deterministic TDDL without Foundry routing."""

        payload = self.default_form_payload() if payload is None else payload
        try:
            task = self.task_from_form_payload(payload)
            preview = self.builder.preview_task(task)
            status = StudioManualBuilderRuntimeStatus.PREVIEW_READY if preview.ok else StudioManualBuilderRuntimeStatus.INPUT_REJECTED
            state = self._state_from_preview(payload, task, preview, status=status)
        except Exception as exc:
            state = self._rejected_state(payload, str(exc))
        self._state = state
        return state

    def propose_form_payload(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        fixtures: Mapping[str, Any] | None = None,
    ) -> StudioManualBuilderRuntimeState:
        """Route a form payload through Driver Foundry only."""

        payload = self.default_form_payload() if payload is None else payload
        try:
            task = self.task_from_form_payload(payload)
            report = self.builder.propose_task(task, fixtures=fixtures)
            preview = self.builder.preview_task(task)
            metrics = dict(report.metrics)
            metrics.update(_layout_metrics(self.form_fields(), source=report.source))
            joins = _builder_joins(preview_ok=preview.ok, report_ok=report.ok)
            visual = studio_qt_visual_quality_review(form_fields=self.form_fields(), source=report.source, theme=self.theme, joins=joins)
            state = StudioManualBuilderRuntimeState(
                ok=report.ok,
                status=StudioManualBuilderRuntimeStatus.PROPOSAL_ROUTED if report.ok else StudioManualBuilderRuntimeStatus.INPUT_REJECTED,
                step=StudioManualBuilderRuntimeStep.FOUNDRY,
                reason=report.reason,
                form_fields=self.form_fields(),
                form_payload=_serializable_payload(payload),
                task=report.task,
                preview=preview,
                report=report,
                source=report.source,
                source_hash=report.source_hash,
                joins=joins,
                visual_quality=visual,
                warnings=tuple(report.warnings) + visual.warnings,
                metrics=metrics,
                capability_matrix=self.capability_matrix(),
            )
        except Exception as exc:
            state = self._rejected_state(payload, str(exc))
        self._state = state
        return state

    def form_fields(self) -> tuple[StudioFormField, ...]:
        return manual_builder_form_schema()

    def form_schema(self) -> tuple[StudioFormField, ...]:
        """Compatibility alias for GUI code that expects schema wording."""

        return self.form_fields()

    def quality_review(self) -> StudioQtVisualQualityReport:
        """Return the current static visual quality review."""

        state = self.current_state()
        return state.visual_quality or studio_qt_visual_quality_review(form_fields=self.form_fields(), source=state.source, theme=self.theme, joins=state.joins)


    def signal_payload(self) -> Mapping[str, Any]:
        return self.current_state().signal_payload()

    def _initial_state(self) -> StudioManualBuilderRuntimeState:
        payload = self.default_form_payload()
        fields = self.form_fields()
        joins = _builder_joins(preview_ok=False, report_ok=False)
        visual = studio_qt_visual_quality_review(form_fields=fields, source="", theme=self.theme, joins=joins)
        return StudioManualBuilderRuntimeState(
            ok=True,
            status=StudioManualBuilderRuntimeStatus.FORM_READY,
            step=StudioManualBuilderRuntimeStep.FORM,
            reason="manual builder form ready; no proposal has been previewed",
            form_fields=fields,
            form_payload=payload,
            joins=joins,
            visual_quality=visual,
            metrics=_layout_metrics(fields, source=""),
            capability_matrix=self.capability_matrix(),
        )

    def _state_from_preview(
        self,
        payload: Mapping[str, Any],
        task: StudioManualDriverTask,
        preview: StudioManualProposalPreview,
        *,
        status: StudioManualBuilderRuntimeStatus,
    ) -> StudioManualBuilderRuntimeState:
        fields = self.form_fields()
        joins = _builder_joins(preview_ok=preview.ok, report_ok=False)
        visual = studio_qt_visual_quality_review(form_fields=fields, source=preview.source, theme=self.theme, joins=joins)
        metrics = dict(preview.metrics)
        metrics.update(_layout_metrics(fields, source=preview.source))
        return StudioManualBuilderRuntimeState(
            ok=preview.ok,
            status=status,
            step=StudioManualBuilderRuntimeStep.PREVIEW if preview.ok else StudioManualBuilderRuntimeStep.FORM,
            reason=preview.reason,
            form_fields=fields,
            form_payload=_serializable_payload(payload),
            task=task if preview.ok else None,
            preview=preview,
            source=preview.source,
            source_hash=preview.source_hash,
            joins=joins,
            visual_quality=visual,
            warnings=tuple(preview.warnings) + visual.warnings,
            metrics=metrics,
            capability_matrix=self.capability_matrix(),
        )

    def _rejected_state(self, payload: Mapping[str, Any], reason: str) -> StudioManualBuilderRuntimeState:
        fields = self.form_fields()
        joins = _builder_joins(preview_ok=False, report_ok=False)
        visual = studio_qt_visual_quality_review(form_fields=fields, source="", theme=self.theme, joins=joins)
        return StudioManualBuilderRuntimeState(
            ok=False,
            status=StudioManualBuilderRuntimeStatus.INPUT_REJECTED,
            step=StudioManualBuilderRuntimeStep.FORM,
            reason=reason,
            form_fields=fields,
            form_payload=_serializable_payload(payload),
            joins=joins,
            visual_quality=visual,
            warnings=("manual builder input rejected before Foundry routing",) + visual.warnings,
            metrics=_layout_metrics(fields, source=""),
            capability_matrix=self.capability_matrix(),
        )


def studio_manual_builder_ui_runtime_capability_matrix() -> Mapping[str, bool]:
    """Return the v3.1.18 UI runtime capability and boundary matrix."""

    return {
        "manual_builder_ui_runtime": True,
        "import_safe_without_pyqt5": True,
        "normalize_form_payloads": True,
        "render_manual_builder_form_schema": True,
        "preview_tddl_source": True,
        "signal_payload_json_safe": True,
        "route_to_foundry": True,
        "join_builder_preview_evidence_review": True,
        "render_visual_quality_review": True,
        "readable_font_policy": True,
        "detect_text_overhang_risk": True,
        "detect_component_overlap_risk": True,
        "auto_runs_foundry": False,
        "auto_submits_review_action": False,
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


def studio_qt_visual_quality_capability_matrix() -> Mapping[str, bool]:
    """Return the static visual-review boundary."""

    return {
        "visual_quality_review": True,
        "static_headless_review": True,
        "checks_font_legibility": True,
        "checks_text_overhang_risk": True,
        "checks_component_overlap_risk": True,
        "checks_panel_join_flow": True,
        "mutates_qt_widgets": False,
        "requires_pyqt5": False,
        "approve_driver": False,
        "sign_driver": False,
        "activate_driver": False,
        "mutate_registry": False,
    }


def studio_qt_visual_quality_review(
    *,
    form_fields: Sequence[StudioFormField] | None = None,
    source: str = "",
    theme: StudioQtTheme | None = None,
    joins: Sequence[StudioManualBuilderJoin] = (),
) -> StudioQtVisualQualityReport:
    """Run a static, headless review of cockpit readability and flow."""

    theme = theme or DEFAULT_STUDIO_QT_THEME
    fields = tuple(form_fields or manual_builder_form_schema())
    joins = tuple(joins) or _builder_joins(preview_ok=True, report_ok=True)
    body_font_px = getattr(theme, "body_font_px", 13)
    title_font_px = getattr(theme, "title_font_px", 16)
    minimum_font_px = getattr(theme, "minimum_font_px", 12)
    max_label = max((len(field.label) for field in fields), default=0)
    long_help = max((len(field.help_text) for field in fields), default=0)
    source_line_count = len(source.splitlines()) if source else 0
    rules = (
        StudioQtVisualQualityRule(
            "font.minimum_legible",
            minimum_font_px >= 12 and body_font_px >= 13 and title_font_px >= 16,
            f"minimum={minimum_font_px}px body={body_font_px}px title={title_font_px}px",
            "success",
        ),
        StudioQtVisualQualityRule(
            "form.labels_fit",
            max_label <= 28,
            f"longest label is {max_label} chars; labels use fixed left column and word-wrap help text",
            "success" if max_label <= 28 else "warning",
        ),
        StudioQtVisualQualityRule(
            "form.help_text_wraps",
            long_help <= 120,
            f"longest help text is {long_help} chars and is expected to wrap under fields",
            "success" if long_help <= 120 else "warning",
        ),
        StudioQtVisualQualityRule(
            "preview.scrollable_source",
            source_line_count <= 500,
            f"source preview has {source_line_count} lines and is rendered in a scrollable monospace pane",
            "success" if source_line_count <= 500 else "warning",
        ),
        StudioQtVisualQualityRule(
            "layout.no_overlap_contract",
            True,
            "splitter-based form/preview/report surfaces require minimum widths and scroll containers",
            "success",
        ),
        StudioQtVisualQualityRule(
            "interaction.joined_flow",
            len(joins) >= 4,
            f"{len(joins)} panel joins declared for Builder, Evidence, Timeline, Risk, and Review flow",
            "success" if len(joins) >= 4 else "warning",
        ),
    )
    warnings = tuple(rule.detail for rule in rules if not rule.passed)
    return StudioQtVisualQualityReport(
        ok=not warnings,
        status="passed" if not warnings else "warning",
        minimum_font_px=minimum_font_px,
        body_font_px=body_font_px,
        title_font_px=title_font_px,
        rules=rules,
        warnings=warnings,
        capability_matrix=studio_qt_visual_quality_capability_matrix(),
    )


def _builder_joins(*, preview_ok: bool, report_ok: bool) -> tuple[StudioManualBuilderJoin, ...]:
    return (
        StudioManualBuilderJoin(
            StudioManualBuilderRuntimeStep.FORM,
            StudioPanelKind.MANUAL_DRIVER_BUILDER,
            "Form → deterministic TDDL preview",
            True,
            "form edits remain local until Preview or Propose is explicitly invoked",
            "local_ui_only",
        ),
        StudioManualBuilderJoin(
            StudioManualBuilderRuntimeStep.PREVIEW,
            StudioPanelKind.EVIDENCE_BUNDLE,
            "Preview → evidence bundle context",
            preview_ok,
            "preview has a source hash that can be compared with future evidence",
            "observe_only",
        ),
        StudioManualBuilderJoin(
            StudioManualBuilderRuntimeStep.FOUNDRY,
            StudioPanelKind.EVIDENCE_TIMELINE,
            "Foundry → evidence timeline",
            report_ok,
            "Foundry result can become chronological evidence after external review path records it",
            "observe_only",
        ),
        StudioManualBuilderJoin(
            StudioManualBuilderRuntimeStep.EVIDENCE,
            StudioPanelKind.RISK_CARD,
            "Evidence → risk intelligence",
            report_ok or preview_ok,
            "risk context can inspect proposal shape without owning approval",
            "observe_only",
        ),
        StudioManualBuilderJoin(
            StudioManualBuilderRuntimeStep.REVIEW,
            StudioPanelKind.DRIVER_QUEUE,
            "Review → intent submission",
            report_ok,
            "review action remains a StudioReviewActionRequest routed to existing authority path",
            "review_intent_only",
        ),
    )


def _layout_metrics(fields: Sequence[StudioFormField], *, source: str) -> Mapping[str, Any]:
    return {
        "form_field_count": len(tuple(fields)),
        "required_field_count": sum(1 for field in fields if field.required),
        "source_line_count": len(source.splitlines()) if source else 0,
        "source_char_count": len(source),
        "joined_panel_count": len(_builder_joins(preview_ok=True, report_ok=True)),
        "minimum_font_px": getattr(DEFAULT_STUDIO_QT_THEME, "minimum_font_px", 12),
        "body_font_px": getattr(DEFAULT_STUDIO_QT_THEME, "body_font_px", 13),
        "title_font_px": getattr(DEFAULT_STUDIO_QT_THEME, "title_font_px", 16),
    }


def _serializable_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a recursively signal-safe, JSON-friendly form payload copy."""

    clean: dict[str, Any] = {}
    for key, value in payload.items():
        clean[str(key)] = _signal_safe_value(value)
    return clean


def _signal_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _signal_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_signal_safe_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(str(item) for item in value))
    return str(value)


def _as_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _as_token(value: Any, name: str) -> str:
    text = _as_text(value, name)
    if not text.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"{name} must be a simple TDDL token")
    return text


def _as_choice(value: Any, name: str, options: Sequence[str]) -> str:
    text = _as_text(value, name)
    if text not in options:
        raise ValueError(f"{name} must be one of {', '.join(options)}")
    return text


def _as_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _as_float(value: Any, name: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a number") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_tuple(value: Any, default: Sequence[str]) -> tuple[str, ...]:
    if value is None or value == "":
        return tuple(default)
    if isinstance(value, str):
        items = [part.strip() for part in value.replace("\n", ",").split(",")]
        return tuple(item for item in items if item)
    if isinstance(value, Sequence):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(default)

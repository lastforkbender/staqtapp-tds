"""Driver Studio manual proposal builder.

v3.1.10 adds a GUI-neutral workbench model for the Driver Studio cockpit.
It lets a human operator describe a bounded driver task, preview the generated
TDDL, and route the proposal through Driver Foundry for validation, audit, and
optional fixture testing. It deliberately does not approve, sign, activate,
execute arbitrary Python, write storage, mutate the Registry, or hold keys.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .foundry import DriverFoundry, DriverFoundryResult


class StudioManualProposalStatus(str, Enum):
    """Stable status values for manual Studio proposal workbench actions."""

    PREVIEWED = "previewed"
    PROPOSED = "proposed"
    INPUT_REJECTED = "input_rejected"


@dataclass(frozen=True, slots=True)
class StudioManualDriverTask:
    """Human-entered task fields for a bounded TDDL driver proposal.

    This object is intentionally form-friendly for a future PyQt5 panel.  It is
    not a registry record and it is not trusted bytecode.  The generated source
    must still pass the Foundry and later evidence/registry authority layers.
    """

    driver_id: str
    description: str
    driver_version: int = 1
    kind: str = "search"
    safety: str = "bounded"
    capabilities: tuple[str, ...] = ("registry.scan", "manifest.read", "trace.write")
    adapters: tuple[str, ...] = ("predicate.semantic_manifest.v1", "scorer.trace_rank.v1")
    scan_scope: str = ".tds"
    recursive: bool = True
    scan_limit: int = 5000
    max_depth: int = 8
    timeout_ms: int = 250
    match_field: str = "manifest.kind"
    match_eq: str = "driver"
    semantic_query: str = "policy routing"
    semantic_threshold: float = 0.80
    extract_fields: tuple[str, ...] = ("driver_id", "version", "capabilities", "safety")
    score_adapter: str = "scorer.trace_rank.v1"
    score_weight: str = "semantic"
    score_threshold: float = 0.75
    emit_mode: str = "ranked"
    emit_limit: int = 10
    trace_event: str = "studio_manual_driver_proposal"
    evolution: tuple[str, ...] = ("deny external_io", "max_delta = 1")
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class StudioManualProposalPreview:
    """Deterministic preview payload for the cockpit manual builder panel."""

    ok: bool
    status: StudioManualProposalStatus
    reason: str
    task: StudioManualDriverTask | None
    source: str
    source_hash: str
    warnings: tuple[str, ...]
    metrics: Mapping[str, int | str | bool | None]
    capability_matrix: Mapping[str, bool]


@dataclass(frozen=True, slots=True)
class StudioManualProposalReport:
    """Manual builder report routed through Driver Foundry.

    The report carries the generated source and Foundry result but gives the
    caller no Registry, signing, activation, VM-authority, storage, or private
    key capability.
    """

    ok: bool
    status: StudioManualProposalStatus
    reason: str
    task: StudioManualDriverTask | None
    source: str
    source_hash: str
    foundry_result: DriverFoundryResult | None
    warnings: tuple[str, ...]
    metrics: Mapping[str, int | str | bool | None]
    capability_matrix: Mapping[str, bool]


class DriverStudioManualProposalBuilder:
    """Manual driver-proposal workbench for the Driver Studio cockpit."""

    def __init__(self, *, foundry: DriverFoundry | None = None) -> None:
        self.foundry = foundry or DriverFoundry()

    def capability_matrix(self) -> Mapping[str, bool]:
        """Return the workbench authority boundary."""

        return {
            "render_manual_builder": True,
            "accept_human_task_fields": True,
            "generate_tddl_source": True,
            "preview_bytecode_intent": True,
            "route_to_foundry": True,
            "validate_driver": True,
            "compile_driver": True,
            "audit_driver": True,
            "test_driver_with_fixtures": True,
            "submit_review_actions": False,
            "submit_candidate": False,
            "approve_driver": False,
            "reject_driver": False,
            "quarantine_driver": False,
            "call_registry_approve": False,
            "sign_driver": False,
            "attach_signature": False,
            "activate_driver": False,
            "run_driver_vm_as_authority": False,
            "edit_active_tddl": False,
            "edit_bytecode": False,
            "write_storage": False,
            "execute_python": False,
            "mutate_registry": False,
            "store_private_keys": False,
            "bypass_policy": False,
        }

    def build_source(self, task: StudioManualDriverTask) -> str:
        """Render a deterministic TDDL source proposal from form fields."""

        normalized = _normalize_task(task)
        lines: list[str] = [
            f"driver {normalized.driver_id} v{normalized.driver_version}",
            "",
            "manifest:",
            f"  kind = {_quote(normalized.kind)}",
            f"  description = {_quote(normalized.description)}",
            f"  safety = {_quote(normalized.safety)}",
            "",
            "requires:",
        ]
        for capability in normalized.capabilities:
            lines.append(f"  capability {capability}")
        for adapter in normalized.adapters:
            lines.append(f"  adapter {adapter}")
        lines.extend(
            [
                "",
                "limits:",
                f"  max_scan = {normalized.scan_limit}",
                f"  max_depth = {normalized.max_depth}",
                f"  timeout_ms = {normalized.timeout_ms}",
                "",
                "program:",
                f"  SCAN scope={_quote(normalized.scan_scope)} recursive={_bool(normalized.recursive)} limit={normalized.scan_limit} depth={normalized.max_depth}",
                "  READ target=\"manifest\"",
                f"  MATCH field={_quote(normalized.match_field)} eq={_quote(normalized.match_eq)}",
            ]
        )
        if normalized.semantic_query:
            lines.append(
                f"  MATCH using={_quote(_semantic_adapter(normalized))} query={_quote(normalized.semantic_query)} threshold={_float(normalized.semantic_threshold)}"
            )
        lines.extend(
            [
                f"  EXTRACT from=\"manifest\" fields={_list_literal(normalized.extract_fields)}",
                f"  SCORE using={_quote(normalized.score_adapter)} weight={_quote(normalized.score_weight)} threshold={_float(normalized.score_threshold)}",
                f"  TRACE event={_quote(normalized.trace_event)}",
                f"  EMIT mode={_quote(normalized.emit_mode)} limit={normalized.emit_limit}",
                "  HALT",
                "",
                "evolution:",
            ]
        )
        for rule in normalized.evolution:
            lines.append(f"  {rule}")
        return "\n".join(lines).strip() + "\n"

    def preview_task(self, task: StudioManualDriverTask) -> StudioManualProposalPreview:
        """Return source preview and metrics without compiling or executing."""

        try:
            normalized = _normalize_task(task)
            source = self.build_source(normalized)
            warnings = _task_warnings(normalized)
            return StudioManualProposalPreview(
                ok=True,
                status=StudioManualProposalStatus.PREVIEWED,
                reason="manual driver task rendered as TDDL proposal source",
                task=normalized,
                source=source,
                source_hash=_source_hash(source),
                warnings=warnings,
                metrics=_task_metrics(normalized, source),
                capability_matrix=self.capability_matrix(),
            )
        except Exception as exc:
            return StudioManualProposalPreview(
                ok=False,
                status=StudioManualProposalStatus.INPUT_REJECTED,
                reason=str(exc),
                task=None,
                source="",
                source_hash=_source_hash(""),
                warnings=("manual task rejected before Foundry routing",),
                metrics={"ok": False, "stage": "preview"},
                capability_matrix=self.capability_matrix(),
            )

    def propose_task(
        self,
        task: StudioManualDriverTask,
        *,
        fixtures: Mapping[str, Any] | None = None,
    ) -> StudioManualProposalReport:
        """Generate source and route it through Driver Foundry only."""

        preview = self.preview_task(task)
        if not preview.ok or preview.task is None:
            return StudioManualProposalReport(
                ok=False,
                status=StudioManualProposalStatus.INPUT_REJECTED,
                reason=preview.reason,
                task=None,
                source=preview.source,
                source_hash=preview.source_hash,
                foundry_result=None,
                warnings=preview.warnings,
                metrics=preview.metrics,
                capability_matrix=preview.capability_matrix,
            )
        result = self.foundry.propose_driver(preview.source, fixtures=fixtures)
        metrics = dict(preview.metrics)
        metrics.update(
            {
                "foundry_ok": result.ok,
                "foundry_stage": result.stage.value,
                "foundry_status": result.status.value,
                "foundry_fault_count": len(result.faults),
                "package_hash": result.context.package_hash,
                "vm_status": result.context.vm_status,
            }
        )
        return StudioManualProposalReport(
            ok=result.ok,
            status=StudioManualProposalStatus.PROPOSED,
            reason=result.reason,
            task=preview.task,
            source=preview.source,
            source_hash=preview.source_hash,
            foundry_result=result,
            warnings=preview.warnings,
            metrics=metrics,
            capability_matrix=self.capability_matrix(),
        )

    # Deliberately no approve/sign/activate/execute/storage helpers.


def studio_manual_builder_capability_matrix() -> Mapping[str, bool]:
    """Convenience function for displaying the manual builder boundary."""

    return DriverStudioManualProposalBuilder().capability_matrix()


_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_ALLOWED_KINDS = {"search", "extract", "rank", "adapter", "policy"}
_ALLOWED_SAFETY = {"bounded", "restricted", "experimental"}
_ALLOWED_EMIT = {"ranked", "list", "first", "proposal"}
_ALLOWED_WEIGHT = {"semantic", "recency", "confidence", "safety", "balanced"}


def _normalize_task(task: StudioManualDriverTask) -> StudioManualDriverTask:
    driver_id = str(task.driver_id).strip()
    if not _TOKEN_RE.fullmatch(driver_id):
        raise ValueError("driver_id must be a TDDL token")
    version = int(task.driver_version)
    if version < 1:
        raise ValueError("driver_version must be >= 1")
    kind = str(task.kind).strip()
    if kind not in _ALLOWED_KINDS:
        raise ValueError("kind must be search, extract, rank, adapter, or policy")
    safety = str(task.safety).strip() or "bounded"
    if safety not in _ALLOWED_SAFETY:
        raise ValueError("safety must be bounded, restricted, or experimental")
    description = str(task.description).strip()
    if not description:
        raise ValueError("description is required for manual proposals")
    capabilities = _normalize_dotted_tuple(task.capabilities, "capability")
    adapters = _normalize_dotted_tuple(task.adapters, "adapter", allow_empty=True)
    score_adapter = str(task.score_adapter).strip()
    if score_adapter and score_adapter not in adapters:
        adapters = tuple(dict.fromkeys((*adapters, score_adapter)))
    semantic_adapter = _semantic_adapter(task)
    if task.semantic_query and semantic_adapter not in adapters:
        adapters = tuple(dict.fromkeys((*adapters, semantic_adapter)))
    scan_limit = _bounded_int(task.scan_limit, "scan_limit", 1, 100_000)
    max_depth = _bounded_int(task.max_depth, "max_depth", 0, 64)
    timeout_ms = _bounded_int(task.timeout_ms, "timeout_ms", 1, 60_000)
    emit_limit = _bounded_int(task.emit_limit, "emit_limit", 1, 10_000)
    semantic_threshold = _bounded_float(task.semantic_threshold, "semantic_threshold", 0.0, 1.0)
    score_threshold = _bounded_float(task.score_threshold, "score_threshold", 0.0, 1.0)
    scan_scope = str(task.scan_scope).strip()
    if not (scan_scope == ".tds" or scan_scope.startswith(".tds/")) or ".." in scan_scope.split("/"):
        raise ValueError("scan_scope must remain inside .tds")
    match_field = str(task.match_field).strip()
    if not _FIELD_RE.fullmatch(match_field):
        raise ValueError("match_field must be a dotted token")
    extract_fields = tuple(str(field).strip() for field in task.extract_fields if str(field).strip())
    if not extract_fields or any(not _FIELD_RE.fullmatch(field) for field in extract_fields):
        raise ValueError("extract_fields must contain dotted tokens")
    emit_mode = str(task.emit_mode).strip()
    if emit_mode not in _ALLOWED_EMIT:
        raise ValueError("emit_mode is not supported")
    score_weight = str(task.score_weight).strip()
    if score_weight not in _ALLOWED_WEIGHT:
        raise ValueError("score_weight is not supported")
    evolution = tuple(str(rule).strip() for rule in task.evolution if str(rule).strip())
    if not evolution:
        evolution = ("deny external_io", "max_delta = 1")
    if not any(rule.startswith("deny external_io") for rule in evolution):
        evolution = ("deny external_io", *evolution)
    return StudioManualDriverTask(
        driver_id=driver_id,
        description=description,
        driver_version=version,
        kind=kind,
        safety=safety,
        capabilities=capabilities,
        adapters=adapters,
        scan_scope=scan_scope,
        recursive=bool(task.recursive),
        scan_limit=scan_limit,
        max_depth=max_depth,
        timeout_ms=timeout_ms,
        match_field=match_field,
        match_eq=str(task.match_eq).strip(),
        semantic_query=str(task.semantic_query).strip(),
        semantic_threshold=semantic_threshold,
        extract_fields=extract_fields,
        score_adapter=score_adapter,
        score_weight=score_weight,
        score_threshold=score_threshold,
        emit_mode=emit_mode,
        emit_limit=emit_limit,
        trace_event=str(task.trace_event).strip() or "studio_manual_driver_proposal",
        evolution=evolution,
        tags=tuple(str(tag).strip() for tag in task.tags if str(tag).strip()),
    )


def _normalize_dotted_tuple(values: Sequence[str], label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        lowered = item.lower()
        if any(part in lowered for part in ("python.eval", "eval", "exec", "socket", "subprocess", "import")):
            raise ValueError(f"unsafe {label} is denied")
        if not _DOTTED_RE.fullmatch(item) or "." not in item:
            raise ValueError(f"{label} must be a dotted token")
        out.append(item)
    if not out and not allow_empty:
        raise ValueError(f"at least one {label} is required")
    return tuple(dict.fromkeys(out))


def _semantic_adapter(task: StudioManualDriverTask) -> str:
    for adapter in task.adapters:
        if adapter.startswith("predicate."):
            return adapter
    return "predicate.semantic_manifest.v1"


def _task_warnings(task: StudioManualDriverTask) -> tuple[str, ...]:
    warnings: list[str] = []
    if task.scan_limit > 10_000:
        warnings.append("large scan_limit should be justified in fixture evidence")
    if task.timeout_ms > 1000:
        warnings.append("timeout_ms exceeds the usual Studio quick-review range")
    if not task.semantic_query:
        warnings.append("semantic MATCH is disabled; proposal relies on field predicates and scoring")
    warnings.append("manual builder creates a proposal only; registry approval, signing, and activation remain external")
    return tuple(warnings)


def _task_metrics(task: StudioManualDriverTask, source: str) -> Mapping[str, int | str | bool | None]:
    instruction_count = 8 + (1 if task.semantic_query else 0)
    return {
        "ok": True,
        "stage": "manual_builder",
        "driver_id": task.driver_id,
        "driver_version": task.driver_version,
        "kind": task.kind,
        "capability_count": len(task.capabilities),
        "adapter_count": len(task.adapters),
        "instruction_count": instruction_count,
        "source_line_count": len(source.splitlines()),
        "scan_limit": task.scan_limit,
        "timeout_ms": task.timeout_ms,
        "fixture_required_for_evidence": True,
    }


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return number


def _bounded_float(value: Any, label: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except Exception as exc:
        raise ValueError(f"{label} must be a number") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return number


def _quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _float(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _list_literal(values: Sequence[str]) -> str:
    return "[" + ", ".join(repr(str(value)) for value in values) + "]"


def _source_hash(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()

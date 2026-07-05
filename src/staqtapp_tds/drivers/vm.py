"""Native-facing Driver VM runtime and skeleton.

v3.1.1 adds a non-halting Driver VM result framework. Driver bytecode may
halt, fault, reject bad input, or exceed budget, but expected runtime
conditions are reported through :class:`DriverVMResult` instead of escaping as
Python exceptions from ``execute()``. This keeps the host process, future
Runtime Manager, and Driver Studio result-first while preserving fail-closed
bytecode loading.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .audit import audit_vm_contract, vm_contract_table
from .bytecode import BytecodePackage
from .trace import TraceEvidence, rank_traces


class VMState(str, Enum):
    EMPTY = "empty"
    LOADED = "loaded"
    REJECTED = "rejected"
    EXECUTION_DISABLED = "execution_disabled"
    EXECUTED = "executed"


class VMStatus(str, Enum):
    """Structured execution status for non-halting Driver VM calls."""

    NOT_LOADED = "not_loaded"
    LOADED = "loaded"
    HALTED = "halted"
    FAULTED = "faulted"
    REJECTED = "rejected"
    INPUT_REJECTED = "input_rejected"
    POLICY_REJECTED = "policy_rejected"
    BUDGET_EXCEEDED = "budget_exceeded"
    INSTRUCTION_LIMIT_EXCEEDED = "instruction_limit_exceeded"
    EXECUTION_DISABLED = "execution_disabled"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class VMLoadedPackage:
    driver_id: str
    driver_version: int
    driver_class: str
    instruction_count: int
    package_hash: str
    cost_budget: int


@dataclass(frozen=True, slots=True)
class VMFault:
    """One structured runtime fault suitable for Studio and telemetry panels."""

    code: str
    message: str
    instruction_pointer: int | None = None
    instruction: str | None = None
    severity: str = "error"
    recoverable: bool = False


@dataclass(frozen=True, slots=True)
class DriverVMContext:
    """Compact execution context captured on success and failure."""

    driver_id: str | None = None
    driver_version: int | None = None
    driver_class: str | None = None
    package_hash: str | None = None
    instruction_pointer: int | None = None
    instruction: str | None = None
    cost_used: int = 0
    max_cost: int = 0
    records_seen: int = 0
    current_count: int = 0
    emitted_count: int = 0


@dataclass(frozen=True, slots=True)
class DriverVMResult:
    """Result-first Driver VM execution envelope.

    This deliberately mirrors the non-halting spirit of ``TDSResult`` while
    carrying VM-specific evidence: status, faults, trace, costs, driver/package
    identity, partial outputs, and execution context.
    """

    ok: bool
    status: VMStatus
    reason: str
    state: VMState = VMState.REJECTED
    trace: tuple[str, ...] = ()
    emitted: tuple[Mapping[str, Any], ...] = ()
    trace_events: tuple[Mapping[str, Any], ...] = ()
    faults: tuple[VMFault, ...] = ()
    metrics: Mapping[str, int | str | bool | None] = field(default_factory=dict)
    context: DriverVMContext = field(default_factory=DriverVMContext)
    cost_used: int = 0
    package_hash: str | None = None
    driver_id: str | None = None
    driver_version: int | None = None
    partial: bool = False


# Backwards-compatible public name retained for v3.0.8/v3.1.0 callers.
VMExecutionResult = DriverVMResult


@dataclass(slots=True)
class _RuntimeContext:
    records: list[dict[str, Any]]
    current: list[dict[str, Any]] = field(default_factory=list)
    read_target: str | None = None
    extracted: list[dict[str, Any]] = field(default_factory=list)
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    cost_used: int = 0
    halted: bool = False


class _VMRuntimeFault(Exception):
    def __init__(
        self,
        status: VMStatus,
        code: str,
        message: str,
        *,
        instruction_pointer: int | None = None,
        instruction: str | None = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.fault = VMFault(
            code=code,
            message=message,
            instruction_pointer=instruction_pointer,
            instruction=instruction,
            recoverable=recoverable,
        )


class DriverVMSkeleton:
    """Fail-closed VM loader shell.

    The skeleton keeps the pre-runtime contract intact. It validates and loads
    bytecode packages, but its ``execute`` method remains disabled. Use
    :class:`DriverVMRuntime` for deterministic execution.
    """

    def __init__(self, *, max_instructions: int = 1024, max_cost: int = 100_000) -> None:
        if max_instructions < 1:
            raise ValueError("max_instructions must be positive")
        if max_cost < 1:
            raise ValueError("max_cost must be positive")
        self.max_instructions = max_instructions
        self.max_cost = max_cost
        self.state = VMState.EMPTY
        self.loaded: VMLoadedPackage | None = None
        self.package: BytecodePackage | None = None

    def load(self, package: BytecodePackage) -> VMLoadedPackage:
        """Validate and load a package."""

        try:
            loaded = _validate_load(package, max_instructions=self.max_instructions, max_cost=self.max_cost)
        except Exception:
            self.state = VMState.REJECTED
            self.loaded = None
            self.package = None
            raise
        self.state = VMState.LOADED
        self.loaded = loaded
        self.package = package
        return loaded

    def execute(self, _inputs: Mapping[str, Any] | None = None) -> DriverVMResult:
        """Fail closed: skeleton intentionally does not execute driver bytecode."""

        if self.state is not VMState.LOADED or self.loaded is None:
            self.state = VMState.REJECTED
            return _result(
                ok=False,
                status=VMStatus.NOT_LOADED,
                state=VMState.REJECTED,
                reason="no validated bytecode package is loaded",
                loaded=self.loaded,
                max_cost=self.max_cost,
                trace=("validate", "load", "not_loaded"),
                faults=(VMFault("vm.not_loaded", "no validated bytecode package is loaded"),),
            )
        self.state = VMState.EXECUTION_DISABLED
        return _result(
            ok=False,
            status=VMStatus.EXECUTION_DISABLED,
            state=VMState.EXECUTION_DISABLED,
            reason="driver bytecode execution is intentionally disabled in DriverVMSkeleton; use DriverVMRuntime",
            loaded=self.loaded,
            max_cost=self.max_cost,
            trace=("validate", "load", "execution_disabled"),
            faults=(
                VMFault(
                    "vm.execution_disabled",
                    "driver bytecode execution is intentionally disabled in DriverVMSkeleton; use DriverVMRuntime",
                ),
            ),
        )


class DriverVMRuntime(DriverVMSkeleton):
    """Deterministic runtime for the safe search/extraction opcode set.

    Inputs are in-memory record snapshots with optional keys such as ``path``,
    ``manifest``, ``payload_header``, ``schema``, ``trace``, ``key`` and
    ``value``. This preserves the separation from the Native Storage Engine.
    """

    def execute(self, inputs: Mapping[str, Any] | None = None) -> DriverVMResult:
        if self.state is not VMState.LOADED or self.loaded is None or self.package is None:
            self.state = VMState.REJECTED
            return _result(
                ok=False,
                status=VMStatus.NOT_LOADED,
                state=VMState.REJECTED,
                reason="no validated bytecode package is loaded",
                loaded=self.loaded,
                max_cost=self.max_cost,
                trace=("validate", "load", "not_loaded"),
                faults=(VMFault("vm.not_loaded", "no validated bytecode package is loaded"),),
            )

        ctx: _RuntimeContext | None = None
        trace_names: list[str] = ["validate", "load"]
        instruction_pointer: int | None = None
        instruction_name: str | None = None
        try:
            records = _normalize_records((inputs or {}).get("records", ()))
            ctx = _RuntimeContext(records=records, current=list(records))
            for instruction_pointer, instr in enumerate(self.package.instructions):
                instruction_name = instr.name
                operands = _operands_for(self.package, instr.operand_ref)
                ctx.cost_used += _instruction_cost(instr.name)
                if ctx.cost_used > self.max_cost:
                    raise _VMRuntimeFault(
                        VMStatus.BUDGET_EXCEEDED,
                        "vm.budget_exceeded",
                        "VM runtime cost exceeded",
                        instruction_pointer=instruction_pointer,
                        instruction=instruction_name,
                    )
                trace_names.append(instr.name)
                _execute_instruction(instr.name, operands, ctx, instruction_pointer=instruction_pointer)
                if ctx.halted:
                    break
            if not ctx.halted:
                raise _VMRuntimeFault(
                    VMStatus.FAULTED,
                    "vm.no_halt",
                    "VM runtime did not halt",
                    instruction_pointer=instruction_pointer,
                    instruction=instruction_name,
                )
            self.state = VMState.EXECUTED
            emitted = tuple(copy.deepcopy(dict(item)) for item in ctx.extracted)
            return _result(
                ok=True,
                status=VMStatus.HALTED,
                state=VMState.EXECUTED,
                reason="driver bytecode halted successfully",
                loaded=self.loaded,
                max_cost=self.max_cost,
                ctx=ctx,
                instruction_pointer=instruction_pointer,
                instruction=instruction_name,
                trace=tuple(trace_names),
                emitted=emitted,
                trace_events=tuple(copy.deepcopy(item) for item in ctx.trace_events),
                partial=False,
            )
        except _VMRuntimeFault as exc:
            self.state = VMState.REJECTED
            trace_names.append(exc.status.value)
            partial = bool(ctx and ctx.extracted)
            return _result(
                ok=False,
                status=exc.status,
                state=VMState.REJECTED,
                reason=exc.fault.message,
                loaded=self.loaded,
                max_cost=self.max_cost,
                ctx=ctx,
                instruction_pointer=exc.fault.instruction_pointer,
                instruction=exc.fault.instruction,
                trace=tuple(trace_names),
                emitted=tuple(copy.deepcopy(dict(item)) for item in (ctx.extracted if ctx else ())),
                trace_events=tuple(copy.deepcopy(item) for item in (ctx.trace_events if ctx else ())),
                faults=(exc.fault,),
                partial=partial,
            )
        except Exception as exc:  # Defensive VM boundary: expected callers still receive a result.
            self.state = VMState.REJECTED
            trace_names.append(VMStatus.INTERNAL_ERROR.value)
            message = f"internal VM error: {exc}"
            fault = VMFault(
                "vm.internal_error",
                message,
                instruction_pointer=instruction_pointer,
                instruction=instruction_name,
                recoverable=False,
            )
            return _result(
                ok=False,
                status=VMStatus.INTERNAL_ERROR,
                state=VMState.REJECTED,
                reason=message,
                loaded=self.loaded,
                max_cost=self.max_cost,
                ctx=ctx,
                instruction_pointer=instruction_pointer,
                instruction=instruction_name,
                trace=tuple(trace_names),
                emitted=tuple(copy.deepcopy(dict(item)) for item in (ctx.extracted if ctx else ())),
                trace_events=tuple(copy.deepcopy(item) for item in (ctx.trace_events if ctx else ())),
                faults=(fault,),
                partial=bool(ctx and ctx.extracted),
            )


def _result(
    *,
    ok: bool,
    status: VMStatus,
    state: VMState,
    reason: str,
    loaded: VMLoadedPackage | None,
    max_cost: int,
    ctx: _RuntimeContext | None = None,
    instruction_pointer: int | None = None,
    instruction: str | None = None,
    trace: tuple[str, ...] = (),
    emitted: tuple[Mapping[str, Any], ...] = (),
    trace_events: tuple[Mapping[str, Any], ...] = (),
    faults: tuple[VMFault, ...] = (),
    partial: bool = False,
) -> DriverVMResult:
    context = DriverVMContext(
        driver_id=loaded.driver_id if loaded else None,
        driver_version=loaded.driver_version if loaded else None,
        driver_class=loaded.driver_class if loaded else None,
        package_hash=loaded.package_hash if loaded else None,
        instruction_pointer=instruction_pointer,
        instruction=instruction,
        cost_used=ctx.cost_used if ctx else 0,
        max_cost=max_cost,
        records_seen=len(ctx.records) if ctx else 0,
        current_count=len(ctx.current) if ctx else 0,
        emitted_count=len(emitted),
    )
    metrics: dict[str, int | str | bool | None] = {
        "cost_used": context.cost_used,
        "max_cost": max_cost,
        "records_seen": context.records_seen,
        "current_count": context.current_count,
        "emitted_count": context.emitted_count,
        "fault_count": len(faults),
        "partial": partial,
        "status": status.value,
    }
    return DriverVMResult(
        ok=ok,
        status=status,
        state=state,
        reason=reason,
        trace=trace,
        emitted=emitted,
        trace_events=trace_events,
        faults=faults,
        metrics=metrics,
        context=context,
        cost_used=context.cost_used,
        package_hash=loaded.package_hash if loaded else None,
        driver_id=loaded.driver_id if loaded else None,
        driver_version=loaded.driver_version if loaded else None,
        partial=partial,
    )


def _validate_load(package: BytecodePackage, *, max_instructions: int, max_cost: int) -> VMLoadedPackage:
    audit_vm_contract(package)
    if len(package.instructions) > max_instructions:
        raise ValueError("instruction count exceeds VM limit")
    cost_budget = sum(_instruction_cost(instr.name) for instr in package.instructions)
    if cost_budget > max_cost:
        raise ValueError("instruction cost exceeds VM limit")
    return VMLoadedPackage(
        driver_id=str(package.header["driver_id"]),
        driver_version=int(package.header["driver_version"]),
        driver_class=str(package.manifest["kind"]),
        instruction_count=len(package.instructions),
        package_hash=package.package_hash,
        cost_budget=cost_budget,
    )


def _execute_instruction(name: str, operands: Mapping[str, Any], ctx: _RuntimeContext, *, instruction_pointer: int) -> None:
    if name == "SCAN":
        _op_scan(operands, ctx, instruction_pointer=instruction_pointer)
    elif name == "READ":
        ctx.read_target = str(operands["target"])
    elif name == "MATCH":
        _op_match(operands, ctx, instruction_pointer=instruction_pointer)
    elif name == "EXTRACT":
        _op_extract(operands, ctx, instruction_pointer=instruction_pointer)
    elif name == "SCORE":
        _op_score(operands, ctx, instruction_pointer=instruction_pointer)
    elif name == "TRACE":
        ctx.trace_events.append({"event": str(operands["event"]), "count": len(ctx.current)})
    elif name == "EMIT":
        _op_emit(operands, ctx, instruction_pointer=instruction_pointer)
    elif name == "HALT":
        ctx.halted = True
    else:
        raise _VMRuntimeFault(
            VMStatus.FAULTED,
            "vm.unsupported_opcode",
            f"unsupported runtime opcode {name}",
            instruction_pointer=instruction_pointer,
            instruction=name,
        )


def _op_scan(operands: Mapping[str, Any], ctx: _RuntimeContext, *, instruction_pointer: int) -> None:
    unsupported = sorted(set(operands) & {"kind", "include", "exclude"})
    if unsupported:
        raise _VMRuntimeFault(
            VMStatus.FAULTED,
            "vm.scan.unsupported_operand",
            f"SCAN operands are not runtime-supported yet: {unsupported}",
            instruction_pointer=instruction_pointer,
            instruction="SCAN",
        )
    scope = str(operands["scope"])
    limit = int(operands.get("limit", len(ctx.records) or 1))
    recursive = bool(operands.get("recursive", False))
    depth = int(operands.get("depth", 0 if not recursive else 64))
    matched: list[dict[str, Any]] = []
    prefix = scope.rstrip("/")
    for record in ctx.records:
        path = str(record.get("path", ""))
        if not (path == prefix or path.startswith(prefix + "/")):
            continue
        rel = path[len(prefix):].strip("/")
        record_depth = 0 if not rel else rel.count("/") + 1
        if not recursive and record_depth > 1:
            continue
        if recursive and record_depth > depth:
            continue
        matched.append(copy.deepcopy(record))
        if len(matched) >= limit:
            break
    ctx.current = matched


def _op_match(operands: Mapping[str, Any], ctx: _RuntimeContext, *, instruction_pointer: int) -> None:
    if "field" in operands:
        field = str(operands["field"])
        _require_field_predicate(operands, instruction_pointer=instruction_pointer)
        ctx.current = [
            record for record in ctx.current if _field_match(_resolve_path(record, field), operands, instruction_pointer=instruction_pointer)
        ]
        return
    if "using" in operands:
        adapter = str(operands.get("using"))
        if adapter != "predicate.semantic_manifest.v1":
            raise _VMRuntimeFault(
                VMStatus.FAULTED,
                "vm.adapter.unsupported",
                f"MATCH adapter is not runtime-supported: {adapter}",
                instruction_pointer=instruction_pointer,
                instruction="MATCH",
            )
        query = str(operands.get("query", "")).lower()
        threshold = float(operands.get("threshold", 0.0))
        ctx.current = [record for record in ctx.current if _semantic_match(record, query, threshold)]
        return
    raise _VMRuntimeFault(
        VMStatus.FAULTED,
        "vm.match.missing_source",
        "MATCH requires field or using",
        instruction_pointer=instruction_pointer,
        instruction="MATCH",
    )


def _op_extract(operands: Mapping[str, Any], ctx: _RuntimeContext, *, instruction_pointer: int) -> None:
    if "using" in operands:
        raise _VMRuntimeFault(
            VMStatus.FAULTED,
            "vm.adapter.unsupported",
            f"EXTRACT adapter execution is not runtime-supported yet: {operands['using']}",
            instruction_pointer=instruction_pointer,
            instruction="EXTRACT",
        )
    source = str(operands.get("from", ctx.read_target or "manifest"))
    fields = operands.get("fields")
    limit = int(operands.get("limit", len(ctx.current) or 1))
    extracted: list[dict[str, Any]] = []
    if fields is None:
        fields = []
    for record in ctx.current[:limit]:
        row: dict[str, Any] = {}
        for field in fields:
            field_name = str(field)
            row[field_name] = copy.deepcopy(_resolve_path(record, f"{source}.{field_name}"))
        if "path" in record and "path" not in row:
            row["path"] = record["path"]
        row["_driver_match_score"] = float(record.get("semantic_score", 1.0))
        extracted.append(row)
    ctx.extracted = extracted


def _op_score(operands: Mapping[str, Any], ctx: _RuntimeContext, *, instruction_pointer: int) -> None:
    adapter = operands.get("using")
    if adapter is not None and str(adapter) != "scorer.trace_rank.v1":
        raise _VMRuntimeFault(
            VMStatus.FAULTED,
            "vm.adapter.unsupported",
            f"SCORE adapter is not runtime-supported: {adapter}",
            instruction_pointer=instruction_pointer,
            instruction="SCORE",
        )
    unsupported = sorted(set(operands) & {"by", "boost", "penalty"})
    if unsupported:
        raise _VMRuntimeFault(
            VMStatus.FAULTED,
            "vm.score.unsupported_operand",
            f"SCORE operands are not runtime-supported yet: {unsupported}",
            instruction_pointer=instruction_pointer,
            instruction="SCORE",
        )
    threshold = float(operands.get("threshold", 0.0))
    traces: list[TraceEvidence] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for idx, item in enumerate(ctx.extracted):
        driver_id = str(item.get("driver_id") or item.get("id") or f"result_{idx}")
        path = str(item.get("path", f"result_{idx}"))
        semantic = float(item.get("_driver_match_score", 1.0))
        manifest_score = float(item.get("manifest_score", semantic))
        extraction_score = 1.0 if any(v is not None for k, v in item.items() if not k.startswith("_")) else 0.0
        lineage = float(item.get("lineage_trust", 1.0))
        evidence = TraceEvidence(driver_id, path, semantic, manifest_score, extraction_score, lineage)
        if evidence.rank_score >= threshold:
            traces.append(evidence)
            by_key[(driver_id, path)] = item
    ranked = rank_traces(traces)
    out: list[dict[str, Any]] = []
    for evidence in ranked:
        item = copy.deepcopy(by_key[(evidence.driver_id, evidence.path)])
        item["rank_score"] = evidence.rank_score
        out.append(item)
    ctx.extracted = out


def _op_emit(operands: Mapping[str, Any], ctx: _RuntimeContext, *, instruction_pointer: int) -> None:
    limit = int(operands.get("limit", len(ctx.extracted) or len(ctx.current) or 1))
    mode = str(operands.get("mode", "list"))
    if mode == "proposal":
        raise _VMRuntimeFault(
            VMStatus.FAULTED,
            "vm.emit.proposal_unsupported",
            "EMIT mode=proposal is reserved for the future evolution engine",
            instruction_pointer=instruction_pointer,
            instruction="EMIT",
        )
    if not ctx.extracted:
        ctx.extracted = [copy.deepcopy(dict(record)) for record in ctx.current]
    if mode == "first":
        ctx.extracted = ctx.extracted[:1]
    else:
        ctx.extracted = ctx.extracted[:limit]


def _require_field_predicate(operands: Mapping[str, Any], *, instruction_pointer: int) -> None:
    predicates = {"eq", "neq", "contains", "prefix", "suffix", "in", "exists", "regex_limited", "range"}
    if not predicates.intersection(operands):
        raise _VMRuntimeFault(
            VMStatus.FAULTED,
            "vm.match.no_predicate",
            "MATCH field requires at least one predicate operand",
            instruction_pointer=instruction_pointer,
            instruction="MATCH",
        )


def _field_match(value: Any, operands: Mapping[str, Any], *, instruction_pointer: int) -> bool:
    if "exists" in operands:
        want = bool(operands["exists"])
        return (value is not None) is want
    if "eq" in operands and value != operands["eq"]:
        return False
    if "neq" in operands and value == operands["neq"]:
        return False
    if "contains" in operands and str(operands["contains"]) not in str(value):
        return False
    if "prefix" in operands and not str(value).startswith(str(operands["prefix"])):
        return False
    if "suffix" in operands and not str(value).endswith(str(operands["suffix"])):
        return False
    if "in" in operands and value not in operands["in"]:
        return False
    if "regex_limited" in operands:
        try:
            if re.search(str(operands["regex_limited"]), str(value)) is None:
                return False
        except re.error as exc:
            raise _VMRuntimeFault(
                VMStatus.FAULTED,
                "vm.match.bad_regex",
                f"MATCH.regex_limited failed at runtime: {exc}",
                instruction_pointer=instruction_pointer,
                instruction="MATCH",
            ) from exc
    if "range" in operands:
        bounds = operands["range"]
        if not isinstance(bounds, Sequence) or isinstance(bounds, (str, bytes, bytearray)) or len(bounds) != 2:
            raise _VMRuntimeFault(
                VMStatus.FAULTED,
                "vm.match.bad_range",
                "MATCH.range must be a two-item numeric sequence",
                instruction_pointer=instruction_pointer,
                instruction="MATCH",
            )
        try:
            numeric = float(value)
            low = float(bounds[0])
            high = float(bounds[1])
        except (TypeError, ValueError) as exc:
            raise _VMRuntimeFault(
                VMStatus.FAULTED,
                "vm.match.bad_range",
                "MATCH.range requires numeric value and bounds",
                instruction_pointer=instruction_pointer,
                instruction="MATCH",
            ) from exc
        if numeric < low or numeric > high:
            return False
    return True


def _semantic_match(record: Mapping[str, Any], query: str, threshold: float) -> bool:
    if not query:
        return True
    haystack = " ".join(_flatten_strings(record)).lower()
    terms = [term for term in query.split() if term]
    score = 1.0 if all(term in haystack for term in terms) else 0.0
    if "semantic_score" in record:
        try:
            score = max(score, float(record["semantic_score"]))
        except (TypeError, ValueError):
            pass
    return score >= threshold


def _resolve_path(record: Mapping[str, Any], dotted: str) -> Any:
    parts = dotted.split(".")
    value: Any = record
    if parts and parts[0] in {"manifest", "payload_header", "schema", "trace", "registry", "capabilities", "value", "key"}:
        pass
    for part in parts:
        if isinstance(value, Mapping):
            value = value.get(part)
        else:
            return None
    return value


def _flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            out.extend(_flatten_strings(item))
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            out.extend(_flatten_strings(item))
    elif value is not None:
        out.append(str(value))
    return out


def _normalize_records(records: Any) -> list[dict[str, Any]]:
    if records is None:
        return []
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise _VMRuntimeFault(VMStatus.INPUT_REJECTED, "vm.input.records", "VM runtime inputs.records must be a sequence")
    normalized: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping):
            raise _VMRuntimeFault(VMStatus.INPUT_REJECTED, "vm.input.record", "VM runtime records must be mappings")
        normalized.append(copy.deepcopy(dict(item)))
    return normalized


def _operands_for(package: BytecodePackage, operand_ref: int) -> Mapping[str, Any]:
    value = package.constants[operand_ref]
    if not isinstance(value, Mapping):
        raise _VMRuntimeFault(VMStatus.FAULTED, "vm.operand.invalid", "operand constant is not a mapping")
    return dict(value)


def _instruction_cost(name: str) -> int:
    try:
        return int(vm_contract_table()[name]["cost"])
    except KeyError as exc:
        raise _VMRuntimeFault(VMStatus.FAULTED, "vm.unsupported_opcode", f"unsupported runtime opcode {name}") from exc

"""TDDL grammar and validation model for future native Driver VM.

v3.0.6 intentionally does not execute driver programs. It parses a strict,
small TDS Driver Language subset into a stable intermediate representation and
validates syntax, bounds, capabilities and adapter declarations before any
native Driver VM exists.
"""
from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping


class TDDLValidationError(ValueError):
    """Raised when TDDL source fails closed during parsing or validation."""


class InstructionName(str, Enum):
    SCAN = "SCAN"
    READ = "READ"
    MATCH = "MATCH"
    EXTRACT = "EXTRACT"
    MAP = "MAP"
    SCORE = "SCORE"
    BRANCH = "BRANCH"
    CALL = "CALL"
    EMIT = "EMIT"
    TRACE = "TRACE"
    PROPOSE = "PROPOSE"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class TDDLInstruction:
    name: InstructionName
    operands: Mapping[str, Any] = field(default_factory=dict)
    line: int = 0


@dataclass(frozen=True, slots=True)
class TDDLProgram:
    driver_id: str
    version: int
    manifest: Mapping[str, Any]
    capabilities: tuple[str, ...]
    adapters: tuple[str, ...]
    limits: Mapping[str, Any]
    instructions: tuple[TDDLInstruction, ...]
    evolution: tuple[str, ...] = field(default_factory=tuple)

    @property
    def instruction_names(self) -> tuple[str, ...]:
        return tuple(instruction.name.value for instruction in self.instructions)


@dataclass(frozen=True, slots=True)
class InstructionSpec:
    name: InstructionName
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    allowed_values: Mapping[str, frozenset[Any]] = field(default_factory=dict)

    @property
    def allowed(self) -> frozenset[str]:
        return self.required | self.optional


_INSTRUCTION_SPECS: dict[InstructionName, InstructionSpec] = {
    InstructionName.SCAN: InstructionSpec(
        InstructionName.SCAN,
        required=frozenset({"scope"}),
        optional=frozenset({"recursive", "limit", "depth", "kind", "include", "exclude"}),
    ),
    InstructionName.READ: InstructionSpec(
        InstructionName.READ,
        required=frozenset({"target"}),
        allowed_values={
            "target": frozenset({"manifest", "payload_header", "key", "value", "schema", "trace", "registry", "capabilities"})
        },
    ),
    InstructionName.MATCH: InstructionSpec(
        InstructionName.MATCH,
        optional=frozenset({"field", "eq", "neq", "contains", "prefix", "suffix", "in", "exists", "regex_limited", "range", "using", "query", "threshold", "tags"}),
    ),
    InstructionName.EXTRACT: InstructionSpec(
        InstructionName.EXTRACT,
        optional=frozenset({"fields", "using", "from", "as", "limit", "required"}),
        allowed_values={"from": frozenset({"manifest", "value", "schema", "trace", "payload_header", "registry"})},
    ),
    InstructionName.MAP: InstructionSpec(InstructionName.MAP, required=frozenset({"using"}), optional=frozenset({"from", "as"})),
    InstructionName.SCORE: InstructionSpec(
        InstructionName.SCORE,
        optional=frozenset({"using", "by", "weight", "boost", "penalty", "threshold"}),
        allowed_values={"weight": frozenset({"semantic", "recency", "confidence", "safety", "balanced"})},
    ),
    InstructionName.BRANCH: InstructionSpec(InstructionName.BRANCH, required=frozenset({"if", "goto"})),
    InstructionName.CALL: InstructionSpec(InstructionName.CALL, required=frozenset({"adapter"}), optional=frozenset({"mode"})),
    InstructionName.EMIT: InstructionSpec(
        InstructionName.EMIT,
        optional=frozenset({"mode", "limit"}),
        allowed_values={"mode": frozenset({"ranked", "list", "first", "proposal"})},
    ),
    InstructionName.TRACE: InstructionSpec(InstructionName.TRACE, required=frozenset({"event"}), optional=frozenset({"level"})),
    InstructionName.PROPOSE: InstructionSpec(InstructionName.PROPOSE, required=frozenset({"kind"}), optional=frozenset({"target", "reason"})),
    InstructionName.HALT: InstructionSpec(InstructionName.HALT),
}

_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_ALLOWED_EVOLUTION_PREFIXES = (
    "allow reorder ",
    "allow replace ",
    "deny ",
    "max_delta ",
    "max_delta=",
)


def instruction_specs() -> Mapping[str, InstructionSpec]:
    """Return the self-describing instruction metadata table for Studio/Builder use."""

    return {name.value: spec for name, spec in _INSTRUCTION_SPECS.items()}


def parse_tddl(source: str) -> TDDLProgram:
    """Parse strict TDDL source into a non-executing intermediate representation."""

    cleaned = _clean_lines(source)
    if not cleaned:
        raise TDDLValidationError("empty TDDL source")

    first_lineno, first = cleaned[0]
    m = re.fullmatch(r"driver\s+([A-Za-z_][A-Za-z0-9_-]*)\s+v([0-9]+)", first)
    if not m:
        raise TDDLValidationError(f"line {first_lineno}: expected 'driver Name vN'")
    driver_id, version_text = m.groups()
    version = int(version_text)

    sections: dict[str, list[tuple[int, str]]] = {"manifest": [], "requires": [], "limits": [], "program": [], "evolution": []}
    current: str | None = None
    for lineno, line in cleaned[1:]:
        if line.endswith(":") and line[:-1] in sections:
            current = line[:-1]
            continue
        if current is None:
            raise TDDLValidationError(f"line {lineno}: content must appear inside a known section")
        sections[current].append((lineno, line))

    manifest = _parse_assignment_section(sections["manifest"], section="manifest")
    limits = _parse_assignment_section(sections["limits"], section="limits")
    capabilities, adapters = _parse_requires(sections["requires"])
    instructions = tuple(_parse_instruction(lineno, line) for lineno, line in sections["program"])
    evolution = tuple(line for _lineno, line in sections["evolution"])

    program = TDDLProgram(
        driver_id=driver_id,
        version=version,
        manifest=manifest,
        capabilities=capabilities,
        adapters=adapters,
        limits=limits,
        instructions=instructions,
        evolution=evolution,
    )
    validate_tddl(program)
    return program


def validate_tddl(program: TDDLProgram) -> None:
    """Validate TDDL syntax contracts without executing driver behavior."""

    if program.version < 1:
        raise TDDLValidationError("driver version must be >= 1")
    _validate_token(program.driver_id, "driver_id")
    if "kind" not in program.manifest:
        raise TDDLValidationError("manifest.kind is required")
    if str(program.manifest["kind"]) not in {"search", "extract", "rank", "adapter", "policy"}:
        raise TDDLValidationError("manifest.kind must be search, extract, rank, adapter or policy")
    if not program.capabilities:
        raise TDDLValidationError("requires must declare at least one capability")
    for capability in program.capabilities:
        _validate_dotted_token(capability, "capability")
    for adapter in program.adapters:
        _validate_dotted_token(adapter, "adapter")
        _reject_unsafe_adapter(adapter)
    if not program.instructions:
        raise TDDLValidationError("program must contain at least HALT")
    if program.instructions[-1].name is not InstructionName.HALT:
        raise TDDLValidationError("program must end with HALT")
    if sum(1 for instr in program.instructions if instr.name is InstructionName.HALT) != 1:
        raise TDDLValidationError("program must contain exactly one HALT")

    max_scan = _int_limit(program.limits.get("max_scan", 5000), "max_scan", minimum=1, maximum=100_000)
    max_depth = _int_limit(program.limits.get("max_depth", 8), "max_depth", minimum=0, maximum=64)
    _int_limit(program.limits.get("timeout_ms", 250), "timeout_ms", minimum=1, maximum=60_000)

    for instr in program.instructions:
        _validate_instruction(program, instr, max_scan=max_scan, max_depth=max_depth)
    for evo in program.evolution:
        if not evo.startswith(_ALLOWED_EVOLUTION_PREFIXES):
            raise TDDLValidationError(f"unsupported evolution rule: {evo}")


def _clean_lines(source: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append((lineno, line))
    return out


def _parse_assignment_section(lines: Iterable[tuple[int, str]], *, section: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for lineno, line in lines:
        if "=" not in line:
            raise TDDLValidationError(f"line {lineno}: {section} entries must use key = value")
        key, value = [part.strip() for part in line.split("=", 1)]
        if not _TOKEN_RE.fullmatch(key):
            raise TDDLValidationError(f"line {lineno}: invalid {section} key")
        data[key] = _parse_value(value)
    return data


def _parse_requires(lines: Iterable[tuple[int, str]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    capabilities: list[str] = []
    adapters: list[str] = []
    for lineno, line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in {"capability", "adapter"}:
            raise TDDLValidationError(f"line {lineno}: requires entries must be 'capability X' or 'adapter X'")
        if parts[0] == "capability":
            capabilities.append(parts[1])
        else:
            adapters.append(parts[1])
    return tuple(capabilities), tuple(adapters)


def _parse_instruction(lineno: int, line: str) -> TDDLInstruction:
    parts = line.split(maxsplit=1)
    if not parts:
        raise TDDLValidationError(f"line {lineno}: empty instruction")
    try:
        name = InstructionName(parts[0])
    except ValueError as exc:
        raise TDDLValidationError(f"line {lineno}: unknown instruction {parts[0]!r}") from exc
    operands: dict[str, Any] = {}
    rest = parts[1] if len(parts) == 2 else ""
    pos = 0
    pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_.-]*)=(\"[^\"]*\"|'[^']*'|\[[^\]]*\]|[^\s]+)")
    for match in pattern.finditer(rest):
        gap = rest[pos:match.start()].strip()
        if gap:
            raise TDDLValidationError(f"line {lineno}: operands must use key=value")
        key, value = match.groups()
        operands[key] = _parse_value(value)
        pos = match.end()
    if rest[pos:].strip():
        raise TDDLValidationError(f"line {lineno}: operands must use key=value")
    return TDDLInstruction(name=name, operands=operands, line=lineno)


def _parse_value(value: str) -> Any:
    text = value.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    if re.fullmatch(r"-?[0-9]+\.[0-9]+", text):
        return float(text)
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError) as exc:
            raise TDDLValidationError("invalid list literal") from exc
        if not isinstance(parsed, list):
            raise TDDLValidationError("only list literals are supported")
        return parsed
    return text


def _validate_instruction(program: TDDLProgram, instr: TDDLInstruction, *, max_scan: int, max_depth: int) -> None:
    spec = _INSTRUCTION_SPECS[instr.name]
    keys = set(instr.operands)
    missing = spec.required - keys
    unknown = keys - spec.allowed
    if missing:
        raise TDDLValidationError(f"line {instr.line}: {instr.name.value} missing operands {sorted(missing)}")
    if unknown:
        raise TDDLValidationError(f"line {instr.line}: {instr.name.value} unknown operands {sorted(unknown)}")
    for key, allowed in spec.allowed_values.items():
        if key in instr.operands and instr.operands[key] not in allowed:
            raise TDDLValidationError(f"line {instr.line}: {instr.name.value}.{key} has unsupported value")

    if instr.name is InstructionName.SCAN:
        _validate_scan(instr, max_scan=max_scan, max_depth=max_depth)
    elif instr.name is InstructionName.MATCH:
        _validate_match(program, instr)
    elif instr.name is InstructionName.EXTRACT:
        _validate_extract(program, instr)
    elif instr.name in {InstructionName.SCORE, InstructionName.MAP}:
        _validate_adapter_use(program, instr)
        if "threshold" in instr.operands:
            _validate_threshold(instr.operands["threshold"], instr.line)
    elif instr.name is InstructionName.CALL:
        adapter = str(instr.operands["adapter"])
        _reject_unsafe_adapter(adapter)
        if adapter not in program.adapters:
            raise TDDLValidationError(f"line {instr.line}: CALL adapter must be declared in requires")
    elif instr.name is InstructionName.EMIT:
        if "limit" in instr.operands:
            _int_limit(instr.operands["limit"], "EMIT.limit", minimum=1, maximum=10_000)
    elif instr.name is InstructionName.PROPOSE:
        if str(instr.operands.get("kind")) not in {"reorder", "replace", "score_policy", "predicate_policy"}:
            raise TDDLValidationError(f"line {instr.line}: PROPOSE.kind is not allowed")
    elif instr.name is InstructionName.HALT and instr.operands:
        raise TDDLValidationError(f"line {instr.line}: HALT takes no operands")


def _validate_scan(instr: TDDLInstruction, *, max_scan: int, max_depth: int) -> None:
    scope = str(instr.operands["scope"])
    if scope.startswith("/") or ".." in PurePosixPath(scope).parts:
        raise TDDLValidationError(f"line {instr.line}: SCAN scope must be relative and cannot escape .tds")
    if not (scope == ".tds" or scope.startswith(".tds/")):
        raise TDDLValidationError(f"line {instr.line}: SCAN scope must begin with .tds")
    if "limit" in instr.operands:
        limit = _int_limit(instr.operands["limit"], "SCAN.limit", minimum=1, maximum=max_scan)
        if limit > max_scan:
            raise TDDLValidationError(f"line {instr.line}: SCAN.limit exceeds limits.max_scan")
    if "depth" in instr.operands:
        depth = _int_limit(instr.operands["depth"], "SCAN.depth", minimum=0, maximum=max_depth)
        if depth > max_depth:
            raise TDDLValidationError(f"line {instr.line}: SCAN.depth exceeds limits.max_depth")
    if "recursive" in instr.operands and not isinstance(instr.operands["recursive"], bool):
        raise TDDLValidationError(f"line {instr.line}: SCAN.recursive must be boolean")


def _validate_match(program: TDDLProgram, instr: TDDLInstruction) -> None:
    if "regex_limited" in instr.operands:
        pattern = str(instr.operands["regex_limited"])
        if len(pattern) > 128 or ".*.*" in pattern or "(?" in pattern:
            raise TDDLValidationError(f"line {instr.line}: MATCH.regex_limited is too broad")
    has_using = "using" in instr.operands
    has_field = "field" in instr.operands
    if not has_using and not has_field:
        raise TDDLValidationError(f"line {instr.line}: MATCH requires field or using")
    if has_using:
        _validate_adapter_use(program, instr)
        if "threshold" in instr.operands:
            _validate_threshold(instr.operands["threshold"], instr.line)
    if has_field:
        field = str(instr.operands["field"])
        if not _FIELD_RE.fullmatch(field):
            raise TDDLValidationError(f"line {instr.line}: MATCH.field must be a dotted token")
        predicate_keys = {"eq", "neq", "contains", "prefix", "suffix", "in", "exists", "regex_limited", "range"}
        if not predicate_keys.intersection(instr.operands):
            raise TDDLValidationError(f"line {instr.line}: MATCH.field requires at least one predicate operand")


def _validate_extract(program: TDDLProgram, instr: TDDLInstruction) -> None:
    if "fields" not in instr.operands and "using" not in instr.operands:
        raise TDDLValidationError(f"line {instr.line}: EXTRACT requires fields or using")
    if "using" in instr.operands:
        _validate_adapter_use(program, instr)
    if instr.operands.get("from") == "raw_pickle":
        raise TDDLValidationError(f"line {instr.line}: EXTRACT from raw_pickle is denied")
    if "fields" in instr.operands:
        fields = instr.operands["fields"]
        if not isinstance(fields, list) or not fields:
            raise TDDLValidationError(f"line {instr.line}: EXTRACT.fields must be a non-empty list")
        for field in fields:
            if not isinstance(field, str) or not _FIELD_RE.fullmatch(field):
                raise TDDLValidationError(f"line {instr.line}: EXTRACT.fields must be dotted tokens")
    if "limit" in instr.operands:
        _int_limit(instr.operands["limit"], "EXTRACT.limit", minimum=1, maximum=100_000)


def _validate_adapter_use(program: TDDLProgram, instr: TDDLInstruction) -> None:
    adapter = str(instr.operands.get("using", ""))
    if not adapter:
        raise TDDLValidationError(f"line {instr.line}: {instr.name.value} requires using adapter")
    if adapter not in program.adapters:
        raise TDDLValidationError(f"line {instr.line}: adapter must be declared in requires")
    _reject_unsafe_adapter(adapter)


def _validate_threshold(value: Any, line: int) -> None:
    if not isinstance(value, (int, float)) or value < 0.0 or value > 1.0:
        raise TDDLValidationError(f"line {line}: threshold must be between 0.0 and 1.0")


def _int_limit(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        raise TDDLValidationError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise TDDLValidationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _validate_token(value: str, label: str) -> None:
    if not _TOKEN_RE.fullmatch(value):
        raise TDDLValidationError(f"{label} must be a token")


def _validate_dotted_token(value: str, label: str) -> None:
    if not _FIELD_RE.fullmatch(value) or "." not in value:
        raise TDDLValidationError(f"{label} must be a dotted token")


def _reject_unsafe_adapter(adapter: str) -> None:
    lowered = adapter.lower()
    if any(part in lowered for part in ("python.eval", "eval", "exec", "socket", "subprocess", "import")):
        raise TDDLValidationError("unsafe adapter is denied")

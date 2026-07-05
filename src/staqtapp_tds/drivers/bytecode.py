"""Deterministic non-executing TDDL IR and bytecode package model.

v3.0.8 compiles already-validated TDDL programs into a stable intermediate
representation and portable bytecode artifact for the future native Driver VM.
This module does not execute bytecode.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping

from .tddl import InstructionName, TDDLInstruction, TDDLProgram, TDDLValidationError, parse_tddl, validate_tddl

BYTECODE_MAGIC = "TDD1"
BYTECODE_VERSION = 1
GRAMMAR_VERSION = "tddl-1"
BUILDER_VERSION = "tds-builder-0.1"


class BytecodeOpcode(IntEnum):
    """Stable opcode mapping for the first non-executing driver bytecode set."""

    SCAN = 0x01
    READ = 0x02
    MATCH = 0x03
    EXTRACT = 0x04
    SCORE = 0x05
    EMIT = 0x06
    TRACE = 0x07
    HALT = 0x08


_SUPPORTED_OPCODE_NAMES = frozenset(item.name for item in BytecodeOpcode)


@dataclass(frozen=True, slots=True)
class BytecodeInstruction:
    """Portable bytecode instruction.

    ``operand_ref`` indexes into the package constant pool. The operand mapping
    is stored once in the constant pool so the future native VM can load compact
    opcodes while the Python builder can still round-trip to readable IR.
    """

    opcode: int
    name: str
    operand_ref: int
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"opcode": self.opcode, "name": self.name, "operand_ref": self.operand_ref, "line": self.line}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BytecodeInstruction":
        return cls(opcode=int(data["opcode"]), name=str(data["name"]), operand_ref=int(data["operand_ref"]), line=int(data.get("line", 0)))


@dataclass(frozen=True, slots=True)
class BytecodePackage:
    """Non-executing compiled driver artifact for registry/builder validation."""

    header: Mapping[str, Any]
    manifest: Mapping[str, Any]
    capabilities: tuple[str, ...]
    adapters: tuple[str, ...]
    limits: Mapping[str, Any]
    instructions: tuple[BytecodeInstruction, ...]
    constants: tuple[Any, ...]
    evolution: tuple[str, ...]
    source_hash: str
    package_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "header": dict(self.header),
            "manifest": dict(self.manifest),
            "capabilities": list(self.capabilities),
            "adapters": list(self.adapters),
            "limits": dict(self.limits),
            "instructions": [instr.to_dict() for instr in self.instructions],
            "constants": list(self.constants),
            "evolution": list(self.evolution),
            "source_hash": self.source_hash,
            "package_hash": self.package_hash,
        }

    def to_bytes(self) -> bytes:
        """Return canonical package bytes including the package hash."""

        return _canonical_json(self.to_dict()).encode("utf-8")

    def to_unsigned_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("package_hash", None)
        return data

    def verify_hash(self) -> bool:
        return _hash_dict(self.to_unsigned_dict()) == self.package_hash

    @classmethod
    def from_bytes(cls, payload: bytes) -> "BytecodePackage":
        data = json.loads(payload.decode("utf-8"))
        instructions = tuple(BytecodeInstruction.from_dict(item) for item in data["instructions"])
        pkg = cls(
            header=dict(data["header"]),
            manifest=dict(data["manifest"]),
            capabilities=tuple(data["capabilities"]),
            adapters=tuple(data["adapters"]),
            limits=dict(data["limits"]),
            instructions=instructions,
            constants=tuple(data["constants"]),
            evolution=tuple(data.get("evolution", ())),
            source_hash=str(data["source_hash"]),
            package_hash=str(data["package_hash"]),
        )
        validate_bytecode_package(pkg)
        return pkg


def compile_tddl(source_or_program: str | TDDLProgram) -> BytecodePackage:
    """Compile TDDL source/program into deterministic non-executing bytecode."""

    if isinstance(source_or_program, str):
        source = source_or_program
        program = parse_tddl(source_or_program)
    else:
        program = source_or_program
        validate_tddl(program)
        source = _program_canonical_dict(program)
    return compile_program(program, source_material=source)


def compile_program(program: TDDLProgram, *, source_material: str | Mapping[str, Any] | None = None) -> BytecodePackage:
    """Compile an already-validated TDDL program to a bytecode package."""

    validate_tddl(program)
    constants: list[Any] = []
    constant_refs: dict[str, int] = {}
    byte_instructions: list[BytecodeInstruction] = []

    for instr in program.instructions:
        if instr.name.value not in _SUPPORTED_OPCODE_NAMES:
            raise TDDLValidationError(f"{instr.name.value} is not supported by bytecode v{BYTECODE_VERSION}")
        operand_ref = _intern_constant(_normalize_value(instr.operands), constants, constant_refs)
        opcode = int(BytecodeOpcode[instr.name.value])
        byte_instructions.append(BytecodeInstruction(opcode=opcode, name=instr.name.value, operand_ref=operand_ref, line=instr.line))

    header = {
        "magic": BYTECODE_MAGIC,
        "bytecode_version": BYTECODE_VERSION,
        "grammar_version": GRAMMAR_VERSION,
        "builder_version": BUILDER_VERSION,
        "driver_id": program.driver_id,
        "driver_version": program.version,
    }
    source_hash = _hash_value(source_material if source_material is not None else _program_canonical_dict(program))
    unsigned = {
        "header": header,
        "manifest": _normalize_mapping(program.manifest),
        "capabilities": list(program.capabilities),
        "adapters": list(program.adapters),
        "limits": _normalize_mapping(program.limits),
        "instructions": [instr.to_dict() for instr in byte_instructions],
        "constants": constants,
        "evolution": list(program.evolution),
        "source_hash": source_hash,
    }
    package_hash = _hash_dict(unsigned)
    package = BytecodePackage(
        header=header,
        manifest=unsigned["manifest"],
        capabilities=tuple(program.capabilities),
        adapters=tuple(program.adapters),
        limits=unsigned["limits"],
        instructions=tuple(byte_instructions),
        constants=tuple(constants),
        evolution=tuple(program.evolution),
        source_hash=source_hash,
        package_hash=package_hash,
    )
    validate_bytecode_package(package)
    return package


def validate_bytecode_package(package: BytecodePackage) -> None:
    """Validate bytecode artifact integrity without executing it."""

    if package.header.get("magic") != BYTECODE_MAGIC:
        raise TDDLValidationError("bytecode magic mismatch")
    if package.header.get("bytecode_version") != BYTECODE_VERSION:
        raise TDDLValidationError("unsupported bytecode version")
    if not package.instructions:
        raise TDDLValidationError("bytecode instruction block is empty")
    if package.instructions[-1].name != "HALT":
        raise TDDLValidationError("bytecode must end with HALT")
    seen_halt = 0
    for instr in package.instructions:
        if instr.name not in _SUPPORTED_OPCODE_NAMES:
            raise TDDLValidationError(f"unsupported bytecode instruction {instr.name}")
        if int(BytecodeOpcode[instr.name]) != instr.opcode:
            raise TDDLValidationError(f"opcode mismatch for {instr.name}")
        if instr.operand_ref < 0 or instr.operand_ref >= len(package.constants):
            raise TDDLValidationError("operand_ref out of range")
        if instr.name == "HALT":
            seen_halt += 1
    if seen_halt != 1:
        raise TDDLValidationError("bytecode must contain exactly one HALT")
    if not package.verify_hash():
        raise TDDLValidationError("bytecode package hash mismatch")


def decompile_to_ir(package: BytecodePackage) -> TDDLProgram:
    """Round-trip bytecode package back to readable non-executing TDDL IR."""

    validate_bytecode_package(package)
    instructions = tuple(
        TDDLInstruction(
            name=InstructionName(instr.name),
            operands=_constant_as_mapping(package.constants[instr.operand_ref]),
            line=instr.line,
        )
        for instr in package.instructions
    )
    program = TDDLProgram(
        driver_id=str(package.header["driver_id"]),
        version=int(package.header["driver_version"]),
        manifest=dict(package.manifest),
        capabilities=tuple(package.capabilities),
        adapters=tuple(package.adapters),
        limits=dict(package.limits),
        instructions=instructions,
        evolution=tuple(package.evolution),
    )
    validate_tddl(program)
    return program


def opcode_table() -> Mapping[str, Mapping[str, Any]]:
    """Return stable opcode metadata for future native VM and Studio display."""

    return {
        op.name: {"opcode": int(op), "hex": f"0x{int(op):02X}", "bytecode_version": BYTECODE_VERSION}
        for op in BytecodeOpcode
    }


def _intern_constant(value: Any, constants: list[Any], refs: dict[str, int]) -> int:
    key = _canonical_json(value)
    if key not in refs:
        refs[key] = len(constants)
        constants.append(value)
    return refs[key]


def _constant_as_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TDDLValidationError("instruction operands constant is not a mapping")
    return dict(value)


def _program_canonical_dict(program: TDDLProgram) -> dict[str, Any]:
    return {
        "driver_id": program.driver_id,
        "version": program.version,
        "manifest": _normalize_mapping(program.manifest),
        "capabilities": list(program.capabilities),
        "adapters": list(program.adapters),
        "limits": _normalize_mapping(program.limits),
        "instructions": [
            {"name": instr.name.value, "operands": _normalize_mapping(instr.operands), "line": instr.line}
            for instr in program.instructions
        ],
        "evolution": list(program.evolution),
    }


def _normalize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k): _normalize_value(value[k]) for k in sorted(value)}


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _hash_value(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _hash_dict(value: Mapping[str, Any]) -> str:
    return _hash_value(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(_normalize_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

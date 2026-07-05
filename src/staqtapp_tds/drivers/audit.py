"""VM contract audit for TDDL bytecode packages.

v3.0.8 keeps the future Driver VM fail-closed by auditing every compiled
instruction against a self-describing execution contract before a VM loader can
accept a package. The audit is non-executing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .bytecode import BytecodeOpcode, BytecodePackage, validate_bytecode_package
from .tddl import TDDLValidationError, instruction_specs


DRIVER_CLASSES = frozenset({"search", "extract", "rank", "adapter", "policy"})


@dataclass(frozen=True, slots=True)
class VMInstructionContract:
    name: str
    opcode: int
    cost: int
    deterministic: bool
    allowed_driver_classes: frozenset[str]
    required_capability: str | None = None
    may_branch: bool = False
    may_call_adapter: bool = False
    may_propose_evolution: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "opcode": self.opcode,
            "hex": f"0x{self.opcode:02X}",
            "cost": self.cost,
            "deterministic": self.deterministic,
            "allowed_driver_classes": sorted(self.allowed_driver_classes),
            "required_capability": self.required_capability,
            "may_branch": self.may_branch,
            "may_call_adapter": self.may_call_adapter,
            "may_propose_evolution": self.may_propose_evolution,
        }


_VM_CONTRACTS: dict[str, VMInstructionContract] = {
    "SCAN": VMInstructionContract("SCAN", int(BytecodeOpcode.SCAN), 4, True, frozenset({"search", "rank"}), "registry.scan"),
    "READ": VMInstructionContract("READ", int(BytecodeOpcode.READ), 2, True, frozenset({"search", "extract", "rank", "adapter", "policy"}), "manifest.read"),
    "MATCH": VMInstructionContract("MATCH", int(BytecodeOpcode.MATCH), 3, True, frozenset({"search", "extract", "rank", "policy"}), None, may_call_adapter=True),
    "EXTRACT": VMInstructionContract("EXTRACT", int(BytecodeOpcode.EXTRACT), 3, True, frozenset({"search", "extract", "rank"}), None, may_call_adapter=True),
    "SCORE": VMInstructionContract("SCORE", int(BytecodeOpcode.SCORE), 3, True, frozenset({"search", "rank"}), None, may_call_adapter=True),
    "EMIT": VMInstructionContract("EMIT", int(BytecodeOpcode.EMIT), 1, True, frozenset({"search", "extract", "rank", "adapter", "policy"}), None),
    "TRACE": VMInstructionContract("TRACE", int(BytecodeOpcode.TRACE), 1, True, frozenset({"search", "extract", "rank", "adapter", "policy"}), "trace.write"),
    "HALT": VMInstructionContract("HALT", int(BytecodeOpcode.HALT), 1, True, frozenset({"search", "extract", "rank", "adapter", "policy"}), None),
}


def vm_contract_table() -> Mapping[str, Mapping[str, Any]]:
    """Return VM-readiness metadata used by tests, Builder and future Studio."""

    return {name: contract.to_dict() for name, contract in _VM_CONTRACTS.items()}


def audit_vm_contract(package: BytecodePackage) -> None:
    """Fail-closed audit before a bytecode package may be loaded by the VM skeleton."""

    validate_bytecode_package(package)
    grammar_specs = instruction_specs()
    driver_class = str(package.manifest.get("kind", ""))
    if driver_class not in DRIVER_CLASSES:
        raise TDDLValidationError("driver manifest kind is not a supported VM class")

    for instr in package.instructions:
        contract = _VM_CONTRACTS.get(instr.name)
        if contract is None:
            raise TDDLValidationError(f"missing VM contract for {instr.name}")
        if instr.name not in grammar_specs:
            raise TDDLValidationError(f"missing grammar spec for {instr.name}")
        if instr.opcode != contract.opcode:
            raise TDDLValidationError(f"VM contract opcode mismatch for {instr.name}")
        if driver_class not in contract.allowed_driver_classes:
            raise TDDLValidationError(f"{instr.name} is not allowed for {driver_class} drivers")
        if contract.required_capability and contract.required_capability not in package.capabilities:
            raise TDDLValidationError(f"{instr.name} requires capability {contract.required_capability}")
        if contract.cost < 1:
            raise TDDLValidationError(f"{instr.name} has invalid VM cost")
        if not contract.deterministic:
            raise TDDLValidationError(f"{instr.name} must be deterministic in VM skeleton")

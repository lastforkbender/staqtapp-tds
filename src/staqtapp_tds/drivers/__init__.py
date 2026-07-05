"""TDS Driver Foundation namespace.

v3.1.2 extends the driver foundation for the future native
Driver VM, Builder, Registry and Studio. These helpers deliberately do not
execute driver programs; they model trust states, manifests, signatures and
trace ranking plus strict non-executing TDDL parsing/validation plus deterministic bytecode packaging, VM contract audits, a non-executing VM skeleton, and the first deterministic runtime execution path plus a non-halting DriverVMResult envelope and AI-safe DriverFoundry API for validated bytecode packages.
"""

from .manifest import DriverManifest, DriverSafety, validate_manifest
from .registry import DriverRegistry, DriverRecord, DriverState, RegistryError
from .signature import SignaturePolicy, SignatureVerdict, sign_payload, verify_signature
from .trace import TraceEvidence, rank_traces
from .audit import VMInstructionContract, audit_vm_contract, vm_contract_table
from .vm import DriverVMContext, DriverVMResult, DriverVMRuntime, DriverVMSkeleton, VMExecutionResult, VMFault, VMLoadedPackage, VMState, VMStatus

from .foundry import (
    DriverFoundry,
    DriverFoundryContext,
    DriverFoundryPolicy,
    DriverFoundryResult,
    FoundryFault,
    FoundryStage,
    FoundryStatus,
    foundry_capability_matrix,
)
from .studio import (
    DriverStudioQuickTestReport,
    DriverStudioSession,
    StudioGate,
    StudioGateResult,
    run_studio_quick_test,
    studio_instruction_reference,
)
from .bytecode import (
    BYTECODE_MAGIC,
    BYTECODE_VERSION,
    BytecodeInstruction,
    BytecodeOpcode,
    BytecodePackage,
    compile_program,
    compile_tddl,
    decompile_to_ir,
    opcode_table,
    validate_bytecode_package,
)
from .tddl import (
    InstructionName,
    TDDLInstruction,
    TDDLProgram,
    TDDLValidationError,
    instruction_specs,
    parse_tddl,
    validate_tddl,
)

__all__ = [
    "DriverManifest",
    "DriverSafety",
    "validate_manifest",
    "DriverRegistry",
    "DriverRecord",
    "DriverState",
    "RegistryError",
    "SignaturePolicy",
    "SignatureVerdict",
    "sign_payload",
    "verify_signature",
    "TraceEvidence",
    "rank_traces",
    "VMInstructionContract",
    "audit_vm_contract",
    "vm_contract_table",
    "DriverVMContext",
    "DriverVMResult",
    "DriverVMRuntime",
    "DriverVMSkeleton",
    "VMExecutionResult",
    "VMFault",
    "VMLoadedPackage",
    "VMState",
    "VMStatus",
    "InstructionName",
    "TDDLInstruction",
    "TDDLProgram",
    "TDDLValidationError",
    "instruction_specs",
    "parse_tddl",
    "validate_tddl",
    "BYTECODE_MAGIC",
    "BYTECODE_VERSION",
    "BytecodeInstruction",
    "BytecodeOpcode",
    "BytecodePackage",
    "compile_program",
    "compile_tddl",
    "decompile_to_ir",
    "opcode_table",
    "validate_bytecode_package",
    "DriverStudioQuickTestReport",
    "DriverStudioSession",
    "StudioGate",
    "StudioGateResult",
    "run_studio_quick_test",
    "studio_instruction_reference",
    "DriverFoundry",
    "DriverFoundryContext",
    "DriverFoundryPolicy",
    "DriverFoundryResult",
    "FoundryFault",
    "FoundryStage",
    "FoundryStatus",
    "foundry_capability_matrix",
]

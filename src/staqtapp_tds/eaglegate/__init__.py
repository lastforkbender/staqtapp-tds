"""Eaglegate lossless speculative-decoding control-plane contracts."""
from .admission import (
    EaglegateDecision,
    EaglegateRequestClass,
    EaglegateRuntimeHealth,
    evaluate_admission,
)
from .config import (
    EAGLEGATE_CONFIG_FILENAME,
    EAGLEGATE_LOCK_FILENAME,
    EaglegateConfiguration,
    EaglegateLock,
    compile_project,
    epoch_diff,
    initialize_project,
    load_configuration,
    load_lock,
    load_project,
    profile_configuration,
    resolve_lock_from_snapshot,
)
from .contract import (
    EAGLEGATE_ACCEPTANCE_CONTRACT_ID,
    EAGLEGATE_AUTHORITY,
    EAGLEGATE_CAPABILITY_SNAPSHOT_ID,
    EAGLEGATE_CONTRACT_ID,
    EAGLEGATE_FORMAT_VERSION,
    EAGLEGATE_PROPOSER_FAMILY,
    EAGLEGATE_SELECTION_CONTRACT_ID,
    EaglegateAuthorityBoundary,
    EaglegateContractError,
    EaglegateDecisionKind,
    EaglegateEpochState,
    EaglegateFault,
    EaglegateIdentity,
    EaglegateMode,
    EaglegateSamplerClass,
    authority_snapshot,
)
from .evidence import (
    EaglegateEpisodeReceipt,
    EaglegateEpochReceipt,
    validate_epoch_transition,
)
from .plans import (
    EaglegateAdmissionPolicy,
    EaglegatePlan,
    EaglegateQualificationSummary,
    EaglegateSpeculationEpoch,
    validate_qualification_for_epoch,
)

__all__ = [name for name in globals() if name.startswith("Eaglegate")]
__all__ += [
    "EAGLEGATE_ACCEPTANCE_CONTRACT_ID",
    "EAGLEGATE_AUTHORITY",
    "EAGLEGATE_CAPABILITY_SNAPSHOT_ID",
    "EAGLEGATE_CONFIG_FILENAME",
    "EAGLEGATE_CONTRACT_ID",
    "EAGLEGATE_FORMAT_VERSION",
    "EAGLEGATE_LOCK_FILENAME",
    "EAGLEGATE_PROPOSER_FAMILY",
    "EAGLEGATE_SELECTION_CONTRACT_ID",
    "authority_snapshot",
    "compile_project",
    "epoch_diff",
    "evaluate_admission",
    "initialize_project",
    "load_configuration",
    "load_lock",
    "load_project",
    "profile_configuration",
    "resolve_lock_from_snapshot",
    "validate_epoch_transition",
    "validate_qualification_for_epoch",
]

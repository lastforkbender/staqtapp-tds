"""Public persistence safety contract for recoverable TDS generations.

This module intentionally contains no disk mutation logic.  It freezes the
programmer-facing durability, retention, cleanup, and recovery-observability
contract before the v3 generation format is implemented.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class Durability(str, Enum):
    """When a successful commit may be acknowledged."""

    DURABLE = "durable"
    GROUP_DURABLE = "group_durable"
    RELAXED = "relaxed"


class CleanupMode(str, Enum):
    """When obsolete, unpinned generations may be reclaimed."""

    BACKGROUND = "background"
    IMMEDIATE = "immediate"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class PersistencePolicy:
    """Immutable data-survival policy.

    Atomic generation construction is an invariant, not an option.  Retention
    controls rollback depth after a completed promotion; it never permits an
    in-place persistent commit.
    """

    durability: Durability = Durability.DURABLE
    retained_generations: int = 2
    cleanup: CleanupMode = CleanupMode.BACKGROUND
    protect_last_known_good: bool = True
    max_storage_bytes: int | None = None
    group_commit_window_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "durability", Durability(self.durability))
        object.__setattr__(self, "cleanup", CleanupMode(self.cleanup))
        if isinstance(self.retained_generations, bool) or self.retained_generations < 1:
            raise ValueError("retained_generations must be an integer >= 1")
        if self.max_storage_bytes is not None:
            if isinstance(self.max_storage_bytes, bool) or self.max_storage_bytes <= 0:
                raise ValueError("max_storage_bytes must be a positive integer or None")
        if self.group_commit_window_ms is not None:
            if isinstance(self.group_commit_window_ms, bool) or self.group_commit_window_ms <= 0:
                raise ValueError("group_commit_window_ms must be a positive integer or None")
        if self.durability is Durability.GROUP_DURABLE and self.group_commit_window_ms is None:
            raise ValueError("group_durable requires group_commit_window_ms")
        if self.durability is not Durability.GROUP_DURABLE and self.group_commit_window_ms is not None:
            raise ValueError("group_commit_window_ms is valid only for group_durable")
        if not self.protect_last_known_good and self.retained_generations > 1:
            raise ValueError(
                "protect_last_known_good=False is incompatible with retained_generations > 1"
            )

    @classmethod
    def production_safe(cls, *, retained_generations: int = 2,
                        cleanup: CleanupMode = CleanupMode.BACKGROUND,
                        max_storage_bytes: int | None = None) -> "PersistencePolicy":
        return cls(
            durability=Durability.DURABLE,
            retained_generations=retained_generations,
            cleanup=cleanup,
            protect_last_known_good=True,
            max_storage_bytes=max_storage_bytes,
        )

    @classmethod
    def relaxed_cache(cls, *, retained_generations: int = 1,
                      cleanup: CleanupMode = CleanupMode.BACKGROUND,
                      max_storage_bytes: int | None = None) -> "PersistencePolicy":
        return cls(
            durability=Durability.RELAXED,
            retained_generations=retained_generations,
            cleanup=cleanup,
            protect_last_known_good=True,
            max_storage_bytes=max_storage_bytes,
        )

    @property
    def atomic_generations(self) -> bool:
        """Always true for persistent TDS stores."""
        return True

    @property
    def reduced_recovery_depth(self) -> bool:
        return self.retained_generations == 1

    @property
    def acknowledged_loss_window_ms(self) -> int | None:
        if self.durability is Durability.DURABLE:
            return 0
        if self.durability is Durability.GROUP_DURABLE:
            return self.group_commit_window_ms
        return None

    def risk_summary(self) -> tuple[str, ...]:
        risks: list[str] = []
        if self.durability is Durability.RELAXED:
            risks.append(
                "Recently acknowledged writes may be lost after abrupt process, OS, or power failure."
            )
        elif self.durability is Durability.GROUP_DURABLE:
            risks.append(
                f"Acknowledged writes may remain non-durable for up to approximately "
                f"{self.group_commit_window_ms} ms."
            )
        if self.retained_generations == 1:
            risks.append(
                "Automatic cleanup leaves no historical rollback generation after promotion."
            )
        if self.cleanup is CleanupMode.IMMEDIATE:
            risks.append(
                "Immediate cleanup reduces the time available to diagnose or manually recover older states."
            )
        risks.append(
            "Internal generations are local crash-recovery states, not off-device backups."
        )
        return tuple(risks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "durability": self.durability.value,
            "retained_generations": self.retained_generations,
            "cleanup": self.cleanup.value,
            "protect_last_known_good": self.protect_last_known_good,
            "max_storage_bytes": self.max_storage_bytes,
            "group_commit_window_ms": self.group_commit_window_ms,
            "atomic_generations": True,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PersistencePolicy":
        allowed = {
            "durability", "retained_generations", "cleanup",
            "protect_last_known_good", "max_storage_bytes",
            "group_commit_window_ms",
        }
        unknown = set(value) - allowed - {"atomic_generations"}
        if unknown:
            raise ValueError(f"Unknown persistence policy fields: {sorted(unknown)!r}")
        if value.get("atomic_generations", True) is not True:
            raise ValueError("atomic_generations cannot be disabled for persistent TDS stores")
        return cls(**{key: value[key] for key in allowed if key in value})


@dataclass(frozen=True, slots=True)
class PersistenceStatus:
    """Runtime statement of the protection actually active for a mounted store."""

    durability: Durability
    retained_generations: int
    atomic_generations: bool
    external_backup_configured: bool
    current_generation: str | None
    last_verified_generation: str | None
    recovery_fallback_active: bool = False
    requested_generation: str | None = None
    mounted_generation: str | None = None
    recovery_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "durability", Durability(self.durability))
        if not self.atomic_generations:
            raise ValueError("A persistent TDS status cannot report atomic_generations=False")
        if self.retained_generations < 1:
            raise ValueError("retained_generations must be >= 1")
        if self.recovery_fallback_active:
            if not self.requested_generation or not self.mounted_generation or not self.recovery_reason:
                raise ValueError("Active recovery fallback requires requested, mounted, and reason fields")
            if self.requested_generation == self.mounted_generation:
                raise ValueError("Recovery fallback must mount a generation different from the requested one")

    @classmethod
    def unmounted(cls, policy: PersistencePolicy,
                  *, external_backup_configured: bool = False) -> "PersistenceStatus":
        return cls(
            durability=policy.durability,
            retained_generations=policy.retained_generations,
            atomic_generations=True,
            external_backup_configured=external_backup_configured,
            current_generation=None,
            last_verified_generation=None,
        )

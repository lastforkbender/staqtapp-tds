"""Restricted pickle boundary for Staqtapp-TDS.

Pickle is a Python compatibility codec, not a trust boundary.  This module keeps
all pickle serialization/deserialization policy in one place so storage code never
calls ``pickle.loads`` directly.
"""

from __future__ import annotations

import builtins
import io
import os
import pickle
from dataclasses import dataclass
from typing import Any, BinaryIO, ClassVar


ENVELOPE_MAGIC = b"TDSPKL\x01"
DEFAULT_PROTOCOL = 5
UNSAFE_ENV_VAR = "TDS_ALLOW_UNSAFE_PICKLE"


class PicklePolicyError(ValueError):
    """Raised when a pickle payload violates the TDS pickle policy."""


@dataclass(frozen=True)
class PicklePolicy:
    """Policy for the Python-object compatibility lane.

    ``restricted`` is the production default. It permits ordinary Python value
    containers and a small set of stable stdlib value classes, while rejecting
    arbitrary globals that could execute code during unpickle.
    """

    mode: str = "restricted"
    require_envelope: bool = False
    max_payload_bytes: int = 64 * 1024 * 1024
    validate_on_dump: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"restricted", "unsafe_legacy"}:
            raise ValueError("PicklePolicy.mode must be restricted or unsafe_legacy")
        if int(self.max_payload_bytes) <= 0:
            raise ValueError("PicklePolicy.max_payload_bytes must be positive")

    @classmethod
    def from_env(cls) -> "PicklePolicy":
        unsafe = os.getenv(UNSAFE_ENV_VAR, "").strip().lower() in {"1", "true", "yes", "on"}
        return cls(mode="unsafe_legacy" if unsafe else "restricted")

    @property
    def unsafe(self) -> bool:
        return self.mode == "unsafe_legacy"


_ALLOWED_GLOBALS: frozenset[tuple[str, str]] = frozenset({
    ("builtins", "bytes"),
    ("builtins", "bytearray"),
    ("builtins", "complex"),
    ("builtins", "frozenset"),
    ("builtins", "set"),
    ("builtins", "slice"),
    ("collections", "Counter"),
    ("collections", "OrderedDict"),
    ("collections", "defaultdict"),
    ("datetime", "date"),
    ("datetime", "datetime"),
    ("datetime", "time"),
    ("datetime", "timedelta"),
    ("decimal", "Decimal"),
    ("uuid", "UUID"),
})


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only resolves explicitly approved value classes."""

    allowed_globals: ClassVar[frozenset[tuple[str, str]]] = _ALLOWED_GLOBALS

    def find_class(self, module: str, name: str) -> Any:  # pragma: no cover - exercised through loads_pickle
        if (module, name) in self.allowed_globals:
            __import__(module)
            mod = __import__(module, fromlist=[name])
            return getattr(mod, name)
        raise PicklePolicyError(f"pickle global is not allowed: {module}.{name}")


def _strip_envelope(raw: bytes, *, require_envelope: bool) -> tuple[bytes, bool]:
    if raw.startswith(ENVELOPE_MAGIC):
        return raw[len(ENVELOPE_MAGIC):], True
    if require_envelope:
        raise PicklePolicyError("pickle payload is missing the TDS pickle envelope")
    return raw, False


def loads_pickle(raw: bytes, policy: PicklePolicy | None = None) -> Any:
    """Deserialize a pickle payload under the configured TDS policy."""

    policy = policy or PicklePolicy.from_env()
    if len(raw) > int(policy.max_payload_bytes):
        raise PicklePolicyError("pickle payload exceeds max_payload_bytes")
    payload, _enveloped = _strip_envelope(bytes(raw), require_envelope=policy.require_envelope)
    if policy.unsafe:
        return pickle.loads(payload)
    return RestrictedUnpickler(io.BytesIO(payload)).load()


def dumps_pickle(value: Any, policy: PicklePolicy | None = None) -> bytes:
    """Serialize a Python object with a TDS envelope and optional safety validation."""

    policy = policy or PicklePolicy.from_env()
    try:
        payload = pickle.dumps(value, protocol=DEFAULT_PROTOCOL)
    except Exception as exc:  # normalize pickle-specific exceptions at boundary
        raise PicklePolicyError(f"pickle dump failed: {type(exc).__name__}: {exc}") from exc
    if len(payload) > int(policy.max_payload_bytes):
        raise PicklePolicyError("pickle payload exceeds max_payload_bytes")
    raw = ENVELOPE_MAGIC + payload
    if policy.validate_on_dump and not policy.unsafe:
        # Fail at write time for values the restricted reader would refuse later.
        loads_pickle(raw, policy=policy)
    return raw


def pickle_policy_snapshot(policy: PicklePolicy | None = None) -> dict[str, Any]:
    policy = policy or PicklePolicy.from_env()
    return {
        "mode": policy.mode,
        "require_envelope": bool(policy.require_envelope),
        "max_payload_bytes": int(policy.max_payload_bytes),
        "validate_on_dump": bool(policy.validate_on_dump),
        "envelope_magic": ENVELOPE_MAGIC.hex(),
        "unsafe_env_var": UNSAFE_ENV_VAR,
    }

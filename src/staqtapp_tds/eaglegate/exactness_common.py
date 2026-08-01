"""Shared deterministic identities and validators for the Eaglegate laboratory."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

EAGLEGATE_EXACTNESS_CONTRACT_ID = "tds-eaglegate-exactness-v1"
EAGLEGATE_EXACTNESS_SUITE_ID = "eaglegate-reference-exactness-v1"
_ROOT_PREFIX = b"STAQTAPP-TDS\x00EAGLEGATE-EXACTNESS\x00V1\x00"
_TOKEN_PREFIX = b"STAQTAPP-TDS\x00EAGLEGATE-TOKENS\x00V1\x00"
_ROOT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_TOKENS = 1 << 20
MAX_EVENTS = 1 << 16
UINT32_MAX = (1 << 32) - 1
UINT63_MAX = (1 << 63) - 1


class EaglegateExactnessError(ValueError):
    """Stable qualification-oracle input or invariant failure."""


def require_int(
    name: str,
    value: int,
    minimum: int = 0,
    maximum: int = UINT63_MAX,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EaglegateExactnessError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise EaglegateExactnessError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def require_ascii(
    name: str,
    value: str,
    *,
    allow_empty: bool = False,
    allow_spaces: bool = False,
    limit: int = 256,
) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise EaglegateExactnessError(f"{name} must be a string")
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise EaglegateExactnessError(f"{name} must be ASCII") from exc
    lower = 0x20 if allow_spaces else 0x21
    if len(raw) > limit or any(byte < lower or byte > 0x7E for byte in raw):
        raise EaglegateExactnessError(f"{name} must be printable ASCII")
    return value


def require_root(name: str, value: str) -> str:
    if not isinstance(value, str) or not _ROOT_RE.fullmatch(value):
        raise EaglegateExactnessError(
            f"{name} must be lowercase sha256:<64-hex>"
        )
    return value


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise EaglegateExactnessError("value is not canonical JSON") from exc


def canonical_root(domain: str, value: Mapping[str, Any]) -> str:
    require_ascii("domain", domain)
    material = _ROOT_PREFIX + domain.encode("ascii") + b"\x00" + canonical_bytes(value)
    return "sha256:" + hashlib.sha256(material).hexdigest()


def normalize_tokens(tokens: Iterable[int]) -> tuple[int, ...]:
    try:
        normalized = tuple(tokens)
    except TypeError as exc:
        raise EaglegateExactnessError("tokens must be iterable") from exc
    if len(normalized) > MAX_TOKENS:
        raise EaglegateExactnessError("token count exceeds the laboratory bound")
    for index, token in enumerate(normalized):
        require_int(f"tokens[{index}]", token, 0, UINT32_MAX)
    return normalized


def token_sequence_root(tokens: Iterable[int]) -> str:
    normalized = normalize_tokens(tokens)
    digest = hashlib.sha256()
    digest.update(_TOKEN_PREFIX)
    digest.update(len(normalized).to_bytes(8, "little", signed=False))
    for token in normalized:
        digest.update(token.to_bytes(4, "little", signed=False))
    return "sha256:" + digest.hexdigest()


def committed_state_root(tokens: Iterable[int]) -> str:
    normalized = normalize_tokens(tokens)
    return canonical_root(
        "committed-state",
        {
            "contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            "token_count": len(normalized),
            "token_sequence_root": token_sequence_root(normalized),
        },
    )


def reference_epoch_root(suite_id: str = EAGLEGATE_EXACTNESS_SUITE_ID) -> str:
    require_ascii("suite_id", suite_id)
    return canonical_root(
        "epoch",
        {
            "contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            "suite_id": suite_id,
        },
    )


__all__ = [
    "EAGLEGATE_EXACTNESS_CONTRACT_ID",
    "EAGLEGATE_EXACTNESS_SUITE_ID",
    "EaglegateExactnessError",
    "MAX_EVENTS",
    "MAX_TOKENS",
    "UINT32_MAX",
    "canonical_bytes",
    "canonical_root",
    "committed_state_root",
    "normalize_tokens",
    "reference_epoch_root",
    "require_ascii",
    "require_int",
    "require_root",
    "token_sequence_root",
]

"""Deterministic mock signature policy for the future Driver Registry.

This is not a cryptographic subsystem. It is a testable trust-policy seam that
models the rules the native registry/signing layer must preserve:
unsigned, bad, revoked and unknown signer packages never become active.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from enum import Enum


class SignatureVerdict(str, Enum):
    ACCEPT = "accept"
    UNSIGNED = "unsigned"
    BAD_SIGNATURE = "bad_signature"
    UNKNOWN_SIGNER = "unknown_signer"
    REVOKED = "revoked"


def sign_payload(payload: bytes, *, signer: str, secret: bytes) -> str:
    digest = hmac.new(secret, signer.encode("utf-8") + b"\0" + payload, hashlib.sha256).hexdigest()
    return f"tds-sig-v1:{signer}:{digest}"


def verify_signature(payload: bytes, signature: str, *, signer: str, secret: bytes) -> bool:
    expected = sign_payload(payload, signer=signer, secret=secret)
    return hmac.compare_digest(expected, signature)


@dataclass(slots=True)
class SignaturePolicy:
    """Small trust-policy model used by v3.0.6 tests and future Studio lessons."""

    signer_secrets: dict[str, bytes] = field(default_factory=dict)
    revoked_signatures: set[str] = field(default_factory=set)

    def approve_signer(self, signer: str, secret: bytes) -> None:
        self.signer_secrets[signer] = secret

    def revoke(self, signature: str) -> None:
        self.revoked_signatures.add(signature)

    def evaluate(self, payload: bytes, signature: str | None) -> SignatureVerdict:
        if not signature:
            return SignatureVerdict.UNSIGNED
        if signature in self.revoked_signatures:
            return SignatureVerdict.REVOKED
        parts = signature.split(":", 2)
        if len(parts) != 3 or parts[0] != "tds-sig-v1":
            return SignatureVerdict.BAD_SIGNATURE
        _, signer, _digest = parts
        secret = self.signer_secrets.get(signer)
        if secret is None:
            return SignatureVerdict.UNKNOWN_SIGNER
        if not verify_signature(payload, signature, signer=signer, secret=secret):
            return SignatureVerdict.BAD_SIGNATURE
        return SignatureVerdict.ACCEPT

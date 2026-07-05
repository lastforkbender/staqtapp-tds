"""Driver registry state model for the future native Driver VM.

The registry in v3.0.6 is intentionally non-executing. It records driver trust
state transitions and rejects unsafe activation paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .manifest import DriverManifest, validate_manifest
from .signature import SignaturePolicy, SignatureVerdict


class DriverState(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    QUARANTINED = "quarantined"
    APPROVED = "approved"
    SIGNED = "signed"
    ACTIVE = "active"
    RETIRED = "retired"
    REVOKED = "revoked"


class RegistryError(RuntimeError):
    pass


@dataclass(slots=True)
class DriverRecord:
    manifest: DriverManifest
    state: DriverState = DriverState.DRAFT
    signature: str | None = None
    test_report_hash: str | None = None


class DriverRegistry:
    """Minimal in-memory registry contract used for foundation tests."""

    def __init__(self, signature_policy: SignaturePolicy | None = None) -> None:
        self.signature_policy = signature_policy or SignaturePolicy()
        self._records: dict[str, DriverRecord] = {}

    def add_candidate(self, manifest: DriverManifest, *, test_report_hash: str | None = None) -> DriverRecord:
        validate_manifest(manifest)
        record = DriverRecord(manifest=manifest, state=DriverState.CANDIDATE, test_report_hash=test_report_hash)
        self._records[manifest.driver_id] = record
        return record

    def approve(self, driver_id: str) -> DriverRecord:
        record = self.require(driver_id)
        if record.state is not DriverState.CANDIDATE:
            raise RegistryError("only candidate drivers can be approved")
        if not record.test_report_hash:
            raise RegistryError("candidate driver must have a test report before approval")
        record.state = DriverState.APPROVED
        return record

    def attach_signature(self, driver_id: str, signature: str) -> DriverRecord:
        record = self.require(driver_id)
        if record.state is not DriverState.APPROVED:
            raise RegistryError("only approved drivers can be signed")
        verdict = self.signature_policy.evaluate(record.manifest.canonical_payload(), signature)
        if verdict is not SignatureVerdict.ACCEPT:
            raise RegistryError(f"signature rejected: {verdict.value}")
        record.signature = signature
        record.state = DriverState.SIGNED
        return record

    def activate(self, driver_id: str) -> DriverRecord:
        record = self.require(driver_id)
        if record.state is not DriverState.SIGNED:
            raise RegistryError("only signed drivers can be activated")
        verdict = self.signature_policy.evaluate(record.manifest.canonical_payload(), record.signature)
        if verdict is not SignatureVerdict.ACCEPT:
            raise RegistryError(f"signature rejected: {verdict.value}")
        record.state = DriverState.ACTIVE
        return record

    def retire(self, driver_id: str) -> DriverRecord:
        record = self.require(driver_id)
        if record.state is DriverState.REVOKED:
            raise RegistryError("revoked drivers cannot be retired")
        record.state = DriverState.RETIRED
        return record

    def revoke(self, driver_id: str) -> DriverRecord:
        record = self.require(driver_id)
        if record.signature:
            self.signature_policy.revoke(record.signature)
        record.state = DriverState.REVOKED
        return record

    def require(self, driver_id: str) -> DriverRecord:
        try:
            return self._records[driver_id]
        except KeyError as exc:
            raise RegistryError(f"unknown driver: {driver_id}") from exc

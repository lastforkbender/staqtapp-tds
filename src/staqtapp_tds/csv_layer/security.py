"""CSV artifact security envelope for .tds directory integration.

The CSV layer derives durable TDS entry names from a CSV identifier.  This module
keeps that identifier/key surface deliberately narrow so later storage-engine
integration does not inherit path separators, ambiguous namespaces, control
characters, or unbounded caller-controlled key material.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from staqtapp_tds.tds_filesystem import TDSDirectory

from .manifest import artifact_keys, is_safe_csv_id, validate_csv_id

CSV_ARTIFACT_KEY_MAX_LENGTH = 256
CSV_ARTIFACT_NAMESPACE_PREFIX = "csv__"


@dataclass(frozen=True, slots=True)
class CSVArtifactSecurityReport:
    """Read-only security envelope report for managed CSV artifact keys."""

    csv_id: str
    status: str
    id_safe: bool
    namespace_prefix: str
    artifact_key_count: int
    core_keyset_verified: bool
    scan_keyset_verified: bool
    checked_artifacts: tuple[str, ...]
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    per_row_writes: bool = False
    per_cell_writes: bool = False
    native_storage_hot_path_touched: bool = False
    semantic_reasoning: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "valid" and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_artifacts"] = list(self.checked_artifacts)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        data["ok"] = self.ok
        return data


def validate_csv_artifact_key(key: str, csv_id: str) -> str:
    """Return *key* after verifying it is contained in the CSV namespace."""
    safe_id = validate_csv_id(csv_id)
    if not isinstance(key, str):
        raise ValueError("CSV artifact key must be a string")
    if not key:
        raise ValueError("CSV artifact key must not be empty")
    if len(key) > CSV_ARTIFACT_KEY_MAX_LENGTH:
        raise ValueError(f"CSV artifact key must be at most {CSV_ARTIFACT_KEY_MAX_LENGTH} characters")
    if any(token in key for token in ("/", "\\", "\x00", "\r", "\n", "\t")):
        raise ValueError("CSV artifact key contains path or control characters")
    expected_prefix = f"{CSV_ARTIFACT_NAMESPACE_PREFIX}{safe_id}__"
    if not key.startswith(expected_prefix):
        raise ValueError("CSV artifact key is outside the expected CSV namespace")
    if key.count("__") < 2:
        raise ValueError("CSV artifact key is missing a CSV artifact suffix")
    return key


def _read(directory: TDSDirectory, key: str) -> tuple[bool, Any]:
    try:
        return True, directory.read_value(key)
    except Exception as exc:  # pragma: no cover - exact TDS read error type is intentionally abstracted
        return False, exc


def _validate_exact_keyset(
    *,
    csv_id: str,
    actual: Mapping[str, Any],
    expected: Mapping[str, str],
    label: str,
    errors: list[str],
) -> bool:
    verified = True
    actual_keys = {str(k): str(v) for k, v in dict(actual).items()}
    if actual_keys != dict(expected):
        errors.append(f"{label}_keyset_mismatch")
        verified = False
    for name, key in {**dict(expected), **actual_keys}.items():
        try:
            validate_csv_artifact_key(key, csv_id)
        except Exception as exc:
            errors.append(f"{label}_{name}_unsafe_key:{type(exc).__name__}")
            verified = False
    return verified


def validate_csv_artifact_security(
    directory: TDSDirectory,
    csv_id: str,
    *,
    include_scan_artifacts: bool = False,
) -> CSVArtifactSecurityReport:
    """Validate the CSV identifier and artifact-key envelope without mutation.

    This is an advanced read-only check. It does not parse CSV rows, materialize
    evidence, run semantic inference, or touch the native storage hot path.
    """
    checked: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    artifact_key_count = 0
    core_keyset_verified = False
    scan_keyset_verified = not include_scan_artifacts

    try:
        safe_id = validate_csv_id(csv_id)
    except Exception as exc:
        errors.append(f"csv_id_unsafe:{type(exc).__name__}:{exc}")
        return CSVArtifactSecurityReport(
            csv_id=str(csv_id),
            status="invalid",
            id_safe=False,
            namespace_prefix=CSV_ARTIFACT_NAMESPACE_PREFIX,
            artifact_key_count=0,
            core_keyset_verified=False,
            scan_keyset_verified=False,
            checked_artifacts=tuple(checked),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    expected_core = artifact_keys(safe_id)
    manifest_ok, manifest_value = _read(directory, expected_core["manifest"])
    checked.append("manifest")
    if not manifest_ok or not isinstance(manifest_value, dict):
        errors.append("manifest_unreadable_for_security_envelope")
    else:
        if manifest_value.get("csv_id") != safe_id:
            errors.append("manifest_csv_id_mismatch")
        manifest_keys = manifest_value.get("artifact_keys", {}) or {}
        if not isinstance(manifest_keys, dict):
            errors.append("manifest_artifact_keys_not_mapping")
        else:
            core_keyset_verified = _validate_exact_keyset(
                csv_id=safe_id,
                actual=manifest_keys,
                expected=expected_core,
                label="core",
                errors=errors,
            )
            artifact_key_count += len(manifest_keys)

    if include_scan_artifacts:
        from .scan_artifacts import csv_scan_artifact_keys

        expected_scan = csv_scan_artifact_keys(safe_id)
        scan_keyset_verified = True
        for artifact_name, key in expected_scan.items():
            checked.append(artifact_name)
            try:
                validate_csv_artifact_key(key, safe_id)
            except Exception as exc:
                errors.append(f"scan_{artifact_name}_unsafe_key:{type(exc).__name__}")
                scan_keyset_verified = False
                continue
            ok, value = _read(directory, key)
            if not ok or not isinstance(value, dict):
                errors.append(f"scan_{artifact_name}_unreadable_for_security_envelope")
                scan_keyset_verified = False
            artifact_key_count += 1

    status = "valid" if not errors else "invalid"
    return CSVArtifactSecurityReport(
        csv_id=safe_id,
        status=status,
        id_safe=is_safe_csv_id(safe_id),
        namespace_prefix=CSV_ARTIFACT_NAMESPACE_PREFIX,
        artifact_key_count=artifact_key_count,
        core_keyset_verified=core_keyset_verified,
        scan_keyset_verified=scan_keyset_verified,
        checked_artifacts=tuple(dict.fromkeys(checked)),
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(warnings),
    )

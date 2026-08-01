"""Deterministic synthetic qualification for the isolated capture producer."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Mapping, Sequence

from .capture_attestation import (
    CaptureReadOnlyStatusSnapshot,
    compare_capture_status,
)
from .capture_producer import (
    EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY,
    EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
    CaptureProducerAuthorityBoundary,
    CaptureProducerLimits,
    CaptureProducerProfile,
    CaptureProducerResult,
    InstalledDistributionInspection,
    inspect_distribution_object,
    produce_offline_capture,
    validate_distribution_member_path,
)
from .exactness_common import (
    EaglegateExactnessError,
    canonical_root,
    require_ascii,
    require_root,
)
from .vllm_shadow_suite import (
    reference_vllm_eagle_snapshot,
    snapshot_to_mapping,
)

EAGLEGATE_CAPTURE_PRODUCER_SUITE_ID = (
    "eaglegate-isolated-capture-producer-reference-v1"
)


def _root(label: str) -> str:
    return canonical_root("capture-producer-fixture", {"label": label})


class _SyntheticDistribution:
    def __init__(
        self,
        root: Path,
        *,
        name: str = "vllm",
        version: str = "0.0.0-fixture.1",
        files: tuple[PurePosixPath, ...] | None = None,
    ) -> None:
        self._root = root
        self.metadata = {"Name": name}
        self.version = version
        self.files = files if files is not None else tuple(
            PurePosixPath(path.relative_to(root).as_posix())
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )

    def read_text(self, name: str) -> str | None:
        path = self._root / "vllm-0.0.0.dist-info" / name
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def locate_file(self, member: Any) -> Path:
        if str(member) == "":
            return self._root
        return self._root / Path(str(member))


def _write_synthetic_distribution(root: Path) -> _SyntheticDistribution:
    package = root / "vllm"
    dist_info = root / "vllm-0.0.0.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "__version__ = '0.0.0-fixture.1'\n", encoding="utf-8", newline="\n"
    )
    (package / "engine.py").write_text(
        "CAPABILITY_ONLY = True\n", encoding="utf-8", newline="\n"
    )
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: vllm\nVersion: 0.0.0-fixture.1\n",
        encoding="utf-8",
        newline="\n",
    )
    (dist_info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nGenerator: eaglegate-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        encoding="utf-8",
        newline="\n",
    )
    record_paths = (
        "vllm/__init__.py",
        "vllm/engine.py",
        "vllm-0.0.0.dist-info/METADATA",
        "vllm-0.0.0.dist-info/WHEEL",
        "vllm-0.0.0.dist-info/RECORD",
    )
    (dist_info / "RECORD").write_text(
        "".join(f"{path},,\n" for path in record_paths),
        encoding="utf-8",
        newline="\n",
    )
    return _SyntheticDistribution(root)


def _reference_result(root: Path) -> CaptureProducerResult:
    distribution = _write_synthetic_distribution(root)
    inspection = inspect_distribution_object(
        distribution, expected_name="vllm"
    )
    snapshot = snapshot_to_mapping(reference_vllm_eagle_snapshot())
    profile = CaptureProducerProfile(source_commit_root=_root("source-commit"))
    return produce_offline_capture(snapshot, inspection, profile)


@dataclass(frozen=True, slots=True)
class CaptureProducerCheck:
    name: str
    passed: bool
    evidence_root: str
    detail: str

    def __post_init__(self) -> None:
        require_ascii("name", self.name)
        if not isinstance(self.passed, bool):
            raise EaglegateExactnessError("passed must be boolean")
        require_root("evidence_root", self.evidence_root)
        require_ascii("detail", self.detail, allow_spaces=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence_root": self.evidence_root,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class CaptureProducerReport:
    checks: tuple[CaptureProducerCheck, ...]
    reference_result_root: str

    def __post_init__(self) -> None:
        if not self.checks or any(
            not isinstance(item, CaptureProducerCheck) for item in self.checks
        ):
            raise EaglegateExactnessError(
                "checks must contain CaptureProducerCheck"
            )
        require_root("reference_result_root", self.reference_result_root)

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.checks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "producer_contract_id": EAGLEGATE_CAPTURE_PRODUCER_CONTRACT_ID,
            "suite_id": EAGLEGATE_CAPTURE_PRODUCER_SUITE_ID,
            "authority_root": EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY.authority_root,
            "reference_result_root": self.reference_result_root,
            "passed": self.passed,
            "check_count": len(self.checks),
            "checks": [item.canonical_dict() for item in self.checks],
            "source_commit_verified": False,
            "provider_runtime_imported": False,
            "model_artifact_read": False,
            "model_loaded": False,
            "accelerator_probed": False,
            "network_used": False,
            "subprocess_used": False,
            "dynamic_code_executed": False,
            "inference_performed": False,
            "token_acceptance_authority": False,
            "kv_commit_authority": False,
            "activation_authority": False,
            "real_runtime_qualified": False,
            "contains_prompt_content": False,
            "contains_token_sequences": False,
            "contains_logits": False,
            "contains_hidden_states": False,
            "contains_kv_tensors": False,
            "contains_private_keys": False,
        }

    @property
    def report_root(self) -> str:
        return canonical_root("capture-producer-report", self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "report_root": self.report_root}


def _content_free(value: Any) -> bool:
    forbidden = {
        "prompt",
        "prompt_text",
        "tokens",
        "token_sequence",
        "logits",
        "logits_payload",
        "hidden_states",
        "kv_tensor",
        "kv_tensors",
        "private_key",
        "secret_key",
    }
    if isinstance(value, Mapping):
        return all(
            key not in forbidden and _content_free(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(_content_free(item) for item in value)
    return True


def run_reference_capture_producer_suite() -> CaptureProducerReport:
    checks: list[CaptureProducerCheck] = []
    with tempfile.TemporaryDirectory(prefix="eaglegate-producer-a-") as first_dir:
        first = _reference_result(Path(first_dir))
    with tempfile.TemporaryDirectory(prefix="eaglegate-producer-b-") as second_dir:
        second = _reference_result(Path(second_dir))

    checks.append(
        CaptureProducerCheck(
            "deterministic_distribution_capture",
            first.inspection.distribution_root
            == second.inspection.distribution_root
            and first.envelope.capture_root == second.envelope.capture_root
            and first.result_root == second.result_root,
            first.result_root,
            "identical package bytes produce identical inspection bundle and result roots",
        )
    )

    version_rejected = False
    try:
        produce_offline_capture(
            snapshot_to_mapping(
                replace(reference_vllm_eagle_snapshot(), runtime_version="0.0.1")
            ),
            first.inspection,
            CaptureProducerProfile(source_commit_root=_root("source-commit")),
        )
    except EaglegateExactnessError:
        version_rejected = True
    checks.append(
        CaptureProducerCheck(
            "runtime_version_binding",
            version_rejected,
            first.inspection.distribution_root,
            "installed distribution version must equal the pinned provider snapshot",
        )
    )

    provider_rejected = False
    try:
        CaptureProducerProfile(
            source_commit_root=_root("source-commit"),
            provider_id="unknown-provider-v1",
        )
    except EaglegateExactnessError:
        provider_rejected = True
    checks.append(
        CaptureProducerCheck(
            "closed_provider_profile",
            provider_rejected,
            first.profile_root,
            "producer v1 accepts only the registered vllm-eagle provider",
        )
    )

    traversal_rejected = False
    try:
        validate_distribution_member_path("../outside.py")
    except EaglegateExactnessError:
        traversal_rejected = True
    checks.append(
        CaptureProducerCheck(
            "path_traversal_rejected",
            traversal_rejected,
            first.inspection.file_manifest_root,
            "distribution members cannot escape the installed package root",
        )
    )

    model_rejected = False
    try:
        validate_distribution_member_path("weights/model.safetensors")
    except EaglegateExactnessError:
        model_rejected = True
    checks.append(
        CaptureProducerCheck(
            "model_artifact_rejected",
            model_rejected,
            first.inspection.file_manifest_root,
            "model weight formats are outside producer authority",
        )
    )

    file_count_rejected = False
    with tempfile.TemporaryDirectory(prefix="eaglegate-producer-count-") as directory:
        distribution = _write_synthetic_distribution(Path(directory))
        try:
            inspect_distribution_object(
                distribution,
                expected_name="vllm",
                limits=CaptureProducerLimits(max_files=1),
            )
        except EaglegateExactnessError:
            file_count_rejected = True
    checks.append(
        CaptureProducerCheck(
            "file_count_bound",
            file_count_rejected,
            first.inspection.limits_root,
            "distribution capture is bounded before hashing begins",
        )
    )

    total_bytes_rejected = False
    with tempfile.TemporaryDirectory(prefix="eaglegate-producer-bytes-") as directory:
        distribution = _write_synthetic_distribution(Path(directory))
        try:
            inspect_distribution_object(
                distribution,
                expected_name="vllm",
                limits=CaptureProducerLimits(
                    max_file_bytes=64,
                    max_total_bytes=64,
                    max_metadata_bytes=4096,
                ),
            )
        except EaglegateExactnessError:
            total_bytes_rejected = True
    checks.append(
        CaptureProducerCheck(
            "byte_budget_enforced",
            total_bytes_rejected,
            first.inspection.limits_root,
            "per-file and aggregate package reads are bounded",
        )
    )

    duplicate_rejected = False
    with tempfile.TemporaryDirectory(prefix="eaglegate-producer-duplicate-") as directory:
        distribution = _write_synthetic_distribution(Path(directory))
        duplicate = _SyntheticDistribution(
            Path(directory), files=distribution.files + (distribution.files[0],)
        )
        try:
            inspect_distribution_object(duplicate, expected_name="vllm")
        except EaglegateExactnessError:
            duplicate_rejected = True
    checks.append(
        CaptureProducerCheck(
            "duplicate_member_rejected",
            duplicate_rejected,
            first.inspection.file_manifest_root,
            "duplicate normalized package paths cannot alter manifest identity",
        )
    )

    status = CaptureReadOnlyStatusSnapshot(
        provider_id=first.envelope.provider_id,
        capture_root=first.envelope.capture_root,
        provider_snapshot_payload_root=first.decision.provider_snapshot_payload_root,
        adapter_identity_root=first.decision.adapter_identity_root,
        runtime_distribution_root=first.envelope.runtime_distribution_root,
        package_metadata_root=first.envelope.package_metadata_root,
        source_commit_root=first.envelope.source_commit_root,
        environment_root=first.envelope.environment_root,
        service_instance_root=_root("service-instance"),
        status_exporter_root=_root("status-exporter"),
        snapshot_generation=1,
    )
    observation = compare_capture_status(
        first.envelope,
        first.decision,
        status,
        witness_id="producer-witness",
        witness_tool_root=_root("producer-witness-tool"),
    )
    checks.append(
        CaptureProducerCheck(
            "downstream_capture_and_witness_binding",
            first.decision.compatible
            and observation.matched
            and first.envelope.runtime_distribution_root
            == first.inspection.distribution_root,
            observation.observation_root,
            "produced bundles pass the canonical importer and exact witness comparison",
        )
    )

    authority_rejected = False
    try:
        CaptureProducerAuthorityBoundary(may_import_provider_runtime=True)
    except EaglegateExactnessError:
        authority_rejected = True
    partial = CaptureProducerReport(tuple(checks), first.result_root)
    checks.append(
        CaptureProducerCheck(
            "authority_and_evidence_boundary",
            authority_rejected
            and _content_free(partial.canonical_dict())
            and first.canonical_dict()["source_commit_verified"] is False,
            EAGLEGATE_CAPTURE_PRODUCER_AUTHORITY.authority_root,
            "producer cannot import execute infer activate read weights or claim source verification",
        )
    )

    return CaptureProducerReport(tuple(checks), first.result_root)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="staqtapp-tds-eaglegate-capture-producer-lab"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_reference_capture_producer_suite()
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    else:
        print(
            "Eaglegate isolated capture producer: "
            + ("PASS" if report.passed else "FAIL")
        )
        for item in report.checks:
            state = "PASS" if item.passed else "FAIL"
            print(f"  {state}  {item.name}: {item.detail}")
        print(f"report_root: {report.report_root}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_CAPTURE_PRODUCER_SUITE_ID",
    "CaptureProducerCheck",
    "CaptureProducerReport",
    "run_reference_capture_producer_suite",
]

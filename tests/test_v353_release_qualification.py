from __future__ import annotations

from pathlib import Path

from staqtapp_tds import (
    ControlledStorage,
    ImmutableSegmentStore,
    StorageMode,
    __version__,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v353_release_identity_and_phase_evidence_are_explicit() -> None:
    assert __version__ == "3.5.3"
    assert StorageMode.LEGACY.value == "legacy"
    assert StorageMode.GUARANTEED_SEGMENTED.value == "guaranteed-segmented"
    assert ControlledStorage.ACTIVATE_ACKNOWLEDGEMENT == "activate-guaranteed-segmented"
    assert ControlledStorage.ROLLBACK_ACKNOWLEDGEMENT == "rollback-to-legacy"
    for relative in (
        "DEV6_GUARANTEED_STORAGE_TRANSITION_STATUS.txt",
        "DEV7_MATERIALIZATION_FAULT_QUALIFICATION_STATUS.txt",
        "DEV8_VERIFIED_ROUND_TRIP_MIGRATION_STATUS.txt",
        "DEV9_INCREMENTAL_IMMUTABLE_SEGMENTS_STATUS.txt",
        "DEV10_CONTROLLED_ACTIVATION_STATUS.txt",
        "DEV11_RELEASE_QUALIFICATION_STATUS.txt",
        "docs/118_v353_dev10_Controlled_Activation.md",
        "docs/119_v353_dev11_Release_Qualification.md",
    ):
        assert (ROOT / relative).is_file()
    phase11 = (ROOT / "DEV11_RELEASE_QUALIFICATION_STATUS.txt").read_text(encoding="utf-8")
    assert "STATUS: LOCAL QUALIFICATION COMPLETE" in phase11
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include AUDIT_REMEDIATION_STATUS.txt DEV*_STATUS.txt" in manifest

    guide = ROOT / "tds_api_docs" / "Staqtapp_TDS_Programmer_Core_API_Guide.pdf"
    guide_bytes = guide.read_bytes()
    assert b"/TDSV353SupplementPages (3)" in guide_bytes
    assert b"/TDSLightBlueLabelSpacing (v1)" in guide_bytes
    api_readme = (ROOT / "tds_api_docs" / "README.md").read_text(encoding="utf-8")
    assert "historical v3.1.23" in api_readme
    assert "not an exhaustive v3.5.3 inventory" in api_readme


def test_incremental_generation_recovery_and_gc_soak(tmp_path: Path) -> None:
    segment_bytes = 64
    segment_count = 64
    store = ImmutableSegmentStore(tmp_path / "soak", segment_bytes=segment_bytes)
    payload = bytearray(segment_bytes * segment_count)
    reports = [store.commit(bytes(payload))]

    # Two complete mutation passes make every first-pass segment and the shared
    # all-zero baseline unreachable. Each commit must still write only one
    # physical segment while representing the complete logical generation.
    for iteration in range(1, (segment_count * 2) + 1):
        segment_index = (iteration - 1) % segment_count
        offset = segment_index * segment_bytes
        payload[offset:offset + 8] = iteration.to_bytes(8, "big")
        report = store.commit(bytes(payload))
        reports.append(report)
        assert report.logical_bytes == len(payload)
        assert report.segments_created == 1
        assert report.segments_reused == segment_count - 1
        assert report.bytes_written == segment_bytes
        assert store.verify(report.generation.generation_id).logical_sha256 == report.generation.logical_sha256

        if iteration in {32, 64, 96}:
            store.current_path.write_text("torn-pointer\n", encoding="ascii")
            recovered = store.recover_current()
            assert recovered.generation_id == report.generation.generation_id
            assert store.read_current() == bytes(payload)

    current_id = reports[-1].generation.generation_id
    for generation in store.list_generations():
        if generation.generation_id != current_id:
            store.delete_generation(generation.generation_id)

    dry_run = store.collect_unreferenced_segments(dry_run=True)
    assert dry_run.blocked is False
    assert dry_run.removed_segments == ()
    assert len(dry_run.candidate_segments) == segment_count + 1

    collected = store.collect_unreferenced_segments(dry_run=False)
    assert collected.blocked is False
    assert set(collected.removed_segments) == set(dry_run.candidate_segments)
    assert collected.removed_bytes == len(collected.removed_segments) * segment_bytes
    assert store.current_generation() == current_id
    assert store.read_current() == bytes(payload)
    assert store.verify(current_id)


def test_release_workflow_makes_publication_depend_on_every_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "python-compatibility:" in workflow
    assert "platform-compatibility:" in workflow
    assert "native-extension-qualification:" in workflow
    assert "build-distributions:" in workflow
    assert "release-gates-complete:" in workflow
    assert "publish-pypi:" in workflow
    assert workflow.index("build-distributions:") < workflow.index("publish-pypi:")
    assert "needs: release-gates-complete" in workflow
    assert "name: Release gates complete" in workflow
    assert "github.ref_name == 'v3.5.3'" in workflow
    assert "id-token: write" in workflow
    assert not (ROOT / ".github" / "workflows" / "publish.yml").exists()


def test_production_pypi_smoke_covers_every_supported_os() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pypi-smoke.yml").read_text(
        encoding="utf-8"
    )
    assert "release:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "https://pypi.org/simple" in workflow
    assert "--no-cache-dir" in workflow
    assert "staqtapp-tds=={version}" in workflow
    assert "ubuntu-latest" in workflow
    assert "macos-latest" in workflow
    assert "windows-latest" in workflow
    assert "python -I" in workflow
    assert "name: Production PyPI smoke complete" in workflow

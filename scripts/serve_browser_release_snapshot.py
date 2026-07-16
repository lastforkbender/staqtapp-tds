#!/usr/bin/env python3
"""Serve a real, deterministic TDS Browser release-qualification snapshot."""

from __future__ import annotations

import argparse

from staqtapp_tds import TDSFileSystem
from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.admin.panel import AdminPanelServer
from staqtapp_tds.admin.spiral_rank import SpiralRankTelemetry
from staqtapp_tds.csv_layer import (
    commit_csv_interpole_determinant_vector_report,
    commit_csv_interpole_timeline_report,
    commit_csv_interpole_timeline_ring_report,
    commit_csv_kernel_performance_gate_report,
    commit_csv_kernel_readiness_contract_report,
    commit_csv_native_row_anchor_kernel_report,
    commit_csv_native_scan_kernel_prototype_report,
    commit_csv_native_storage_artifacts,
    commit_csv_native_storage_revalidation_report,
    commit_csv_storage_adapter_replay_report,
    commit_csv_storage_bridge_manifest,
    import_csv_bytes,
    prepare_csv_interpole_browser_monitor_snapshot,
)
from staqtapp_tds.spiral import NativeSpiralRankEngine


CSV_RELEASE_EVIDENCE = (
    b"id,name,score,stage\n"
    b"1,Ada,99,qualified\n"
    b"2,Grace,98,qualified\n"
    b"3,Katherine,97,qualified\n"
    b"4,Barbara,96,qualified\n"
)


def _require_ok(report: object, name: str) -> None:
    if not bool(getattr(report, "ok", False)):
        raise RuntimeError(f"{name} did not produce valid release evidence: {report!r}")


def _prepare_csv_monitor(fs: TDSFileSystem):
    manifest = import_csv_bytes(
        fs.root,
        CSV_RELEASE_EVIDENCE,
        source_name="phase11_browser_release_qualification.csv",
    )
    stages = (
        ("storage bridge", commit_csv_storage_bridge_manifest(fs.root, manifest.csv_id)),
        ("adapter replay", commit_csv_storage_adapter_replay_report(fs.root, manifest.csv_id)),
        ("native storage", commit_csv_native_storage_artifacts(fs.root, manifest.csv_id)),
        ("native revalidation", commit_csv_native_storage_revalidation_report(fs.root, manifest.csv_id)),
        ("Interpole timeline", commit_csv_interpole_timeline_report(fs.root, manifest.csv_id)),
        ("determinant vectors", commit_csv_interpole_determinant_vector_report(fs.root, manifest.csv_id)),
        ("timeline ring", commit_csv_interpole_timeline_ring_report(fs.root, manifest.csv_id)),
        ("kernel readiness", commit_csv_kernel_readiness_contract_report(fs.root, manifest.csv_id, chunk_size=7)),
        ("native scan", commit_csv_native_scan_kernel_prototype_report(fs.root, manifest.csv_id, chunk_size=7)),
        ("row anchors", commit_csv_native_row_anchor_kernel_report(fs.root, manifest.csv_id, chunk_size=7)),
        ("performance gate", commit_csv_kernel_performance_gate_report(fs.root, manifest.csv_id)),
    )
    for name, report in stages:
        _require_ok(report, name)
    snapshot = prepare_csv_interpole_browser_monitor_snapshot(fs.root, manifest.csv_id)
    _require_ok(snapshot, "CSV Interpole Browser snapshot")
    return snapshot


class ReleaseQualificationSource:
    """Expose real TDS, CSV, and Spiral Rank observer snapshots to AdminControl."""

    def __init__(self) -> None:
        self.fs = TDSFileSystem("phase11-release-browser")
        release = self.fs.makedirs("/release/qualification")
        for index in range(32):
            release.write_text(
                f"evidence-{index:02d}.txt",
                f"Phase 11 release evidence row {index:02d}. " * 12,
                provenance="REAL",
            )
        release.write_json(
            "qualification.json",
            {"phase": 11, "status": "testing", "push_authorized": False},
            provenance="REAL",
        )
        for index in range(24):
            release.read_text(f"evidence-{index % 8:02d}.txt")

        self.csv_snapshot = _prepare_csv_monitor(self.fs)
        self.spiral_rank_telemetry = SpiralRankTelemetry()
        engine = NativeSpiralRankEngine(prefer_native=True)
        trace_ids = [f"phase11-trace-{index:02d}" for index in range(18)]
        for run_index in range(6):
            scores = [0.99 - (index * 0.025) + (run_index * 0.001) for index in range(18)]
            run = engine.rank_run(
                trace_ids,
                scores,
                confidences=[0.97 - (index * 0.01) for index in range(18)],
                depths=[index % 5 for index in range(18)],
                ages_ns=[index * 1000 for index in range(18)],
                limit=8,
            )
            self.spiral_rank_telemetry.observe_run(run)

        # Publish after all release evidence has been generated so every page
        # consumes one complete, internally consistent observer snapshot.
        self._observation = self.fs.observation_snapshot(force=True)

    def observation_snapshot(self):
        return self._observation

    def csv_interpole_monitor_snapshot(self):
        return self.csv_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    source = ReleaseQualificationSource()
    panel = AdminPanelServer(
        control=AdminControl(observation_source=source),
        host=args.host,
        port=args.port,
    )
    panel.serve_forever()


if __name__ == "__main__":
    main()

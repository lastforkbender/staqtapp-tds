from __future__ import annotations

import hashlib
import importlib.util
import json
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUALIFIER_PATH = ROOT / "benchmarks" / "qualify_native_handle_allocator.py"
SPEC = importlib.util.spec_from_file_location("native_allocator_qualifier", QUALIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
QUALIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFIER)


def test_harness_binding_requires_exact_head_baseline_blobs_and_c_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    benchmark_dir = repo / "benchmarks"
    benchmark_dir.mkdir(parents=True)
    runner = benchmark_dir / "qualify_native_handle_allocator.py"
    worker = benchmark_dir / "native_allocator_release_sample.py"
    sentinel = benchmark_dir / "native_allocator_release_sentinels.py"
    for path, content in ((runner, b"runner-v2"), (worker, b"worker-v2"), (sentinel, b"sentinel-v2")):
        path.write_bytes(content)

    baseline_c = b"baseline-native-source"
    candidate_c = b"candidate-native-source"
    native_diff = (
        "diff --git a/src/staqtapp_tds/_native_index.c b/src/staqtapp_tds/_native_index.c\n"
        "-    if (handle_in_use_locked(self, handle, -1)) return -4;\n"
    )
    monkeypatch.setattr(QUALIFIER, "RUNNER_PATH", runner)
    monkeypatch.setattr(QUALIFIER, "WORKER_PATH", worker)
    monkeypatch.setattr(QUALIFIER, "SENTINEL_PATH", sentinel)
    monkeypatch.setattr(QUALIFIER, "BASELINE_COMMIT", "baseline-commit")
    monkeypatch.setattr(
        QUALIFIER, "BASELINE_NATIVE_SOURCE_SHA256", hashlib.sha256(baseline_c).hexdigest()
    )
    monkeypatch.setattr(
        QUALIFIER, "CANDIDATE_NATIVE_SOURCE_SHA256", hashlib.sha256(candidate_c).hexdigest()
    )
    monkeypatch.setattr(
        QUALIFIER, "NATIVE_SOURCE_DIFF_SHA256", hashlib.sha256(native_diff.encode()).hexdigest()
    )

    def fake_git(_repo: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "HEAD^{commit}"):
            return "candidate-commit"
        if arguments[:2] == ("status", "--porcelain"):
            return ""
        if arguments[0] == "rev-parse":
            return "exact-harness-blob"
        raise AssertionError(arguments)

    def fake_blob(_repo: Path, commit: str, relative: str) -> bytes:
        if relative == "src/staqtapp_tds/_native_index.c":
            return baseline_c if commit == "baseline-commit" else candidate_c
        return (repo / relative).read_bytes()

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[1:3] == ["merge-base", "--is-ancestor"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[1:3] == ["diff", "--no-ext-diff"]:
            return SimpleNamespace(returncode=0, stdout=native_diff, stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(QUALIFIER, "_git", fake_git)
    monkeypatch.setattr(QUALIFIER, "_git_blob", fake_blob)
    monkeypatch.setattr(QUALIFIER, "_run", fake_run)
    monkeypatch.setattr(
        QUALIFIER.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    baseline = {"commit": "baseline-commit", "tree": "baseline-tree"}
    candidate = {"commit": "candidate-commit", "tree": "candidate-tree"}
    evidence = QUALIFIER._verify_harness_binding(repo, baseline, candidate)
    assert evidence["tracked_worktree_clean"] is True
    assert evidence["native_index_diff_sha256"] == QUALIFIER.NATIVE_SOURCE_DIFF_SHA256
    assert set(evidence["harness_blobs"]) == {
        "benchmarks/qualify_native_handle_allocator.py",
        "benchmarks/native_allocator_release_sample.py",
        "benchmarks/native_allocator_release_sentinels.py",
    }

    with pytest.raises(RuntimeError, match="candidate ref must resolve exactly"):
        QUALIFIER._verify_harness_binding(
            repo,
            baseline,
            {"commit": "not-head", "tree": "candidate-tree"},
        )


def test_cells_include_full_tds_primary_complete_wrapper_and_mandatory_raw_control() -> None:
    cells = QUALIFIER._cells(8)
    full_primary = [cell for cell in cells if cell["role"].startswith("release-primary-")]
    wrapper = [cell for cell in cells if cell["role"].startswith("allocator-wrapper-")]
    raw = [cell for cell in cells if cell["role"] == "causal-localization-only"]
    assert {
        (cell["entries"], cell["threads"], cell["telemetry"], cell["diagnostics"])
        for cell in full_primary
    } == {
        (entries, threads, "normal", "off")
        for entries in (10_000, 50_000, 100_000)
        for threads in (1, 8)
    }
    assert len(full_primary) == 12
    assert {cell["comparison_id"] for cell in full_primary} == {
        "baseline-vs-allocator-only",
        "baseline-vs-candidate",
    }
    assert len(wrapper) == 2
    assert len(raw) == 1
    assert raw[0]["path"] == "raw"
    assert raw[0]["comparison"] == ["baseline", "allocator-only"]
    assert raw[0]["entries"] == 100_000 and raw[0]["threads"] == 1
    assert any(cell["path"] == "full-tds" and cell["telemetry"] == "off" for cell in cells)
    assert all(cell["diagnostics"] == "off" for cell in cells)
    assert len(cells) == 17


def _clean_interference() -> dict[str, object]:
    return {
        "affinity_before": [8],
        "affinity_after": [8],
        "affinity_source": "os.sched_getaffinity(0)",
        "cgroup_cpu_stat_delta": {"nr_throttled": 0, "throttled_usec": 0},
        "cgroup_cpu_stat_source": "/sys/fs/cgroup/cpu.stat",
        "required_cgroup_throttle_keys": ["nr_throttled", "throttled_usec"],
        "per_cpu_tick_delta": {"8": {"steal": 0}},
        "per_cpu_ticks_source": "/proc/stat",
        "cgroup_cpu_max": "max 100000",
        "cgroup_cpu_max_source": "/sys/fs/cgroup/cpu.max",
        "pressure_total_usec_delta": {"some": 0, "full": 0},
        "clock_ticks_per_second": 100,
        "evidence_errors": [],
    }


def _record(
    *,
    source: str,
    phase: str,
    pair: int,
    order: str,
    target_latency: float = 1.04,
    target_lookup_mean: float = 100.0,
    target_rss: float = 1.04,
) -> dict[str, object]:
    target = source != "baseline"
    insertion_mean = 50.0 if target else 100.0
    lookup_mean = target_lookup_mean if target else 100.0
    latency_factor = target_latency if target else 1.0
    rss = int(1_000_000 * (target_rss if target else 1.0))

    def measurement(mean: float, operations: int) -> dict[str, object]:
        wall = int(mean * operations)
        return {
            "operations": operations,
            "wall_ns": wall,
            "process_cpu_ns": wall,
            "cpu_utilization_percent": 100.0,
            "mean_wall_ns_per_operation": mean,
            "cpu_interference": _clean_interference(),
        }

    return {
        "schema": 2,
        "benchmark_id": "native-handle-allocator-release-sample-v2",
        "sample": {
            "phase": phase,
            "pair_index": pair,
            "order": order,
            "source_label": source,
        },
        "cell": {
            "id": "full-tds-shipped-normal-50000-t1",
            "comparison_id": "baseline-vs-candidate",
            "lookup_unique_keys": 50_000,
            "threads": 1,
        },
        "measurements": {
            "insertion": measurement(insertion_mean, 50_000),
            "lookup_control": measurement(lookup_mean, 1_000_000),
            "insertion_rss": {
                "peak_bytes_immediately_after_insertion": rss,
            },
            "whole_workload_rss": {"peak_bytes": rss, "current_bytes": rss},
            "final_process_rss": {"peak_bytes": rss, "current_bytes": rss},
        },
        "dedicated_latency": {
            "measurements": {
                "insertion": measurement(100.0 * latency_factor, 50_000),
                "lookup_control": measurement(100.0 * latency_factor, 1_000_000),
                "insertion_rss": {"peak_bytes_immediately_after_insertion": rss},
                "whole_workload_rss": {"peak_bytes": rss, "current_bytes": rss},
                "final_process_rss": {"peak_bytes": rss, "current_bytes": rss},
            },
            "operation_samples": {
                "insertion_ns": [100.0 * latency_factor] * 16,
                "lookup_ns": [100.0 * latency_factor] * 16,
            },
        },
        "runtime_identity": {
            "cpu_affinity": [8],
            "cgroup_cpu_max": {"source": "/sys/fs/cgroup/cpu.max", "raw": "max 100000"},
        },
        "semantic_outcome": {
            "handle_set_sha256": "handles",
            "value_sha256": "value",
            "key_handle_value_association_exact": True,
        },
        "association_sha256": "association",
        "real_tds_telemetry": {"telemetry_level": "normal", "write_count": 50_000},
        "final_stats": {
            "throughput_diagnostics": {
                "enabled": False,
                "native_put_calls": 0,
                "native_lookup_calls": 0,
                "python_native_transitions": 0,
                "gil_released_calls": 0,
                "events_emitted": 0,
                "events_dropped": 0,
            },
            "latency_diagnostics": {
                "enabled": False,
                "native_put_calls": 0,
                "native_lookup_calls": 0,
                "python_native_transitions": 0,
                "gil_released_calls": 0,
                "events_emitted": 0,
                "events_dropped": 0,
            },
        },
        "host_before": {"thermal_celsius": None, "thermal_source": "/sys/class/thermal/thermal_zone*/temp"},
        "host_after": {"thermal_celsius": None, "thermal_source": "/sys/class/thermal/thermal_zone*/temp"},
    }


def _records(**target_overrides: float) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for pair in range(2):
        order = "AB" if pair == 0 else "BA"
        records.extend(
            _record(source=source, phase="warmup", pair=pair, order=order, **target_overrides)
            for source in ("baseline", "candidate")
        )
    for pair in range(7):
        order = "AB" if pair % 2 == 0 else "BA"
        records.extend(
            _record(source=source, phase="measured", pair=pair, order=order, **target_overrides)
            for source in ("baseline", "candidate")
        )
    return records


def _summary(
    monkeypatch: pytest.MonkeyPatch,
    **target_overrides: float,
) -> dict[str, object]:
    monkeypatch.setattr(
        QUALIFIER,
        "_bootstrap_median_ci",
        lambda values, **_kwargs: [statistics.median(values), statistics.median(values)],
    )
    cell = {
        "id": "full-tds-shipped-normal-50000-t1",
        "comparison_id": "baseline-vs-candidate",
        "path": "full-tds",
        "diagnostics": "off",
        "telemetry": "normal",
        "entries": 50_000,
        "threads": 1,
        "role": "release-primary-shipped",
        "comparison": ["baseline", "candidate"],
    }
    return QUALIFIER._summarize_cell(
        cell,
        _records(**target_overrides),
        expected_pairs=7,
        bootstrap_seed=1,
    )


def test_operation_latency_lookup_and_rss_ci_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passing = _summary(monkeypatch)
    assert passing["passed"] is True
    assert passing["lookup_control"]["operations_per_process"] == 1_000_000
    assert passing["lookup_control"]["unique_keys_per_process"] == 50_000

    latency = _summary(monkeypatch, target_latency=1.06)
    assert any(
        not check["passed"] and check["name"] == "insertion_p95_latency_ci_upper"
        for check in latency["checks"]
    )
    lookup = _summary(monkeypatch, target_lookup_mean=104.0)
    assert any(
        not check["passed"] and check["name"] == "lookup_throughput_ci_lower"
        for check in lookup["checks"]
    )
    rss = _summary(monkeypatch, target_rss=1.06)
    assert any(
        not check["passed"] and check["name"] == "insertion_peak_rss_ci_upper"
        for check in rss["checks"]
    )


def test_worst_pair_checks_prevent_median_bootstrap_from_hiding_catastrophe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        QUALIFIER,
        "_bootstrap_median_ci",
        lambda values, **_kwargs: [statistics.median(values), statistics.median(values)],
    )
    records = _records()
    outlier = next(
        record
        for record in records
        if record["sample"]["phase"] == "measured"
        and record["sample"]["pair_index"] == 6
        and record["sample"]["source_label"] == "candidate"
    )
    outlier["measurements"]["insertion"]["mean_wall_ns_per_operation"] = 1_000.0
    outlier["measurements"]["lookup_control"]["mean_wall_ns_per_operation"] = 1_000.0
    outlier["measurements"]["insertion_rss"]["peak_bytes_immediately_after_insertion"] = 10_000_000
    outlier["measurements"]["whole_workload_rss"]["peak_bytes"] = 10_000_000
    outlier["dedicated_latency"]["operation_samples"]["insertion_ns"] = [1_000.0] * 16
    outlier["dedicated_latency"]["operation_samples"]["lookup_ns"] = [1_000.0] * 16
    cell = {
        "id": "full-tds-shipped-normal-50000-t1",
        "comparison_id": "baseline-vs-candidate",
        "path": "full-tds",
        "diagnostics": "off",
        "telemetry": "normal",
        "entries": 50_000,
        "threads": 1,
        "role": "release-primary-shipped",
        "comparison": ["baseline", "candidate"],
    }
    summary = QUALIFIER._summarize_cell(
        cell,
        records,
        expected_pairs=7,
        bootstrap_seed=1,
    )
    failed = {check["name"] for check in summary["checks"] if not check["passed"]}
    assert "insertion_gain_worst_pair_floor" in failed
    assert "lookup_throughput_worst_pair_floor" in failed
    assert "insertion_p95_latency_worst_pair" in failed
    assert "lookup_p99_latency_worst_pair" in failed
    assert "insertion_peak_rss_worst_pair" in failed
    assert "whole_workload_peak_rss_worst_pair" in failed


def test_summary_rejects_foreign_cell_or_comparison_id() -> None:
    records = _records()
    records[0]["cell"]["comparison_id"] = "baseline-vs-allocator-only"
    cell = {
        "id": "full-tds-shipped-normal-50000-t1",
        "comparison_id": "baseline-vs-candidate",
        "path": "full-tds",
        "diagnostics": "off",
        "telemetry": "normal",
        "entries": 50_000,
        "threads": 1,
        "role": "release-primary-shipped",
        "comparison": ["baseline", "candidate"],
    }
    with pytest.raises(RuntimeError, match="foreign comparison evidence"):
        QUALIFIER._summarize_cell(cell, records, expected_pairs=7, bootstrap_seed=1)


def test_status_never_masks_substantive_failure_as_host_pending() -> None:
    host = {"name": "host_interference", "kind": "validity"}
    gain = {"name": "insertion_gain_ci_lower", "kind": "performance"}
    semantic = {"name": "semantic_and_telemetry_equality", "kind": "deterministic"}
    assert QUALIFIER._decide_status([]) == "PASS"
    assert QUALIFIER._decide_status([host]) == "HOST_REVIEW_PENDING"
    assert QUALIFIER._decide_status([host, gain]) == "FAIL"
    assert QUALIFIER._decide_status([gain]) == "FAIL"
    assert QUALIFIER._decide_status([host, semantic]) == "FAIL"


def test_steal_is_normalized_by_cpu_capacity_and_missing_evidence_fails_closed() -> None:
    evidence = _clean_interference()
    evidence["affinity_before"] = [8, 9]
    evidence["affinity_after"] = [8, 9]
    evidence["per_cpu_tick_delta"] = {
        "8": {"steal": 1},
        "9": {"steal": 1},
    }
    phase = {"wall_ns": 1_000_000_000, "cpu_interference": evidence}
    record = {
        "cell": {"threads": 2},
        "runtime_identity": {
            "cpu_affinity": [8, 9],
            "cgroup_cpu_max": {"source": "/sys/fs/cgroup/cpu.max", "raw": "max 100000"},
        },
        "measurements": {"insertion": phase, "lookup_control": phase},
        "dedicated_latency": {
            "measurements": {"insertion": phase, "lookup_control": phase},
        },
    }
    result = QUALIFIER._interference(record)
    # 8 steal ticks / 100 Hz divided by (2 selected CPUs * 4 seconds).
    assert result["selected_cpu_steal_capacity_fraction"] == pytest.approx(0.01)
    assert result["clean"] is False

    evidence["per_cpu_tick_delta"] = None
    missing = QUALIFIER._interference(record)
    assert missing["evidence_complete"] is False
    assert missing["clean"] is False


def test_independent_telemetry_roots_require_real_records_and_exact_equality() -> None:
    normal = [{
        "semantic_outcome": {"handle_set_sha256": "h", "value_sha256": "v"},
        "association_sha256": "a",
    }]
    off = json.loads(json.dumps(normal))
    assert normal[0] is not off[0]
    assert QUALIFIER._independent_roots_equal(normal, off)
    off[0]["association_sha256"] = "changed"
    assert not QUALIFIER._independent_roots_equal(normal, off)
    assert not QUALIFIER._independent_roots_equal(normal, [])


def _sentinel_fixture() -> tuple[dict[str, object], dict[str, object]]:
    allocator = {
        "automatic_scan_present": False,
        "explicit_scan_present": True,
        "first_handles": list(range(1, 13)),
        "deleted_handle": 4,
        "after_delete": 13,
        "capacity_before_resize": 16,
        "capacity_after_resize": 64,
        "after_resize": 46,
        "restore_failures": ["ValueError:duplicate", "ValueError:reuse"],
        "exhaustion": "OverflowError:exhausted",
        "concurrent_handle_set_sha256": "concurrent",
    }
    file_records = [
        {
            "path": ".tds_manifest",
            "sha256": "manifest-sha",
            "size_bytes": 10,
            "st_blocks": 1,
            "allocated_bytes_st_blocks_x_512": 512,
        },
        {
            "path": "tds_root.tds",
            "sha256": "tds-sha",
            "size_bytes": 20,
            "st_blocks": 1,
            "allocated_bytes_st_blocks_x_512": 512,
        },
        {
            "path": "tds_root.tds.meta",
            "sha256": "meta-sha",
            "size_bytes": 30,
            "st_blocks": 1,
            "allocated_bytes_st_blocks_x_512": 512,
        },
    ]
    restored_semantics = {
        "preflush": {"keys": ["alpha", "beta", "gamma"], "handles": [1, 3, 4], "next_handle": 5},
        "serialized_keys": ["/tds_root/alpha", "/tds_root/beta", "/tds_root/gamma"],
        "reopened_keys": ["/tds_root/alpha", "/tds_root/beta", "/tds_root/gamma"],
        "restored_before_insert": {"keys": ["alpha", "beta", "gamma"], "handles": [1, 2, 3], "next_handle": 4},
        "restored_after_insert": {"delta_handle": 4, "next_handle": 5},
    }
    persistence = {
        "value_root": "value-root",
        "written_paths": ["tds_root.tds"],
        "restored_semantics": restored_semantics,
        "file_tree": {
            "records": file_records,
            "tree_root_sha256": QUALIFIER._canonical_file_tree_root(file_records),
            "files": 3,
            "logical_bytes": 60,
            "allocated_bytes_st_blocks_x_512": 1536,
        },
        "tree_allocation": {"allocated_bytes_st_blocks_x_512": 1536},
        "process_io_delta": {"write_bytes": 100},
        "rusage_output_blocks_delta": 100,
        "storage_device": {"classification": "non-rotational-block"},
    }
    generation_roots = {
        "candidate_generation": "generation-root",
        "published_manifest_generation": "generation-root",
        "published_head_generation": "generation-root",
        "current_before_generation": "generation-root",
        "recovered_generation": "generation-root",
        "stable_generation": "generation-root",
        "current_after_generation": "generation-root",
        "lease_generation": "generation-root",
        "published_head": "head-root",
        "current_before_head": "head-root",
        "recovered_head": "head-root",
        "stable_head": "head-root",
        "current_after_head": "head-root",
    }
    generation = {
        "generation_root": "generation-root",
        "head_root": "head-root",
        "roots": generation_roots,
        "first_recovery_repaired": True,
        "second_recovery_repaired": False,
        "source_sha256": "source-root",
        "offsets_sha256": "offsets-root",
        "offsets_value_little_endian": 14,
        "payload_readback": {
            "records": [
                {"name": "offsets", "size": 8, "sha256": "offsets-root"},
                {"name": "source", "size": 14, "sha256": "source-root"},
            ],
            "root_sha256": "readback-root",
        },
        "mutations": {
            "source_generation_root": "source-mutant-root",
            "offsets_generation_root": "offsets-mutant-root",
            "payload_content_roots": {
                "base": {"source": "source-root", "offsets": "offsets-root"},
                "source_mutant": {"source": "source-mutant", "offsets": "offsets-root"},
                "offsets_mutant": {"source": "source-root", "offsets": "offsets-mutant"},
            },
        },
        "tree_allocation": {"allocated_bytes_st_blocks_x_512": 100},
        "process_io_delta": {"write_bytes": 100},
        "rusage_output_blocks_delta": 100,
    }
    sentinels: dict[str, object] = {}
    builds: dict[str, object] = {}
    for label in ("baseline", "allocator-only", "candidate"):
        native_hash = "native-baseline" if label == "baseline" else "native-patch"
        wrapper_hash = "wrapper-candidate" if label == "candidate" else "wrapper-baseline"
        current_allocator = json.loads(json.dumps(allocator))
        current_allocator["automatic_scan_present"] = label == "baseline"
        sentinels[label] = {
            "source_identity": {
                "native_source_sha256": native_hash,
                "wrapper_source_sha256": wrapper_hash,
                "extension_sha256": f"extension-{label}",
            },
            "allocator": current_allocator,
            "persistence": json.loads(json.dumps(persistence)),
            "generation": json.loads(json.dumps(generation)),
        }
        builds[label] = {
            "native_source_sha256": native_hash,
            "wrapper_source_sha256": wrapper_hash,
            "extension_sha256": f"extension-{label}",
            "actual_native_compile_command": "cc -O3 -c src/staqtapp_tds/_native_index.c",
            "actual_native_link_command": "cc -shared native.o -o _native_index.so",
        }
    return sentinels, builds


def test_sentinel_hash_and_physical_writes_are_decision_gates() -> None:
    sentinels, builds = _sentinel_fixture()
    binding = {"native_index_diff_sha256": QUALIFIER.NATIVE_SOURCE_DIFF_SHA256}
    passing = QUALIFIER._sentinel_global_checks(sentinels, binding, builds)
    assert all(check["passed"] for check in passing)

    sentinels["candidate"]["persistence"]["process_io_delta"]["write_bytes"] = 106
    failing = QUALIFIER._sentinel_global_checks(sentinels, binding, builds)
    by_name = {check["name"]: check for check in failing}
    assert by_name["persistence_process_write_bytes_candidate_over_baseline"]["passed"] is False
    sentinels["candidate"]["persistence"]["file_tree"]["records"][1]["sha256"] = "different"
    failing = QUALIFIER._sentinel_global_checks(sentinels, binding, builds)
    by_name = {check["name"]: check for check in failing}
    assert by_name["persistence_file_tree_self_hash"]["passed"] is False


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        ("generation-root", "generation_root_exact"),
        ("recovered-head", "generation_published_recovered_identity"),
        ("offset-readback", "generation_source_offsets_readback"),
        ("mutation-sensitivity", "generation_mutation_sensitivity"),
        ("persistence-tree", "persistence_file_tree_exact"),
        ("restored-order", "persistence_restored_order_handles_high_water"),
        ("restored-handle", "persistence_restored_order_handles_high_water"),
        ("restored-high-water", "persistence_restored_order_handles_high_water"),
    ),
)
def test_generation_and_persistence_mutations_fail_exact_gate(
    mutation: str,
    failed_check: str,
) -> None:
    sentinels, builds = _sentinel_fixture()
    candidate = sentinels["candidate"]
    if mutation == "generation-root":
        candidate["generation"]["generation_root"] = "changed-generation"
    elif mutation == "recovered-head":
        candidate["generation"]["roots"]["recovered_head"] = "changed-head"
    elif mutation == "offset-readback":
        candidate["generation"]["payload_readback"]["root_sha256"] = "changed-readback"
    elif mutation == "mutation-sensitivity":
        candidate["generation"]["mutations"]["source_generation_root"] = candidate["generation"]["generation_root"]
    elif mutation == "persistence-tree":
        records = candidate["persistence"]["file_tree"]["records"]
        records[1]["sha256"] = "changed-but-self-consistent"
        candidate["persistence"]["file_tree"]["tree_root_sha256"] = QUALIFIER._canonical_file_tree_root(records)
    elif mutation == "restored-order":
        candidate["persistence"]["restored_semantics"]["serialized_keys"].reverse()
    elif mutation == "restored-handle":
        candidate["persistence"]["restored_semantics"]["restored_before_insert"]["handles"][1] = 99
    else:
        candidate["persistence"]["restored_semantics"]["restored_after_insert"]["next_handle"] = 99
    checks = QUALIFIER._sentinel_global_checks(
        sentinels,
        {"native_index_diff_sha256": QUALIFIER.NATIVE_SOURCE_DIFF_SHA256},
        builds,
    )
    assert {check["name"] for check in checks if not check["passed"]} >= {failed_check}


def test_v1_samples_are_rejected_before_release_math() -> None:
    with pytest.raises(RuntimeError, match="rejects non-v2"):
        QUALIFIER._validate_v2_records(
            [{"schema": 1, "benchmark_id": "native-handle-allocator-release-sample-v1"}]
        )


def _strict_record_fixture(tmp_path: Path) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    worker_path = (tmp_path / "native_allocator_release_sample.py").resolve()
    worker_path.write_text("# immutable worker\n", encoding="utf-8")
    topology = {
        "allowed_cpu_ids": [8, 9],
        "logical_cpu_topology": {
            "8": {"package_id": 0, "core_id": 8},
            "9": {"package_id": 0, "core_id": 9},
        },
        "physical_core_groups": {
            "package-0/core-8": [8],
            "package-0/core-9": [9],
        },
        "representative_cpu_ids": [8, 9],
        "topology_sha256": "topology-sha",
        "allowed_physical_core_count": 2,
        "effective_physical_core_count": 2,
        "multi_threads": 2,
        "single_cpu_ids": [9],
        "multi_cpu_ids": [8, 9],
        "cpu_max": {
            "source": "/sys/fs/cgroup/cpu.max",
            "raw": "max 100000",
            "quota_usec": None,
            "period_usec": 100000,
            "quota_cores": None,
        },
    }
    cell = {
        "id": "full-tds-shipped-normal-50000-t1",
        "comparison_id": "baseline-vs-candidate",
        "path": "full-tds",
        "diagnostics": "off",
        "telemetry": "normal",
        "entries": 50_000,
        "threads": 1,
        "role": "release-primary-shipped",
        "comparison": ["baseline", "candidate"],
    }
    sources = {
        label: {
            "label": label,
            "reference": label,
            "commit": f"{label}-commit",
            "tree": f"{label}-tree",
        }
        for label in ("baseline", "candidate")
    }
    builds: dict[str, dict[str, object]] = {}
    for label in ("baseline", "candidate"):
        source_root = (tmp_path / label).resolve()
        build = {
            "schema": 2,
            "source": sources[label],
            "command": ["python", "setup.py", "build_ext"],
            "actual_native_compile_command": "cc -O3 -c src/staqtapp_tds/_native_index.c",
            "actual_native_link_command": "cc -shared native.o -o _native_index.so",
            "native_source_sha256": f"native-{label}",
            "wrapper_source_sha256": f"wrapper-{label}",
            "extension_name": "_native_index.test.so",
            "extension_sha256": f"extension-{label}",
            "path": str((tmp_path / f"{label}-build.json").resolve()),
            "source_root": str(source_root),
        }
        builds[label] = build
    protocol = {
        "schema": 2,
        "run_id": "strict-run",
        "seed": 1234,
        "measured_pairs": 7,
        "warmup_pairs_excluded": 2,
        "expected_worker_processes": 18,
        "worker_path": str(worker_path),
        "worker_sha256": hashlib.sha256(worker_path.read_bytes()).hexdigest(),
        "effective_cpu_topology": topology,
        "sources": sources,
        "cells": [cell],
    }
    records: list[dict[str, object]] = []
    for phase, orders in (("warmup", ["AB", "BA"]), ("measured", ["AB", "BA", "AB", "BA", "AB", "BA", "AB"])):
        for pair_index, order in enumerate(orders):
            labels = cell["comparison"] if order == "AB" else list(reversed(cell["comparison"]))
            lookup_seed = protocol["seed"] ^ (1 << 20) ^ pair_index
            for position, label in enumerate(labels, start=1):
                record = _record(source=label, phase=phase, pair=pair_index, order=order)
                record["run_id"] = protocol["run_id"]
                record["sample"]["order_position"] = position
                record["cell"] = {
                    "id": cell["id"],
                    "comparison_id": cell["comparison_id"],
                    "path": "full-tds",
                    "measurement_role": "release-primary-full-tds-32-byte-raw-binary",
                    "entries": 50_000,
                    "threads": 1,
                    "diagnostics": "off",
                    "telemetry": "normal",
                    "qualification_role": "release-primary-shipped",
                    "value_bytes": 32,
                    "dataset": "sequential-string-keys-exact-32-byte-raw-binary-v2",
                    "lookup": "one-million-or-more-hot-lookups-over-deterministically-shuffled-existing-keys",
                    "lookup_unique_keys": 50_000,
                    "lookup_operations": 1_000_000,
                    "lookup_seed": lookup_seed,
                }
                build = builds[label]
                source = sources[label]
                record["source_identity"] = {
                    "label": label,
                    "git_commit": source["commit"],
                    "git_tree": source["tree"],
                    "tds_version": "3.8.1" if label == "baseline" else "3.8.2",
                    "package_path": str(Path(build["source_root"]) / "src" / "staqtapp_tds" / "__init__.py"),
                    "native_source_sha256": build["native_source_sha256"],
                    "wrapper_source_sha256": build["wrapper_source_sha256"],
                    "extension_path": str(Path(build["source_root"]) / "src" / "staqtapp_tds" / build["extension_name"]),
                    "extension_sha256": build["extension_sha256"],
                    "selected_backend": QUALIFIER.EXPECTED_BACKEND,
                    "expected_backend": QUALIFIER.EXPECTED_BACKEND,
                }
                record["build_provenance"] = {
                    key: value for key, value in build.items()
                    if key not in {"path", "source_root"}
                }
                record["harness_identity"] = {
                    "script_path": str(worker_path),
                    "script_sha256": protocol["worker_sha256"],
                }
                record["runtime_identity"].update({
                    "admitted_cpu_affinity_before_pin": [8, 9],
                    "cpu_affinity": [9],
                    "admitted_topology": {"topology_sha256": "topology-sha"},
                })
                for measurement_set in (
                    record["measurements"],
                    record["dedicated_latency"]["measurements"],
                ):
                    for phase_name in ("insertion", "lookup_control"):
                        measurement_set[phase_name]["actual_cpu_ids"] = [9]
                record["orchestrator_command"] = QUALIFIER._worker_command(
                    run_id=protocol["run_id"],
                    source=source,
                    cell=cell,
                    phase=phase,
                    pair_index=pair_index,
                    order=order,
                    order_position=position,
                    lookup_seed=lookup_seed,
                    build=build,
                    worker_path=worker_path,
                    topology=topology,
                )
                records.append(record)
    return records, protocol, builds


def test_strict_retained_validator_binds_schedule_source_build_link_and_topology(
    tmp_path: Path,
) -> None:
    records, protocol, builds = _strict_record_fixture(tmp_path)
    result = QUALIFIER._validate_retained_records(records, protocol=protocol, builds=builds)
    assert result["validated"] is True and result["records"] == 18
    assert result["cells"]["full-tds-shipped-normal-50000-t1"]["measured_order_counts"] == {
        "AB": 4,
        "BA": 3,
    }

    records[0]["source_identity"]["extension_sha256"] = "wrong-extension"
    with pytest.raises(RuntimeError, match="source/extension identity"):
        QUALIFIER._validate_retained_records(records, protocol=protocol, builds=builds)


def test_strict_retained_validator_rejects_link_seed_order_and_extra_records(
    tmp_path: Path,
) -> None:
    for mutation, expected in (
        ("link", "build provenance"),
        ("seed", "cell parameters"),
        ("order", "source order"),
        ("extra", "cardinality"),
    ):
        records, protocol, builds = _strict_record_fixture(tmp_path / mutation)
        if mutation == "link":
            records[0]["build_provenance"]["actual_native_link_command"] = "cc wrong-link"
        elif mutation == "seed":
            records[0]["cell"]["lookup_seed"] += 1
        elif mutation == "order":
            records[0]["sample"]["order"] = "BA"
            records[1]["sample"]["order"] = "BA"
        else:
            records.append(json.loads(json.dumps(records[-1])))
        with pytest.raises(RuntimeError, match=expected):
            QUALIFIER._validate_retained_records(records, protocol=protocol, builds=builds)


def test_effective_topology_uses_allowed_physical_cores_and_quota_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(QUALIFIER.os, "sched_getaffinity", lambda _pid: {0, 1, 2, 3})
    original_read_text = QUALIFIER.Path.read_text

    def topology_read(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "physical_package_id":
            return "0"
        if path.name == "core_id":
            cpu = int(path.parent.parent.name.removeprefix("cpu"))
            return str(cpu // 2)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(QUALIFIER.Path, "read_text", topology_read)
    monkeypatch.setattr(
        QUALIFIER,
        "_cpu_max",
        lambda: {
            "source": "/sys/fs/cgroup/cpu.max",
            "raw": "200000 100000",
            "quota_usec": 200000,
            "period_usec": 100000,
            "quota_cores": 2.0,
        },
    )
    topology = QUALIFIER._effective_cpu_topology()
    assert topology["representative_cpu_ids"] == [1, 3]
    assert topology["multi_cpu_ids"] == [1, 3]
    assert topology["multi_threads"] == 2
    assert QUALIFIER._affinity_for(2, topology) == "1,3"

    monkeypatch.setattr(
        QUALIFIER,
        "_cpu_max",
        lambda: {
            "source": "/sys/fs/cgroup/cpu.max",
            "raw": "100000 100000",
            "quota_usec": 100000,
            "period_usec": 100000,
            "quota_cores": 1.0,
        },
    )
    with pytest.raises(RuntimeError, match="at least two"):
        QUALIFIER._effective_cpu_topology()


def test_thermal_one_sided_unavailable_and_ceiling_fail_closed() -> None:
    record = {
        "host_before": {
            "thermal_celsius": {"sensor": 80.0},
            "thermal_source": "thermal-source",
        },
        "host_after": {"thermal_celsius": None, "thermal_source": "thermal-source"},
    }
    assert QUALIFIER._thermal_evidence(record)["clean"] is False
    record["host_after"]["thermal_celsius"] = {"sensor": 91.0}
    assert QUALIFIER._thermal_evidence(record)["clean"] is False
    record["host_after"]["thermal_celsius"] = {"sensor": 85.0}
    assert QUALIFIER._thermal_evidence(record)["clean"] is True


def test_every_gated_baseline_metric_requires_cv_and_per_sample_five_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        QUALIFIER,
        "_bootstrap_median_ci",
        lambda values, **_kwargs: [statistics.median(values), statistics.median(values)],
    )
    records = _records(target_latency=1.20)
    baseline_outlier = next(
        record for record in records
        if record["sample"]["phase"] == "measured"
        and record["sample"]["pair_index"] == 6
        and record["sample"]["source_label"] == "baseline"
    )
    baseline_outlier["dedicated_latency"]["operation_samples"]["lookup_ns"] = [120.0] * 16
    baseline_outlier["measurements"]["whole_workload_rss"]["peak_bytes"] = 1_200_000
    cell = {
        "id": "full-tds-shipped-normal-50000-t1",
        "comparison_id": "baseline-vs-candidate",
        "path": "full-tds",
        "diagnostics": "off",
        "telemetry": "normal",
        "entries": 50_000,
        "threads": 1,
        "role": "release-primary-shipped",
        "comparison": ["baseline", "candidate"],
    }
    summary = QUALIFIER._summarize_cell(cell, records, expected_pairs=7, bootstrap_seed=1)
    assert summary["measurement_valid"] is False
    assert summary["baseline_metric_stability"]["lookup_p99_operation_latency"]["stable"] is False
    assert summary["baseline_metric_stability"]["whole_workload_peak_rss"]["stable"] is False
    failed_latency = next(
        check for check in summary["checks"]
        if check["name"] == "lookup_p99_latency_ci_upper"
    )
    assert failed_latency["passed"] is False
    assert failed_latency["kind"] == "performance"
    assert failed_latency["decisional"] is False


def test_release_job_leaves_upload_margin_around_runner() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    job = workflow.split("native-handle-allocator-release-qualification:", 1)[1]
    job = job.split("\n  native-architecture-semantic-evidence:", 1)[0]
    assert "timeout-minutes: 330" in job
    assert "timeout --signal=TERM --kill-after=30s 300m" in job
    assert "if: always()" in job

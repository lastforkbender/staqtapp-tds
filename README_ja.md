# Staqtapp-TDS v3.5.3.post1

> **PyPI presentation correction:** v3.5.3.post1 は qualified v3.5.3 storage
> behavior を保持し、PyPI page の image/document link と obsolete
> pre-publication status を修正する corrective post-release です。

**Temporal Directory System - AI システム向けの native-indexed `.tds` ストレージ、変数制御、トレース順位付け、CSV evidence 操作、semantic review、集中型 observability。**

**プログラマー向けの最初の資料:** [Staqtapp-TDS Programmer Core API Guide (PDF)](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf)

## Browser Operations Console — 全 19 ページ

以下は packaged local-only TDS Browser から取得した、個別の 1280×800 viewport capture 19 枚です。Release qualification 用の実データ observer snapshot に対して、各 navigation control を選択してから capture しました。07 は `Monitor Ready` 状態の実際の CSV Interpole Monitor です。Dashboard の結合画像や UI mock ではなく、Browser の navigation 順に縦並びで表示しています。

<p align="center"><strong>01 — Dashboard</strong><br>
  <img src="docs/screenshots/browser_pages/01-dashboard-1280x800.png" alt="Staqtapp-TDS Browser 01、navigation で選択された Dashboard" width="100%">
</p>
<p align="center"><strong>02 — Engine Health</strong><br>
  <img src="docs/screenshots/browser_pages/02-engine-health-1280x800.png" alt="Staqtapp-TDS Browser 02、navigation で選択された Engine Health" width="100%">
</p>
<p align="center"><strong>03 — Real-time Metrics</strong><br>
  <img src="docs/screenshots/browser_pages/03-real-time-metrics-1280x800.png" alt="Staqtapp-TDS Browser 03、navigation で選択された Real-time Metrics" width="100%">
</p>
<p align="center"><strong>04 — Transition Timeline</strong><br>
  <img src="docs/screenshots/browser_pages/04-transition-timeline-1280x800.png" alt="Staqtapp-TDS Browser 04、navigation で選択された Transition Timeline" width="100%">
</p>
<p align="center"><strong>05 — Event Ring Monitor</strong><br>
  <img src="docs/screenshots/browser_pages/05-event-ring-monitor-1280x800.png" alt="Staqtapp-TDS Browser 05、navigation で選択された Event Ring Monitor" width="100%">
</p>
<p align="center"><strong>06 — Pressure Diagnostics</strong><br>
  <img src="docs/screenshots/browser_pages/06-pressure-diagnostics-1280x800.png" alt="Staqtapp-TDS Browser 06、navigation で選択された Pressure Diagnostics" width="100%">
</p>
<p align="center"><strong>07 — CSV Interpole</strong><br>
  <img src="docs/screenshots/browser_pages/07-csv-interpole-1280x800.png" alt="Staqtapp-TDS Browser 07、Monitor Ready 状態で navigation から選択された実際の CSV Interpole Monitor" width="100%">
</p>
<p align="center"><strong>08 — Snapshot Explorer</strong><br>
  <img src="docs/screenshots/browser_pages/08-snapshot-explorer-1280x800.png" alt="Staqtapp-TDS Browser 08、navigation で選択された Snapshot Explorer" width="100%">
</p>
<p align="center"><strong>09 — Lock Contention</strong><br>
  <img src="docs/screenshots/browser_pages/09-lock-contention-1280x800.png" alt="Staqtapp-TDS Browser 09、navigation で選択された Lock Contention" width="100%">
</p>
<p align="center"><strong>10 — Workload Analytics</strong><br>
  <img src="docs/screenshots/browser_pages/10-workload-analytics-1280x800.png" alt="Staqtapp-TDS Browser 10、navigation で選択された Workload Analytics" width="100%">
</p>
<p align="center"><strong>11 — Spiral Rank</strong><br>
  <img src="docs/screenshots/browser_pages/11-spiral-rank-1280x800.png" alt="Staqtapp-TDS Browser 11、navigation で選択された Spiral Rank" width="100%">
</p>
<p align="center"><strong>12 — Index Analytics</strong><br>
  <img src="docs/screenshots/browser_pages/12-index-analytics-1280x800.png" alt="Staqtapp-TDS Browser 12、navigation で選択された Index Analytics" width="100%">
</p>
<p align="center"><strong>13 — Storage Analytics</strong><br>
  <img src="docs/screenshots/browser_pages/13-storage-analytics-1280x800.png" alt="Staqtapp-TDS Browser 13、navigation で選択された Storage Analytics" width="100%">
</p>
<p align="center"><strong>14 — Comparative Views</strong><br>
  <img src="docs/screenshots/browser_pages/14-comparative-views-1280x800.png" alt="Staqtapp-TDS Browser 14、navigation で選択された Comparative Views" width="100%">
</p>
<p align="center"><strong>15 — Recovery Planner</strong><br>
  <img src="docs/screenshots/browser_pages/15-recovery-planner-1280x800.png" alt="Staqtapp-TDS Browser 15、navigation で選択された Recovery Planner" width="100%">
</p>
<p align="center"><strong>16 — Policy Proposals</strong><br>
  <img src="docs/screenshots/browser_pages/16-policy-proposals-1280x800.png" alt="Staqtapp-TDS Browser 16、navigation で選択された Policy Proposals" width="100%">
</p>
<p align="center"><strong>17 — Alerts &amp; Events</strong><br>
  <img src="docs/screenshots/browser_pages/17-alerts-events-1280x800.png" alt="Staqtapp-TDS Browser 17、navigation で選択された Alerts and Events" width="100%">
</p>
<p align="center"><strong>18 — Security</strong><br>
  <img src="docs/screenshots/browser_pages/18-security-1280x800.png" alt="Staqtapp-TDS Browser 18、navigation で選択された Security" width="100%">
</p>
<p align="center"><strong>19 — Settings</strong><br>
  <img src="docs/screenshots/browser_pages/19-settings-1280x800.png" alt="Staqtapp-TDS Browser 19、navigation で選択された Settings" width="100%">
</p>

[English README](README.md) | [Complete API Surface Reference PDF](tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) | [Changelog](CHANGELOG.md)

## TDS が提供するもの

Staqtapp-TDS は AI アプリケーション向けの directory-first storage / operations layer です。Python value、text、JSON、binary payload、trace evidence、driver evidence、管理対象 CSV artifact を階層化された in-memory directory に保持し、その状態を `.tds` file へ flush、または `.tds` file から mount できます。

TDS は storage hot path を狭く保つ設計です。Native index、lookup、persistence、optional CSV scan kernel は、diagnostics、Browser rendering、Driver Studio、Semantic IR review、policy-facing evidence workflow から分離されています。

## 現在の主な利点

| Capability | 実装上の利点 |
|---|---|
| `.tds` persistence | Atomic file replacement、mmap random access、sidecar integrity metadata、mounted-reader lifecycle、deterministic directory snapshot。 |
| 直接的な変数制御 | 別の application database API を作らずに、add、edit、lock、unlock、find、load、stalk chain append を実行できます。 |
| Non-halting result model | Result-first call は `TDSResult` を返し、安定した code、message、value、metadata により AI runtime の通常エラーを停止に直結させません。 |
| Native-indexed storage | Optional compiled index/checksum path、deterministic Python fallback、明示的な native capability report。 |
| Trace ranking | Confidence、depth、age、top-N、statistics、native/Python parity を持つ deterministic Spiral-compatible ranking。 |
| CSV Suite | Original-byte preservation、dialect evidence、logical row offset、row anchor、scan parity、artifact transaction、storage binding、native scan evidence、Interpole telemetry、Semantic IR candidate、lifecycle transition、atomic batch review。 |
| Evidence-bound semantics | Caller が明示した declaration と承認済み review transition を記録し、semantic truth を自動推論または自動 commit しません。 |
| Driver platform | TDDL validation、deterministic bytecode、bounded Driver VM、Foundry proposal/test、regression evidence、review bundle、read-only Studio integration。 |
| 集中型 Browser | Engine health、pressure、event ring、CSV Interpole、Spiral Rank、snapshot、index、storage、recovery、alert、security、settings を 1 つの local Browser で表示します。 |
| Observer isolation | Browser、telemetry、diagnostics、Studio は snapshot または copied event を利用し、storage lock を制御しません。 |

## インストール

```bash
# Production PyPI corrective release
python -m pip install staqtapp-tds==3.5.3.post1

# Source checkout
python -m pip install .

# Optional PyQt5 Driver Studio
python -m pip install "staqtapp-tds[gui]==3.5.3.post1"
```

Python 3.10 以上と NumPy が必要です。C extension は optional です。Caller が native-only を明示的に強制しない限り、対応する operation には deterministic Python fallback があります。

## Core storage quick start

```python
from pathlib import Path
from staqtapp_tds import TDSFileSystem, TDSPersistence

fs = TDSFileSystem("agent_state")
models = fs.makedirs("/models/runtime")

models.write_text("system_prompt", "You are a careful planning agent.")
models.write_json("settings", {"temperature": 0.2, "tools": True})
models.write_result("step_count", 7)

result = models.read_result("settings")
if result.ok:
    settings = result.value

store = TDSPersistence(Path("./tds_store"))
store.flush(fs, parallel_nodes=False)
loaded_runtime = store.load_node(
    Path("./tds_store/agent_state__models__runtime.tds")
)
assert loaded_runtime.read_value("step_count") == 7
```

## 変数操作 quick start

```python
state = fs.makedirs("/agent/state")

state.addvar("reward", 1.0)
state.editvar("reward", 1.25)
state.lockvar("reward")

found = state.findvar("reward")
assert found.ok and found.value == 1.25

state.unlockvar("reward")
state.addvar("context", ["initial"])
state.stalkvar("~context", ["observation-1"])
state.stalkvar("~context", ["observation-2"])
latest_context = state.loadvar("context_0002")
```

## Trace ranking quick start

```python
from staqtapp_tds.spiral import rank_traces

ranked = rank_traces(
    ["trace-a", "trace-b", "trace-c"],
    [0.82, 0.95, 0.95],
    confidences=[0.90, 0.92, 0.92],
    depths=[2, 3, 1],
    limit=2,
)

for record in ranked:
    print(record.rank, record.trace_id, record.rank_score)
```

## CSV quick start

```python
from staqtapp_tds.csv_layer import (
    export_original_csv,
    import_csv_bytes,
    prove_original_roundtrip,
    validate_csv_artifacts,
)

csv_dir = fs.makedirs("/datasets")
manifest = import_csv_bytes(
    csv_dir,
    b"id,name,score\n1,Ada,99\n2,Grace,98\n",
    source_name="people.csv",
)

validation = validate_csv_artifacts(csv_dir, manifest.csv_id)
assert validation.ok
assert export_original_csv(csv_dir, manifest.csv_id).startswith("id,name")
assert prove_original_roundtrip(csv_dir, manifest.csv_id).byte_equivalent
```

CSV layer は source と derived evidence を bounded TDS artifact として保存します。Cell ごとの TDS entry は作成せず、native storage engine を CSV parser や semantic reasoner にしません。

## 集中型 Browser

```bash
staqtapp-tds-admin status
staqtapp-tds-admin verify --sample
staqtapp-tds-admin serve-panel --host 127.0.0.1 --port 8765
```

`http://127.0.0.1:8765/` を開きます。Browser は default で local-only です。Configuration action には same-origin と CSRF check が必要で、refresh ごとに storage structure を walk せず cached status snapshot を読みます。

## Architecture boundary

```text
AI application / service
        |
        +-- TDSResult-first storage and variable calls
        +-- trace ranking and provenance
        +-- CSV evidence and Semantic IR review
        +-- Driver Foundry / Runtime Manager / Studio
        |
        v
Python TDS orchestration layer
        |
        +-- immutable snapshots and copied diagnostics --> centralized Browser
        |
        v
native index / optional CSV kernels / .tds persistence
```

Native storage は限定された mechanical work を担当します。Diagnostics、Semantic IR、Driver Studio、Browser rendering は native storage lock を制御しません。

## Programmer documentation

[Programmer Core API Guide](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf) を最初に参照してください。最初の 3 page は controlled activation、segment GC、release qualification の authoritative v3.5.3 supplement です。その後の broad guide は Task ごとに direct call を整理し、次の実装 snippet を含みます。

- directory / entry operation;
- `.tds` write、read、mount、integrity behavior;
- variable manipulation と stalk chain;
- text、JSON、serialization、provenance、result handling;
- telemetry、verification、pressure、recovery、native diagnostics;
- trace creation と ranking;
- complete operational CSV call chain;
- Semantic IR candidate、lifecycle transition、atomic batch;
- Driver Foundry、VM、Runtime Manager、regression、review、evidence、Browser、Driver Studio call。

新しい storage call には current [v3.5.3 Guaranteed Storage API reference](docs/reference/Programmers_API_Reference.md) を使用してください。別の [API Surface Reference PDF](tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) は historical v3.1.23 Driver/Studio reference として保持されていますが、v3.5.3 の exhaustive inventory ではありません。

## Safety / authority boundary

TDS は preparation、evidence、review、authority を明確に分離します。

- CSV Semantic IR call は semantic truth を自動宣言しません。
- v3.5.2 が許可する state は `proposed`、`validated`、`contested` です。`committed` と `superseded` は許可しません。
- Driver Foundry は validate、compile、audit、test、candidate submit を行えますが、sign または activate は行いません。
- Driver Studio は observe、explain、proposal preparation、review request routing を行いますが、Registry、Review Board、Runtime Manager、signature policy を bypass しません。
- Browser telemetry は snapshot-based であり storage control loop ではありません。

## Validation status

v3.5.3 runtime release qualification は完了しています。

- Phase 10 controlled activation、exact migration proof、lossless rollback test;
- Phase 11 GC corruption、publication-window、replacement、interruption、concurrency、accounting test;
- 129-generation incremental/recovery/GC soak;
- Python 3.10–3.14、Windows、macOS、Linux、native-extension CI gate;
- PEP 517 wheel/sdist、metadata、isolated install、source-hygiene gate。

Evidence: pure monolithic suite は 832 passed / 11 skipped、native-active monolithic suite は 843 passed、重複する v3.5.3/workflow/Browser/CSV qualification group は 157 passed です。両 distribution artifact は `twine check`、archive content inspection、isolated wheel activation/rollback/GC smoke test に合格しました。Pull request、merged `main`、annotated `v3.5.3` tag の matrix はすべて green となり、v3.5.3 は 2026-07-16 に PyPI trusted publishing で公開されました。正確な run、artifact hash、publication response は `DEV11_RELEASE_QUALIFICATION_STATUS.txt` に記録しています。

v3.5.3.post1 は PyPI long description と source archive の presentation を修正します。すべての PyPI-facing target は absolute HTTPS URL であり、release hygiene は relative image/document target を distribution build 前に拒否します。Publication は complete aggregate release gate 通過後の exact annotated `v3.5.3.post1` tag に限定されます。

## Repository map

```text
src/staqtapp_tds/          core storage, persistence, telemetry, native management
src/staqtapp_tds/csv_layer CSV evidence, transactions, Interpole, Semantic IR
src/staqtapp_tds/drivers/  TDDL, bytecode, VM, Foundry, review and evidence
src/staqtapp_tds/studio_pyqt5/ optional Driver Studio cockpit
src/staqtapp_tds/admin/    centralized Browser and local admin control
examples/                  runnable examples
docs/                      architecture and release contract documents
tds_api_docs/              programmer guide と historical API-surface PDF
```

## License

[LICENSE](LICENSE) を参照してください。

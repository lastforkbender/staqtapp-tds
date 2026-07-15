# Staqtapp-TDS v3.5.2

**Temporal Directory System - AI システム向けの native-indexed `.tds` ストレージ、変数制御、トレース順位付け、CSV evidence 操作、semantic review、集中型 observability。**

**プログラマー向けの最初の資料:** [Staqtapp-TDS Programmer Core API Guide (PDF)](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf)

<p align="center">
  <img src="docs/screenshots/tds_browser_telemetry_overview_1280x800.png" alt="Staqtapp-TDS Browser の全 19 ページを個別に表示し、07 番目に CSV Interpole Monitor を表示" width="100%">
</p>

<p align="center"><em>Browser Operations Console - 集中型 Browser の全 19 navigation page を個別に capture し、縦方向に配置しています。Page 07 では、CSV Interpole が選択され、データが設定された CSV Interpole Monitor を明確に確認できます。</em></p>

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
python -m pip install .

# Optional PyQt5 Driver Studio
python -m pip install ".[gui]"
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

新しい [Programmer Core API Guide](tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf) を最初に参照してください。Task ごとに direct call を整理し、次の実装 snippet を含みます。

- directory / entry operation;
- `.tds` write、read、mount、integrity behavior;
- variable manipulation と stalk chain;
- text、JSON、serialization、provenance、result handling;
- telemetry、verification、pressure、recovery、native diagnostics;
- trace creation と ranking;
- complete operational CSV call chain;
- Semantic IR candidate、lifecycle transition、atomic batch;
- Driver Foundry、VM、Runtime Manager、regression、review、evidence、Browser、Driver Studio call。

[API Surface Reference](tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf) は class-by-class の広範な確認用として引き続き利用できます。

## Safety / authority boundary

TDS は preparation、evidence、review、authority を明確に分離します。

- CSV Semantic IR call は semantic truth を自動宣言しません。
- v3.5.2 が許可する state は `proposed`、`validated`、`contested` です。`committed` と `superseded` は許可しません。
- Driver Foundry は validate、compile、audit、test、candidate submit を行えますが、sign または activate は行いません。
- Driver Studio は observe、explain、proposal preparation、review request routing を行いますが、Registry、Review Board、Runtime Manager、signature policy を bypass しません。
- Browser telemetry は snapshot-based であり storage control loop ではありません。

## Validation status

v3.5.2 delivery baseline の検証結果:

- fallback/source: 683 passed、native-only 11 skipped;
- 両方の C extension build: 694 passed;
- packaged Semantic IR: 61 passed;
- fresh archive release check と packaged native build: passed;
- source archive に compiled object / cache directory なし。

## Repository map

```text
src/staqtapp_tds/          core storage, persistence, telemetry, native management
src/staqtapp_tds/csv_layer CSV evidence, transactions, Interpole, Semantic IR
src/staqtapp_tds/drivers/  TDDL, bytecode, VM, Foundry, review and evidence
src/staqtapp_tds/studio_pyqt5/ optional Driver Studio cockpit
src/staqtapp_tds/admin/    centralized Browser and local admin control
examples/                  runnable examples
docs/                      architecture and release contract documents
tds_api_docs/              programmer and full API PDFs
```

## License

[LICENSE](LICENSE) を参照してください。

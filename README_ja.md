<p align="center">
    <img src="docs/dashboard-2.7.4.png" alt="Staqtapp-TDS v2.8.1 Dashboard" width="100%"/>
</p>


# 🟦🟪🟧 Staqtapp-TDS v3.1.2

## v3.1.2 Driver Foundry API

TDS v3.1.2 では AI セーフな `DriverFoundry` API を追加しました。これは AI による高速な Driver 生成を支援する build/test/candidate 層ですが、registry trust 権限は与えません。Foundry は TDDL validation、`.tdd` bytecode compile、VM contract audit、`DriverVMRuntime` による test、registry candidate submission を実行できます。一方で approve、sign、activate、policy bypass、storage write、任意 Python 実行はできません。

Class A Foundry 特性:

- AI/Studio 呼び出し側は、想定される source/package/fixture/runtime/policy failure を raw exception ではなく `DriverFoundryResult` として受け取ります。
- Foundry test result は `DriverVMResult` を保持し、repair loop に trace、fault、cost、context、partial output、emitted result evidence を渡します。
- Candidate submission は既定で成功した runtime test evidence を必須とし、driver を `DriverState.CANDIDATE` に入れるだけです。
- Approval、signing、activation、retirement、revocation は Foundry API の外側に残します。
- `foundry_capability_matrix()` は future PyQt5 Studio と AI agent surface に authority boundary を表示します。

## v3.1.1 Driver VM 非停止 Result フレームワーク

TDS v3.1.1 では Driver VM 専用の非停止実行エンベロープ `DriverVMResult` を追加しました。ドライバー実行の失敗はホストプロセスを停止せず、`VMStatus`、`VMFault`、`DriverVMContext`、trace、metrics、partial output として返されます。

Class A 実行特性:

- `execute()` は想定される VM 障害を Python 例外ではなく構造化 Result として返します。
- 正常終了は `VMStatus.HALTED` を返し、互換用の `VMState.EXECUTED` も保持します。
- 不正な入力は `INPUT_REJECTED`、予算超過は `BUDGET_EXCEEDED`、未対応のランタイム意味論は `FAULTED`、想定外の内部エラーは `INTERNAL_ERROR` になります。
- 入力 record snapshot は deep copy され、Driver VM は呼び出し元の入力を変更しません。
- `MATCH field=...` は predicate を必須化し、`regex_limited` と numeric `range` は決定的なランタイム挙動を持ちます。
- Driver VM runtime は storage engine 内部から分離され、その境界を regression test で保護します。

## v3.1.0 Driver VM Runtime

v3.1.0 adds the first deterministic Driver VM runtime for validated `.tdd` bytecode packages. It executes the safe opcode set against explicit in-memory `.tds` record snapshots and remains separate from the Native Storage Engine. Runtime loading remains fail-closed through bytecode hash, opcode, class, capability and budget validation.

## v3.0.9 Driver Studio Class A Quick Test

TDS v3.0.9 adds a non-GUI Driver Studio readiness path. It models the future Studio as a gated certification workflow: learn, syntax validation, capability checks, bytecode generation, VM audit, VM skeleton load, registry approval, signing and activation. Execution remains disabled; the Studio teaches and orchestrates while Builder/VM/Registry remain authoritative.

🇯🇵 **日本語** | 🇺🇸 [English](README.md)

## v3.0.9 TDDL Grammar Validation

TDS v3.0.9 adds a non-executing TDS Driver Language grammar and validation layer for future Driver VM, Builder, Registry and Studio work. It validates SCAN/READ/MATCH/EXTRACT/SCORE/EMIT/HALT behavior, rejects unsafe adapter names and path escapes, requires declared capabilities/adapters, and exposes an instruction metadata table for a future minimal syntax editor.

This release still does not execute driver programs; it prepares a stable, tested syntax boundary before native Driver VM bytecode is introduced.


Staqtapp-TDS は、ディレクトリ中心の Temporal Directory System です。仮想ストレージ、radix ルーティング、Swiss-table 風インデックス、ネイティブ診断、ブラウザ運用テレメトリ、そして任意の Spiral 互換トレースワークフローを提供します。

基本方針は変わりません。

> TDS は保存、取得、索引化、観測、来歴記録を行います。AI システムの代わりに推論、報酬付け、学習、ポリシー決定の変更は行いません。

## v3.0.2 Native Safety + Dashboard Hotfix

v3.0.2 fixes a critical TinyKeyPool safety issue in `_native_index.c` by enforcing a fixed-capacity pooling invariant for small key buffers. It also fixes the wide-desktop dashboard hero graphic so the AI and TDS nodes no longer overlap. The v3.0.1 Native Engine Manager and release-pipeline architecture remain intact.

## v3.0.1 Native Engine Manager

v3.0.1 では、任意のコンパイル済みネイティブエンジンを一元管理する Native Engine Manager を追加しました。TDS は実行環境を検出し、単一の制御境界からネイティブロードを試み、期待される TDS native ABI を検証し、ケイパビリティ診断を記録し、安全でない場合は Python バックエンドへフォールバックします。

アプリケーション側がバイナリファイル名を選ぶ必要はありません。それはライブラリ側の責任です。

```python
from staqtapp_tds import EntryIndex, native_status_result, native_capabilities_result

idx = EntryIndex(backend="auto")
print(idx.native_status_result().as_dict())
print(native_status_result().as_dict())
print(native_capabilities_result().as_dict())
```

ネイティブ管理診断は `TDSResult` を返し、集中化された result-code registry を使用します。主なコードは `NATIVE_ENGINE_LOADED`, `NATIVE_ENGINE_FALLBACK`, `NATIVE_ENGINE_UNAVAILABLE`, `NATIVE_ENGINE_INCOMPATIBLE`, `NATIVE_ENGINE_LOAD_ERROR`, `NATIVE_MANAGER_OK`, `NATIVE_CAPABILITY_OK` です。

## Non-halting API 契約

公開 AI 向け TDS 操作は、成功／失敗を停止なしで返す必要がある場合に `TDSResult` を使用します。ネイティブ import 失敗、コンパイル済みバイナリ不足、ABI 不一致、フォールバック判断は、呼び出し側を停止せず、構造化された result として報告されます。

Result code の authoritative source:

```text
src/staqtapp_tds/result.py
```

生成済み参照:

```text
docs/TDS_RESULT_CODES.md
docs/TDS_RESULT_CODES.json
```

## 自動リリースパイプラインの土台

v3.0.1 では、release check automation と将来の wheel build scaffold を追加しました。現在の ZIP はクリーンな source archive であり、`.so`, `.pyd`, `.dll`, `.dylib`, `.pyc`, `__pycache__`, `.pytest_cache` は意図的に含みません。プラットフォーム別 wheel とコンパイル済みバイナリは、TDS が公開リリース品質に到達した後の release/distribution 段階に属します。

設計ノート:

- `docs/44_v301_Native_Engine_Manager.md`
- `docs/RELEASE_PIPELINE.md`

## ハイライト

- セマンティックルーティングゾーンと予約名前空間ポリシーを備えたディレクトリ中心 VFS API。
- 利用可能な環境で動作するネイティブ Swiss-table 風 `EntryIndex` バックエンド。
- 損失許容型の Native Diagnostic Event Ring とテレメトリスナップショット。
- Native Spiral Rank スコアリングループ、Python フォールバック、不変の実行統計。
- ブラウザ Operations Console の Spiral Rank ページで、フィードバックテレメトリ、Top-N トレース、タイミング履歴を表示。
- インデックス、チェックサム、チャンクスキャン、ランクスコアリングでの GIL 解放ネイティブ実行。
- 多言語対応の Browser Operations Console とプロ向けテレメトリページ。
- stage / promote / rollback による RuntimeConfig 世代管理。
- 任意の Spiral 互換トレース／来歴ヘルパー。
- CSRF・Origin 保護と安全な DOM 描画を備えたローカル専用ブラウザ管理パネル。

## インストール

```bash
python -m pip install -e .
```

テスト実行:

```bash
pytest -q
```

ローカルブラウザコンソール起動:

```bash
staqtapp-tds-admin panel
```

ヘルス検証:

```bash
staqtapp-tds-admin verify --sample
```

開発・CI 用のネイティブ sanitizer ビルド:

```bash
STAQTAPP_TDS_SANITIZE=address python -m pip install -e .
STAQTAPP_TDS_SANITIZE=undefined python -m pip install -e .
```

## Native Spiral Rank Engine

```python
from staqtapp_tds.spiral import NativeSpiralRankEngine

engine = NativeSpiralRankEngine()
ranked = engine.rank(
    trace_ids=["trace_a", "trace_b", "trace_c"],
    scores=[0.91, 0.80, 0.91],
    confidences=[0.95, 0.90, 0.95],
    depths=[3, 1, 1],
    ages_ns=[0, 0, 0],
)

for result in ranked:
    print(result.rank, result.trace_id, result.score, result.native)
```

スコアモデルは小さく、監査しやすい形にしています。

```text
score = source_score * score_weight
      + confidence * confidence_weight
      - depth * depth_penalty
      - age_ns * age_penalty
```

既定値は `SpiralRankConfig` にあります。Python 側が検証と安定した並べ替えを担当し、ネイティブ拡張は利用可能な場合に数値スコア計算ループを担当します。

テレメトリ向けの可視性が必要な場合は、`rank(...)` ではなく `rank_run(...)` を使います。

```python
run = engine.rank_run(["a", "b", "c"], [0.2, 0.9, 0.5], limit=2)
print(run.stats.to_dict())
```

`SpiralRankStats` は `input_count`、`ranked_count`、`limited_count`、`dropped_by_limit`、ネイティブ／フォールバック経路、elapsed/scoring/sorting/shaping の時間、最小・最大・平均スコア、警告、使用中の config id を記録します。これらは観測用統計であり、ストレージ、ポリシー、スコア制御にはフィードバックされません。

## 任意の Spiral 互換トレースサポート

TDS は、推論システムそのものにならずに Spiral 形式のワークフローデータを保存できます。

```python
from staqtapp_tds import TDSFileSystem, create_spiral_run

fs = TDSFileSystem("root")
run = create_spiral_run(
    fs.root,
    "run_000041",
    problem={"prompt": "example task"},
    problem_id="p_812",
)

run.store_search_trace(
    "trace_0001",
    "candidate trace stored as ordinary TDS data",
    rank_score=0.87,
    rank_source="external_verifier_A",
)

run.create_trace_set("set_0001", ["trace_0001"])
run.store_final("answer.tds", "final answer", derived_from=["trace_0001"])
```

代表的なレイアウト:

```text
/spiral_runs/
  run_000041/
    problem.json
    search_traces/
    trace_sets/
    aggregations/
    final/
    metadata/
```

## テレメトリとダッシュボード境界

テレメトリは一方向で、スナップショット駆動です。ダッシュボードはキャッシュされたテレメトリを読みます。更新のたびにストレージエンジンを走査せず、ブラウザ操作をストレージのホットパスに入れません。

テレメトリレベル:

- `off`
- `minimal`
- `normal`
- `engineering`
- `developer`

## 設計上の境界

```text
Caller / verifier / ranker decides.
TDS stores trace data, metadata, scores, and provenance.
Native rank scoring accelerates copied numeric metadata only.
Dashboard observes immutable snapshots.
```

これにより、TDS は高度な AI ワークフローの下でも有用でありながら、ストレージシステムとしての役割を保ちます。

## リリースノート

v3.0.1 は v2.8.7 の Native Spiral Rank Engine の上に構築されています。不変の Spiral Rank 統計、実行バンドル出力、統計テスト、更新済みの日英ドキュメントを追加し、v2.8.7 のリスト返却型 rank API も維持しています。

追加の v3.0.1 設計ノート: `docs/40_v290_Spiral_Rank_Browser_Telemetry.md`。


## v3.0.9 Driver Foundation Testbed

TDS v3.0.9 は、将来の Native Driver VM と Driver Studio のために、実行を行わないドライバー基盤を追加します。Driver Manifest、Registry 状態、署名ポリシー拒否、決定的な Trace Ranking の契約をテストで固定し、Native Storage Engine は分離されたまま変更しません。


## v3.0.9 TDDL Bytecode Package

v3.0.9 は、将来のネイティブ Driver VM に向けた非実行型のバイトコード成果物レイヤーを追加します。検証済み TDDL は、安定した opcode マップ、定数プール、source hash、package hash を持つ決定的な `BytecodePackage` にコンパイルできます。

このリリースではまだ Driver VM の実行は行いません。

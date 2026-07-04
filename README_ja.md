<p align="center">
    <img src="docs/dashboard-2.7.4.png" alt="Staqtapp-TDS v2.8.1 Dashboard" width="100%"/>
</p>


🟦🟪🟧 Staqtapp-TDS v2.9.0

🇯🇵 **日本語** | 🇺🇸 [English](README.md)

Staqtapp-TDS は、ディレクトリ中心の Temporal Directory System です。仮想ストレージ、radix ルーティング、Swiss-table 風インデックス、ネイティブ診断、ブラウザ運用テレメトリ、そして任意の Spiral 互換トレースワークフローを提供します。

基本方針は変わりません。

> TDS は保存、取得、索引化、観測、来歴記録を行います。AI システムの代わりに推論、報酬付け、学習、ポリシー決定の変更は行いません。

## v2.9.0 の主な変更
## v2.9.0 JSON パフォーマンスコーデック

v2.9.0 では、集中化済みの JSON 境界を高性能コーデックへ強化しました。任意依存の `simdjson` と `orjson` は一度だけ検出され、標準ライブラリへの安全なフォールバックを維持します。ブラウザの `status.json` はコンパクト出力となり、loads/dumps 回数、バックエンド使用状況、経過ナノ秒、フォールオーバーを統計として確認できます。

設計ノート: `docs/41_v290_JSON_Performance_Codec.md`.


v2.9.0 では Spiral Rank の観測ループを完成させました。Native Spiral Rank Engine は引き続きストレージのホットパスから分離され、admin レイヤーが専用の **Spiral Rank** 分析ページへキャッシュ済みブラウザフィードバックテレメトリを公開します。ダッシュボードでは、実行回数、ネイティブ/フォールバック比率、処理時間、スコア範囲、平均スコア、Top-N ランク済みトレース、直近の実行履歴を確認できます。

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

v2.9.0 は v2.8.7 の Native Spiral Rank Engine の上に構築されています。不変の Spiral Rank 統計、実行バンドル出力、統計テスト、更新済みの日英ドキュメントを追加し、v2.8.7 のリスト返却型 rank API も維持しています。

追加の v2.9.0 設計ノート: `docs/40_v290_Spiral_Rank_Browser_Telemetry.md`。

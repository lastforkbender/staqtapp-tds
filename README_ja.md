# 🟦🟪🟧 Staqtapp-TDS v3.1.20

## v3.1.20 Driver Studio Export Integrity Workflow

TDS v3.1.20 では、v3.1.19 の Export / Audit Console の上に Driver Studio Export Integrity Workflow を追加しました。manifest hash と packet hash を再計算し、任意の expected manifest / packet hash と比較し、export checklist を checkpoint として進行表示し、外部 export tooling へ渡すための review-safe readiness gate を生成します。

この Workflow は evidence readiness を verify/explain するだけです。approve、reject、quarantine、sign、activate、Registry mutation、trusted driver execution、storage write、private key storage、Runtime Manager / Foundry / Review Board / Registry policy bypass は行いません。

### v3.1.17 Driver VM Performance Evidence Harness

TDS v3.1.17 では、任意実行の Driver VM Performance Evidence Harness を追加しました。この harness は、現在の Python Driver VM の検索/抽出性能を制御された形で測定し、将来の optional native C Driver VM backend に対する parity target を作ります。

通常の Python driver 実行経路は変更しません。

```text
通常の DriverVMRuntime.execute()
  -> 変更なし
  -> benchmark loop なし
  -> per-record timer hook なし
  -> automatic profiling なし

明示的な DriverVMPerformanceHarness.run_package(...)
  -> controlled repetitions
  -> direct Python VM timing
  -> optional Runtime Manager timing
  -> optional native C backend slot
  -> parity/performance evidence report
```

## 現在の検証状態

```text
367 passed, 11 skipped
release check passed
```

## v3.1.20 の追加要素

- `staqtapp_tds.studio_pyqt5.export_integrity_workflow`
- `StudioExportIntegrityWorkflow`
- `StudioExportIntegrityWorkflowState`
- `StudioExportIntegrityCheckpoint`
- `StudioExportIntegrityCheckpointStatus`
- `StudioExportIntegrityManifestComparison`
- `StudioExportIntegrityReviewGate`
- `StudioExportIntegrityWorkflowStatus`
- manifest hash recomputation
- packet hash recomputation
- expected manifest/hash comparison
- progressive export checkpoint rows
- review-safe export handoff gate
- deterministic export workflow hash
- bridge/runtime constructors for the workflow

## v3.1.17 の追加要素

- `staqtapp_tds.drivers.performance`
- `DriverVMPerformanceHarness`
- `DriverVMPerformancePolicy`
- `DriverVMPerformanceReport`
- `DriverVMPerformanceRun`
- `DriverVMPerformanceSummary`
- `DriverVMPerformanceComparison`
- `DriverVMPerformanceStatus`
- `DriverVMPerformanceBackend`
- `driver_vm_performance_capability_matrix()`
- `driver_vm_performance_enabled()`
- direct Python VM benchmark evidence
- optional Runtime Manager overhead comparison
- optional native C backend parity slot
- deterministic result hash comparison
- records/sec、emitted/sec、cost/sec metrics
- performance evidence hash
- future native C conversion target documentation

## 権限境界

Performance Harness は evidence を生成します。trust authority ではありません。

approve、reject、quarantine、sign、activate、Registry mutation、storage write、private key storage、Runtime Manager / Foundry / Review Board / Registry policy bypass は行いません。

## Core rule

```text
Performance Harness measures execution.
Runtime Manager gates execution.
Registry owns trust.
Studio explains evidence.
```


### v3.1.20 Driver Studio Export Integrity Workflow

Driver Studio に Export Integrity Workflow を追加しました。Export / Audit packet preview を review/export handoff 前に検証し、deterministic manifest hash と packet hash を再計算し、任意の expected hash または manifest field と比較し、checklist item を checkpoint row に変換します。Studio は verify/explanation layer のままで、Registry trust authority は持ちません。

### v3.1.18 Driver Studio Manual Builder UI Runtime

Driver Studio の Manual Builder に GUI 対応の UI Runtime を追加しました。フォーム入力を正規化し、決定的な TDDL プレビューを生成し、明示的な提案のみを Driver Foundry にルーティングします。さらに Builder、Evidence、Timeline、Risk Intelligence、Review Workflow の連携情報と、フォント可読性・テキストはみ出し・コンポーネント重なり・スクロール可能なプレビュー面を確認する静的 PyQt5 ビジュアル品質レビューを追加しました。Studio は引き続き Registry の信頼権限を持ちません。
---

## 将来方向: TDS-C 6G Evidence Fabric

Staqtapp-TDS の長期的な native track は **TDS-C** です。これは単なる C への移植ではなく、また 6G network stack そのものでもありません。AI 対応の将来型通信システムに向けた、決定的な C-native evidence substrate です。

想定する方向性は次の通りです。

```text
RAN / Core / Edge / AI workloads
        │
        │ tiny events, counters, traces, snapshots
        ▼
TDS-C evidence fabric
        │
        ├── immutable telemetry storage
        ├── bounded diagnostic event rings
        ├── replay and failure reconstruction
        ├── model / policy audit history
        ├── anomaly and trust scoring evidence
        ├── slice / QoS / energy / sensing evidence
        └── safe observer bridges to Python, Studio, browser, and AI tooling
```

この方向性は現在の TDS authority model と一貫しています。storage は主権を持ち、hot path は小さな events/counters のみを出し、diagnostics はコピーされた evidence を消費し、policy intelligence は gate され、Studio は trust authority にならず observe、explain、verify、prepare intent に徹します。

将来の AI-native 6G-style systems において、TDS-C は RAN、core、edge、sensing、policy、security、model-decision 領域にまたがる分散 network evidence の **black-box recorder、audit spine、replay engine、trust memory** になることを目指します。

設計基準は意図的に厳格です。

- C-native semantics は実装前に specification として固定する。
- Python は engine ではなく client/observer になる。
- hot path では hidden allocation、blocking telemetry writes、diagnostic lock ownership を避ける。
- すべての operation は明示的で evidence-bearing な result state を返す。
- replay、policy audit、crash recovery、ABI stability、fuzzing、sanitizer-clean builds、long-duration stress testing を core requirements として扱う。

現在の TDS は deterministic storage、telemetry、trust-aware Studio の基盤です。TDS-C は AI 対応、cloudified、zero-trust、sensing-aware な 6G storage intelligence に向けた将来の native evidence fabric direction です。

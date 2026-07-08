# 🟦🟪🟧 Staqtapp-TDS v3.1.25

[English README](README.md) · [API Surface Reference PDF](tds_api_docs/Staqtapp_TDS_v3_1_25_API_Surface_Reference.pdf)

<p align="center">
  <img src="docs/screenshots/tds_browser_telemetry_overview_1280x800.png" alt="Staqtapp-TDS Browser telemetry dashboard overview" width="100%">
</p>

<p align="center"><em>Browser Operations Console — 1280×800 で取得した telemetry page 全体の overview。</em></p>

## v3.1.25 Browser & Studio Visual Consistency Hardening

TDS v3.1.25 では、次の persistence / edit-safety reliability layer に進む前に、Browser dashboard と optional PyQt5 Driver Studio shell の visual consistency を強化しました。

Browser stylesheet では、sidebar の control-plane card を通常 flow に戻し、長い navigation list に独立した scroll region を与え、後続 CSS override 後にも compact desktop breakpoint が効くようにし、workload card の width pressure、architecture connector rail、hero-orbit の overhang risk を抑えました。これにより 1560×960、1440×900、1280×800 の screenshot size で panel overlap / text overhang / unfitted resizing risk を減らします。

Studio PyQt5 shell は observe-only authority model を維持しながら、1280×800 minimum、dock nesting/tabbing、panel minimum、group-box/help-label styling、bounded scroll area、text-edit padding、Manual Builder split sizing を改善しました。


## v3.1.23 Driver Studio Stress Scenario Matrix

TDS v3.1.23 では、v3.1.22 の operational stress harness を拡張し、Browser、Studio、Manual Builder、`.tds` persistence、combined observation、authority-denial の各 stress path を named scenario として実行できる deterministic scenario matrix を追加しました。

この scenario matrix は host operation を停止せず、`StudioOperationalStressScenarioMatrix` として evidence を返します。各 stress path を個別に検証でき、同時に Browser + Studio + `.tds` の combined proof path も保持します。

## v3.1.22 Driver Studio Operational Stress Harness

TDS v3.1.22 では、完成済みの Driver Studio runtime と Browser-style observer path のために、headless operational stress harness を追加しました。Browser snapshot polling、bounded Studio live-event overflow、Manual Builder の JSON/signal payload safety、`.tds` atomic persistence reader check を、Studio / Browser の authority を広げずに検証します。

この harness は host operation を停止せず、`StudioOperationalStressReport` として evidence を返します。event overflow は、drop count、warning、current immutable snapshot からの recovery が明示される限り、正常な pressure condition として扱います。

## v3.1.21 Driver Studio Runtime Hardening

TDS v3.1.21 では、v3.1.20 の Export Integrity Workflow 完了後の optional Driver Studio runtime を強化しました。bounded live-event stream の drop accounting、retained cursor floor、GUI polling が遅れた場合の retention-gap warning、Manual Builder signal payload の JSON-safe normalization、runtime hardening test を追加しています。

これは Studio cockpit runtime の信頼性を高めるための release です。Studio は引き続き observe、hydrate、explain、verify、intent preparation のみを行います。approve、reject、quarantine、sign、activate、Registry mutation、trusted driver execution、storage write、private key storage、Runtime Manager / Foundry / Review Board / Registry policy bypass は行いません。

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
393 passed, 11 skipped
release check passed
```

## v3.1.23 の追加要素

- `StudioOperationalStressScenario`
- `StudioOperationalStressScenarioResult`
- `StudioOperationalStressScenarioMatrix`
- `DEFAULT_OPERATIONAL_STRESS_SCENARIOS`
- `StudioOperationalStressHarness.run_scenario(...)`
- `StudioOperationalStressHarness.run_scenario_matrix(...)`
- named Browser polling stress scenario
- named Studio live-event overflow stress scenario
- named Manual Builder payload stress scenario
- named `.tds` persistence atomicity stress scenario
- combined Browser + Studio + `.tds` observation stress scenario
- explicit authority-boundary denial scenario
- JSON/signal-safe scenario matrix payload
- `tds_api_docs/` 以下の更新済み API reference PDF
- README / README_ja の相互リンクと API PDF リンク

## v3.1.22 の追加要素

- `staqtapp_tds.studio_pyqt5.operational_stress`
- `StudioOperationalStressHarness`
- `StudioOperationalStressReport`
- `StudioOperationalStressObservation`
- `StudioOperationalStressStatus`
- `studio_operational_stress_capability_matrix()`
- Browser-style `AdminControl.status()` polling stress
- bounded Studio live-event overflow stress
- Manual Builder JSON/signal payload stress
- `.tds` atomic persistence reader/writer stress
- `tds_api_docs/` 以下の API reference PDF
- README / README_ja の相互リンクと API PDF リンク
- すべての stress surface での authority-boundary preservation

## v3.1.21 の追加要素

- bounded live-event stream drop accounting
- retained cursor floor reporting
- dropped event count reporting
- runtime retention-gap warnings
- JSON/signal-safe Manual Builder form payload normalization
- bridge/runtime/manual-builder factory cleanup
- focused Driver Studio runtime hardening tests
- Studio runtime authority-boundary preservation

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

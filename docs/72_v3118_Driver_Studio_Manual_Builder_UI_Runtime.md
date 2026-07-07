# v3.1.18 Driver Studio Manual Builder UI Runtime

v3.1.18 promotes the Manual Driver Builder from schema and backend routing into a GUI-ready Driver Studio runtime surface.

The Manual Builder UI Runtime remains proposal-only. It normalizes human form fields, renders deterministic TDDL preview source, routes explicit proposal actions through Driver Foundry, and publishes joined interaction state for Evidence, Timeline, Risk, and Review surfaces. It does not approve, reject, quarantine, sign, activate, mutate Registry state, execute trusted drivers, write storage, store private keys, or bypass Runtime Manager / Foundry / Review Board / Registry policy.

## Added surfaces

- `staqtapp_tds.studio_pyqt5.manual_builder_runtime`
- `StudioManualBuilderUIRuntime`
- `StudioManualBuilderRuntimeState`
- `StudioManualBuilderRuntimeStatus`
- `StudioManualBuilderRuntimeStep`
- `StudioManualBuilderJoin`
- `StudioQtVisualQualityReport`
- `StudioQtVisualQualityRule`
- `studio_manual_builder_ui_runtime_capability_matrix()`
- `studio_qt_visual_quality_review()`
- `studio_qt_visual_quality_capability_matrix()`

## Interaction flow

```text
Manual Builder Form
→ deterministic TDDL preview
→ Driver Foundry validation / compile / audit / optional fixture replay
→ evidence context
→ Evidence Timeline / Risk Intelligence / Review Workflow context
→ StudioReviewActionRequest intent path
→ Runtime Manager / Review Board / Registry authority path
```

## Visual-quality review

v3.1.18 also adds a static, headless PyQt5 app quality review so CI can check visual intent without requiring PyQt5:

- readable minimum font policy
- body/title/summary/monospace font sizing
- form label length overhang risk
- help-text wrapping risk
- scrollable source preview contract
- splitter/scroll layout overlap contract
- Builder → Preview → Evidence → Risk → Review join contract

The actual PyQt5 shell also receives safer readability defaults: larger minimum window sizing, word-wrapped summaries, scrollable source/body panes, and minimum component sizing for form controls.

## Authority boundary

The runtime is still not a trust authority. It can preview and route proposals to Foundry. Approval, rejection, quarantine, signing, activation, Registry mutation, and trusted execution remain outside Studio.

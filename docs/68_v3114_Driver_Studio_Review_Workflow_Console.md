# v3.1.14 Driver Studio Review Workflow Console

v3.1.14 adds a pure-Python Review Workflow Console for the optional Driver Studio PyQt5 cockpit. It sits above the v3.1.11 hydration layer and v3.1.13 live panel runtime, shaping review state into readiness cards, action eligibility, rationale templates, and review history.

## Purpose

The Review Workflow Console is a decision-support layer. It helps a human reviewer understand what actions are available and why, then builds bounded `StudioReviewActionRequest` objects for the existing Studio action layer.

It does not become a trust authority.

```text
Hydrated cockpit state
   ↓
Review Workflow Console
   ↓
readiness / eligibility / templates / history
   ↓
StudioReviewActionRequest
   ↓
Studio action layer
   ↓
Review Board / Runtime Manager / Registry authority path
```

## Added module

```text
staqtapp_tds/studio_pyqt5/review_workflow.py
```

## Main types

```text
StudioReviewWorkflowConsole
StudioReviewWorkflowConsoleState
StudioReviewWorkflowItem
StudioReviewActionEligibility
StudioReviewRationaleTemplate
StudioReviewHistoryEntry
StudioReviewWorkflowStatus
```

## Convenience helpers

```text
studio_review_rationale_templates()
studio_review_workflow_capability_matrix()
```

## Bridge/runtime additions

```text
StudioQtBridge.review_workflow_console(max_events=256)
StudioLivePanelRuntime.review_workflow_console()
```

## Workflow surfaces

The console provides GUI-ready payloads for:

- selected-driver readiness
- readiness score
- recommended action
- blockers and warnings
- approve / hold / reject / quarantine eligibility
- rationale template selection
- review-relevant event history
- Qt signal payloads

## Authority boundary

The console may:

- render review readiness
- render action eligibility
- render rationale templates
- render review history
- build `StudioReviewActionRequest`
- delegate review intent to the existing runtime/action layer

The console must not:

- approve drivers directly
- reject drivers directly
- quarantine drivers directly
- call Registry approval directly
- sign drivers
- activate drivers
- run trusted drivers
- write storage
- mutate Registry state
- store private keys
- bypass policy

## Why this matters for the export path

Export capability should not arrive as a raw button. The Studio first needs strong review and evidence semantics so that any future export/audit console can explain what was reviewed, what was eligible, what rationale was used, what evidence was shown, and which authority path owned the final trust decision.

# v3.1.11 Driver Studio Hydrated Cockpit Panels

v3.1.11 turns the optional PyQt5 Driver Studio shell into a richer cockpit-ready
view-model layer.  The new hydration adapter converts immutable Studio snapshots
into concrete GUI surfaces: table columns, cards, timelines, review-action
button descriptors, and Manual Driver Builder form schemas.

The feature remains GUI-focused and authority-neutral. Studio can render,
explain, preview, and submit intent, but it still cannot approve, sign,
activate, execute trusted drivers, mutate Registry state, write storage, or hold
private keys.

## New module

```text
staqtapp_tds/studio_pyqt5/hydration.py
```

Primary classes:

```text
StudioCockpitHydrator
StudioHydratedCockpitState
StudioHydratedPanel
StudioTableColumn
StudioPanelCard
StudioTimelineItem
StudioPanelActionDescriptor
StudioFormField
```

Primary helpers:

```text
manual_builder_form_schema()
studio_cockpit_hydration_capability_matrix()
```

## Bridge additions

`StudioQtBridge` now exposes:

```python
bridge.hydrated_shell_state()
bridge.hydrate_panel(kind)
bridge.manual_builder_form_schema()
```

These methods are pure-Python and import-safe without PyQt5. They let a real Qt
window render meaningful cockpit widgets without embedding trust authority in the
UI layer.

## Hydrated panel surfaces

The existing Studio panels are now hydrated as GUI-ready models:

```text
Driver Evidence Queue        -> table columns + review-intent actions
Evidence Bundle Viewer       -> hash-bound evidence card
Audit Trail Panel            -> audit table model
Fixture Replay Summary       -> fixture table model
Risk Card Inspector          -> risk cards + review-intent actions
Registry State Observer      -> observe-only registry state card/table
Export Integrity Verifier    -> integrity card with verified/mismatch badge
Manual Driver Builder        -> bounded form schema + proposal-only card
Bottom Event Console         -> timeline stream
```

## Review action descriptors

Hydration may render action descriptors such as:

```text
Request Approve
Request Hold
Request Reject
Request Quarantine
```

These are button descriptors only. They do not perform authority actions. A GUI
must route them through:

```text
StudioQtBridge.build_action_request()
StudioQtBridge.submit_review_action()
```

The resulting submission still passes through the v3.1.8 Studio admin action
layer and existing Review Board / Runtime Manager / Registry authority path.

## Manual builder form schema

`manual_builder_form_schema()` exposes stable fields for a future real Qt form:

```text
driver_id
description
driver_version
kind
safety
scan_scope
recursive
scan_limit
max_depth
timeout_ms
match_field
match_eq
semantic_query
semantic_threshold
emit_mode
emit_limit
```

The schema includes bounds and option sets so the GUI can fail closed before
creating a manual proposal task. The generated task still routes through
`DriverFoundry` and remains a proposal, not a trusted active driver.

## Authority boundary

Hydration may:

```text
hydrate panel view-models
render table columns
render card surfaces
render timeline streams
render review-action descriptors
render manual-builder form schemas
```

Hydration must not:

```text
approve drivers
call Registry approval
sign drivers
attach signatures
activate drivers
run the Driver VM as authority
write storage
execute Python
mutate Registry state
store private keys
bypass policy
```

## Test coverage

v3.1.11 adds tests for:

```text
hydration capability matrix
empty cockpit hydration
loaded bundle hydration
table/card/timeline surfaces
safe review-action descriptors
manual-builder form schema bounds
continued PyQt5 optional import safety
```
